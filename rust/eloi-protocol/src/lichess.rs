//! Bounded game-stream decoding and authoritative legal history reconstruction.

use eloi_core::{Player, Variant, game::Game, position::initial_fen};
use serde_json::Value;

/// Incomplete stream fragment; caller owns transport cancellation and reconnection.
#[derive(Default)]
pub struct StreamLines {
    pending: Vec<u8>,
}

impl StreamLines {
    /// Decode bounded UTF-8 lines; empty keepalive lines are not events.
    ///
    /// # Errors
    /// Oversized fragments/lines and invalid UTF-8 stop the stream.
    pub fn feed(&mut self, bytes: &[u8]) -> Result<Vec<String>, &'static str> {
        if bytes.len() > 65_536 {
            return Err("stream fragment exceeds limit");
        }
        let mut lines = Vec::new();
        for &byte in bytes {
            if byte == b'\n' {
                let line = std::str::from_utf8(&self.pending)
                    .map_err(|_| "stream is not UTF-8")?
                    .trim_end_matches('\r');
                if !line.is_empty() {
                    lines.push(line.to_owned());
                }
                self.pending.clear();
            } else {
                if self.pending.len() >= 65_536 {
                    return Err("stream line exceeds limit");
                }
                self.pending.push(byte);
            }
        }
        Ok(lines)
    }
}

/// Parsed server status, separate from a chess-result claim.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ServerState {
    /// Exact server status.
    pub status: String,
    /// Server-declared winner, absent for draws/aborts.
    pub winner: Option<Player>,
    /// Remaining White clock in milliseconds.
    pub white_ms: u64,
    /// Remaining Black clock in milliseconds.
    pub black_ms: u64,
}

impl ServerState {
    /// Whether server reports play in progress.
    #[must_use]
    pub fn active(&self) -> bool {
        matches!(self.status.as_str(), "created" | "started")
    }
}

/// A single game whose route/variant is fixed by the full authenticated stream.
pub struct Session {
    /// Server game identity.
    pub id: String,
    /// Authenticated bot color.
    pub color: Player,
    /// Legal reconstructed game.
    pub game: Game,
    /// Current server clocks/status.
    pub state: ServerState,
    initial: String,
    moves: Vec<String>,
}

fn decode(line: &str) -> Result<Value, &'static str> {
    if line.len() > 65_536 {
        return Err("game event exceeds limit");
    }
    serde_json::from_str(line).map_err(|_| "malformed game JSON")
}

fn string<'a>(value: &'a Value, key: &str) -> Result<&'a str, &'static str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or("required game string missing")
}

fn state(value: &Value) -> Result<ServerState, &'static str> {
    let status = string(value, "status")?;
    if !matches!(
        status,
        "created"
            | "started"
            | "aborted"
            | "mate"
            | "resign"
            | "stalemate"
            | "timeout"
            | "draw"
            | "outoftime"
            | "cheat"
            | "noStart"
            | "unknownFinish"
            | "variantEnd"
    ) {
        return Err("unknown game status");
    }
    let winner = match value.get("winner") {
        Some(Value::String(winner)) if winner == "white" => Some(Player::White),
        Some(Value::String(winner)) if winner == "black" => Some(Player::Black),
        None | Some(Value::Null) => None,
        _ => return Err("invalid winner"),
    };
    if winner.is_some() && matches!(status, "created" | "started" | "draw" | "aborted") {
        return Err("winner contradicts game status");
    }
    Ok(ServerState {
        status: status.into(),
        winner,
        white_ms: value
            .get("wtime")
            .and_then(Value::as_u64)
            .ok_or("White clock missing")?,
        black_ms: value
            .get("btime")
            .and_then(Value::as_u64)
            .ok_or("Black clock missing")?,
    })
}

