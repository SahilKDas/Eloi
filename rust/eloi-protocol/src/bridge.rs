//! Transport-independent Operations Center state and cancellation policy.
//! No network connection or production brain is selected by this module.

use std::collections::VecDeque;
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};

/// Observable supervisor states, matching the visible production dashboard.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum State {
    /// No connection is running.
    Stopped,
    /// Authentication/control stream setup is in progress.
    Connecting,
    /// Connected and idle.
    Connected,
    /// A game is active.
    Playing,
    /// A transient failure awaits a bounded retry.
    BackingOff,
    /// An actionable permanent failure requires intervention.
    Fatal,
    /// Searches and network requests are being cancelled.
    Stopping,
}

/// HTTP outcomes never implicitly restart authentication failures.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HttpDisposition {
    /// Successful HTTP response.
    Success,
    /// Retryable transport/server failure.
    Retry,
    /// Permanent failure; preserve an actionable diagnostic.
    Fatal,
}

/// Classify the actual HTTP status; zero denotes transport failure.
#[must_use]
pub const fn classify_http(status: u16) -> HttpDisposition {
    match status {
        200..=299 => HttpDisposition::Success,
        0 | 408 | 429 | 500..=599 => HttpDisposition::Retry,
        _ => HttpDisposition::Fatal,
    }
}

/// Frozen bounded backoff sequence; valid Retry-After seconds take precedence.
#[must_use]
pub fn retry_seconds(attempt: usize, status: u16, retry_after: Option<u32>) -> u32 {
    if status == 429
        && let Some(seconds) = retry_after
    {
        return seconds;
    }
    [2, 4, 8, 15, 30, 60][attempt.min(5)]
}

/// Redact Lichess token-shaped values before they enter an event buffer.
#[must_use]
pub fn redact(text: &str) -> String {
    if text.to_ascii_lowercase().contains("authorization:")
        || text.to_ascii_lowercase().contains("bearer ")
    {
        return "[REDACTED credential-bearing event]".into();
    }
    let mut output = String::new();
    let mut rest = text;
    while let Some(start) = rest.find("lip_") {
        output.push_str(&rest[..start]);
        let token = &rest[start..];
        let end = token
            .bytes()
            .take_while(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
            .count();
        output.push_str("[REDACTED]");
        rest = &token[end..];
    }
    output.push_str(rest);
    output
}

/// Session-only counters, not persistent strength evidence.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct Counters {
    /// Accepted challenges.
    pub accepted: u64,
    /// Declined challenges.
    pub declined: u64,
    /// Completed wins.
    pub wins: u64,
    /// Completed draws.
    pub draws: u64,
    /// Completed losses.
    pub losses: u64,
    /// Invalid internal/protocol transitions.
    pub incidents: u64,
}

/// UI-safe snapshot. Credentials and HTTP payloads have no fields here.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Snapshot {
    /// Current supervisor state.
    pub state: State,
    /// Whether new challenges may be accepted.
    pub accepting: bool,
    /// Active game identifier, absent outside games.
    pub game: Option<String>,
    /// Retry attempt count.
    pub attempts: usize,
    /// Seconds until the next network retry.
    pub retry_seconds: u32,
    /// Last observed status.
    pub http_status: u16,
    /// Session counters.
    pub counters: Counters,
    /// Bounded redacted event messages.
    pub events: VecDeque<String>,
}

/// Reducer shared by visible and headless supervisors. Transport adapters must
/// additionally cancel blocking operations when this signal is set.
pub struct Controller {
    snapshot: Snapshot,
    cancelled: Arc<AtomicBool>,
}

impl Default for Controller {
    fn default() -> Self {
        Self {
            snapshot: Snapshot {
                state: State::Stopped,
                accepting: true,
                game: None,
                attempts: 0,
                retry_seconds: 0,
                http_status: 0,
                counters: Counters::default(),
                events: VecDeque::new(),
            },
            cancelled: Arc::new(AtomicBool::new(false)),
        }
    }
}

impl Controller {
    /// Immutable token-free state for the dashboard or status serializer.
    #[must_use]
    pub const fn snapshot(&self) -> &Snapshot {
        &self.snapshot
    }

