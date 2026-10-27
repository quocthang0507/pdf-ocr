"""Markdown and plain-text exporters for OCR documents."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from src.core.models import OCRDocument, OCRPage, OCRTable
from src.exporters.base_exporter import BaseExporter
from src.exporters.exporter_registry import register_exporter
from src.exporters.page_flow import PageItem, page_flow


class _TextDocumentExporter(BaseExporter):
    """Shared traversal helpers for line-oriented text formats."""

    @staticmethod
    def _items(document: OCRDocument) -> Iterator[tuple[OCRPage, list[PageItem]]]:
        for page in document.pages:
            yield page, page_flow(page)

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
        for page, items in self._items(document):
            lines.extend([f"## Trang {page.page_number}", ""])
            for item in items:
                if isinstance(item, OCRTable):
                    if item.rows and item.rows[0]:
                        lines.extend([*self._markdown_table(item), ""])
                elif item.text:
                    lines.extend([self._escape(item.text), ""])
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
        for page, items in self._items(document):
            lines.extend([f"Trang {page.page_number}", ""])
            for item in items:
                if isinstance(item, OCRTable):
                    if item.rows:
                        lines.extend(["\t".join(row) for row in item.rows] + [""])
                elif item.text:
                    lines.extend([item.text, ""])
        output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# A concise alias is useful to callers that prefer the format name as a class.
TextExporter = PlainTextExporter
