"""Export a paste-safe Kaggle bootstrap cell for Eloi v4.

The generated cell embeds four_player_kaggle_pipeline.py as base64 text, writes
it into /kaggle/working, runs both bootstrap modes, and archives the output.
This avoids fragile manual triple-quoted script pastes in the Kaggle editor.
"""

from __future__ import annotations

import base64
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "scripts" / "four_player_kaggle_pipeline.py"
OUTPUT = ROOT / "tmp" / "kaggle" / "eloi_v4_bootstrap_cell.py"


def build_cell(source: bytes) -> str:
    encoded = base64.b64encode(source).decode("ascii")
    return f'''# Eloi v4 Kaggle bootstrap cell.
# Paste this entire cell into Kaggle and run it.
from pathlib import Path
import base64
import shutil
import subprocess
import sys

WORK = Path("/kaggle/working/eloi-v4")
SCRIPT = Path("/kaggle/working/four_player_kaggle_pipeline.py")
SCRIPT.write_bytes(base64.b64decode("{encoded}"))

for mode in ("ffa", "teams"):
    subprocess.check_call([
        sys.executable,
        str(SCRIPT),
        "--mode",
        mode,
        "--output",
        str(WORK),
    ])

archive = shutil.make_archive("/kaggle/working/eloi-v4-bootstrap-records", "zip", WORK)
print("Wrote", SCRIPT)
print("Wrote", archive)
'''


def main() -> int:
    source = PIPELINE.read_bytes()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build_cell(source), encoding="utf-8", newline="\n")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
