"""Application paths independent of the working directory and GUI framework."""

import sys
import tempfile
from pathlib import Path, PureWindowsPath


def get_app_root() -> Path:
    """Use the executable directory for portable builds, repository root in dev."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def normalize_directory(path: str | Path) -> Path:
    """Accept an explicit location, rejecting parent traversal before resolving."""
    raw = str(path)
    if not raw.strip() or "\x00" in raw:
        raise ValueError("Invalid directory.")
    if ".." in PureWindowsPath(raw).parts or ".." in Path(raw).parts:
        raise ValueError("Parent traversal is not allowed.")
    return Path(raw).expanduser().resolve()


def contained_directory(base: Path, relative: str) -> Path:
    """Resolve links/junctions before accepting a child directory."""
    target = (base / relative).resolve()
    if not target.is_relative_to(base) or target == base:
        raise ValueError("Directory escapes the storage root.")
    return target


def ensure_writable_directory(path: Path) -> None:
    """Check actual create/write access instead of relying on os.access/ACL hints."""
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=path) as probe:
        probe.write(b"weights-storage-check")
        probe.flush()
