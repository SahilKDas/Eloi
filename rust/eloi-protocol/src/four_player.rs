//! Transport-neutral four-player messages for local GUI and future adapters.
//!
//! These types are not Chess.com integration. They are Eloi-owned messages that
//! describe local state, clocks, scores, routes and results without coupling the
//! engine to any website-specific protocol.

use eloi_core::PieceKind;
use eloi_core::four_player::{FourGame, FourMode, FourMove, FourOutcome, FourPosition, FourSeat};
use eloi_engine::four_player::{FourSearchLimits, search_four_player};
use std::sync::atomic::AtomicBool;
use std::time::Duration;

/// Who controls a seat in a local four-player game.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SeatController {
    /// Human input in the native GUI.
    Human,
    /// Eloi handcrafted or qualified model route.
    Eloi,
}

/// Stable brain route shown to the GUI and logs.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FourBrainRoute {
    /// Handcrafted Max-N / team alpha-beta baseline.
    HandcraftedBaseline,
    /// Qualified FFA neural policy/value model.
    E4PcFfa,
    /// Qualified Teams neural policy/value model.
    E4PcTeams,
}

/// Per-seat clock information.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SeatClock {
    /// Remaining time in milliseconds.
    pub remaining_ms: u64,
    /// Increment in milliseconds.
    pub increment_ms: u32,
}

/// Complete seat configuration for a local game.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SeatConfig {
    /// Seat identity.
    pub seat: FourSeat,
    /// Controller identity.
    pub controller: SeatController,
}

/// Token-free local four-player snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FourPlayerSnapshot {
    /// FFA or Teams.
    pub mode: FourMode,
    /// Seat to move.
    pub turn: FourSeat,
    /// Seat controllers.
    pub seats: [SeatConfig; 4],
    /// Seat clocks.
    pub clocks: [SeatClock; 4],
    /// Active army flags.
    pub active: [bool; 4],
    /// FFA capture scores.
    pub scores: [i16; 4],
    /// Current route for Eloi seats.
    pub route: FourBrainRoute,
    /// Last move if any.
    pub last_move: Option<FourMove>,
    /// Terminal outcome if any.
    pub outcome: Option<FourOutcome>,
    /// Complete Eloi-owned state string.
    pub state: String,
}

/// Local four-player session model for GUI and offline smoke tests.
#[derive(Clone, Debug)]
pub struct FourPlayerSession {
    game: FourGame,
    controllers: [SeatController; 4],
    clocks: [SeatClock; 4],
    route: FourBrainRoute,
    last_move: Option<FourMove>,
}

impl FourPlayerSnapshot {
    /// Build a display/protocol snapshot from authoritative state.
    #[must_use]
    pub fn from_position(
        position: &FourPosition,
        controllers: [SeatController; 4],
        clocks: [SeatClock; 4],
        route: FourBrainRoute,
        last_move: Option<FourMove>,
    ) -> Self {
        Self {
            mode: position.mode,
            turn: position.turn,
            seats: FourSeat::ORDER.map(|seat| SeatConfig {
                seat,
                controller: controllers[seat.index()],
            }),
            clocks,
            active: position.active,
            scores: position.scores,
            route,
            last_move,
            outcome: position.outcome(),
            state: position.to_state(),
        }
    }
}

impl FourPlayerSession {
    /// Create a local session from one of the GUI presets.
    #[must_use]
    pub fn new(
        mode: FourMode,
        preset: FourPlayerPreset,
        base_clock_ms: u64,
        increment_ms: u32,
    ) -> Self {
        Self {
            game: FourGame::new(mode),
            controllers: preset.controllers(),
            clocks: [SeatClock {
                remaining_ms: base_clock_ms,
                increment_ms,
            }; 4],
            route: FourBrainRoute::HandcraftedBaseline,
            last_move: None,
        }
    }

    /// Current authoritative position.
    #[must_use]
    pub const fn position(&self) -> &FourPosition {
        self.game.position()
    }

    /// Current token-free snapshot.
    #[must_use]
    pub fn snapshot(&self) -> FourPlayerSnapshot {
        let mut snapshot = FourPlayerSnapshot::from_position(
            self.game.position(),
            self.controllers,
            self.clocks,
            self.route,
            self.last_move,
        );
        snapshot.outcome = self.game.outcome();
        snapshot
    }

    /// Apply a human/local move in compact notation.
    pub fn push_notation(&mut self, text: &str) -> bool {
        let Some(mv) = self.game.position().parse_move(text) else {
            return false;
        };
        if !self.game.push(mv) {
            return false;
        }
        self.last_move = Some(mv);
        true
    }

    /// Undo one local ply.
    pub fn undo(&mut self) -> bool {
        if !self.game.pop() {
            return false;
        }
        self.last_move = self.game.moves().last();
        true
    }

