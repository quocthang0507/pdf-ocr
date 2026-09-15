"""JSON exporter for lossless OCR document interchange."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.models import OCRDocument
from src.exporters.base_exporter import BaseExporter
from src.exporters.exporter_registry import register_exporter


@register_exporter("json", "JSON", extensions=(".json",))
class JSONExporter(BaseExporter):
    """Serialize the complete OCR document tree with Unicode coordinates intact."""

    def _export(self, document: OCRDocument, output_path: Path) -> None:
        output_path.write_text(
            json.dumps(
                document.to_dict(),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )


JsonExporter = JSONExporter
