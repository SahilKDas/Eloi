"""Retired Kaggle exporter, preserved for historical audit/tests only.

The generated cell embeds four_player_kaggle_real_pipeline.py as base64 text,
writes it into /kaggle/working, runs FFA and Teams collection/training, and
archives the output. This avoids fragile manual triple-quoted script pastes in
the Kaggle editor.
"""

from __future__ import annotations

import base64
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "scripts" / "four_player_kaggle_real_pipeline.py"
OUTPUT = ROOT / "tmp" / "kaggle" / "eloi_v4_bootstrap_cell.py"


def build_cell(source: bytes) -> str:
    encoded = base64.b64encode(source).decode("ascii")
    return f'''# Eloi v4 Kaggle self-play/training cell.
# Paste this entire cell into Kaggle and run it.
from pathlib import Path
import base64
import shutil
import subprocess
import sys

WORK = Path("/kaggle/working/eloi-v4")
SCRIPT = Path("/kaggle/working/four_player_kaggle_real_pipeline.py")
SCRIPT.write_bytes(base64.b64decode("{encoded}"))

for mode in ("ffa", "teams"):
    subprocess.check_call([
        sys.executable,
        str(SCRIPT),
        "--mode",
        mode,
        "--stage",
        "all",
        "--output",
        str(WORK),
    ])

archive = shutil.make_archive("/kaggle/working/eloi-v4-selfplay-training", "zip", WORK)
print("Wrote", SCRIPT)
print("Wrote", archive)
'''


def main() -> int:
    raise SystemExit("Kaggle campaign retired. Use cargo run --release -p eloi-rs -- --four-player-gui for handcrafted Teams play. Historical exporter retained for evidence only.")


if __name__ == "__main__":
    raise SystemExit(main())
