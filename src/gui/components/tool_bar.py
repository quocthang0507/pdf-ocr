"""Quick-task tool bar bound to the shared application commands."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QToolBar, QWidget

from src.gui.components.menu_bar import SEPARATOR

TOOL_BAR_KEYS: tuple[str, ...] = (
    "open_file",
    "open_folder",
    SEPARATOR,
    "run_ocr",
    "select_region",
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
    "select_region": QStyle.StandardPixmap.SP_FileDialogContentsView,
    "export": QStyle.StandardPixmap.SP_DialogSaveButton,
    "zoom_in": QStyle.StandardPixmap.SP_ArrowUp,
    "zoom_out": QStyle.StandardPixmap.SP_ArrowDown,
    "zoom_reset": QStyle.StandardPixmap.SP_BrowserReload,
    "settings": QStyle.StandardPixmap.SP_FileDialogDetailedView,
}


ICON_SIZE = 18


def _tinted(icon: QIcon, colour: QColor, size: int = ICON_SIZE) -> QIcon:
    """Recolour a style icon so it stays visible on a dark tool bar."""
    source = icon.pixmap(QSize(size, size))
    if source.isNull():
        return icon
    tinted = QPixmap(source.size())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), colour)
    painter.end()
    return QIcon(tinted)


class ApplicationToolBar(QToolBar):
    """Icon-and-text tool bar; its object name lets Qt restore the layout."""

    def __init__(
        self, actions: Mapping[str, QAction], parent: QWidget | None = None
    ) -> None:
        super().__init__("Thanh công cụ", parent)
        self.setObjectName("main_tool_bar")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setMovable(True)
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._source_icons: dict[str, QIcon] = {}
        self._actions_by_key: dict[str, QAction] = {}
        for key in TOOL_BAR_KEYS:
            if key == SEPARATOR:
                self.addSeparator()
                continue
            action = actions[key]
            self._apply_icon(action, key)
            self._actions_by_key[key] = action
            self.addAction(action)

    def _apply_icon(self, action: QAction, key: str) -> None:
        """Use the platform style so the bundle carries no extra image assets."""
        pixmap = _STANDARD_ICONS.get(key)
        if pixmap is None or not action.icon().isNull():
            return
        icon = self.style().standardIcon(pixmap)
        self._source_icons[key] = icon
        action.setIcon(icon)

    def apply_icon_color(self, colour: QColor | None) -> None:
        """Re-tint the icons, or restore the originals when None is given.

        Style icons are drawn dark and disappear on a dark tool bar, but
        tinting flattens their detail, so it is only applied where needed.
        """
        for key, action in self._actions_by_key.items():
            source = self._source_icons.get(key)
            if source is None:
                continue
            action.setIcon(source if colour is None else _tinted(source, colour))
