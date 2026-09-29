//! Injectable network seam and token-free control-stream decisions.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use serde_json::Value;

use crate::bridge::{Controller, State};
use crate::config::RuntimeConfig;

/// HTTP reply metadata; raw bodies belong only to bounded parsers, never logs.
pub struct Reply {
    /// Actual status, zero only for transport failure.
    pub status: u16,
    /// Parsed Retry-After delay.
    pub retry_after_seconds: Option<u32>,
    /// Bounded response bytes, excluding headers.
    pub body: Vec<u8>,
}

/// Adapter seam. Implementations must enforce the exact HTTPS origin, reject
/// redirects carrying credentials and make cancellation interrupt blocked reads.
pub trait Transport: Send + Sync {
    /// Request a bounded account response.
    ///
    /// # Errors
    /// Returns a token-free transport/cancellation diagnostic.
    fn account(&self, cancelled: &AtomicBool) -> Result<Reply, &'static str>;
    /// Submit an authenticated form to a fixed Lichess API path.
    ///
    /// # Errors
    /// Returns a token-free transport/cancellation diagnostic.
    fn post(&self, path: &str, form: &str, cancelled: &AtomicBool) -> Result<Reply, &'static str>;
    /// Stream raw chunks; returning false from the consumer stops immediately.
    ///
    /// # Errors
    /// Returns a token-free transport/cancellation diagnostic.
    fn stream(
        &self,
        path: &str,
        cancelled: &AtomicBool,
        consumer: &mut dyn FnMut(&[u8]) -> bool,
    ) -> Result<Reply, &'static str>;
    /// Must be safe on another thread and release a blocked active request.
    fn cancel(&self);
}

/// Action derived from a control event; no hidden live side effects.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Action {
    /// Accept a validated challenge.
    Accept(String),
    /// Decline unsupported/disabled/busy challenges.
    Decline(String),
    /// Attach exactly one reported active game.
    AttachGame(String),
    /// Event has no supported control action.
    Ignore,
}

fn identity(value: &Value) -> Result<&str, &'static str> {
    let id = value
        .get("id")
        .and_then(Value::as_str)
        .ok_or("control identity missing")?;
    if id.is_empty()
        || id.len() > 32
        || !id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
    {
        return Err("control identity malformed");
    }
    Ok(id)
}

/// Single owned bridge session, injectable for offline transport validation.
pub struct Supervisor<T: Transport> {
    /// Redacted state consumed by dashboard/headless views.
    pub controller: Controller,
    transport: Arc<T>,
    config: RuntimeConfig,
    account: Option<String>,
    attached_game: Option<String>,
}

impl<T: Transport> Supervisor<T> {
    /// Build an inert supervisor; construction never opens a network connection.
    pub fn new(transport: Arc<T>, config: RuntimeConfig) -> Self {
        Self {
            controller: Controller::default(),
            transport,
            config,
            account: None,
            attached_game: None,
        }
    }

