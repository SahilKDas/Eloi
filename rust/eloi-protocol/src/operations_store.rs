//! Token-free durable Operations Center evidence.

use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::bridge::{Snapshot, State};

const MAX_FILES: usize = 10;
const MAX_TOTAL_BYTES: u64 = 10 * 1024 * 1024;
const MAX_SESSION_BYTES: u64 = 1024 * 1024;

/// Rotating log and atomic status publisher rooted below Local `AppData`.
pub struct OperationsStore {
    log: File,
    log_path: PathBuf,
    status_path: PathBuf,
}

impl OperationsStore {
    /// Open the per-user evidence store without reading private configuration.
    ///
    /// # Errors
    /// Returns an I/O error if the per-user directory cannot be created.
    pub fn local() -> io::Result<Self> {
        let local = std::env::var_os("LOCALAPPDATA")
            .ok_or_else(|| io::Error::other("LOCALAPPDATA is unavailable"))?;
        Self::at(&PathBuf::from(local).join("Eloi"))
    }

    /// Open a store at an explicit root for deterministic offline tests.
    ///
    /// # Errors
    /// Returns an I/O error if directories or the collision-free log cannot be created.
    pub fn at(root: &Path) -> io::Result<Self> {
        let log_dir = root.join("logs").join("lichess");
        let status_dir = root.join("status");
        fs::create_dir_all(&log_dir)?;
        fs::create_dir_all(&status_dir)?;
        rotate(&log_dir)?;
        let epoch = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(io::Error::other)?
            .as_secs();
        let base = format!("lichess-{epoch}-{}", std::process::id());
        let mut suffix = 0_u16;
        let (log, log_path) = loop {
            let name = if suffix == 0 {
                format!("{base}.log")
            } else {
                format!("{base}-{suffix}.log")
            };
            let path = log_dir.join(name);
            match OpenOptions::new().create_new(true).append(true).open(&path) {
                Ok(file) => break (file, path),
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    suffix = suffix
                        .checked_add(1)
                        .ok_or_else(|| io::Error::other("log collision limit reached"))?;
                }
                Err(error) => return Err(error),
            }
        };
        Ok(Self {
            log,
            log_path,
            status_path: status_dir.join("lichess.json"),
        })
    }

    /// Append one bounded JSON event and atomically publish the current status.
    ///
    /// # Errors
    /// Returns an I/O error without exposing credentials or configuration text.
    pub fn publish(&mut self, snapshot: &Snapshot) -> io::Result<()> {
        let bytes = status_json(snapshot)?;
        if self.log.metadata()?.len() < MAX_SESSION_BYTES {
            self.log.write_all(&bytes)?;
            self.log.write_all(b"\n")?;
            self.log.flush()?;
        }
        let temporary = self
            .status_path
            .with_extension(format!("json.{}.tmp", std::process::id()));
        {
            let mut file = OpenOptions::new()
                .create(true)
                .truncate(true)
                .write(true)
                .open(&temporary)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
        }
        fs::rename(&temporary, &self.status_path)?;
        Ok(())
    }

    /// Current session log path, suitable for token-free diagnostics.
    #[must_use]
    pub fn log_path(&self) -> &Path {
        &self.log_path
    }
}

fn state_name(state: State) -> &'static str {
    match state {
        State::Stopped => "stopped",
        State::Connecting => "connecting",
        State::Connected => "connected",
        State::Playing => "playing",
        State::BackingOff => "backing_off",
        State::Fatal => "fatal",
        State::Stopping => "stopping",
    }
}

fn status_json(snapshot: &Snapshot) -> io::Result<Vec<u8>> {
    serde_json::to_vec(&serde_json::json!({
        "schema": 1,
        "state": state_name(snapshot.state),
        "accepting": snapshot.accepting,
        "game": snapshot.game,
        "reconnect_attempts": snapshot.attempts,
        "next_retry_seconds": snapshot.retry_seconds,
        "last_http_status": snapshot.http_status,
        "counters": {
            "accepted": snapshot.counters.accepted,
            "declined": snapshot.counters.declined,
            "wins": snapshot.counters.wins,
            "draws": snapshot.counters.draws,
            "losses": snapshot.counters.losses,
            "incidents": snapshot.counters.incidents,
        },
        "events": snapshot.events,
    }))
    .map_err(io::Error::other)
}

fn rotate(directory: &Path) -> io::Result<()> {
    let mut files = fs::read_dir(directory)?
        .filter_map(Result::ok)
        .filter_map(|entry| {
            let metadata = entry.metadata().ok()?;
            (metadata.is_file()
                && entry.file_name().to_string_lossy().starts_with("lichess-")
                && entry.path().extension().is_some_and(|value| value == "log"))
            .then_some((entry.path(), metadata.len(), metadata.modified().ok()))
        })
        .collect::<Vec<_>>();
    files.sort_by_key(|(path, _, modified)| (*modified, path.clone()));
    let mut total = files.iter().map(|(_, bytes, _)| *bytes).sum::<u64>();
    while files.len() >= MAX_FILES || total > MAX_TOTAL_BYTES.saturating_sub(MAX_SESSION_BYTES) {
        let (path, bytes, _) = files.remove(0);
        fs::remove_file(path)?;
        total = total.saturating_sub(bytes);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bridge::Controller;

    fn scratch(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "eloi-ops-{name}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ))
    }

    #[test]
    fn publishes_token_free_log_and_parseable_snapshot() {
        let root = scratch("publish");
        let mut controller = Controller::default();
        assert!(controller.start());
        controller.failure(503, None, "Bearer lip_SECRET");
        let mut store = OperationsStore::at(&root).unwrap();
        store.publish(controller.snapshot()).unwrap();
        store.publish(controller.snapshot()).unwrap();
        let status = fs::read(root.join("status/lichess.json")).unwrap();
        let value: serde_json::Value = serde_json::from_slice(&status).unwrap();
        assert_eq!(value["state"], "backing_off");
        let log = fs::read_to_string(store.log_path()).unwrap();
        assert!(!log.contains("SECRET"));
        assert!(log.contains("REDACTED"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rotation_keeps_room_for_one_bounded_session() {
        let root = scratch("rotate");
        let logs = root.join("logs/lichess");
        fs::create_dir_all(&logs).unwrap();
        for index in 0..12 {
            fs::write(logs.join(format!("lichess-{index:02}.log")), vec![0; 8]).unwrap();
        }
        let store = OperationsStore::at(&root).unwrap();
        let count = fs::read_dir(&logs).unwrap().count();
        assert!(count <= MAX_FILES);
        drop(store);
        fs::remove_dir_all(root).unwrap();
    }
}
