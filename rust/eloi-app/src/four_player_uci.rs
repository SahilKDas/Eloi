//! Eloi's explicit four-player Teams UCI extension. Coordinates are four hex digits.
use eloi_core::four_player::{FourGame, FourMode, FourPosition};
use eloi_engine::four_player::{FourSearchLimits, search_four_player};
use std::io::{self, BufRead, Write};
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
use std::thread::JoinHandle;
use std::time::Duration;

struct Search {
    stop: Arc<AtomicBool>,
    publish: Arc<AtomicBool>,
    thread: JoinHandle<()>,
}
fn emit(line: &str) {
    let mut out = io::stdout().lock();
    let _ = writeln!(out, "{line}");
    let _ = out.flush();
}
fn stop(search: &mut Option<Search>, publish: bool) {
    if let Some(s) = search.take() {
        s.publish.store(publish, Ordering::Release);
        s.stop.store(true, Ordering::Release);
        let _ = s.thread.join();
    }
}
fn position(line: &str) -> Result<FourGame, &'static str> {
    let (base, moves) = line
        .strip_prefix("position ")
        .ok_or("missing position")?
        .split_once(" moves ")
        .map_or_else(|| (line.strip_prefix("position ").unwrap(), ""), |v| v);
    let position = if base == "startpos" {
        FourPosition::initial(FourMode::Teams)
    } else {
        FourPosition::from_state(base.strip_prefix("state ").ok_or("use startpos or state")?)?
    };
    if position.mode != FourMode::Teams {
        return Err("this protocol supports Teams only");
    }
    let mut game = FourGame::from_position(position);
    for text in moves.split_whitespace() {
        if game.outcome().is_some() {
            return Err("moves after terminal position");
        }
        if !game.push_notation(text) {
            return Err("illegal four-player move");
        }
    }
    Ok(game)
}
fn limits(
    line: &str,
    p: &FourPosition,
    overhead: u64,
) -> Result<(FourSearchLimits, bool), &'static str> {
    let tokens: Vec<_> = line.split_whitespace().collect();
    let mut time = None;
    let mut depth = 12;
    let mut nodes = None;
    let mut infinite = false;
    let mut clocks = [None; 4];
    let mut increments = [0; 4];
    let mut i = 1;
    while i < tokens.len() {
        let key = tokens[i];
        if key == "infinite" {
            infinite = true;
            i += 1;
            continue;
        }
        let value = tokens
            .get(i + 1)
            .ok_or("missing go value")?
            .parse::<u64>()
            .map_err(|_| "invalid go value")?;
        match key {
            "movetime" if value > 0 => time = Some(value),
            "depth" if (1..=12).contains(&value) => depth = value as u8,
            "nodes" if value > 0 => nodes = Some(value),
            "rtime" => clocks[0] = Some(value),
            "btime" => clocks[1] = Some(value),
            "ytime" => clocks[2] = Some(value),
            "gtime" => clocks[3] = Some(value),
            "rinc" => increments[0] = value,
            "binc" => increments[1] = value,
            "yinc" => increments[2] = value,
            "ginc" => increments[3] = value,
            _ => return Err("unsupported go option"),
        }
        i += 2;
    }
    let ms = if infinite {
        86_400_000
    } else if let Some(t) = time {
        t.saturating_sub(overhead).max(1)
    } else if let Some(clock) = clocks[p.turn.index()] {
        let available = clock.saturating_sub(overhead).max(1);
        (available / 25 + increments[p.turn.index()] / 2).clamp(1, available)
    } else if nodes.is_some() || depth < 12 {
        60_000
    } else {
        1000
    };
    Ok((
        FourSearchLimits {
            movetime: Duration::from_millis(ms.min(86_400_000)),
            depth,
            nodes,
        },
        infinite,
    ))
}

