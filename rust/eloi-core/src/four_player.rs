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
    /// Per-seat castling rights: low-file rook = 1, high-file rook = 2.
    pub castling: [u8; 4],
    /// Double-pushed pawn and passed square, valid until that owner's next turn.
    pub en_passant: [Option<(Square14, Square14)>; 4],
}

/// Local four-player game with reversible history and local terminal actions.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FourGame {
    position: FourPosition,
    history: Vec<(FourPosition, FourMove)>,
    resignation: Option<FourSeat>,
    timeout: Option<FourSeat>,
}

impl FourGame {
    /// Begin local history at an explicitly loaded rule state.
    #[must_use]
    pub fn from_position(position: FourPosition) -> Self {
        Self {
            position,
            history: Vec::new(),
            resignation: None,
            timeout: None,
        }
    }
    /// Create a local game from the standard four-player initial setup.
    #[must_use]
    pub fn new(mode: FourMode) -> Self {
        Self {
            position: FourPosition::initial(mode),
            history: Vec::new(),
            resignation: None,
            timeout: None,
        }
    }

    /// Current authoritative four-player position.
    #[must_use]
    pub const fn position(&self) -> &FourPosition {
        &self.position
    }

    /// Apply a legal move and preserve the full previous state.
    pub fn push(&mut self, mv: FourMove) -> bool {
        if self.outcome().is_some() {
            return false;
        }
        let Some(next) = self.position.play(mv) else {
            return false;
        };
        self.history
            .push((std::mem::replace(&mut self.position, next), mv));
        true
    }

    /// Apply exact compact four-player move notation.
    pub fn push_notation(&mut self, text: &str) -> bool {
        let Some(mv) = self.position.parse_move(text) else {
            return false;
        };
        self.push(mv)
    }

    /// Undo one local ply. Resignation and timeout terminal actions are sticky
    /// and are not undone by move navigation.
    pub fn pop(&mut self) -> bool {
        let Some((previous, _)) = self.history.pop() else {
            return false;
        };
        self.position = previous;
        true
    }

    /// Moves since the starting position.
    pub fn moves(&self) -> impl Iterator<Item = FourMove> + '_ {
        self.history.iter().map(|(_, mv)| *mv)
    }

    /// Mark a local resignation.
    pub fn resign(&mut self, seat: FourSeat) {
        self.resignation = Some(seat);
        if self.position.mode == FourMode::Ffa {
            self.position.active[seat.index()] = false;
        }
    }

    /// Mark a local timeout.
    pub fn timeout(&mut self, seat: FourSeat) {
        self.timeout = Some(seat);
        if self.position.mode == FourMode::Ffa {
            self.position.active[seat.index()] = false;
        }
    }

    /// Current terminal result, including local resignation and timeout.
    #[must_use]
    pub fn outcome(&self) -> Option<FourOutcome> {
        if let Some(seat) = self.resignation.or(self.timeout) {
            return Some(self.forfeit_outcome(seat));
        }
        if self.position.mode == FourMode::Teams {
            let identity = self.position.identity_key();
            if self
                .history
                .iter()
                .filter(|(p, _)| p.identity_key() == identity)
                .count()
                >= 2
            {
                return Some(FourOutcome::Draw);
            }
        }
        self.position.outcome()
    }

    fn forfeit_outcome(&self, seat: FourSeat) -> FourOutcome {
        match self.position.mode {
            FourMode::Ffa => {
                let mut placements: Vec<_> = FourSeat::ORDER
                    .into_iter()
                    .map(|candidate| {
                        let penalty = if candidate == seat { -10_000 } else { 0 };
                        (candidate, self.position.scores[candidate.index()] + penalty)
                    })
                    .collect();
                placements.sort_by_key(|&(candidate, score)| (std::cmp::Reverse(score), candidate));
                FourOutcome::Placements(placements)
            }
            FourMode::Teams => FourOutcome::TeamWin {
                red_yellow: !matches!(seat, FourSeat::Red | FourSeat::Yellow),
            },
        }
    }
}

