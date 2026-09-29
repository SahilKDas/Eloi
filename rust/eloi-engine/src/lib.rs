//! Search-brain boundaries for the Rust Eloi rewrite.

pub mod nnue;
pub mod search;
pub mod time;
pub mod worker;

use eloi_core::Variant;

/// Stable identity for a chess-search implementation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Brain {
    /// Eloi-owned variant-capable search.
    Eloi,
    /// Frozen legacy Caissa process used only during migration.
    LegacyCaissa,
    /// Proposed permissive Rust donor, subject to qualification.
    Viridithas19,
}

/// Returns the only brain eligible for a variant before donor qualification.
#[must_use]
pub const fn safe_brain_for(variant: Variant) -> Brain {
    match variant {
        Variant::Standard => Brain::LegacyCaissa,
        Variant::Chess960
        | Variant::Horde
        | Variant::KingOfTheHill
        | Variant::Atomic
        | Variant::Antichess
        | Variant::Crazyhouse
        | Variant::FourPlayer => Brain::Eloi,
    }
}

#[cfg(test)]
mod tests {
    use super::{Brain, safe_brain_for};
    use eloi_core::Variant;

    #[test]
    fn donor_is_never_selected_before_qualification() {
        assert_eq!(safe_brain_for(Variant::Standard), Brain::LegacyCaissa);
        assert_eq!(safe_brain_for(Variant::Atomic), Brain::Eloi);
    }
}