    /// Authenticate once with bounded parsing; raw account JSON is not retained.
    ///
    /// # Errors
    /// Returns static token-free diagnostics and preserves fatal/retry policy.
    pub fn connect(&mut self) -> Result<(), &'static str> {
        if !self.config.enabled {
            return Err("Lichess is disabled in configuration");
        }
        if self.config.token.expose_for_transport().is_empty() {
            return Err("Lichess token is empty");
        }
        match self.controller.snapshot().state {
            State::Stopped => {
                self.controller.start();
            }
            State::BackingOff => {}
            _ => return Err("bridge is not ready to connect"),
        }
        let cancellation = self.controller.cancellation();
        let reply = match self.transport.account(&cancellation) {
            Ok(reply) => reply,
            Err(error) => {
                self.controller.failure(0, None, "account transport failed");
                return Err(error);
            }
        };
        if reply.status != 200 {
            self.controller.failure(
                reply.status,
                reply.retry_after_seconds,
                "account request failed",
            );
            return Err("account HTTP failure");
        }
        let account = parse_account(&reply.body);
        match account {
            Ok(account) => {
                self.account = Some(account);
                self.controller.connected();
                Ok(())
            }
            Err(error) => {
                self.controller
                    .protocol_incident("malformed account response");
                Err(error)
            }
        }
    }

    /// Authenticated account name, safe for status display.
    #[must_use]
    pub fn account(&self) -> Option<&str> {
        self.account.as_deref()
    }

    /// Bind the owned game stream only after legal full-history reconstruction.
    ///
    /// # Errors
    /// Rejects account, variant or identity mismatches without changing the controller.
    pub fn game_full(&mut self, line: &str) -> Result<crate::lichess::Session, &'static str> {
        let account = self
            .account
            .as_deref()
            .ok_or("account is not authenticated")?;
        let session = crate::lichess::Session::from_full(line, account, &self.config.variants)?;
        if self.attached_game.as_deref() != Some(session.id.as_str()) {
            return Err("game stream does not match owned identity");
        }
        if self.controller.snapshot().game.as_deref() != Some(session.id.as_str())
            && !self.controller.begin_game(&session.id)
        {
            return Err("controller cannot begin this game");
        }
        Ok(session)
    }

    /// Release exactly one terminal owned game and count only explicit results.
    ///
    /// # Errors
    /// Active/unrelated games cannot release ownership or modify counters.
    pub fn finish_session(
        &mut self,
        session: &crate::lichess::Session,
    ) -> Result<(), &'static str> {
        if session.state.active() || self.attached_game.as_deref() != Some(session.id.as_str()) {
            return Err("game is not an owned completed session");
        }
        let result = match session.state.winner {
            Some(winner) => Some(if winner == session.color {
                std::cmp::Ordering::Greater
            } else {
                std::cmp::Ordering::Less
            }),
            None if matches!(session.state.status.as_str(), "draw" | "stalemate") => {
                Some(std::cmp::Ordering::Equal)
            }
            None => None,
        };
        if !self.controller.finish_game(&session.id, result) {
            return Err("completed game was not active in controller");
        }
        self.attached_game = None;
        Ok(())
    }

    /// Classify a bounded control event and reserve one game attachment.
    ///
    /// # Errors
    /// Rejects malformed events and duplicate concurrent game ownership.
    pub fn control(&mut self, line: &str) -> Result<Action, &'static str> {
        if line.len() > 65_536 {
            return Err("control event exceeds limit");
        }
        if !matches!(
            self.controller.snapshot().state,
            State::Connected | State::Playing
        ) {
            return Err("control stream is not connected");
        }
        let value: Value = serde_json::from_str(line).map_err(|_| "malformed control JSON")?;
        match value.get("type").and_then(Value::as_str) {
            Some("challenge") => {
                let challenge = value.get("challenge").ok_or("challenge missing")?;
                let id = identity(challenge)?.to_owned();
                let variant = challenge
                    .get("variant")
                    .and_then(|v| v.get("key"))
                    .and_then(Value::as_str)
                    .and_then(crate::variant_from_lichess);
                let base = challenge
                    .get("timeControl")
                    .and_then(|clock| clock.get("limit"))
                    .and_then(Value::as_u64);
                let challenger = challenge.get("challenger").ok_or("challenger missing")?;
                let bot = challenger.get("title").and_then(Value::as_str) == Some("BOT");
                let allowed = self.controller.snapshot().accepting
                    && self.attached_game.is_none()
                    && variant.is_some_and(|v| self.config.variants.contains(&v))
                    && base.is_some_and(|seconds| {
                        seconds >= u64::from(self.config.min_base_seconds)
                            && seconds <= u64::from(self.config.max_base_seconds)
                    })
                    && (!bot || self.config.allow_bots);
                Ok(if allowed {
                    Action::Accept(id)
                } else {
                    Action::Decline(id)
                })
            }
            Some("gameStart") => {
                let id = identity(value.get("game").ok_or("game missing")?)?.to_owned();
                if self.attached_game.as_deref() == Some(&id) {
                    return Ok(Action::Ignore);
                }
                if self.attached_game.is_some() {
                    return Err("another game is already owned");
                }
                self.attached_game = Some(id.clone());
                Ok(Action::AttachGame(id))
            }
            Some(_) => Ok(Action::Ignore),
            None => Err("control event type missing"),
        }
    }

    /// Perform only validated challenge actions, recording successful outcomes.
    ///
    /// # Errors
    /// HTTP/transport failure does not count as successful acceptance/decline.
    pub fn challenge_action(&mut self, action: &Action) -> Result<(), &'static str> {
        if !matches!(
            self.controller.snapshot().state,
            State::Connected | State::Playing
        ) {
            return Err("challenge action while disconnected");
        }
        let (id, accepted) = match action {
            Action::Accept(id) => (id, true),
            Action::Decline(id) => (id, false),
            _ => return Err("not a challenge action"),
        };
        if accepted && (!self.controller.snapshot().accepting || self.attached_game.is_some()) {
            return Err("challenge acceptance is no longer allowed");
        }
        identity(&serde_json::json!({"id":id}))?;
        let path = format!(
            "/api/challenge/{id}/{}",
            if accepted { "accept" } else { "decline" }
        );
        let reply = self
            .transport
            .post(&path, "", &self.controller.cancellation())?;
        if !(200..=299).contains(&reply.status) {
            return Err("challenge HTTP failure");
        }
        self.controller.record_challenge(accepted);
        Ok(())
    }

    /// Stop both search signal and blocking transport, without fabricating results.
    pub fn stop(&mut self) {
        self.controller.stop();
        self.transport.cancel();
    }

    /// Called only after owned stream/search work has joined.
    pub fn stopped(&mut self) {
        self.attached_game = None;
        self.controller.stopped();
    }
}

