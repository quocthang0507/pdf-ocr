"""Load and switch the application themes, including the system default."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.utils.logger import logger

SYSTEM = "system"
LIGHT = "light"
DARK = "dark"
THEMES: tuple[str, ...] = (SYSTEM, LIGHT, DARK)


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
            return _theme_path(resolved).read_text(encoding="utf-8")
        except OSError:
            logger.warning("Không đọc được tệp giao diện '{}'.", resolved)
            return ""

    def apply(self, name: str) -> str:
        """Repaint the whole application and report the theme now in use."""
        resolved = self.resolve(name)
        self._application.setStyleSheet(self.stylesheet(resolved))
        self._selected = name
        self._current = resolved
        logger.info("Đã áp dụng giao diện '{}'.", resolved)
        return resolved
