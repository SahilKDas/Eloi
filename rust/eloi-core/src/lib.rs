//! Authoritative chess and variant state for the Rust Eloi rewrite.

/// Eloi's fixed production search-thread contract.
pub const SEARCH_THREADS: usize = 3;

/// Chess variants supported by the current native Eloi runtime.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Variant {
    /// FIDE Standard chess.
    Standard,
    /// Fischer Random / Chess960.
    Chess960,
    /// Horde chess.
    Horde,
    /// King of the Hill.
    KingOfTheHill,
    /// Atomic chess.
    Atomic,
    /// Antichess with compulsory captures.
    Antichess,
    /// Crazyhouse with captured-piece pockets and drops.
    Crazyhouse,
    /// Four-player chess on a cross-shaped board.
    FourPlayer,
}

impl Variant {
    /// Returns the exact Lichess stream key when Lichess offers the variant.
    #[must_use]
    pub const fn lichess_key(self) -> Option<&'static str> {
        match self {
            Self::Standard => Some("standard"),
            Self::Chess960 => Some("chess960"),
            Self::Horde => Some("horde"),
            Self::KingOfTheHill => Some("kingOfTheHill"),
            Self::Atomic => Some("atomic"),
            Self::Antichess => Some("antichess"),
            Self::Crazyhouse => Some("crazyhouse"),
            Self::FourPlayer => None,
        }
    }

    /// Returns the board topology required by this ruleset.
    #[must_use]
    pub const fn topology(self) -> BoardTopology {
        match self {
            Self::FourPlayer => BoardTopology::FourPlayerCross14,
            _ => BoardTopology::TwoPlayer8x8,
        }
    }
}

/// Physical board and turn topology, separate from individual variant rules.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BoardTopology {
    /// Conventional two-player 8×8 chess board.
    TwoPlayer8x8,
    /// Four-player 14×14 cross board with four turn owners.
    FourPlayerCross14,
}

#[cfg(test)]
mod tests {
    use super::{SEARCH_THREADS, Variant};

    #[test]
    fn production_contract_is_three_threads() {
        assert_eq!(SEARCH_THREADS, 3);
    }

    #[test]
    fn lichess_variant_keys_preserve_exact_casing() {
        assert_eq!(Variant::KingOfTheHill.lichess_key(), Some("kingOfTheHill"));
        assert_eq!(Variant::Atomic.lichess_key(), Some("atomic"));
        assert_eq!(Variant::FourPlayer.lichess_key(), None);
    }

    #[test]
    fn four_player_does_not_reuse_the_eight_by_eight_topology() {
        assert_eq!(
            Variant::FourPlayer.topology(),
            super::BoardTopology::FourPlayerCross14
        );
    }
}
