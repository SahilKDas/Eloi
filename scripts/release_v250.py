#!/usr/bin/env python3
"""Preservation-only, bounded v2.5.0 release validation. Never trains or publishes."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import statistics
import struct
import tempfile
import zipfile
import platform
import zlib
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "tmp/release-v2.5.0"
OUTPUT = ROOT / "dist/v2.5.0"
MSYS = Path("C:/msys64/ucrt64/bin")
STARTED = "2026-09-03T04:07:54+00:00"
C_WEIGHTS = "6510D18A63C3AB68C337B5427A03AEF3284080BEA7A400746391688392BB16CD"
OLD_WEIGHTS = "CD3226903D48E0ADFE1DBD337E9CEC7BFB0A22C85185F9B6E0895D873A73394E"
C_BINARY = ROOT / "tmp/nnue-fresh-data/candidates/C/build/Eloi.exe"
C_BINARY_SHA = "E2F7CE21B59D56BEBF1DF00334CC60C6032869648D86D2D3DF834021D046C6EA"
FLAGS = (subprocess.IDLE_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def remaining():
    return 7200 - (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(STARTED)).total_seconds()


def size(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file()) if Path(path).exists() else 0


def quota(total, training, owned, free, projected=0):
    require(total + projected <= 10_000_000_000, "Total temporary quota exceeded")
    require(training <= min(8_000_000_000, 7 * 1024**3), "Training quota exceeded")
    require(owned + projected <= 2_000_000_000, "New release scratch quota exceeded")
    require(free - projected >= 5_000_000_000, "Free-space reserve would be breached")


def resources(projected=0, check_deadline=True):
    roots = [ROOT / p for p in ("tmp", "dist", "pkg", ".deps", "build")]
    roots += list(ROOT.glob("build-*"))
    prior = read(ROOT / "data/abc60_start.json")
    roots += [Path(p) for p in prior["external_temporary_directories_found"]]
    extra = WORK / "external.json"
    external = read(extra) if extra.exists() else []
    roots += [Path(p) for p in external]
    usage = {str(p): size(p) for p in roots}
    training = sum(size(ROOT / p) for p in ("tmp/nnue-fresh-data", ".deps/nnue-inputs", ".deps/nnue-inputs-v2-broader1"))
    own = size(WORK) + size(OUTPUT) + sum(size(p) for p in external)
    free = shutil.disk_usage(ROOT).free
    quota(sum(usage.values()), training, own, free, projected)
    if check_deadline:
        require(remaining() > 0, "Two-hour release deadline reached")
    return {"utc": utc(), "total_bytes": sum(usage.values()), "training_bytes": training,
            "own_bytes": own, "free_bytes": free, "roots": usage}


def new_bytes(path, payload):
    resources(len(payload))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def deterministic_zip(folder, target, epoch):
    require(not Path(target).exists(), "Archive collision")
    paths = sorted(p for p in Path(folder).rglob("*") if p.is_file())
    resources(sum(p.stat().st_size for p in paths))
    stamp = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            require(not path.is_symlink(), "Package symlink rejected")
            item = zipfile.ZipInfo(path.relative_to(folder).as_posix(), date_time=stamp)
            item.create_system = 3
            item.external_attr = 0o100644 << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, path.read_bytes(), compresslevel=9)


def extract_new(archive_path, directory):
    directory = Path(directory)
    require(not directory.exists(), f"Extraction collision: {directory}")
    with zipfile.ZipFile(archive_path) as archive:
        require(len(archive.namelist()) == len(set(archive.namelist())), "Duplicate ZIP entries")
        resources(sum(item.file_size for item in archive.infolist()))
        for item in archive.infolist():
            relative = Path(item.filename)
            require(not relative.is_absolute() and ".." not in relative.parts and ":" not in item.filename,
                    "Unsafe archive member")
            target = directory / relative
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(archive.read(item))


def files(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def copy_tree(source, target):
    for p in sorted(Path(source).rglob("*")):
        if p.is_file():
            copy_new(p, Path(target) / p.relative_to(source))


def pe_zero(path):
    with Path(path).open("rb") as stream:
        require(stream.read(2) == b"MZ", "Not a PE executable")
        stream.seek(0x3c)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        require(stream.read(4) == b"PE\0\0", "Invalid PE signature")
        stream.seek(offset + 8)
        require(struct.unpack("<I", stream.read(4))[0] == 0, "Nonzero PE timestamp")


def package_files_valid(folder, split):
    names = set(files(folder))
    require("Eloi.exe" in names and "config.yml" in names, "Missing main executable/config")
    require((Path(folder) / "config.yml").read_bytes().replace(b"\r\n", b"\n") ==
            (ROOT / "config.example.yml").read_bytes().replace(b"\r\n", b"\n"), "Config template mismatch")
    config = (Path(folder) / "config.yml").read_text()
    require(re.search(r'^\s*token:\s*""\s*$', config, re.M), "Package token must be empty")
    if not split:
        require(names == {"Eloi.exe", "config.yml"}, "Standalone must contain exactly two files")
    else:
        lock = read(ROOT / "reproducibility.lock.json")
        allowed_root = {"Eloi.exe", "EloiLichess.exe", "config.yml", "README.md", "SOURCE_COMMIT.txt", "SHA256SUMS.txt"}
        allowed_root.update(Path(row["path"]).name for row in lock["toolchain_runtime_libraries"])
        require({p for p in names if "/" not in p} == allowed_root, "Unexpected Exoskeleton root entries")
        allowed_assets = {"assets/chess_maestro_bw/" + p.name for p in (ROOT / "assets/chess_maestro_bw").iterdir() if p.is_file()}
        require({p for p in names if p.startswith("assets/")} == allowed_assets, "Unexpected assets")
        require(sum(p.endswith(".png") for p in allowed_assets) == 12, "Expected twelve piece PNGs")
        require(all("/" not in p or p in allowed_assets or p.startswith("licenses/") for p in names), "Unexpected package directory")
        manifest = dict(line.split("  ", 1)[::-1] for line in (Path(folder) / "SHA256SUMS.txt").read_text().splitlines())
        require(manifest == {p: h.lower() for p, h in files(folder).items() if p != "SHA256SUMS.txt"}, "Package hash manifest mismatch")


def stage_package(source, build, target, split, commit):
    target.mkdir(parents=True, exist_ok=False)
    copy_new(build / "Eloi.exe", target / "Eloi.exe")
    copy_new(source / "config.example.yml", target / "config.yml")
    if split:
        copy_new(build / "EloiLichess.exe", target / "EloiLichess.exe")
        copy_new(source / "packaging/WINDOWS-X64-EXOSKELETON.md", target / "README.md")
        copy_tree(source / "assets/chess_maestro_bw", target / "assets/chess_maestro_bw")
        copy_new(source / "LICENSE", target / "licenses/Eloi-MIT.txt")
        for origin, dest in (("C:/msys64/ucrt64/share/licenses/gcc-libs", "gcc-libs"),
                             ("C:/msys64/ucrt64/share/licenses/libwinpthread", "libwinpthread"),
                             (ROOT / ".deps/skia108/ucrt64/share/licenses/skia", "skia")):
            copy_tree(origin, target / "licenses" / dest)
        for name, origin in {"zlib.txt": "zlib-1.3.2/LICENSE", "libjpeg-turbo.md": "libjpeg-turbo-3.2.0/LICENSE.md",
                             "libpng.txt": "libpng-1.6.58/LICENSE", "libwebp.txt": "libwebp-1.6.0/COPYING"}.items():
            copy_new(ROOT / ".deps/static-sources" / origin, target / "licenses" / name)
        for row in read(ROOT / "reproducibility.lock.json")["toolchain_runtime_libraries"]:
            require(sha(row["path"]) == row["sha256"].upper(), "Runtime library changed")
            copy_new(row["path"], target / Path(row["path"]).name)
        new_bytes(target / "SOURCE_COMMIT.txt", (commit + "\n").encode())
        manifest = "".join(f"{digest.lower()}  {name}\n" for name, digest in files(target).items())
        new_bytes(target / "SHA256SUMS.txt", manifest.encode())
    package_files_valid(target, split)


def validate_imports(package, split, label):
    imports = {}
    for name in (["Eloi.exe", "EloiLichess.exe"] if split else ["Eloi.exe"]):
        pe_zero(package / name)
        log = run([MSYS / "objdump.exe", "-p", package / name], label + "-imports-" + name)
        imports[name] = [s.lower() for s in re.findall(r"DLL Name:\s*(\S+)", log)]
    if split:
        require("winhttp.dll" not in imports["Eloi.exe"] and "winhttp.dll" in imports["EloiLichess.exe"], "Networking isolation failed")
        for row in read(ROOT / "reproducibility.lock.json")["toolchain_runtime_libraries"]:
            require(all(Path(row["path"]).name.lower() in found for found in imports.values()), "Missing runtime import")
    else:
        require(all((Path(os.environ["SystemRoot"]) / "System32" / dll).exists() for dll in imports["Eloi.exe"]), "Non-system standalone DLL dependency")
    return imports


def uci_smoke(executable):
    import engine_lab as lab
    engine = lab.chess.engine.SimpleEngine.popen_uci([str(executable), "--uci", "--move-overhead", "0"], timeout=3, creationflags=FLAGS)
    rows = []
    try:
        option = engine.options["Threads"]
        require(option.default == option.min == option.max == 3, "Thread contract changed")
        require("ParallelMode" not in engine.options and "Ponder" not in engine.options, "Unexpected public option")
        lab.configure(engine)
        engine.ping()
        for index in range(3):
            board = lab.chess.Board()
            if index == 1:
                board.push_uci("e2e4")
            before = time.monotonic()
            response = engine.play(board, lab.chess.engine.Limit(time=.25), game=object())
            elapsed = time.monotonic() - before
            require(response.move in board.legal_moves and elapsed <= 2.5, "Illegal or overdue UCI response")
            rows.append({"fen": board.fen(), "move": response.move.uci(), "elapsed_seconds": elapsed})
        with engine.analysis(lab.chess.Board()) as analysis:
            time.sleep(.10)
            before = time.monotonic()
            analysis.stop()
            result = analysis.wait()
            elapsed = time.monotonic() - before
            require(result.move in lab.chess.Board().legal_moves and elapsed <= 2.5, "Stop response failed")
        engine.ping()
    finally:
        engine.quit()
    print(json.dumps({"uci_moves": rows, "stop_seconds": elapsed, "passed": True}))


def diagnostics(executable, label):
    import run_abc60 as assessment
    rows = []
    for case in assessment.epd_cases():
        output = WORK / "diagnostics" / (label + "-" + case["id"] + ".json")
        require(not output.exists(), "Diagnostic collision")
        output.parent.mkdir(exist_ok=True)
        run([executable, "--diagnose-search", "--fen", case["fen"], "--depth", str(case["depth"]),
             "--profile", "production", "--json", output], output.stem, 15)
        trace = read(output)
        require(trace["completed"], "Incomplete fixed-depth diagnostic")
        final = trace["final_result"]
        rows.append({"id": case["id"], "depth": final["depth"], "move": final["selected_move"],
                     "score_cp": final["score_cp"], "pv": final["pv"], "nodes": trace["total_nodes_consumed"]})
    create(WORK / (label + "-diagnostics.json"), rows)
    return rows


def validate_binary(executable, label, split=False):
    output = run([executable, "--version"], label + "-version")
    require(output.strip() == "Eloi 2.5.0", "Wrong stable version")
    output = run([executable, "--perft", "--depth", "4"], label + "-perft", 30)
    require(",4,197281," in output, "Perft mismatch")
    run([sys.executable, "-B", ROOT / "scripts/differential_movegen.py", "--engine", executable,
         "--samples", "32", "--output", WORK / (label + "-differential.json")], label + "-differential", 180)
    run([sys.executable, "-B", __file__, "uci-smoke", "--executable", executable], label + "-uci", 30, cwd=executable.parent)
    run([executable, "--version-match-smoke", C_BINARY], label + "-version-match", 60, cwd=executable.parent)
    for option in ("screenshot", "screenshot-setup", "screenshot-engine-lab"):
        command = [executable, "--" + option, WORK / (label + "-" + option + ".bmp")]
        if option == "screenshot-engine-lab":
            command.append(C_BINARY)
        run(command, label + "-" + option, 30, cwd=executable.parent)
    if split:
        run([executable.parent / "EloiLichess.exe", "--check-config"], label + "-config", cwd=executable.parent)
        output = run([executable, "--lichess"], label + "-redirect", cwd=executable.parent, accepted=(2,))
        require("EloiLichess.exe" in output, "Missing Exoskeleton redirection")
        client = [executable.parent / "EloiLichess.exe"]
    else:
        client = [executable, "--lichess"]
        run([*client, "--check-config", "--config", executable.parent / "config.yml"], label + "-config", cwd=executable.parent)
    fixture = WORK / (label + "-empty-token.yml")
    new_bytes(fixture, (ROOT / "config.example.yml").read_bytes().replace(b"enabled: false", b"enabled: true", 1))
    output = run([*client, "--config", fixture], label + "-empty-token", 15, cwd=executable.parent, accepted=(2,))
    require("token" in output.lower(), "Empty-token guard did not explain failure")


def benchmark(executables, label):
    rows = []
    for depth in (1, 5, 10):
        for repetition in range(3):
            for name, executable in executables.items():
                log = run([executable, "--bench", "--depth", str(depth)], f"{label}-{name}-d{depth}-r{repetition}", 60)
                summary = next(line for line in log.splitlines() if line.startswith("bench summary"))
                tokens = summary.split()[2:]
                values = dict(zip(tokens[::2], map(int, tokens[1::2])))
                rows.append({"name": name, "repetition": repetition, **values})
    summary = {}
    for depth in (1, 5, 10):
        base = [row for row in rows if row["name"] == "C" and row["depth"] == depth]
        baseline = statistics.median(row["time"] for row in base)
        for name in executables:
            sample = [row for row in rows if row["name"] == name and row["depth"] == depth]
            require(all(row["checksum"] == base[0]["checksum"] and row["nodes"] == base[0]["nodes"] for row in sample), "Benchmark behavior diverged")
            median = statistics.median(row["time"] for row in sample)
            summary[f"{name}-d{depth}"] = {"median_ms": median, "ratio_to_C": median / max(1, baseline)}
    create(WORK / (label + ".json"), {"rows": rows, "summary": summary})
    require(all(value["ratio_to_C"] <= 1.15 for key, value in summary.items() if key.endswith(("-d5", "-d10"))), "Unexplained performance regression over 15%; publication blocked")


def build_packages(reproduce_only=False):
    require(not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT), "Clean committed source required")
    require(sha(ROOT / "include/eloi/nnue_weights.hpp") == C_WEIGHTS, "Production header changed")
    if not reproduce_only:
        require(not OUTPUT.exists(), "Stable output directory already exists")
    if not WORK.exists():
        WORK.mkdir(parents=True)
        create(WORK / "start.json", {"started_utc": STARTED, "mode": "reproduce-only" if reproduce_only else "release-validation"})
        create(WORK / "protected.json", {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / "src").iterdir() if p.is_file()})
    resources(1_000_000_000)
    powershell = shutil.which("pwsh")
    require(powershell is not None, "PowerShell 7 (pwsh) is required by the locked build contract")
    run([powershell, "-NoProfile", "-File", ROOT / "scripts/verify-toolchain.ps1", "-RequirePackageArchives"], "locked-toolchain-pwsh", 180)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    lock = read(ROOT / "reproducibility.lock.json")
    archive = WORK / "source.zip"
    require(not archive.exists(), "Source export collision")
    run(["git", "archive", "--format=zip", "--output", archive, commit], "source-export")
    if not reproduce_only:
        require(sha(C_BINARY) == C_BINARY_SHA, "Frozen C reference mismatch")
    reference = diagnostics(C_BINARY, "frozen-C-final") if not reproduce_only else None
    artifacts = {}
    for split in (False, True):
        form = "exoskeleton" if split else "standalone"
        copies = []
        for copy in ("A", "B"):
            label = form + "-" + copy
            root = WORK / label
            source, build, package = root / "source", root / (label + "-build"), root / "package"
            extract_new(archive, source)
            require(sha(source / "include/eloi/nnue_weights.hpp") == C_WEIGHTS, "Exported C header hash changed")
            for path in source.rglob("*"):
                if path.is_file():
                    os.utime(path, (lock["source_date_epoch"], lock["source_date_epoch"]))
            configure(source, build, split=split)
            cache = (build / "CMakeCache.txt").read_text()
            require("ELOI_NNUE_INCLUDE_DIR:PATH=\n" in cache, "Experimental NNUE override is not empty")
            targets = ["Eloi", "eloi_tests", "eloi_gui_tests"] + (["EloiLichess"] if split else [])
            run([MSYS / "cmake.exe", "--build", build, "--target", *targets, "-j", "2"], label + "-build", 600,
                env={"SOURCE_DATE_EPOCH": str(lock["source_date_epoch"]), "TZ": "UTC", "LC_ALL": "C"})
            run([MSYS / "ctest.exe", "--test-dir", build, "--output-on-failure", "--timeout", "120"], label + "-ctest", 240, cwd=build)
            stage_package(source, build, package, split, commit)
            validate_imports(package, split, label)
            zipped = root / f"Eloi-v2.5.0-windows-x64-{form}.zip"
            deterministic_zip(package, zipped, lock["source_date_epoch"])
            copies.append((package, zipped))
        require(files(copies[0][0]) == files(copies[1][0]), f"{form} payload reproducibility failure")
        require(sha(copies[0][1]) == sha(copies[1][1]), f"{form} ZIP reproducibility failure")
        # The packages themselves, not build directories, supply the final smoke binaries.
        external_parent = Path(tempfile.gettempdir()) / ("Eloi-v2.5.0-smoke-" + commit[:12] + "-" + WORK.name)
        external_file = WORK / "external.json"
        if not external_file.exists():
            require(not external_parent.exists(), "External scratch collision")
            create(external_file, [str(external_parent)])
        extracted = external_parent / form
        extract_new(copies[0][1], extracted)
        package_files_valid(extracted, split)
        if not reproduce_only:
            validate_binary(extracted / "Eloi.exe", form + "-extracted", split)
            actual = diagnostics(extracted / "Eloi.exe", form + "-final")
            require(actual == reference, f"{form} changed frozen C search behavior")
        artifacts[form] = {"source_commit": commit, "zip": str(copies[0][1]), "sha256": sha(copies[0][1]),
                           "payload": files(copies[0][0]), "extracted": str(extracted)}
    if not reproduce_only:
        benchmark({"C": C_BINARY, **{name: Path(value["extracted"]) / "Eloi.exe" for name, value in artifacts.items()}}, "final-performance")
    create(WORK / "package-proof.json", {"source_commit": commit, "weights_sha256": C_WEIGHTS,
           "toolchain_lock_sha256": sha(ROOT / "reproducibility.lock.json"), "artifacts": artifacts,
           "resources": resources(), "both_payloads_and_archives_reproducible": True,
           "mode": "reproduce-only" if reproduce_only else "release-validation",
           "archive_environment": {"python": platform.python_version(), "python_executable_sha256": sha(sys.executable),
                                   "zlib": zlib.ZLIB_RUNTIME_VERSION, "epoch": lock["source_date_epoch"], "compresslevel": 9}})
    for name, digest in read(WORK / "protected.json").items():
        require(sha(ROOT / name) == digest, "Protected evidence/source changed: " + name)
    if not reproduce_only:
        for value in artifacts.values():
            copy_new(value["zip"], OUTPUT / Path(value["zip"]).name)
    print("PACKAGES BUILT; DEFENDER AND GUI REVIEW STILL REQUIRED BEFORE PUBLICATION", flush=True)


def create(path, value):
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    # Retain failure/timeout evidence even after the deadline; never launch work.
    resources(len(payload), check_deadline=False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def copy_new(source, target):
    source, target = Path(source), Path(target)
    require(not target.exists(), f"Output already exists: {target}")
    resources(source.stat().st_size)
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    require(sha(source) == sha(target), "Copy hash mismatch")


def run(command, label, timeout=120, cwd=None, accepted=(0,), env=None):
    resources()
    folder = WORK / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / (label + ".log")
    started = time.monotonic()
    environment = os.environ.copy()
    environment.update({"ELOI_KEEP_TEST_ARTIFACTS": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    if env:
        environment.update(env)
    record = {"command": [str(x) for x in command], "started_utc": utc(), "cwd": str(cwd or ROOT)}
    failure = None
    with log.open("xb") as output:
        process = subprocess.Popen(record["command"], cwd=cwd or ROOT, env=environment,
                                   stdout=output, stderr=subprocess.STDOUT, creationflags=FLAGS)
        try:
            end = started + min(timeout, remaining())
            while process.poll() is None:
                if time.monotonic() >= end or remaining() <= 0:
                    raise TimeoutError(f"Timeout: {label}")
                resources()
                time.sleep(1)
        except BaseException as error:
            failure = f"{type(error).__name__}: {error}"
            if process.poll() is None:
                # Only this live, owned child's tree; never image-wide termination.
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, creationflags=FLAGS, timeout=15)
                process.wait(timeout=15)
        record.update(exit_code=process.returncode, elapsed_seconds=time.monotonic() - started,
                      ended_utc=utc(), error=failure, log_sha256=sha(log))
    create(folder / (label + ".json"), record)
    print(json.dumps({"stage": label, **{k: record[k] for k in ("exit_code", "elapsed_seconds", "error")}}), flush=True)
    require(not failure and process.returncode in accepted, f"Failed {label}; inspect {log}")
    return log.read_text(encoding="utf-8", errors="replace")


def configure(source, build, split=False, include=None, app=True):
    build = Path(build)
    command = [MSYS / "cmake.exe", "-S", source, "-B", build, "-G", "Ninja",
               "-DCMAKE_BUILD_TYPE=Release", "-DELOI_BUILD_TESTS=ON",
               "-DCMAKE_CXX_COMPILER=" + str(MSYS / "c++.exe"),
               "-DCMAKE_MAKE_PROGRAM=" + str(MSYS / "ninja.exe"),
               "-DCMAKE_RC_COMPILER=" + str(MSYS / "windres.exe"),
               "-DSKIA_ROOT=" + str(ROOT / ".deps/skia108/ucrt64"),
               "-DELOI_STATIC_ROOT=" + str(ROOT / ".deps/static-runtime"),
               "-DELOI_NNUE_INCLUDE_DIR=" + (str(include) if include else ""),
               "-DELOI_BUILD_APP=" + ("ON" if app else "OFF"),
               "-DELOI_SPLIT_PACKAGE=" + ("ON" if split else "OFF")]
    run([str(x).replace("\\", "/") for x in command], build.name + "-configure")


def prepare():
    require(not WORK.exists(), "Release attempt already initialized")
    resources(1_000_000_000)
    require(sha(C_BINARY) == C_BINARY_SHA, "C binary identity mismatch")
    require(sha(ROOT / "include/eloi/nnue_weights.hpp") == OLD_WEIGHTS, "Production identity mismatch")
    require(sha(ROOT / "tmp/nnue-fresh-data/candidates/C/include/eloi/nnue_weights.hpp") == C_WEIGHTS, "C weights mismatch")
    WORK.mkdir()
    create(WORK / "start.json", {"started_utc": STARTED, "deadline_utc": "2026-09-03T06:07:54+00:00",
           "resources": resources(), "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
           "old_weights": OLD_WEIGHTS, "C_weights": C_WEIGHTS, "C_binary": C_BINARY_SHA})
    copy_new(ROOT / "include/eloi/nnue_weights.hpp", WORK / "old-production/eloi/nnue_weights.hpp")
    copy_new(ROOT / "data/nnue_provenance.json", WORK / "old-production/nnue_provenance.json")
    protected = list((ROOT / "data").glob("abc*.json")) + list((ROOT / "data").glob("abc*.pgn"))
    protected += list((ROOT / "dist/current").glob("*"))
    protected += list((ROOT / "src").glob("*"))
    create(WORK / "protected.json", {str(p.relative_to(ROOT)): sha(p) for p in protected if p.is_file()})
    originals()


def originals():
    for name, include in (("original-C-2", ROOT / "tmp/nnue-fresh-data/candidates/C/include"),
                          ("original-production-2", WORK / "old-production")):
        build = WORK / name
        configure(ROOT, build, include=include, app=False)
        run([MSYS / "cmake.exe", "--build", build, "--target", "eloi_tests", "-j", "2"], name + "-build", 600)
        log = run([build / "eloi_tests.exe"], name + "-tests", 120, cwd=build, accepted=(1,) if name.startswith("original-C") else (0,))
        fails = [s for s in log.splitlines() if s.startswith("FAIL:")]
        expected = ["FAIL: RootSplit: lichess-001XA: best move remains stable across quiescence depths",
                    "FAIL: RootSplit: poisoned-pawn-capture: best move remains stable across quiescence depths"] if name.startswith("original-C") else []
        require(fails == expected, f"Unexpected original failures: {fails}")
    create(WORK / "original-regressions.json", {"C_original_failures_reproduced": True,
           "production_control_passed": True, "fixture_preservation_only_change": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "originals", "resources", "build", "uci-smoke"))
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--work-dir", type=Path, help="New preserved attempt directory under repository tmp")
    parser.add_argument("--reproduce-only", action="store_true", help="Prove package bytes without strength/reference/security qualification or staging")
    args = parser.parse_args()
    if args.work_dir:
        WORK = args.work_dir.resolve()
        require(WORK.is_relative_to((ROOT / "tmp").resolve()), "Scratch must stay below repository tmp")
        require(WORK != (ROOT / "tmp").resolve(), "Scratch must be a dedicated directory")
    if (WORK / "start.json").exists():
        STARTED = read(WORK / "start.json")["started_utc"]
    elif args.action == "build":
        STARTED = utc()
    if args.action == "prepare":
        prepare()
    elif args.action == "originals":
        originals()
    elif args.action == "build":
        build_packages(args.reproduce_only)
    elif args.action == "uci-smoke":
        require(args.executable is not None, "An executable is required")
        uci_smoke(args.executable)
    else:
        print(json.dumps(resources(), indent=2))
