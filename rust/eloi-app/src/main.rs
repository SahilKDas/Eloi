//! Temporary executable shell for the staged Rust rewrite.

use std::io::{self, BufRead};

const VERSION: &str = env!("CARGO_PKG_VERSION");

fn uci() -> io::Result<()> {
    println!("id name Eloi Rust Rewrite {VERSION}");
    println!("id author Sahil Das and Eloi contributors");
    println!("option name Threads type spin default 3 min 3 max 3");
    println!("uciok");
    for line in io::stdin().lock().lines() {
        match line?.trim() {
            "isready" => println!("readyok"),
            "uci" => println!("uciok"),
            "quit" => break,
            _ => println!("info string Rust rewrite shell: search not migrated"),
        }
    }
    Ok(())
}

fn main() -> io::Result<()> {
    match std::env::args().nth(1).as_deref() {
        Some("--version" | "-v") => println!("Eloi Rust Rewrite {VERSION}"),
        Some("--uci") => uci()?,
        _ => println!("Eloi Rust Rewrite {VERSION}: staged migration build"),
    }
    Ok(())
}
