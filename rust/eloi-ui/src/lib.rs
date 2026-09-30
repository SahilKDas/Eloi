//! Native Windows surfaces rendered through tiny-skia.

use std::sync::atomic::{AtomicBool, AtomicU8, AtomicU64, Ordering};
use std::sync::{Arc, RwLock};

const RECONNECT: u8 = 1;

mod render;

#[cfg(windows)]
mod windows;

pub use render::{Surface, SurfaceKind};

/// Lock-free, token-free data shared with the visible Operations Center.
#[derive(Default)]
pub struct OperationsModel {
    state: AtomicU8,
    accepting: AtomicBool,
    wins: AtomicU64,
    draws: AtomicU64,
    losses: AtomicU64,
    incidents: AtomicU64,
    accepted: AtomicU64,
    declined: AtomicU64,
    attempts: AtomicU64,
    retry_seconds: AtomicU64,
    http_status: AtomicU64,
    stop_requested: AtomicBool,
    commands: AtomicU8,
    details: RwLock<OperationsDetails>,
}

#[derive(Clone, Debug, Default)]
struct OperationsDetails {
    account: String,
    game: String,
    variant: String,
    route: String,
    network: String,
    latest_move: String,
    pv: String,
    stop_reason: String,
    white_ms: u64,
    black_ms: u64,
    ply: u64,
    depth: u64,
    score: i64,
    nodes: u64,
    elapsed_ms: u64,
    latest_event: String,
}

/// Session-local dashboard values safe to display or copy.
#[derive(Clone, Debug, Default)]
pub struct OperationsSnapshot {
    /// Numeric supervisor state defined by the app adapter.
    pub state: u8,
    /// Whether incoming challenges are accepted.
    pub accepting: bool,
    /// Completed wins.
    pub wins: u64,
    /// Completed draws.
    pub draws: u64,
    /// Completed losses.
    pub losses: u64,
    /// Protocol incidents.
    pub incidents: u64,
    pub accepted: u64,
    pub declined: u64,
    pub attempts: u64,
    pub retry_seconds: u64,
    pub http_status: u64,
    pub account: String,
    pub game: String,
    pub variant: String,
    pub route: String,
    pub network: String,
    pub latest_move: String,
    pub pv: String,
    pub stop_reason: String,
    pub white_ms: u64,
    pub black_ms: u64,
    pub ply: u64,
    pub depth: u64,
    pub score: i64,
    pub nodes: u64,
    pub elapsed_ms: u64,
    pub latest_event: String,
}

impl OperationsModel {
    /// Publish only non-secret bridge health data.
    pub fn publish(&self, snapshot: OperationsSnapshot) {
        self.state.store(snapshot.state, Ordering::Relaxed);
        self.accepting.store(snapshot.accepting, Ordering::Relaxed);
        self.wins.store(snapshot.wins, Ordering::Relaxed);
        self.draws.store(snapshot.draws, Ordering::Relaxed);
        self.losses.store(snapshot.losses, Ordering::Relaxed);
        self.incidents.store(snapshot.incidents, Ordering::Relaxed);
        self.accepted.store(snapshot.accepted, Ordering::Relaxed);
        self.declined.store(snapshot.declined, Ordering::Relaxed);
        self.attempts.store(snapshot.attempts, Ordering::Relaxed);
        self.retry_seconds
            .store(snapshot.retry_seconds, Ordering::Relaxed);
        self.http_status
            .store(snapshot.http_status, Ordering::Relaxed);
        if let Ok(mut details) = self.details.write() {
            details.account = snapshot.account;
            details.game = snapshot.game;
            details.latest_event = snapshot.latest_event;
        }
    }

    /// Read dashboard data for paint or controller synchronization.
    #[must_use]
    pub fn snapshot(&self) -> OperationsSnapshot {
        let details = self
            .details
            .read()
            .map_or_else(|_| OperationsDetails::default(), |details| details.clone());
        OperationsSnapshot {
            state: self.state.load(Ordering::Relaxed),
            accepting: self.accepting.load(Ordering::Relaxed),
            wins: self.wins.load(Ordering::Relaxed),
            draws: self.draws.load(Ordering::Relaxed),
            losses: self.losses.load(Ordering::Relaxed),
            incidents: self.incidents.load(Ordering::Relaxed),
            accepted: self.accepted.load(Ordering::Relaxed),
            declined: self.declined.load(Ordering::Relaxed),
            attempts: self.attempts.load(Ordering::Relaxed),
            retry_seconds: self.retry_seconds.load(Ordering::Relaxed),
            http_status: self.http_status.load(Ordering::Relaxed),
            account: details.account,
            game: details.game,
            variant: details.variant,
            route: details.route,
            network: details.network,
            latest_move: details.latest_move,
            pv: details.pv,
            stop_reason: details.stop_reason,
            white_ms: details.white_ms,
            black_ms: details.black_ms,
            ply: details.ply,
            depth: details.depth,
            score: details.score,
            nodes: details.nodes,
            elapsed_ms: details.elapsed_ms,
            latest_event: details.latest_event,
        }
    }

