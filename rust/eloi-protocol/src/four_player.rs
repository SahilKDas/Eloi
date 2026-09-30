//! Transport-neutral four-player messages for local GUI and future adapters.
//!
//! These types are not Chess.com integration. They are Eloi-owned messages that
//! describe local state, clocks, scores, routes and results without coupling the
//! engine to any website-specific protocol.

use eloi_core::PieceKind;
use eloi_core::four_player::{FourMode, FourMove, FourOutcome, FourPosition, FourSeat};

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
}
