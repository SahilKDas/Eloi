//! Native Windows surfaces rendered through tiny-skia.

mod render;

#[cfg(windows)]
mod windows;

pub use render::{Surface, SurfaceKind};

/// Open the requested visible native surface and block until it closes.
///
/// # Errors
/// Returns an OS initialization or rendering failure.
#[cfg(windows)]
pub fn run(kind: SurfaceKind) -> std::io::Result<()> {
    windows::run(kind, None)
}

/// Open the single-instance Operations Center and start its supervised worker
/// only after the dashboard owns the instance mutex.
///
/// # Errors
/// Returns an OS initialization or rendering failure.
#[cfg(windows)]
pub fn run_supervised(start: impl FnOnce() + Send + 'static) -> std::io::Result<()> {
    windows::run(SurfaceKind::Operations, Some(Box::new(start)))
}

/// Native UI is intentionally Windows-only for this release.
#[cfg(not(windows))]
pub fn run(_: SurfaceKind) -> std::io::Result<()> {
    Err(std::io::Error::other("native Eloi UI requires Windows"))
}

/// Supervised bridge UI is unavailable away from Windows.
#[cfg(not(windows))]
pub fn run_supervised(_: impl FnOnce() + Send + 'static) -> std::io::Result<()> {
    Err(std::io::Error::other("native Eloi UI requires Windows"))
}