    /// Publish token-free active-game and search telemetry from the live route.
    pub fn publish_search(&self, telemetry: SearchTelemetry) {
        if let Ok(mut details) = self.details.write() {
            details.variant = telemetry.variant;
            details.route = telemetry.route;
            details.network = telemetry.network;
            details.latest_move = telemetry.latest_move;
            details.pv = telemetry.pv;
            details.stop_reason = telemetry.stop_reason;
            details.white_ms = telemetry.white_ms;
            details.black_ms = telemetry.black_ms;
            details.ply = telemetry.ply;
            details.depth = telemetry.depth;
            details.score = telemetry.score;
            details.nodes = telemetry.nodes;
            details.elapsed_ms = telemetry.elapsed_ms;
        }
    }

    /// User-facing Start/Stop accepting control.
    pub fn toggle_accepting(&self) {
        self.accepting.fetch_xor(true, Ordering::Relaxed);
    }

    /// Request cancellation of blocked network work before the window exits.
    pub fn request_stop(&self) {
        self.stop_requested.store(true, Ordering::Relaxed);
    }

    /// Request cancellation and immediate reconstruction of the live streams.
    pub fn request_reconnect(&self) {
        self.commands.fetch_or(RECONNECT, Ordering::Release);
    }

    /// Consume one pending reconnect request in the supervisor thread.
    #[must_use]
    pub fn take_reconnect(&self) -> bool {
        self.commands.fetch_and(!RECONNECT, Ordering::AcqRel) & RECONNECT != 0
    }

    /// Peek without consuming so a cancellation watcher can interrupt `WinHTTP`.
    #[must_use]
    pub fn reconnect_requested(&self) -> bool {
        self.commands.load(Ordering::Acquire) & RECONNECT != 0
    }

    /// Whether the visible owner requested controlled shutdown.
    #[must_use]
    pub fn stop_requested(&self) -> bool {
        self.stop_requested.load(Ordering::Relaxed)
    }
}

/// Search fields safe for the dashboard and clipboard diagnostics.
pub struct SearchTelemetry {
    pub variant: String,
    pub route: String,
    pub network: String,
    pub latest_move: String,
    pub pv: String,
    pub stop_reason: String,
    pub white_ms: u64,
    pub black_ms: u64,
    pub ply: u64,
    pub depth: u64,
    pub score: i64,
    pub nodes: u64,
    pub elapsed_ms: u64,
}

/// Open the requested visible native surface and block until it closes.
///
/// # Errors
/// Returns an OS initialization or rendering failure.
#[cfg(windows)]
pub fn run(kind: SurfaceKind) -> std::io::Result<()> {
    windows::run(kind, None, None, None)
}

/// Open the single-instance Operations Center and start its supervised worker
/// only after the dashboard owns the instance mutex.
///
/// # Errors
/// Returns an OS initialization or rendering failure.
#[cfg(windows)]
pub fn run_supervised(
    config_path: std::path::PathBuf,
    start: impl FnOnce(Arc<OperationsModel>) + Send + 'static,
) -> std::io::Result<()> {
    let model = Arc::new(OperationsModel::default());
    windows::run(
        SurfaceKind::Operations,
        Some(Arc::clone(&model)),
        Some(config_path),
        Some(Box::new(move || start(model))),
    )
}

/// Native UI is intentionally Windows-only for this release.
#[cfg(not(windows))]
pub fn run(_: SurfaceKind) -> std::io::Result<()> {
    Err(std::io::Error::other("native Eloi UI requires Windows"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn operations_model_exposes_only_explicit_session_values() {
        let model = OperationsModel::default();
        model.publish(OperationsSnapshot {
            state: 3,
            accepting: true,
            wins: 4,
            draws: 2,
            losses: 1,
            incidents: 0,
            ..OperationsSnapshot::default()
        });
        assert_eq!(model.snapshot().state, 3);
        assert_eq!(model.snapshot().wins, 4);
        model.toggle_accepting();
        assert!(!model.snapshot().accepting);
        model.publish_search(SearchTelemetry {
            variant: "Atomic".into(),
            route: "Eloi native".into(),
            network: "hash".into(),
            latest_move: "e2e4".into(),
            pv: "e2e4 e7e5".into(),
            stop_reason: "Depth".into(),
            white_ms: 900,
            black_ms: 800,
            ply: 4,
            depth: 7,
            score: 23,
            nodes: 1_234,
            elapsed_ms: 17,
        });
        let snapshot = model.snapshot();
        assert_eq!(snapshot.route, "Eloi native");
        assert_eq!(snapshot.latest_move, "e2e4");
        assert_eq!(snapshot.nodes, 1_234);
        model.request_stop();
        assert!(model.stop_requested());
        model.request_reconnect();
        assert!(model.reconnect_requested());
        assert!(model.take_reconnect());
        assert!(!model.take_reconnect());
    }
}

/// Supervised bridge UI is unavailable away from Windows.
#[cfg(not(windows))]
pub fn run_supervised(
    _: std::path::PathBuf,
    _: impl FnOnce(Arc<OperationsModel>) + Send + 'static,
) -> std::io::Result<()> {
    Err(std::io::Error::other("native Eloi UI requires Windows"))
}
