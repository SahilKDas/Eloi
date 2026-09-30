//! Integer-exact port of production clock reserve and panic protections.

use eloi_core::{PieceKind, position::Position};

/// Clock pressure classification used by diagnostics.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ClockMode {
    /// More than two minutes remain.
    Normal,
    /// At most two minutes remain.
    Pressure,
    /// At most one minute remains.
    Emergency,
    /// At most twenty seconds remain.
    Panic,
}

/// Frozen production time allocation, in milliseconds.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TimeBudget {
    /// Clock pressure mode.
    pub mode: ClockMode,
    /// Reserved for future moves and network/protocol overhead.
    pub reserve_ms: u64,
    /// Nominal allocation.
    pub base_ms: u64,
    /// Iteration-boundary stop budget.
    pub soft_ms: u64,
    /// Absolute deadline budget.
    pub hard_ms: u64,
}

/// Allocate without floating point, reproducing the legacy production planner.
#[must_use]
pub fn plan(
    position: &Position,
    remaining_ms: u32,
    increment_ms: u32,
    moves_to_go: u32,
    overhead_ms: u32,
) -> TimeBudget {
    let remaining = u64::from(remaining_ms).max(1);
    let overhead = u64::from(overhead_ms.min(5000));
    let material: u64 = position
        .cells
        .iter()
        .flatten()
        .map(|piece| match piece.kind {
            PieceKind::Bishop | PieceKind::Knight => 300,
            PieceKind::Rook => 500,
            PieceKind::Queen => 900,
            _ => 0,
        })
        .sum();
    let mut horizon = if material >= 5000 {
        64
    } else if material >= 2200 {
        52
    } else {
        36
    };
    if moves_to_go > 0 {
        horizon = u64::from(moves_to_go.clamp(8, 80));
    }
    let (mode, floor, divisor, credit_percent, hard_cap, hard_divisor, multiplier, horizon_floor) =
        if remaining <= 20_000 {
            (ClockMode::Panic, 750, 4, 10, 250, 48, 180, 128)
        } else if remaining <= 60_000 {
            (ClockMode::Emergency, 2000, 6, 25, 1200, 24, 190, 96)
        } else if remaining <= 120_000 {
            (ClockMode::Pressure, 4000, 10, 50, 4000, 20, 200, 72)
        } else {
            (ClockMode::Normal, 5000, 16, 70, 12000, 24, 200, 0)
        };
    horizon = horizon.max(horizon_floor);
    let reserve_ms = floor
        .max(remaining / divisor)
        .max(overhead * 6 + 250)
        .min(remaining - 1);
    let usable = (remaining - reserve_ms).max(1);
    let credit = (u64::from(increment_ms) * credit_percent / 100).min(usable / 8);
    let cap = hard_cap.min((usable / hard_divisor).max(1) + credit).max(1);
    let base_ms = (usable / horizon + credit).clamp(1, usable).min(cap);
    let hard_ms = (base_ms * multiplier / 100).clamp(base_ms, usable.min(cap));
    TimeBudget {
        mode,
        reserve_ms,
        base_ms,
        soft_ms: base_ms.min(hard_ms),
        hard_ms,
    }
}

#[cfg(test)]
mod tests {
    use super::{ClockMode, plan};
    use eloi_core::{
        Variant,
        position::{INITIAL_FEN, Position},
    };

    #[test]
    fn clock_reserves_and_pressure_boundaries() {
        let position = Position::from_fen(INITIAL_FEN, Variant::Standard).unwrap();
        for (remaining, mode) in [
            (1, ClockMode::Panic),
            (20_000, ClockMode::Panic),
            (20_001, ClockMode::Emergency),
            (60_001, ClockMode::Pressure),
            (120_001, ClockMode::Normal),
        ] {
            let budget = plan(&position, remaining, 0, 0, 0);
            assert_eq!(budget.mode, mode);
            assert!(budget.soft_ms > 0 && budget.soft_ms <= budget.hard_ms);
            assert!(budget.reserve_ms + budget.hard_ms <= u64::from(remaining));
        }
        let budget = plan(&position, 300_000, 0, 0, 0);
        assert_eq!(
            (budget.reserve_ms, budget.soft_ms, budget.hard_ms),
            (18_750, 4394, 8788)
        );
        assert!(plan(&position, u32::MAX, u32::MAX, u32::MAX, u32::MAX).hard_ms > 0);
    }
}