    /// Resign the current seat or a chosen seat.
    pub fn resign(&mut self, seat: FourSeat) {
        self.game.resign(seat);
    }

    /// Search and play once if the side to move is controlled by Eloi.
    ///
    /// # Errors
    /// Returns the baseline search error or move rejection.
    pub fn step_engine_once(
        &mut self,
        movetime: Duration,
        depth: u8,
        stopped: &AtomicBool,
    ) -> Result<Option<FourMove>, &'static str> {
        let seat = self.game.position().turn;
        if self.controllers[seat.index()] != SeatController::Eloi || self.game.outcome().is_some() {
            return Ok(None);
        }
        let result = search_four_player(
            self.game.position(),
            FourSearchLimits {
                movetime,
                depth,
                nodes: None,
            },
            stopped,
        )?;
        let Some(best) = result.best_move else {
            return Ok(None);
        };
        if !self.game.push(best) {
            return Err("four-player engine produced rejected move");
        }
        self.last_move = Some(best);
        Ok(Some(best))
    }
}

/// Complete move-index key for future policy heads.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct FourMoveIndex {
    /// Source file.
    pub from_file: u8,
    /// Source rank.
    pub from_rank: u8,
    /// Destination file.
    pub to_file: u8,
    /// Destination rank.
    pub to_rank: u8,
    /// Promotion, if any.
    pub promotion: Option<PieceKind>,
}

impl From<FourMove> for FourMoveIndex {
    fn from(value: FourMove) -> Self {
        Self {
            from_file: value.from.file(),
            from_rank: value.from.rank(),
            to_file: value.to.file(),
            to_rank: value.to.rank(),
            promotion: value.promotion,
        }
    }
}

/// Presets expected by the local GUI.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FourPlayerPreset {
    /// One human, three Eloi seats.
    OneHumanFfa,
    /// Four humans passing one local device.
    FourHumanPassAndPlay,
    /// Two humans with Eloi partners or opponents in Teams.
    TwoHumanTeams,
    /// All four seats controlled by Eloi.
    AllEngineDemo,
}

impl FourPlayerPreset {
    /// Controllers for this preset.
    #[must_use]
    pub const fn controllers(self) -> [SeatController; 4] {
        match self {
            Self::OneHumanFfa => [
                SeatController::Human,
                SeatController::Eloi,
                SeatController::Eloi,
                SeatController::Eloi,
            ],
            Self::FourHumanPassAndPlay => [SeatController::Human; 4],
            Self::TwoHumanTeams => [
                SeatController::Human,
                SeatController::Human,
                SeatController::Eloi,
                SeatController::Eloi,
            ],
            Self::AllEngineDemo => [SeatController::Eloi; 4],
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_carries_state_without_site_protocol() {
        let position = FourPosition::initial(FourMode::Ffa);
        let clocks = [SeatClock {
            remaining_ms: 60_000,
            increment_ms: 1_000,
        }; 4];
        let snapshot = FourPlayerSnapshot::from_position(
            &position,
            FourPlayerPreset::OneHumanFfa.controllers(),
            clocks,
            FourBrainRoute::HandcraftedBaseline,
            None,
        );
        assert_eq!(snapshot.turn, FourSeat::Red);
        assert_eq!(snapshot.seats[0].controller, SeatController::Human);
        assert_eq!(snapshot.seats[1].controller, SeatController::Eloi);
        assert!(snapshot.state.starts_with("4pc-ffa r "));
    }

    #[test]
    fn complete_move_index_preserves_promotions() {
        let position = FourPosition::initial(FourMode::Teams);
        let mv = position
            .legal_moves()
            .into_iter()
            .find(|mv| mv.promotion.is_none())
            .unwrap();
        let index = FourMoveIndex::from(mv);
        assert_eq!(index.from_file, mv.from.file());
        assert_eq!(index.to_rank, mv.to.rank());
        assert_eq!(index.promotion, None);
    }

    #[test]
    fn session_steps_engine_seats_and_preserves_snapshots() {
        let mut session =
            FourPlayerSession::new(FourMode::Ffa, FourPlayerPreset::AllEngineDemo, 60_000, 0);
        let before = session.snapshot();
        let played = session
            .step_engine_once(Duration::from_millis(100), 1, &AtomicBool::new(false))
            .unwrap();
        assert!(played.is_some());
        let after = session.snapshot();
        assert_ne!(before.state, after.state);
        assert_eq!(after.last_move, played);
        assert!(session.undo());
        assert_eq!(session.snapshot().state, before.state);
    }

    #[test]
    fn session_does_not_move_human_seat() {
        let mut session = FourPlayerSession::new(
            FourMode::Teams,
            FourPlayerPreset::FourHumanPassAndPlay,
            60_000,
            0,
        );
        assert_eq!(
            session
                .step_engine_once(Duration::from_millis(100), 1, &AtomicBool::new(false))
                .unwrap(),
            None
        );
    }
}
