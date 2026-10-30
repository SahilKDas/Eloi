"""One-shot, fail-closed v4.0.1 publication gate; no local bridge interaction."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
import tempfile
import time

TARGET = dt.datetime(2026, 10, 30, 5, 0, tzinfo=dt.timezone.utc)
TAG = "v4.0.1"
REPO = "SahilKDas/Eloi"
NAMES = {f"Eloi-{TAG}-windows-x64-{kind}.zip" for kind in ("standalone", "exoskeleton")}
GATES = {"rust", "python", "observer_parity", "legal_pv", "uci_teams",
         "gui", "timing", "reproducibility", "contents", "defender"}
MARKER = r"<!-- eloi-v401-gate: (\{[^\n]+\}) -->"


def validate_release(release: dict, commit: str) -> dict:
    """Require a complete, exact-source proof and exactly two golden assets."""
    if release.get("tag_name") != TAG or release.get("name") != "Eloi v4.0.1":
        raise ValueError("Unexpected release identity")
    if release.get("draft") is not True or release.get("prerelease") is not False:
        raise ValueError("Release must still be a stable draft")
    match = re.search(MARKER, release.get("body") or "")
    if not match:
        raise ValueError("Missing completed validation proof")
    proof = json.loads(match.group(1))
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or proof.get("source_commit") != commit:
        raise ValueError("Validation proof does not match the tagged source")
    if proof.get("publish_at") != TARGET.isoformat():
        raise ValueError("Wrong publication instant")
    if set(proof.get("gates", {})) != GATES or not all(
        value is True for value in proof["gates"].values()
    ):
        raise ValueError("A required validation gate has not passed")
    assets = release.get("assets", [])
    if len(assets) != 2 or {a.get("name") for a in assets} != NAMES:
        raise ValueError("Expected exactly the standalone and Exoskeleton ZIPs")
    if set(proof.get("sha256", {})) != NAMES:
        raise ValueError("Missing golden hashes")
    for asset in assets:
        expected = proof["sha256"][asset["name"]]
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise ValueError("Malformed golden hash")
        if asset.get("state") != "uploaded" or asset.get("size", 0) <= 0:
            raise ValueError("Asset upload incomplete")
        if asset.get("digest", "").lower() != "sha256:" + expected.lower():
            raise ValueError("GitHub asset digest differs from the qualified ZIP")
    return proof


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True,
                          text=True, timeout=120).stdout


def fetch_release() -> dict:
    # GitHub's release-by-tag endpoint hides unpublished drafts. Authenticated
    # release listing includes drafts and remains valid after publication.
    pages = json.loads(gh("api", f"repos/{REPO}/releases?per_page=100", "--paginate", "--slurp"))
    matches = [release for page in pages for release in page if release.get("tag_name") == TAG]
    if len(matches) != 1:
        raise ValueError("Expected exactly one matching draft/published release")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    if dt.datetime.now(dt.timezone.utc) >= TARGET:
        raise SystemExit("Missed pre-deadline setup; refusing late/backdated publication")
    release = fetch_release()
    proof = validate_release(release, args.commit)
    snapshot = [(a["id"], a["name"], a["digest"], a["updated_at"]) for a in release["assets"]]
    with tempfile.TemporaryDirectory(prefix="eloi-v401-verify-") as folder:
        gh("release", "download", TAG, "--repo", REPO, "--dir", folder, "--pattern", "*.zip")
        for name, expected in proof["sha256"].items():
            actual = hashlib.sha256((pathlib.Path(folder) / name).read_bytes()).hexdigest()
            if actual != expected.lower():
                raise SystemExit(f"Downloaded asset hash mismatch: {name}")
    if dt.datetime.now(dt.timezone.utc) >= TARGET:
        raise SystemExit("Verification missed the deadline; refusing late publication")
    print("All gates and downloaded hashes verified; waiting for 05:00 UTC", flush=True)
    while (remaining := (TARGET - dt.datetime.now(dt.timezone.utc)).total_seconds()) > 0:
        time.sleep(min(remaining, 10))
    fresh = fetch_release()
    validate_release(fresh, args.commit)
    if fresh["id"] != release["id"] or snapshot != [
        (a["id"], a["name"], a["digest"], a["updated_at"]) for a in fresh["assets"]
    ] or fresh["body"] != release["body"]:
        raise SystemExit("Draft changed after verification; publication blocked")
    if dt.datetime.now(dt.timezone.utc) > TARGET + dt.timedelta(seconds=60):
        raise SystemExit("Publication runner missed its target window; refusing backdating")
    gh("release", "edit", TAG, "--repo", REPO, "--draft=false", "--latest")
    final = fetch_release()
    if final.get("draft") or final.get("prerelease"):
        raise SystemExit("Public release verification failed")
    print(final["html_url"], flush=True)


if __name__ == "__main__":
    main()
