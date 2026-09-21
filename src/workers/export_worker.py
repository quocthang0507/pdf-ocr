"""Write an export off the GUI thread, and map a save dialog choice to a format."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

import src.exporters  # noqa: F401 - registers the built-in formats
from src.core.exceptions import ExportError, PDFOCRError
from src.core.models import OCRDocument
from src.exporters.exporter_registry import ExporterRegistry
from src.utils.logger import logger

# The formats people reach for most come first; the first is the default.
_PREFERRED_ORDER = ("docx", "pdf", "xlsx", "markdown", "text", "json")


def export_filters() -> list[tuple[str, str]]:
    """(file dialog filter, format id) for every registered exporter."""
    formats = ExporterRegistry.available()
    ranked = sorted(
        formats,
        key=lambda item: (
            (
                _PREFERRED_ORDER.index(item.format_id)
                if item.format_id in _PREFERRED_ORDER
                else len(_PREFERRED_ORDER)
            ),
            item.name,
        ),
    )
    return [
        (
            f"{item.name} ({' '.join(f'*{ext}' for ext in item.extensions)})",
            item.format_id,
        )
        for item in ranked
    ]


def resolve_export_target(selected: str, chosen_filter: str) -> tuple[str, Path]:
    """Pick the format from the typed extension, else from the chosen filter."""
    path = Path(selected)
    for item in ExporterRegistry.available():
        if path.suffix.lower() in item.extensions:
            return item.format_id, path
    filters = dict(export_filters())
    format_id = filters.get(chosen_filter) or export_filters()[0][1]
    extension = ExporterRegistry.describe(format_id).extensions[0]
    return format_id, path.with_name(path.name + extension)


class ExportSignals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class ExportWorker(QRunnable):
    """One export. Every path ends in a signal; nothing escapes the thread pool."""

    def __init__(
        self, document: OCRDocument, format_id: str, destination: str | Path
    ) -> None:
        super().__init__()
        self.signals = ExportSignals()
        self._document = document
        self._format_id = format_id
        self._destination = Path(destination)

    def run(self) -> None:
        try:
            exporter = ExporterRegistry.get(self._format_id)
            written = exporter.export(self._document, self._destination)
        except PDFOCRError as error:
            logger.warning("Xuất tài liệu thất bại: {}", error)
            self.signals.failed.emit(str(error))
            return
        except Exception:
            logger.exception("Xuất tài liệu gặp lỗi không mong đợi.")
            self.signals.failed.emit(ExportError.default_message)
            return
        logger.info("Đã xuất tài liệu: {}", written)
        self.signals.finished.emit(str(written))
