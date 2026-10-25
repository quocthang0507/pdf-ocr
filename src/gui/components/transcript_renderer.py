"""Pure transcript layout helpers: spans, column counting, and line joining."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.constants import BlockType
from src.core.models import OCRBlock, OCRPage
from src.core.transcript import BLOCK_SEPARATOR

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
        cursor = _render_block_lines(block, parts, cursor, uncertain)
        blocks.append(TextSpan(start, cursor))
    return "".join(parts), tuple(blocks), tuple(uncertain)


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
    block: OCRBlock, parts: list[str], cursor: int, uncertain: list[TextSpan]
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
            if word.is_low_confidence:
                uncertain.append(TextSpan(cursor, cursor + len(word.text)))
            cursor += len(word.text)
    return cursor
