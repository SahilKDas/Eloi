//! Exact scalar Eloi NNUE with model-aware incremental accumulator state.

use std::sync::OnceLock;

use eloi_core::position::{Piece, Position};
use eloi_core::{PieceKind, Player, Variant};

const HIDDEN: usize = 64;
const FEATURES: usize = 6144;
const HEADER: usize = 16;
const INPUT_OFFSET: usize = HEADER + HIDDEN * 4;

/// Qualified embedded Eloi evaluator identity.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Model {
    /// Production E4-10 evaluator.
    Production,
    /// Qualified King of the Hill evaluator.
    Koth,
    /// Qualified Atomic evaluator.
    Atomic,
}

impl Model {
    /// Model selected by the position variant.
    #[must_use]
    pub const fn for_variant(variant: Variant) -> Self {
        match variant {
            Variant::KingOfTheHill => Self::Koth,
            Variant::Atomic => Self::Atomic,
            _ => Self::Production,
        }
    }

    /// Canonical qualified source header identity.
    #[must_use]
    pub const fn source_sha256(self) -> &'static str {
        match self {
            Self::Production => "4C705496950E27204C976F0D027CAA9C73B209961584F7998742AA481B524E88",
            Self::Koth => "E06F0B3A71445933BF066E8FE6B03A9271B94DB522A15180C63DA4703E5FBF8E",
            Self::Atomic => "9B47E6EAEFBB3DCAE0B5861AE90C8A647FDD3A6A31FFF93543D8DAC336D5B179",
        }
    }

    fn weights(self) -> Result<&'static Weights<'static>, &'static str> {
        static PRODUCTION: OnceLock<Result<Weights<'static>, &'static str>> = OnceLock::new();
        static KOTH: OnceLock<Result<Weights<'static>, &'static str>> = OnceLock::new();
        static ATOMIC: OnceLock<Result<Weights<'static>, &'static str>> = OnceLock::new();
        let (cell, bytes): (_, &[u8]) = match self {
            Self::Production => (&PRODUCTION, &include_bytes!("../models/e4-10.ennue")[..]),
            Self::Koth => (&KOTH, &include_bytes!("../models/e4-koth.ennue")[..]),
            Self::Atomic => (&ATOMIC, &include_bytes!("../models/e4-atomic.ennue")[..]),
        };
        cell.get_or_init(|| Weights::parse(bytes))
            .as_ref()
            .map_err(|&e| e)
    }
}

/// Borrowed, strictly validated quantized model arrays.
pub struct Weights<'a> {
    bias: [i16; HIDDEN],
    output: [i16; HIDDEN],
    input: &'a [u8],
}

impl<'a> Weights<'a> {
    /// Parse deterministic ELNNUE1 data without executable deserialization.
    ///
    /// # Errors
    /// Rejects magic, architecture or exact-size mismatches.
    pub fn parse(bytes: &'a [u8]) -> Result<Self, &'static str> {
        if bytes.len() != INPUT_OFFSET + FEATURES * HIDDEN {
            return Err("NNUE length mismatch");
        }
        if &bytes[..8] != b"ELNNUE1\0"
            || bytes[8..12] != 6144_u32.to_le_bytes()
            || bytes[12..16] != 64_u32.to_le_bytes()
        {
            return Err("NNUE magic or architecture mismatch");
        }
        let mut bias = [0; HIDDEN];
        let mut output = [0; HIDDEN];
        for (index, value) in bias.iter_mut().enumerate() {
            let offset = HEADER + index * 2;
            *value = i16::from_le_bytes([bytes[offset], bytes[offset + 1]]);
        }
        for (index, value) in output.iter_mut().enumerate() {
            let offset = HEADER + HIDDEN * 2 + index * 2;
            *value = i16::from_le_bytes([bytes[offset], bytes[offset + 1]]);
        }
        Ok(Self {
            bias,
            output,
            input: &bytes[INPUT_OFFSET..],
        })
    }

    fn add(&self, accumulator: &mut [i32; HIDDEN], feature: usize, sign: i32) {
        let base = feature * HIDDEN;
        for (index, value) in accumulator.iter_mut().enumerate() {
            *value += sign * i32::from(i8::from_ne_bytes([self.input[base + index]]));
        }
    }
}

/// Two-perspective accumulator with explicit variant and model identity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NnueState {
    /// Selected evaluator.
    pub model: Model,
    variant: Variant,
    source_cells: [Option<Piece>; 64],
    perspective: [[i32; HIDDEN]; 2],
}

fn bucket(position: &Position, perspective: Player) -> usize {
    let Some(king) = position.king(perspective) else {
        return 0;
    };
    let square = king.index() ^ if perspective == Player::Black { 56 } else { 0 };
    usize::from(square % 8 >= 4) + 2 * usize::from(square / 16)
}

