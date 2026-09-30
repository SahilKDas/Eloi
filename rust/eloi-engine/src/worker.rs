//! Owned Rust donor process with explicit deadlines and authoritative legality.

use std::fs::File;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use sha2::{Digest, Sha256};

use eloi_core::Variant;
use eloi_core::game::Game;
use eloi_core::rules::Move8;

/// Published SHA-256 of the qualified official Caissa 2.0 AVX2 release asset.
pub const DONOR_SHA256: &str = "043c0925df8c608d0d87b9e6b1c761240ddd1901ee8cba49e346686b28816b97";

/// Completed donor search, translated through Eloi's legal-move authority.
#[derive(Clone, Debug)]
pub struct SearchReport {
    /// Legal root move.
    pub best_move: Move8,
    /// Last completed depth reported by the donor.
    pub depth: u16,
    /// Reported centipawn score, absent for mate scores.
    pub score_cp: Option<i32>,
    /// Reported mate distance.
    pub mate: Option<i32>,
    /// Reported searched nodes.
    pub nodes: u64,
    /// Legally replayed principal variation.
    pub pv: Vec<Move8>,
    /// Wall time observed by the Eloi owner.
    pub elapsed: Duration,
    /// Whether an external stop was requested.
    pub externally_stopped: bool,
}

/// A single contained, persistent Standard search process.
pub struct DonorWorker {
    child: Child,
    input: ChildStdin,
    output: Option<Receiver<io::Result<String>>>,
    reader: Option<JoinHandle<()>>,
}

fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}

fn update_info(
    game: &Game,
    fields: &[&str],
    depth: &mut u16,
    score_cp: &mut Option<i32>,
    mate: &mut Option<i32>,
    nodes: &mut u64,
    pv: &mut Vec<Move8>,
) -> io::Result<()> {
    let value = |key| {
        fields
            .iter()
            .position(|&v| v == key)
            .and_then(|i| fields.get(i + 1))
    };
    *depth = value("depth")
        .and_then(|v| v.parse().ok())
        .unwrap_or(*depth);
    *nodes = value("nodes")
        .and_then(|v| v.parse().ok())
        .unwrap_or(*nodes);
    if let Some(value) = value("cp").and_then(|v| v.parse().ok()) {
        *score_cp = Some(value);
        *mate = None;
    }
    if let Some(value) = value("mate").and_then(|v| v.parse().ok()) {
        *mate = Some(value);
        *score_cp = None;
    }
    if let Some(index) = fields.iter().position(|&v| v == "pv") {
        let mut board = game.position().clone();
        let mut moves = Vec::new();
        for text in &fields[index + 1..] {
            let mv = board
                .parse_move(text)
                .ok_or_else(|| invalid("illegal donor principal variation"))?;
            board = board
                .play(mv)
                .ok_or_else(|| invalid("PV state transition failed"))?;
            moves.push(mv);
        }
        *pv = moves;
    }
    Ok(())
}

fn bounded_line(reader: &mut impl BufRead) -> io::Result<Option<String>> {
    const LIMIT: usize = 32_768;
    let mut bytes = Vec::new();
    loop {
        let buffer = reader.fill_buf()?;
        if buffer.is_empty() {
            return if bytes.is_empty() {
                Ok(None)
            } else {
                String::from_utf8(bytes)
                    .map(Some)
                    .map_err(|_| invalid("worker output is not UTF-8"))
            };
        }
        let end = buffer.iter().position(|&byte| byte == b'\n');
        let take = end.map_or(buffer.len(), |index| index + 1);
        if bytes.len() + take > LIMIT {
            return Err(invalid("worker protocol line exceeds limit"));
        }
        bytes.extend_from_slice(&buffer[..take]);
        reader.consume(take);
        if end.is_some() {
            return String::from_utf8(bytes)
                .map(Some)
                .map_err(|_| invalid("worker output is not UTF-8"));
        }
    }
}

