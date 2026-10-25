"""Quick-task tool bar bound to the shared application commands."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
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

#: Stroke colour of the line icons on the light tool bar.
DEFAULT_ICON_COLOR = "#334155"

# Line icons drawn on a 24 px grid. Platform style icons are unreliable here:
# the Windows 11 style renders several of them (file, arrows) blank or so pale
# that the buttons looked text-only.
_SVG_ICONS: dict[str, str] = {
    "open_file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 '
    '2-2V9z"/><path d="M14 3v6h6"/>',
    "open_folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 '
    '1-2 2H5a2 2 0 0 1-2-2z"/>',
    "run_ocr": '<path d="M7 4l13 8-13 8z"/>',
    "select_region": '<rect x="4" y="5" width="16" height="14" rx="1" '
    'stroke-dasharray="3 2.5"/><path d="M9 12h6"/>',
    "pdf_tools": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/>',
    "document_properties": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/>'
    '<path d="M12 7.5v.01"/>',
    "export": '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M4 20h16"/>',
    "zoom_in": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.4-4.4"/>'
    '<path d="M8 11h6"/><path d="M11 8v6"/>',
    "zoom_out": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.4-4.4"/>'
    '<path d="M8 11h6"/>',
    "zoom_reset": '<path d="M4 9V4h5"/><path d="M20 9V4h-5"/><path d="M4 15v5h5"/>'
    '<path d="M20 15v5h-5"/>',
    "settings": '<path d="M4 7h9"/><path d="M19 7h1"/><circle cx="16" cy="7" r="2.5"/>'
    '<path d="M4 17h3"/><path d="M13 17h7"/><circle cx="10" cy="17" r="2.5"/>',
}


def _svg_icon(key: str, colour: QColor, size: int = ICON_SIZE) -> QIcon:
    """Render a bundled line icon at 1x and 2x so it stays crisp on HiDPI."""
    body = _SVG_ICONS.get(key)
    if body is None:
        return QIcon()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{colour.name()}" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return QIcon()
    icon = QIcon()
    for scale in (1, 2):
        pixmap = QPixmap(size * scale, size * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(float(scale))
        icon.addPixmap(pixmap)
    return icon


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
        """Prefer the bundled line icon; fall back to the platform style icon."""
        if not action.icon().isNull():
            return
        icon = _svg_icon(key, QColor(DEFAULT_ICON_COLOR))
        if icon.isNull():
            pixmap = _STANDARD_ICONS.get(key)
            if pixmap is None:
                return
            icon = self.style().standardIcon(pixmap)
        self._source_icons[key] = icon
        action.setIcon(icon)

    def apply_icon_color(self, colour: QColor | None) -> None:
        """Re-tint the icons, or restore the originals when None is given.

        Line icons are simply redrawn in the new colour; platform fallback
        icons are re-tinted with a duotone map that keeps their shading.
        """
        for key, action in self._actions_by_key.items():
            source = self._source_icons.get(key)
            if source is None:
                continue
            if key in _SVG_ICONS:
                redrawn = _svg_icon(key, colour or QColor(DEFAULT_ICON_COLOR))
                if not redrawn.isNull():
                    action.setIcon(redrawn)
                    continue
            action.setIcon(source if colour is None else _tinted(source, colour))
