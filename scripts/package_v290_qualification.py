#!/usr/bin/env python3
"""Build and reproducibility-check preserved Eloi v2.9.0 hybrid packages.

This is a qualification helper, not a publisher.  It exports one clean commit,
performs two independent builds of each Windows package form, embeds only the
hash-pinned Caissa v1.25 network, and refuses every output collision.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib

import caissa_license_gate
import release_v250 as base
import validation_support


ROOT = Path(__file__).resolve().parents[1]
MSYS = Path("C:/msys64/ucrt64/bin")
VERSION = "2.9.0"
NETWORK = ROOT / ".deps/caissa/eval-71-v1.25.pnn"
NETWORK_SHA256 = "615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B"
LICENSE_MANIFEST = ROOT / "third_party/caissa/caissa-network-license-v1.25.json"
FLAGS = (subprocess.IDLE_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def file_map(folder: Path) -> dict[str, str]:
    return {
        path.relative_to(folder).as_posix(): sha256(path)
        for path in sorted(Path(folder).rglob("*")) if path.is_file()
    }


def write_new(path: Path, value) -> None:
    payload = value if isinstance(value, bytes) else (
        json.dumps(value, indent=2, sort_keys=True) + "\n"
    ).encode()
    resource_guard(len(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def copy_new(source: Path, target: Path) -> None:
    require(not target.exists(), f"output collision: {target}")
    resource_guard(Path(source).stat().st_size)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    require(sha256(source) == sha256(target), f"copy hash mismatch: {target}")


def copy_release_output(source: Path, target: Path) -> None:
    """Copy a verified archive to dist without charging it to scratch."""
    require(not target.exists(), f"output collision: {target}")
    snapshot = validation_support.resource_snapshot(WORK, 0)
    amount = Path(source).stat().st_size
    require(snapshot["total_bytes"] + amount <= 10_000_000_000,
            "release copy would exceed total temporary quota")
    require(snapshot["free_bytes"] - amount >= 5_000_000_000,
            "release copy would breach free-space reserve")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    require(sha256(source) == sha256(target), f"release copy hash mismatch: {target}")


def resource_guard(projected: int = 0, check_deadline: bool = True):
    snapshot = validation_support.resource_snapshot(WORK, projected)
    if check_deadline:
        require(time.monotonic() < DEADLINE, "qualification package deadline reached")
    return snapshot


def run(command, label: str, timeout: int = 180, cwd: Path | None = None,
        accepted=(0,), env=None) -> str:
    resource_guard()
    logs = WORK / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{label}.log"
    require(not log.exists(), f"log collision: {log}")
    environment = os.environ.copy()
    environment.update({"ELOI_KEEP_TEST_ARTIFACTS": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    if env:
        environment.update(env)
    started = time.monotonic()
    record = {"command": [str(item) for item in command], "cwd": str(cwd or ROOT),
              "started_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    failure = None
    with log.open("xb") as output:
        process = subprocess.Popen(record["command"], cwd=cwd or ROOT, env=environment,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=FLAGS)
        try:
            end = min(started + timeout, DEADLINE)
            while process.poll() is None:
                if time.monotonic() >= end:
                    raise TimeoutError(label)
                resource_guard(check_deadline=False)
                time.sleep(1)
        except BaseException as error:
            failure = f"{type(error).__name__}: {error}"
            if process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, creationflags=FLAGS, timeout=15)
                process.wait(timeout=15)
    record.update(exit_code=process.returncode, elapsed_seconds=time.monotonic() - started,
                  error=failure, ended_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  log_sha256=sha256(log))
    write_new(logs / f"{label}.json", record)
    print(json.dumps({"stage": label, "exit_code": process.returncode,
                      "elapsed_seconds": record["elapsed_seconds"], "error": failure}), flush=True)
    require(failure is None and process.returncode in accepted,
            f"failed {label}; inspect {log}")
    return log.read_text(encoding="utf-8", errors="replace")


def configure(source: Path, build: Path, split: bool, label: str) -> None:
    command = [MSYS / "cmake.exe", "-S", source, "-B", build, "-G", "Ninja",
               "-DCMAKE_BUILD_TYPE=Release", "-DELOI_BUILD_TESTS=ON",
               "-DCMAKE_CXX_COMPILER=" + str(MSYS / "c++.exe"),
               "-DCMAKE_MAKE_PROGRAM=" + str(MSYS / "ninja.exe"),
               "-DCMAKE_RC_COMPILER=" + str(MSYS / "windres.exe"),
               "-DSKIA_ROOT=" + str(ROOT / ".deps/skia108/ucrt64"),
               "-DELOI_STATIC_ROOT=" + str(ROOT / ".deps/static-runtime"),
               "-DELOI_NNUE_INCLUDE_DIR=", "-DELOI_BUILD_APP=ON",
               "-DELOI_SPLIT_PACKAGE=" + ("ON" if split else "OFF"),
               "-DELOI_ENABLE_CAISSA_PRODUCTION=ON",
               "-DELOI_EMBED_CAISSA_NETWORK=ON",
               "-DELOI_CAISSA_NETWORK_FILE=" + str(NETWORK)]
    run([str(item).replace("\\", "/") for item in command], label + "-configure")
    cache = (build / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace")
    require("ELOI_ENABLE_CAISSA_PRODUCTION:BOOL=ON" in cache, "hybrid production flag missing")
    require("ELOI_EMBED_CAISSA_NETWORK:BOOL=ON" in cache, "embedded network flag missing")
    require("ELOI_NNUE_INCLUDE_DIR:PATH=\n" in cache, "experimental Eloi NNUE override is nonempty")


def copy_tree(source: Path, target: Path) -> None:
    for path in sorted(Path(source).rglob("*")):
        if path.is_file():
            copy_new(path, target / path.relative_to(source))


def validate_package(folder: Path, split: bool, commit: str) -> None:
    names = set(file_map(folder))
    require((folder / "config.yml").read_bytes().replace(b"\r\n", b"\n") ==
            (ROOT / "config.example.yml").read_bytes().replace(b"\r\n", b"\n"),
            "config template mismatch")
    config = (folder / "config.yml").read_text(encoding="utf-8")
    require(re.search(r'^\s*token:\s*""\s*$', config, re.M) is not None,
            "package token is not empty")
    if not split:
        require(names == {"Eloi.exe", "config.yml", "LICENSE.txt"},
                "standalone package contents differ from the v2.9 contract")
    else:
        roots = {name for name in names if "/" not in name}
        runtime = {Path(row["path"]).name for row in base.read(ROOT / "reproducibility.lock.json")["toolchain_runtime_libraries"]}
        require(roots == {"Eloi.exe", "EloiLichess.exe", "config.yml", "README.md",
                          "SOURCE_COMMIT.txt", "SHA256SUMS.txt", *runtime},
                "unexpected Exoskeleton root entries")
        require((folder / "SOURCE_COMMIT.txt").read_text().strip() == commit,
                "source commit marker mismatch")
        require("licenses/Caissa-MIT.txt" in names and "licenses/Eloi-MIT.txt" in names,
                "Caissa/Eloi notices are absent")
        require(sum(name.endswith(".png") for name in names) == 12,
                "expected twelve piece PNGs")
        manifest = dict(line.split("  ", 1)[::-1]
                        for line in (folder / "SHA256SUMS.txt").read_text().splitlines())
        require(manifest == {name: digest.lower() for name, digest in file_map(folder).items()
                             if name != "SHA256SUMS.txt"}, "package manifest mismatch")


def stage(source: Path, build: Path, target: Path, split: bool, commit: str) -> None:
    target.mkdir(parents=True, exist_ok=False)
    copy_new(build / "Eloi.exe", target / "Eloi.exe")
    copy_new(source / "config.example.yml", target / "config.yml")
    if not split:
        copy_new(source / "LICENSE", target / "LICENSE.txt")
    else:
        copy_new(build / "EloiLichess.exe", target / "EloiLichess.exe")
        copy_new(source / "packaging/WINDOWS-X64-EXOSKELETON.md", target / "README.md")
        copy_tree(source / "assets/chess_maestro_bw", target / "assets/chess_maestro_bw")
        copy_new(source / "LICENSE", target / "licenses/Eloi-MIT.txt")
        copy_new(source / "third_party/caissa/LICENSE", target / "licenses/Caissa-MIT.txt")
        for origin, destination in ((Path("C:/msys64/ucrt64/share/licenses/gcc-libs"), "gcc-libs"),
                                    (Path("C:/msys64/ucrt64/share/licenses/libwinpthread"), "libwinpthread"),
                                    (ROOT / ".deps/skia108/ucrt64/share/licenses/skia", "skia")):
            copy_tree(origin, target / "licenses" / destination)
        for name, origin in {"zlib.txt": "zlib-1.3.2/LICENSE",
                             "libjpeg-turbo.md": "libjpeg-turbo-3.2.0/LICENSE.md",
                             "libpng.txt": "libpng-1.6.58/LICENSE",
                             "libwebp.txt": "libwebp-1.6.0/COPYING"}.items():
            copy_new(ROOT / ".deps/static-sources" / origin, target / "licenses" / name)
        for row in base.read(ROOT / "reproducibility.lock.json")["toolchain_runtime_libraries"]:
            origin = Path(row["path"])
            require(sha256(origin) == row["sha256"].upper(), "runtime library hash changed")
            copy_new(origin, target / origin.name)
        write_new(target / "SOURCE_COMMIT.txt", (commit + "\n").encode())
        manifest = "".join(f"{digest.lower()}  {name}\n" for name, digest in file_map(target).items())
        write_new(target / "SHA256SUMS.txt", manifest.encode())
    validate_package(target, split, commit)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--hours", type=float, default=2.0)
    parser.add_argument("--resume-after-standalone", action="store_true")
    parser.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    global WORK, OUTPUT, DEADLINE
    WORK, OUTPUT = args.scratch.resolve(), args.output.resolve()
    DEADLINE = time.monotonic() + args.hours * 3600
    require(WORK != (ROOT / "tmp").resolve() and WORK.is_relative_to((ROOT / "tmp").resolve()),
            "scratch must be a dedicated child of repository tmp")
    require(OUTPUT != (ROOT / "dist").resolve() and OUTPUT.is_relative_to((ROOT / "dist").resolve()),
            "output must be a dedicated child of repository dist")
    require(OUTPUT.is_dir() if args.finalize_existing else not OUTPUT.exists(),
            "output collision or finalize destination absent")
    require(WORK.is_dir() if (args.resume_after_standalone or args.finalize_existing) else not WORK.exists(),
            "resume scratch is absent or new scratch collides")
    require(not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT),
            "clean committed source required")
    require(sha256(NETWORK) == NETWORK_SHA256, "Caissa v1.25 network identity mismatch")
    permissions = {mode: caissa_license_gate.verify_gate(LICENSE_MANIFEST, NETWORK, mode)
                   for mode in ("standalone", "exoskeleton")}
    if args.finalize_existing:
        require(args.source_commit and re.fullmatch(r"[0-9a-f]{40}", args.source_commit),
                "finalization requires the exact package source commit")
        require(not any(OUTPUT.iterdir()), "finalize destination is not empty")
        artifacts = {}
        for form in ("standalone", "exoskeleton"):
            pairs = [(WORK / f"{form}-{copy}" / "package",
                      WORK / f"{form}-{copy}" / f"Eloi-v{VERSION}-windows-x64-{form}.zip")
                     for copy in ("A", "B")]
            require(file_map(pairs[0][0]) == file_map(pairs[1][0]), f"{form} payload mismatch")
            require(sha256(pairs[0][1]) == sha256(pairs[1][1]), f"{form} archive mismatch")
            validate_package(WORK / "fresh-extraction" / form,
                             form == "exoskeleton", args.source_commit)
            worker = json.loads((WORK / (f"{form}-worker.json" if form == "exoskeleton"
                                          else "standalone-worker-resume.json")).read_text())
            require(worker.get("passed") is True, f"{form} worker proof did not pass")
            target = OUTPUT / pairs[0][1].name
            copy_release_output(pairs[0][1], target)
            artifacts[form] = {"zip_sha256": sha256(target), "final_path": str(target),
                               "payload": file_map(pairs[0][0]),
                               "source_commit": args.source_commit}
        report = {"schema": "eloi-v2.9.0-package-qualification-v1", "status": "passed",
                  "source_commit": args.source_commit, "network_sha256": NETWORK_SHA256,
                  "artifacts": artifacts, "resources": resource_guard(check_deadline=False),
                  "resumed_after_preserved_failures": True}
        write_new(WORK / "package-proof.json", report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    resource_guard(900_000_000 if args.resume_after_standalone else 1_600_000_000)
    if not args.resume_after_standalone:
        WORK.mkdir(parents=True)
        write_new(WORK / "start.json", {"version": VERSION, "network_sha256": NETWORK_SHA256,
                  "permissions": permissions, "resources": resource_guard(check_deadline=False)})
    base.ROOT, base.WORK, base.STARTED = ROOT, WORK, dt.datetime.now(dt.timezone.utc).isoformat()
    base.resources, base.run, base.create = resource_guard, run, write_new
    base.new_bytes, base.copy_new = write_new, copy_new
    powershell = shutil.which("pwsh")
    require(powershell is not None, "PowerShell 7 is required")
    if not args.resume_after_standalone:
        run([powershell, "-NoProfile", "-File", ROOT / "scripts/verify-toolchain.ps1",
             "-RequirePackageArchives"], "locked-toolchain", 180)
    commit = (args.source_commit or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
    require(not args.resume_after_standalone or bool(re.fullmatch(r"[0-9a-f]{40}", commit)),
            "resume requires the exact prior source commit")
    lock = base.read(ROOT / "reproducibility.lock.json")
    archive = WORK / "source.zip"
    if not args.resume_after_standalone:
        run(["git", "archive", "--format=zip", "--output", archive, commit], "source-export")
    else:
        require(archive.is_file(), "preserved source archive is absent")
    artifacts = {}
    if args.resume_after_standalone:
        prior = [(WORK / f"standalone-{copy}" / "package",
                  WORK / f"standalone-{copy}" / f"Eloi-v{VERSION}-windows-x64-standalone.zip")
                 for copy in ("A", "B")]
        require(file_map(prior[0][0]) == file_map(prior[1][0]), "preserved standalone payload mismatch")
        require(sha256(prior[0][1]) == sha256(prior[1][1]), "preserved standalone archive mismatch")
        extracted = WORK / "fresh-extraction/standalone"
        validate_package(extracted, False, commit)
        run([sys.executable, "-B", ROOT / "scripts/validate_caissa_worker.py",
             "--engine", extracted / "Eloi.exe", "--output", WORK / "standalone-worker-resume.json"],
            "standalone-worker-resume", 60, cwd=extracted)
        artifacts["standalone"] = {"zip_sha256": sha256(prior[0][1]),
                                   "payload": file_map(prior[0][0]),
                                   "source_commit": commit, "source_zip": str(prior[0][1])}
    for split in ((True,) if args.resume_after_standalone else (False, True)):
        form = "exoskeleton" if split else "standalone"
        copies = []
        for copy in ("A", "B"):
            label = f"{form}-{copy}"
            root = WORK / label
            source, build, package = root / "source", root / "build", root / "package"
            base.extract_new(archive, source)
            for path in source.rglob("*"):
                if path.is_file():
                    os.utime(path, (lock["source_date_epoch"], lock["source_date_epoch"]))
            configure(source, build, split, label)
            targets = ["Eloi", "eloi_tests", "eloi_hybrid_tests", "eloi_gui_tests"] + (["EloiLichess"] if split else [])
            run([MSYS / "cmake.exe", "--build", build, "--target", *targets, "-j", "2"],
                label + "-build", 900,
                env={"SOURCE_DATE_EPOCH": str(lock["source_date_epoch"]), "TZ": "UTC", "LC_ALL": "C"})
            run([MSYS / "ctest.exe", "--test-dir", build, "--output-on-failure", "--timeout", "120"],
                label + "-ctest", 300, cwd=build)
            stage(source, build, package, split, commit)
            base.validate_imports(package, split, label)
            archive_path = root / f"Eloi-v{VERSION}-windows-x64-{form}.zip"
            base.deterministic_zip(package, archive_path, lock["source_date_epoch"])
            copies.append((package, archive_path))
        require(file_map(copies[0][0]) == file_map(copies[1][0]), f"{form} payload mismatch")
        require(sha256(copies[0][1]) == sha256(copies[1][1]), f"{form} archive mismatch")
        extracted = WORK / "fresh-extraction" / form
        base.extract_new(copies[0][1], extracted)
        validate_package(extracted, split, commit)
        base.pe_zero(extracted / "Eloi.exe")
        if split:
            base.pe_zero(extracted / "EloiLichess.exe")
        version = run([extracted / "Eloi.exe", "--version"], form + "-version", 20,
                      cwd=extracted).strip()
        require(version == f"Eloi {VERSION}", f"wrong packaged version: {version}")
        perft = run([extracted / "Eloi.exe", "--perft", "--depth", "4"], form + "-perft", 40,
                    cwd=extracted)
        require(",4,197281," in perft, "packaged perft mismatch")
        run([sys.executable, "-B", ROOT / "scripts/validate_caissa_worker.py",
             "--engine", extracted / "Eloi.exe", "--output", WORK / f"{form}-worker.json"],
            form + "-worker", 60, cwd=extracted)
        artifacts[form] = {"zip_sha256": sha256(copies[0][1]),
                           "payload": file_map(copies[0][0]), "source_commit": commit,
                           "source_zip": str(copies[0][1])}
    OUTPUT.mkdir(parents=True, exist_ok=False)
    for form, artifact in artifacts.items():
        origin = Path(artifact["source_zip"])
        target = OUTPUT / origin.name
        copy_release_output(origin, target)
        artifact["final_path"] = str(target)
    report = {"schema": "eloi-v2.9.0-package-qualification-v1", "status": "passed",
              "source_commit": commit, "network_sha256": NETWORK_SHA256,
              "artifacts": artifacts, "resources": resource_guard(check_deadline=False),
              "archive_environment": {"python": platform.python_version(),
                 "python_executable_sha256": sha256(Path(sys.executable)),
                 "zlib": zlib.ZLIB_RUNTIME_VERSION,
                 "source_date_epoch": lock["source_date_epoch"], "compression_level": 9}}
    write_new(WORK / "package-proof.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