    /// Search/network cancellation handle shared without locking live work.
    #[must_use]
    pub fn cancellation(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.cancelled)
    }

    fn event(&mut self, message: &str) {
        // Enforce a byte bound as well as an event-count bound.
        let end = message
            .char_indices()
            .map(|(index, _)| index)
            .find(|&index| index >= 2048)
            .unwrap_or(message.len());
        self.snapshot.events.push_back(redact(&message[..end]));
        while self.snapshot.events.len() > 128 {
            self.snapshot.events.pop_front();
        }
    }

    /// Begin only from a fully stopped supervisor; fatal failures need explicit reset.
    pub fn start(&mut self) -> bool {
        if self.snapshot.state != State::Stopped {
            return false;
        }
        self.cancelled.store(false, Ordering::Relaxed);
        self.snapshot.state = State::Connecting;
        self.event("connecting");
        true
    }

    /// Successful authenticated connection, preserving an active game on reconnect.
    pub fn connected(&mut self) -> bool {
        if !matches!(self.snapshot.state, State::Connecting | State::BackingOff) {
            return false;
        }
        self.snapshot.state = if self.snapshot.game.is_some() {
            State::Playing
        } else {
            State::Connected
        };
        self.snapshot.attempts = 0;
        self.snapshot.retry_seconds = 0;
        self.event("connected");
        true
    }

    /// Observe a failed request without retries for authentication or malformed data.
    pub fn failure(&mut self, status: u16, retry_after: Option<u32>, message: &str) {
        if matches!(
            self.snapshot.state,
            State::Stopping | State::Stopped | State::Fatal
        ) {
            return;
        }
        self.snapshot.http_status = status;
        if classify_http(status) == HttpDisposition::Retry {
            self.snapshot.retry_seconds =
                retry_seconds(self.snapshot.attempts, status, retry_after);
            self.snapshot.attempts = self.snapshot.attempts.saturating_add(1);
            self.snapshot.state = State::BackingOff;
        } else {
            self.snapshot.state = State::Fatal;
            self.cancelled.store(true, Ordering::Relaxed);
        }
        self.event(message);
    }

    /// Begin a single owned game only while the stream is connected.
    pub fn begin_game(&mut self, id: &str) -> bool {
        if self.snapshot.state != State::Connected
            || self.snapshot.game.is_some()
            || id.is_empty()
            || id.len() > 32
            || !id.bytes().all(|b| b.is_ascii_alphanumeric())
        {
            return false;
        }
        self.snapshot.game = Some(id.to_owned());
        self.snapshot.state = State::Playing;
        self.event("game started");
        true
    }

    /// Complete once; None denotes aborted/interrupted, not a fabricated draw.
    pub fn finish_game(&mut self, id: &str, result: Option<std::cmp::Ordering>) -> bool {
        if self.snapshot.game.as_deref() != Some(id) {
            return false;
        }
        match result {
            Some(std::cmp::Ordering::Greater) => self.snapshot.counters.wins += 1,
            Some(std::cmp::Ordering::Equal) => self.snapshot.counters.draws += 1,
            Some(std::cmp::Ordering::Less) => self.snapshot.counters.losses += 1,
            None => {}
        }
        self.snapshot.game = None;
        if self.snapshot.state == State::Playing {
            self.snapshot.state = State::Connected;
        }
        self.event("game ended");
        true
    }

    /// Toggle new challenge acceptance without disturbing an active game.
    pub fn set_accepting(&mut self, accepting: bool) {
        self.snapshot.accepting = accepting;
    }

    /// User-requested reconnect clears transient backoff without reviving a
    /// stopped/fatal controller or discarding the active game identity.
    pub fn reconnect_now(&mut self) -> bool {
        if matches!(
            self.snapshot.state,
            State::Stopping | State::Stopped | State::Fatal
        ) {
            return false;
        }
        self.snapshot.state = State::Connecting;
        self.snapshot.attempts = 0;
        self.snapshot.retry_seconds = 0;
        self.event("manual reconnect");
        true
    }

    /// Count the observed challenge decision without changing connection state.
    pub fn record_challenge(&mut self, accepted: bool) {
        if accepted {
            self.snapshot.counters.accepted = self.snapshot.counters.accepted.saturating_add(1);
        } else {
            self.snapshot.counters.declined = self.snapshot.counters.declined.saturating_add(1);
        }
    }

    /// Preserve an internal protocol incident and stop automatic recovery.
    pub fn protocol_incident(&mut self, message: &str) {
        self.snapshot.counters.incidents = self.snapshot.counters.incidents.saturating_add(1);
        self.failure(400, None, message);
    }

    /// Cancel immediately; transport completion must call `stopped` after joining.
    pub fn stop(&mut self) {
        self.cancelled.store(true, Ordering::Relaxed);
        self.snapshot.state = State::Stopping;
        self.event("stopping");
    }

    /// Mark teardown complete, preserving counters but never assigning interrupted results.
    pub fn stopped(&mut self) {
        self.snapshot.state = State::Stopped;
        self.snapshot.game = None;
        self.snapshot.retry_seconds = 0;
        self.event("stopped");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reconnect_preserves_game_but_stop_never_invents_result() {
        let mut controller = Controller::default();
        assert!(controller.start());
        assert!(!controller.start());
        assert!(controller.connected());
        assert!(controller.begin_game("Abcd1234"));
        controller.failure(429, Some(47), "lip_SECRET-token rate limited");
        assert_eq!(controller.snapshot().retry_seconds, 47);
        assert!(controller.connected());
        assert_eq!(controller.snapshot().state, State::Playing);
        assert!(!controller.finish_game("other", Some(std::cmp::Ordering::Equal)));
        let cancellation = controller.cancellation();
        controller.stop();
        assert!(cancellation.load(Ordering::Relaxed));
        controller.stopped();
        assert_eq!(controller.snapshot().counters.draws, 0);
        assert!(
            controller
                .snapshot()
                .events
                .iter()
                .all(|event| !event.contains("SECRET"))
        );
    }

    #[test]
    fn fatal_authentication_and_bounded_event_history() {
        let mut controller = Controller::default();
        controller.start();
        controller.failure(401, None, "authentication failed");
        assert_eq!(controller.snapshot().state, State::Fatal);
        assert!(!controller.connected());
        assert!(!controller.start());
        for _ in 0..200 {
            controller.event(&"é".repeat(3000));
        }
        assert_eq!(controller.snapshot().events.len(), 128);
        assert!(
            controller
                .snapshot()
                .events
                .iter()
                .all(|event| event.len() <= 2048)
        );
        for (attempt, seconds) in [2, 4, 8, 15, 30, 60, 60].into_iter().enumerate() {
            assert_eq!(retry_seconds(attempt, 503, Some(99)), seconds);
        }
        assert_eq!(classify_http(403), HttpDisposition::Fatal);
        assert_eq!(classify_http(408), HttpDisposition::Retry);
        assert_eq!(classify_http(600), HttpDisposition::Fatal);
        assert!(!redact("Authorization: Bearer secret").contains("secret"));
    }

    #[test]
    fn manual_reconnect_clears_backoff_and_preserves_active_game() {
        let mut controller = Controller::default();
        assert!(controller.start());
        assert!(controller.connected());
        assert!(controller.begin_game("Game1234"));
        controller.failure(503, None, "server unavailable");
        assert!(controller.reconnect_now());
        assert_eq!(controller.snapshot().state, State::Connecting);
        assert_eq!(controller.snapshot().game.as_deref(), Some("Game1234"));
        assert_eq!(controller.snapshot().retry_seconds, 0);
        assert!(controller.connected());
        assert_eq!(controller.snapshot().state, State::Playing);
    }

    #[test]
    fn completion_and_challenge_counters_are_session_local() {
        let mut controller = Controller::default();
        controller.start();
        controller.connected();
        controller.record_challenge(true);
        controller.record_challenge(false);
        controller.set_accepting(false);
        assert!(controller.begin_game("game1234"));
        assert!(controller.finish_game("game1234", Some(std::cmp::Ordering::Greater)));
        assert!(!controller.finish_game("game1234", Some(std::cmp::Ordering::Greater)));
        assert_eq!(controller.snapshot().counters.wins, 1);
        assert_eq!(controller.snapshot().counters.accepted, 1);
        assert_eq!(controller.snapshot().counters.declined, 1);
        assert!(!controller.snapshot().accepting);
        controller.protocol_incident("malformed game event");
        assert_eq!(controller.snapshot().state, State::Fatal);
        assert_eq!(controller.snapshot().counters.incidents, 1);
    }
}
