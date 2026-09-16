"""Themes load, switch instantly, stay in step, and stay readable."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.gui.styles import style_manager as style_module
from src.gui.styles.style_manager import THEMES, StyleManager

pytestmark = pytest.mark.gui

_RULE = re.compile(r"(?P<selector>[^{}]+)\{(?P<body>[^{}]*)\}", re.MULTILINE)
_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _rules(sheet: str) -> list[re.Match[str]]:
    """Parse rules from a stylesheet, ignoring its documentation comments."""
    return list(_RULE.finditer(_COMMENT.sub("", sheet)))


@pytest.fixture
def manager(qapp: QApplication) -> StyleManager:
    return StyleManager(qapp)


def _selectors(sheet: str) -> set[str]:
    return {" ".join(match.group("selector").split()) for match in _rules(sheet)}


def _relative_luminance(colour: str) -> float:
    channels = [int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    first, second = _relative_luminance(foreground), _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _base_colours(sheet: str) -> tuple[str, str]:
    """Read the application-wide text and background colours from a theme."""
    body = next(
        match.group("body")
        for match in _rules(sheet)
        if match.group("selector").strip() == "QWidget"
    )
    text = re.search(r"(?<!-)\bcolor:\s*(#[0-9a-fA-F]{6})", body)
    background = re.search(r"background-color:\s*(#[0-9a-fA-F]{6})", body)
    assert text and background, "Chủ đề phải khai báo màu chữ và màu nền cơ sở."
    return text.group(1), background.group(1)


def test_every_supported_theme_is_offered(manager: StyleManager) -> None:
    assert manager.available_themes() == ("system", "light", "dark")
    assert THEMES == ("system", "light", "dark")


def test_an_unknown_theme_is_refused(manager: StyleManager) -> None:
    with pytest.raises(ValueError, match="Giao diện"):
        manager.apply("neon")


def test_system_resolves_to_a_concrete_theme(manager: StyleManager) -> None:
    assert manager.resolve("system") in ("light", "dark")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_each_theme_ships_a_stylesheet(manager: StyleManager, theme: str) -> None:
    sheet = manager.stylesheet(theme)

    assert "QMainWindow" in sheet
    assert len(_HEX.findall(sheet)) > 20


def test_applying_a_theme_styles_the_running_application(
    manager: StyleManager, qapp: QApplication
) -> None:
    manager.apply("dark")

    assert qapp.styleSheet() == manager.stylesheet("dark")
    assert manager.current_theme == "dark"


def test_switching_themes_replaces_the_whole_stylesheet(
    manager: StyleManager, qapp: QApplication
) -> None:
    manager.apply("dark")
    dark = qapp.styleSheet()

    manager.apply("light")

    assert qapp.styleSheet() != dark
    assert manager.current_theme == "light"


def test_applying_system_reports_the_resolved_theme(manager: StyleManager) -> None:
    resolved = manager.apply("system")

    assert resolved in ("light", "dark")
    assert manager.selected_theme == "system"


def test_both_themes_style_exactly_the_same_widgets(manager: StyleManager) -> None:
    light = _selectors(manager.stylesheet("light"))
    dark = _selectors(manager.stylesheet("dark"))

    assert light == dark


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_body_text_meets_the_wcag_aa_contrast_ratio(
    manager: StyleManager, theme: str
) -> None:
    text, background = _base_colours(manager.stylesheet(theme))

    assert _contrast(text, background) >= 4.5


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_each_theme_defines_hover_focus_and_disabled_states(
    manager: StyleManager, theme: str
) -> None:
    sheet = manager.stylesheet(theme)

    assert ":hover" in sheet
    assert ":focus" in sheet
    assert ":disabled" in sheet


def test_a_missing_stylesheet_does_not_stop_the_application(
    manager: StyleManager, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        style_module, "_theme_path", lambda name: Path("/khong/ton/tai.qss")
    )

    resolved = manager.apply("dark")

    assert resolved == "dark"
    assert qapp.styleSheet() == ""


def test_the_settings_dialog_offers_and_stores_the_theme(
    qtbot: object, tmp_path: Path
) -> None:
    from pytestqt.qtbot import QtBot

    from src.config import ConfigManager
    from src.gui.dialogs.settings_dialog import SettingsDialog

    bot = QtBot(qtbot) if not isinstance(qtbot, QtBot) else qtbot
    config = ConfigManager(tmp_path / "config", use_qsettings=False)
    dialog = SettingsDialog(config=config)
    bot.addWidget(dialog)
    dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("dark"))

    with bot.waitSignal(dialog.theme_changed) as blocker:
        dialog.accept()

    assert blocker.args == ["dark"]
    assert config.load().theme == "dark"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_modal_and_dialog_widgets_are_styled(manager: StyleManager, theme: str) -> None:
    sheet = manager.stylesheet(theme)
    assert "QMessageBox" in sheet
    assert "QDialogButtonBox" in sheet
    assert "QListWidget" in sheet
    assert "QTableWidget" in sheet


def test_is_dark_theme_tracks_current_theme(
    manager: StyleManager, qapp: QApplication
) -> None:
    from src.gui.styles.style_manager import is_dark_theme

    manager.apply("light")
    assert is_dark_theme(qapp) is False

    manager.apply("dark")
    assert is_dark_theme(qapp) is True

    manager.apply("light")
    assert is_dark_theme(qapp) is False


def test_status_colors_meet_wcag_contrast() -> None:
    from src.gui.styles.style_manager import (
        STATUS_ERROR_DARK,
        STATUS_ERROR_LIGHT,
        STATUS_SUCCESS_DARK,
        STATUS_SUCCESS_LIGHT,
        status_error_color,
        status_success_color,
    )

    light_surface = "#ffffff"
    dark_surface = "#1a212b"

    # Light theme contrast (WCAG AA >= 4.0 for status items)
    assert _contrast(STATUS_SUCCESS_LIGHT, light_surface) >= 4.0
    assert _contrast(STATUS_ERROR_LIGHT, light_surface) >= 4.0

    # Dark theme contrast (WCAG AA >= 4.5)
    assert _contrast(STATUS_SUCCESS_DARK, dark_surface) >= 4.5
    assert _contrast(STATUS_ERROR_DARK, dark_surface) >= 4.5

    # Check color getters
    assert status_success_color(dark=False).name() == STATUS_SUCCESS_LIGHT
    assert status_success_color(dark=True).name() == STATUS_SUCCESS_DARK
    assert status_error_color(dark=False).name() == STATUS_ERROR_LIGHT
    assert status_error_color(dark=True).name() == STATUS_ERROR_DARK

