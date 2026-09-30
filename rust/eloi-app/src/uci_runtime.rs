//! Cancellable laboratory UCI runtime. Production routing remains unchanged.

use std::io::{self, BufRead, Write};
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
};
use std::thread::JoinHandle;

use eloi_core::{
    Variant,
    game::Game,
    position::{INITIAL_FEN, initial_fen},
};
use eloi_protocol::uci::{SearchRequest, apply_position, parse_search_request};

struct ActiveSearch {
    cancelled: Arc<AtomicBool>,
    publish: Arc<AtomicBool>,
    handle: JoinHandle<()>,
    ponder_resume: Option<(Game, eloi_engine::search::SearchLimits)>,
}

struct UciOptions {
    variant: Variant,
    overhead: u64,
    hash_mb: u16,
    depth: u8,
    noise_millipawns: u16,
    own_book: bool,
}

impl Default for UciOptions {
    fn default() -> Self {
        Self {
            variant: Variant::Standard,
            overhead: 100,
            hash_mb: 32,
            depth: 0,
            noise_millipawns: 0,
            own_book: true,
        }
    }
}

impl UciOptions {
    fn set(&mut self, name: &str, value: &str) {
        match name {
            "Threads" if value == "3" => {}
            "Depth" => match value.parse::<u8>() {
                Ok(value) if value <= 64 => self.depth = value,
                _ => emit("info string invalid depth"),
            },
            "Move Overhead" | "MoveOverhead" => match value.parse::<u64>() {
                Ok(ms) if ms <= 5000 => self.overhead = ms,
                _ => emit("info string invalid overhead"),
            },
            "Hash" => match value.parse::<u16>() {
                Ok(value) if value <= 1024 => self.hash_mb = value,
                _ => emit("info string invalid hash size"),
            },
            "Noise" => match value.parse::<u16>() {
                Ok(value) if value <= 10_000 => self.noise_millipawns = value,
                _ => emit("info string invalid noise"),
            },
            "OwnBook" => match value {
                "true" | "1" => self.own_book = true,
                "false" | "0" => self.own_book = false,
                _ => emit("info string invalid OwnBook flag"),
            },
            "UCI_Chess960" => match value {
                "true" => self.variant = Variant::Chess960,
                "false" => self.variant = Variant::Standard,
                _ => emit("info string invalid Chess960 flag"),
            },
            "UCI_Variant" => self.set_variant(value),
            _ => emit("info string unsupported option or value"),
        }
    }

    fn set_variant(&mut self, value: &str) {
        let key = match value {
            "chess" => "standard",
            "kingofthehill" => "kingOfTheHill",
            other => other,
        };
        if let Some(selected) = eloi_protocol::variant_from_lichess(key) {
            self.variant = selected;
        } else {
            emit("info string unsupported variant");
        }
    }
}

fn stop(active: &mut Option<ActiveSearch>) {
    if let Some(search) = active.take() {
        search.publish.store(true, Ordering::Relaxed);
        search.cancelled.store(true, Ordering::Relaxed);
        let _ = search.handle.join();
    }
}

fn emit(text: &str) {
    let mut output = io::stdout().lock();
    let _ = writeln!(output, "{text}");
    let _ = output.flush();
}

