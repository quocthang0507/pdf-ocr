"""Quick-task tool bar bound to the shared application commands."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QStyle, QToolBar, QWidget

from src.gui.components.menu_bar import SEPARATOR

TOOL_BAR_KEYS: tuple[str, ...] = (
    "open_file",
    "open_folder",
    SEPARATOR,
    "run_ocr",
    "select_region",
    "pdf_tools",
    "document_properties",
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
    "pdf_tools": QStyle.StandardPixmap.SP_FileDialogListView,
    "document_properties": QStyle.StandardPixmap.SP_FileDialogInfoView,
    "export": QStyle.StandardPixmap.SP_DialogSaveButton,
    "zoom_in": QStyle.StandardPixmap.SP_ArrowUp,
    "zoom_out": QStyle.StandardPixmap.SP_ArrowDown,
    "zoom_reset": QStyle.StandardPixmap.SP_BrowserReload,
    "settings": QStyle.StandardPixmap.SP_FileDialogDetailedView,
}


ICON_SIZE = 18


def _tint_pixmap(source: QPixmap, colour: QColor, scale: int) -> QPixmap:
    """Tint a single pixmap with a duotone gradient and tag its device pixel ratio."""
    image = source.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    shadow = colour.darker(280)
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            alpha = pixel.alpha()
            if alpha == 0:
                continue
            luminance = (
                0.299 * pixel.red() + 0.587 * pixel.green() + 0.114 * pixel.blue()
            ) / 255
            mixed = _mix(shadow, colour, luminance)
            mixed.setAlpha(alpha)
            image.setPixelColor(x, y, mixed)
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(float(scale))
    return pixmap


def _tinted(icon: QIcon, colour: QColor, size: int = ICON_SIZE) -> QIcon:
    """Recolour a style icon for a dark tool bar across 1x and 2x HiDPI scales."""
    base = icon.pixmap(QSize(size, size))
    if base.isNull():
        return icon
    result = QIcon()
    for scale in (1, 2):
        scaled = icon.pixmap(QSize(size * scale, size * scale))
        if not scaled.isNull():
            result.addPixmap(_tint_pixmap(scaled, colour, scale))
    return result


def _mix(start: QColor, end: QColor, ratio: float) -> QColor:
    """Linearly blend two colours; ratio 0 is the start, 1 is the end."""
    return QColor(
        round(start.red() + (end.red() - start.red()) * ratio),
        round(start.green() + (end.green() - start.green()) * ratio),
        round(start.blue() + (end.blue() - start.blue()) * ratio),
    )


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

        Style icons are drawn dark and disappear on a dark tool bar, so they
        are re-tinted with a duotone map that keeps their internal shading.
        """
        for key, action in self._actions_by_key.items():
            source = self._source_icons.get(key)
            if source is None:
                continue
            action.setIcon(source if colour is None else _tinted(source, colour))
