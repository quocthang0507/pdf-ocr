"""Pure transcript layout helpers: spans, column counting, and line joining."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.constants import BlockType
from src.core.models import OCRBlock, OCRPage
from src.core.transcript import BLOCK_SEPARATOR, table_for_block, table_transcript

_LIST_MARKER_REGEX = re.compile(r"^([•\-\*\+–—]|\d+[\.\)]|[a-zA-Z][\.\)])\s+")


@dataclass(frozen=True)
class TextSpan:
    """Half-open character range of one recognised element in the transcript."""

    start: int
    end: int

    def contains(self, position: int) -> bool:
        return self.start <= position <= self.end


def render_page_transcript(
    page: OCRPage,
    *,
    confidence_threshold: float | None = None,
) -> tuple[str, tuple[TextSpan, ...], tuple[TextSpan, ...]]:
    """Lay out the transcript once, recording where each block and word landed."""
    parts: list[str] = []
    blocks: list[TextSpan] = []
    uncertain: list[TextSpan] = []
    cursor = 0
    for index, block in enumerate(page.blocks):
        if index:
            parts.append(BLOCK_SEPARATOR)
            cursor += len(BLOCK_SEPARATOR)
        start = cursor
        table_text = table_transcript(page, index)
        if table_text is not None:
            parts.append(table_text)
            cursor += len(table_text)
        else:
            cursor = _render_block_lines(
                block,
                parts,
                cursor,
                uncertain,
                confidence_threshold=confidence_threshold,
            )
        blocks.append(TextSpan(start, cursor))
    return "".join(parts), tuple(blocks), tuple(uncertain)


def find_search_spans(text: str, query: str) -> tuple[TextSpan, ...]:
    """Find all case-insensitive occurrences of `query` in `text`."""
    clean = query.strip()
    if not clean or not text:
        return ()
    lower_text = text.lower()
    lower_query = clean.lower()
    spans: list[TextSpan] = []
    pos = 0
    q_len = len(clean)
    while True:
        idx = lower_text.find(lower_query, pos)
        if idx < 0:
            break
        spans.append(TextSpan(idx, idx + q_len))
        pos = idx + q_len
    return tuple(spans)


def summarize_page_structure(
    page: OCRPage, uncertain_count: int
) -> tuple[str, list[str]]:
    """Return `(summary_label_text, table_combo_labels)` for a recognised page."""
    counts = {kind: 0 for kind in BlockType}
    for block in page.blocks:
        counts[block.block_type] += 1
    table_labels: list[str] = []
    for position, table in enumerate(page.tables, start=1):
        columns = len(table.rows[0]) if table.rows else 0
        table_labels.append(f"Bảng {position} ({len(table.rows)}×{columns})")
    heading_count = sum(
        counts[kind]
        for kind in (
            BlockType.TITLE,
            BlockType.HEADING_1,
            BlockType.HEADING_2,
            BlockType.HEADING_3,
        )
    )
    uncertain_suffix = (
        f" · {uncertain_count} từ cần kiểm tra" if uncertain_count > 0 else ""
    )
    summary = (
        f"Bố cục: {estimate_column_count(page.blocks)} cột · "
        f"{counts[BlockType.TEXT]} đoạn · "
        f"{heading_count} tiêu đề · "
        f"{counts[BlockType.CAPTION]} chú thích · "
        f"{len(page.tables)} bảng · {counts[BlockType.IMAGE]} hình"
        f"{uncertain_suffix}"
    )
    return summary, table_labels


def match_table_for_block(page: OCRPage | None, index: int) -> int | None:
    """Match a table block index to the extracted table drawn inside it."""
    return None if page is None else table_for_block(page, index)


def match_block_for_table(page: OCRPage | None, position: int) -> int | None:
    """Find the layout block index corresponding to a table index."""
    if page is None or not 0 <= position < len(page.tables):
        return None
    for index in range(len(page.blocks)):
        if match_table_for_block(page, index) == position:
            return index
    return None


def estimate_column_count(blocks: tuple[OCRBlock, ...]) -> int:
    """Estimate text columns as the widest set of side-by-side narrow blocks."""
    narrow = [
        block
        for block in blocks
        if block.block_type
        in (
            BlockType.TEXT,
            BlockType.TITLE,
            BlockType.HEADING_1,
            BlockType.HEADING_2,
            BlockType.HEADING_3,
        )
    ]
    if not narrow:
        return 0
    page_left = min(block.bbox.x1 for block in narrow)
    page_right = max(block.bbox.x2 for block in narrow)
    span = page_right - page_left
    columns: list[tuple[float, float]] = []
    for block in sorted(narrow, key=lambda item: item.bbox.x1):
        if span > 0 and block.bbox.width >= span * 0.8:
            continue
        for index, (left, right) in enumerate(columns):
            overlap = min(right, block.bbox.x2) - max(left, block.bbox.x1)
            if overlap > 0.5 * min(right - left, block.bbox.width):
                columns[index] = (min(left, block.bbox.x1), max(right, block.bbox.x2))
                break
        else:
            columns.append((block.bbox.x1, block.bbox.x2))
    return max(1, len(columns))


def _should_break_line(prev_text: str, curr_text: str) -> bool:
    if prev_text.endswith(":"):
        return True
    if bool(_LIST_MARKER_REGEX.match(curr_text)):
        return True
    return False


def _render_block_lines(
    block: OCRBlock,
    parts: list[str],
    cursor: int,
    uncertain: list[TextSpan],
    *,
    confidence_threshold: float | None = None,
) -> int:
    for line_index, line in enumerate(block.lines):
        if line_index:
            prev_line = block.lines[line_index - 1]
            prev_text = prev_line.text.rstrip()
            curr_text = line.text.lstrip()
            if _should_break_line(prev_text, curr_text):
                parts.append("\n")
                cursor += 1
            elif prev_text.endswith("-") and not prev_text.endswith(" -"):
                pass
            else:
                parts.append(" ")
                cursor += 1
        for word_index, word in enumerate(line.words):
            if word_index:
                parts.append(" ")
                cursor += 1
            parts.append(word.text)
            is_low = (
                word.is_low_confidence
                if confidence_threshold is None
                else word.confidence < confidence_threshold
            )
            if is_low:
                uncertain.append(TextSpan(cursor, cursor + len(word.text)))
            cursor += len(word.text)
    return cursor