// Donor search, native fallback, ponder publication and telemetry stay together
// so there is one auditable owner for every possible `bestmove` response.
#[allow(clippy::too_many_lines)]
fn dispatch(
    game: Game,
    request: SearchRequest,
    donor: Option<Arc<Mutex<eloi_engine::worker::DonorWorker>>>,
    strict_donor: bool,
) -> ActiveSearch {
    let cancelled = Arc::new(AtomicBool::new(false));
    let signal = Arc::clone(&cancelled);
    let publish = Arc::new(AtomicBool::new(request.ponder_resume.is_none()));
    let publish_result = Arc::clone(&publish);
    let limits = request.limits;
    let resume = request.ponder_resume.map(|limits| (game.clone(), limits));
    let handle = std::thread::spawn(move || {
        let chess960 = game.position().variant == Variant::Chess960;
        if let Some(worker) = donor {
            let reserve = limits.movetime.div_f32(10.0).clamp(
                std::time::Duration::from_millis(15),
                std::time::Duration::from_millis(100),
            );
            let donor_budget = if strict_donor {
                limits.movetime
            } else {
                limits
                    .movetime
                    .saturating_sub(reserve)
                    .max(std::time::Duration::from_millis(1))
            };
            let result = worker
                .lock()
                .map_err(|_| io::Error::other("donor lock poisoned"))
                .and_then(|mut worker| worker.search(&game, donor_budget, &signal));
            match result {
                Ok(result) => {
                    emit(&format!(
                        "info depth {} score cp {} nodes {} time {} pv {}",
                        result.depth,
                        result.score_cp.unwrap_or(0),
                        result.nodes,
                        result.elapsed.as_millis(),
                        result
                            .pv
                            .iter()
                            .map(|mv| mv.uci(false))
                            .collect::<Vec<_>>()
                            .join(" ")
                    ));
                    if publish_result.load(Ordering::Relaxed) {
                        emit(&format!("bestmove {}", result.best_move.uci(false)));
                    }
                }
                Err(error) => {
                    emit(&format!("info string donor failure: {error}"));
                    if strict_donor {
                        if publish_result.load(Ordering::Relaxed) {
                            emit("bestmove 0000");
                        }
                        return;
                    }
                    let mut fallback_limits = limits;
                    fallback_limits.movetime = reserve;
                    fallback_limits.soft_time = Some(reserve.mul_f32(0.8));
                    let fallback =
                        eloi_engine::search::search(&game, fallback_limits, &signal, |_| {});
                    match fallback {
                        Ok(fallback) => {
                            emit(&format!(
                                "info string donor fallback depth {} emergency {}",
                                fallback.depth, fallback.emergency
                            ));
                            if publish_result.load(Ordering::Relaxed) {
                                emit(&format!(
                                    "bestmove {}",
                                    fallback
                                        .best_move
                                        .map_or_else(|| "0000".into(), |mv| mv.uci(chess960),)
                                ));
                            }
                        }
                        Err(fallback_error) => {
                            emit(&format!("info string fallback failure: {fallback_error}"));
                            if publish_result.load(Ordering::Relaxed) {
                                let emergency = game
                                    .position()
                                    .legal_moves()
                                    .into_iter()
                                    .next()
                                    .map_or_else(|| "0000".into(), |mv| mv.uci(chess960));
                                emit(&format!("bestmove {emergency}"));
                            }
                        }
                    }
                }
            }
            return;
        }
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
                if publish_result.load(Ordering::Relaxed) {
                    emit(&format!(
                        "bestmove {}",
                        result
                            .best_move
                            .map_or_else(|| "0000".into(), |mv| mv.uci(chess960))
                    ));
                }
            }
            Err(error) => {
                emit(&format!("info string search failure: {error}"));
                if publish_result.load(Ordering::Relaxed) {
                    emit("bestmove 0000");
                }
            }
        }
    });
    ActiveSearch {
        cancelled,
        publish,
        handle,
        ponder_resume: resume,
    }
}

fn ponderhit(
    active: &mut Option<ActiveSearch>,
    donor: Option<Arc<Mutex<eloi_engine::worker::DonorWorker>>>,
    strict_donor: bool,
) {
    let Some(mut search) = active.take() else {
        emit("info string ponderhit without active ponder");
        return;
    };
    let Some((game, limits)) = search.ponder_resume.take() else {
        emit("info string ponderhit without active ponder");
        *active = Some(search);
        return;
    };
    search.cancelled.store(true, Ordering::Relaxed);
    let _ = search.handle.join();
    *active = Some(dispatch(
        game,
        SearchRequest {
            limits,
            ponder_resume: None,
            infinite: false,
        },
        donor,
        strict_donor,
    ));
}

