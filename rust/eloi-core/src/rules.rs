//! Authoritative legal moves and reversible state transitions for 8×8 variants.

use crate::position::{Piece, Position, parse_square, square_name};
use crate::{PieceKind, Player, Square8, Variant};

/// Special state transition associated with a move.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MoveKind {
    /// Ordinary movement, including capture and promotion.
    Normal,
    /// Capture of the pawn behind the en-passant target.
    EnPassant,
    /// Castling, with explicit rook source and destination.
    Castle {
        /// Castling rook source.
        rook_from: Square8,
        /// Castling rook destination.
        rook_to: Square8,
    },
    /// A piece enters the board from the mover's pocket.
    Drop(PieceKind),
}

/// A complete executable move on the two-player board.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Move8 {
    /// Source, absent for pocket drops.
    pub from: Option<Square8>,
    /// Destination.
    pub to: Square8,
    /// Promotion choice.
    pub promotion: Option<PieceKind>,
    /// Additional rule semantics.
    pub kind: MoveKind,
}

impl Move8 {
    /// UCI notation; Chess960 castling uses the rook-origin convention.
    #[must_use]
    pub fn uci(self, chess960: bool) -> String {
        if let MoveKind::Drop(piece) = self.kind {
            return format!(
                "{}@{}",
                piece_letter(piece).to_ascii_uppercase(),
                square_name(self.to)
            );
        }
        let Some(from) = self.from else {
            return String::new();
        };
        let to = match self.kind {
            MoveKind::Castle { rook_from, .. } if chess960 => rook_from,
            _ => self.to,
        };
        let mut text = format!("{}{}", square_name(from), square_name(to));
        if let Some(piece) = self.promotion {
            text.push(piece_letter(piece));
        }
        text
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

/// Opposing participant in a two-player game.
#[must_use]
pub const fn opponent(player: Player) -> Player {
    match player {
        Player::White => Player::Black,
        Player::Black => Player::White,
    }
}

fn sq(index: u8) -> Square8 {
    Square8::new(index).expect("internal square is bounded")
}

fn offset(square: Square8, df: i8, dr: i8) -> Option<Square8> {
    let file = i16::from(square.index() % 8) + i16::from(df);
    let rank = i16::from(square.index() / 8) + i16::from(dr);
    if !(0..8).contains(&file) || !(0..8).contains(&rank) {
        return None;
    }
    Square8::new(u8::try_from(rank * 8 + file).ok()?)
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

impl Position {
    /// Piece on a square.
    #[must_use]
    pub fn at(&self, square: Square8) -> Option<Piece> {
        self.cells[usize::from(square.index())]
    }

    /// King location, absent in kingless or terminal variants.
    #[must_use]
    pub fn king(&self, owner: Player) -> Option<Square8> {
        (0..64)
            .find(|&i| {
                self.at(sq(i))
                    .is_some_and(|p| p.owner == owner && p.kind == PieceKind::King)
            })
            .map(sq)
    }

    /// Geometric orthodox attack detection, independent of move legality.
    #[must_use]
    pub fn attacked(&self, target: Square8, by: Player) -> bool {
        self.attackers(target, by) != 0
    }

    /// Proven orthodox dead material. Variant-specific objectives must not use
    /// orthodox material adjudication, and Crazyhouse pockets require separate rules.
    #[must_use]
    pub fn insufficient_material(&self) -> bool {
        if !matches!(self.variant, Variant::Standard | Variant::Chess960) {
            return false;
        }
        let mut knights = 0;
        let mut bishops = 0;
        let mut bishop_color = None;
        let mut same_color = true;
        for (square, piece) in self.cells.iter().enumerate() {
            let Some(piece) = piece else {
                continue;
            };
            match piece.kind {
                PieceKind::Pawn | PieceKind::Rook | PieceKind::Queen => return false,
                PieceKind::Knight => knights += 1,
                PieceKind::Bishop => {
                    bishops += 1;
                    let color = (square % 8 + square / 8) % 2;
                    if bishop_color.is_some_and(|previous| previous != color) {
                        same_color = false;
                    }
                    bishop_color = Some(color);
                }
                PieceKind::King => {}
            }
        }
        knights + bishops <= 1 || (knights == 0 && same_color)
    }

    /// Count geometric attackers without removing blockers or testing king safety.
    #[must_use]
    pub fn attackers(&self, target: Square8, by: Player) -> u8 {
        let mut count = 0;
        let pawn_direction = if by == Player::White { -1 } else { 1 };
        for df in [-1, 1] {
            if offset(target, df, pawn_direction)
                .and_then(|s| self.at(s))
                .is_some_and(|p| p.owner == by && p.kind == PieceKind::Pawn)
            {
                count += 1;
            }
        }
        for (df, dr) in KNIGHT {
            if offset(target, df, dr)
                .and_then(|s| self.at(s))
                .is_some_and(|p| p.owner == by && p.kind == PieceKind::Knight)
            {
                count += 1;
            }
        }
        for (df, dr) in KING {
            if offset(target, df, dr)
                .and_then(|s| self.at(s))
                .is_some_and(|p| p.owner == by && p.kind == PieceKind::King)
            {
                count += 1;
            }
        }
        for (directions, kind) in [
            (&BISHOP[..], PieceKind::Bishop),
            (&ROOK[..], PieceKind::Rook),
        ] {
            for &(df, dr) in directions {
                let mut cursor = offset(target, df, dr);
                while let Some(s) = cursor {
                    if let Some(p) = self.at(s) {
                        if p.owner == by && (p.kind == kind || p.kind == PieceKind::Queen) {
                            count += 1;
                        }
                        break;
                    }
                    cursor = offset(s, df, dr);
                }
            }
        }
        count
    }

    /// Variant-aware king threat status.
    #[must_use]
    pub fn in_check(&self, player: Player) -> bool {
        if self.variant == Variant::Antichess {
            return false;
        }
        let Some(king) = self.king(player) else {
            return !(self.variant == Variant::Horde && player == Player::White);
        };
        if self.variant == Variant::Atomic {
            let enemy = opponent(player);
            return self.pseudo_for(enemy, false).into_iter().any(|m| {
                m.to == king
                    && self.is_capture(m)
                    && self
                        .king(enemy)
                        .is_none_or(|k| !explosion_contains(m.to, k))
            });
        }
        self.attacked(king, opponent(player))
    }

    /// Whether a generated move captures a piece.
    #[must_use]
    pub fn is_capture(&self, mv: Move8) -> bool {
        !matches!(mv.kind, MoveKind::Castle { .. } | MoveKind::Drop(_))
            && (self.at(mv.to).is_some() || mv.kind == MoveKind::EnPassant)
    }

    fn append_pawn(&self, moves: &mut Vec<Move8>, from: Square8, to: Square8, kind: MoveKind) {
        if to.index() / 8 == 0 || to.index() / 8 == 7 {
            for promotion in [
                PieceKind::Queen,
                PieceKind::Rook,
                PieceKind::Bishop,
                PieceKind::Knight,
            ] {
                moves.push(Move8 {
                    from: Some(from),
                    to,
                    promotion: Some(promotion),
                    kind,
                });
            }
            if self.variant == Variant::Antichess {
                moves.push(Move8 {
                    from: Some(from),
                    to,
                    promotion: Some(PieceKind::King),
                    kind,
                });
            }
        } else {
            moves.push(Move8 {
                from: Some(from),
                to,
                promotion: None,
                kind,
            });
        }
    }

    fn pawn_moves(&self, player: Player, from: Square8, moves: &mut Vec<Move8>) {
        let direction = if player == Player::White { 1 } else { -1 };
        if let Some(to) = offset(from, 0, direction).filter(|&s| self.at(s).is_none()) {
            self.append_pawn(moves, from, to, MoveKind::Normal);
            let start = if player == Player::White { 1 } else { 6 };
            if (from.index() / 8 == start
                || (self.variant == Variant::Horde
                    && player == Player::White
                    && from.index() / 8 == 0))
                && let Some(jump) = offset(to, 0, direction).filter(|&s| self.at(s).is_none())
            {
                moves.push(Move8 {
                    from: Some(from),
                    to: jump,
                    promotion: None,
                    kind: MoveKind::Normal,
                });
            }
        }
        for df in [-1, 1] {
            if let Some(to) = offset(from, df, direction) {
                if self.at(to).is_some_and(|p| {
                    p.owner != player
                        && (p.kind != PieceKind::King
                            || matches!(self.variant, Variant::Antichess | Variant::Atomic))
                }) {
                    self.append_pawn(moves, from, to, MoveKind::Normal);
                } else if player == self.turn
                    && Some(to) == self.en_passant
                    && self.at(to).is_none()
                    && offset(to, 0, -direction)
                        .and_then(|s| self.at(s))
                        .is_some_and(|p| p.owner != player && p.kind == PieceKind::Pawn)
                {
                    self.append_pawn(moves, from, to, MoveKind::EnPassant);
                }
            }
        }
    }

    fn pseudo_for(&self, player: Player, castles: bool) -> Vec<Move8> {
        let mut moves = Vec::with_capacity(64);
        for index in 0..64 {
            let from = sq(index);
            let Some(piece) = self.at(from).filter(|p| p.owner == player) else {
                continue;
            };
            if piece.kind == PieceKind::Pawn {
                self.pawn_moves(player, from, &mut moves);
                continue;
            }
            let directions: &[(i8, i8)] = match piece.kind {
                PieceKind::Knight => &KNIGHT,
                PieceKind::King | PieceKind::Queen => &KING,
                PieceKind::Bishop => &BISHOP,
                PieceKind::Rook => &ROOK,
                PieceKind::Pawn => unreachable!(),
            };
            let sliding = matches!(
                piece.kind,
                PieceKind::Bishop | PieceKind::Rook | PieceKind::Queen
            );
            for &(df, dr) in directions {
                let mut cursor = offset(from, df, dr);
                while let Some(to) = cursor {
                    let victim = self.at(to);
                    if victim.is_some_and(|p| p.owner == player) {
                        break;
                    }
                    if victim.is_none_or(|p| {
                        p.kind != PieceKind::King
                            || matches!(self.variant, Variant::Antichess | Variant::Atomic)
                    }) {
                        moves.push(Move8 {
                            from: Some(from),
                            to,
                            promotion: None,
                            kind: MoveKind::Normal,
                        });
                    }
                    if victim.is_some() || !sliding {
                        break;
                    }
                    cursor = offset(to, df, dr);
                }
            }
        }
        if castles && self.variant != Variant::Antichess {
            self.append_castles(player, &mut moves);
        }
        if self.variant == Variant::Crazyhouse {
            let owner = usize::from(player == Player::Black);
            for (kind, count) in [
                PieceKind::Pawn,
                PieceKind::Knight,
                PieceKind::Bishop,
                PieceKind::Rook,
                PieceKind::Queen,
            ]
            .into_iter()
            .zip(self.pockets[owner])
            {
                if count == 0 {
                    continue;
                }
                for i in 0..64 {
                    let to = sq(i);
                    if self.at(to).is_none()
                        && !(kind == PieceKind::Pawn && (i / 8 == 0 || i / 8 == 7))
                    {
                        moves.push(Move8 {
                            from: None,
                            to,
                            promotion: None,
                            kind: MoveKind::Drop(kind),
                        });
                    }
                }
            }
        }
        moves
    }

    fn append_castles(&self, player: Player, moves: &mut Vec<Move8>) {
        let Some(king) = self.king(player) else {
            return;
        };
        if self.in_check(player) {
            return;
        }
        for right in self.castling.iter().filter(|r| r.owner == player) {
            let base = king.index() / 8 * 8;
            let kingside = right.rook.index() > king.index();
            let king_to = sq(base + if kingside { 6 } else { 2 });
            let rook_to = sq(base + if kingside { 5 } else { 3 });
            let paths = [(king, king_to), (right.rook, rook_to)];
            let mut clear = true;
            for (start, end) in paths {
                for i in start.index().min(end.index())..=start.index().max(end.index()) {
                    if i != king.index() && i != right.rook.index() && self.at(sq(i)).is_some() {
                        clear = false;
                    }
                }
            }
            if !clear {
                continue;
            }
            for i in king.index().min(king_to.index())..=king.index().max(king_to.index()) {
                let mut transit = self.clone();
                transit.cells[usize::from(king.index())] = None;
                if i == right.rook.index() {
                    transit.cells[usize::from(i)] = None;
                }
                transit.cells[usize::from(i)] = self.at(king);
                if transit.in_check(player) {
                    clear = false;
                    break;
                }
            }
            if clear {
                moves.push(Move8 {
                    from: Some(king),
                    to: king_to,
                    promotion: None,
                    kind: MoveKind::Castle {
                        rook_from: right.rook,
                        rook_to,
                    },
                });
            }
        }
    }

    fn apply_generated(&self, mv: Move8) -> Option<Self> {
        let mut next = self.clone();
        let captured = self.at(mv.to);
        let capture = self.is_capture(mv);
        let moving = if let MoveKind::Drop(kind) = mv.kind {
            let slot = pocket_slot(kind)?;
            let owner = usize::from(self.turn == Player::Black);
            next.pockets[owner][slot] = next.pockets[owner][slot].checked_sub(1)?;
            Piece {
                owner: self.turn,
                kind,
                promoted: false,
            }
        } else {
            let from = mv.from?;
            let piece = self.at(from)?;
            next.cells[usize::from(from.index())] = None;
            piece
        };
        if let MoveKind::Castle { rook_from, rook_to } = mv.kind {
            let rook = self.at(rook_from)?;
            next.cells[usize::from(rook_from.index())] = None;
            next.cells[usize::from(rook_to.index())] = Some(rook);
        }
        if mv.kind == MoveKind::EnPassant {
            let victim = offset(mv.to, 0, if self.turn == Player::White { -1 } else { 1 })?;
            next.cells[usize::from(victim.index())] = None;
        }
        next.cells[usize::from(mv.to.index())] = Some(Piece {
            kind: mv.promotion.unwrap_or(moving.kind),
            promoted: moving.promoted
                || (mv.promotion.is_some() && self.variant == Variant::Crazyhouse),
            ..moving
        });
        if capture && self.variant == Variant::Crazyhouse {
            let kind = captured.map_or(PieceKind::Pawn, |p| {
                if p.promoted { PieceKind::Pawn } else { p.kind }
            });
            let slot = pocket_slot(kind)?;
            let owner = usize::from(self.turn == Player::Black);
            next.pockets[owner][slot] = next.pockets[owner][slot].checked_add(1)?;
        }
        if capture && self.variant == Variant::Atomic {
            for i in 0..64 {
                if explosion_contains(mv.to, sq(i))
                    && (sq(i) == mv.to || next.at(sq(i)).is_some_and(|p| p.kind != PieceKind::Pawn))
                {
                    next.cells[usize::from(i)] = None;
                }
            }
        }
        next.castling.retain(|r| {
            !(moving.kind == PieceKind::King && r.owner == self.turn)
                && Some(r.rook) != mv.from
                && r.rook != mv.to
                && next.cells[usize::from(r.rook.index())]
                    .is_some_and(|p| p.kind == PieceKind::Rook && p.owner == r.owner)
        });
        next.en_passant = if moving.kind == PieceKind::Pawn
            && mv
                .from
                .is_some_and(|s| s.index().abs_diff(mv.to.index()) == 16)
        {
            mv.from
                .and_then(|from| Square8::new(u8::midpoint(from.index(), mv.to.index())))
        } else {
            None
        };
        next.halfmove = if capture || moving.kind == PieceKind::Pawn {
            0
        } else {
            self.halfmove.checked_add(1)?
        };
        next.fullmove = self
            .fullmove
            .checked_add(u32::from(self.turn == Player::Black))?;
        next.turn = opponent(self.turn);
        Some(next)
    }

    /// Generate legal moves and their validated resulting positions.
    #[must_use]
    pub fn legal_children(&self) -> Vec<(Move8, Self)> {
        if self.immediate_winner().is_some() {
            return Vec::new();
        }
        let mut legal: Vec<_> = self
            .pseudo_for(self.turn, true)
            .into_iter()
            .filter_map(|mv| {
                self.apply_generated(mv).and_then(|next| {
                    let valid = self.variant == Variant::Antichess
                        || (self.variant == Variant::Atomic
                            && next.king(opponent(self.turn)).is_none()
                            && next.king(self.turn).is_some())
                        || !next.in_check(self.turn);
                    valid.then_some((mv, next))
                })
            })
            .collect();
        if self.variant == Variant::Antichess && legal.iter().any(|(m, _)| self.is_capture(*m)) {
            legal.retain(|(m, _)| self.is_capture(*m));
        }
        legal
    }

    /// Generate legal moves under this position's variant rules.
    #[must_use]
    pub fn legal_moves(&self) -> Vec<Move8> {
        self.legal_children()
            .into_iter()
            .map(|(mv, _)| mv)
            .collect()
    }

    /// Geometric candidate moves for diagnostics and variant pressure terms.
    #[must_use]
    pub fn pseudo_moves(&self, player: Player) -> Vec<Move8> {
        self.pseudo_for(player, false)
    }

    /// Rule-state identity, including only genuinely available en-passant rights.
    #[must_use]
    pub fn identity_key(&self, has_legal_en_passant: bool) -> u64 {
        let mut key = 0xcbf2_9ce4_8422_2325_u64;
        let mut add = |value: u64| {
            key ^= value;
            key = key.wrapping_mul(0x0000_0100_0000_01b3);
        };
        add(self.variant as u64);
        add(self.turn as u64);
        for piece in self.cells {
            add(piece.map_or(0, |p| {
                1 + p.kind as u64 + 8 * p.owner as u64 + 64 * u64::from(p.promoted)
            }));
        }
        for right in &self.castling {
            add(1 + right.owner as u64 * 64 + u64::from(right.rook.index()));
        }
        add(0xff);
        for pocket in self.pockets {
            for count in pocket {
                add(u64::from(count));
            }
        }
        if has_legal_en_passant {
            add(self.en_passant.map_or(0, |s| u64::from(s.index()) + 1));
        }
        key
    }

    /// Immediate rule winner without generating a legal list.
    #[must_use]
    pub fn terminal_winner(&self) -> Option<Player> {
        self.immediate_winner()
    }

    /// Apply an action only if it belongs to the authoritative legal list.
    #[must_use]
    pub fn play(&self, mv: Move8) -> Option<Self> {
        self.legal_children()
            .into_iter()
            .find(|(legal, _)| *legal == mv)
            .map(|(_, next)| next)
    }

    /// Resolve and apply exact UCI move notation, including drops.
    #[must_use]
    pub fn play_uci(&self, text: &str) -> Option<Self> {
        let mv = self
            .legal_moves()
            .into_iter()
            .find(|m| m.uci(self.variant == Variant::Chess960) == text)?;
        self.apply_generated(mv)
    }

    /// Resolve an orthodox coordinate move through the legal move list.
    #[must_use]
    pub fn parse_move(&self, text: &str) -> Option<Move8> {
        if !text.is_ascii() {
            return None;
        }
        if text.len() >= 4 && !text.contains('@') {
            parse_square(&text[..2])?;
            parse_square(&text[2..4])?;
        }
        self.legal_moves()
            .into_iter()
            .find(|m| m.uci(self.variant == Variant::Chess960) == text)
    }

    fn immediate_winner(&self) -> Option<Player> {
        match self.variant {
            Variant::Atomic => {
                if self.king(Player::White).is_none() {
                    return Some(Player::Black);
                }
                if self.king(Player::Black).is_none() {
                    return Some(Player::White);
                }
            }
            Variant::KingOfTheHill => {
                for owner in [opponent(self.turn), self.turn] {
                    if self
                        .king(owner)
                        .is_some_and(|s| [27, 28, 35, 36].contains(&s.index()))
                    {
                        return Some(owner);
                    }
                }
            }
            Variant::Horde
                if !self
                    .cells
                    .iter()
                    .flatten()
                    .any(|p| p.owner == Player::White) =>
            {
                return Some(Player::Black);
            }
            _ => {}
        }
        None
    }

    /// Variant or checkmate winner; stalemates and claimable draws are separate.
    #[must_use]
    pub fn winner(&self) -> Option<Player> {
        if let Some(winner) = self.immediate_winner() {
            return Some(winner);
        }
        if self.legal_moves().is_empty() {
            if self.variant == Variant::Antichess {
                return Some(self.turn);
            }
            if self.in_check(self.turn) {
                return Some(opponent(self.turn));
            }
        }
        None
    }

    /// Count legal leaf nodes. Used for move-generation validation.
    #[must_use]
    pub fn perft(&self, depth: u8) -> u64 {
        if depth == 0 {
            return 1;
        }
        let moves = self.legal_moves();
        if depth == 1 {
            return moves.len() as u64;
        }
        moves
            .into_iter()
            .filter_map(|m| self.apply_generated(m))
            .map(|p| p.perft(depth - 1))
            .sum()
    }
}

fn pocket_slot(kind: PieceKind) -> Option<usize> {
    Some(match kind {
        PieceKind::Pawn => 0,
        PieceKind::Knight => 1,
        PieceKind::Bishop => 2,
        PieceKind::Rook => 3,
        PieceKind::Queen => 4,
        PieceKind::King => return None,
    })
}

fn explosion_contains(center: Square8, square: Square8) -> bool {
    (center.index() % 8).abs_diff(square.index() % 8) <= 1
        && (center.index() / 8).abs_diff(square.index() / 8) <= 1
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::position::INITIAL_FEN;

    #[test]
    fn starting_position_perft() {
        let p = Position::from_fen(INITIAL_FEN, Variant::Standard).unwrap();
        for (depth, expected) in [(1, 20), (2, 400), (3, 8902), (4, 197_281)] {
            assert_eq!(p.perft(depth), expected);
        }
    }

    #[test]
    fn en_passant_cannot_expose_king() {
        let p =
            Position::from_fen("4r1k1/8/8/3pP3/8/8/8/4K3 w - d6 0 1", Variant::Standard).unwrap();
        assert!(p.play_uci("e5d6").is_none());
    }

    #[test]
    fn chess960_overlapping_castle_preserves_both_pieces() {
        let p = Position::from_fen("4k3/8/8/8/8/8/8/5KR1 w G - 0 1", Variant::Chess960).unwrap();
        let next = p.play_uci("f1g1").unwrap();
        assert_eq!(
            next.at(parse_square("g1").unwrap()).unwrap().kind,
            PieceKind::King
        );
        assert_eq!(
            next.at(parse_square("f1").unwrap()).unwrap().kind,
            PieceKind::Rook
        );
        assert!(next.castling.is_empty());
    }

    #[test]
    fn antichess_forces_capture_and_allows_king_promotion() {
        let p = Position::from_fen("8/P7/8/8/8/8/1p6/R7 w - - 0 1", Variant::Antichess).unwrap();
        assert!(p.play_uci("a7a8k").is_some());
        let p = Position::from_fen("8/8/8/8/8/8/p7/R7 w - - 0 1", Variant::Antichess).unwrap();
        assert_eq!(p.legal_moves().len(), 1);
        assert!(p.play_uci("a1a2").is_some());
    }

    #[test]
    fn crazyhouse_capture_reverts_promoted_piece_and_masks_pawn_drops() {
        let p =
            Position::from_fen("4k3/8/8/8/8/q~7/R7/4K3[] w - - 0 1", Variant::Crazyhouse).unwrap();
        let next = p.play_uci("a2a3").unwrap();
        assert_eq!(next.pockets[0][0], 1);
        let p =
            Position::from_fen("4k3/8/8/8/8/8/8/4K3[P] w - - 0 1", Variant::Crazyhouse).unwrap();
        assert!(p.play_uci("P@a1").is_none());
        assert_eq!(p.play_uci("P@a4").unwrap().pockets[0][0], 0);
    }

    #[test]
    fn atomic_explosion_and_hill_win() {
        let p = Position::from_fen("4k3/4p3/8/8/8/8/8/K3R3 w - - 0 1", Variant::Atomic).unwrap();
        assert_eq!(p.play_uci("e1e7").unwrap().winner(), Some(Player::White));
        let p = Position::from_fen("7k/8/8/8/8/4K3/8/8 w - - 0 1", Variant::KingOfTheHill).unwrap();
        assert_eq!(p.play_uci("e3e4").unwrap().winner(), Some(Player::White));
    }

    #[test]
    fn dead_material_does_not_cross_variant_objectives() {
        for (fen, expected) in [
            ("7k/8/8/8/8/8/8/K7 w - - 0 1", true),
            ("7k/8/8/8/8/8/8/KN6 w - - 0 1", true),
            ("7k/8/8/8/8/8/8/KB6 w - - 0 1", true),
            ("7k/8/8/8/8/8/8/KNN5 w - - 0 1", false),
            ("7k/8/8/8/8/8/8/KBB5 w - - 0 1", false),
            ("7k/8/8/8/8/8/8/KB1B4 w - - 0 1", true),
            ("7k/8/8/8/8/8/P7/K7 w - - 0 1", false),
        ] {
            let position = Position::from_fen(fen, Variant::Standard).unwrap();
            assert_eq!(position.insufficient_material(), expected, "{fen}");
        }
        for variant in [
            Variant::KingOfTheHill,
            Variant::Atomic,
            Variant::Antichess,
            Variant::Horde,
            Variant::Crazyhouse,
        ] {
            assert!(
                !Position::from_fen("7k/8/8/8/8/8/8/K7 w - - 0 1", variant)
                    .unwrap()
                    .insufficient_material()
            );
        }
    }
}
