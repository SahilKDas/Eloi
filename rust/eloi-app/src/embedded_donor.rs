//! Optional release-only contained donor payload.

use std::io;
use std::path::PathBuf;

#[cfg(eloi_embedded_donor)]
const WORKER: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/eloi-caissa-2.0.exe"));

/// Materialize an immutable hash-named worker only when the package embedded it.
///
/// Existing mismatched files fail closed and are never overwritten.
#[allow(clippy::unnecessary_wraps)] // Non-release builds compile only the inert branch.
pub fn materialize() -> io::Result<Option<PathBuf>> {
    #[cfg(not(eloi_embedded_donor))]
    {
        Ok(None)
    }
    #[cfg(eloi_embedded_donor)]
    {
        const IDENTITY: &str = "043C0925DF8C608D0D87B9E6B1C761240DDD1901EE8CBA49E346686B28816B97";
        let root = std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(std::env::temp_dir)
            .join("Eloi")
            .join("workers");
        std::fs::create_dir_all(&root)?;
        let path = root.join(format!("caissa-2.0-avx2-{IDENTITY}.exe"));
        if path.exists() {
            let existing = std::fs::read(&path)?;
            if existing != WORKER {
                return Err(io::Error::other("embedded donor cache identity mismatch"));
            }
            return Ok(Some(path));
        }
        let temporary = root.join(format!("worker-{}.new", std::process::id()));
        std::fs::write(&temporary, WORKER)?;
        match std::fs::rename(&temporary, &path) {
            Ok(()) => Ok(Some(path)),
            Err(_error) if path.exists() && std::fs::read(&path)? == WORKER => {
                let _ = std::fs::remove_file(temporary);
                Ok(Some(path))
            }
            Err(error) => Err(error),
        }
    }
}
