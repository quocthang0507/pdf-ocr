"""Opening sizes for windows whose content is wider than their minimum size."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QTabWidget, QWidget

SCREEN_SHARE = 0.9


def fit_to_contents(window: QWidget) -> None:
    """Open large enough for every tab and field, but never off the screen.

    A minimum size only stops the user shrinking a dialog; with tabs wider
    than it, the tab bar fell back to tiny scroll arrows and crowded forms
    squeezed their fields below a readable height.
    """
    screen = window.screen() or QGuiApplication.primaryScreen()
    window.resize(window.sizeHint().expandedTo(window.size()))
    layout = window.layout()
    if layout is not None:
        layout.activate()
    # QTabWidget leaves the tab bar out of its size hint once it can scroll.
    extra = max(
        (
            tabs.tabBar().sizeHint().width() - tabs.tabBar().width()
            for tabs in window.findChildren(QTabWidget)
            if tabs.isVisibleTo(window)
        ),
        default=0,
    )
    wanted = window.size() + QSize(max(extra, 0) + 8 if extra > 0 else 0, 0)
    if screen is not None:
        available = screen.availableSize()
        wanted = wanted.boundedTo(
            QSize(
                int(available.width() * SCREEN_SHARE),
                int(available.height() * SCREEN_SHARE),
            )
        )
    window.resize(wanted)
