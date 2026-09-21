"""Exports run off the GUI thread and always end in exactly one signal."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from src.core.models import (
    BoundingBox,
    OCRBlock,
    OCRDocument,
    OCRLine,
    OCRPage,
    OCRWord,
)
from src.workers.export_worker import (
    ExportWorker,
    export_filters,
    resolve_export_target,
)

pytestmark = pytest.mark.unit


def _document(tmp_path: Path) -> OCRDocument:
    source = tmp_path / "nguon.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=200, height=100)
        pdf.save(source)
    box = BoundingBox(10, 10, 90, 30)
    line = OCRLine(words=(OCRWord("Xin chào", box),), bbox=box)
    page = OCRPage(
        page_number=1,
        width=200,
        height=100,
        blocks=(OCRBlock(lines=(line,), bbox=box),),
        dpi=72,
    )
    return OCRDocument((page,), source_path=str(source), title="nguon")


def test_every_registered_format_is_offered() -> None:
    offered = {format_id for _label, format_id in export_filters()}

    assert offered == {"docx", "xlsx", "pdf", "json", "markdown", "text"}


def test_filters_name_the_extensions() -> None:
    labels = dict((format_id, label) for label, format_id in export_filters())

    assert labels["docx"] == "Microsoft Word (*.docx)"


def test_the_extension_decides_the_format(tmp_path: Path) -> None:
    target = tmp_path / "ket-qua.xlsx"

    assert resolve_export_target(str(target), "Microsoft Word (*.docx)") == (
        "xlsx",
        target,
    )


def test_a_missing_extension_is_taken_from_the_chosen_filter(tmp_path: Path) -> None:
    assert resolve_export_target(str(tmp_path / "ket-qua"), "JSON (*.json)") == (
        "json",
        tmp_path / "ket-qua.json",
    )


def test_an_unknown_extension_follows_the_chosen_filter(tmp_path: Path) -> None:
    format_id, path = resolve_export_target(
        str(tmp_path / "ket-qua.abc"), "Plain text (*.txt)"
    )

    assert (format_id, path.name) == ("text", "ket-qua.abc.txt")


def test_a_successful_export_reports_the_written_file(qtbot, tmp_path: Path) -> None:
    worker = ExportWorker(_document(tmp_path), "text", tmp_path / "ket-qua.txt")

    with qtbot.waitSignal(worker.signals.finished) as blocker:
        worker.run()

    assert "Xin chào" in Path(blocker.args[0]).read_text(encoding="utf-8")


def test_a_failed_export_reports_a_friendly_message(qtbot, tmp_path: Path) -> None:
    worker = ExportWorker(
        _document(tmp_path), "text", tmp_path / "khong-co" / "ket-qua.txt"
    )

    with qtbot.waitSignal(worker.signals.failed) as blocker:
        worker.run()

    assert blocker.args == ["Thư mục đích không tồn tại."]


def test_an_unexpected_failure_hides_its_details(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.exporters.exporter_registry import ExporterRegistry

    def explode(_format_id: str) -> object:
        raise ZeroDivisionError("/bi-mat/duong-dan")

    monkeypatch.setattr(ExporterRegistry, "get", explode)
    worker = ExportWorker(_document(tmp_path), "text", tmp_path / "ket-qua.txt")

    with qtbot.waitSignal(worker.signals.failed) as blocker:
        worker.run()

    assert "bi-mat" not in blocker.args[0]