impl FourPosition {
    /// Parse Eloi's complete four-player state. Malformed rule state is rejected.
    pub fn from_state(text: &str) -> Result<Self, &'static str> {
        let fields: Vec<_> = text.split_whitespace().collect();
        if fields.len() != 9 {
            return Err("expected complete four-player state");
        }
        let mode = match fields[0] {
            "4pc-teams" => FourMode::Teams,
            "4pc-ffa" => FourMode::Ffa,
            _ => return Err("unknown mode"),
        };
        let mut p = Self::initial(mode);
        p.cells = [None; 196];
        p.turn = FourSeat::ORDER
            .into_iter()
            .find(|s| s.key().to_string() == fields[1])
            .ok_or("invalid turn")?;
        let ranks: Vec<_> = fields[2].split('/').collect();
        if ranks.len() != 14 {
            return Err("expected fourteen ranks");
        }
        for (row, rank) in ranks.into_iter().enumerate() {
            let mut chars = rank.chars().peekable();
            let mut file = 0u8;
            while let Some(c) = chars.next() {
                if c.is_ascii_digit() {
                    let mut digits = c.to_string();
                    while chars.peek().is_some_and(char::is_ascii_digit) {
                        digits.push(chars.next().unwrap());
                    }
                    let count = digits.parse::<u8>().map_err(|_| "invalid empty count")?;
                    if count == 0 {
                        return Err("zero empty run");
                    }
                    for _ in 0..count {
                        if Square14::new(file, 13 - row as u8).is_none() {
                            return Err("empty run crosses corner");
                        }
                        file = file.checked_add(1).ok_or("rank overflow")?;
                    }
                } else if c == 'x' {
                    if file >= 14 || Square14::new(file, 13 - row as u8).is_some() {
                        return Err("invalid corner");
                    }
                    file += 1;
                } else {
                    let owner = FourSeat::ORDER
                        .into_iter()
                        .find(|s| piece_owner(*s) == c)
                        .ok_or("invalid owner")?;
                    let kind = match chars.next() {
                        Some('p') => PieceKind::Pawn,
                        Some('n') => PieceKind::Knight,
                        Some('b') => PieceKind::Bishop,
                        Some('r') => PieceKind::Rook,
                        Some('q') => PieceKind::Queen,
                        Some('k') => PieceKind::King,
                        _ => return Err("invalid piece"),
                    };
                    let square =
                        Square14::new(file, 13 - row as u8).ok_or("piece outside board")?;
                    p.set(square, Some(FourPiece { owner, kind }));
                    file += 1;
                }
            }
            if file != 14 {
                return Err("rank length");
            }
        }
        let value = |index: usize, prefix: &str| {
            fields[index]
                .strip_prefix(prefix)
                .ok_or("missing state field")
        };
        let active = value(3, "active=")?.as_bytes();
        let castle = value(7, "castle=")?.as_bytes();
        if active.len() != 4 || castle.len() != 4 {
            return Err("invalid seat state");
        }
        for i in 0..4 {
            p.active[i] = match active[i] {
                b'1' => true,
                b'0' => false,
                _ => return Err("invalid active flag"),
            };
            p.castling[i] = match castle[i] {
                b'0'..=b'3' => castle[i] - b'0',
                _ => return Err("invalid castle flag"),
            };
        }
        let scores: Vec<_> = value(4, "scores=")?.split(',').collect();
        let ep: Vec<_> = value(8, "ep=")?.split(',').collect();
        if scores.len() != 4 || ep.len() != 4 {
            return Err("invalid seat arrays");
        }
        for i in 0..4 {
            p.scores[i] = scores[i].parse().map_err(|_| "invalid score")?;
            p.en_passant[i] = if ep[i] == "-" {
                None
            } else {
                let bytes = ep[i].as_bytes();
                if bytes.len() != 4 || !ep[i].is_ascii() {
                    return Err("invalid en passant");
                }
                let square = |start| -> Result<Square14, &'static str> {
                    let f = (bytes[start] as char).to_digit(16).ok_or("ep file")? as u8;
                    let r = (bytes[start + 1] as char).to_digit(16).ok_or("ep rank")? as u8;
                    Square14::new(f, r).ok_or("ep corner")
                };
                let pawn = square(0)?;
                let passed = square(2)?;
                let seat = FourSeat::ORDER[i];
                let (df, dr) = seat.pawn_step();
                if p.at(pawn)
                    != Some(FourPiece {
                        owner: seat,
                        kind: PieceKind::Pawn,
                    })
                    || offset(passed, df, dr) != Some(pawn)
                    || p.at(passed).is_some()
                    || seat == p.turn
                {
                    return Err("inconsistent en passant");
                }
                Some((pawn, passed))
            };
        }
        p.halfmove = value(5, "half=")?.parse().map_err(|_| "invalid halfmove")?;
        p.ply = value(6, "ply=")?.parse().map_err(|_| "invalid ply")?;
        for seat in FourSeat::ORDER {
            if p.cells
                .iter()
                .flatten()
                .filter(|piece| piece.owner == seat && piece.kind == PieceKind::King)
                .count()
                != 1
            {
                return Err("expected one king per seat");
            }
            let (king, rooks, _) = castle_geometry(seat);
            for side in 0..2 {
                if p.castling[seat.index()] & (1 << side) != 0
                    && (p.at(king)
                        != Some(FourPiece {
                            owner: seat,
                            kind: PieceKind::King,
                        })
                        || p.at(rooks[side])
                            != Some(FourPiece {
                                owner: seat,
                                kind: PieceKind::Rook,
                            }))
                {
                    return Err("inconsistent castling rights");
                }
            }
        }
        Ok(p)
    }
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
            castling: [3; 4],
            en_passant: [None; 4],
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
        if !self.active[self.turn.index()] {
            return Vec::new();
        }
        self.moves_for_turn()
    }

    fn moves_for_turn(&self) -> Vec<FourMove> {
        self.legal_successors()
            .into_iter()
            .map(|(mv, _)| mv)
            .collect()
    }

    /// Generate each legal child exactly once for search, retaining legality ownership here.
    #[must_use]
    pub fn legal_successors(&self) -> Vec<(FourMove, Self)> {
        if !self.active[self.turn.index()] || self.outcome().is_some() {
            return Vec::new();
        }
        self.pseudo_moves(self.turn)
            .into_iter()
            .filter_map(|mv| {
                let next = self.apply_unchecked(mv)?;
                (!next.king_attacked(self.turn)).then_some((mv, next))
            })
            .collect()
    }

    /// Resolve exact compact move notation through the legal move list.
    #[must_use]
    pub fn parse_move(&self, text: &str) -> Option<FourMove> {
        if !text.is_ascii() {
            return None;
        }
        self.legal_moves()
            .into_iter()
            .find(|mv| mv.notation() == text)
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
                    self.append_castling(from, seat, &mut moves);
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
            let home = match seat {
                FourSeat::Red => from.rank() == 1,
                FourSeat::Blue => from.file() == 1,
                FourSeat::Yellow => from.rank() == 12,
                FourSeat::Green => from.file() == 12,
            };
            if home && let Some(end) = offset(to, df, dr).filter(|&end| self.at(end).is_none()) {
                self.append_promotion_aware(from, end, moves);
            }
        }
        let captures = if df == 0 {
            [(-1, dr), (1, dr)]
        } else {
            [(df, -1), (df, 1)]
        };
        for (cdf, cdr) in captures {
            if let Some(to) = offset(from, cdf, cdr)
                && (self.at(to).is_some_and(|piece| {
                    !self.allied(seat, piece.owner) && piece.kind != PieceKind::King
                }) || (self.at(to).is_none()
                    && self.en_passant.iter().flatten().any(|&(pawn, passed)| {
                        passed == to
                            && self.at(pawn).is_some_and(|p| {
                                p.kind == PieceKind::Pawn && !self.allied(seat, p.owner)
                            })
                    })))
            {
                self.append_promotion_aware(from, to, moves);
            }
        }
    }

    fn append_castling(&self, from: Square14, seat: FourSeat, moves: &mut Vec<FourMove>) {
        let (king, rooks, axis) = castle_geometry(seat);
        if from != king || self.king_attacked(seat) {
            return;
        }
        for (side, rook) in rooks.into_iter().enumerate() {
            if self.castling[seat.index()] & (1 << side) == 0
                || self.at(rook)
                    != Some(FourPiece {
                        owner: seat,
                        kind: PieceKind::Rook,
                    })
            {
                continue;
            }
            let sign = if side == 0 { -1 } else { 1 };
            let (df, dr) = (axis.0 * sign, axis.1 * sign);
            let mut cursor = offset(from, df, dr);
            let mut clear = true;
            while let Some(square) = cursor {
                if square == rook {
                    break;
                }
                if self.at(square).is_some() {
                    clear = false;
                    break;
                }
                cursor = offset(square, df, dr);
            }
            if !clear {
                continue;
            }
            let transit = offset(from, df, dr).expect("home transit");
            let to = offset(transit, df, dr).expect("home destination");
            let mut probe = self.clone();
            probe.set(from, None);
            probe.set(
                transit,
                Some(FourPiece {
                    owner: seat,
                    kind: PieceKind::King,
                }),
            );
            if !probe.king_attacked(seat) {
                moves.push(FourMove {
                    from,
                    to,
                    promotion: None,
                });
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
        let has = |square: Option<Square14>, kind| {
            square
                .and_then(|sq| self.at(sq))
                .is_some_and(|p| p.owner == attacker && p.kind == kind)
        };
        for (df, dr) in KNIGHT {
            if has(offset(target, df, dr), PieceKind::Knight) {
                return true;
            }
        }
        for (df, dr) in KING {
            if has(offset(target, df, dr), PieceKind::King) {
                return true;
            }
        }
        let (pf, pr) = attacker.pawn_step();
        let captures = if pf == 0 {
            [(-1, pr), (1, pr)]
        } else {
            [(pf, -1), (pf, 1)]
        };
        for (df, dr) in captures {
            if has(offset(target, -df, -dr), PieceKind::Pawn) {
                return true;
            }
        }
        for (df, dr) in KING {
            let diagonal = df != 0 && dr != 0;
            let mut cursor = offset(target, df, dr);
            while let Some(square) = cursor {
                if let Some(piece) = self.at(square) {
                    if piece.owner == attacker
                        && (piece.kind == PieceKind::Queen
                            || piece.kind
                                == if diagonal {
                                    PieceKind::Bishop
                                } else {
                                    PieceKind::Rook
                                })
                    {
                        return true;
                    }
                    break;
                }
                cursor = offset(square, df, dr);
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
        let capture_square = if moving.kind == PieceKind::Pawn && self.at(mv.to).is_none() {
            self.en_passant
                .iter()
                .flatten()
                .find_map(|&(pawn, passed)| {
                    (passed == mv.to
                        && self
                            .at(pawn)
                            .is_some_and(|p| !self.allied(moving.owner, p.owner)))
                    .then_some(pawn)
                })
                .unwrap_or(mv.to)
        } else {
            mv.to
        };
        for seat in FourSeat::ORDER {
            let (_, rooks, _) = castle_geometry(seat);
            for (side, rook) in rooks.into_iter().enumerate() {
                if mv.from == rook || capture_square == rook {
                    next.castling[seat.index()] &= !(1 << side);
                }
            }
        }
        if moving.kind == PieceKind::King {
            next.castling[moving.owner.index()] = 0;
            let distance = (i16::from(mv.from.file()) - i16::from(mv.to.file())).abs()
                + (i16::from(mv.from.rank()) - i16::from(mv.to.rank())).abs();
            if distance == 2 {
                let (_, rooks, axis) = castle_geometry(moving.owner);
                let sign = if mv.to.file() < mv.from.file() || mv.to.rank() < mv.from.rank() {
                    -1
                } else {
                    1
                };
                let rook = rooks[usize::from(sign > 0)];
                next.set(rook, None);
                next.set(
                    offset(mv.from, axis.0 * sign, axis.1 * sign)?,
                    Some(FourPiece {
                        owner: moving.owner,
                        kind: PieceKind::Rook,
                    }),
                );
            }
        }
        if let Some(captured) = self.at(capture_square) {
            if self.allied(moving.owner, captured.owner) || captured.kind == PieceKind::King {
                return None;
            }
            if self.mode == FourMode::Ffa {
                next.scores[moving.owner.index()] += capture_value(captured.kind);
            }
        }
        next.set(capture_square, None);
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
        next.en_passant[moving.owner.index()] = None;
        if moving.kind == PieceKind::Pawn {
            let (df, dr) = moving.owner.pawn_step();
            if offset(mv.from, df * 2, dr * 2) == Some(mv.to) {
                next.en_passant[moving.owner.index()] = Some((mv.to, offset(mv.from, df, dr)?));
            }
        }
        next.advance_turn();
        next.en_passant[next.turn.index()] = None;
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

    /// Move notation list, useful for UI/protocol previews.
    #[must_use]
    pub fn legal_move_notations(&self) -> Vec<String> {
        self.legal_moves()
            .into_iter()
            .map(FourMove::notation)
            .collect()
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
                        let mobile = self.pseudo_moves(self.turn).into_iter().any(|mv| {
                            self.apply_unchecked(mv)
                                .is_some_and(|next| !next.king_attacked(self.turn))
                        });
                        if !mobile {
                            if self.king_attacked(self.turn) {
                                Some(FourOutcome::TeamWin {
                                    red_yellow: !matches!(
                                        self.turn,
                                        FourSeat::Red | FourSeat::Yellow
                                    ),
                                })
                            } else {
                                Some(FourOutcome::Draw)
                            }
                        } else if self.halfmove >= 200
                            || self
                                .cells
                                .iter()
                                .flatten()
                                .all(|p| p.kind == PieceKind::King)
                        {
                            Some(FourOutcome::Draw)
                        } else {
                            None
                        }
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
        for rights in self.castling {
            add(u64::from(rights));
        }
        for ep in self.en_passant {
            add(ep.map_or(0, |(pawn, passed)| {
                1 + square_index(pawn) as u64 * 196 + square_index(passed) as u64
            }));
        }
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
            " active={}{}{}{} scores={},{},{},{} half={} ply={} castle={}{}{}{} ep={}",
            u8::from(self.active[0]),
            u8::from(self.active[1]),
            u8::from(self.active[2]),
            u8::from(self.active[3]),
            self.scores[0],
            self.scores[1],
            self.scores[2],
            self.scores[3],
            self.halfmove,
            self.ply,
            self.castling[0],
            self.castling[1],
            self.castling[2],
            self.castling[3],
            self.en_passant
                .map(|ep| ep.map_or_else(
                    || "-".into(),
                    |(pawn, passed)| format!("{}{}", square_name(pawn), square_name(passed))
                ))
                .join(",")
        )
        .expect("String write");
        out
    }
}

fn castle_geometry(seat: FourSeat) -> (Square14, [Square14; 2], (i8, i8)) {
    let (king, a, b, axis) = match seat {
        FourSeat::Red => ((7, 0), (3, 0), (10, 0), (1, 0)),
        FourSeat::Blue => ((0, 7), (0, 3), (0, 10), (0, 1)),
        FourSeat::Yellow => ((6, 13), (3, 13), (10, 13), (1, 0)),
        FourSeat::Green => ((13, 6), (13, 3), (13, 10), (0, 1)),
    };
    (
        Square14::new(king.0, king.1).unwrap(),
        [
            Square14::new(a.0, a.1).unwrap(),
            Square14::new(b.0, b.1).unwrap(),
        ],
        axis,
    )
}

#[cfg(test)]
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

#[cfg(test)]
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

    fn teams_fixture() -> FourPosition {
        let mut p = FourPosition::initial(FourMode::Teams);
        p.cells = [None; 196];
        p.castling = [0; 4];
        for (seat, (f, r)) in FourSeat::ORDER
            .into_iter()
            .zip([(7, 0), (0, 7), (6, 13), (13, 6)])
        {
            p.set(
                Square14::new(f, r).unwrap(),
                Some(FourPiece {
                    owner: seat,
                    kind: PieceKind::King,
                }),
            );
        }
        p
    }
    fn put(p: &mut FourPosition, f: u8, r: u8, seat: FourSeat, kind: PieceKind) {
        p.set(
            Square14::new(f, r).unwrap(),
            Some(FourPiece { owner: seat, kind }),
        );
    }

    #[test]
    fn teams_initial_state_and_special_state_roundtrip() {
        let mut p = FourPosition::initial(FourMode::Teams);
        assert_eq!(FourPosition::from_state(&p.to_state()).unwrap(), p);
        let mv = p
            .legal_moves()
            .into_iter()
            .find(|mv| {
                mv.from == Square14::new(6, 1).unwrap() && mv.to == Square14::new(6, 3).unwrap()
            })
            .unwrap();
        p = p.play(mv).unwrap();
        assert!(p.en_passant[0].is_some());
        assert_eq!(FourPosition::from_state(&p.to_state()).unwrap(), p);
        assert!(FourPosition::from_state("4pc-teams malformed").is_err());
    }
    #[test]
    fn teams_repetition_draw_preserves_complete_round_history() {
        let mut game = FourGame::new(FourMode::Teams);
        let cycle = [
            "4052", "0425", "9d8b", "d9b8", "5240", "2504", "8b9d", "b8d9",
        ];
        for text in cycle {
            assert!(game.push_notation(text));
        }
        assert_eq!(game.outcome(), None);
        for text in cycle {
            assert!(game.push_notation(text));
        }
        assert_eq!(game.outcome(), Some(FourOutcome::Draw));
        assert!(!game.push_notation("4052"));
    }
    #[test]
    fn teams_stalemate_draws_instead_of_winning_for_enemy() {
        let mut p = teams_fixture();
        put(&mut p, 6, 2, FourSeat::Blue, PieceKind::Rook);
        put(&mut p, 8, 2, FourSeat::Blue, PieceKind::Rook);
        put(&mut p, 5, 2, FourSeat::Blue, PieceKind::Knight);
        assert!(!p.king_attacked(FourSeat::Red));
        assert_eq!(p.outcome(), Some(FourOutcome::Draw));
        assert!(p.legal_moves().is_empty());
    }
    #[test]
    fn attack_lookup_matches_slow_piece_scan_through_seeded_game() {
        let mut p = FourPosition::initial(FourMode::Teams);
        let mut seed = 0x4e10u64;
        for _ in 0..32 {
            for target in playable_squares() {
                for seat in FourSeat::ORDER {
                    let expected = playable_squares().any(|from| {
                        p.at(from).is_some_and(|piece| {
                            piece.owner == seat && piece_attacks(&p, piece, from, target)
                        })
                    });
                    assert_eq!(
                        p.attacks_square(seat, target),
                        expected,
                        "{seat:?} {target:?}"
                    );
                }
            }
            let children = p.legal_successors();
            if children.is_empty() || p.outcome().is_some() {
                break;
            }
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            p = children[seed as usize % children.len()].1.clone();
        }
    }
    #[test]
    fn all_four_seats_can_castle_and_rights_are_irreversible() {
        for seat in FourSeat::ORDER {
            for side in 0..2 {
                let mut p = teams_fixture();
                p.turn = seat;
                p.castling[seat.index()] = 3;
                let (king, rooks, axis) = castle_geometry(seat);
                for rook in rooks {
                    p.set(
                        rook,
                        Some(FourPiece {
                            owner: seat,
                            kind: PieceKind::Rook,
                        }),
                    );
                }
                let sign = if side == 0 { -1 } else { 1 };
                let target = offset(king, axis.0 * sign * 2, axis.1 * sign * 2).unwrap();
                let mv = p
                    .legal_moves()
                    .into_iter()
                    .find(|mv| mv.from == king && mv.to == target)
                    .unwrap();
                let next = p.play(mv).unwrap();
                assert_eq!(next.at(target).unwrap().kind, PieceKind::King);
                assert!(next.at(rooks[side]).is_none());
                assert_eq!(
                    next.at(offset(king, axis.0 * sign, axis.1 * sign).unwrap())
                        .unwrap()
                        .kind,
                    PieceKind::Rook
                );
                assert_eq!(next.castling[seat.index()], 0);
                assert_ne!(next.identity_key(), p.identity_key());
            }
        }
    }
    #[test]
    fn castling_cannot_cross_attacked_square() {
        let mut p = teams_fixture();
        p.castling[0] = 3;
        put(&mut p, 3, 0, FourSeat::Red, PieceKind::Rook);
        put(&mut p, 10, 0, FourSeat::Red, PieceKind::Rook);
        put(&mut p, 8, 5, FourSeat::Blue, PieceKind::Rook);
        let king = p.king(FourSeat::Red).unwrap();
        assert!(
            !p.legal_moves()
                .iter()
                .any(|mv| mv.from == king && mv.to == Square14::new(9, 0).unwrap())
        );
    }
    #[test]
    fn en_passant_capture_removes_only_enemy_pawn() {
        let mut p = teams_fixture();
        put(&mut p, 4, 1, FourSeat::Red, PieceKind::Pawn);
        put(&mut p, 3, 1, FourSeat::Blue, PieceKind::Pawn);
        let mv = p.parse_move("4143").unwrap();
        let p = p.play(mv).unwrap();
        let mv = p.parse_move("3142").unwrap();
        let next = p.play(mv).unwrap();
        assert!(next.at(Square14::new(4, 3).unwrap()).is_none());
        assert_eq!(
            next.at(Square14::new(4, 2).unwrap()).unwrap().owner,
            FourSeat::Blue
        );
    }
    #[test]
    fn mate_is_adjudicated_only_when_victims_turn_arrives() {
        let mut p = teams_fixture();
        // Red's king cannot move out of a rook battery on its home strip.
        put(&mut p, 7, 2, FourSeat::Blue, PieceKind::Rook);
        put(&mut p, 6, 2, FourSeat::Blue, PieceKind::Rook);
        put(&mut p, 8, 2, FourSeat::Blue, PieceKind::Rook);
        assert!(p.king_attacked(FourSeat::Red));
        assert!(p.legal_moves().is_empty());
        assert_eq!(
            p.outcome(),
            Some(FourOutcome::TeamWin { red_yellow: false })
        );
        p.turn = FourSeat::Yellow;
        assert_eq!(p.outcome(), None);
    }
    #[test]
    fn pinned_piece_cannot_expose_own_king() {
        let mut p = teams_fixture();
        put(&mut p, 7, 1, FourSeat::Red, PieceKind::Rook);
        put(&mut p, 7, 5, FourSeat::Blue, PieceKind::Rook);
        assert!(
            !p.legal_moves()
                .iter()
                .any(|mv| mv.from == Square14::new(7, 1).unwrap()
                    && mv.to == Square14::new(8, 1).unwrap())
        );
    }
    #[test]
    fn teams_underpromotions_and_replay_keep_partner_safe() {
        let mut p = teams_fixture();
        put(&mut p, 5, 9, FourSeat::Red, PieceKind::Pawn);
        let promotions: Vec<_> = p
            .legal_moves()
            .into_iter()
            .filter(|mv| mv.from == Square14::new(5, 9).unwrap())
            .collect();
        assert_eq!(promotions.len(), 4);
        for mv in promotions {
            assert_eq!(
                p.play(mv).unwrap().at(mv.to).unwrap().kind,
                mv.promotion.unwrap()
            );
        }
    }

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

    #[test]
    fn four_game_push_parse_and_undo_are_reversible() {
        let mut game = FourGame::new(FourMode::Ffa);
        let original = game.clone();
        let notation = game
            .position()
            .legal_moves()
            .into_iter()
            .next()
            .unwrap()
            .notation();
        assert!(game.push_notation(&notation));
        assert_eq!(game.moves().count(), 1);
        assert!(game.pop());
        assert_eq!(game, original);
        assert!(!game.push_notation("not-a-move"));
    }

    #[test]
    fn resignation_and_timeout_create_local_outcomes() {
        let mut ffa = FourGame::new(FourMode::Ffa);
        ffa.resign(FourSeat::Blue);
        let Some(FourOutcome::Placements(placements)) = ffa.outcome() else {
            panic!("resignation should create FFA placements");
        };
        assert_eq!(placements.last().unwrap().0, FourSeat::Blue);

        let mut teams = FourGame::new(FourMode::Teams);
        teams.timeout(FourSeat::Red);
        assert_eq!(
            teams.outcome(),
            Some(FourOutcome::TeamWin { red_yellow: false })
        );
    }
}
