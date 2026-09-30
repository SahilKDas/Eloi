//! Four-player chess state, rules and deterministic baseline support.
//!
//! This module is deliberately separate from the orthodox 8x8 `Position`.
//! Four-player chess has different seats, scoring, teams, board geometry and
//! terminal rules, so sharing `Player` or FEN state would make later protocol
//! and training code fragile.

use std::fmt::{self, Write};

use crate::{PieceKind, Square14};

/// Clockwise four-player seat order used by Chess.com-style four-player chess.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum FourSeat {
    /// South seat, first to move.
    Red,
    /// West seat, second to move.
    Blue,
    /// North seat, third to move.
    Yellow,
    /// East seat, fourth to move.
    Green,
}

impl FourSeat {
    /// Clockwise move order.
    pub const ORDER: [Self; 4] = [Self::Red, Self::Blue, Self::Yellow, Self::Green];

    /// Stable index used for arrays and serialization.
    #[must_use]
    pub const fn index(self) -> usize {
        match self {
            Self::Red => 0,
            Self::Blue => 1,
            Self::Yellow => 2,
            Self::Green => 3,
        }
    }

    /// Next seat in Red -> Blue -> Yellow -> Green order.
    #[must_use]
    pub const fn next(self) -> Self {
        match self {
            Self::Red => Self::Blue,
            Self::Blue => Self::Yellow,
            Self::Yellow => Self::Green,
            Self::Green => Self::Red,
        }
    }

    /// Partner seat in Teams mode.
    #[must_use]
    pub const fn partner(self) -> Self {
        match self {
            Self::Red => Self::Yellow,
            Self::Yellow => Self::Red,
            Self::Blue => Self::Green,
            Self::Green => Self::Blue,
        }
    }

    /// Direction a pawn advances for this seat.
    #[must_use]
    pub const fn pawn_step(self) -> (i8, i8) {
        match self {
            Self::Red => (0, 1),
            Self::Blue => (1, 0),
            Self::Yellow => (0, -1),
            Self::Green => (-1, 0),
        }
    }

    /// Display key used in compact state notation.
    #[must_use]
    pub const fn key(self) -> char {
        match self {
            Self::Red => 'r',
            Self::Blue => 'b',
            Self::Yellow => 'y',
            Self::Green => 'g',
        }
    }
}

/// Four-player ruleset.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FourMode {
    /// Free-for-all with individual capture points and placements.
    Ffa,
    /// Red/Yellow versus Blue/Green.
    Teams,
}

/// A four-player board piece.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FourPiece {
    /// Owning seat.
    pub owner: FourSeat,
    /// Current piece kind.
    pub kind: PieceKind,
}

/// A legal move on the 14x14 cross board.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FourMove {
    /// Source square.
    pub from: Square14,
    /// Destination square.
    pub to: Square14,
    /// Teams-mode promotion choice. FFA promotions are automatic queens.
    pub promotion: Option<PieceKind>,
}

impl FourMove {
    /// Compact coordinate notation using two base-14 coordinates and optional promotion.
    #[must_use]
    pub fn notation(self) -> String {
        let mut out = format!("{}{}", square_name(self.from), square_name(self.to));
        if let Some(piece) = self.promotion {
            out.push(piece_letter(piece));
        }
        out
    }
}

/// Outcome once a four-player position is terminal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FourOutcome {
    /// FFA placements, preserving tied scores by equal values.
    Placements(Vec<(FourSeat, i16)>),
    /// Teams winner.
    TeamWin {
        /// True when Red/Yellow won; false when Blue/Green won.
        red_yellow: bool,
    },
    /// Teams draw.
    Draw,
}

/// Complete four-player game state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FourPosition {
    /// Ruleset.
    pub mode: FourMode,
    /// Board cells indexed by rank * 14 + file. Non-playable corner cells stay `None`.
    pub cells: [Option<FourPiece>; 196],
    /// Seat to move.
    pub turn: FourSeat,
    /// Active armies; inactive FFA armies may retain a zombie king.
    pub active: [bool; 4],
    /// FFA capture scores.
    pub scores: [i16; 4],
    /// Halfmove clock for reversible-state diagnostics.
    pub halfmove: u16,
    /// Ply count.
    pub ply: u32,
}

