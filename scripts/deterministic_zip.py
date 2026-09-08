"""Create a deterministic ZIP without release-campaign state."""
import datetime as dt
import os
import sys
import zipfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: deterministic_zip.py FOLDER TARGET EPOCH")
    folder, target, epoch = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
    if target.exists():
        raise RuntimeError(f"archive collision: {target}")
    paths = sorted(path for path in folder.rglob("*") if path.is_file())
    stamp = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            if path.is_symlink():
                raise RuntimeError(f"package symlink rejected: {path}")
            item = zipfile.ZipInfo(path.relative_to(folder).as_posix(), date_time=stamp)
            item.create_system = 3
            item.external_attr = 0o100644 << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, path.read_bytes(), compresslevel=9)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
