//! Restored playable two-player GUI model. No window/HTTP/token ownership.
use eloi_core::{
    PieceKind, Player, Square8, Variant,
    game::Game,
    position::{Piece, initial_fen},
    rules::{Move8, MoveKind, opponent},
};
use eloi_engine::{
    search::{self, SearchLimits},
    time,
    worker::DonorWorker,
};
use std::{
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    thread::JoinHandle,
    time::{Duration, Instant},
};

pub(crate) const VARIANTS: [Variant; 7] = [
    Variant::Standard,
    Variant::Chess960,
    Variant::Horde,
    Variant::KingOfTheHill,
    Variant::Atomic,
    Variant::Antichess,
    Variant::Crazyhouse,
];
pub(crate) const PROMOTIONS: [PieceKind; 5] = [
    PieceKind::Queen,
    PieceKind::Rook,
    PieceKind::Bishop,
    PieceKind::Knight,
    PieceKind::King,
];
pub(crate) fn side(p: Player) -> usize {
    usize::from(p == Player::Black)
}
pub(crate) fn variant_name(v: Variant) -> &'static str {
    match v {
        Variant::Standard => "Standard",
        Variant::Chess960 => "Chess960",
        Variant::Horde => "Horde",
        Variant::KingOfTheHill => "King of the Hill",
        Variant::Atomic => "Atomic",
        Variant::Antichess => "Antichess",
        Variant::Crazyhouse => "Crazyhouse",
        Variant::FourPlayer => "Teams",
    }
}

