"""Normalize provider line geometry into the common immutable OCR tree."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from importlib import import_module
from typing import Any, cast

from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRTable, OCRWord

LineResult = tuple[Sequence[Sequence[float]], str, float]


def as_pil_image(image: object) -> Any:
    """Convert RGB/greyscale array inputs for backends that require Pillow."""
    pil_image = import_module("PIL.Image")
    if isinstance(image, pil_image.Image):
        return image.convert("RGB")
    if hasattr(image, "shape"):
        return pil_image.fromarray(image).convert("RGB")
    raise ValueError("Ảnh OCR phải là PIL Image hoặc mảng NumPy.")


def image_size(image: object) -> tuple[int, int]:
    shape = getattr(image, "shape", None)
    if isinstance(shape, tuple) and len(shape) >= 2:
        height, width = shape[:2]
    else:
        size = getattr(image, "size", None)
        if not isinstance(size, tuple) or len(size) != 2:
            raise ValueError("Ảnh OCR không cung cấp kích thước hợp lệ.")
        width, height = size
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        raise ValueError("Ảnh OCR phải có chiều rộng và chiều cao dương.")
    return width, height


def rectangle_polygon(width: int, height: int) -> tuple[tuple[float, float], ...]:
    return ((0, 0), (width, 0), (width, height), (0, height))


def normalize_polygon(points: object) -> tuple[tuple[float, float], ...]:
    if isinstance(points, (str, bytes)):
        raise ValueError("Tọa độ OCR phải là một dãy điểm.")
    try:
        values = list(cast(Iterable[object], points))
    except TypeError as error:
        raise ValueError("Tọa độ OCR phải là một dãy điểm.") from error
    if len(values) == 4 and all(isinstance(value, (int, float)) for value in values):
        x1, y1, x2, y2 = values
        points = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    else:
        points = values
    polygon: list[tuple[float, float]] = []
    for point in points:
        try:
            coordinates = list(cast(Iterable[object], point))
        except TypeError as error:
            raise ValueError("Mỗi điểm OCR phải có hai tọa độ.") from error
        if len(coordinates) != 2:
            raise ValueError("Mỗi điểm OCR phải có hai tọa độ.")
        x, y = coordinates
        if isinstance(x, bool) or isinstance(y, bool):
            raise ValueError("Tọa độ OCR không hợp lệ.")
        polygon.append((max(0.0, float(str(x))), max(0.0, float(str(y)))))
    if len(polygon) < 3:
        raise ValueError("Vùng OCR phải có ít nhất ba điểm.")
    return tuple(polygon)


def safe_confidence(value: object) -> float:
    try:
        confidence = float(str(value))
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(confidence):
        return 0.0
    return min(1.0, max(0.0, confidence))


def build_page(
    image: object,
    page_number: int,
    lines: Iterable[LineResult],
    tables: Iterable[OCRTable] = (),
) -> OCRPage:
    width, height = image_size(image)
    blocks: list[OCRBlock] = []
    for reading_order, (points, text, confidence) in enumerate(lines):
        if not isinstance(text, str) or not text.strip():
            continue
        bbox = BoundingBox.from_polygon(normalize_polygon(points))
        word = OCRWord(text.strip(), bbox, safe_confidence(confidence))
        line = OCRLine(words=(word,), bbox=bbox)
        blocks.append(OCRBlock(lines=(line,), bbox=bbox, reading_order=reading_order))
    return OCRPage(
        page_number=page_number,
        width=width,
        height=height,
        blocks=tuple(blocks),
        tables=tuple(tables),
    )
