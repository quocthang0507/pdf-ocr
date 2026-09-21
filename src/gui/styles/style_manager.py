"""Load and switch the application themes, including the system default."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from src.utils.logger import logger

SYSTEM = "system"
LIGHT = "light"
DARK = "dark"
THEMES: tuple[str, ...] = (SYSTEM, LIGHT, DARK)

STATUS_SUCCESS_LIGHT = "#15803d"
STATUS_SUCCESS_DARK = "#4ade80"
STATUS_ERROR_LIGHT = "#dc2626"
STATUS_ERROR_DARK = "#f87171"
STATUS_WARNING_LIGHT = "#d97706"
STATUS_WARNING_DARK = "#fbbf24"
STATUS_INFO_LIGHT = "#1d4ed8"
STATUS_INFO_DARK = "#60a5fa"
STATUS_MUTED_LIGHT = "#5a6474"
STATUS_MUTED_DARK = "#9aa6b8"


ICONS_PLACEHOLDER = "@ICONS@"


def icons_dir() -> Path:
    """Glyphs the themes draw; Qt resolves url() against the working directory,
    so the sheets name them by absolute path, filled in when a theme loads."""
    return Path(__file__).with_name("icons")


def _theme_path(name: str) -> Path:
    """Resolve a bundled stylesheet next to this module, frozen builds included."""
    return Path(__file__).with_name(f"{name}_theme.qss")


def _system_theme() -> str:
    """Follow the desktop's colour scheme, defaulting to light when unknown."""
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        return LIGHT
    scheme = application.styleHints().colorScheme()
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


class StyleManager:
    """Stateful theme service; it owns the application-wide stylesheet."""

    _active_current: str | None = None
    _active_selected: str | None = None

    def __init__(self, application: QApplication | None = None) -> None:
        resolved = application or QApplication.instance()
        if not isinstance(resolved, QApplication):
            raise RuntimeError("Cần khởi tạo QApplication trước khi áp dụng giao diện.")
        self._application = resolved
        self._selected = SYSTEM
        self._current = _system_theme()

    @staticmethod
    def available_themes() -> tuple[str, ...]:
        return THEMES

    @property
    def selected_theme(self) -> str:
        """What the user chose, which may still be the system default."""
        return self._selected

    @property
    def current_theme(self) -> str:
        """The concrete theme currently painted on screen."""
        return self._current

    def resolve(self, name: str) -> str:
        """Turn a stored preference into the theme that will actually be drawn."""
        if name not in THEMES:
            raise ValueError("Giao diện phải là system, light hoặc dark.")
        return _system_theme() if name == SYSTEM else name

    def stylesheet(self, name: str) -> str:
        """Read one theme from disk; an absent file yields the platform default."""
        resolved = self.resolve(name)
        try:
            sheet = _theme_path(resolved).read_text(encoding="utf-8")
        except OSError:
            logger.warning("Không đọc được tệp giao diện '{}'.", resolved)
            return ""
        return sheet.replace(ICONS_PLACEHOLDER, icons_dir().as_posix())

    def apply(self, name: str) -> str:
        """Repaint the whole application and report the theme now in use."""
        resolved = self.resolve(name)
        self._application.setStyleSheet(self.stylesheet(resolved))
        self._selected = name
        self._current = resolved
        StyleManager._active_current = resolved
        StyleManager._active_selected = name
        logger.info("Đã áp dụng giao diện '{}'.", resolved)
        return resolved


def is_dark_theme(application: QApplication | None = None) -> bool:
    """Check whether the application is currently running under a dark theme."""
    if StyleManager._active_current is not None:
        return StyleManager._active_current == DARK
    app = application or QApplication.instance()
    if isinstance(app, QApplication):
        sheet = app.styleSheet()
        if sheet:
            if "Dark theme" in sheet or "#11161d" in sheet:
                return True
            if "Light theme" in sheet or "#f5f7fa" in sheet:
                return False
        scheme = app.styleHints().colorScheme()
        return scheme == Qt.ColorScheme.Dark
    return False


def status_success_color(dark: bool | None = None) -> QColor:
    """Theme-aware success/exists color (emerald green)."""
    is_dark = is_dark_theme() if dark is None else dark
    return QColor(STATUS_SUCCESS_DARK if is_dark else STATUS_SUCCESS_LIGHT)


def status_error_color(dark: bool | None = None) -> QColor:
    """Theme-aware error/missing color (rose red)."""
    is_dark = is_dark_theme() if dark is None else dark
    return QColor(STATUS_ERROR_DARK if is_dark else STATUS_ERROR_LIGHT)


def status_accent_color(dark: bool | None = None) -> QColor:
    """Theme-aware accent/running color (blue)."""
    is_dark = is_dark_theme() if dark is None else dark
    return QColor(STATUS_INFO_DARK if is_dark else STATUS_INFO_LIGHT)


def status_muted_color(dark: bool | None = None) -> QColor:
    """Theme-aware muted/waiting color (slate)."""
    is_dark = is_dark_theme() if dark is None else dark
    return QColor(STATUS_MUTED_DARK if is_dark else STATUS_MUTED_LIGHT)
