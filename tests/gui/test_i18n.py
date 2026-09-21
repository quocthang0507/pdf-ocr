"""The interface speaks Vietnamese by default and English on request."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from src.config import ConfigManager, Preferences
from src.gui import i18n as i18n_module
from src.gui.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    MENU_CONTEXT,
    TranslationManager,
    available_languages,
)
from src.gui.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def manager(qapp: QApplication) -> TranslationManager:
    translations = TranslationManager(qapp)
    yield translations
    translations.apply(DEFAULT_LANGUAGE)


def test_vietnamese_and_english_are_both_offered() -> None:
    assert set(available_languages()) >= {"vi", "en"}
    assert LANGUAGE_NAMES["vi"] == "Tiếng Việt"
    assert LANGUAGE_NAMES["en"] == "English"


def test_vietnamese_is_the_default(manager: TranslationManager) -> None:
    assert DEFAULT_LANGUAGE == "vi"
    assert manager.current_language == "vi"


def test_an_unknown_language_is_refused(manager: TranslationManager) -> None:
    with pytest.raises(ValueError, match="Ngôn ngữ"):
        manager.apply("fr")


def test_english_translates_the_menu_commands(manager: TranslationManager) -> None:
    manager.apply("en")

    assert QCoreApplication.translate(MENU_CONTEXT, "&Mở tệp…") == "&Open file…"
    assert QCoreApplication.translate(MENU_CONTEXT, "&Chạy OCR") == "&Run OCR"


def test_switching_back_restores_the_source_language(
    manager: TranslationManager,
) -> None:
    manager.apply("en")

    manager.apply("vi")

    assert QCoreApplication.translate(MENU_CONTEXT, "&Mở tệp…") == "&Mở tệp…"
    assert manager.current_language == "vi"


def test_every_offered_language_ships_its_catalogue() -> None:
    for language in available_languages():
        if language == DEFAULT_LANGUAGE:
            continue
        assert (i18n_module.translations_dir() / f"{language}.qm").is_file()


def test_a_missing_catalogue_falls_back_instead_of_failing(
    manager: TranslationManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(i18n_module, "translations_dir", lambda: Path("/khong/ton/tai"))

    applied = manager.apply("en")

    assert applied == DEFAULT_LANGUAGE
    assert QCoreApplication.translate(MENU_CONTEXT, "&Mở tệp…") == "&Mở tệp…"


# -- persisted and reachable from the interface -----------------------------


def test_the_language_preference_round_trips(tmp_path: Path) -> None:
    config = ConfigManager(tmp_path / "config", use_qsettings=False)

    config.save(Preferences(language="en"))

    assert config.load().language == "en"


def test_an_invalid_language_preference_is_refused() -> None:
    with pytest.raises(ValueError):
        Preferences(language="klingon")


def test_the_settings_dialog_offers_and_applies_the_language(
    qtbot, tmp_path: Path
) -> None:
    from src.gui.dialogs.settings_dialog import SettingsDialog

    config = ConfigManager(tmp_path / "config", use_qsettings=False)
    dialog = SettingsDialog(config=config)
    qtbot.addWidget(dialog)
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("en"))

    with qtbot.waitSignal(dialog.language_changed) as blocker:
        dialog.accept()

    assert blocker.args == ["en"]
    assert config.load().language == "en"
    TranslationManager().apply(DEFAULT_LANGUAGE)


def test_the_window_retranslates_without_a_restart(
    qtbot, tmp_path: Path, manager: TranslationManager
) -> None:
    settings = QSettings(str(tmp_path / "session.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    vietnamese = window.command_actions["open_file"].text()

    manager.apply("en")
    window.retranslate()

    assert vietnamese == "&Mở tệp…"
    assert window.command_actions["open_file"].text() == "&Open file…"
    assert [action.text() for action in window.menuBar().actions()][0] == "&File"


def test_standard_dialog_buttons_are_labelled_in_vietnamese(qtbot) -> None:
    """Qt ships no Vietnamese catalogue, so OK and Cancel would stay English."""
    from PySide6.QtWidgets import QDialogButtonBox

    from src.gui.i18n import localise_buttons

    buttons = localise_buttons(
        QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Close
        )
    )
    qtbot.addWidget(buttons)

    labels = {button.text() for button in buttons.buttons()}
    assert labels == {"Đồng ý", "Hủy", "Đóng"}


def test_group_box_titles_do_not_swallow_an_ampersand(qtbot, tmp_path) -> None:
    """An & in a Qt title becomes a mnemonic and disappears from the label."""
    from src.config import ConfigManager
    from src.gui.dialogs.settings_dialog import SettingsDialog

    dialog = SettingsDialog(
        config=ConfigManager(tmp_path / "config", use_qsettings=False)
    )
    qtbot.addWidget(dialog)

    from PySide6.QtWidgets import QGroupBox

    titles = [box.title() for box in dialog.findChildren(QGroupBox)]
    assert titles, "Hộp thoại cài đặt phải có các nhóm tùy chọn."
    assert all("&" not in title for title in titles)


def test_every_command_has_an_english_label(manager: TranslationManager) -> None:
    """A command added without a translation would stay Vietnamese in English."""
    from src.gui.components.menu_bar import ACTION_SPECS

    manager.apply("en")

    untranslated = [
        spec.text
        for spec in ACTION_SPECS
        if QCoreApplication.translate(MENU_CONTEXT, spec.text) == spec.text
    ]
    assert untranslated == []
