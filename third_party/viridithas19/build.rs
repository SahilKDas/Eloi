// Eloi's preservation-safe, offline-only donor build contract.
use sha2::{Digest, Sha256};

fn main() {
    for feature in ["SYZYGY", "BINDGEN", "DATAGEN", "STATS", "ZSTD", "FINAL_RELEASE", "TUNING"] {
        assert!(std::env::var_os(format!("CARGO_FEATURE_{feature}")).is_none(), "unsupported donor feature: {feature}");
    }
    println!("cargo:rerun-if-env-changed=ELOI_VIRIDITHAS_MODEL");
    let path = std::env::var_os("ELOI_VIRIDITHAS_MODEL").expect("set ELOI_VIRIDITHAS_MODEL to the pinned local CC0 noumena model; downloads are prohibited");
    let path = std::fs::canonicalize(path).expect("local donor network must exist");
    let bytes = std::fs::read(&path).expect("read local model");
    assert_eq!(format!("{:x}", Sha256::digest(&bytes)), "05d552b0ae659938ef0933a06156762a8c94632740fabbbe119611c6439d2319", "donor model hash mismatch");
    println!("cargo:rerun-if-changed={}", path.display());
    println!("cargo:rustc-env=ELOI_VIRIDITHAS_MODEL={}", path.display());
}
