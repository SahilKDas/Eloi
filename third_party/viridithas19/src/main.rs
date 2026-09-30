//! Eloi's contained Viridithas 19.0.1 Standard worker.
// Original source: Cosmo Bobak, MIT. Search and evaluation remain donor-owned.

#[macro_use]
mod macros;
mod bench;
mod chess;
mod cuckoo;
mod errors;
mod evaluation;
mod history;
mod historytable;
mod image;
mod lookups;
mod movepicker;
mod nnue;
mod perft;
mod rng;
mod search;
mod searchinfo;
mod stack;
mod tablebases;
mod term;
mod threadlocal;
mod threadpool;
mod timemgmt;
mod transpositiontable;
mod uci;
mod util;

pub static NAME: &str = "Eloi Viridithas Worker";
pub static VERSION: &str = env!("CARGO_PKG_VERSION");

fn main() -> anyhow::Result<()> {
    anyhow::ensure!(std::env::args().skip(1).eq(["--eloi-worker"]), "internal worker requires --eloi-worker");
    Ok(uci::main_loop()?)
}
