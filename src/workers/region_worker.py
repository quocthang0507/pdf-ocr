"""Read the text inside a rectangle the user drew on the page."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymupdf
from PySide6.QtCore import QObject, QRunnable, Signal

from src.constants import BlockType
from src.core.exceptions import OCREngineError, PDFOCRError
from src.core.layout_analyzer import LayoutAnalyzer
from src.core.models import (
    BoundingBox,
    OCRBlock,
    OCRLine,
    OCRPage,
    OCRTable,
    OCRWord,
)
from src.core.transcript import render_transcript
from src.engines.engine_registry import engine_session
from src.services.weights_manager import ModelWeightsManager
from src.utils.logger import logger

_POINTS_PER_INCH = 72


def native_region_text(
    path: str | Path, page_number: int, region: BoundingBox, dpi: int
) -> str:
    """Text the PDF already carries inside the region; empty when there is none.

    The region is in pixels of a page rendered at `dpi`, so it is scaled back
    to PDF points before clipping. Taking real text is instant and exact,
    which beats running a model over something that was never scanned.
    """
    source = Path(path)
    if source.suffix.lower() != ".pdf":
        return ""
    scale = _POINTS_PER_INCH / dpi
    clip = pymupdf.Rect(
        region.x1 * scale, region.y1 * scale, region.x2 * scale, region.y2 * scale
    )
    try:
        with pymupdf.open(str(source)) as pdf:
            if not 1 <= page_number <= pdf.page_count:
                return ""
            text = pdf[page_number - 1].get_text("text", clip=clip)
    except Exception as error:
        logger.warning("Không đọc được lớp chữ của vùng chọn: {}", error)
        return ""
    lines = (" ".join(line.split()) for line in str(text).splitlines())
    return "\n".join(line for line in lines if line)


class RegionSignals(QObject):
    finished = Signal(str)
    page_finished = Signal(object)
    failed = Signal(str)


@dataclass(frozen=True)
class RegionOCRResult:
    """OCR content and document identity for one selected region."""

    source_path: str
    page_number: int
    page: OCRPage


class RegionWorker(QRunnable):
    """Recognise one cropped region with the chosen engine, off the GUI thread."""

    def __init__(
        self,
        image: np.ndarray,
        region: BoundingBox,
        engine_id: str,
        device: str,
        *,
        config: Mapping[str, object] | None = None,
        weights_manager: ModelWeightsManager | None = None,
        source_path: str = "",
        page_number: int = 1,
        preferred_text: str = "",
        emit_text: bool = True,
        merge_paragraphs: bool = True,
        reading_order: bool = True,
    ) -> None:
        super().__init__()
        self.signals = RegionSignals()
        height, width = image.shape[:2]
        top, bottom = _clamp(region.y1, height), _clamp(region.y2, height)
        left, right = _clamp(region.x1, width), _clamp(region.x2, width)
        # Copy so the page image can be released while the model runs.
        self._crop = np.ascontiguousarray(image[top:bottom, left:right]).copy()
        self._left = left
        self._top = top
        self._engine_id = engine_id
        self._device = device
        self._config = dict(config or {})
        self._weights_manager = weights_manager
        self._source_path = source_path
        self._page_number = page_number
        self._preferred_text = preferred_text
        self._emit_text = emit_text
        self._merge_paragraphs = merge_paragraphs
        self._reading_order = reading_order

    def run(self) -> None:
        try:
            if self._crop.size == 0:
                raise OCREngineError("Vùng chọn nằm ngoài trang tài liệu.")
            with engine_session(
                self._engine_id,
                device=self._device,
                config=self._config,
                weights_manager=self._weights_manager,
            ) as engine:
                page = engine.recognize(self._crop, page_number=self._page_number)
        except PDFOCRError as error:
            logger.warning("Nhận diện vùng chọn thất bại: {}", error)
            self.signals.failed.emit(str(error))
            return
        except Exception:
            logger.exception("Nhận diện vùng chọn gặp lỗi không mong đợi.")
            self.signals.failed.emit(OCREngineError.default_message)
            return
        if self._emit_text:
            # Engines report one block per line; rebuild paragraphs and column order.
            tidy = LayoutAnalyzer().analyze(
                page,
                merge_paragraphs=self._merge_paragraphs,
                reading_order=self._reading_order,
            )
            text = self._preferred_text or render_transcript(tidy).strip()
            self.signals.finished.emit(text)
        if page.tables:
            tables = tuple(
                table.with_updates(
                    bbox=_translate_box(table.bbox, self._left, self._top)
                )
                for table in page.tables
            )
            self.signals.page_finished.emit(
                RegionOCRResult(
                    self._source_path,
                    self._page_number,
                    page.with_updates(tables=tables),
                )
            )


def _clamp(value: float, limit: int) -> int:
    return max(0, min(int(round(value)), limit))


def _translate_box(box: BoundingBox, left: int, top: int) -> BoundingBox:
    polygon = tuple((x + left, y + top) for x, y in box.polygon)
    return BoundingBox(
        box.x1 + left,
        box.y1 + top,
        box.x2 + left,
        box.y2 + top,
        polygon,
    )


def _same_table_region(first: OCRTable, second: OCRTable) -> bool:
    """Treat mostly overlapping table boxes as an existing detection."""
    left = max(first.bbox.x1, second.bbox.x1)
    top = max(first.bbox.y1, second.bbox.y1)
    right = min(first.bbox.x2, second.bbox.x2)
    bottom = min(first.bbox.y2, second.bbox.y2)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    smaller_area = min(
        first.bbox.width * first.bbox.height,
        second.bbox.width * second.bbox.height,
    )
    return smaller_area > 0 and intersection / smaller_area >= 0.75


def merge_region_tables(
    page: OCRPage, region_tables: Sequence[OCRTable]
) -> tuple[OCRPage, int]:
    """Append newly discovered region tables and their block lines to a page."""
    tables = list(page.tables)
    blocks = list(page.blocks)
    added = 0
    for table in region_tables:
        if any(_same_table_region(table, existing) for existing in tables):
            continue
        tables.append(table)
        row_lines = tuple(
            OCRLine(
                words=(OCRWord(" | ".join(row), table.bbox),),
                bbox=table.bbox,
            )
            for row in table.rows
            if any(cell.strip() for cell in row)
        )
        blocks.append(
            OCRBlock(
                lines=row_lines,
                bbox=table.bbox,
                block_type=BlockType.TABLE,
                reading_order=len(blocks),
            )
        )
        added += 1
    if not added:
        return page, 0
    updated = page.with_updates(blocks=tuple(blocks), tables=tuple(tables))
    return LayoutAnalyzer().analyze(updated, merge_paragraphs=False), added
