"""Desktop application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from src.config import ConfigManager
from src.core.exceptions import PDFOCRError
from src.gui.i18n import TranslationManager
from src.gui.main_window import APPLICATION_NAME, ORGANIZATION_NAME, MainWindow
from src.gui.styles.style_manager import StyleManager
from src.services.weights_manager import ModelWeightsManager
from src.utils.logger import configure_logging, logger


def main(argv: list[str] | None = None) -> int:
    """Start the GUI, redirecting model caches before any AI library loads."""
    configure_logging()
    application = QApplication(argv if argv is not None else sys.argv)
    application.setOrganizationName(ORGANIZATION_NAME)
    application.setApplicationName(APPLICATION_NAME)
    _apply_saved_appearance(application)
    window = MainWindow()
    _prepare_weights_storage(window)
    window.show()
    return application.exec()


def _apply_saved_appearance(application: QApplication) -> None:
    """Set language and theme before the first window appears, never after."""
    try:
        preferences = ConfigManager().load()
        TranslationManager(application).apply(preferences.language)
        StyleManager(application).apply(preferences.theme)
    except (PDFOCRError, ValueError, RuntimeError) as error:
        logger.warning("Không áp dụng được giao diện đã lưu: {}", error)


def _prepare_weights_storage(window: MainWindow) -> None:
    try:
        ModelWeightsManager()
    except PDFOCRError as error:
        logger.warning("Không chuẩn bị được thư mục weights: {}", error)
        QMessageBox.warning(window, "Thư mục weights", str(error))


if __name__ == "__main__":
    raise SystemExit(main())
