//! Playable Teams model; engine work never blocks the window message loop.
use eloi_core::four_player::{FourMode, FourSeat};
use eloi_core::{PieceKind, Square14};
use eloi_protocol::four_player::{FourPlayerPreset, FourPlayerSession, SeatController};
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
    mpsc,
};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

pub(crate) struct FourTable {
    pub session: FourPlayerSession,
    pub selected: Option<Square14>,
    pub paused: bool,
    pub message: String,
    pub budget_ms: u64,
    pub promotion: PieceKind,
    last_tick: Instant,
    worker: Option<(
        Arc<AtomicBool>,
        JoinHandle<()>,
        mpsc::Receiver<Result<FourPlayerSession, &'static str>>,
    )>,
}

impl FourTable {
    pub fn new() -> Self {
        Self {
            session: FourPlayerSession::new(
                FourMode::Teams,
                FourPlayerPreset::OneHumanTeams,
                600_000,
                0,
            ),
            selected: None,
            paused: false,
            message: "You are Red; Yellow is your Eloi teammate.".into(),
            budget_ms: 1000,
            promotion: PieceKind::Queen,
            worker: None,
            last_tick: Instant::now(),
        }
    }
    pub fn cancel(&mut self) {
        if let Some((stop, handle, _)) = self.worker.take() {
            stop.store(true, Ordering::Relaxed);
            let _ = handle.join();
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
        let ready = self.worker.as_ref().map(|(_, _, rx)| rx.try_recv());
        if let Some(Ok(result)) = ready {
            self.cancel();
            match result {
                Ok(session) => {
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
                let handle = std::thread::spawn(move || {
                    let result = next
                        .step_engine_once(Duration::from_millis(budget), 12, &signal)
                        .map(|_| next);
                    let _ = tx.send(result);
                });
                self.worker = Some((stop, handle, rx));
                self.message = format!("{:?} is thinking...", snapshot.turn);
                return true;
            }
        }
        false
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
                while self.session.snapshot().turn != FourSeat::Red && self.session.undo() {}
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
