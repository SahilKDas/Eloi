"""Record imported Rust donor files and audit active Windows dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ALLOWED = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib", "CC0-1.0", "Unlicense", "Unicode-3.0"}
COMMIT = "77f4731ea4c319a68fc4bb3317459a3115073820"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--imported", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    commit = subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True).strip()
    if commit != COMMIT:
        raise ValueError("donor source commit mismatch")
    upstream_tracked = set(subprocess.check_output([
        "git", "-C", str(args.upstream), "ls-files",
    ], text=True).splitlines())
    metadata = json.loads(subprocess.check_output([
        "cargo", "metadata", "--manifest-path", str(args.imported / "Cargo.toml"),
        "--format-version", "1", "--locked", "--offline", "--no-default-features",
        "--filter-platform", "x86_64-pc-windows-msvc",
    ], text=True))
    dependencies = []
    for package in sorted(metadata["packages"], key=lambda p: p["name"]):
        license_text = package.get("license") or ""
        # Legacy dual-license slash syntax is equivalent to alternatives.
        identifiers = set(re.findall(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*", license_text)) - {"AND", "OR", "WITH"}
        if not identifiers or not identifiers <= ALLOWED or "WITH" in license_text:
            raise ValueError(f"unapproved dependency license: {package['name']} {license_text}")
        dependencies.append({"name": package["name"], "version": package["version"], "license": license_text})
    imported_files = []
    for path in sorted(args.imported.rglob("*")):
        if not path.is_file() or path.resolve() == args.output.resolve():
            continue
        relative = path.relative_to(args.imported)
        original = args.upstream / relative
        imported_files.append({
            "path": relative.as_posix(),
            "sha256": digest(path),
            "upstream_sha256": digest(original) if relative.as_posix() in upstream_tracked else None,
        })
    report = {
        "schema": 1,
        "tag": "v19.0.1",
        "source_commit": COMMIT,
        "source_archive_sha256": "d82c1c1e1c9567f8985c58d4e04a850a7254bf8737582fe0fff64ccc4ad2d02c",
        "source_license": "MIT",
        "source_license_sha256": "7ee7d175d4d12aed856df5e2db1569c7877c577d31a724becd72fb02141c6df3",
        "network_sha256": "05d552b0ae659938ef0933a06156762a8c94632740fabbbe119611c6439d2319",
        "network_license": "CC0-1.0",
        "network_license_basis": "https://github.com/cosmobobak/viridithas-networks/blob/main/README.md",
        "network_embedded_in_official_release_verified": True,
        "external_c_sources_imported": False,
        "runtime_downloads": False,
        "search_threads": 3,
        "strength_qualified": False,
        "dependencies": dependencies,
        "imported_files": imported_files,
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(f"audited {len(imported_files)} imported files, {len(dependencies)} dependencies")


if __name__ == "__main__":
    main()
