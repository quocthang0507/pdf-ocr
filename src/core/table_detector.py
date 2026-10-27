"""Find ruled tables in a page image and lay out their cells as a grid.

Engines such as VietOCR, EasyOCR and Surya return text lines only, so tables
were read as loose lines, column by column. Ruled tables (the common case in
Vietnamese administrative and financial documents) can be recovered from the
ruling lines alone; each enclosed white area is a cell, and merged cells fall
out of the grid boundaries they span.
"""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from src.core.models import BoundingBox
from src.core.table_extractor import DetectedTableCell

#: A ruling line must run at least this share of the page width or height.
_LINE_SHARE = 1 / 40
#: Grid boundaries closer than this share of the median cell size merge.
_SNAP_SHARE = 0.25
#: A table needs at least this many rows and columns.
_MIN_GRID = 2


def _ink_mask(image: np.ndarray) -> np.ndarray:
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    size = max(15, (min(gray.shape[:2]) // 60) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    flattened = cv2.divide(gray, np.maximum(background, 1), scale=255)
    _, mask = cv2.threshold(flattened, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return mask


def _ruling_lines(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    height, width = mask.shape[:2]
    horizontal = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(20, int(width * _LINE_SHARE)), 1)
        ),
    )
    vertical = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (1, max(20, int(height * _LINE_SHARE)))
        ),
    )
    return horizontal, vertical


def _snap(values: Sequence[float], tolerance: float) -> list[float]:
    """Cluster nearly equal coordinates into shared grid boundaries."""
    snapped: list[float] = []
    for value in sorted(values):
        if snapped and value - snapped[-1] <= tolerance:
            continue
        snapped.append(value)
    return snapped


def _index(boundaries: Sequence[float], value: float) -> int:
    return int(np.argmin([abs(boundary - value) for boundary in boundaries]))


def _cells_in(
    grid: np.ndarray, region: tuple[int, int, int, int]
) -> list[DetectedTableCell]:
    x, y, w, h = region
    inside = cv2.bitwise_not(grid[y : y + h, x : x + w])
    count, _, stats, _ = cv2.connectedComponentsWithStats(inside, connectivity=4)
    boxes: list[tuple[int, int, int, int]] = []
    for label in range(1, count):
        cx, cy, cw, ch, area = (int(value) for value in stats[label])
        touches_edge = cx <= 0 or cy <= 0 or cx + cw >= w or cy + ch >= h
        if touches_edge or cw < 8 or ch < 8 or area < 0.5 * cw * ch:
            continue
        boxes.append((cx, cy, cw, ch))
    if len(boxes) < _MIN_GRID * _MIN_GRID:
        return []
    typical = float(np.median([min(cw, ch) for _, _, cw, ch in boxes]))
    tolerance = max(3.0, typical * _SNAP_SHARE)
    rows = _snap(
        [by for _, by, _, _ in boxes] + [by + bh for _, by, _, bh in boxes], tolerance
    )
    cols = _snap(
        [bx for bx, _, _, _ in boxes] + [bx + bw for bx, _, bw, _ in boxes], tolerance
    )
    cells: list[DetectedTableCell] = []
    taken: set[tuple[int, int]] = set()
    for bx, by, bw, bh in sorted(boxes, key=lambda box: (box[1], box[0])):
        top, bottom = _index(rows, by), _index(rows, by + bh)
        left, right = _index(cols, bx), _index(cols, bx + bw)
        if bottom <= top or right <= left:
            continue
        span = {(r, c) for r in range(top, bottom) for c in range(left, right)}
        if span & taken:
            continue
        taken |= span
        cells.append(
            DetectedTableCell(
                row=top,
                column=left,
                bbox=BoundingBox(x + bx, y + by, x + bx + bw, y + by + bh),
                row_span=bottom - top,
                column_span=right - left,
            )
        )
    row_count = max(cell.row + cell.row_span for cell in cells)
    column_count = max(cell.column + cell.column_span for cell in cells)
    if row_count < _MIN_GRID or column_count < _MIN_GRID:
        return []
    if len(taken) < row_count * column_count:
        return []  # holes: not a clean grid, leave it to the text flow
    return cells


def _close_at_page_edges(grid: np.ndarray, margin: int = 3) -> None:
    """Draw the frame line a crop cut off where the grid meets the page edge.

    Border removal may trim a table's outer rule when it sits on the image
    edge, which left the outermost cells open and the whole column unseen.
    """
    height, width = grid.shape[:2]
    for strip, horizontal_side, index in (
        (grid[:margin, :], True, 0),
        (grid[height - margin :, :], True, height - 1),
        (grid[:, :margin], False, 0),
        (grid[:, width - margin :], False, width - 1),
    ):
        hits = np.flatnonzero(strip.any(axis=0 if horizontal_side else 1))
        if hits.size < 2:
            continue
        start, end = int(hits.min()), int(hits.max())
        if horizontal_side:
            grid[index, start : end + 1] = 255
        else:
            grid[start : end + 1, index] = 255


def detect_ruled_tables(image: np.ndarray) -> list[list[DetectedTableCell]]:
    """Cells of every ruled table on the page, one list per table."""
    if not isinstance(image, np.ndarray) or image.size == 0:
        return []
    mask = _ink_mask(image)
    horizontal, vertical = _ruling_lines(mask)
    if not horizontal.any() or not vertical.any():
        return []
    grid = cv2.dilate(
        cv2.bitwise_or(horizontal, vertical),
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
    )
    _close_at_page_edges(grid)
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tables: list[list[DetectedTableCell]] = []
    for contour in contours:
        x, y, w, h = (int(value) for value in cv2.boundingRect(contour))
        if w < 40 or h < 20:
            continue
        region = (x, y, w, h)
        cells = _cells_in(grid, region)
        if cells:
            tables.append(cells)
    tables.sort(key=lambda cells: min(cell.bbox.y1 for cell in cells))
    return tables
