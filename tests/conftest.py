"""Shared pytest configuration; GUI tests must not require a real display."""

from __future__ import annotations

import gc
import os
import sys
from collections.abc import Iterator

import pytest


def _needs_offscreen_qt() -> bool:
    """Only Linux CI containers lack a usable native Qt platform plugin."""
    if not sys.platform.startswith("linux"):
        return False
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


if _needs_offscreen_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _destroy_leftover_windows() -> Iterator[None]:
    """Delete every top-level widget a test leaves behind, at a known moment.

    Windows kept alive by signal closures are otherwise freed whenever the
    garbage collector happens to run, which can be in the middle of Qt
    repolishing every widget for a theme change, and that crashes Qt.
    """
    yield
    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance()
    if not isinstance(application, QApplication):
        return
    for widget in application.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    gc.collect()