impl FourPosition {
    /// Construct the standard 160-square initial setup.
    #[must_use]
    pub fn initial(mode: FourMode) -> Self {
        let mut position = Self {
            mode,
            cells: [None; 196],
            turn: FourSeat::Red,
            active: [true; 4],
            scores: [0; 4],
            halfmove: 0,
            ply: 0,
        };
        position.place_back_rank(FourSeat::Red);
        position.place_back_rank(FourSeat::Blue);
        position.place_back_rank(FourSeat::Yellow);
        position.place_back_rank(FourSeat::Green);
        position
    }

    /// Number of playable cross-board squares.
    #[must_use]
    pub fn playable_square_count() -> usize {
        (0..14)
            .flat_map(|rank| (0..14).map(move |file| (file, rank)))
            .filter(|&(file, rank)| Square14::new(file, rank).is_some())
            .count()
    }

    fn place_back_rank(&mut self, seat: FourSeat) {
        let back = [
            PieceKind::Rook,
            PieceKind::Knight,
            PieceKind::Bishop,
            PieceKind::Queen,
            PieceKind::King,
            PieceKind::Bishop,
            PieceKind::Knight,
            PieceKind::Rook,
        ];
        for (i, kind) in back.into_iter().enumerate() {
            let (file, rank) = match seat {
                FourSeat::Red => (3 + i as u8, 0),
                FourSeat::Yellow => (10 - i as u8, 13),
                FourSeat::Blue => (0, 3 + i as u8),
                FourSeat::Green => (13, 10 - i as u8),
            };
            self.set(
                Square14::new(file, rank).expect("home rank is playable"),
                Some(FourPiece { owner: seat, kind }),
            );
        }
        for i in 0..8 {
            let (file, rank) = match seat {
                FourSeat::Red => (3 + i, 1),
                FourSeat::Yellow => (3 + i, 12),
                FourSeat::Blue => (1, 3 + i),
                FourSeat::Green => (12, 3 + i),
            };
            self.set(
                Square14::new(file, rank).expect("pawn rank is playable"),
                Some(FourPiece {
                    owner: seat,
                    kind: PieceKind::Pawn,
                }),
            );
        }
    }

    /// Piece on a square.
    #[must_use]
    pub fn at(&self, square: Square14) -> Option<FourPiece> {
        self.cells[square_index(square)]
    }

    fn set(&mut self, square: Square14, piece: Option<FourPiece>) {
        self.cells[square_index(square)] = piece;
    }

    /// Return the king square for an active or zombie army.
    #[must_use]
    pub fn king(&self, seat: FourSeat) -> Option<Square14> {
        playable_squares().find(|&square| {
            self.at(square)
                .is_some_and(|piece| piece.owner == seat && piece.kind == PieceKind::King)
        })
    }

    /// Whether two seats are partners under the active mode.
    #[must_use]
    pub const fn allied(&self, a: FourSeat, b: FourSeat) -> bool {
        match self.mode {
            FourMode::Ffa => a.index() == b.index(),
            FourMode::Teams => a.index() == b.index() || a.partner().index() == b.index(),
        }
    }

    /// Generate legal moves for the side to move.
    #[must_use]
    pub fn legal_moves(&self) -> Vec<FourMove> {
        if self.outcome().is_some() || !self.active[self.turn.index()] {
            return Vec::new();
        }
        let mut moves = self.pseudo_moves(self.turn);
        moves.retain(|&mv| {
            let Some(next) = self.apply_unchecked(mv) else {
                return false;
            };
            !next.king_attacked(self.turn)
        });
        moves
    }

    /// Generate geometric legal candidates before king-safety filtering.
    #[must_use]
    pub fn pseudo_moves(&self, seat: FourSeat) -> Vec<FourMove> {
        let mut moves = Vec::new();
        for from in playable_squares() {
            let Some(piece) = self.at(from).filter(|piece| piece.owner == seat) else {
                continue;
            };
            match piece.kind {
                PieceKind::Pawn => self.append_pawns(from, seat, &mut moves),
                PieceKind::Knight => {
                    for (df, dr) in KNIGHT {
                        self.append_step(from, df, dr, seat, None, &mut moves);
                    }
                }
                PieceKind::King => {
                    for (df, dr) in KING {
                        self.append_step(from, df, dr, seat, None, &mut moves);
                    }
                }
                PieceKind::Bishop => self.append_sliders(from, seat, &BISHOP, &mut moves),
                PieceKind::Rook => self.append_sliders(from, seat, &ROOK, &mut moves),
                PieceKind::Queen => {
                    self.append_sliders(from, seat, &BISHOP, &mut moves);
                    self.append_sliders(from, seat, &ROOK, &mut moves);
                }
            }
        }
        moves
    }

