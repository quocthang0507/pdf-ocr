"""Quick-task tool bar bound to the shared application commands."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QStyle, QToolBar, QWidget

from src.gui.components.menu_bar import SEPARATOR

TOOL_BAR_KEYS: tuple[str, ...] = (
    "open_file",
    "open_folder",
    SEPARATOR,
    "run_ocr",
    "export",
    SEPARATOR,
    "zoom_in",
    "zoom_out",
    "zoom_reset",
    SEPARATOR,
    "settings",
)

_STANDARD_ICONS: dict[str, QStyle.StandardPixmap] = {
    "open_file": QStyle.StandardPixmap.SP_FileIcon,
    "open_folder": QStyle.StandardPixmap.SP_DirOpenIcon,
    "run_ocr": QStyle.StandardPixmap.SP_MediaPlay,
    "export": QStyle.StandardPixmap.SP_DialogSaveButton,
    "zoom_in": QStyle.StandardPixmap.SP_ArrowUp,
    "zoom_out": QStyle.StandardPixmap.SP_ArrowDown,
    "zoom_reset": QStyle.StandardPixmap.SP_BrowserReload,
    "settings": QStyle.StandardPixmap.SP_FileDialogDetailedView,
}


class ApplicationToolBar(QToolBar):
    """Icon-and-text tool bar; its object name lets Qt restore the layout."""

    def __init__(
        self, actions: Mapping[str, QAction], parent: QWidget | None = None
    ) -> None:
        super().__init__("Thanh công cụ", parent)
        self.setObjectName("main_tool_bar")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setMovable(True)
        for key in TOOL_BAR_KEYS:
            if key == SEPARATOR:
                self.addSeparator()
                continue
            action = actions[key]
            self._apply_icon(action, key)
            self.addAction(action)

    def _apply_icon(self, action: QAction, key: str) -> None:
        """Use the platform style so the bundle carries no extra image assets."""
        pixmap = _STANDARD_ICONS.get(key)
        if pixmap is not None and action.icon().isNull():
            action.setIcon(self.style().standardIcon(pixmap))
