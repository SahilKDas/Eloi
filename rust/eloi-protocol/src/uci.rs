//! Strict, transactional UCI position and bounded-search decoding.

use std::time::Duration;

use eloi_core::Variant;
use eloi_core::game::Game;
use eloi_core::position::{HORDE_INITIAL_FEN, INITIAL_FEN};
use eloi_engine::search::SearchLimits;

/// Apply a UCI position command without changing the game on any failure.
///
/// # Errors
/// Rejects malformed FEN, unsupported syntax, and illegal history moves.
pub fn apply_position(game: &mut Game, command: &str, variant: Variant) -> Result<(), String> {
    let words: Vec<_> = command.split_whitespace().collect();
    if words.first() != Some(&"position") {
        return Err("expected position command".into());
    }
    let (fen, tail) = match words.get(1) {
        Some(&"startpos") => (
            if variant == Variant::Horde {
                HORDE_INITIAL_FEN
            } else {
                INITIAL_FEN
            }
            .to_owned(),
            2,
        ),
        Some(&"fen") if words.len() >= 8 => (words[2..8].join(" "), 8),
        _ => return Err("expected startpos or six-field FEN".into()),
    };
    let moves = if words.len() == tail {
        &[][..]
    } else if words.get(tail) == Some(&"moves") {
        &words[tail + 1..]
    } else {
        return Err("unexpected position suffix".into());
    };
    game.replace(&fen, variant, moves)
        .map_err(|error| error.to_string())
}

/// Decode explicitly bounded development searches; clock allocation is not
/// silently approximated while the legacy time manager is being migrated.
///
/// # Errors
/// Rejects unknown limits, zero limits, unbounded searches and overflow.
pub fn parse_go(command: &str, overhead_ms: u64) -> Result<SearchLimits, String> {
    let words: Vec<_> = command.split_whitespace().collect();
    if words.first() != Some(&"go") {
        return Err("expected go command".into());
    }
    let mut depth = 64;
    let mut nodes = None;
    let mut millis = None;
    let mut index = 1;
    while index < words.len() {
        let key = words[index];
        let value: u64 = words
            .get(index + 1)
            .ok_or_else(|| format!("missing value for {key}"))?
            .parse()
            .map_err(|_| format!("invalid value for {key}"))?;
        if value == 0 {
            return Err(format!("zero {key} refused"));
        }
        match key {
            "depth" if value <= 64 => depth = u8::try_from(value).map_err(|e| e.to_string())?,
            "nodes" => nodes = Some(value),
            "movetime" if value <= 60_000 => {
                millis = Some(value.saturating_sub(overhead_ms).max(1));
            }
            _ => return Err(format!("unsupported or out-of-range search limit: {key}")),
        }
        index += 2;
    }
    if millis.is_none() && nodes.is_none() && depth == 64 {
        return Err("explicit bounded search limit required".into());
    }
    Ok(SearchLimits {
        movetime: Duration::from_millis(millis.unwrap_or(60_000)),
        depth,
        nodes,
    })
}

#[cfg(test)]
mod tests {
    use super::{apply_position, parse_go};
    use eloi_core::{Variant, game::Game, position::INITIAL_FEN};

    #[test]
    fn position_failure_preserves_history() {
        let mut game = Game::from_fen(INITIAL_FEN, Variant::Standard).unwrap();
        apply_position(
            &mut game,
            "position startpos moves e2e4 e7e5",
            Variant::Standard,
        )
        .unwrap();
        let frozen = game.clone();
        assert!(
            apply_position(
                &mut game,
                "position startpos moves e2e4 e7e4",
                Variant::Standard
            )
            .is_err()
        );
        assert_eq!(game, frozen);
        assert!(apply_position(&mut game, "position startpos garbage", Variant::Standard).is_err());
        assert_eq!(game, frozen);
    }

    #[test]
    fn limits_are_bounded_and_explicit() {
        let limits = parse_go("go movetime 250 nodes 20000 depth 5", 10).unwrap();
        assert_eq!(limits.movetime.as_millis(), 240);
        assert_eq!(limits.nodes, Some(20_000));
        assert_eq!(limits.depth, 5);
        for invalid in [
            "go",
            "go infinite",
            "go depth 65",
            "go nodes 0",
            "go movetime 60001",
            "go movetime",
        ] {
            assert!(parse_go(invalid, 0).is_err(), "{invalid}");
        }
    }

    #[test]
    fn horde_startpos_has_the_production_pawn_army() {
        let mut game = Game::from_fen(INITIAL_FEN, Variant::Standard).unwrap();
        apply_position(&mut game, "position startpos", Variant::Horde).unwrap();
        assert_eq!(game.position().variant, Variant::Horde);
        assert_eq!(
            game.position().to_fen(),
            eloi_core::position::HORDE_INITIAL_FEN
        );
        assert_eq!(
            game.position()
                .cells
                .iter()
                .flatten()
                .filter(|piece| piece.owner == eloi_core::Player::White)
                .count(),
            36
        );
    }
}