impl Session {
    /// Reconstruct a full game with explicit supported/allowed variant gating.
    ///
    /// # Errors
    /// Rejects unsupported variants, unrelated accounts, invalid FEN/history or fields.
    pub fn from_full(line: &str, account: &str, allowed: &[Variant]) -> Result<Self, &'static str> {
        let value = decode(line)?;
        if string(&value, "type")? != "gameFull" {
            return Err("expected gameFull");
        }
        let id = string(&value, "id")?;
        if id.is_empty() || id.len() > 32 || !id.bytes().all(|byte| byte.is_ascii_alphanumeric()) {
            return Err("invalid game identity");
        }
        let key = value
            .get("variant")
            .and_then(|v| v.get("key"))
            .and_then(Value::as_str)
            .ok_or("variant missing")?;
        let variant = super::variant_from_lichess(key)
            .filter(|variant| {
                allowed.contains(variant)
                    && !matches!(variant, Variant::Crazyhouse | Variant::FourPlayer)
            })
            .ok_or("unsupported or disabled variant")?;
        let white = value
            .get("white")
            .and_then(|v| v.get("id"))
            .and_then(Value::as_str)
            .ok_or("White identity missing")?;
        let black = value
            .get("black")
            .and_then(|v| v.get("id"))
            .and_then(Value::as_str)
            .ok_or("Black identity missing")?;
        let color = if !account.is_empty()
            && white.eq_ignore_ascii_case(account)
            && !black.eq_ignore_ascii_case(account)
        {
            Player::White
        } else if !account.is_empty()
            && black.eq_ignore_ascii_case(account)
            && !white.eq_ignore_ascii_case(account)
        {
            Player::Black
        } else {
            return Err("account does not identify exactly one player");
        };
        let fen = string(&value, "initialFen")?;
        let initial = if fen == "startpos" {
            initial_fen(variant)
        } else {
            fen
        };
        let state_value = value.get("state").ok_or("full state missing")?;
        let state = state(state_value)?;
        let moves: Vec<_> = string(state_value, "moves")?
            .split_whitespace()
            .map(str::to_owned)
            .collect();
        let mut game = Game::from_fen(initial, variant).map_err(|_| "invalid initial FEN")?;
        for mv in &moves {
            if !game.push_uci(mv) {
                return Err("illegal game history");
            }
        }
        Ok(Self {
            id: id.into(),
            color,
            game,
            state,
            initial: initial.into(),
            moves,
        })
    }

    /// Apply a cumulative gameState transaction, preserving state on any error.
    /// Duplicate/reconnected snapshots are idempotent; divergent histories fail closed.
    ///
    /// # Errors
    /// Rejects out-of-order/divergent moves, invalid clocks or illegal transitions.
    pub fn update(&mut self, line: &str) -> Result<(), &'static str> {
        let value = decode(line)?;
        if string(&value, "type")? != "gameState" {
            return Err("expected gameState");
        }
        let next_state = state(&value)?;
        if !self.state.active() && next_state != self.state {
            return Err("completed game state changed");
        }
        let moves: Vec<_> = string(&value, "moves")?
            .split_whitespace()
            .map(str::to_owned)
            .collect();
        if !moves.starts_with(&self.moves) {
            return Err("game history diverged");
        }
        let mut replacement = self.game.clone();
        for mv in &moves[self.moves.len()..] {
            if !replacement.push_uci(mv) {
                return Err("illegal game update");
            }
        }
        self.game = replacement;
        self.moves = moves;
        self.state = next_state;
        Ok(())
    }

    /// Frozen initial position for journals and reconnect identity checks.
    #[must_use]
    pub fn initial_fen(&self) -> &str {
        &self.initial
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn full(key: &str) -> String {
        serde_json::json!({"type":"gameFull", "id":"Abcd1234", "variant":{"key":key}, "initialFen":"startpos", "white":{"id":"EloiBot"}, "black":{"id":"opponent"}, "state":{"moves":"", "status":"started", "wtime":300_000, "btime":300_000}}).to_string()
    }

    #[test]
    fn all_six_variants_reconstruct_without_cross_routing() {
        for key in [
            "standard",
            "chess960",
            "horde",
            "kingOfTheHill",
            "atomic",
            "antichess",
        ] {
            let variant = super::super::variant_from_lichess(key).unwrap();
            let session = Session::from_full(&full(key), "eloibot", &[variant]).unwrap();
            assert_eq!(session.game.position().variant, variant);
            assert_eq!(session.color, Player::White);
            assert!(session.state.active());
        }
        assert!(
            Session::from_full(&full("crazyhouse"), "eloibot", &[Variant::Crazyhouse]).is_err()
        );
        assert!(Session::from_full(&full("standard"), "stranger", &[Variant::Standard]).is_err());
    }

    #[test]
    fn updates_are_legal_transactional_and_idempotent() {
        let mut session =
            Session::from_full(&full("standard"), "eloibot", &[Variant::Standard]).unwrap();
        let update = |moves| {
            serde_json::json!({"type":"gameState", "moves":moves, "status":"started", "wtime":299_000,"btime":299_000}).to_string()
        };
        session.update(&update("e2e4 e7e5")).unwrap();
        let frozen = session.game.clone();
        session.update(&update("e2e4 e7e5")).unwrap();
        assert_eq!(session.game, frozen);
        assert!(session.update(&update("e2e4 e7e5 e4e6")).is_err());
        assert!(session.update(&update("d2d4")).is_err());
        assert_eq!(session.game, frozen);
    }

    #[test]
    fn chunks_keep_utf8_and_json_boundaries() {
        let mut lines = StreamLines::default();
        assert!(lines.feed(b"\n{\"type\":").unwrap().is_empty());
        assert_eq!(
            lines.feed(b"\"gameState\"}\r\n").unwrap(),
            vec!["{\"type\":\"gameState\"}"]
        );
        assert!(lines.feed(&vec![b'x'; 65_536]).unwrap().is_empty());
        assert!(lines.feed(b"x").is_err());
        assert!(StreamLines::default().feed(&[0xff, b'\n']).is_err());
    }

    #[test]
    fn terminal_status_and_malformed_winner_are_not_fabricated() {
        let mut session =
            Session::from_full(&full("standard"), "eloibot", &[Variant::Standard]).unwrap();
        let mut event = serde_json::json!({"type":"gameState", "moves":"", "status":"started", "wtime":300_000, "btime":300_000, "winner":42});
        assert!(session.update(&event.to_string()).is_err());
        event["winner"] = Value::String("white".into());
        assert!(session.update(&event.to_string()).is_err());
        event["status"] = Value::String("resign".into());
        session.update(&event.to_string()).unwrap();
        assert_eq!(session.state.winner, Some(Player::White));
        assert!(!session.state.active());
        event["status"] = Value::String("started".into());
        event.as_object_mut().unwrap().remove("winner");
        assert!(session.update(&event.to_string()).is_err());
    }
}
