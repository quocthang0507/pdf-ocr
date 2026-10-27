"""Reading-order traversal shared by the document exporters."""

from __future__ import annotations

from src.constants import BlockType
from src.core.models import BoundingBox, OCRBlock, OCRPage, OCRTable

PageItem = OCRBlock | OCRTable


def _overlaps(first: BoundingBox, second: BoundingBox) -> bool:
    centre_x = (first.x1 + first.x2) / 2
    centre_y = (first.y1 + first.y2) / 2
    return second.x1 <= centre_x <= second.x2 and second.y1 <= centre_y <= second.y2


def page_flow(page: OCRPage) -> list[PageItem]:
    """Blocks in reading order with each table in place of its table block.

    The layout analyser folds a table's lines into one TABLE block at the
    table's position. Exporters used to write that block as a paragraph of
    run-together cell text and then the real table again at the end of the
    page, so every table appeared twice and out of place.
    """
    remaining = list(page.tables)
    items: list[PageItem] = []
    for block in sorted(page.blocks, key=lambda item: item.reading_order):
        if block.block_type is BlockType.TABLE:
            match = next(
                (
                    table
                    for table in remaining
                    if _overlaps(block.bbox, table.bbox)
                    or _overlaps(table.bbox, block.bbox)
                ),
                None,
            )
            if match is not None:
                remaining.remove(match)
                items.append(match)
                continue
        items.append(block)
    items.extend(remaining)
    return items
