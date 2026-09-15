"""Desktop application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from src.core.exceptions import PDFOCRError
from src.gui.main_window import APPLICATION_NAME, ORGANIZATION_NAME, MainWindow
from src.services.weights_manager import ModelWeightsManager
from src.utils.logger import configure_logging, logger


def main(argv: list[str] | None = None) -> int:
    """Start the GUI, redirecting model caches before any AI library loads."""
    configure_logging()
    application = QApplication(argv if argv is not None else sys.argv)
    application.setOrganizationName(ORGANIZATION_NAME)
    application.setApplicationName(APPLICATION_NAME)
    window = MainWindow()
    _prepare_weights_storage(window)
    window.show()
    return application.exec()


def _prepare_weights_storage(window: MainWindow) -> None:
    try:
        ModelWeightsManager()
    except PDFOCRError as error:
        logger.warning("Không chuẩn bị được thư mục weights: {}", error)
        QMessageBox.warning(window, "Thư mục weights", str(error))


if __name__ == "__main__":
    raise SystemExit(main())
