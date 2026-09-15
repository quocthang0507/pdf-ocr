"""Exporter contracts validate destinations and remain open for extension."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.exceptions import ExportError
from src.core.models import OCRDocument
from src.exporters.base_exporter import BaseExporter
from src.exporters.exporter_registry import ExporterRegistry, register_exporter

pytestmark = pytest.mark.unit


class DemoExporter(BaseExporter):
    FORMAT_ID = "demo"
    EXTENSIONS = (".demo",)

    def _export(self, document: OCRDocument, output_path: Path) -> None:
        output_path.write_text(document.title, encoding="utf-8")


class BrokenExporter(DemoExporter):
    def _export(self, document: OCRDocument, output_path: Path) -> None:
        output_path.write_text("partial", encoding="utf-8")
        raise RuntimeError("secret backend detail")


@pytest.fixture(autouse=True)
def preserve_registry() -> None:
    snapshot = ExporterRegistry.snapshot()
    yield
    ExporterRegistry.restore(snapshot)


def test_registers_and_creates_future_exporters_without_core_edits() -> None:
    @register_exporter("future", "Future format", extensions=(".future",))
    class FutureExporter(DemoExporter):
        pass

    exporter = ExporterRegistry.get("future")
    metadata = ExporterRegistry.describe("future")

    assert isinstance(exporter, FutureExporter)
    assert metadata.name == "Future format"
    assert metadata.extensions == (".future",)


def test_exports_atomically_to_a_valid_destination(tmp_path: Path) -> None:
    destination = tmp_path / "result.demo"

    result = DemoExporter().export(OCRDocument(title="Nội dung"), destination)

    assert result == destination.resolve()
    assert destination.read_text(encoding="utf-8") == "Nội dung"
    assert list(tmp_path.iterdir()) == [destination]


def test_rejects_wrong_extension_and_directory_destination(tmp_path: Path) -> None:
    exporter = DemoExporter()

    with pytest.raises(ExportError, match="đuôi tệp"):
        exporter.export(OCRDocument(), tmp_path / "result.txt")
    with pytest.raises(ExportError, match="thư mục"):
        exporter.export(OCRDocument(), tmp_path)


def test_rejects_unwritable_or_full_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = DemoExporter()
    monkeypatch.setattr(os, "access", lambda path, mode: False)
    with pytest.raises(ExportError, match="quyền ghi"):
        exporter.export(OCRDocument(), tmp_path / "result.demo")

    monkeypatch.setattr(os, "access", lambda path, mode: True)
    monkeypatch.setattr(
        "src.exporters.base_exporter.shutil.disk_usage",
        lambda path: SimpleNamespace(total=10, used=10, free=0),
    )
    with pytest.raises(ExportError, match="dung lượng"):
        exporter.export(OCRDocument(), tmp_path / "result.demo")


def test_failure_preserves_existing_file_and_hides_backend_details(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "result.demo"
    destination.write_text("original", encoding="utf-8")

    with pytest.raises(ExportError) as caught:
        BrokenExporter().export(OCRDocument(), destination)

    assert destination.read_text(encoding="utf-8") == "original"
    assert "secret backend detail" not in str(caught.value)
    assert isinstance(caught.value.__cause__, RuntimeError)