impl DonorWorker {
    /// Start an explicitly supplied source-built worker and complete readiness.
    ///
    /// # Errors
    /// Returns process, handshake, or readiness errors; owns and cleans up its child.
    pub fn start(path: &Path) -> io::Result<Self> {
        let mut file = File::open(path)?;
        let mut digest = Sha256::new();
        let mut buffer = [0_u8; 8 * 1024];
        loop {
            let count = file.read(&mut buffer)?;
            if count == 0 {
                break;
            }
            digest.update(&buffer[..count]);
        }
        let actual = format!("{:x}", digest.finalize());
        if actual != DONOR_SHA256 {
            return Err(invalid("donor executable SHA-256 mismatch"));
        }
        let mut command = Command::new(path);
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            // Internal worker: Idle priority, no independent console window.
            command.creation_flags(0x0000_0040 | 0x0800_0000);
        }
        let mut child = command.spawn()?;
        let input = child
            .stdin
            .take()
            .ok_or_else(|| invalid("worker stdin unavailable"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| invalid("worker stdout unavailable"))?;
        let (send, receive) = mpsc::sync_channel(256);
        let reader = thread::spawn(move || {
            let mut stdout = BufReader::new(stdout);
            loop {
                let result = match bounded_line(&mut stdout) {
                    Ok(None) => break,
                    Ok(Some(line)) => Ok(line),
                    Err(e) => Err(e),
                };
                let failed = result.is_err();
                if send.send(result).is_err() || failed {
                    break;
                }
            }
        });
        let mut worker = Self {
            child,
            input,
            output: Some(receive),
            reader: Some(reader),
        };
        worker.send("uci")?;
        let deadline = Instant::now() + Duration::from_secs(10);
        let mut identity_verified = false;
        let mut threads_supported = false;
        let mut pretty_print_supported = false;
        loop {
            let line = worker.line(deadline)?;
            let line = line.trim();
            identity_verified |= line == "id name Caissa 2.0 AVX2";
            threads_supported |= line.starts_with("option name Threads type spin ");
            pretty_print_supported |= line.starts_with("option name PrettyPrint type ");
            if line == "uciok" {
                break;
            }
        }
        if !identity_verified {
            return Err(invalid("worker is not the pinned Caissa 2.0 AVX2 donor"));
        }
        if !threads_supported {
            return Err(invalid("worker cannot enforce the three-thread contract"));
        }
        worker.send("setoption name Threads value 3")?;
        worker.send("setoption name Hash value 32")?;
        worker.send("setoption name MoveOverhead value 0")?;
        if pretty_print_supported {
            worker.send("setoption name PrettyPrint value false")?;
        }
        worker.send("isready")?;
        while worker.line(deadline)?.trim() != "readyok" {}
        Ok(worker)
    }

    fn send(&mut self, text: &str) -> io::Result<()> {
        writeln!(self.input, "{text}")?;
        self.input.flush()
    }

    fn line(&self, deadline: Instant) -> io::Result<String> {
        let duration = deadline.saturating_duration_since(Instant::now());
        self.output
            .as_ref()
            .ok_or_else(|| invalid("worker closed"))?
            .recv_timeout(duration)
            .map_err(|e| {
                io::Error::new(
                    if e == mpsc::RecvTimeoutError::Timeout {
                        io::ErrorKind::TimedOut
                    } else {
                        io::ErrorKind::BrokenPipe
                    },
                    e,
                )
            })?
    }

    /// Reset search caches without replacing the process.
    ///
    /// # Errors
    /// Returns protocol or readiness failure.
    pub fn new_game(&mut self) -> io::Result<()> {
        self.send("ucinewgame")?;
        self.send("isready")?;
        let deadline = Instant::now() + Duration::from_secs(2);
        while self.line(deadline)?.trim() != "readyok" {}
        Ok(())
    }