fn feature(piece: Piece, square: usize, king_bucket: usize, perspective: Player) -> usize {
    let kind = match piece.kind {
        PieceKind::Pawn => 0,
        PieceKind::Bishop => 1,
        PieceKind::Knight => 2,
        PieceKind::Rook => 3,
        PieceKind::Queen => 4,
        PieceKind::King => 5,
    };
    let plane = usize::from(piece.owner != perspective) * 6 + kind;
    let oriented = square ^ if perspective == Player::Black { 56 } else { 0 };
    (king_bucket * 12 + plane) * 64 + oriented
}

impl NnueState {
    /// Rebuild both perspectives using the position's matching model.
    ///
    /// # Errors
    /// Returns an embedded artifact validation error.
    pub fn refresh(position: &Position) -> Result<Self, &'static str> {
        let model = Model::for_variant(position.variant);
        let weights = model.weights()?;
        let mut result = Self {
            model,
            variant: position.variant,
            source_cells: position.cells,
            perspective: [weights.bias.map(i32::from); 2],
        };
        for (index, perspective) in [Player::White, Player::Black].into_iter().enumerate() {
            let king_bucket = bucket(position, perspective);
            for (square, piece) in position.cells.iter().enumerate() {
                if let Some(piece) = piece {
                    weights.add(
                        &mut result.perspective[index],
                        feature(*piece, square, king_bucket, perspective),
                        1,
                    );
                }
            }
        }
        Ok(result)
    }

    /// Incrementally update changed pieces; rebuild when a king bucket or model changes.
    ///
    /// # Errors
    /// Returns a model validation error or mismatched source variant.
    pub fn update(&mut self, before: &Position, after: &Position) -> Result<(), &'static str> {
        if before.variant != self.variant || before.cells != self.source_cells {
            return Err("accumulator source variant mismatch");
        }
        if after.variant != self.variant || Model::for_variant(after.variant) != self.model {
            *self = Self::refresh(after)?;
            return Ok(());
        }
        let weights = self.model.weights()?;
        for (index, perspective) in [Player::White, Player::Black].into_iter().enumerate() {
            let old_bucket = bucket(before, perspective);
            let new_bucket = bucket(after, perspective);
            if old_bucket != new_bucket {
                self.perspective[index] = weights.bias.map(i32::from);
                for (square, piece) in after.cells.iter().enumerate() {
                    if let Some(piece) = piece {
                        weights.add(
                            &mut self.perspective[index],
                            feature(*piece, square, new_bucket, perspective),
                            1,
                        );
                    }
                }
                continue;
            }
            for (square, (old, new)) in before.cells.iter().zip(after.cells.iter()).enumerate() {
                if old == new {
                    continue;
                }
                if let Some(piece) = old {
                    weights.add(
                        &mut self.perspective[index],
                        feature(*piece, square, old_bucket, perspective),
                        -1,
                    );
                }
                if let Some(piece) = new {
                    weights.add(
                        &mut self.perspective[index],
                        feature(*piece, square, new_bucket, perspective),
                        1,
                    );
                }
            }
        }
        self.source_cells = after.cells;
        Ok(())
    }

    /// Exact production NNUE arithmetic, including the 10 cp tempo term.
    ///
    /// # Errors
    /// Rejects non-two-player turns and invalid embedded weights.
    pub fn evaluate(&self, turn: Player) -> Result<i32, &'static str> {
        if !matches!(turn, Player::White | Player::Black) {
            return Err("NNUE requires a two-player turn");
        }
        let weights = self.model.weights()?;
        let activate = |values: &[i32; HIDDEN]| eloi_simd::clipped_dot(values, &weights.output);
        let white_score = (activate(&self.perspective[0]) - activate(&self.perspective[1])) / 8;
        let score = if turn == Player::White {
            white_score
        } else {
            -white_score
        } + 10;
        i32::try_from(score).map_err(|_| "NNUE score overflow")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use eloi_core::position::INITIAL_FEN;

    #[test]
    fn malformed_models_are_rejected() {
        assert!(Weights::parse(&[]).is_err());
        let mut bytes = include_bytes!("../models/e4-10.ennue").to_vec();
        bytes[12] = 32;
        assert!(Weights::parse(&bytes).is_err());
    }

    #[test]
    fn incremental_updates_and_model_switches_match_refresh() {
        for variant in [
            Variant::Standard,
            Variant::Chess960,
            Variant::KingOfTheHill,
            Variant::Atomic,
            Variant::Crazyhouse,
        ] {
            let mut position = Position::from_fen(INITIAL_FEN, variant).unwrap();
            let mut state = NnueState::refresh(&position).unwrap();
            for ply in 0..20 {
                let moves = position.legal_moves();
                if moves.is_empty() {
                    break;
                }
                let next = position.play(moves[(ply * 17) % moves.len()]).unwrap();
                state.update(&position, &next).unwrap();
                assert_eq!(state, NnueState::refresh(&next).unwrap());
                let mut restored = state.clone();
                restored.update(&next, &position).unwrap();
                assert_eq!(restored, NnueState::refresh(&position).unwrap());
                position = next;
            }
            let mut switched = position.clone();
            switched.variant = Variant::KingOfTheHill;
            state.update(&position, &switched).unwrap();
            assert_eq!(state, NnueState::refresh(&switched).unwrap());
        }
    }
}
