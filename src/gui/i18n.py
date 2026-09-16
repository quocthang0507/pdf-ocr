"""Interface languages: Vietnamese is the source language, English a catalogue."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTranslator

from src.constants import DEFAULT_LANGUAGE, LANGUAGE_NAMES
from src.utils.logger import logger

MENU_CONTEXT = "MenuBar"


def translations_dir() -> Path:
    """Locate the bundled catalogues next to this module, frozen builds included."""
    return Path(__file__).with_name("translations")


def available_languages() -> tuple[str, ...]:
    return tuple(LANGUAGE_NAMES)


class TranslationManager:
    """Stateful translator holder; only one catalogue is installed at a time.

    Vietnamese needs no catalogue because the source strings are already
    Vietnamese, so a missing or damaged file simply falls back to it.
    """

    _translator: QTranslator | None = None
    _language: str = DEFAULT_LANGUAGE

    def __init__(self, application: QCoreApplication | None = None) -> None:
        resolved = application or QCoreApplication.instance()
        if resolved is None:
            raise RuntimeError("Cần khởi tạo QApplication trước khi đổi ngôn ngữ.")
        self._application = resolved

    @property
    def current_language(self) -> str:
        return type(self)._language

    def apply(self, language: str) -> str:
        """Install a catalogue and report the language actually in use."""
        if language not in LANGUAGE_NAMES:
            raise ValueError("Ngôn ngữ giao diện không được hỗ trợ.")
        self._remove_current()
        if language == DEFAULT_LANGUAGE:
            return self._remember(DEFAULT_LANGUAGE)
        translator = QTranslator()
        catalogue = translations_dir() / f"{language}.qm"
        if not translator.load(
            str(catalogue)
        ) or not self._application.installTranslator(translator):
            logger.warning("Thiếu tệp dịch '{}'; dùng tiếng Việt.", language)
            return self._remember(DEFAULT_LANGUAGE)
        type(self)._translator = translator
        return self._remember(language)

    def _remove_current(self) -> None:
        translator = type(self)._translator
        if translator is not None:
            self._application.removeTranslator(translator)
            type(self)._translator = None

    @staticmethod
    def _remember(language: str) -> str:
        TranslationManager._language = language
        logger.info("Đã áp dụng ngôn ngữ giao diện '{}'.", language)
        return language


def translate_menu(text: str) -> str:
    """Translate one command label through the shared menu context."""
    return QCoreApplication.translate(MENU_CONTEXT, text)


__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGE_NAMES",
    "MENU_CONTEXT",
    "TranslationManager",
    "available_languages",
    "translate_menu",
    "translations_dir",
]