fn handshake() {
    emit(concat!(
        "id name Eloi Rust Rewrite ",
        env!("CARGO_PKG_VERSION")
    ));
    emit("id author Sahil Das and Eloi contributors");
    emit("option name Threads type spin default 3 min 3 max 3");
    emit("option name Depth type spin default 0 min 0 max 64");
    emit("option name Hash type spin default 32 min 0 max 1024");
    emit("option name Move Overhead type spin default 100 min 0 max 5000");
    emit("option name Noise type spin default 0 min 0 max 10000");
    emit("option name OwnBook type check default true");
    emit(
        "option name UCI_Variant type combo default chess var chess var chess960 var horde var kingofthehill var atomic var antichess var crazyhouse",
    );
    emit("option name UCI_Chess960 type check default false");
    emit("uciok");
}

pub fn run(worker_path: Option<&std::path::Path>, strict_donor: bool) -> io::Result<()> {
    let donor = worker_path
        .map(eloi_engine::worker::DonorWorker::start)
        .transpose()?
        .map(|worker| Arc::new(Mutex::new(worker)));
    let mut game = Game::from_fen(INITIAL_FEN, Variant::Standard).map_err(io::Error::other)?;
    let mut active = None;
    let mut options = UciOptions::default();
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
            "uci" => handshake(),
            "isready" => emit("readyok"),
            "stop" => stop(&mut active),
            "ponderhit" => ponderhit(&mut active, donor.clone(), strict_donor),
            "quit" => {
                stop(&mut active);
                break;
            }
            "ucinewgame" => {
                stop(&mut active);
                let fen = initial_fen(options.variant);
                if let Ok(new_game) = Game::from_fen(fen, options.variant) {
                    game = new_game;
                }
                if let Some(worker) = &donor
                    && let Ok(mut worker) = worker.lock()
                {
                    let _ = worker.new_game();
                }
            }
            _ if line.starts_with("position ") => {
                stop(&mut active);
                if let Err(error) = apply_position(&mut game, line, options.variant) {
                    emit(&format!("info string position rejected: {error}"));
                }
            }
            _ if line.starts_with("setoption name ") => {
                stop(&mut active);
                let Some((name, value)) = line[15..].split_once(" value ") else {
                    emit("info string malformed option");
                    continue;
                };
                options.set(name, value);
            }
            _ if line.starts_with("go") => {
                stop(&mut active);
                let mut request = match parse_search_request(&game, line, options.overhead) {
                    Ok(request) => request,
                    Err(error) => {
                        emit(&format!("info string search rejected: {error}"));
                        continue;
                    }
                };
                request.limits.hash_mb = options.hash_mb;
                request.limits.noise_millipawns = options.noise_millipawns;
                if options.depth != 0 {
                    request.limits.depth = request.limits.depth.min(options.depth);
                }
                if let Some(limits) = &mut request.ponder_resume {
                    limits.hash_mb = options.hash_mb;
                    limits.noise_millipawns = options.noise_millipawns;
                    if options.depth != 0 {
                        limits.depth = limits.depth.min(options.depth);
                    }
                }
                if game.position().variant != options.variant {
                    emit("info string send position after changing variant");
                    continue;
                }
                if options.own_book
                    && request.ponder_resume.is_none()
                    && !request.infinite
                    && let Some(mv) = eloi_engine::book::opening_move(&game)
                {
                    emit("info string stop OpeningBook");
                    emit(&format!("bestmove {}", mv.uci(false)));
                    continue;
                }
                let route = (options.variant == Variant::Standard)
                    .then(|| donor.clone())
                    .flatten();
                active = Some(dispatch(game.clone(), request, route, strict_donor));
            }
            "" => {}
            _ => emit("info string unknown command"),
        }
    }
    stop(&mut active);
    Ok(())
}
