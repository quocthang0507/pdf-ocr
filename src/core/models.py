"""Immutable OCR document tree, with pixel geometry and JSON-safe round trips."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, fields, replace
from enum import Enum
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

from src.constants import LOW_CONFIDENCE_THRESHOLD, BlockType, PageType

_LIST_MARKER_PATTERN = re.compile(r"^([•\-\*\+–—]|\d+[\.\)]|[a-zA-Z][\.\)])\s+")

ModelT = TypeVar("ModelT", bound="ImmutableModel")
Point = tuple[float, float]


def _number(value: object, name: str, minimum: float = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} phải là số hữu hạn.")
    try:
        finite = math.isfinite(value)
    except OverflowError as error:
        raise ValueError(f"{name} vượt quá miền tọa độ hỗ trợ.") from error
    if not finite:
        raise ValueError(f"{name} phải là số hữu hạn.")
    if value < minimum:
        raise ValueError(f"{name} phải lớn hơn hoặc bằng {minimum}.")


def _integer(value: object, name: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} phải là số nguyên lớn hơn hoặc bằng {minimum}.")


def _text(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} phải là chuỗi văn bản.")


def _freeze_children(model: ImmutableModel, name: str, child_type: type) -> None:
    children = getattr(model, name)
    if not isinstance(children, (tuple, list)) or any(
        not isinstance(child, child_type) for child in children
    ):
        raise ValueError(f"{name} phải chứa các đối tượng {child_type.__name__}.")
    object.__setattr__(model, name, tuple(children))


def _encode(value: Any) -> Any:
    if isinstance(value, ImmutableModel):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


def _decode(annotation: Any, value: Any) -> Any:
    if get_origin(annotation) is tuple:
        if not isinstance(value, (tuple, list)):
            raise ValueError("Danh sách dữ liệu không hợp lệ.")
        arguments = get_args(annotation)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return tuple(_decode(arguments[0], item) for item in value)
        if len(value) != len(arguments):
            raise ValueError("Số phần tử tọa độ không hợp lệ.")
        return tuple(
            _decode(kind, item) for kind, item in zip(arguments, value, strict=True)
        )
    if isinstance(annotation, type):
        if issubclass(annotation, ImmutableModel):
            return annotation.from_dict(value)
        if issubclass(annotation, Enum):
            return annotation(value)
    return value


@dataclass(frozen=True)
class ImmutableModel:
    """Shared serialization and validated functional copying for domain values."""

    def with_updates(self: ModelT, **changes: Any) -> ModelT:
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            field.name: _encode(getattr(self, field.name)) for field in fields(self)
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_dict(cls: type[ModelT], payload: dict[str, Any]) -> ModelT:
        if not isinstance(payload, dict):
            raise ValueError("Dữ liệu mô hình phải là một JSON object.")
        annotations = get_type_hints(cls)
        if set(payload) - {field.name for field in fields(cls)}:
            raise ValueError("Dữ liệu mô hình chứa trường không được hỗ trợ.")
        try:
            return cls(
                **{
                    name: _decode(annotations[name], value)
                    for name, value in payload.items()
                }
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"Dữ liệu {cls.__name__} không hợp lệ.") from error

    @classmethod
    def from_json(cls: type[ModelT], payload: str) -> ModelT:
        return cls.from_dict(json.loads(payload))


def _points(polygon: object) -> tuple[Point, ...]:
    if not isinstance(polygon, (list, tuple)) or len(polygon) < 3:
        raise ValueError("Polygon phải có ít nhất ba điểm.")
    result: list[Point] = []
    for point in polygon:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise ValueError("Mỗi điểm polygon phải gồm hai tọa độ.")
        _number(point[0], "x")
        _number(point[1], "y")
        result.append((point[0], point[1]))
    return tuple(result)


@dataclass(frozen=True)
class BoundingBox(ImmutableModel):
    """Axis-aligned pixel envelope; optional polygon retains rotated geometry."""

    x1: float
    y1: float
    x2: float
    y2: float
    polygon: tuple[Point, ...] = ()

    def __post_init__(self) -> None:
        for name in ("x1", "y1", "x2", "y2"):
            _number(getattr(self, name), name)
        if self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError("Tọa độ cuối phải nằm sau tọa độ đầu của bounding box.")
        if not isinstance(self.polygon, (tuple, list)):
            raise ValueError("Polygon phải là danh sách tọa độ.")
        polygon = _points(self.polygon) if self.polygon else ()
        if any(
            not (self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2)
            for x, y in polygon
        ):
            raise ValueError("Polygon phải nằm trong bounding box.")
        object.__setattr__(self, "polygon", polygon)

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @classmethod
    def from_polygon(cls, polygon: tuple[Point, ...]) -> BoundingBox:
        points = _points(polygon)
        xs, ys = zip(*points, strict=True)
        return cls(min(xs), min(ys), max(xs), max(ys), points)


def _box(bbox: BoundingBox) -> None:
    if not isinstance(bbox, BoundingBox):
        raise ValueError("bbox phải là đối tượng BoundingBox.")


@dataclass(frozen=True)
class OCRWord(ImmutableModel):
    text: str
    bbox: BoundingBox
    confidence: float = 1.0

    def __post_init__(self) -> None:
        _text(self.text, "text")
        _box(self.bbox)
        _number(self.confidence, "confidence")
        if self.confidence > 1:
            raise ValueError("Confidence phải nằm trong khoảng 0 đến 1.")

    @property
    def is_low_confidence(self) -> bool:
        return self.confidence < LOW_CONFIDENCE_THRESHOLD


@dataclass(frozen=True)
class OCRLine(ImmutableModel):
    words: tuple[OCRWord, ...]
    bbox: BoundingBox
    font_name: str | None = None
    font_size: float | None = None

    def __post_init__(self) -> None:
        _freeze_children(self, "words", OCRWord)
        _box(self.bbox)
        if self.font_name is not None:
            _text(self.font_name, "font_name")
        if self.font_size is not None:
            _number(self.font_size, "font_size")
            if self.font_size == 0:
                raise ValueError("Cỡ chữ phải lớn hơn không.")

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)


@dataclass(frozen=True)
class OCRBlock(ImmutableModel):
    lines: tuple[OCRLine, ...]
    bbox: BoundingBox
    block_type: BlockType = BlockType.TEXT
    reading_order: int = 0

    def __post_init__(self) -> None:
        _freeze_children(self, "lines", OCRLine)
        _box(self.bbox)
        object.__setattr__(self, "block_type", BlockType(self.block_type))
        _integer(self.reading_order, "reading_order")

    @property
    def text(self) -> str:
        if not self.lines:
            return ""
        if len(self.lines) == 1:
            return self.lines[0].text
        parts: list[str] = [self.lines[0].text]
        for line_index in range(1, len(self.lines)):
            prev_line_text = self.lines[line_index - 1].text.rstrip()
            curr_line_text = self.lines[line_index].text.lstrip()
            if prev_line_text.endswith(":") or bool(
                _LIST_MARKER_PATTERN.match(curr_line_text)
            ):
                parts.append("\n" + curr_line_text)
            elif prev_line_text.endswith("-") and not prev_line_text.endswith(" -"):
                parts.append(curr_line_text)
            else:
                parts.append(" " + curr_line_text)
        return "".join(parts)


@dataclass(frozen=True)
class TableCellSpan(ImmutableModel):
    """Logical position and extent of one merged table cell."""

    row: int
    column: int
    row_span: int = 1
    column_span: int = 1

    def __post_init__(self) -> None:
        _integer(self.row, "row")
        _integer(self.column, "column")
        _integer(self.row_span, "row_span", 1)
        _integer(self.column_span, "column_span", 1)


@dataclass(frozen=True)
class OCRTable(ImmutableModel):
    """Rectangular immutable text matrix with optional merged-cell metadata."""

    rows: tuple[tuple[str, ...], ...]
    bbox: BoundingBox
    merged_cells: tuple[TableCellSpan, ...] = ()

    def __post_init__(self) -> None:
        _box(self.bbox)
        if not isinstance(self.rows, (tuple, list)):
            raise ValueError("Bảng phải là danh sách hàng.")
        for row in self.rows:
            if not isinstance(row, (tuple, list)):
                raise ValueError("Mỗi hàng phải là danh sách ô.")
            for cell in row:
                _text(cell, "cell")
        rows = tuple(tuple(row) for row in self.rows)
        if rows and any(len(row) != len(rows[0]) for row in rows):
            raise ValueError("Các hàng trong bảng phải có cùng số cột.")
        object.__setattr__(self, "rows", rows)
        _freeze_children(self, "merged_cells", TableCellSpan)
        row_count = len(rows)
        column_count = len(rows[0]) if rows else 0
        if any(
            span.row + span.row_span > row_count
            or span.column + span.column_span > column_count
            for span in self.merged_cells
        ):
            raise ValueError("Ô gộp phải nằm trong phạm vi bảng.")


@dataclass(frozen=True)
class OCRPage(ImmutableModel):
    """One-based page number and dimensions in the same pixel space as its boxes."""

    page_number: int
    width: float
    height: float
    blocks: tuple[OCRBlock, ...] = ()
    tables: tuple[OCRTable, ...] = ()
    page_type: PageType = PageType.SCANNED
    dpi: int = 300

    def __post_init__(self) -> None:
        _integer(self.page_number, "page_number", 1)
        _integer(self.dpi, "dpi", 1)
        _number(self.width, "width")
        _number(self.height, "height")
        if self.width == 0 or self.height == 0:
            raise ValueError("Kích thước trang phải lớn hơn không.")
        _freeze_children(self, "blocks", OCRBlock)
        _freeze_children(self, "tables", OCRTable)
        object.__setattr__(self, "page_type", PageType(self.page_type))


@dataclass(frozen=True)
class OCRDocument(ImmutableModel):
    pages: tuple[OCRPage, ...] = ()
    source_path: str = ""
    title: str = ""

    def __post_init__(self) -> None:
        _freeze_children(self, "pages", OCRPage)
        _text(self.source_path, "source_path")
        _text(self.title, "title")
