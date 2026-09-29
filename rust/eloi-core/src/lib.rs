//! Authoritative chess and variant state for the Rust Eloi rewrite.

/// Eloi's fixed production search-thread contract.
pub const SEARCH_THREADS: usize = 3;

/// A participant that can own a turn or a piece.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum Player {
    /// Conventional White, or the south player in four-player chess.
    White,
    /// Conventional Black, or the north player in four-player chess.
    Black,
    /// The west player on a four-player board.
    Red,
    /// The east player on a four-player board.
    Blue,
}

/// A square on the optimized two-player 8×8 board.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Square8(u8);

impl Square8 {
    /// Number of playable squares.
    pub const COUNT: u8 = 64;

    /// Constructs a square from a zero-based board index.
    #[must_use]
    pub const fn new(index: u8) -> Option<Self> {
        if index < Self::COUNT {
            Some(Self(index))
        } else {
            None
        }
    }

    /// Returns the compact zero-based square index.
    #[must_use]
    pub const fn index(self) -> u8 {
        self.0
    }
}

/// A playable square on the 14×14 cross board used by four-player chess.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Square14 {
    file: u8,
    rank: u8,
}

impl Square14 {
    /// Side length of the square coordinate grid containing the cross board.
    pub const WIDTH: u8 = 14;

    /// Constructs a playable cross-board square.
    ///
    /// The 3×3 corner regions are outside the board and therefore rejected.
    #[must_use]
    pub const fn new(file: u8, rank: u8) -> Option<Self> {
        if file >= Self::WIDTH || rank >= Self::WIDTH {
            return None;
        }
        let corner_file = file < 3 || file >= 11;
        let corner_rank = rank < 3 || rank >= 11;
        if corner_file && corner_rank {
            None
        } else {
            Some(Self { file, rank })
        }
    }

    /// Returns the zero-based file.
    #[must_use]
    pub const fn file(self) -> u8 {
        self.file
    }

    /// Returns the zero-based rank.
    #[must_use]
    pub const fn rank(self) -> u8 {
        self.rank
    }
}

/// A location in any Eloi-owned board topology.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum BoardSquare {
    /// A square on the two-player board.
    TwoPlayer(Square8),
    /// A square on the four-player cross board.
    FourPlayer(Square14),
}

/// Piece identities shared by orthodox movement and pocket variants.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum PieceKind {
    /// Pawn.
    Pawn,
    /// Knight.
    Knight,
    /// Bishop.
    Bishop,
    /// Rook.
    Rook,
    /// Queen.
    Queen,
    /// King.
    King,
}

/// A complete player action. Drops are represented directly rather than as
/// sentinel source squares, keeping Crazyhouse legal-move handling type-safe.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum Move {
    /// Move a board piece, optionally promoting it.
    Board {
        /// Source square.
        from: BoardSquare,
        /// Destination square.
        to: BoardSquare,
        /// Promotion piece, if any.
        promotion: Option<PieceKind>,
    },
    /// Drop a pocket piece onto the board.
    Drop {
        /// Piece removed from the player's pocket.
        piece: PieceKind,
        /// Destination square.
        to: BoardSquare,
    },
}

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

    /// Returns the turn owners that participate in this variant.
    #[must_use]
    pub const fn players(self) -> &'static [Player] {
        match self {
            Self::FourPlayer => &[Player::White, Player::Red, Player::Black, Player::Blue],
            _ => &[Player::White, Player::Black],
        }
    }

    /// Whether legal moves can include pieces dropped from a pocket.
    #[must_use]
    pub const fn supports_drops(self) -> bool {
        matches!(self, Self::Crazyhouse)
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
    use super::{BoardSquare, Move, PieceKind, Player, SEARCH_THREADS, Square8, Square14, Variant};

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

    #[test]
    fn topology_types_reject_impossible_squares() {
        assert_eq!(Square8::new(63).map(Square8::index), Some(63));
        assert_eq!(Square8::new(64), None);
        assert_eq!(Square14::new(0, 0), None);
        assert_eq!(Square14::new(3, 0).map(Square14::file), Some(3));
        assert_eq!(Square14::new(13, 10).map(Square14::rank), Some(10));
    }

    #[test]
    fn future_variants_have_explicit_semantics() {
        assert_eq!(
            Variant::Crazyhouse.players(),
            &[Player::White, Player::Black]
        );
        assert!(Variant::Crazyhouse.supports_drops());
        assert_eq!(Variant::FourPlayer.players().len(), 4);
        assert!(!Variant::FourPlayer.supports_drops());

        let drop = Move::Drop {
            piece: PieceKind::Knight,
            to: BoardSquare::TwoPlayer(Square8::new(28).expect("valid square")),
        };
        assert!(matches!(drop, Move::Drop { .. }));
    }
}
