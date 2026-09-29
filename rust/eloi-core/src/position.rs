//! Strict, variant-aware position serialization for the two-player board.

use std::fmt::{self, Write};

use crate::{PieceKind, Player, Square8, Variant};

/// Standard starting position.
pub const INITIAL_FEN: &str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

/// Production Horde starting position, with Black retaining castling rights.
pub const HORDE_INITIAL_FEN: &str =
    "rnbqkbnr/pppppppp/8/1PP2PP1/PPPPPPPP/PPPPPPPP/PPPPPPPP/PPPPPPPP w kq - 0 1";

/// A board piece, including Crazyhouse promotion provenance.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Piece {
    /// Owner of the piece.
    pub owner: Player,
    /// Current piece type.
    pub kind: PieceKind,
    /// Whether this piece originated through pawn promotion.
    pub promoted: bool,
}

/// Explicit rook origin for one castling right.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CastlingRight {
    /// Player holding the right.
    pub owner: Player,
    /// Rook's original square.
    pub rook: Square8,
}

/// Complete serialized two-player position, independent of search caches.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Position {
    /// Variant determines rules and model selection.
    pub variant: Variant,
    /// Board squares in a1-to-h8 order.
    pub cells: [Option<Piece>; 64],
    /// Player to move.
    pub turn: Player,
    /// Castling rook origins, preserving Chess960 metadata.
    pub castling: Vec<CastlingRight>,
    /// En-passant target square.
    pub en_passant: Option<Square8>,
    /// Halfmove clock.
    pub halfmove: u32,
    /// Fullmove number, starting at one.
    pub fullmove: u32,
    /// Pocket counts indexed by player then pawn/knight/bishop/rook/queen.
    pub pockets: [[u8; 5]; 2],
}

/// A rejected FEN; callers must leave their old position intact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FenError(pub &'static str);

impl fmt::Display for FenError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}

impl std::error::Error for FenError {}

fn piece_from_char(c: char) -> Option<Piece> {
    let kind = match c.to_ascii_lowercase() {
        'p' => PieceKind::Pawn,
        'n' => PieceKind::Knight,
        'b' => PieceKind::Bishop,
        'r' => PieceKind::Rook,
        'q' => PieceKind::Queen,
        'k' => PieceKind::King,
        _ => return None,
    };
    Some(Piece {
        owner: if c.is_ascii_uppercase() {
            Player::White
        } else {
            Player::Black
        },
        kind,
        promoted: false,
    })
}

fn piece_char(piece: Piece) -> char {
    let c = match piece.kind {
        PieceKind::Pawn => 'p',
        PieceKind::Knight => 'n',
        PieceKind::Bishop => 'b',
        PieceKind::Rook => 'r',
        PieceKind::Queen => 'q',
        PieceKind::King => 'k',
    };
    if piece.owner == Player::White {
        c.to_ascii_uppercase()
    } else {
        c
    }
}

fn pocket_index(kind: PieceKind) -> Option<usize> {
    Some(match kind {
        PieceKind::Pawn => 0,
        PieceKind::Knight => 1,
        PieceKind::Bishop => 2,
        PieceKind::Rook => 3,
        PieceKind::Queen => 4,
        PieceKind::King => return None,
    })
}

/// Parse an algebraic 8×8 square.
#[must_use]
pub fn parse_square(text: &str) -> Option<Square8> {
    let b = text.as_bytes();
    if b.len() != 2 || !(b'a'..=b'h').contains(&b[0]) || !(b'1'..=b'8').contains(&b[1]) {
        return None;
    }
    Square8::new((b[1] - b'1') * 8 + b[0] - b'a')
}

/// Format a valid 8×8 square in algebraic notation.
#[must_use]
pub fn square_name(square: Square8) -> String {
    let i = square.index();
    format!("{}{}", char::from(b'a' + i % 8), char::from(b'1' + i / 8))
}