    /// Search Standard chess with full position history and the real time budget.
    ///
    /// # Errors
    /// Rejects variants, illegal responses, crashes, late responses and invalid PVs.
    pub fn search(
        &mut self,
        game: &Game,
        budget: Duration,
        stopped: &AtomicBool,
    ) -> io::Result<SearchReport> {
        if game.position().variant != Variant::Standard {
            return Err(invalid("Standard-only donor refused variant"));
        }
        if budget.is_zero() || budget > Duration::from_secs(60) {
            return Err(invalid("search budget outside bounded worker contract"));
        }
        if game.position().legal_moves().is_empty() {
            return Err(invalid("no legal moves in terminal position"));
        }
        let mut position = format!("position fen {}", game.initial_position().to_fen());
        let history: Vec<_> = game.moves().map(|m| m.uci(false)).collect();
        if !history.is_empty() {
            position.push_str(" moves ");
            position.push_str(&history.join(" "));
        }
        self.send(&position)?;
        let start = Instant::now();
        let stop_deadline = start + budget;
        let deadline = stop_deadline + Duration::from_millis(150);
        self.send(&format!("go movetime {}", budget.as_millis().max(1)))?;
        let mut depth = 0;
        let mut score_cp = None;
        let mut mate = None;
        let mut nodes = 0;
        let mut pv = Vec::new();
        let mut externally_stopped = false;
        let mut deadline_stop_sent = false;
        loop {
            if stopped.load(Ordering::Relaxed) && !externally_stopped {
                self.send("stop")?;
                externally_stopped = true;
            }
            let phase_deadline = if deadline_stop_sent || externally_stopped {
                deadline
            } else {
                stop_deadline
            };
            let slice = phase_deadline.min(Instant::now() + Duration::from_millis(10));
            let line = match self.line(slice) {
                Err(e)
                    if e.kind() == io::ErrorKind::TimedOut
                        && !deadline_stop_sent
                        && !externally_stopped
                        && Instant::now() >= stop_deadline =>
                {
                    self.send("stop")?;
                    deadline_stop_sent = true;
                    continue;
                }
                Err(e)
                    if e.kind() == io::ErrorKind::TimedOut && Instant::now() < phase_deadline =>
                {
                    continue;
                }
                Err(e) => {
                    let _ = self.child.kill();
                    return Err(e);
                }
                Ok(line) => line,
            };
            let fields: Vec<_> = line.split_whitespace().collect();
            if fields.first() == Some(&"bestmove") {
                let best_move = fields
                    .get(1)
                    .and_then(|text| game.position().parse_move(text))
                    .ok_or_else(|| invalid("donor returned illegal or absent move"))?;
                return Ok(SearchReport {
                    best_move,
                    depth,
                    score_cp,
                    mate,
                    nodes,
                    pv,
                    elapsed: start.elapsed(),
                    externally_stopped,
                });
            }
            if fields.first() != Some(&"info") {
                continue;
            }
            update_info(
                game,
                &fields,
                &mut depth,
                &mut score_cp,
                &mut mate,
                &mut nodes,
                &mut pv,
            )?;
        }
    }
}

impl Drop for DonorWorker {
    fn drop(&mut self) {
        // Drop receiver first to unblock a full reader queue before joining it.
        self.output.take();
        let _ = self.child.kill();
        let _ = self.child.wait();
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
    }
}

#[cfg(test)]
mod bounded_tests {
    use super::bounded_line;
    use std::io::{BufReader, Cursor};

    #[test]
    fn worker_output_is_bounded_before_allocation() {
        let mut reader = BufReader::with_capacity(7, Cursor::new(b"readyok\nlast"));
        assert_eq!(
            bounded_line(&mut reader).unwrap().as_deref(),
            Some("readyok\n")
        );
        assert_eq!(bounded_line(&mut reader).unwrap().as_deref(), Some("last"));
        assert!(bounded_line(&mut reader).unwrap().is_none());
        let mut reader = BufReader::with_capacity(8, Cursor::new(vec![b'x'; 32_769]));
        assert!(bounded_line(&mut reader).is_err());
        let mut reader = Cursor::new(vec![0xff, b'\n']);
        assert!(bounded_line(&mut reader).is_err());
    }
}
