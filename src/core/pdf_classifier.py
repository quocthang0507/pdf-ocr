"""PDF page classification and direct vector text extraction."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import pymupdf

from src.constants import BlockType, PageType
from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord


def classify_page(page: pymupdf.Page) -> PageType:
    """Classify a single PDF page into TEXT_BASED, SCANNED, or HYBRID.

    Args:
        page: PyMuPDF Page instance.

    Returns:
        PageType: Classification result.
    """
    text_dict = page.get_text("dict")
    char_count = sum(
        len(span.get("text", "").strip())
        for block in text_dict.get("blocks", [])
        if block.get("type") == 0
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    )
    images = page.get_images(full=True)

    if char_count < 10:
        return PageType.SCANNED

    if len(images) == 0:
        return PageType.TEXT_BASED

    page_area = float(page.rect.width * page.rect.height)
    if page_area <= 0:
        return PageType.TEXT_BASED

    img_area = 0.0
    for img_info in images:
        xref = img_info[0]
        for rect in page.get_image_rects(xref):
            img_area += float(rect.width * rect.height)

    coverage = img_area / page_area
    if coverage > 0.15:
        return PageType.HYBRID

    return PageType.TEXT_BASED


def _build_word_map(
    page: pymupdf.Page, scale: float
) -> dict[tuple[int, int], list[OCRWord]]:
    """Extract individual words with scaled coordinates grouped by block

    and line index.
    """
    word_map: dict[tuple[int, int], list[OCRWord]] = defaultdict(list)
    raw_words = page.get_text("words")

    for item in raw_words:
        x0, y0, x1, y1, word_text, b_idx, l_idx = item[:7]
        x1_sc = max(x0 * scale + 1.0, x1 * scale)
        y1_sc = max(y0 * scale + 1.0, y1 * scale)
        bbox = BoundingBox(x1=x0 * scale, y1=y0 * scale, x2=x1_sc, y2=y1_sc)
        word_map[(int(b_idx), int(l_idx))].append(
            OCRWord(text=str(word_text), bbox=bbox, confidence=1.0)
        )
    return word_map


def _build_lines(
    block: dict[str, Any],
    b_idx: int,
    scale: float,
    word_map: dict[tuple[int, int], list[OCRWord]],
) -> list[OCRLine]:
    """Parse text lines and words for a single block."""
    lines: list[OCRLine] = []
    for l_idx, line in enumerate(block.get("lines", [])):
        lx0, ly0, lx1, ly1 = line["bbox"]
        l_bbox = BoundingBox(
            x1=lx0 * scale,
            y1=ly0 * scale,
            x2=max(lx0 * scale + 1.0, lx1 * scale),
            y2=max(ly0 * scale + 1.0, ly1 * scale),
        )
        words = tuple(word_map.get((b_idx, l_idx), []))
        if not words:
            spans = line.get("spans", [])
            span_text = " ".join(
                s.get("text", "").strip() for s in spans if s.get("text", "").strip()
            )
            if not span_text:
                continue
            words = tuple(
                OCRWord(text=w, bbox=l_bbox, confidence=1.0) for w in span_text.split()
            )

        font_name: str | None = None
        font_size: float | None = None
        spans = line.get("spans", [])
        if spans:
            font_name = spans[0].get("font")
            raw_size = spans[0].get("size")
            if raw_size and raw_size > 0:
                font_size = float(raw_size)

        lines.append(
            OCRLine(
                words=words,
                bbox=l_bbox,
                font_name=font_name,
                font_size=font_size,
            )
        )
    return lines


def _text_blocks(page: pymupdf.Page, scale: float) -> tuple[OCRBlock, ...]:
    """Turn the page's native text runs into blocks, keeping their reading order."""
    word_map = _build_word_map(page, scale)
    blocks: list[OCRBlock] = []
    for index, block in enumerate(page.get_text("dict").get("blocks", [])):
        if block.get("type") != 0:
            continue
        block_lines = _build_lines(block, index, scale, word_map)
        if not block_lines:
            continue
        blocks.append(
            OCRBlock(
                lines=tuple(block_lines),
                bbox=_scaled_box(block["bbox"], scale),
                block_type=BlockType.TEXT,
                reading_order=index,
            )
        )
    return tuple(blocks)


def _scaled_box(bbox: Sequence[float], scale: float) -> BoundingBox:
    """Scale a PDF point box into pixels, never letting it collapse to nothing."""
    x1, y1, x2, y2 = (float(value) * scale for value in bbox)
    return BoundingBox(x1=x1, y1=y1, x2=max(x1 + 1.0, x2), y2=max(y1 + 1.0, y2))


def extract_text_page(page: pymupdf.Page, page_number: int, dpi: int = 300) -> OCRPage:
    """Extract the native text layer of a PDF page without rasterizing it.

    Args:
        page: PyMuPDF Page object.
        page_number: 1-indexed page number.
        dpi: Target pixel resolution for bounding boxes.

    Returns:
        OCRPage: Structured immutable page representation.
    """
    scale = dpi / 72.0
    page_type = classify_page(page)
    blocks = () if page_type == PageType.SCANNED else _text_blocks(page, scale)
    return OCRPage(
        page_number=page_number,
        width=float(page.rect.width * scale),
        height=float(page.rect.height * scale),
        blocks=blocks,
        page_type=page_type,
        dpi=dpi,
    )


class PDFClassifier:
    """High-level classifier and fast text extraction service."""

    def classify_page(self, page: pymupdf.Page) -> PageType:
        """Classify a single page."""
        return classify_page(page)

    def classify_document(self, doc: pymupdf.Document) -> list[PageType]:
        """Classify all pages in a document."""
        return [classify_page(doc[i]) for i in range(len(doc))]

    def extract_page(
        self, page: pymupdf.Page, page_number: int, dpi: int = 300
    ) -> OCRPage:
        """Extract native text page directly."""
        return extract_text_page(page, page_number=page_number, dpi=dpi)
