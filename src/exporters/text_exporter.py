"""Markdown and plain-text exporters for OCR documents."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from src.core.models import OCRBlock, OCRDocument, OCRPage, OCRTable
from src.exporters.base_exporter import BaseExporter
from src.exporters.exporter_registry import register_exporter


class _TextDocumentExporter(BaseExporter):
    """Shared traversal helpers for line-oriented text formats."""

    @staticmethod
    def _blocks(document: OCRDocument) -> Iterator[tuple[OCRPage, list[OCRBlock]]]:
        for page in document.pages:
            yield page, sorted(page.blocks, key=lambda item: item.reading_order)

    @staticmethod
    def _table_rows(table: OCRTable) -> list[tuple[str, ...]]:
        return [tuple(cell for cell in row) for row in table.rows]


@register_exporter("markdown", "Markdown", extensions=(".md", ".markdown"))
class MarkdownExporter(_TextDocumentExporter):
    """Export OCR structure as conventional Markdown headings and tables."""

    def _export(self, document: OCRDocument, output_path: Path) -> None:
        lines: list[str] = []
        if document.title:
            lines.extend([f"# {document.title}", ""])
        for page, blocks in self._blocks(document):
            lines.extend([f"## Trang {page.page_number}", ""])
            for block in blocks:
                if block.text:
                    lines.extend([self._escape(block.text), ""])
            for table in page.tables:
                if table.rows and table.rows[0]:
                    lines.extend(self._markdown_table(table))
                    lines.append("")
        output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    @classmethod
    def _markdown_table(cls, table: OCRTable) -> list[str]:
        rows = cls._table_rows(table)
        header = rows[0]
        lines = [f"| {' | '.join(cls._escape(cell) for cell in header)} |"]
        lines.append(f"| {' | '.join('---' for _ in header)} |")
        for row in rows[1:]:
            lines.append(f"| {' | '.join(cls._escape(cell) for cell in row)} |")
        return lines

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


@register_exporter("text", "Plain text", extensions=(".txt",))
class PlainTextExporter(_TextDocumentExporter):
    """Export OCR content without Markdown-specific syntax."""

    def _export(self, document: OCRDocument, output_path: Path) -> None:
        lines: list[str] = []
        if document.title:
            lines.extend([document.title, ""])
        for page, blocks in self._blocks(document):
            lines.extend([f"Trang {page.page_number}", ""])
            for block in blocks:
                if block.text:
                    lines.extend([block.text, ""])
            for table in page.tables:
                for row in table.rows:
                    lines.append("\t".join(row))
                if table.rows:
                    lines.append("")
        output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# A concise alias is useful to callers that prefer the format name as a class.
TextExporter = PlainTextExporter
