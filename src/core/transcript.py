"""Plain-text view of a page, and folding the user's edits back into it.

Exporters work from the page model, not from the editor, so an edit that
never reaches the model would silently vanish from the exported file. The
editor shows each block as a paragraph (`OCRBlock.text`), hiding line breaks,
so edits are matched word by word across the whole block: every word that
still lines up keeps its original box. Where the edit no longer lines up,
the new text is laid out inside the area the old block occupied, so a
searchable PDF still finds it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord

BLOCK_SEPARATOR = "\n\n"
USER_CONFIDENCE = 1.0
_BLANK_LINES = re.compile(r"\n[ \t]*\n+")

# (line index, word index) of every word that shows as one token on screen.
_Group = list[tuple[int, int]]


def render_transcript(page: OCRPage) -> str:
    """The page as the editor shows it: one paragraph per block."""
    return BLOCK_SEPARATOR.join(block.text for block in page.blocks)


def apply_transcript(page: OCRPage, text: str) -> OCRPage:
    """Return the page with its text replaced by the edited transcript."""
    if text == render_transcript(page):
        return page
    chunks = [chunk for chunk in _BLANK_LINES.split(text) if chunk.strip()]
    if len(chunks) == len(page.blocks):
        blocks = tuple(
            _edit_block(block, chunk)
            for block, chunk in zip(page.blocks, chunks, strict=True)
        )
        return page.with_updates(blocks=tuple(block for block in blocks if block))
    return page.with_updates(blocks=_relayout(page, chunks))


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
