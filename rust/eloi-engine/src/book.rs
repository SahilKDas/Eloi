//! Frozen Eloi opening repertoire with legacy-compatible position identity.

use eloi_core::game::Game;
use eloi_core::rules::{Move8, MoveKind};
use eloi_core::{PieceKind, Player, Variant};

#[path = "book_data.rs"]
mod data;

const fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

const fn zobrist(index: u64) -> u64 {
    splitmix64(0xE101_C026_5A17_u64.wrapping_add(index.wrapping_mul(0x9e37_79b9_7f4a_7c15)))
}

fn legacy_key(game: &Game) -> u64 {
    let position = game.position();
    let mut key = 0;
    for (square, piece) in position.cells.iter().enumerate() {
        if let Some(piece) = piece {
            let color = u64::from(piece.owner == Player::Black);
            let legacy_piece = match piece.kind {
                PieceKind::Pawn => 0,
                PieceKind::Bishop => 1,
                PieceKind::Knight => 2,
                PieceKind::Rook => 3,
                PieceKind::Queen => 4,
                PieceKind::King => 5,
            };
            key ^= zobrist((color * 6 + legacy_piece) * 64 + square as u64);
        }
    }
    for right in &position.castling {
        let side = u64::from(right.owner == Player::Black) * 2;
        let wing = u64::from(right.rook.index() % 8 == 0);
        key ^= zobrist(768 + side + wing);
    }
    if position.turn == Player::Black {
        key ^= zobrist(772);
    }
    if let Some(en_passant) = position.en_passant.filter(|_| {
        position
            .legal_moves()
            .iter()
            .any(|mv| mv.kind == MoveKind::EnPassant)
    }) {
        key ^= zobrist(773 + u64::from(en_passant.index() % 8));
    }
    key
}

/// Select the strongest legal frozen repertoire edge for Standard chess.
#[must_use]
pub fn opening_move(game: &Game) -> Option<Move8> {
    if game.position().variant != Variant::Standard || game.moves().count() >= 32 {
        return None;
    }
    let key = legacy_key(game);
    let node = data::NODES
        .binary_search_by_key(&key, |entry| entry.0)
        .ok()
        .map(|index| data::NODES[index])?;
    let legal = game.position().legal_moves();
    (node.1..node.1 + u32::from(node.2))
        .filter_map(|index| {
            let (encoded, weight, family) = data::EDGES[index as usize];
            let from = u8::try_from(encoded & 63).ok()?;
            let to = u8::try_from((encoded >> 6) & 63).ok()?;
            let promotion = match (encoded >> 12) & 7 {
                0 => None,
                2 => Some(PieceKind::Knight),
                3 => Some(PieceKind::Bishop),
                4 => Some(PieceKind::Rook),
                5 => Some(PieceKind::Queen),
                _ => return None,
            };
            let mv = legal.iter().copied().find(|mv| {
                mv.from.is_some_and(|square| square.index() == from)
                    && mv.to.index() == to
                    && mv.promotion == promotion
            })?;
            let signature = (family == 1 && game.position().turn == Player::White)
                || (family == 2 && game.position().turn == Player::Black);
            Some((signature, weight, mv))
        })
        .max_by_key(|(signature, weight, _)| (*signature, *weight))
        .map(|(_, _, mv)| mv)
}

#[cfg(test)]
mod tests {
    use super::*;
    use eloi_core::position::INITIAL_FEN;

    #[test]
    fn frozen_book_recognizes_start_and_leaves_variants_alone() {
        let game = Game::from_fen(INITIAL_FEN, Variant::Standard).unwrap();
        assert!(opening_move(&game).is_some());
        let game = Game::from_fen(INITIAL_FEN, Variant::Atomic).unwrap();
        assert!(opening_move(&game).is_none());
    }
}