    fn append_pawns(&self, from: Square14, seat: FourSeat, moves: &mut Vec<FourMove>) {
        let (df, dr) = seat.pawn_step();
        if let Some(to) = offset(from, df, dr).filter(|&to| self.at(to).is_none()) {
            self.append_promotion_aware(from, to, moves);
        }
        let captures = if df == 0 {
            [(-1, dr), (1, dr)]
        } else {
            [(df, -1), (df, 1)]
        };
        for (cdf, cdr) in captures {
            if let Some(to) = offset(from, cdf, cdr)
                && self.at(to).is_some_and(|piece| {
                    !self.allied(seat, piece.owner) && piece.kind != PieceKind::King
                })
            {
                self.append_promotion_aware(from, to, moves);
            }
        }
    }

    fn append_promotion_aware(&self, from: Square14, to: Square14, moves: &mut Vec<FourMove>) {
        if !promotion_square(self.turn, to, self.mode) {
            moves.push(FourMove {
                from,
                to,
                promotion: None,
            });
            return;
        }
        match self.mode {
            FourMode::Ffa => moves.push(FourMove {
                from,
                to,
                promotion: Some(PieceKind::Queen),
            }),
            FourMode::Teams => {
                for promotion in [
                    PieceKind::Queen,
                    PieceKind::Rook,
                    PieceKind::Bishop,
                    PieceKind::Knight,
                ] {
                    moves.push(FourMove {
                        from,
                        to,
                        promotion: Some(promotion),
                    });
                }
            }
        }
    }

    fn append_step(
        &self,
        from: Square14,
        df: i8,
        dr: i8,
        seat: FourSeat,
        promotion: Option<PieceKind>,
        moves: &mut Vec<FourMove>,
    ) {
        if let Some(to) = offset(from, df, dr)
            && self.at(to).is_none_or(|piece| {
                !self.allied(seat, piece.owner) && piece.kind != PieceKind::King
            })
        {
            moves.push(FourMove {
                from,
                to,
                promotion,
            });
        }
    }

    fn append_sliders(
        &self,
        from: Square14,
        seat: FourSeat,
        directions: &[(i8, i8)],
        moves: &mut Vec<FourMove>,
    ) {
        for &(df, dr) in directions {
            let mut cursor = offset(from, df, dr);
            while let Some(to) = cursor {
                if let Some(piece) = self.at(to) {
                    if !self.allied(seat, piece.owner) && piece.kind != PieceKind::King {
                        moves.push(FourMove {
                            from,
                            to,
                            promotion: None,
                        });
                    }
                    break;
                }
                moves.push(FourMove {
                    from,
                    to,
                    promotion: None,
                });
                cursor = offset(to, df, dr);
            }
        }
    }

    /// Whether a seat's king is currently attacked by any enemy.
    #[must_use]
    pub fn king_attacked(&self, seat: FourSeat) -> bool {
        let Some(king) = self.king(seat) else {
            return true;
        };
        FourSeat::ORDER
            .into_iter()
            .filter(|&other| self.active[other.index()] && !self.allied(seat, other))
            .any(|other| self.attacks_square(other, king))
    }

    /// Geometric attack detection for the four-player board.
    #[must_use]
    pub fn attacks_square(&self, attacker: FourSeat, target: Square14) -> bool {
        for from in playable_squares() {
            let Some(piece) = self.at(from).filter(|piece| piece.owner == attacker) else {
                continue;
            };
            if piece_attacks(self, piece, from, target) {
                return true;
            }
        }
        false
    }

    /// Apply a legal move.
    #[must_use]
    pub fn play(&self, mv: FourMove) -> Option<Self> {
        self.legal_moves()
            .into_iter()
            .find(|&legal| legal == mv)
            .and_then(|_| self.apply_unchecked(mv))
    }

