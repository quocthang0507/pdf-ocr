"""Plain-text view of a page, and folding the user's edits back into it.

Exporters work from the page model, not from the editor, so an edit that
never reaches the model would silently vanish from the exported file. The
editor shows each block as a paragraph (`OCRBlock.text`), hiding line breaks,
so edits are matched word by word across the whole block: every word that
still lines up keeps its original box. Where the edit no longer lines up,
the new text is laid out inside the area the old block occupied, so a
searchable PDF still finds it.

A table block shows as its recognised table instead, one row per line with
the cells separated by tabs, and an edit there updates the table's cells.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from src.constants import BlockType
from src.core.models import (
    BoundingBox,
    OCRBlock,
    OCRLine,
    OCRPage,
    OCRTable,
    OCRWord,
)

BLOCK_SEPARATOR = "\n\n"
USER_CONFIDENCE = 1.0
# Tabs stay out: a table row whose cells are all empty is just tabs.
_BLANK_LINES = re.compile(r"\n[ ]*\n+")
CELL_SEPARATOR = "\t"

# (line index, word index) of every word that shows as one token on screen.
_Group = list[tuple[int, int]]


def table_for_block(page: OCRPage, index: int) -> int | None:
    """Index of the table drawn inside the table block at `index`, if any."""
    if not 0 <= index < len(page.blocks):
        return None
    block = page.blocks[index]
    if block.block_type is not BlockType.TABLE:
        return None
    for position, table in enumerate(page.tables):
        centre_x = (table.bbox.x1 + table.bbox.x2) / 2
        centre_y = (table.bbox.y1 + table.bbox.y2) / 2
        if (
            block.bbox.x1 <= centre_x <= block.bbox.x2
            and block.bbox.y1 <= centre_y <= block.bbox.y2
        ):
            return position
    return None


def table_transcript(page: OCRPage, index: int) -> str | None:
    """The block's table, row by row, or None when it shows as a paragraph."""
    position = _shown_table(page, index)
    if position is None:
        return None
    return "\n".join(
        CELL_SEPARATOR.join(cell.strip() for cell in row)
        for row in page.tables[position].rows
    )


def _shown_table(page: OCRPage, index: int) -> int | None:
    position = table_for_block(page, index)
    if position is None:
        return None
    rows = page.tables[position].rows
    return position if any(cell.strip() for row in rows for cell in row) else None


def render_transcript(page: OCRPage) -> str:
    """The page as the editor shows it: one paragraph or table per block."""
    return BLOCK_SEPARATOR.join(
        _block_transcript(page, index) for index in range(len(page.blocks))
    )


def _block_transcript(page: OCRPage, index: int) -> str:
    table = table_transcript(page, index)
    return page.blocks[index].text if table is None else table


def apply_transcript(page: OCRPage, text: str) -> OCRPage:
    """Return the page with its text replaced by the edited transcript."""
    if text == render_transcript(page):
        return page
    chunks = [chunk for chunk in _BLANK_LINES.split(text) if chunk.strip()]
    if len(chunks) == len(page.blocks):
        tables = list(page.tables)
        blocks: list[OCRBlock] = []
        for index, (block, chunk) in enumerate(zip(page.blocks, chunks, strict=True)):
            position = _shown_table(page, index)
            if position is not None:
                tables[position] = _edit_table(tables[position], chunk)
                blocks.append(block)
                continue
            edited = _edit_block(block, chunk)
            if edited is not None:
                blocks.append(edited)
        return page.with_updates(blocks=tuple(blocks), tables=tuple(tables))
    return page.with_updates(blocks=_relayout(page, chunks))


def _edit_table(table: OCRTable, chunk: str) -> OCRTable:
    """Rows are lines and cells are tab-separated; short rows are padded."""
    lines = chunk.strip("\n").split("\n")
    cells = [[cell.strip() for cell in line.split(CELL_SEPARATOR)] for line in lines]
    width = max(len(row) for row in cells)
    rows = tuple(tuple(row + [""] * (width - len(row))) for row in cells)
    if rows == tuple(tuple(cell.strip() for cell in row) for row in table.rows):
        return table
    return table.with_updates(
        rows=rows,
        merged_cells=tuple(
            span
            for span in table.merged_cells
            if span.row + span.row_span <= len(rows)
            and span.column + span.column_span <= width
        ),
    )


