//! Game history, atomic position replacement and draw claims.

use crate::Variant;
use crate::position::{FenError, Position};
use crate::rules::{Move8, MoveKind};

/// A game whose position can only change through validated transitions.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Game {
    position: Position,
    history: Vec<(Position, Move8)>,
}

impl Game {
    /// Create a game from validated FEN state.
    ///
    /// # Errors
    /// Returns the FEN validation failure.
    pub fn from_fen(fen: &str, variant: Variant) -> Result<Self, FenError> {
        Ok(Self {
            position: Position::from_fen(fen, variant)?,
            history: Vec::new(),
        })
    }

    /// Current authoritative position; mutable access is deliberately withheld.
    #[must_use]
    pub const fn position(&self) -> &Position {
        &self.position
    }

    /// Apply a legal move and preserve the entire prior state for undo.
    pub fn push(&mut self, mv: Move8) -> bool {
        let Some(next) = self.position.play(mv) else {
            return false;
        };
        self.history
            .push((std::mem::replace(&mut self.position, next), mv));
        true
    }

    /// Apply exact UCI notation through the legal-move parser.
    pub fn push_uci(&mut self, text: &str) -> bool {
        let Some(mv) = self.position.parse_move(text) else {
            return false;
        };
        self.push(mv)
    }

    /// Undo one ply, including clocks, pockets, castling and promotion identity.
    pub fn pop(&mut self) -> bool {
        let Some((previous, _)) = self.history.pop() else {
            return false;
        };
        self.position = previous;
        true
    }

    /// Replace the game only after the FEN and every supplied move are valid.
    ///
    /// # Errors
    /// Leaves this game unchanged on a malformed position or illegal move.
    pub fn replace(&mut self, fen: &str, variant: Variant, moves: &[&str]) -> Result<(), FenError> {
        let mut replacement = Self::from_fen(fen, variant)?;
        for text in moves {
            if !replacement.push_uci(text) {
                return Err(FenError("illegal move in position history"));
            }
        }
        *self = replacement;
        Ok(())
    }

    /// Moves since this game's initial position.
    pub fn moves(&self) -> impl Iterator<Item = Move8> + '_ {
        self.history.iter().map(|(_, mv)| *mv)
    }

    /// Count matching positions, ignoring clocks and unusable en-passant targets.
    #[must_use]
    pub fn repetition_count(&self) -> usize {
        let current = repetition_state(&self.position);
        1 + self
            .history
            .iter()
            .filter(|(position, _)| repetition_state(position) == current)
            .count()
    }

    /// Whether a threefold draw can be claimed in the current position.
    #[must_use]
    pub fn threefold(&self) -> bool {
        self.repetition_count() >= 3
    }

    /// Whether orthodox fifty-move rules permit a current-position claim.
    #[must_use]
    pub fn fifty_move(&self) -> bool {
        !matches!(
            self.position.variant,
            Variant::Crazyhouse | Variant::Antichess
        ) && self.position.halfmove >= 100
            && !self.position.legal_moves().is_empty()
    }
}

fn repetition_state(position: &Position) -> Position {
    let mut state = position.clone();
    state.halfmove = 0;
    state.fullmove = 1;
    if state.en_passant.is_some()
        && !state
            .legal_moves()
            .iter()
            .any(|mv| mv.kind == MoveKind::EnPassant)
    {
        state.en_passant = None;
    }
    state
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::position::INITIAL_FEN;

    #[test]
    fn reversible_history_and_failed_replacement() {
        let mut game = Game::from_fen(INITIAL_FEN, Variant::Standard).unwrap();
        let original = game.clone();
        assert!(game.push_uci("e2e4"));
        assert!(game.push_uci("e7e5"));
        let after = game.clone();
        assert!(
            game.replace(INITIAL_FEN, Variant::Standard, &["e2e4", "e2e5"])
                .is_err()
        );
        assert_eq!(game, after);
        assert!(game.pop());
        assert!(game.pop());
        assert_eq!(game, original);
    }

    #[test]
    fn repetition_ignores_clocks_but_preserves_turn_and_rules() {
        let mut game = Game::from_fen(INITIAL_FEN, Variant::Standard).unwrap();
        for _ in 0..2 {
            for text in ["g1f3", "g8f6", "f3g1", "f6g8"] {
                assert!(game.push_uci(text));
            }
        }
        assert_eq!(game.repetition_count(), 3);
        assert!(game.threefold());
        assert!(!game.fifty_move());
    }

    #[test]
    fn undo_restores_pockets_and_promoted_provenance() {
        let mut game =
            Game::from_fen("4k3/8/8/8/8/q~7/R7/4K3[] w - - 0 1", Variant::Crazyhouse).unwrap();
        let original = game.clone();
        assert!(game.push_uci("a2a3"));
        assert_eq!(game.position().pockets[0][0], 1);
        assert!(game.pop());
        assert_eq!(game, original);
    }
}
