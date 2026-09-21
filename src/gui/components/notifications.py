"""In-app toast notifications: informative, stackable, and never blocking."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from src.gui.styles.style_manager import is_dark_theme

DEFAULT_DURATION_MS = 4000
MAX_VISIBLE_TOASTS = 4
TOAST_WIDTH = 340
TOAST_MARGIN = 16
TOAST_SPACING = 10


class Severity(str, Enum):
    """How urgent a message is, which decides its colour and its lifetime."""

    SUCCESS = "success"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


_ACCENTS: dict[Severity, str] = {
    Severity.SUCCESS: "#059669",
    Severity.INFO: "#2563eb",
    Severity.WARNING: "#d97706",
    Severity.ERROR: "#dc2626",
}

_ICONS: dict[Severity, str] = {
    Severity.SUCCESS: "✓",
    Severity.INFO: "i",
    Severity.WARNING: "!",
    Severity.ERROR: "×",
}


class Toast(QFrame):
    """One message card. Errors stay until dismissed; the rest fade by themselves."""

    dismissed = Signal(QObject)

    def __init__(
        self,
        message: str,
        severity: Severity,
        duration_ms: int,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(f"toast_{severity.value}")
        self.severity = severity
        self.duration_ms = duration_ms
        self.icon_label = QLabel(_ICONS[severity], self)
        self.icon_label.setObjectName("toast_icon")
        self.message_label = QLabel(message, self)
        self.message_label.setObjectName("toast_message")
        self.message_label.setWordWrap(True)
        self.close_button = QPushButton("✕", self)
        self.close_button.setObjectName("toast_close")
        self.close_button.setFlat(True)
        self.close_button.setFixedWidth(24)
        self.close_button.clicked.connect(self.dismiss)
        self._build_layout()
        self._apply_style()
        if duration_ms > 0:
            QTimer.singleShot(duration_ms, self.dismiss)

    def _build_layout(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 8, 10)
        layout.setSpacing(10)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.message_label, 1)
        layout.addWidget(self.close_button)
        self.setFixedWidth(TOAST_WIDTH)
        self.adjustSize()

    def _is_dark(self) -> bool:
        if is_dark_theme():
            return True
        application = QApplication.instance()
        if isinstance(application, QApplication):
            scheme = application.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return True
        bg = self.palette().color(self.backgroundRole())
        return bg.lightness() < 128

    def _apply_style(self) -> None:
        """Paint the card itself so it matches the theme even before one loads."""
        accent = self.accent_color().name()
        if self._is_dark():
            bg = "#1a212b"
            fg = "#e6ebf2"
            close_fg = "#9aa6b8"
            close_hover_bg = "#232c38"
            border = "#2c3644"
        else:
            bg = "#ffffff"
            fg = "#16202e"
            close_fg = "#5a6474"
            close_hover_bg = "#eef1f6"
            border = "#d8dee7"

        self.setStyleSheet(
            f"#{self.objectName()} {{"
            f" background-color: {bg};"
            f" border: 1px solid {border};"
            f" border-left: 4px solid {accent};"
            f" border-radius: 8px; }}"
            f" #toast_icon {{"
            f" color: {accent}; font-weight: 700; font-size: 14px;"
            f" background: transparent; border: none; }}"
            f" #toast_message {{"
            f" color: {fg}; font-size: 13px; background: transparent;"
            f" border: none; }}"
            f" #toast_close {{"
            f" background: transparent; border: none; color: {close_fg};"
            f" font-size: 13px; font-weight: bold; border-radius: 4px;"
            f" padding: 2px; }}"
            f" #toast_close:hover {{"
            f" background-color: {close_hover_bg}; color: {fg}; }}"
        )

    def accent_color(self) -> QColor:
        return QColor(_ACCENTS[self.severity])

    def dismiss(self) -> None:
        """Remove the card once; a manual close and the timer may both fire."""
        if not self.isVisible() and self.parent() is None:
            return
        self.hide()
        self.dismissed.emit(self)
        self.deleteLater()


class NotificationCenter(QObject):
    """Stateful stack of toasts anchored to the bottom right of one window.

    It watches the host for resizes so the stack stays in the corner, and drops
    the oldest card when more arrive than the corner can show at once.
    """

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self._host = host
        self._toasts: list[Toast] = []
        host.installEventFilter(self)

    def notify(
        self,
        message: str,
        severity: Severity = Severity.INFO,
        *,
        duration_ms: int | None = None,
    ) -> Toast:
        """Show a message; errors wait for the user, everything else fades."""
        lifetime = _lifetime(severity, duration_ms)
        toast = Toast(message, severity, lifetime, self._host)
        toast.dismissed.connect(self._forget)
        self._toasts.append(toast)
        self._trim()
        toast.show()
        self.reposition()
        return toast

    def visible_toasts(self) -> list[Toast]:
        return list(self._toasts)

    def dismiss_all(self) -> None:
        for toast in list(self._toasts):
            toast.dismiss()

    def reposition(self) -> None:
        """Stack the cards upward from the bottom-right corner of the host."""
        bottom = self._host.height() - TOAST_MARGIN - self._reserved_bottom()
        for toast in reversed(self._toasts):
            toast.adjustSize()
            left = self._host.width() - toast.width() - TOAST_MARGIN
            bottom -= toast.height()
            toast.move(max(left, TOAST_MARGIN), max(bottom, TOAST_MARGIN))
            toast.raise_()
            bottom -= TOAST_SPACING

    def _reserved_bottom(self) -> int:
        """Never cover the window's status bar; its controls must stay clickable."""
        status_bar = getattr(self._host, "statusBar", None)
        if status_bar is None:
            return 0
        bar = status_bar()
        if bar is None or not bar.isVisibleTo(self._host):
            return 0
        # isVisibleTo, not isVisible: the window may not be on screen yet.
        return int(bar.sizeHint().height())

    def eventFilter(  # noqa: N802 - Qt override
        self, watched: QObject, event: QEvent
    ) -> bool:
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self.reposition()
        return False

    def _forget(self, toast: QObject) -> None:
        if isinstance(toast, Toast) and toast in self._toasts:
            self._toasts.remove(toast)
        self.reposition()

    def _trim(self) -> None:
        while len(self._toasts) > MAX_VISIBLE_TOASTS:
            self._toasts[0].dismiss()


def _lifetime(severity: Severity, duration_ms: int | None) -> int:
    if duration_ms is not None:
        return duration_ms
    return 0 if severity is Severity.ERROR else DEFAULT_DURATION_MS


__all__ = [
    "DEFAULT_DURATION_MS",
    "MAX_VISIBLE_TOASTS",
    "NotificationCenter",
    "Severity",
    "Toast",
]
