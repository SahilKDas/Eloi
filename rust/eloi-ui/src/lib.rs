//! Native Windows surfaces rendered through tiny-skia.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU8, AtomicU64, Ordering};

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
    stop_requested: AtomicBool,
    commands: AtomicU8,
}

/// Session-local dashboard values safe to display or copy.
#[derive(Clone, Copy, Debug, Default)]
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
    }

    /// Read dashboard data for paint or controller synchronization.
    #[must_use]
    pub fn snapshot(&self) -> OperationsSnapshot {
        OperationsSnapshot {
            state: self.state.load(Ordering::Relaxed),
            accepting: self.accepting.load(Ordering::Relaxed),
            wins: self.wins.load(Ordering::Relaxed),
            draws: self.draws.load(Ordering::Relaxed),
            losses: self.losses.load(Ordering::Relaxed),
            incidents: self.incidents.load(Ordering::Relaxed),
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
        });
        assert_eq!(model.snapshot().state, 3);
        assert_eq!(model.snapshot().wins, 4);
        model.toggle_accepting();
        assert!(!model.snapshot().accepting);
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