    fn apply_unchecked(&self, mv: FourMove) -> Option<Self> {
        let mut next = self.clone();
        let moving = self.at(mv.from)?;
        if moving.owner != self.turn {
            return None;
        }
        if let Some(captured) = self.at(mv.to) {
            if self.allied(moving.owner, captured.owner) || captured.kind == PieceKind::King {
                return None;
            }
            if self.mode == FourMode::Ffa {
                next.scores[moving.owner.index()] += capture_value(captured.kind);
            }
        }
        next.set(mv.from, None);
        next.set(
            mv.to,
            Some(FourPiece {
                kind: mv.promotion.unwrap_or(moving.kind),
                ..moving
            }),
        );
        next.halfmove = if moving.kind == PieceKind::Pawn || self.at(mv.to).is_some() {
            0
        } else {
            next.halfmove.saturating_add(1)
        };
        next.ply = next.ply.saturating_add(1);
        next.advance_turn();
        next.resolve_eliminations();
        Some(next)
    }

    fn advance_turn(&mut self) {
        let mut candidate = self.turn.next();
        for _ in 0..4 {
            if self.active[candidate.index()] || self.king(candidate).is_some() {
                self.turn = candidate;
                return;
            }
            candidate = candidate.next();
        }
        self.turn = candidate;
    }

    fn resolve_eliminations(&mut self) {
        match self.mode {
            FourMode::Ffa => {
                for seat in FourSeat::ORDER {
                    if self.active[seat.index()] && self.king(seat).is_none() {
                        self.active[seat.index()] = false;
                    }
                }
            }
            FourMode::Teams => {}
        }
    }

    /// Terminal result, if any.
    #[must_use]
    pub fn outcome(&self) -> Option<FourOutcome> {
        match self.mode {
            FourMode::Ffa => {
                let active = FourSeat::ORDER
                    .into_iter()
                    .filter(|seat| self.active[seat.index()])
                    .count();
                if active <= 1 || self.scores.iter().any(|&score| score >= 21) {
                    let mut placements: Vec<_> = FourSeat::ORDER
                        .into_iter()
                        .map(|seat| (seat, self.scores[seat.index()]))
                        .collect();
                    placements.sort_by_key(|&(seat, score)| {
                        (
                            std::cmp::Reverse(score),
                            std::cmp::Reverse(self.active[seat.index()]),
                            seat,
                        )
                    });
                    Some(FourOutcome::Placements(placements))
                } else {
                    None
                }
            }
            FourMode::Teams => {
                let red_alive = self.king(FourSeat::Red).is_some();
                let yellow_alive = self.king(FourSeat::Yellow).is_some();
                let blue_alive = self.king(FourSeat::Blue).is_some();
                let green_alive = self.king(FourSeat::Green).is_some();
                if red_alive || yellow_alive {
                    if blue_alive || green_alive {
                        None
                    } else {
                        Some(FourOutcome::TeamWin { red_yellow: true })
                    }
                } else if blue_alive || green_alive {
                    Some(FourOutcome::TeamWin { red_yellow: false })
                } else {
                    Some(FourOutcome::Draw)
                }
            }
        }
    }

    /// Deterministic rule-state identity used by repetition and tests.
    #[must_use]
    pub fn identity_key(&self) -> u64 {
        let mut key = 0xcbf2_9ce4_8422_2325_u64;
        let mut add = |value: u64| {
            key ^= value;
            key = key.wrapping_mul(0x0000_0100_0000_01b3);
        };
        add(match self.mode {
            FourMode::Ffa => 1,
            FourMode::Teams => 2,
        });
        add(self.turn.index() as u64);
        for cell in self.cells {
            add(cell.map_or(0, |piece| {
                1 + piece.kind as u64 * 4 + piece.owner.index() as u64
            }));
        }
        for value in self.active {
            add(u64::from(value));
        }
        for score in self.scores {
            add(score as u16 as u64);
        }
        key
    }

