//! Temporary executable shell for the staged Rust rewrite.

use std::io;

mod uci_runtime;

use eloi_core::Variant;
use eloi_core::position::{INITIAL_FEN, Position};

const VERSION: &str = env!("CARGO_PKG_VERSION");

fn main() -> io::Result<()> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("--version" | "-v") => println!("Eloi Rust Rewrite {VERSION}"),
        Some("--uci") => uci_runtime::run()?,
        Some("--perft") => perft(&args)?,
        Some("--donor-probe") => donor_probe(&args)?,
        Some("--nnue") => nnue_probe(&args)?,
        Some("--check-config") => check_config(&args)?,
        _ => println!("Eloi Rust Rewrite {VERSION}: staged migration build"),
    }
    Ok(())
}

fn check_config(args: &[String]) -> io::Result<()> {
    use std::io::Read;
    let path = args
        .iter()
        .position(|arg| arg == "--config")
        .and_then(|index| args.get(index + 1))
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "explicit --config path required",
            )
        })?;
    let mut text = String::new();
    std::fs::File::open(path)?
        .take(65_537)
        .read_to_string(&mut text)?;
    let config = eloi_protocol::config::parse(&text).map_err(io::Error::other)?;
    println!(
        "config valid: {} supported variants; credentials withheld; no connection started",
        config.variants.len()
    );
    Ok(())
}

fn nnue_probe(args: &[String]) -> io::Result<()> {
    let value = |key: &str| {
        args.iter()
            .position(|a| a == key)
            .and_then(|i| args.get(i + 1))
    };
    let variant =
        eloi_protocol::variant_from_lichess(value("--variant").map_or("standard", String::as_str))
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "unsupported variant"))?;
    let position = Position::from_fen(value("--fen").map_or(INITIAL_FEN, String::as_str), variant)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
    let state = eloi_engine::nnue::NnueState::refresh(&position).map_err(io::Error::other)?;
    println!(
        "{}",
        state.evaluate(position.turn).map_err(io::Error::other)?
    );
    Ok(())
}

fn donor_probe(args: &[String]) -> io::Result<()> {
    let value = |key: &str| {
        args.iter()
            .position(|a| a == key)
            .and_then(|i| args.get(i + 1))
    };
    let invalid = |message| io::Error::new(io::ErrorKind::InvalidInput, message);
    let path =
        value("--worker").ok_or_else(|| invalid("explicit source-built --worker path required"))?;
    let budget: u64 = value("--budget")
        .map_or("250", String::as_str)
        .parse()
        .map_err(|_| invalid("invalid budget"))?;
    let fen = value("--fen").map_or(INITIAL_FEN, String::as_str);
    let game = eloi_core::game::Game::from_fen(fen, Variant::Standard)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
    let mut worker = eloi_engine::worker::DonorWorker::start(std::path::Path::new(path))?;
    let result = worker.search(
        &game,
        std::time::Duration::from_millis(budget),
        &std::sync::atomic::AtomicBool::new(false),
    )?;
    println!(
        "donor-probe move={} depth={} cp={:?} mate={:?} nodes={} elapsed_ms={} model={}",
        result.best_move.uci(false),
        result.depth,
        result.score_cp,
        result.mate,
        result.nodes,
        result.elapsed.as_millis(),
        eloi_engine::worker::NETWORK_SHA256
    );
    Ok(())
}

fn perft(args: &[String]) -> io::Result<()> {
    let value = |key: &str| {
        args.iter()
            .position(|a| a == key)
            .and_then(|i| args.get(i + 1))
    };
    let invalid = |message| io::Error::new(io::ErrorKind::InvalidInput, message);
    let depth: u8 = value("--depth")
        .map_or("1", String::as_str)
        .parse()
        .map_err(|_| invalid("invalid depth"))?;
    if depth > 6 {
        return Err(invalid("unbounded perft depth refused; maximum is six"));
    }
    let fen = value("--fen").map_or(INITIAL_FEN, String::as_str);
    let key = value("--variant").map_or("standard", String::as_str);
    let mut variant =
        eloi_protocol::variant_from_lichess(key).ok_or_else(|| invalid("unsupported variant"))?;
    if variant == Variant::Standard
        && fen
            .split_whitespace()
            .nth(2)
            .is_some_and(|rights| rights.chars().any(|c| matches!(c, 'A'..='H' | 'a'..='h')))
    {
        variant = Variant::Chess960;
    }
    let board = Position::from_fen(fen, variant)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
    let total = if args.iter().any(|a| a == "--divide") && depth != 0 {
        let mut total = 0;
        for mv in board.legal_moves() {
            let child = board
                .play(mv)
                .ok_or_else(|| invalid("generated move was rejected"))?;
            let nodes = child.perft(depth - 1);
            println!("{}: {nodes}", mv.uci(variant == Variant::Chess960));
            total += nodes;
        }
        total
    } else {
        board.perft(depth)
    };
    println!("perft,depth={depth},nodes={total}");
    Ok(())
}
