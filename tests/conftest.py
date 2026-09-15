"""Shared pytest configuration; GUI tests must not require a real display."""

from __future__ import annotations

import os
import sys


def _needs_offscreen_qt() -> bool:
    """Only Linux CI containers lack a usable native Qt platform plugin."""
    if not sys.platform.startswith("linux"):
        return False
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


if _needs_offscreen_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
