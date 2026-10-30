//! Playable Teams model; engine work never blocks the window message loop.
use eloi_core::four_player::{FourMode, FourSeat};
use eloi_core::{PieceKind, Square14};
use eloi_engine::four_player::FourSearchResult;
use eloi_protocol::four_player::{FourPlayerPreset, FourPlayerSession, SeatController};
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
    mpsc,
};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ThinkPhase {
    Idle,
    Thinking,
    Chosen,
    Cancelled,
    Emergency,
}

#[derive(Clone)]
pub(crate) struct SearchProgress {
    pub generation: u64,
    pub root: u64,
    pub seat: FourSeat,
    pub result: FourSearchResult,
}

struct SearchWorker {
    stop: Arc<AtomicBool>,
    handle: JoinHandle<()>,
    receiver: mpsc::Receiver<Result<FourPlayerSession, &'static str>>,
    generation: u64,
    root: u64,
    seat: FourSeat,
}

fn publish_progress(slot: &Mutex<Option<SearchProgress>>, update: SearchProgress) {
    if let Ok(mut latest) = slot.try_lock() {
        *latest = Some(update);
    }
}

pub(crate) struct FourTable {
    pub session: FourPlayerSession,
    pub selected: Option<Square14>,
    pub paused: bool,
    pub message: String,
    pub budget_ms: u64,
    pub promotion: PieceKind,
    pub show_suggestion: bool,
    pub phase: ThinkPhase,
    pub progress: Option<SearchProgress>,
    generation: u64,
    latest: Arc<Mutex<Option<SearchProgress>>>,
    last_tick: Instant,
    worker: Option<SearchWorker>,
}