    /// Serialize the complete local state without claiming Chess.com notation.
    #[must_use]
    pub fn to_state(&self) -> String {
        let mut out = String::new();
        out.push_str(match self.mode {
            FourMode::Ffa => "4pc-ffa ",
            FourMode::Teams => "4pc-teams ",
        });
        out.push(self.turn.key());
        out.push(' ');
        for rank in (0..14).rev() {
            let mut empty = 0;
            for file in 0..14 {
                let Some(square) = Square14::new(file, rank) else {
                    if empty != 0 {
                        write!(out, "{empty}").expect("String write");
                        empty = 0;
                    }
                    out.push('x');
                    continue;
                };
                if let Some(piece) = self.at(square) {
                    if empty != 0 {
                        write!(out, "{empty}").expect("String write");
                        empty = 0;
                    }
                    out.push(piece_owner(piece.owner));
                    out.push(piece_letter(piece.kind));
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
        write!(
            out,
            " active={}{}{}{} scores={},{},{},{} half={} ply={}",
            u8::from(self.active[0]),
            u8::from(self.active[1]),
            u8::from(self.active[2]),
            u8::from(self.active[3]),
            self.scores[0],
            self.scores[1],
            self.scores[2],
            self.scores[3],
            self.halfmove,
            self.ply
        )
        .expect("String write");
        out
    }
}

fn piece_attacks(
    position: &FourPosition,
    piece: FourPiece,
    from: Square14,
    target: Square14,
) -> bool {
    let df = target.file() as i8 - from.file() as i8;
    let dr = target.rank() as i8 - from.rank() as i8;
    match piece.kind {
        PieceKind::Pawn => {
            let (pf, pr) = piece.owner.pawn_step();
            if pf == 0 {
                dr == pr && df.abs() == 1
            } else {
                df == pf && dr.abs() == 1
            }
        }
        PieceKind::Knight => KNIGHT.contains(&(df, dr)),
        PieceKind::King => df.abs() <= 1 && dr.abs() <= 1 && (df != 0 || dr != 0),
        PieceKind::Bishop => clear_slider(position, from, target, &BISHOP),
        PieceKind::Rook => clear_slider(position, from, target, &ROOK),
        PieceKind::Queen => {
            clear_slider(position, from, target, &BISHOP)
                || clear_slider(position, from, target, &ROOK)
        }
    }
}

fn clear_slider(
    position: &FourPosition,
    from: Square14,
    target: Square14,
    directions: &[(i8, i8)],
) -> bool {
    for &(df, dr) in directions {
        let mut cursor = offset(from, df, dr);
        while let Some(square) = cursor {
            if square == target {
                return true;
            }
            if position.at(square).is_some() {
                break;
            }
            cursor = offset(square, df, dr);
        }
    }
    false
}

fn promotion_square(seat: FourSeat, square: Square14, mode: FourMode) -> bool {
    let progress = match seat {
        FourSeat::Red => square.rank(),
        FourSeat::Blue => square.file(),
        FourSeat::Yellow => 13 - square.rank(),
        FourSeat::Green => 13 - square.file(),
    };
    progress
        >= match mode {
            FourMode::Ffa => 7,
            FourMode::Teams => 10,
        }
}

fn playable_squares() -> impl Iterator<Item = Square14> {
    (0..14).flat_map(|rank| (0..14).filter_map(move |file| Square14::new(file, rank)))
}

fn square_index(square: Square14) -> usize {
    usize::from(square.rank()) * 14 + usize::from(square.file())
}

fn offset(square: Square14, df: i8, dr: i8) -> Option<Square14> {
    let file = i16::from(square.file()) + i16::from(df);
    let rank = i16::from(square.rank()) + i16::from(dr);
    if !(0..14).contains(&file) || !(0..14).contains(&rank) {
        return None;
    }
    Square14::new(u8::try_from(file).ok()?, u8::try_from(rank).ok()?)
}

fn square_name(square: Square14) -> String {
    format!("{:x}{:x}", square.file(), square.rank())
}

fn capture_value(piece: PieceKind) -> i16 {
    match piece {
        PieceKind::Pawn => 1,
        PieceKind::Knight => 3,
        PieceKind::Bishop | PieceKind::Rook => 5,
        PieceKind::Queen => 9,
        PieceKind::King => 20,
    }
}

fn piece_letter(piece: PieceKind) -> char {
    match piece {
        PieceKind::Pawn => 'p',
        PieceKind::Knight => 'n',
        PieceKind::Bishop => 'b',
        PieceKind::Rook => 'r',
        PieceKind::Queen => 'q',
        PieceKind::King => 'k',
    }
}

fn piece_owner(seat: FourSeat) -> char {
    match seat {
        FourSeat::Red => 'R',
        FourSeat::Blue => 'B',
        FourSeat::Yellow => 'Y',
        FourSeat::Green => 'G',
    }
}

const KNIGHT: [(i8, i8); 8] = [
    (1, 2),
    (2, 1),
    (2, -1),
    (1, -2),
    (-1, -2),
    (-2, -1),
    (-2, 1),
    (-1, 2),
];
const KING: [(i8, i8); 8] = [
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
    (-1, 0),
    (-1, -1),
    (0, -1),
    (1, -1),
];
const BISHOP: [(i8, i8); 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];
const ROOK: [(i8, i8); 4] = [(1, 0), (-1, 0), (0, 1), (0, -1)];

impl fmt::Display for FourMove {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.notation())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cross_board_has_160_playable_squares() {
        assert_eq!(FourPosition::playable_square_count(), 160);
    }

    #[test]
    fn seat_order_and_teams_are_explicit() {
        assert_eq!(
            FourSeat::ORDER,
            [
                FourSeat::Red,
                FourSeat::Blue,
                FourSeat::Yellow,
                FourSeat::Green
            ]
        );
        assert_eq!(FourSeat::Red.next(), FourSeat::Blue);
        assert_eq!(FourSeat::Red.partner(), FourSeat::Yellow);
        assert_eq!(FourSeat::Blue.partner(), FourSeat::Green);
    }

    #[test]
    fn initial_position_has_four_armies_and_red_to_move() {
        let position = FourPosition::initial(FourMode::Ffa);
        assert_eq!(position.turn, FourSeat::Red);
        for seat in FourSeat::ORDER {
            assert_eq!(
                position
                    .cells
                    .iter()
                    .flatten()
                    .filter(|piece| piece.owner == seat)
                    .count(),
                16
            );
            assert!(position.king(seat).is_some());
        }
    }

    #[test]
    fn ffa_scores_captures_and_auto_promotes() {
        let mut position = FourPosition::initial(FourMode::Ffa);
        position.cells = [None; 196];
        let red_pawn = Square14::new(6, 6).unwrap();
        let target = Square14::new(7, 7).unwrap();
        position.set(
            red_pawn,
            Some(FourPiece {
                owner: FourSeat::Red,
                kind: PieceKind::Pawn,
            }),
        );
        position.set(
            Square14::new(5, 0).unwrap(),
            Some(FourPiece {
                owner: FourSeat::Red,
                kind: PieceKind::King,
            }),
        );
        position.set(
            Square14::new(6, 13).unwrap(),
            Some(FourPiece {
                owner: FourSeat::Yellow,
                kind: PieceKind::King,
            }),
        );
        position.set(
            target,
            Some(FourPiece {
                owner: FourSeat::Blue,
                kind: PieceKind::Rook,
            }),
        );
        let mv = position
            .legal_moves()
            .into_iter()
            .find(|mv| mv.to == target)
            .unwrap();
        assert_eq!(mv.promotion, Some(PieceKind::Queen));
        let next = position.play(mv).unwrap();
        assert_eq!(next.scores[FourSeat::Red.index()], 5);
        assert_eq!(next.at(target).unwrap().kind, PieceKind::Queen);
    }

    #[test]
    fn teams_cannot_capture_partner() {
        let mut position = FourPosition::initial(FourMode::Teams);
        position.cells = [None; 196];
        let red_rook = Square14::new(6, 6).unwrap();
        position.set(
            red_rook,
            Some(FourPiece {
                owner: FourSeat::Red,
                kind: PieceKind::Rook,
            }),
        );
        position.set(
            Square14::new(6, 8).unwrap(),
            Some(FourPiece {
                owner: FourSeat::Yellow,
                kind: PieceKind::Knight,
            }),
        );
        position.set(
            Square14::new(6, 5).unwrap(),
            Some(FourPiece {
                owner: FourSeat::Red,
                kind: PieceKind::King,
            }),
        );
        position.set(
            Square14::new(7, 13).unwrap(),
            Some(FourPiece {
                owner: FourSeat::Blue,
                kind: PieceKind::King,
            }),
        );
        assert!(
            !position
                .legal_moves()
                .iter()
                .any(|mv| mv.from == red_rook && mv.to == Square14::new(6, 8).unwrap())
        );
    }

    #[test]
    fn state_identity_changes_after_move() {
        let position = FourPosition::initial(FourMode::Ffa);
        let mv = position.legal_moves().into_iter().next().unwrap();
        let next = position.play(mv).unwrap();
        assert_ne!(position.identity_key(), next.identity_key());
        assert!(next.to_state().starts_with("4pc-ffa b "));
    }
}