impl Position {
    /// Parse all six FEN fields with variant-specific state validation.
    ///
    /// # Errors
    /// Rejects malformed boards, pockets, counters, castling origins and kings.
    /// Four-player positions require their separate serializer.
    pub fn from_fen(fen: &str, variant: Variant) -> Result<Self, FenError> {
        if variant == Variant::FourPlayer {
            return Err(FenError("four-player requires its own position format"));
        }
        let fields: Vec<_> = fen.split_whitespace().collect();
        if fields.len() != 6 {
            return Err(FenError("FEN requires exactly six fields"));
        }
        let mut result = Self {
            variant,
            cells: [None; 64],
            turn: Player::White,
            castling: Vec::new(),
            en_passant: None,
            halfmove: 0,
            fullmove: 1,
            pockets: [[0; 5]; 2],
        };
        let (board, pocket) = if let Some((board, tail)) = fields[0].split_once('[') {
            if variant != Variant::Crazyhouse
                || !tail.ends_with(']')
                || tail[..tail.len() - 1].contains(['[', ']'])
            {
                return Err(FenError("invalid pocket syntax or variant"));
            }
            (board, Some(&tail[..tail.len() - 1]))
        } else {
            (fields[0], None)
        };
        let ranks: Vec<_> = board.split('/').collect();
        if ranks.len() != 8 {
            return Err(FenError("board requires eight ranks"));
        }
        for (rank, row) in (0_usize..8).rev().zip(ranks) {
            let mut file = 0_usize;
            let mut chars = row.chars().peekable();
            while let Some(c) = chars.next() {
                if ('1'..='8').contains(&c) {
                    file += (c as usize) - ('0' as usize);
                } else {
                    if file >= 8 {
                        return Err(FenError("rank exceeds eight squares"));
                    }
                    let mut piece = piece_from_char(c).ok_or(FenError("unknown piece"))?;
                    if chars.peek() == Some(&'~') {
                        chars.next();
                        if variant != Variant::Crazyhouse
                            || matches!(piece.kind, PieceKind::Pawn | PieceKind::King)
                        {
                            return Err(FenError("invalid promoted-piece marker"));
                        }
                        piece.promoted = true;
                    }
                    result.cells[rank * 8 + file] = Some(piece);
                    file += 1;
                }
                if file > 8 {
                    return Err(FenError("rank exceeds eight squares"));
                }
            }
            if file != 8 {
                return Err(FenError("rank must contain eight squares"));
            }
        }
        if let Some(pocket) = pocket {
            for c in pocket.chars() {
                let p = piece_from_char(c).ok_or(FenError("unknown pocket piece"))?;
                let index = pocket_index(p.kind).ok_or(FenError("king cannot enter pocket"))?;
                let owner = usize::from(p.owner == Player::Black);
                result.pockets[owner][index] = result.pockets[owner][index]
                    .checked_add(1)
                    .ok_or(FenError("pocket count overflow"))?;
            }
        }
        result.turn = match fields[1] {
            "w" => Player::White,
            "b" => Player::Black,
            _ => return Err(FenError("invalid turn")),
        };
        result.halfmove = fields[4]
            .parse()
            .map_err(|_| FenError("invalid halfmove clock"))?;
        result.fullmove = fields[5]
            .parse()
            .map_err(|_| FenError("invalid fullmove number"))?;
        if result.fullmove == 0 {
            return Err(FenError("fullmove number starts at one"));
        }
        result.validate_kings()?;
        result.parse_castling(fields[2])?;
        if fields[3] != "-" {
            let square = parse_square(fields[3]).ok_or(FenError("invalid en-passant square"))?;
            let rank = square.index() / 8;
            if rank != if result.turn == Player::White { 5 } else { 2 }
                || result.cells[usize::from(square.index())].is_some()
            {
                return Err(FenError("invalid en-passant rank or occupied target"));
            }
            result.en_passant = Some(square);
        }
        Ok(result)
    }

    fn validate_kings(&self) -> Result<(), FenError> {
        if self.variant == Variant::Antichess {
            return Ok(());
        }
        for owner in [Player::White, Player::Black] {
            let count = self
                .cells
                .iter()
                .flatten()
                .filter(|p| p.owner == owner && p.kind == PieceKind::King)
                .count();
            let optional = (self.variant == Variant::Horde && owner == Player::White)
                || self.variant == Variant::Atomic;
            if count > 1 || (!optional && count != 1) {
                return Err(FenError("invalid king count"));
            }
        }
        Ok(())
    }

    fn parse_castling(&mut self, text: &str) -> Result<(), FenError> {
        if text == "-" {
            return Ok(());
        }
        if self.variant == Variant::Antichess {
            return Err(FenError("antichess has no castling"));
        }
        for c in text.chars() {
            let owner = if c.is_ascii_uppercase() {
                Player::White
            } else {
                Player::Black
            };
            let rank = if owner == Player::White { 0_u8 } else { 7 };
            let king = self
                .cells
                .iter()
                .position(|p| p.is_some_and(|p| p.owner == owner && p.kind == PieceKind::King))
                .ok_or(FenError("castling requires king"))?;
            if king / 8 != usize::from(rank) {
                return Err(FenError("castling king must be on home rank"));
            }
            let file = match c.to_ascii_uppercase() {
                'K' | 'Q' => {
                    let kingside = c.eq_ignore_ascii_case(&'k');
                    if self.variant == Variant::Chess960 {
                        let rooks: Vec<u8> = (0..8)
                            .filter(|&f| {
                                self.cells[usize::from(rank * 8 + f)]
                                    .is_some_and(|p| p.owner == owner && p.kind == PieceKind::Rook)
                                    && ((usize::from(f) > king % 8) == kingside)
                            })
                            .collect();
                        if kingside {
                            rooks.last().copied()
                        } else {
                            rooks.first().copied()
                        }
                        .ok_or(FenError("castling rook missing"))?
                    } else {
                        if king % 8 != 4 {
                            return Err(FenError("orthodox castling requires e-file king"));
                        }
                        if kingside { 7 } else { 0 }
                    }
                }
                'A'..='H' if self.variant == Variant::Chess960 => {
                    c.to_ascii_uppercase() as u8 - b'A'
                }
                _ => return Err(FenError("invalid castling flag")),
            };
            let rook = Square8::new(rank * 8 + file).expect("bounded square");
            if !self.cells[usize::from(rook.index())]
                .is_some_and(|p| p.owner == owner && p.kind == PieceKind::Rook && !p.promoted)
            {
                return Err(FenError("castling rook missing"));
            }
            let kingside = usize::from(file) > king % 8;
            if self.castling.iter().any(|r| {
                r.owner == owner && ((usize::from(r.rook.index() % 8) > king % 8) == kingside)
            }) {
                return Err(FenError("duplicate castling side"));
            }
            self.castling.push(CastlingRight { owner, rook });
        }
        self.castling.sort_by_key(|r| {
            (
                u8::from(r.owner == Player::Black),
                std::cmp::Reverse(r.rook.index() % 8),
            )
        });
        Ok(())
    }

