# Eloi's Viridithas 19.0.1 worker

Pinned upstream source commit: `77f4731ea4c319a68fc4bb3317459a3115073820`.
The original MIT notice remains in `LICENSE`. `DONOR_PROVENANCE.json` records
the imported files, original/current hashes and active dependency licenses.

Eloi changes only the deployment boundary at this milestone:

- Renames the package to `eloi-viridithas-worker` and reports the tagged 19.0.1
  version instead of the upstream manifest's unreleased 20.0.0 string.
- Replaces the build script with local-only, hash-verified model embedding.
- Requires the internal `--eloi-worker` entry point; external command-line
  training, quantization and benchmark frontends are disconnected.
- Fixes the worker to exactly three search threads and defaults to 32 MB hash.
- Excludes all external C/tablebase sources and refuses their build features.
- Preserves the donor's search/evaluation coupling without tuning or blending.

The network is supplied locally through `ELOI_VIRIDITHAS_MODEL`, pointing to
the CC0 `noumena-b1200.nnue.zst` artifact. The compressed SHA-256 is
`05d552b0ae659938ef0933a06156762a8c94632740fabbbe119611c6439d2319`.
There is no configure-time or runtime download.

Build with the repository's pinned Rust toolchain:

```powershell
$env:ELOI_VIRIDITHAS_MODEL = 'C:\path\to\noumena-b1200.nnue.zst'
$env:CARGO_BUILD_JOBS = '2'
cargo build --locked --no-default-features --manifest-path third_party/viridithas19/Cargo.toml --target-dir target/viridithas19
```

This worker remains experimental until correctness, adapter parity, resource,
strength and package gates pass. `eloi-engine` owns process cancellation and
validates every move/PV through Eloi's variant-aware board.
