//! Cancellable laboratory UCI runtime. Production routing remains unchanged.

use std::io::{self, BufRead, Write};
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
use std::thread::JoinHandle;

use eloi_core::{Variant, game::Game, position::INITIAL_FEN};
use eloi_protocol::uci::{apply_position, parse_go};

struct ActiveSearch {
    cancelled: Arc<AtomicBool>,
    handle: JoinHandle<()>,
}

fn stop(active: &mut Option<ActiveSearch>) {
    if let Some(search) = active.take() {
        search.cancelled.store(true, Ordering::Relaxed);
        let _ = search.handle.join();
    }
}

fn emit(text: &str) {
    let mut output = io::stdout().lock();
    let _ = writeln!(output, "{text}");
    let _ = output.flush();
}

fn dispatch(game: Game, limits: eloi_engine::search::SearchLimits) -> ActiveSearch {
    let cancelled = Arc::new(AtomicBool::new(false));
    let signal = Arc::clone(&cancelled);
    let handle = std::thread::spawn(move || {
        let chess960 = game.position().variant == Variant::Chess960;
        let report = |result: &eloi_engine::search::SearchResult| {
            let pv = result
                .pv
                .iter()
                .map(|mv| mv.uci(chess960))
                .collect::<Vec<_>>()
                .join(" ");
            emit(&format!(
                "info depth {} score cp {} nodes {} time {} pv {pv}",
                result.depth,
                result.score,
                result.nodes,
                result.elapsed.as_millis()
            ));
        };
        match eloi_engine::search::search(&game, limits, &signal, report) {
            Ok(result) => {
                report(&result);
                emit(&format!(
                    "info string stop {:?} emergency {}",
                    result.stop_reason, result.emergency
                ));
                emit(&format!(
                    "bestmove {}",
                    result
                        .best_move
                        .map_or_else(|| "0000".into(), |mv| mv.uci(chess960))
                ));
            }
            Err(error) => {
                emit(&format!("info string search failure: {error}"));
                emit("bestmove 0000");
            }
        }
    });
    ActiveSearch { cancelled, handle }
}

pub fn run() -> io::Result<()> {
    let mut game = Game::from_fen(INITIAL_FEN, Variant::Standard).map_err(io::Error::other)?;
    let mut active = None;
    let mut variant = Variant::Standard;
    let mut overhead = 0;
    for input in io::stdin().lock().lines() {
        let line = match input {
            Ok(line) => line,
            Err(error) => {
                stop(&mut active);
                return Err(error);
            }
        };
        let line = line.trim();
        match line {
            "uci" => {
                emit(concat!(
                    "id name Eloi Rust Rewrite ",
                    env!("CARGO_PKG_VERSION")
                ));
                emit("id author Sahil Das and Eloi contributors");
                emit("option name Threads type spin default 3 min 3 max 3");
                emit("option name MoveOverhead type spin default 0 min 0 max 5000");
                emit(
                    "option name UCI_Variant type combo default chess var chess var chess960 var horde var kingofthehill var atomic var antichess var crazyhouse",
                );
                emit("option name UCI_Chess960 type check default false");
                emit("uciok");
            }
            "isready" => emit("readyok"),
            "stop" => stop(&mut active),
            "quit" => {
                stop(&mut active);
                break;
            }
            "ucinewgame" => {
                stop(&mut active);
                if let Ok(new_game) = Game::from_fen(INITIAL_FEN, variant) {
                    game = new_game;
                }
            }
            _ if line.starts_with("position ") => {
                stop(&mut active);
                if let Err(error) = apply_position(&mut game, line, variant) {
                    emit(&format!("info string position rejected: {error}"));
                }
            }
            _ if line.starts_with("setoption name ") => {
                stop(&mut active);
                let Some((name, value)) = line[15..].split_once(" value ") else {
                    emit("info string malformed option");
                    continue;
                };
                match name {
                    "Threads" if value == "3" => {}
                    "MoveOverhead" => match value.parse::<u64>() {
                        Ok(ms) if ms <= 5000 => overhead = ms,
                        _ => emit("info string invalid overhead"),
                    },
                    "UCI_Chess960" => match value {
                        "true" => variant = Variant::Chess960,
                        "false" => variant = Variant::Standard,
                        _ => emit("info string invalid Chess960 flag"),
                    },
                    "UCI_Variant" => {
                        let key = match value {
                            "chess" => "standard",
                            "kingofthehill" => "kingOfTheHill",
                            other => other,
                        };
                        if let Some(selected) = eloi_protocol::variant_from_lichess(key) {
                            variant = selected;
                        } else {
                            emit("info string unsupported variant");
                        }
                    }
                    _ => emit("info string unsupported option or value"),
                }
            }
            _ if line.starts_with("go") => {
                stop(&mut active);
                let limits = match parse_go(line, overhead) {
                    Ok(limits) => limits,
                    Err(error) => {
                        emit(&format!("info string search rejected: {error}"));
                        continue;
                    }
                };
                if game.position().variant != variant {
                    emit("info string send position after changing variant");
                    continue;
                }
                active = Some(dispatch(game.clone(), limits));
            }
            "" => {}
            _ => emit("info string unknown command"),
        }
    }
    stop(&mut active);
    Ok(())
}
