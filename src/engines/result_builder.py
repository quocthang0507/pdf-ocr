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


Box = tuple[int, int, int, int]

#: A detached mark is at most this share of the height of its host line.
_MARK_RATIO = 0.45
#: How far (as a share of the host line height) a mark may float from it.
_MARK_REACH = 0.5


def _vertical_gap(a: Box, b: Box) -> int:
    top = max(a[1], b[1])
    bottom = min(a[1] + a[3], b[1] + b[3])
    return max(0, top - bottom)


def _horizontal_overlap(a: Box, b: Box) -> int:
    return min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])


def _union(a: Box, b: Box) -> Box:
    x1, y1 = min(a[0], b[0]), min(a[1], b[1])
    x2 = max(a[0] + a[2], b[0] + b[2])
    y2 = max(a[1] + a[3], b[1] + b[3])
    return (x1, y1, x2 - x1, y2 - y1)


#: A box taller than this many glyph heights may hold several glued lines.
_MULTI_LINE_RATIO = 2.6
#: Each piece cut from a glued box must be at least this many glyphs tall.
_MIN_LINE_RATIO = 1.2
#: A valley row holds at most this share of the ink peak on either side.
_VALLEY_RATIO = 0.3


def _glyph_height(text_only: np.ndarray) -> float:
    """Median height of glyph-sized connected components (letters, digits)."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(text_only, connectivity=8)
    heights = [
        int(stats[index, cv2.CC_STAT_HEIGHT])
        for index in range(1, count)
        if stats[index, cv2.CC_STAT_AREA] >= 12
        and stats[index, cv2.CC_STAT_HEIGHT] >= 4
    ]
    return float(np.median(heights)) if heights else 0.0


def _split_rows(profile: np.ndarray, min_piece: float) -> list[int]:
    """Rows at which to cut a box holding several glued text lines.

    A row is a valley when its ink is a small share of the densest row on
    *both* sides, so a short line ("tăng") above a long one still separates.
    Pieces are kept at least `min_piece` rows tall, which keeps the accent
    band of a single line from being cut off.
    """
    smooth = np.convolve(profile.astype(float), np.ones(3) / 3, mode="same")
    margin = max(1, int(np.ceil(min_piece)))

    def cuts_between(start: int, stop: int) -> list[int]:
        if stop - start < 2 * margin:
            return []
        segment = smooth[start:stop]
        left_peak = np.maximum.accumulate(segment)
        right_peak = np.maximum.accumulate(segment[::-1])[::-1]
        best: tuple[float, int] | None = None
        for row in range(margin, len(segment) - margin + 1):
            shoulder = min(left_peak[row - 1], right_peak[row])
            if shoulder <= 0:
                continue
            score = segment[row] / shoulder
            if score <= _VALLEY_RATIO and (best is None or score < best[0]):
                best = (score, row)
        if best is None:
            return []
        cut = start + best[1]
        return [*cuts_between(start, cut), cut, *cuts_between(cut, stop)]

    return cuts_between(0, len(smooth))


def _tight_box(mask: np.ndarray, x: int, y: int) -> Box | None:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    return (
        x + int(xs.min()),
        y + int(ys.min()),
        int(xs.max() - xs.min()) + 1,
        int(ys.max() - ys.min()) + 1,
    )


def split_touching_lines(text_only: np.ndarray, boxes: list[Box]) -> list[Box]:
    """Separate text lines that tight leading glued into one contour.

    When descenders of one line touch the accents of the next, both lines end
    up in one box and a line recogniser only reads the first of them, so text
    silently disappears. Boxes much taller than a glyph are cut at the
    horizontal ink valleys between lines.
    """
    glyph = _glyph_height(text_only)
    if glyph <= 0:
        return list(boxes)
    result: list[Box] = []
    for x, y, w, h in boxes:
        if h < glyph * _MULTI_LINE_RATIO:
            result.append((x, y, w, h))
            continue
        region = text_only[y : y + h, x : x + w]
        cuts = _split_rows((region > 0).sum(axis=1), glyph * _MIN_LINE_RATIO)
        if not cuts:
            result.append((x, y, w, h))
            continue
        edges = [0, *cuts, h]
        for top, bottom in zip(edges, edges[1:], strict=False):
            piece = _tight_box(region[top:bottom], x, y + top)
            if piece is not None:
                result.append(piece)
    return result


def _typical_height(boxes: list[Box]) -> int:
    """Width-weighted median height: wide text lines outweigh narrow marks."""
    ordered = sorted(boxes, key=lambda box: box[3])
    half = sum(box[2] for box in ordered) / 2
    running = 0
    for box in ordered:
        running += box[2]
        if running >= half:
            return box[3]
    return ordered[-1][3]


def _host_for(mark: Box, boxes: list[Box], typical: int) -> int | None:
    """Index of the nearest much taller line the mark overlaps horizontally."""
    if mark[3] > typical * _MARK_RATIO:
        return None
    best: tuple[int, int] | None = None
    for index, line in enumerate(boxes):
        if mark[3] > line[3] * _MARK_RATIO:
            continue
        if _horizontal_overlap(mark, line) <= 0:
            continue
        gap = _vertical_gap(mark, line)
        if gap <= line[3] * _MARK_REACH and (best is None or gap < best[1]):
            best = (index, gap)
    return None if best is None else best[0]


def merge_detached_marks(boxes: list[Box]) -> list[Box]:
    """Fold detached diacritics back into the text line they belong to.

    Vietnamese tone marks and circumflexes sit above or below the letter body;
    at scan resolution they form their own thin contours, which a line
    recogniser would otherwise read as garbage lines (``0100``, ``STEUTED``).
    """
    if len(boxes) < 2:
        return list(boxes)
    typical = _typical_height(boxes)
    hosts = {index: _host_for(box, boxes, typical) for index, box in enumerate(boxes)}
    marks = {index for index, host in hosts.items() if host is not None}
    merged = {index: box for index, box in enumerate(boxes) if index not in marks}
    for index in sorted(marks):
        host = hosts[index]
        if host is None or host in marks:
            # A mark hosted by another mark is too faint to be text: keep it.
            merged[index] = boxes[index]
            continue
        merged[host] = _union(merged[host], boxes[index])
    return [merged[index] for index in sorted(merged)]


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

    boxes = split_touching_lines(text_only, boxes)
    boxes = merge_detached_marks(boxes)
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