pub fn run() -> io::Result<()> {
    let mut game = FourGame::new(FourMode::Teams);
    let mut active = None;
    let mut overhead = 20;
    let result = (|| {
        for line in io::stdin().lock().lines() {
            let line = line?;
            let line = line.trim();
            match line {
                "uci" => {
                    emit(concat!(
                        "id name Eloi ",
                        env!("CARGO_PKG_VERSION"),
                        " Four-Player Teams"
                    ));
                    emit("id author Sahil Das and Eloi contributors");
                    emit(
                        "option name UCI_Variant type combo default fourplayerteams var fourplayerteams",
                    );
                    emit("option name Threads type spin default 3 min 3 max 3");
                    emit("option name Move Overhead type spin default 20 min 0 max 5000");
                    emit(
                        "info string Eloi extension: from-file/from-rank/to-file/to-rank in hexadecimal 0..d; promotion q/r/b/n",
                    );
                    emit("uciok");
                }
                "isready" => emit("readyok"),
                "stop" => stop(&mut active, true),
                "quit" => break,
                "ucinewgame" => {
                    stop(&mut active, false);
                    game = FourGame::new(FourMode::Teams);
                }
                "d" => emit(&format!("info string {}", game.position().to_state())),
                _ if line.starts_with("position ") => {
                    stop(&mut active, false);
                    match position(line) {
                        Ok(next) => game = next,
                        Err(e) => emit(&format!("info string position rejected: {e}")),
                    }
                }
                _ if line.starts_with("setoption name ") => {
                    stop(&mut active, false);
                    match line
                        .strip_prefix("setoption name ")
                        .unwrap()
                        .split_once(" value ")
                    {
                        Some(("Threads", "3") | ("UCI_Variant", "fourplayerteams")) => {}
                        Some(("Move Overhead", value)) => match value.parse::<u64>() {
                            Ok(ms) if ms <= 5000 => overhead = ms,
                            _ => emit("info string invalid overhead"),
                        },
                        _ => emit("info string unsupported option"),
                    }
                }
                _ if line == "go" || line.starts_with("go ") => {
                    stop(&mut active, false);
                    let (limits, infinite) = match limits(line, game.position(), overhead) {
                        Ok(v) => v,
                        Err(e) => {
                            emit(&format!("info string go rejected: {e}"));
                            continue;
                        }
                    };
                    if let Some(outcome) = game.outcome() {
                        emit(&format!("info string terminal {outcome:?}"));
                        emit("bestmove 0000");
                        continue;
                    }
                    let position = game.position().clone();
                    let signal = Arc::new(AtomicBool::new(false));
                    let stop_signal = Arc::clone(&signal);
                    let publish = Arc::new(AtomicBool::new(true));
                    let output = Arc::clone(&publish);
                    let thread = std::thread::spawn(move || {
                        match search_four_player(&position, limits, &signal) {
                            Ok(r) => {
                                while infinite && !signal.load(Ordering::Acquire) {
                                    std::thread::park_timeout(Duration::from_millis(10));
                                }
                                if output.load(Ordering::Acquire) {
                                    emit(&format!(
                                        "info depth {} score cp {} nodes {} time {} string emergency {}",
                                        r.depth,
                                        r.score,
                                        r.nodes,
                                        r.elapsed.as_millis(),
                                        r.emergency
                                    ));
                                    emit(&format!(
                                        "bestmove {}",
                                        r.best_move
                                            .map_or_else(|| "0000".into(), |mv| mv.notation())
                                    ));
                                }
                            }
                            Err(e) => {
                                if output.load(Ordering::Acquire) {
                                    emit(&format!("info string search failed: {e}"));
                                    emit("bestmove 0000");
                                }
                            }
                        }
                    });
                    active = Some(Search {
                        stop: stop_signal,
                        publish,
                        thread,
                    });
                }
                "" => {}
                _ => emit("info string unknown four-player Teams command"),
            }
        }
        Ok(())
    })();
    stop(&mut active, false);
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn position_replay_and_rejection() {
        let p = FourPosition::initial(FourMode::Teams);
        let mv = p.legal_moves()[0];
        let loaded = position(&format!("position startpos moves {mv}")).unwrap();
        assert_eq!(loaded.position(), &p.play(mv).unwrap());
        assert!(position("position startpos moves xxxx").is_err());
        assert_eq!(
            position(&format!("position state {}", p.to_state()))
                .unwrap()
                .position(),
            &p
        );
    }
    #[test]
    fn clocks_and_bad_limits() {
        let p = FourPosition::initial(FourMode::Teams);
        assert_eq!(
            limits("go movetime 500", &p, 20)
                .unwrap()
                .0
                .movetime
                .as_millis(),
            480
        );
        assert!(limits("go nodes 0", &p, 20).is_err());
        assert!(limits("go depth 13", &p, 20).is_err());
        assert!(
            limits("go rtime 6000 binc 1", &p, 20)
                .unwrap()
                .0
                .movetime
                .as_millis()
                < 6000
        );
    }
}
