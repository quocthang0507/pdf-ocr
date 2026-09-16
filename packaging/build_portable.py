"""Build the portable bundle and zip it for copying onto another machine.

    python packaging/build_portable.py                # build and zip
    python packaging/build_portable.py --with-weights # include src/models too
    python packaging/build_portable.py --no-archive   # leave dist/ unzipped

The bundle is self-contained: the target machine needs no Python and no
internet connection. Weights live in a `models` folder beside the executable,
which `ModelWeightsManager` looks for first when the application is frozen.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess  # nosec B404
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = PROJECT_ROOT / "packaging" / "pdf-ocr.spec"
DIST_DIR = PROJECT_ROOT / "dist"
BUNDLE_DIR = DIST_DIR / "pdf-ocr"
WEIGHTS_SOURCE = PROJECT_ROOT / "src" / "models"
ARCHIVE = DIST_DIR / "pdf-ocr-portable.zip"


def run_pyinstaller() -> None:
    """Run PyInstaller through this interpreter so the venv is always used."""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC_FILE),
        "--noconfirm",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(PROJECT_ROOT / "build" / "pyinstaller"),
    ]
    # Fixed argument list, no shell: nothing here comes from user input.
    subprocess.run(command, check=True, cwd=PROJECT_ROOT)  # nosec B603


def copy_weights() -> int:
    """Carry the downloaded models into the bundle for a fully offline copy."""
    if not WEIGHTS_SOURCE.is_dir():
        return 0
    destination = BUNDLE_DIR / "models"
    copied = 0
    for source in sorted(WEIGHTS_SOURCE.rglob("*")):
        if not source.is_file() or source.name == ".gitkeep":
            continue
        target = destination / source.relative_to(WEIGHTS_SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def make_archive() -> Path:
    """Zip the bundle so it survives being emailed or copied to a USB stick."""
    ARCHIVE.unlink(missing_ok=True)
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(BUNDLE_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(DIST_DIR))
    return ARCHIVE


def directory_size_mb(path: Path) -> float:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) / 1e6


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Đóng gói bản Portable.")
    parser.add_argument(
        "--with-weights",
        action="store_true",
        help="Sao chép src/models vào bundle để chạy hoàn toàn ngoại tuyến.",
    )
    parser.add_argument(
        "--no-archive", action="store_true", help="Không nén thành tệp zip."
    )
    options = parser.parse_args(argv)

    run_pyinstaller()
    if not BUNDLE_DIR.is_dir():
        sys.stderr.write("PyInstaller không tạo được thư mục dist/pdf-ocr.\n")
        return 1

    lines = [f"Bundle: {BUNDLE_DIR} ({directory_size_mb(BUNDLE_DIR):.0f} MB)"]
    if options.with_weights:
        lines.append(f"Đã chép {copy_weights()} tệp weights vào bundle.")
    if not options.no_archive:
        lines.append(f"Archive: {make_archive()}")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
