"""Excel exports preserve OCR tables, Unicode, merges, and readable styling."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook

from src.core.models import (
    BoundingBox,
    OCRDocument,
    OCRPage,
    OCRTable,
    TableCellSpan,
)
from src.exporters.xlsx_exporter import XLSXExporter

pytestmark = pytest.mark.unit


def _document_with_tables() -> OCRDocument:
    first = OCRTable(
        rows=(
            ("Kết quả", "", ""),
            ("Tên", "Giá", "Ghi chú"),
            ("Sách", "50.000", "Có sẵn"),
        ),
        bbox=BoundingBox(10, 10, 500, 240),
        merged_cells=(TableCellSpan(0, 0, 1, 3),),
    )
    second = OCRTable(
        rows=(("Mục", "Giá trị"), ("Tỷ lệ", "98%")),
        bbox=BoundingBox(10, 250, 500, 400),
    )
    return OCRDocument(
        pages=(OCRPage(1, 600, 800, tables=(first, second)),),
        title="Báo cáo OCR",
    )


def test_exports_each_ocr_table_to_a_styled_worksheet(tmp_path: Path) -> None:
    destination = tmp_path / "report.xlsx"

    XLSXExporter().export(_document_with_tables(), destination)

    workbook = load_workbook(destination)
    assert workbook.sheetnames == ["Table 1", "Table 2"]
    sheet = workbook["Table 1"]
    assert sheet["A1"].value == "Kết quả"
    assert sheet["A3"].value == "Sách"
    assert sheet["C3"].value == "Có sẵn"
    assert "A1:C1" in {str(item) for item in sheet.merged_cells.ranges}
    assert sheet.freeze_panes == "A2"
    assert sheet["A1"].font.bold is True
    assert sheet["A1"].font.color is not None
    assert sheet["A1"].font.color.rgb in {"FFFFFFFF", "00FFFFFF"}
    assert sheet.column_dimensions["A"].width >= len("Kết quả")
    assert workbook.properties.title == "Báo cáo OCR"


def test_exports_text_fallback_when_document_has_no_tables(tmp_path: Path) -> None:
    destination = tmp_path / "empty.xlsx"
    document = OCRDocument(
        pages=(OCRPage(1, 400, 600),),
        title="Không có bảng",
    )

    XLSXExporter().export(document, destination)

    workbook = load_workbook(destination)
    assert workbook.sheetnames == ["OCR Text"]
    assert workbook["OCR Text"]["A1"].value == "Không có bảng"