    /// Serialize all rule-relevant fields to a canonical FEN.
    #[must_use]
    pub fn to_fen(&self) -> String {
        let mut out = String::new();
        for rank in (0..8).rev() {
            let mut empty = 0;
            for file in 0..8 {
                if let Some(piece) = self.cells[rank * 8 + file] {
                    if empty != 0 {
                        write!(out, "{empty}").expect("String write");
                        empty = 0;
                    }
                    out.push(piece_char(piece));
                    if piece.promoted {
                        out.push('~');
                    }
                } else {
                    empty += 1;
                }
            }
            if empty != 0 {
                write!(out, "{empty}").expect("String write");
            }
            if rank != 0 {
                out.push('/');
            }
        }
        if self.variant == Variant::Crazyhouse {
            out.push('[');
            for (owner, kinds) in self.pockets.iter().enumerate() {
                for (kind, count) in [
                    PieceKind::Pawn,
                    PieceKind::Knight,
                    PieceKind::Bishop,
                    PieceKind::Rook,
                    PieceKind::Queen,
                ]
                .into_iter()
                .zip(kinds)
                {
                    for _ in 0..*count {
                        out.push(piece_char(Piece {
                            owner: if owner == 0 {
                                Player::White
                            } else {
                                Player::Black
                            },
                            kind,
                            promoted: false,
                        }));
                    }
                }
            }
            out.push(']');
        }
        out.push_str(if self.turn == Player::White {
            " w "
        } else {
            " b "
        });
        if self.castling.is_empty() {
            out.push('-');
        } else {
            for right in &self.castling {
                let file = right.rook.index() % 8;
                let c = if self.variant == Variant::Chess960 {
                    char::from(b'A' + file)
                } else if file == 7 {
                    'K'
                } else {
                    'Q'
                };
                out.push(if right.owner == Player::White {
                    c
                } else {
                    c.to_ascii_lowercase()
                });
            }
        }
        write!(
            out,
            " {} {} {}",
            self.en_passant.map_or_else(|| "-".into(), square_name),
            self.halfmove,
            self.fullmove
        )
        .expect("String write");
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn orthodox_roundtrip_preserves_all_fields() {
        let p = Position::from_fen(INITIAL_FEN, Variant::Standard).unwrap();
        assert_eq!(p.to_fen(), INITIAL_FEN);
        let fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2";
        assert_eq!(
            Position::from_fen(fen, Variant::Standard).unwrap().to_fen(),
            fen
        );
    }

    #[test]
    fn chess960_preserves_rook_origins() {
        let fen = "rk5r/8/8/8/8/8/8/RK5R w HAha - 0 1";
        let p = Position::from_fen(fen, Variant::Chess960).unwrap();
        assert_eq!(p.to_fen(), fen);
        assert_eq!(
            Position::from_fen("rk5r/8/8/8/8/8/8/RK5R w KQkq - 0 1", Variant::Chess960).unwrap(),
            p
        );
    }

    #[test]
    fn pockets_and_promotions_survive_roundtrip() {
        let p = Position::from_fen(
            "4k3/8/8/8/3Q~4/8/8/4K3[PNq] b - - 12 30",
            Variant::Crazyhouse,
        )
        .unwrap();
        assert_eq!(
            Position::from_fen(&p.to_fen(), Variant::Crazyhouse).unwrap(),
            p
        );
        assert_eq!(p.pockets[0], [1, 1, 0, 0, 0]);
        assert_eq!(p.pockets[1], [0, 0, 0, 0, 1]);
    }

    #[test]
    fn malformed_positions_fail_closed() {
        for fen in [
            "8/8/8/8/8/8/8/8 w - - 0 1",
            "4k3/8/8/8/8/8/8/4K3 w K - 0 1",
            "4k3/8/8/8/8/8/8/4K3 w - e3 0 1",
            "4k3/8/8/8/8/8/8/4K3 w - - 0 0",
            "4k3/8/8/8/8/8/8/4K3[K] w - - 0 1",
            "4k3/8/8/8/8/8/8/4K3 w - - 0 1 extra",
        ] {
            assert!(Position::from_fen(fen, Variant::Standard).is_err(), "{fen}");
        }
    }
}
