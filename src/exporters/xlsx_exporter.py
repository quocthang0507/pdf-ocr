"""Microsoft Excel exporter for OCR tables and document text."""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.core.models import OCRDocument, OCRTable
from src.exporters.base_exporter import BaseExporter
from src.exporters.exporter_registry import register_exporter


@register_exporter("xlsx", "Microsoft Excel", extensions=(".xlsx",))
class XLSXExporter(BaseExporter):
    """Write every OCR table to a separate, readable Excel worksheet."""

    _HEADER_FILL = "1F4E78"
    _HEADER_FONT = "FFFFFF"
    _BORDER_COLOR = "D9D9D9"

    def _export(self, document: OCRDocument, output_path: Path) -> None:
        workbook = Workbook()
        default_sheet = workbook.active
        if default_sheet is not None:
            workbook.remove(default_sheet)
        workbook.properties.title = document.title

        tables = [table for page in document.pages for table in page.tables]
        if tables:
            for index, table in enumerate(tables, start=1):
                sheet = workbook.create_sheet(
                    self._sheet_title(f"Table {index}", workbook)
                )
                self._write_table(sheet, table)
        else:
            sheet = workbook.create_sheet("OCR Text")
            self._write_text_fallback(sheet, document)
        workbook.save(output_path)

    @staticmethod
    def _sheet_title(candidate: str, workbook: Workbook) -> str:
        title = re.sub(r"[\\/*?:\[\]]", " ", candidate).strip() or "Sheet"
        title = title[:31]
        used = {sheet.title for sheet in workbook.worksheets}
        if title not in used:
            return title
        suffix = 2
        while True:
            suffix_text = f" ({suffix})"
            trimmed = title[: 31 - len(suffix_text)] + suffix_text
            if trimmed not in used:
                return trimmed
            suffix += 1

    def _write_table(self, sheet: Worksheet, table: OCRTable) -> None:
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "A2"
        row_count = len(table.rows)
        column_count = len(table.rows[0]) if table.rows else 0
        if not row_count or not column_count:
            sheet["A1"] = "(Bảng rỗng)"
            return

        thin = Side(style="thin", color=self._BORDER_COLOR)
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        for row_index, row in enumerate(table.rows, start=1):
            for column_index, value in enumerate(row, start=1):
                cell = sheet.cell(row=row_index, column=column_index, value=value)
                cell.font = Font(
                    name="Arial",
                    size=10,
                    bold=row_index == 1,
                    color=self._HEADER_FONT if row_index == 1 else "000000",
                )
                cell.fill = PatternFill(
                    "solid", fgColor=self._HEADER_FILL if row_index == 1 else "FFFFFF"
                )
                cell.border = border
                cell.alignment = Alignment(
                    horizontal="left", vertical="center", wrap_text=True
                )

        for span in table.merged_cells:
            sheet.merge_cells(
                start_row=span.row + 1,
                start_column=span.column + 1,
                end_row=span.row + span.row_span,
                end_column=span.column + span.column_span,
            )

        for column_index in range(1, column_count + 1):
            values = [
                str(table.rows[row_index][column_index - 1])
                for row_index in range(row_count)
            ]
            width = min(
                max(max((len(value) for value in values), default=8) + 2, 10), 48
            )
            sheet.column_dimensions[get_column_letter(column_index)].width = width

    @staticmethod
    def _write_text_fallback(sheet: Worksheet, document: OCRDocument) -> None:
        sheet.sheet_view.showGridLines = False
        sheet.column_dimensions["A"].width = 100
        row_index = 1
        if document.title:
            sheet.cell(row=row_index, column=1, value=document.title)
            sheet.cell(row=row_index, column=1).font = Font(
                name="Arial", size=14, bold=True
            )
            row_index += 2
        for page in document.pages:
            for block in sorted(page.blocks, key=lambda item: item.reading_order):
                if block.text:
                    sheet.cell(row=row_index, column=1, value=block.text)
                    sheet.cell(row=row_index, column=1).alignment = Alignment(
                        wrap_text=True, vertical="top"
                    )
                    row_index += 1