fn parse_account(body: &[u8]) -> Result<String, &'static str> {
    if body.len() > 65_536 {
        return Err("account response exceeds limit");
    }
    let value: Value = serde_json::from_slice(body).map_err(|_| "malformed account JSON")?;
    identity(&value).map(str::to_owned)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;
    use std::sync::atomic::Ordering;

    struct Fake {
        status: u16,
        posts: Mutex<Vec<String>>,
        cancelled: AtomicBool,
    }
    impl Transport for Fake {
        fn account(&self, _: &AtomicBool) -> Result<Reply, &'static str> {
            Ok(Reply {
                status: self.status,
                retry_after_seconds: None,
                body: br#"{"id":"eloibot"}"#.to_vec(),
            })
        }
        fn post(&self, path: &str, _: &str, _: &AtomicBool) -> Result<Reply, &'static str> {
            self.posts.lock().unwrap().push(path.into());
            Ok(Reply {
                status: 200,
                retry_after_seconds: None,
                body: Vec::new(),
            })
        }
        fn stream(
            &self,
            _: &str,
            cancelled: &AtomicBool,
            _: &mut dyn FnMut(&[u8]) -> bool,
        ) -> Result<Reply, &'static str> {
            if cancelled.load(Ordering::Relaxed) {
                Err("cancelled")
            } else {
                Ok(Reply {
                    status: 200,
                    retry_after_seconds: None,
                    body: Vec::new(),
                })
            }
        }
        fn cancel(&self) {
            self.cancelled.store(true, Ordering::Relaxed);
        }
    }

    fn supervisor(status: u16) -> Supervisor<Fake> {
        let config =
            crate::config::parse("lichess:\n  enabled: true\n  token: lip_offline_fixture\n")
                .unwrap();
        Supervisor::new(
            Arc::new(Fake {
                status,
                posts: Mutex::new(Vec::new()),
                cancelled: AtomicBool::new(false),
            }),
            config,
        )
    }

    #[test]
    fn offline_auth_challenges_game_ownership_and_cancel() {
        let mut supervisor = supervisor(200);
        supervisor.connect().unwrap();
        assert_eq!(supervisor.account(), Some("eloibot"));
        let challenge = |key| {
            serde_json::json!({"type":"challenge", "challenge":{"id":"Abcd1234", "variant":{"key":key}, "timeControl":{"limit":300}, "challenger":{"title":"BOT"}}}).to_string()
        };
        let action = supervisor.control(&challenge("standard")).unwrap();
        assert_eq!(action, Action::Accept("Abcd1234".into()));
        supervisor.challenge_action(&action).unwrap();
        assert_eq!(supervisor.controller.snapshot().counters.accepted, 1);
        assert!(matches!(
            supervisor.control(&challenge("crazyhouse")).unwrap(),
            Action::Decline(_)
        ));
        let game = r#"{"type":"gameStart","game":{"id":"Game1234"}}"#;
        assert!(matches!(
            supervisor.control(game).unwrap(),
            Action::AttachGame(_)
        ));
        assert_eq!(supervisor.control(game).unwrap(), Action::Ignore);
        assert!(
            supervisor
                .control(r#"{"type":"gameStart","game":{"id":"Other123"}}"#)
                .is_err()
        );
        let full = serde_json::json!({"type":"gameFull", "id":"Game1234", "variant":{"key":"standard"}, "initialFen":"startpos", "white":{"id":"eloibot"}, "black":{"id":"opponent"}, "state":{"moves":"", "status":"started", "wtime":300_000,"btime":300_000}}).to_string();
        let mut session = supervisor.game_full(&full).unwrap();
        assert_eq!(supervisor.controller.snapshot().state, State::Playing);
        assert!(supervisor.finish_session(&session).is_err());
        session.update(r#"{"type":"gameState","moves":"","status":"aborted","wtime":300000,"btime":300000}"#).unwrap();
        supervisor.finish_session(&session).unwrap();
        assert_eq!(supervisor.controller.snapshot().counters.draws, 0);
        assert!(supervisor.finish_session(&session).is_err());
        supervisor.stop();
        assert!(supervisor.transport.cancelled.load(Ordering::Relaxed));
        supervisor.stopped();
        assert_eq!(supervisor.controller.snapshot().state, State::Stopped);
    }

    #[test]
    fn auth_failure_is_fatal_and_no_connection_without_token() {
        let mut supervisor = supervisor(401);
        assert!(supervisor.connect().is_err());
        assert_eq!(supervisor.controller.snapshot().state, State::Fatal);
        assert!(supervisor.transport.posts.lock().unwrap().is_empty());
        assert!(parse_account(br#"{"id":"bad/path"}"#).is_err());
        let mut retry = super::tests::supervisor(503);
        assert!(retry.connect().is_err());
        assert_eq!(retry.controller.snapshot().state, State::BackingOff);
        assert!(retry.connect().is_err());
        assert_eq!(retry.controller.snapshot().attempts, 2);
        let mut empty = super::tests::supervisor(200);
        empty.config = RuntimeConfig::default();
        assert!(empty.connect().is_err());
        assert_eq!(empty.controller.snapshot().state, State::Stopped);
    }
}