#[derive(Clone)]
pub(crate) struct Setup {
    pub variant: Variant,
    pub caissa: bool,
    pub human: Player,
    pub minutes: u32,
    pub increment: u32,
    pub chess960: u16,
}
impl Default for Setup {
    fn default() -> Self {
        Self {
            variant: Variant::Standard,
            caissa: true,
            human: Player::White,
            minutes: 5,
            increment: 0,
            chess960: 518,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub(crate) struct SearchInfo {
    pub depth: u16,
    pub depth_reported: bool,
    pub score_known: bool,
    pub score: i32,
    pub mate: Option<i32>,
    pub nodes: u64,
    pub elapsed: Duration,
    pub pv: Vec<Move8>,
    pub route: String,
    pub emergency: bool,
    pub stop_reason: String,
    pub mover: Option<Player>,
    pub root_fen: String,
}

pub(crate) struct Animation {
    pub mv: Move8,
    pub piece: Piece,
    pub rook: Option<(Square8, Square8, Piece)>,
    pub started: Instant,
}
impl Animation {
    pub fn fraction(&self) -> f32 {
        (self.started.elapsed().as_secs_f32() / 0.18).min(1.0)
    }
}

struct Answer {
    generation: u64,
    root: String,
    best: Option<Move8>,
    info: SearchInfo,
    donor: Option<DonorWorker>,
    error: Option<String>,
    analysis: bool,
}
struct Worker {
    stop: Arc<AtomicBool>,
    handle: JoinHandle<()>,
    receiver: mpsc::Receiver<Answer>,
}

pub(crate) struct ChessTable {
    pub game: Game,
    pub human: Player,
    pub flipped: bool,
    pub selected: Option<Square8>,
    pub paused: bool,
    pub message: String,
    pub clocks: [u64; 2],
    pub settings: Setup,
    pub setup: Option<Setup>,
    pub setup_was_paused: bool,
    pub promotion: Vec<Move8>,
    pub drop_piece: Option<PieceKind>,
    pub info: SearchInfo,
    pub animation: Option<Animation>,
    pub displayed_eval: f32,
    pub depth: u8,
    pub finished: Option<String>,
    pub analysis_open: bool,
    analysis_requested: bool,
    last_tick: Instant,
    generation: u64,
    worker: Option<Worker>,
    donor: Option<DonorWorker>,
    donor_path: Option<PathBuf>,
    clock_history: Vec<[u64; 2]>,
}

impl ChessTable {
    pub fn new(path: Option<PathBuf>) -> Self {
        Self {
            game: Game::from_fen(initial_fen(Variant::Standard), Variant::Standard).unwrap(),
            human: Player::White,
            flipped: false,
            selected: None,
            paused: false,
            message: "Your turn · select a piece and a legal target".into(),
            clocks: [300_000; 2],
            settings: Setup::default(),
            setup: None,
            setup_was_paused: false,
            promotion: Vec::new(),
            drop_piece: None,
            info: SearchInfo::default(),
            animation: None,
            displayed_eval: 0.5,
            depth: 0,
            finished: None,
            analysis_open: false,
            analysis_requested: false,
            last_tick: Instant::now(),
            generation: 0,
            worker: None,
            donor: None,
            donor_path: path,
            clock_history: Vec::new(),
        }
    }
    pub fn busy(&self) -> bool {
        self.worker.is_some()
    }
    pub fn cancel(&mut self) {
        self.generation = self.generation.wrapping_add(1);
        if let Some(worker) = &self.worker {
            worker.stop.store(true, Ordering::Relaxed);
        }
    }
    pub fn suspend(&mut self) {
        self.cancel();
        self.paused = true;
        self.selected = None;
        self.promotion.clear();
        self.drop_piece = None;
        self.analysis_requested = false;
        self.last_tick = Instant::now();
        self.message = "Paused while switching views · Resume to continue".into();
    }
    pub fn outcome(&self) -> Option<String> {
        if let Some(result) = &self.finished {
            return Some(result.clone());
        }
        if let Some(winner) = self.game.position().winner() {
            return Some(format!("{winner:?} wins"));
        }
        self.game.drawn().then(|| "Draw".into())
    }
    pub fn route(&self) -> &'static str {
        if self.settings.variant == Variant::Standard && self.settings.caissa {
            "Caissa 2.0 · isolated"
        } else {
            match self.settings.variant {
                Variant::Horde => "Eloi · Horde material",
                Variant::KingOfTheHill => "Eloi E4-KOTH",
                Variant::Atomic => "Eloi E4-Atomic",
                Variant::Crazyhouse => "Eloi · pocket-aware Crazyhouse",
                _ => "Eloi E4-10",
            }
        }
    }
    pub fn charge(&mut self, elapsed: Duration) {
        if self.paused || self.setup.is_some() || self.outcome().is_some() {
            return;
        }
        let mover = self.game.position().turn;
        let i = side(mover);
        self.clocks[i] =
            self.clocks[i].saturating_sub(u64::try_from(elapsed.as_millis()).unwrap_or(u64::MAX));
        if self.clocks[i] == 0 {
            self.promotion.clear();
            self.drop_piece = None;
            self.selected = None;
            self.finished = Some(format!("{:?} wins on time", opponent(mover)));
            self.cancel();
        }
    }
    pub fn tick(&mut self, active: bool) -> bool {
        let elapsed = self.last_tick.elapsed();
        self.last_tick = Instant::now();
        if active {
            self.charge(elapsed);
        }
        let mut changed = false;
        let target = self
            .white_score()
            .map_or(0.5, |cp| (0.5 + cp as f32 / 1600.0).clamp(0.03, 0.97));
        let next = self.displayed_eval + (target - self.displayed_eval) * 0.18;
        if (next - self.displayed_eval).abs() > 0.001 {
            self.displayed_eval = next;
            changed = true;
        }
        let ready = self.worker.as_ref().map(|w| w.receiver.try_recv());
        if let Some(Ok(answer)) = ready {
            if let Some(worker) = self.worker.take() {
                let _ = worker.handle.join();
            }
            self.donor = if answer.generation == self.generation {
                answer.donor
            } else {
                None
            };
            let valid = active
                && answer.generation == self.generation
                && answer.root == self.game.position().to_fen()
                && (!self.paused || answer.analysis && self.analysis_open)
                && self.setup.is_none()
                && self.outcome().is_none();
            if valid {
                self.info = answer.info;
                if let Some(error) = answer.error {
                    self.message = error;
                    self.paused = true;
                } else if answer.analysis {
                    self.message = "Analysis complete · no move played".into();
                } else if let Some(best) = answer.best {
                    if !self.commit(best) {
                        self.message = "Rejected illegal engine move; paused".into();
                        self.paused = true;
                    }
                }
            }
            changed = true;
        } else if let Some(Err(mpsc::TryRecvError::Disconnected)) = ready {
            if let Some(worker) = self.worker.take() {
                let _ = worker.handle.join();
            }
            self.message = "Engine worker stopped; game paused".into();
            self.paused = true;
            changed = true;
        }
        if self.animation.as_ref().is_some_and(|a| a.fraction() >= 1.0) {
            self.animation = None;
            changed = true;
        }
        if self.animation.is_some() {
            changed = true;
        }
        if active
            && self.analysis_open
            && self.analysis_requested
            && !self.busy()
            && self.outcome().is_none()
        {
            self.analysis_requested = false;
            self.start_search(true);
            changed = true;
        }
        if active
            && !self.paused
            && self.setup.is_none()
            && self.promotion.is_empty()
            && self.animation.is_none()
            && self.outcome().is_none()
            && self.game.position().turn != self.human
            && !self.busy()
        {
            self.start_search(false);
            changed = true;
        }
        changed
    }
    fn start_search(&mut self, analysis: bool) {
        self.generation = self.generation.wrapping_add(1);
        let generation = self.generation;
        let game = self.game.clone();
        let root = game.position().to_fen();
        let path = self.donor_path.clone();
        let mut donor = self.donor.take();
        let caissa = self.settings.caissa && self.settings.variant == Variant::Standard;
        let remaining = self.clocks[side(game.position().turn)];
        let planned = time::plan(
            game.position(),
            u32::try_from(remaining).unwrap_or(u32::MAX),
            self.settings.increment * 1000,
            0,
            100,
        );
        let budget = planned.hard_ms.min(remaining.saturating_sub(20)).max(1);
        let depth = self.depth;
        let route = self.route().to_string();
        let stop = Arc::new(AtomicBool::new(false));
        let signal = Arc::clone(&stop);
        let (tx, receiver) = mpsc::channel();
        let handle = std::thread::spawn(move || {
            let started = Instant::now();
            let mut info = SearchInfo {
                route,
                mover: Some(game.position().turn),
                root_fen: root.clone(),
                ..Default::default()
            };
            let mut best = None;
            let mut error = None;
            if caissa {
                let result = (|| {
                    if donor.is_none() {
                        donor = Some(DonorWorker::start(path.as_deref().ok_or_else(|| {
                            std::io::Error::other("Caissa 2.0 worker unavailable")
                        })?)?);
                    }
                    donor.as_mut().unwrap().search_with_depth(
                        &game,
                        Duration::from_millis(budget),
                        (depth > 0).then_some(depth),
                        &signal,
                    )
                })();
                match result {
                    Ok(r) => {
                        info.route = "Caissa 2.0 · SHA-256 verified".into();
                        best = Some(r.best_move);
                        info.depth = r.depth;
                        info.depth_reported = r.depth > 0;
                        info.score_known = r.score_cp.is_some() || r.mate.is_some();
                        info.score = r.score_cp.unwrap_or(0);
                        info.mate = r.mate;
                        info.nodes = r.nodes;
                        info.elapsed = r.elapsed;
                        info.pv = r.pv;
                        // Missing UCI info is unknown telemetry, not a native
                        // depth-zero fallback. Never invent the requested depth.
                        info.emergency = false;
                        info.stop_reason = if r.externally_stopped {
                            "external stop"
                        } else {
                            "donor budget"
                        }
                        .into();
                    }
                    Err(e) => {
                        donor = None;
                        info.route = format!("Eloi fallback · {e}");
                    }
                }
            }
            if best.is_none() && !signal.load(Ordering::Relaxed) {
                let fresh = budget.saturating_sub(
                    u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX),
                );
                if fresh == 0 {
                    error = Some(
                        "Search budget expired; paused instead of playing a superficial fallback"
                            .into(),
                    );
                } else {
                    match search::search(
                        &game,
                        SearchLimits {
                            movetime: Duration::from_millis(fresh),
                            soft_time: (depth == 0)
                                .then(|| Duration::from_millis(planned.soft_ms.min(fresh))),
                            depth: if depth == 0 { 40 } else { depth },
                            nodes: None,
                            hash_mb: 32,
                            noise_millipawns: 0,
                        },
                        &signal,
                        |_| {},
                    ) {
                        Ok(r) => {
                            best = r.best_move;
                            info.depth = u16::from(r.depth);
                            info.depth_reported = r.depth > 0;
                            info.score_known = !r.emergency;
                            info.score = r.score;
                            info.nodes = r.nodes;
                            info.elapsed = r.elapsed;
                            info.pv = r.pv;
                            info.emergency = r.emergency;
                            info.stop_reason = format!("{:?}", r.stop_reason);
                        }
                        Err(e) => error = Some(e.into()),
                    }
                }
            }
            if info.emergency && remaining > 100 && !signal.load(Ordering::Relaxed) {
                error = Some(
                    "No completed iteration; paused without submitting a depth-zero move".into(),
                );
                best = None;
            }
            let _ = tx.send(Answer {
                generation,
                root,
                best,
                info,
                donor,
                error,
                analysis,
            });
        });
        self.worker = Some(Worker {
            stop,
            handle,
            receiver,
        });
        self.message = format!("{} thinking · three search threads", self.route());
    }
    pub fn commit(&mut self, mv: Move8) -> bool {
        if self.outcome().is_some() {
            return false;
        }
        let before = self.game.position();
        if !before.legal_moves().contains(&mv) {
            return false;
        }
        let piece = mv
            .from
            .and_then(|s| before.at(s))
            .or_else(|| match mv.kind {
                MoveKind::Drop(kind) => Some(Piece {
                    owner: before.turn,
                    kind,
                    promoted: false,
                }),
                _ => None,
            });
        let rook = if let MoveKind::Castle { rook_from, rook_to } = mv.kind {
            before.at(rook_from).map(|p| (rook_from, rook_to, p))
        } else {
            None
        };
        let mover = before.turn;
        let clocks = self.clocks;
        if !self.game.push(mv) {
            return false;
        }
        self.clock_history.push(clocks);
        self.clocks[side(mover)] =
            self.clocks[side(mover)].saturating_add(u64::from(self.settings.increment) * 1000);
        self.animation = piece.map(|piece| Animation {
            mv,
            piece,
            rook,
            started: Instant::now(),
        });
        self.selected = None;
        self.drop_piece = None;
        self.analysis_open = false;
        self.analysis_requested = false;
        self.promotion.clear();
        self.message = format!(
            "{:?}: {}",
            mover,
            mv.uci(self.settings.variant == Variant::Chess960)
        );
        if mover != self.human && self.info.route.starts_with("Eloi fallback") {
            self.message.push_str(" · ELOI FALLBACK");
        }
        if mover != self.human && self.info.emergency {
            self.message.push_str(" · EMERGENCY LEGAL MOVE");
        }
        if let Some(outcome) = self.outcome() {
            self.message = outcome;
        }
        true
    }
    pub fn click(&mut self, square: Square8) {
        if self.paused
            || self.setup.is_some()
            || self.analysis_open
            || !self.promotion.is_empty()
            || self.busy()
            || self.game.position().turn != self.human
            || self.outcome().is_some()
        {
            return;
        }
        let legal = self.game.position().legal_moves();
        if let Some(kind) = self.drop_piece {
            if let Some(mv) = legal
                .iter()
                .find(|m| m.kind == MoveKind::Drop(kind) && m.to == square)
            {
                self.commit(*mv);
            } else if self
                .game
                .position()
                .at(square)
                .is_some_and(|p| p.owner == self.human)
            {
                self.drop_piece = None;
                self.selected = Some(square);
            }
            return;
        }
        if let Some(from) = self.selected.take() {
            let choices: Vec<_> = legal
                .iter()
                .copied()
                .filter(|m| m.from == Some(from) && m.to == square)
                .collect();
            if choices.len() > 1 && choices.iter().any(|m| m.promotion.is_some()) {
                self.promotion = choices;
                return;
            }
            if let Some(mv) = choices.first() {
                self.commit(*mv);
                return;
            }
        }
        if self
            .game
            .position()
            .at(square)
            .is_some_and(|p| p.owner == self.human)
        {
            self.selected = Some(square);
        }
    }
    pub fn choose_promotion(&mut self, kind: PieceKind) {
        if let Some(mv) = self
            .promotion
            .iter()
            .copied()
            .find(|m| m.promotion == Some(kind))
        {
            self.commit(mv);
        }
    }
    pub fn start_game(&mut self, setup: Setup) {
        self.cancel();
        let fen = if setup.variant == Variant::Chess960 {
            chess960_fen(setup.chess960)
        } else {
            initial_fen(setup.variant).into()
        };
        match Game::from_fen(&fen, setup.variant) {
            Ok(game) => self.game = game,
            Err(e) => {
                self.message = format!("Setup rejected: {e}");
                return;
            }
        }
        self.human = setup.human;
        self.flipped = setup.human == Player::Black;
        self.clocks = [u64::from(setup.minutes) * 60_000; 2];
        self.settings = setup;
        self.setup = None;
        self.paused = false;
        self.selected = None;
        self.clock_history.clear();
        self.info = SearchInfo::default();
        self.displayed_eval = 0.5;
        self.finished = None;
        self.animation = None;
        self.promotion.clear();
        self.drop_piece = None;
        self.analysis_open = false;
        self.analysis_requested = false;
        self.last_tick = Instant::now();
        self.message = "New clocked game · select a piece and a legal target".into();
        // Never reuse donor search histories across games or variant changes.
        self.donor = None;
    }
    pub fn control(&mut self, id: usize) {
        match id {
            0 => {
                self.cancel();
                self.setup_was_paused = self.paused;
                self.paused = true;
                self.setup = Some(self.settings.clone());
            }
            1 => {
                self.cancel();
                self.analysis_open = false;
                self.analysis_requested = false;
                if self.game.pop() {
                    self.clocks = self.clock_history.pop().unwrap_or(self.clocks);
                }
                while self.game.position().turn != self.human && self.game.pop() {
                    self.clocks = self.clock_history.pop().unwrap_or(self.clocks);
                }
                self.finished = None;
                self.animation = None;
                self.selected = None;
                self.promotion.clear();
                self.info = SearchInfo::default();
                self.paused = false;
                self.last_tick = Instant::now();
                self.message = "Undid to your turn".into();
            }
            2 => self.flipped = !self.flipped,
            3 => {
                self.cancel();
                self.human = opponent(self.human);
                self.flipped = self.human == Player::Black;
                self.settings.human = self.human;
            }
            4 => {
                self.cancel();
                self.analysis_open = false;
                self.analysis_requested = false;
                self.paused = !self.paused;
                self.last_tick = Instant::now();
                self.message = if self.paused { "Paused" } else { "Resumed" }.into();
            }
            5 => {
                self.cancel();
                self.analysis_requested = false;
                if self.analysis_open {
                    self.analysis_open = false;
                    self.paused = self.setup_was_paused;
                } else {
                    self.analysis_open = true;
                    self.setup_was_paused = self.paused;
                    self.paused = true;
                }
                self.last_tick = Instant::now();
            }
            80 => {
                if self.analysis_open {
                    self.cancel();
                    self.analysis_requested = true;
                }
            }
            82 => {
                use std::io::Write;
                let result = (|| -> std::io::Result<PathBuf> {
                    let root = std::env::var_os("LOCALAPPDATA")
                        .map(PathBuf::from)
                        .unwrap_or_else(std::env::temp_dir)
                        .join("Eloi")
                        .join("Lab");
                    std::fs::create_dir_all(&root)?;
                    let stamp = std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .unwrap_or_default()
                        .as_nanos();
                    let path = root.join(format!("analysis-{stamp}.md"));
                    std::fs::OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .open(&path)?
                        .write_all(self.diagnostics().as_bytes())?;
                    Ok(path)
                })();
                self.message = match result {
                    Ok(path) => format!("Exported {}", path.display()),
                    Err(e) => format!("Export failed: {e}"),
                };
            }
            6 => {
                self.cancel();
                self.finished = Some(format!("{:?} wins by resignation", opponent(self.human)));
            }
            7 => {
                self.cancel();
                self.depth = self.depth.saturating_sub(1);
            }
            8 => {
                self.cancel();
                self.depth = self.depth.saturating_add(1).min(40);
            }
            20..=24 => {
                if self.settings.variant == Variant::Crazyhouse {
                    let kind = [
                        PieceKind::Pawn,
                        PieceKind::Knight,
                        PieceKind::Bishop,
                        PieceKind::Rook,
                        PieceKind::Queen,
                    ][id - 20];
                    self.drop_piece = if self.drop_piece == Some(kind) {
                        None
                    } else {
                        Some(kind)
                    };
                    self.selected = None;
                }
            }
            30..=34 => self.choose_promotion(PROMOTIONS[id - 30]),
            40 => {
                self.setup = None;
                self.paused = self.setup_was_paused;
                self.last_tick = Instant::now();
            }
            41 => {
                if let Some(setup) = self.setup.clone() {
                    self.start_game(setup);
                }
            }
            _ => {
                if let Some(setup) = &mut self.setup {
                    match id {
                        50 => setup.minutes = setup.minutes.saturating_sub(1).max(1),
                        51 => setup.minutes = (setup.minutes + 1).min(180),
                        52 => setup.increment = setup.increment.saturating_sub(1),
                        53 => setup.increment = (setup.increment + 1).min(60),
                        54 => setup.human = Player::White,
                        55 => setup.human = Player::Black,
                        56 => setup.caissa = setup.variant == Variant::Standard,
                        57 => setup.caissa = false,
                        58 => setup.chess960 = (setup.chess960 + 1) % 960,
                        60..=66 => {
                            setup.variant = VARIANTS[id - 60];
                            if setup.variant != Variant::Standard {
                                setup.caissa = false;
                            }
                        }
                        _ => {}
                    }
                }
            }
        }
    }
    pub fn diagnostics(&self) -> String {
        let depth = if self.info.depth_reported {
            self.info.depth.to_string()
        } else {
            "unreported".into()
        };
        let score = if self.info.score_known {
            self.info.score.to_string()
        } else {
            "unreported".into()
        };
        format!("# Eloi {} — local Engine Lab diagnostics\n\nVariant: {}\nSelected brain: {}\nActual last route: {}\nClocks (ms): W={} B={}\nCompleted depth: {}\nScore (mover-relative cp): {}\nMate: {:?}\nNodes: {}\nElapsed (ms): {}\nStop: {}\nEmergency: {}\nCurrent FEN: `{}`\nLast-search root FEN: `{}`\nLast-search PV: {}\n\nThis is a local analysis report, not a strength qualification or completed version tournament.\n",
            env!("CARGO_PKG_VERSION"),variant_name(self.settings.variant),self.route(),self.info.route,
            self.clocks[0],self.clocks[1],depth,score,self.info.mate,self.info.nodes,self.info.elapsed.as_millis(),
            self.info.stop_reason,self.info.emergency,self.game.position().to_fen(),self.info.root_fen,
            self.info.pv.iter().take(32).map(|m|m.uci(self.settings.variant==Variant::Chess960)).collect::<Vec<_>>().join(" ")).chars().take(16000).collect()
    }
    pub fn white_score(&self) -> Option<i32> {
        if !self.info.score_known {
            return None;
        }
        let cp = self
            .info
            .mate
            .map_or(self.info.score, |m| if m >= 0 { 30_000 } else { -30_000 });
        Some(if self.info.mover == Some(Player::Black) {
            -cp
        } else {
            cp
        })
    }
}
impl Drop for ChessTable {
    fn drop(&mut self) {
        self.cancel();
        if let Some(w) = self.worker.take() {
            let _ = w.handle.join();
        }
    }
}

/// Standard Scharnagl numbering; opposite-color bishops and R-K-R ordering.
pub(crate) fn chess960_fen(index: u16) -> String {
    let mut n = usize::from(index % 960);
    let mut rank = [' '; 8];
    rank[(n % 4) * 2 + 1] = 'B';
    n /= 4;
    rank[(n % 4) * 2] = 'B';
    n /= 4;
    let mut empty: Vec<_> = (0..8).filter(|&i| rank[i] == ' ').collect();
    rank[empty[n % 6]] = 'Q';
    n /= 6;
    empty = (0..8).filter(|&i| rank[i] == ' ').collect();
    let pairs = [
        (0, 1),
        (0, 2),
        (0, 3),
        (0, 4),
        (1, 2),
        (1, 3),
        (1, 4),
        (2, 3),
        (2, 4),
        (3, 4),
    ];
    let (a, b) = pairs[n];
    rank[empty[a]] = 'N';
    rank[empty[b]] = 'N';
    empty = (0..8).filter(|&i| rank[i] == ' ').collect();
    rank[empty[0]] = 'R';
    rank[empty[1]] = 'K';
    rank[empty[2]] = 'R';
    let white: String = rank.iter().collect();
    let black = white.to_ascii_lowercase();
    let right = (b'A' + empty[2] as u8) as char;
    let left = (b'A' + empty[0] as u8) as char;
    format!(
        "{black}/pppppppp/8/8/8/8/PPPPPPPP/{white} w {right}{left}{}{} - 0 1",
        right.to_ascii_lowercase(),
        left.to_ascii_lowercase()
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use eloi_core::position::parse_square;
    #[test]
    fn real_board_input_undo_side_flip_and_pause() {
        let mut t = ChessTable::new(None);
        let initial = t.game.clone();
        t.click(parse_square("e2").unwrap());
        t.click(parse_square("e4").unwrap());
        assert_eq!(
            t.game.moves().count(),
            1,
            "GUI status: {}; report: {:?}",
            t.message,
            t.info
        );
        t.control(1);
        assert_eq!(t.game, initial);
        t.control(2);
        assert!(t.flipped);
        t.control(3);
        assert_eq!(t.human, Player::Black);
        t.control(4);
        assert!(t.paused);
        t.suspend();
        assert!(t.paused);
    }
    #[test]
    fn all_960_starts_are_unique_and_roundtrip() {
        let mut unique = std::collections::HashSet::new();
        for i in 0..960 {
            let f = chess960_fen(i);
            assert!(unique.insert(f.clone()));
            assert!(Game::from_fen(&f, Variant::Chess960).is_ok());
        }
        assert!(chess960_fen(518).contains("RNBQKBNR"));
    }
    #[test]
    fn setup_is_transactional_and_variants_never_choose_caissa() {
        let mut t = ChessTable::new(None);
        let old = t.game.clone();
        t.control(0);
        t.control(62);
        t.control(56);
        assert!(!t.setup.as_ref().unwrap().caissa);
        assert_eq!(t.game, old);
        t.control(40);
        assert_eq!(t.game, old);
        for variant in VARIANTS {
            let setup = Setup {
                variant,
                caissa: variant == Variant::Standard,
                ..Default::default()
            };
            t.start_game(setup);
            assert_eq!(t.game.position().variant, variant);
            if variant != Variant::Standard {
                assert!(!t.route().contains("Caissa"));
            }
        }
    }
    #[test]
    fn clock_increment_pause_timeout_and_terminal_positions() {
        let mut t = ChessTable::new(None);
        t.settings.increment = 2;
        t.clocks = [1000, 1000];
        t.charge(Duration::from_millis(200));
        assert_eq!(t.clocks[0], 800);
        assert!(t.commit(t.game.position().parse_move("e2e4").unwrap()));
        assert_eq!(t.clocks[0], 2800);
        t.paused = true;
        t.charge(Duration::from_secs(10));
        assert_eq!(t.clocks[1], 1000);
        t.paused = false;
        t.charge(Duration::from_secs(2));
        assert!(t.outcome().unwrap().contains("time"));
    }
    #[test]
    fn underpromotion_uses_picker_instead_of_silent_queen() {
        let mut t = ChessTable::new(None);
        t.game = Game::from_fen("7k/P7/8/8/8/8/8/7K w - - 0 1", Variant::Standard).unwrap();
        t.click(parse_square("a7").unwrap());
        t.click(parse_square("a8").unwrap());
        assert_eq!(t.promotion.len(), 4);
        t.choose_promotion(PieceKind::Knight);
        assert_eq!(
            t.game
                .position()
                .at(parse_square("a8").unwrap())
                .unwrap()
                .kind,
            PieceKind::Knight
        );
    }
    #[test]
    fn pocket_selection_can_be_cancelled_and_flag_fall_clears_promotion() {
        let mut t = ChessTable::new(None);
        t.start_game(Setup {
            variant: Variant::Crazyhouse,
            caissa: false,
            ..Default::default()
        });
        t.control(20);
        assert_eq!(t.drop_piece, Some(PieceKind::Pawn));
        t.control(20);
        assert!(t.drop_piece.is_none());
        t.control(21);
        let own = parse_square("e2").unwrap();
        t.click(own);
        assert!(t.drop_piece.is_none());
        assert_eq!(t.selected, Some(own));
        t.start_game(Setup::default());
        t.game = Game::from_fen("7k/P7/8/8/8/8/8/7K w - - 0 1", Variant::Standard).unwrap();
        t.click(parse_square("a7").unwrap());
        t.click(parse_square("a8").unwrap());
        assert_eq!(t.promotion.len(), 4);
        t.clocks[0] = 1;
        t.charge(Duration::from_millis(2));
        assert!(t.promotion.is_empty());
        assert!(t.outcome().unwrap().contains("time"));
    }
    #[test]
    fn native_gui_play_analysis_and_cancellation_do_not_share_game_authority() {
        let mut t = ChessTable::new(None);
        t.settings.caissa = false;
        t.depth = 1;
        t.control(5);
        assert!(t.paused);
        let root = t.game.clone();
        let clocks = t.clocks;
        t.control(80);
        assert!(t.tick(true));
        let end = Instant::now() + Duration::from_secs(5);
        while t.busy() && Instant::now() < end {
            std::thread::sleep(Duration::from_millis(5));
            t.tick(true);
        }
        assert!(!t.busy());
        assert!(t.info.depth >= 1);
        assert_eq!(t.game, root);
        assert_eq!(t.clocks, clocks);
        assert!(t.message.contains("no move played"));
        let report = t.diagnostics();
        assert!(report.contains("FEN:"));
        assert!(!report.contains("Authorization"));
        t.control(5);
        assert!(!t.paused);
        t.human = Player::Black;
        t.tick(true);
        assert!(t.busy());
        t.suspend();
        let end = Instant::now() + Duration::from_secs(5);
        while t.busy() && Instant::now() < end {
            std::thread::sleep(Duration::from_millis(5));
            t.tick(false);
        }
        assert!(!t.busy());
        assert_eq!(t.game, root);
        assert!(t.paused);
    }
    #[test]
    #[ignore = "requires the pinned local Caissa 2.0 fixture"]
    fn actual_gui_standard_uses_verified_caissa_and_depth_ceiling() {
        let path = std::env::var_os("ELOI_TEST_CAISSA20").expect("explicit donor fixture");
        let mut t = ChessTable::new(Some(path.into()));
        t.depth = 1;
        t.human = Player::Black;
        t.tick(true);
        let end = Instant::now() + Duration::from_secs(8);
        while t.busy() && Instant::now() < end {
            std::thread::sleep(Duration::from_millis(5));
            t.tick(true);
        }
        assert!(!t.busy());
        assert_eq!(
            t.game.moves().count(),
            1,
            "GUI status: {}; report: {:?}",
            t.message,
            t.info
        );
        assert!(t.info.depth <= 1);
        assert_eq!(t.info.depth_reported, t.info.depth > 0);
        assert!(!t.info.emergency);
        assert_eq!(t.info.route, "Caissa 2.0 · SHA-256 verified");
        assert!(t.game.position().legal_moves().len() > 0);
    }
}
