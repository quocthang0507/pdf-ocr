"""Text and JSON exporters preserve readable and machine-readable OCR output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.constants import BlockType
from src.core.models import (
    BoundingBox,
    OCRBlock,
    OCRDocument,
    OCRLine,
    OCRPage,
    OCRTable,
    OCRWord,
)
from src.exporters.json_exporter import JSONExporter
from src.exporters.text_exporter import MarkdownExporter, PlainTextExporter

pytestmark = pytest.mark.unit


def _document() -> OCRDocument:
    box = BoundingBox(20, 30, 300, 70)
    title = OCRBlock(
        (OCRLine((OCRWord("Báo cáo OCR", box),), box, font_size=22),),
        box,
        block_type=BlockType.TITLE,
        reading_order=0,
    )
    paragraph = OCRBlock(
        (OCRLine((OCRWord("Nội dung | tiếng Việt", box),), box),),
        box,
        reading_order=1,
    )
    table = OCRTable(
        rows=(("Tên", "Giá"), ("Sách", "50.000")),
        bbox=BoundingBox(20, 100, 300, 220),
    )
    return OCRDocument(
        pages=(OCRPage(1, 600, 800, blocks=(title, paragraph), tables=(table,)),),
        title="Báo cáo OCR",
        source_path="input.pdf",
    )


def test_exports_markdown_with_headings_tables_and_escaped_pipes(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "report.md"

    MarkdownExporter().export(_document(), destination)

    text = destination.read_text(encoding="utf-8")
    assert text.startswith("# Báo cáo OCR\n\n## Trang 1")
    assert "Nội dung \\| tiếng Việt" in text
    assert "| Tên | Giá |" in text
    assert "| --- | --- |" in text
    assert text.endswith("\n")


def test_exports_plain_text_without_markdown_markup(tmp_path: Path) -> None:
    destination = tmp_path / "report.txt"

    PlainTextExporter().export(_document(), destination)

    text = destination.read_text(encoding="utf-8")
    assert text.startswith("Báo cáo OCR\n\nTrang 1\n")
    assert "Nội dung | tiếng Việt" in text
    assert "Tên\tGiá" in text
    assert "| --- |" not in text


def test_exports_json_with_coordinates_and_unicode(tmp_path: Path) -> None:
    destination = tmp_path / "report.json"

    JSONExporter().export(_document(), destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["title"] == "Báo cáo OCR"
    assert payload["pages"][0]["width"] == 600
    assert (
        payload["pages"][0]["blocks"][1]["lines"][0]["words"][0]["text"]
        == "Nội dung | tiếng Việt"
    )
    assert payload["pages"][0]["blocks"][1]["lines"][0]["words"][0]["bbox"]["x1"] == 20


@pytest.mark.unit
def test_markdown_and_text_place_each_table_once_in_reading_order(
    tmp_path: Path,
) -> None:
    from src.core.layout_analyzer import LayoutAnalyzer

    def at(text: str, box: tuple[float, float, float, float]) -> OCRBlock:
        bbox = BoundingBox(*box)
        return OCRBlock((OCRLine((OCRWord(text, bbox),), bbox),), bbox)

    table = OCRTable(
        rows=(("Mặt hàng", "Số lượng"), ("Sổ tay", "12")),
        bbox=BoundingBox(180, 280, 1020, 420),
    )
    page = LayoutAnalyzer().analyze(
        OCRPage(
            1,
            1600,
            2000,
            blocks=(
                at("Trước bảng", (200, 100, 1400, 160)),
                at("Mặt hàng", (200, 300, 500, 340)),
                at("Số lượng", (700, 300, 1000, 340)),
                at("Sổ tay", (200, 360, 500, 400)),
                at("12", (700, 360, 1000, 400)),
                at("Sau bảng", (200, 600, 1400, 640)),
            ),
            tables=(table,),
        )
    )
    document = OCRDocument((page,), source_path="bang.pdf")

    MarkdownExporter().export(document, tmp_path / "bang.md")
    PlainTextExporter().export(document, tmp_path / "bang.txt")

    markdown = (tmp_path / "bang.md").read_text(encoding="utf-8")
    text = (tmp_path / "bang.txt").read_text(encoding="utf-8")
    assert markdown.count("Sổ tay") == 1 and text.count("Sổ tay") == 1
    assert markdown.index("Trước bảng") < markdown.index("| Mặt hàng |")
    assert markdown.index("| Sổ tay | 12 |") < markdown.index("Sau bảng")
    assert text.index("Mặt hàng\tSố lượng") < text.index("Sau bảng")