impl FourTable {
    pub fn new() -> Self {
        Self {
            session: FourPlayerSession::new(
                FourMode::Teams,
                FourPlayerPreset::HumanTeamRedYellow,
                600_000,
                0,
            ),
            selected: None,
            paused: false,
            message: "You control Red + Yellow. Eloi controls Blue + Green.".into(),
            budget_ms: 1000,
            promotion: PieceKind::Queen,
            show_suggestion: false,
            phase: ThinkPhase::Idle,
            progress: None,
            generation: 0,
            latest: Arc::new(Mutex::new(None)),
            worker: None,
            last_tick: Instant::now(),
        }
    }
    pub fn cancel(&mut self) {
        self.generation = self.generation.wrapping_add(1);
        if let Some(worker) = self.worker.take() {
            worker.stop.store(true, Ordering::Relaxed);
            let _ = worker.handle.join();
            self.phase = ThinkPhase::Cancelled;
        }
        if let Ok(mut latest) = self.latest.try_lock() {
            *latest = None;
        }
    }
    pub fn busy(&self) -> bool {
        self.worker.is_some()
    }
    pub fn tick(&mut self) -> bool {
        let elapsed = self.last_tick.elapsed();
        self.last_tick = Instant::now();
        if !self.paused && !self.busy() {
            self.session.charge_turn(elapsed);
        }
        let update = self.latest.try_lock().ok().and_then(|mut slot| slot.take());
        let mut changed = false;
        if let Some(update) = update {
            changed = self.accept_progress(update);
        }
        let ready = self
            .worker
            .as_ref()
            .map(|worker| worker.receiver.try_recv());
        if let Some(Ok(result)) = ready {
            let identity = self.worker.as_ref().map(|w| (w.generation, w.root, w.seat));
            let valid = identity.is_some_and(|(generation, root, _)| {
                generation == self.generation && root == self.session.position().identity_key()
            });
            self.cancel();
            if !valid {
                return true;
            }
            match result {
                Ok(session) => {
                    if let Some(search) = session
                        .last_search()
                        .filter(|_| session.position().identity_key() != identity.unwrap().1)
                    {
                        let (generation, root, seat) = identity.unwrap();
                        self.progress = Some(SearchProgress {
                            generation,
                            root,
                            seat,
                            result: search.clone(),
                        });
                        self.phase = if search.emergency {
                            ThinkPhase::Emergency
                        } else {
                            ThinkPhase::Chosen
                        };
                    } else {
                        self.progress = None;
                        self.phase = ThinkPhase::Idle;
                    }
                    self.session = session;
                    self.message = self.session.last_search().map_or_else(
                        || "Game ended.".into(),
                        |r| {
                            format!(
                                "Eloi: depth {} | score {} cp | {} nodes | {} ms{}",
                                r.depth,
                                r.score,
                                r.nodes,
                                r.elapsed.as_millis(),
                                if r.emergency { " | EMERGENCY" } else { "" }
                            )
                        },
                    );
                }
                Err(e) => {
                    self.paused = true;
                    self.message = e.into();
                }
            }
            return true;
        }
        if let Some(Err(mpsc::TryRecvError::Disconnected)) = ready {
            self.cancel();
            self.paused = true;
            self.message = "Engine worker stopped; game paused.".into();
            return true;
        }
        if self.worker.is_none() && !self.paused && self.session.snapshot().outcome.is_none() {
            let snapshot = self.session.snapshot();
            if snapshot.seats[snapshot.turn.index()].controller == SeatController::Eloi {
                let mut next = self.session.clone();
                let stop = Arc::new(AtomicBool::new(false));
                let signal = Arc::clone(&stop);
                let (tx, rx) = mpsc::channel();
                let budget = self.budget_ms;
                self.generation = self.generation.wrapping_add(1);
                let generation = self.generation;
                let root = next.position().identity_key();
                let seat = snapshot.turn;
                let latest = Arc::clone(&self.latest);
                self.progress = None;
                self.phase = ThinkPhase::Thinking;
                let handle = std::thread::spawn(move || {
                    let result = next
                        .step_engine_once_observed(
                            Duration::from_millis(budget),
                            12,
                            &signal,
                            &mut |result| {
                                // Never let painting or a disconnected view stall search.
                                publish_progress(
                                    &latest,
                                    SearchProgress {
                                        generation,
                                        root,
                                        seat,
                                        result: result.clone(),
                                    },
                                );
                            },
                        )
                        .map(|_| next);
                    let _ = tx.send(result);
                });
                self.worker = Some(SearchWorker {
                    stop,
                    handle,
                    receiver: rx,
                    generation,
                    root,
                    seat,
                });
                self.message = format!("{:?} is thinking...", snapshot.turn);
                return true;
            }
        }
        changed
    }
    fn accept_progress(&mut self, update: SearchProgress) -> bool {
        let valid = self.worker.as_ref().is_some_and(|worker| {
            update.generation == worker.generation
                && update.generation == self.generation
                && update.root == worker.root
                && update.root == self.session.position().identity_key()
                && update.seat == worker.seat
                && update.result.depth > 0
                && !update.result.emergency
                && update.result.best_move.is_some_and(|mv| {
                    update.result.pv.first() == Some(&mv)
                        && self.session.position().legal_moves().contains(&mv)
                })
        });
        if valid {
            self.progress = Some(update);
        }
        valid
    }
    pub fn suggestion(&self) -> Option<eloi_core::four_player::FourMove> {
        if !self.show_suggestion || self.phase != ThinkPhase::Thinking {
            return None;
        }
        let progress = self.progress.as_ref()?;
        if progress.generation != self.generation
            || progress.root != self.session.position().identity_key()
        {
            return None;
        }
        progress.result.best_move
    }
    pub fn think_lines(&self) -> Vec<String> {
        let state = match self.phase {
            ThinkPhase::Idle => "Ready for Eloi's turn",
            ThinkPhase::Thinking if self.progress.is_none() => "Preparing search",
            ThinkPhase::Thinking => "Thinking",
            ThinkPhase::Chosen => "Move chosen - previous search",
            ThinkPhase::Cancelled => "Cancelled - previous search",
            ThinkPhase::Emergency => "Emergency legal move",
        };
        let mut lines = vec![state.to_owned()];
        if let Some(progress) = &self.progress {
            let team = match progress.seat {
                FourSeat::Red | FourSeat::Yellow => "Red + Yellow",
                _ => "Blue + Green",
            };
            lines.push(format!("Searching seat: {:?}", progress.seat));
            lines.push(format!("Positive favors {team}"));
            let r = &progress.result;
            if r.depth == 0 {
                lines.push("No completed iteration".into());
                return lines;
            }
            lines.push(format!("Depth {} | {:+} cp", r.depth, r.score));
            lines.push(format!("{} nodes | {} ms", r.nodes, r.elapsed.as_millis()));
            let mut seat = progress.seat;
            let moves: Vec<_> =
                r.pv.iter()
                    .take(6)
                    .map(|mv| {
                        let text = format!("{seat:?}: {mv}");
                        seat = match seat {
                            FourSeat::Red => FourSeat::Blue,
                            FourSeat::Blue => FourSeat::Yellow,
                            FourSeat::Yellow => FourSeat::Green,
                            FourSeat::Green => FourSeat::Red,
                        };
                        text
                    })
                    .collect();
            for pair in moves.chunks(2) {
                lines.push(pair.join("  "));
            }
        }
        lines
    }
    pub fn click(&mut self, square: Square14) {
        let snapshot = self.session.snapshot();
        if self.busy()
            || self.paused
            || snapshot.outcome.is_some()
            || snapshot.seats[snapshot.turn.index()].controller != SeatController::Human
        {
            return;
        }
        if let Some(from) = self.selected.take() {
            if let Some(mv) = self
                .session
                .position()
                .legal_moves()
                .into_iter()
                .find(|mv| {
                    mv.from == from
                        && mv.to == square
                        && (mv.promotion.is_none() || mv.promotion == Some(self.promotion))
                })
            {
                self.session.push_notation(&mv.notation());
                self.message = format!("Played {mv}");
                return;
            }
        }
        if self
            .session
            .position()
            .at(square)
            .is_some_and(|p| p.owner == snapshot.turn)
        {
            self.selected = Some(square);
        }
    }
    pub fn control(&mut self, index: usize) {
        if index == 8 {
            self.show_suggestion = !self.show_suggestion;
            return;
        }
        self.cancel();
        self.selected = None;
        self.last_tick = Instant::now();
        match index {
            0 => {
                *self = Self::new();
            }
            1 => {
                self.paused = !self.paused;
            }
            2 => {
                self.session.undo();
                while self.session.snapshot().seats[self.session.snapshot().turn.index()].controller
                    != SeatController::Human
                    && self.session.undo()
                {}
                self.paused = false;
            }
            3 => {
                self.session.resign(FourSeat::Red);
            }
            4 => {
                self.session = FourPlayerSession::new(
                    FourMode::Teams,
                    FourPlayerPreset::FourHumanPassAndPlay,
                    600_000,
                    0,
                );
                self.paused = false;
            }
            5 => {
                self.session = FourPlayerSession::new(
                    FourMode::Teams,
                    FourPlayerPreset::AllEngineDemo,
                    600_000,
                    0,
                );
                self.paused = false;
            }
            6 => {
                self.budget_ms = if self.budget_ms == 1000 { 3000 } else { 1000 };
            }
            7 => {
                self.promotion = match self.promotion {
                    PieceKind::Queen => PieceKind::Rook,
                    PieceKind::Rook => PieceKind::Bishop,
                    PieceKind::Bishop => PieceKind::Knight,
                    _ => PieceKind::Queen,
                };
            }
            _ => {}
        }
    }
}
impl Drop for FourTable {
    fn drop(&mut self) {
        self.cancel();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fake_progress(table: &mut FourTable) -> SearchProgress {
        let root = table.session.position().identity_key();
        let seat = table.session.position().turn;
        let mv = table.session.position().legal_moves()[0];
        let (tx, receiver) = mpsc::channel();
        let handle = std::thread::spawn(move || {
            drop(tx);
        });
        table.generation = 42;
        table.phase = ThinkPhase::Thinking;
        table.worker = Some(SearchWorker {
            stop: Arc::new(AtomicBool::new(false)),
            handle,
            receiver,
            generation: 42,
            root,
            seat,
        });
        SearchProgress {
            generation: 42,
            root,
            seat,
            result: FourSearchResult {
                best_move: Some(mv),
                depth: 2,
                score: 25,
                nodes: 99,
                elapsed: Duration::from_millis(10),
                emergency: false,
                pv: vec![mv],
            },
        }
    }
    #[test]
    fn progress_is_bounded_nonblocking_and_latest_only() {
        let mut table = FourTable::new();
        let update = fake_progress(&mut table);
        for i in 0..1000 {
            let mut next = update.clone();
            next.result.nodes = i;
            publish_progress(&table.latest, next);
        }
        assert_eq!(
            table.latest.lock().unwrap().as_ref().unwrap().result.nodes,
            999
        );
        // Contention drops an intermediate update rather than blocking the search.
        let guard = table.latest.lock().unwrap();
        publish_progress(&table.latest, update.clone());
        assert_eq!(guard.as_ref().unwrap().result.nodes, 999);
        drop(guard);
        table.cancel();
        assert!(table.latest.lock().unwrap().is_none());
        assert!(!table.accept_progress(update));
    }
    #[test]
    fn stale_roots_generations_and_depth_zero_never_reach_the_board() {
        let mut table = FourTable::new();
        let update = fake_progress(&mut table);
        assert!(table.accept_progress(update.clone()));
        let state = table.session.snapshot().state;
        table.control(8);
        assert!(table.busy()); // Toggle never cancels or plays a move.
        assert_eq!(table.suggestion(), update.result.best_move);
        assert_eq!(table.session.snapshot().state, state);
        for kind in 0..4 {
            let mut stale = update.clone();
            match kind {
                0 => stale.generation -= 1,
                1 => stale.root ^= 1,
                2 => stale.result.depth = 0,
                _ => stale.result.emergency = true,
            }
            assert!(!table.accept_progress(stale));
        }
        let mv = table.session.position().legal_moves()[0];
        table.session.push_notation(&mv.notation());
        assert!(table.suggestion().is_none());
        assert!(!table.accept_progress(update));
        table.cancel();
        assert_eq!(table.phase, ThinkPhase::Cancelled);
    }
    #[test]
    fn preparing_final_and_emergency_labels_do_not_fabricate_evaluations() {
        let mut table = FourTable::new();
        table.phase = ThinkPhase::Thinking;
        assert_eq!(table.think_lines(), vec!["Preparing search"]);
        let mut update = fake_progress(&mut table);
        assert!(table.accept_progress(update.clone()));
        assert!(table.think_lines()[2].contains("Red + Yellow"));
        table.phase = ThinkPhase::Chosen;
        assert!(table.think_lines()[0].contains("previous search"));
        assert!(table.suggestion().is_none());
        update.result.depth = 0;
        update.result.emergency = true;
        table.progress = Some(update);
        table.phase = ThinkPhase::Emergency;
        let lines = table.think_lines();
        assert!(lines[0].contains("Emergency legal move"));
        assert!(!lines.iter().any(|line| line.contains(" cp")));
    }
    #[test]
    fn controls_invalidate_running_generations_and_both_enemy_seats_are_labelled() {
        for control in 0..8 {
            let mut table = FourTable::new();
            let update = fake_progress(&mut table);
            assert!(table.accept_progress(update.clone()));
            table.control(control);
            assert!(!table.busy());
            assert!(!table.accept_progress(update));
            assert!(table.suggestion().is_none());
        }
        for plies in [1, 3] {
            let mut table = FourTable::new();
            for _ in 0..plies {
                let mv = table.session.position().legal_moves()[0];
                assert!(table.session.push_notation(&mv.notation()));
            }
            let update = fake_progress(&mut table);
            assert!(matches!(update.seat, FourSeat::Blue | FourSeat::Green));
            assert!(table.accept_progress(update));
            assert!(table.think_lines()[2].contains("Blue + Green"));
            table.cancel();
        }
    }
    #[test]
    fn real_worker_delivers_a_visible_live_suggestion_before_playing() {
        let mut table = FourTable::new();
        table.control(5); // All-Eloi demo, exactly the manual smoke path.
        table.control(8);
        table.budget_ms = 1500;
        let root = table.session.position().identity_key();
        assert!(table.show_suggestion);
        assert!(table.tick());
        let deadline = Instant::now() + Duration::from_secs(4);
        let mut visible = false;
        while Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(5));
            table.tick();
            if table.phase == ThinkPhase::Thinking && table.progress.is_some() {
                assert_eq!(table.session.position().identity_key(), root);
                assert!(table.suggestion().is_some());
                visible = true;
                break;
            }
            if table.phase == ThinkPhase::Chosen || table.phase == ThinkPhase::Emergency {
                break;
            }
        }
        table.cancel();
        assert!(visible, "real GUI worker never exposed a live suggestion");
    }
    #[test]
    fn default_controllers_are_complete_opposing_teams() {
        let table = FourTable::new();
        let snapshot = table.session.snapshot();
        assert_eq!(
            snapshot.route,
            eloi_protocol::four_player::FourBrainRoute::HandcraftedTeams
        );
        for seat in [FourSeat::Red, FourSeat::Yellow] {
            assert_eq!(
                snapshot.seats[seat.index()].controller,
                SeatController::Human
            );
            assert!(table.session.position().allied(FourSeat::Red, seat));
        }
        for seat in [FourSeat::Blue, FourSeat::Green] {
            assert_eq!(
                snapshot.seats[seat.index()].controller,
                SeatController::Eloi
            );
            assert!(!table.session.position().allied(FourSeat::Red, seat));
        }
    }
    #[test]
    fn human_move_is_legal_and_undo_restores_turn() {
        let mut table = FourTable::new();
        let initial = table.session.snapshot().state;
        let mv = table.session.position().legal_moves()[0];
        table.click(mv.from);
        table.click(mv.to);
        assert_eq!(table.session.snapshot().turn, FourSeat::Blue);
        table.control(2);
        assert_eq!(table.session.snapshot().state, initial);
    }
}
