//! Strict, transactional UCI position and bounded-search decoding.

use std::time::Duration;

use eloi_core::Variant;
use eloi_core::game::Game;
use eloi_core::position::initial_fen;
use eloi_engine::search::SearchLimits;

/// Fully decoded UCI search request, including protocol search modes.
#[derive(Clone, Copy, Debug)]
pub struct SearchRequest {
    /// Limits used by the initial search.
    pub limits: SearchLimits,
    /// Normal clock limits to begin after `ponderhit`.
    pub ponder_resume: Option<SearchLimits>,
    /// Whether the initial search is explicitly infinite.
    pub infinite: bool,
}

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
        Some(&"startpos") => (initial_fen(variant).to_owned(), 2),
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
        soft_time: None,
        hash_mb: 32,
    })
}

/// Decode clock searches using the authoritative side-to-move and production
/// reserve planner. Explicit movetime takes precedence over clock fields.
///
/// # Errors
/// Rejects malformed, duplicate, unknown and overflowing clock fields.
pub fn parse_go_for(game: &Game, command: &str, overhead_ms: u64) -> Result<SearchLimits, String> {
    let words: Vec<_> = command.split_whitespace().collect();
    if words.first() != Some(&"go") || words.len().is_multiple_of(2) {
        return Err("malformed go command".into());
    }
    let mut explicit = String::from("go");
    let mut clocks = [None; 5];
    let mut seen = std::collections::BTreeSet::new();
    let mut movetime = false;
    let mut bounded = false;
    for pair in words[1..].chunks(2) {
        if pair.len() != 2 || !seen.insert(pair[0]) {
            return Err("missing or duplicate search field".into());
        }
        let field = match pair[0] {
            "wtime" => Some(0),
            "btime" => Some(1),
            "winc" => Some(2),
            "binc" => Some(3),
            "movestogo" => Some(4),
            _ => None,
        };
        if let Some(index) = field {
            clocks[index] = Some(pair[1].parse::<u32>().map_err(|_| "invalid clock value")?);
        } else {
            explicit.push(' ');
            explicit.push_str(pair[0]);
            explicit.push(' ');
            explicit.push_str(pair[1]);
            movetime |= pair[0] == "movetime";
            bounded = true;
        }
    }
    if movetime || clocks.iter().all(Option::is_none) {
        return parse_go(&explicit, overhead_ms);
    }
    let white = game.position().turn == eloi_core::Player::White;
    let remaining = clocks[usize::from(!white)].ok_or("side-to-move clock missing")?;
    let increment = clocks[if white { 2 } else { 3 }].unwrap_or(0);
    let budget = eloi_engine::time::plan(
        game.position(),
        remaining,
        increment,
        clocks[4].unwrap_or(0),
        u32::try_from(overhead_ms).map_err(|_| "overhead overflow")?,
    );
    let mut limits = if bounded {
        parse_go(&explicit, overhead_ms)?
    } else {
        parse_go("go movetime 60000", 0)?
    };
    limits.movetime = Duration::from_millis(budget.hard_ms);
    limits.soft_time = Some(Duration::from_millis(budget.soft_ms));
    Ok(limits)
}

/// Decode standard, infinite, and ponder UCI searches.
///
/// Infinite and pre-`ponderhit` work receives a day-long safety ceiling while
/// still remaining immediately externally cancellable.
///
/// # Errors
/// Rejects malformed combinations and delegates bounded-field validation.
pub fn parse_search_request(
    game: &Game,
    command: &str,
    overhead_ms: u64,
) -> Result<SearchRequest, String> {
    let mut words: Vec<_> = command.split_whitespace().collect();
    if words.first() != Some(&"go") {
        return Err("expected go command".into());
    }
    let ponder = words.iter().filter(|word| **word == "ponder").count();
    let infinite = words.iter().filter(|word| **word == "infinite").count();
    if ponder > 1 || infinite > 1 || (ponder != 0 && infinite != 0) {
        return Err("duplicate or conflicting search mode".into());
    }
    words.retain(|word| !matches!(*word, "ponder" | "infinite"));
    let normalized = words.join(" ");
    if infinite != 0 {
        if normalized != "go" {
            return Err("infinite cannot be combined with limits".into());
        }
        return Ok(SearchRequest {
            limits: unbounded_protocol_limits(),
            ponder_resume: None,
            infinite: true,
        });
    }
    let normal = parse_go_for(game, &normalized, overhead_ms)?;
    Ok(SearchRequest {
        limits: if ponder != 0 {
            unbounded_protocol_limits()
        } else {
            normal
        },
        ponder_resume: (ponder != 0).then_some(normal),
        infinite: false,
    })
}

fn unbounded_protocol_limits() -> SearchLimits {
    SearchLimits {
        movetime: Duration::from_hours(24),
        soft_time: None,
        depth: 64,
        nodes: None,
        hash_mb: 32,
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::{apply_position, parse_go, parse_go_for, parse_search_request};
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
    fn clock_search_uses_active_color_and_production_reserve() {
        let mut game = Game::from_fen(INITIAL_FEN, Variant::Standard).unwrap();
        let limits = parse_go_for(&game, "go wtime 300000 btime 1000 winc 0 binc 0", 0).unwrap();
        assert_eq!(limits.movetime.as_millis(), 8788);
        assert_eq!(limits.soft_time.unwrap().as_millis(), 4394);
        assert!(game.push_uci("e2e4"));
        let limits = parse_go_for(&game, "go wtime 300000 btime 1000", 0).unwrap();
        assert!(limits.movetime.as_millis() < 50);
        for bad in [
            "go wtime 1",
            "go btime 1 btime 2",
            "go btime -1",
            "go btime 4294967296",
            "go btime",
        ] {
            assert!(parse_go_for(&game, bad, 0).is_err(), "{bad}");
        }
        let explicit = parse_go_for(&game, "go movetime 250 btime 1000", 10).unwrap();
        assert_eq!(explicit.movetime.as_millis(), 240);
        assert!(explicit.soft_time.is_none());
    }

    #[test]
    fn infinite_and_ponder_modes_are_explicit_and_bounded() {
        let game = Game::from_fen(INITIAL_FEN, Variant::Standard).unwrap();
        let infinite = parse_search_request(&game, "go infinite", 0).unwrap();
        assert!(infinite.infinite);
        assert_eq!(infinite.limits.movetime, Duration::from_hours(24));
        assert!(infinite.ponder_resume.is_none());

        let ponder = parse_search_request(
            &game,
            "go ponder wtime 60000 btime 60000 winc 100 binc 100",
            0,
        )
        .unwrap();
        assert!(!ponder.infinite);
        assert_eq!(ponder.limits.movetime, Duration::from_hours(24));
        assert!(ponder.ponder_resume.unwrap().movetime < Duration::from_secs(60));
        assert!(parse_search_request(&game, "go ponder infinite", 0).is_err());
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