def _edit_block(block: OCRBlock, chunk: str) -> OCRBlock | None:
    if chunk.split() == block.text.split():
        return block
    groups = _token_groups(block)
    tokens = chunk.split()
    if len(tokens) != len(groups):
        return block.with_updates(lines=_layout_lines(_clean_lines(chunk), block.bbox))
    replaced: dict[tuple[int, int], OCRWord | None] = {}
    for token, group in zip(tokens, groups, strict=True):
        shown = [block.lines[line].words[index] for line, index in group]
        if token == "".join(word.text for word in shown):
            continue
        first, *rest = group
        # A word split across lines becomes one word where it started.
        replaced[first] = OCRWord(token, shown[0].bbox, USER_CONFIDENCE)
        replaced.update(dict.fromkeys(rest))
    lines = []
    for line_index, line in enumerate(block.lines):
        kept: list[OCRWord] = []
        for index, word in enumerate(line.words):
            new = replaced.get((line_index, index), word)
            if new is not None:
                kept.append(new)
        if kept:
            lines.append(line.with_updates(words=tuple(kept)))
    return block.with_updates(lines=tuple(lines))


def _token_groups(block: OCRBlock) -> list[_Group]:
    """Words as the editor tokenises them: a hyphen at a line end glues words."""
    groups: list[_Group] = []
    glue = False
    for line_index, line in enumerate(block.lines):
        for word_index, _word in enumerate(line.words):
            position = (line_index, word_index)
            if glue and word_index == 0 and groups:
                groups[-1].append(position)
            else:
                groups.append([position])
        text = line.text.rstrip()
        glue = text.endswith("-") and not text.endswith(" -")
    return groups


def _clean_lines(chunk: str) -> list[str]:
    return [" ".join(line.split()) for line in chunk.split("\n") if line.strip()]


def _relayout(page: OCRPage, chunks: Sequence[str]) -> tuple[OCRBlock, ...]:
    """Lay restructured text out inside the area the old text covered."""
    if not chunks:
        return ()
    area = _union([block.bbox for block in page.blocks]) or BoundingBox(
        0, 0, page.width, page.height
    )
    bands = _split_vertically(area, len(chunks))
    return tuple(
        OCRBlock(
            lines=_layout_lines(_clean_lines(chunk), band),
            bbox=band,
            reading_order=order,
        )
        for order, (chunk, band) in enumerate(zip(chunks, bands, strict=True))
    )


def _layout_lines(lines: Sequence[str], area: BoundingBox) -> tuple[OCRLine, ...]:
    bands = _split_vertically(area, len(lines))
    return tuple(
        _layout_line(text.split(), band)
        for text, band in zip(lines, bands, strict=True)
    )


def _layout_line(tokens: Sequence[str], area: BoundingBox) -> OCRLine:
    """Share the line's width between its words in proportion to their length."""
    total = sum(len(token) for token in tokens) + max(len(tokens) - 1, 0)
    width = area.x2 - area.x1
    words: list[OCRWord] = []
    cursor = 0
    for token in tokens:
        start = area.x1 + width * cursor / total
        cursor += len(token)
        end = area.x1 + width * cursor / total
        cursor += 1
        words.append(
            OCRWord(token, BoundingBox(start, area.y1, end, area.y2), USER_CONFIDENCE)
        )
    return OCRLine(words=tuple(words), bbox=area)


def _split_vertically(area: BoundingBox, parts: int) -> list[BoundingBox]:
    height = (area.y2 - area.y1) / max(parts, 1)
    return [
        BoundingBox(
            area.x1, area.y1 + index * height, area.x2, area.y1 + (index + 1) * height
        )
        for index in range(parts)
    ]


def _union(boxes: Sequence[BoundingBox]) -> BoundingBox | None:
    if not boxes:
        return None
    return BoundingBox(
        min(box.x1 for box in boxes),
        min(box.y1 for box in boxes),
        max(box.x2 for box in boxes),
        max(box.y2 for box in boxes),
    )


_PARAGRAPH_LIST_REGEX = re.compile(r"^([•\-\*\+–—]|\d+[\.\)]|[a-zA-Z][\.\)])\s+")


def reconstruct_paragraphs(raw_text: str) -> str:
    """Merge broken lines within paragraphs while preserving true paragraph breaks."""
    if not raw_text:
        return ""
    paragraphs: list[str] = []
    current_para: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_para:
                paragraphs.append(_join_paragraph_lines(current_para))
                current_para = []
            continue
        current_para.append(stripped)
    if current_para:
        paragraphs.append(_join_paragraph_lines(current_para))
    return "\n\n".join(paragraphs)


def _join_paragraph_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0]
    parts: list[str] = [lines[0]]
    for idx in range(1, len(lines)):
        prev, curr = lines[idx - 1], lines[idx]
        if prev.endswith(":") or bool(_PARAGRAPH_LIST_REGEX.match(curr)):
            parts.append("\n" + curr)
        elif prev.endswith("-") and not prev.endswith(" -"):
            parts[-1] = parts[-1][:-1]
            parts.append(curr)
        else:
            parts.append(" " + curr)
    return "".join(parts)
