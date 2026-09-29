//! Release build hook for the optional contained donor payload.

use std::path::PathBuf;

fn main() {
    println!("cargo:rustc-check-cfg=cfg(eloi_embedded_donor)");
    println!("cargo:rerun-if-env-changed=ELOI_DONOR_WORKER");
    let Ok(source) = std::env::var("ELOI_DONOR_WORKER") else {
        return;
    };
    let source = PathBuf::from(source);
    println!("cargo:rerun-if-changed={}", source.display());
    let output = PathBuf::from(std::env::var_os("OUT_DIR").expect("OUT_DIR is required"))
        .join("eloi-viridithas-worker.exe");
    std::fs::copy(source, output).expect("could not embed the verified donor worker");
    println!("cargo:rustc-cfg=eloi_embedded_donor");
}
