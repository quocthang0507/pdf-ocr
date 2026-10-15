"""Normalize provider line geometry into the common immutable OCR tree."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from importlib import import_module
from typing import Any, cast

import cv2
import numpy as np

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


def to_grayscale(image: object) -> np.ndarray | None:
    if isinstance(image, np.ndarray):
        if image.ndim == 3 and image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
        if image.ndim == 3 and image.shape[2] == 3:
            return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        if image.ndim == 2:
            return image
        return None
    pil_image = as_pil_image(image).convert("L")
    return np.array(pil_image)


def segment_lines(image: object) -> list[tuple[int, int, int, int]]:
    """Segment an image into horizontal text line bounding boxes (x, y, w, h)."""
    gray = to_grayscale(image)
    if gray is None or gray.size == 0:
        return []

    height, width = gray.shape[:2]
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    h_rule = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, int(width * 0.03)), 1))
    v_rule = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, int(height * 0.02))))
    h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_rule, iterations=2)
    v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_rule, iterations=2)
    text_only = cv2.subtract(thresh, cv2.add(h_lines, v_lines))

    kw = max(20, int(width * 0.02))
    kh = max(2, int(height * 0.001))
    line_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, kh))
    dilated = cv2.dilate(text_only, line_kernel, iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int]] = []
    min_h = max(8, int(height * 0.003))
    max_h = max(200, int(height * 0.1))
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw > 12 and min_h <= bh <= max_h:
            boxes.append((int(x), int(y), int(bw), int(bh)))

    y_band = max(15, int(height * 0.006))
    boxes.sort(key=lambda box: (round(box[1] / y_band) * y_band, box[0]))
    return boxes


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
