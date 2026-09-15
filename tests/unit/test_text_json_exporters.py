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
