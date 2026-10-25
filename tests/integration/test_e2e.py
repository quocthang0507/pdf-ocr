"""End to end over the sample documents, from file on disk to exported file."""

from __future__ import annotations

import json
import time
import unicodedata
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from docx import Document as DocxDocument
from openpyxl import load_workbook

from src.constants import PageType
from src.core.models import (
    BoundingBox,
    OCRBlock,
    OCRDocument,
    OCRLine,
    OCRPage,
    OCRTable,
    OCRWord,
)
from src.core.table_extractor import DetectedTableCell, TableExtractor
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.engine_registry import EngineRegistry
from src.exporters import (
    DOCXExporter,
    JSONExporter,
    MarkdownExporter,
    PDFExporter,
    PlainTextExporter,
    XLSXExporter,
)
from src.services.pipeline_service import PipelineService

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ENGINE_ID = "e2e-stub"
SAMPLE_LINES = (
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
    "Kính gửi: Phòng Kế toán",
    "Đề nghị quý phòng giải quyết cho tôi được nhận trợ cấp.",
)
SECONDS_PER_TEXT_PAGE = 1.0


def _fixture(name: str) -> Path:
    path = FIXTURES / name
    if not path.is_file():
        pytest.fail(
            f"Thiếu tệp mẫu '{name}'. Chạy: python tests/fixtures/generate_fixtures.py"
        )
    return path


@pytest.fixture(scope="module", autouse=True)
def stub_engine() -> None:
    """A deterministic recogniser, so the suite runs offline and repeatably.

    Everything else in the path is real: loading, preprocessing, layout,
    post-processing and every exporter.
    """

    class StubEngine(BaseOCREngine):
        CONFIG_SCHEMA = {
            "device": ConfigField("cpu", lambda value: isinstance(value, str)),
        }

        def _load_model(self) -> None:
            return None

        def _unload_model(self) -> None:
            return None

        def _recognize(self, image: object, page_number: int) -> OCRPage:
            assert isinstance(image, np.ndarray)
            height, width = image.shape[:2]
            blocks = []
            for index, text in enumerate(SAMPLE_LINES):
                top = 20.0 + index * 60.0
                parts = text.split(" ")
                total_w = min(width - 1.0, 700.0) - 20.0
                word_w = total_w / max(1, len(parts))
                words = tuple(
                    OCRWord(
                        part,
                        BoundingBox(
                            20.0 + j * word_w,
                            top,
                            20.0 + (j + 1) * word_w,
                            top + 40.0,
                        ),
                        0.99 if index else 0.62,
                    )
                    for j, part in enumerate(parts)
                )
                box = BoundingBox(20.0, top, min(width - 1.0, 700.0), top + 40.0)
                blocks.append(
                    OCRBlock(lines=(OCRLine(words=words, bbox=box),), bbox=box)
                )
            return OCRPage(
                page_number=page_number,
                width=float(width),
                height=float(height),
                blocks=tuple(blocks),
            )

    snapshot = EngineRegistry.snapshot()
    EngineRegistry.register(ENGINE_ID, "E2E stub", "Bộ nhận diện giả lập")(StubEngine)
    yield
    EngineRegistry.restore(snapshot)


def _process(name: str) -> OCRDocument:
    service = PipelineService()
    return service.process(_fixture(name), engine_id=ENGINE_ID, device="cpu", dpi=150)


# -- the sample set ---------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "sample_vi_text.pdf",
        "sample_two_column.pdf",
        "sample_scanned.pdf",
        "sample_vi.png",
        "sample_table.png",
        "sample_skewed.png",
        "sample_handwriting.png",
    ],
)
def test_every_sample_document_processes_end_to_end(name: str) -> None:
    document = _process(name)

    assert document.pages, f"'{name}' không tạo được trang nào."
    assert all(page.width > 0 and page.height > 0 for page in document.pages)
    assert document.title == Path(name).stem


# -- text-based documents ---------------------------------------------------


def test_a_pdf_with_a_text_layer_is_read_without_ocr() -> None:
    document = _process("sample_vi_text.pdf")

    assert len(document.pages) == 2
    assert all(page.page_type is PageType.TEXT_BASED for page in document.pages)


def test_extracted_vietnamese_keeps_its_diacritics() -> None:
    document = _process("sample_vi_text.pdf")

    text = "\n".join(block.text for block in document.pages[0].blocks)
    assert "XÃ HỘI CHỦ NGHĨA VIỆT NAM" in text
    assert "Nguyễn Văn An" in text
    assert "Độc lập - Tự do - Hạnh phúc" in text
    assert text == unicodedata.normalize("NFC", text)


def test_tone_marks_are_normalised_to_the_project_convention() -> None:
    """Post-processing rewrites hòa as hoà; the whole pipeline must agree."""
    document = _process("sample_vi_text.pdf")

    text = "\n".join(block.text for block in document.pages[0].blocks)
    assert "CỘNG HOÀ" in text
    assert "CỘNG HÒA" not in text


def test_reading_a_text_layer_is_fast_enough_to_feel_instant() -> None:
    started = time.monotonic()
    document = _process("sample_vi_text.pdf")
    elapsed = time.monotonic() - started

    assert elapsed < SECONDS_PER_TEXT_PAGE * len(document.pages)


def test_two_columns_are_not_read_across_the_gutter() -> None:
    document = _process("sample_two_column.pdf")

    text = " ".join(block.text for block in document.pages[0].blocks)
    left = text.index("Thị trường lao động")
    right = text.index("Ngành chế biến chế tạo")
    assert left < right, "Cột trái phải được đọc trọn vẹn trước cột phải."


# -- scanned documents ------------------------------------------------------


def test_a_scanned_pdf_goes_through_recognition() -> None:
    document = _process("sample_scanned.pdf")

    assert document.pages[0].page_type is PageType.SCANNED
    assert document.pages[0].blocks


def test_low_confidence_words_are_flagged_for_review() -> None:
    document = _process("sample_scanned.pdf")

    words = [
        word
        for block in document.pages[0].blocks
        for line in block.lines
        for word in line.words
    ]
    assert any(word.is_low_confidence for word in words)


def test_a_skewed_photograph_still_produces_text() -> None:
    document = _process("sample_skewed.png")

    assert document.pages[0].blocks[0].text


# -- tables -----------------------------------------------------------------


def _invoice_table() -> OCRTable:
    rows = (
        ("Mặt hàng", "Số lượng", "Đơn giá", "Thành tiền"),
        ("Sổ tay bìa cứng", "12", "45.000", "540.000"),
        ("Bút bi xanh", "50", "5.000", "250.000"),
    )
    cells = []
    words = []
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            box = BoundingBox(
                30.0 + column_index * 150,
                40.0 + row_index * 52,
                170.0 + column_index * 150,
                88.0 + row_index * 52,
            )
            cells.append(DetectedTableCell(row_index, column_index, box))
            words.append(OCRWord(value, box, 0.95))
    return TableExtractor().extract(
        cells, words, table_bbox=BoundingBox(30, 40, 770, 200)
    )


def test_an_invoice_table_keeps_its_shape_through_excel(tmp_path: Path) -> None:
    table = _invoice_table()
    document = OCRDocument(
        pages=(OCRPage(1, 760, 320, tables=(table,)),), title="Hóa đơn"
    )
    destination = tmp_path / "hoa-don.xlsx"

    XLSXExporter().export(document, destination)

    sheet = load_workbook(destination).active
    assert sheet.max_row == len(table.rows)
    assert sheet.max_column == len(table.rows[0])
    assert sheet["A2"].value == "Sổ tay bìa cứng"
    assert sheet["D3"].value == "250.000"


# -- every export format ----------------------------------------------------


@pytest.fixture(scope="module")
def recognised() -> OCRDocument:
    return _process("sample_vi.png")


def test_markdown_export_carries_the_recognised_text(
    recognised: OCRDocument, tmp_path: Path
) -> None:
    destination = tmp_path / "ket-qua.md"

    MarkdownExporter().export(recognised, destination)

    body = destination.read_text(encoding="utf-8")
    assert "Kính gửi: Phòng Kế toán" in body


def test_plain_text_export_carries_the_recognised_text(
    recognised: OCRDocument, tmp_path: Path
) -> None:
    destination = tmp_path / "ket-qua.txt"

    PlainTextExporter().export(recognised, destination)

    assert "Phòng Kế toán" in destination.read_text(encoding="utf-8")


def test_json_export_round_trips_back_into_the_model(
    recognised: OCRDocument, tmp_path: Path
) -> None:
    destination = tmp_path / "ket-qua.json"

    JSONExporter().export(recognised, destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert OCRDocument.from_dict(payload).pages[0].blocks == recognised.pages[0].blocks


def test_word_export_opens_and_keeps_the_text(
    recognised: OCRDocument, tmp_path: Path
) -> None:
    destination = tmp_path / "ket-qua.docx"

    DOCXExporter().export(recognised, destination)

    body = "\n".join(item.text for item in DocxDocument(str(destination)).paragraphs)
    assert "Phòng Kế toán" in body


def test_the_searchable_pdf_can_be_searched(
    recognised: OCRDocument, tmp_path: Path
) -> None:
    destination = tmp_path / "ket-qua.pdf"

    PDFExporter().export(recognised, destination)

    with pymupdf.open(destination) as pdf:
        assert pdf[0].search_for("Kính"), "Không tìm thấy chữ trong lớp text ẩn."
        assert "Phòng" in pdf[0].get_text()


def test_every_exported_file_is_complete_not_a_leftover_temporary(
    recognised: OCRDocument, tmp_path: Path
) -> None:
    exporters = {
        "md": MarkdownExporter(),
        "txt": PlainTextExporter(),
        "json": JSONExporter(),
        "docx": DOCXExporter(),
        "pdf": PDFExporter(),
        "xlsx": XLSXExporter(),
    }

    for suffix, exporter in exporters.items():
        exporter.export(recognised, tmp_path / f"ket-qua.{suffix}")

    written = sorted(path.suffix for path in tmp_path.iterdir())
    assert written == sorted(f".{suffix}" for suffix in exporters)
    assert all(path.stat().st_size > 0 for path in tmp_path.iterdir())


# -- the whole sample set through the batch queue ----------------------------


def test_the_whole_sample_set_runs_through_the_batch_queue(qapp) -> None:
    from src.workers.batch_manager import BatchManager

    documents = sorted(FIXTURES.glob("sample_*"))
    service = PipelineService()
    with service.open_page_session(
        engine_id=ENGINE_ID, device="cpu", dpi=100
    ) as session:
        manager = BatchManager(
            lambda task: session.recognise(task.document_path, task.page_number),
            page_counter=session.page_count,
        )
        queued = manager.start(documents)
        assert manager.wait_for_completion(120_000) is True

    snapshot = manager.progress_snapshot()
    assert queued == len(documents) + 1, "PDF hai trang phải đóng góp hai tác vụ."
    assert snapshot.failed == 0
    assert snapshot.completed == queued


def test_full_ui_pdf_reader_ocr_and_editor_workflow(qtbot, tmp_path: Path) -> None:
    """End-to-end UI workflow: Open -> View -> Edit PDF -> OCR -> Search -> Settings."""
    from PySide6.QtCore import QSettings

    from src.config import ConfigManager
    from src.gui.dialogs.document_properties_dialog import DocumentPropertiesDialog
    from src.gui.dialogs.pdf_tools_dialog import PDFToolsDialog
    from src.gui.dialogs.settings_dialog import SettingsDialog
    from src.gui.main_window import MainWindow
    from src.gui.window_helpers import reload_modified_pdf

    # 1. Create a 2-page PDF and open it in MainWindow
    pdf_path = tmp_path / "hop-dong-2026.pdf"
    with pymupdf.open() as doc:
        p1 = doc.new_page(width=400, height=600)
        p1.insert_text((40, 80), "HOP DONG DICH VU CONG NGHE", fontsize=14)
        p2 = doc.new_page(width=400, height=600)
        p2.insert_text((40, 80), "Dieu 2: Thanh toan va bao mat", fontsize=12)
        doc.save(str(pdf_path))

    settings = QSettings(str(tmp_path / "session.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    window.open_path(pdf_path)
    assert window.document_session is not None
    assert window.document_session.page_count == 2
    assert not window.navigation_dock.page_list.item(0).icon().isNull()

    # 2. Switch reading color modes smoothly
    window.command_actions["color_mode_sepia"].trigger()
    assert window.document_session.page_color_mode == "sepia"
    window.command_actions["color_mode_night"].trigger()
    assert window.document_session.page_color_mode == "night"
    window.command_actions["color_mode_normal"].trigger()
    assert window.document_session.page_color_mode == "normal"

    # 3. Edit PDF via PDFToolsDialog (Metadata, Bookmarks, Highlight, Note, Compress)
    window.document_session.close()
    tools = PDFToolsDialog(pdf_path, current_page=1, parent=window)
    qtbot.addWidget(tools)
    tools.pdf_modified.connect(lambda _p: reload_modified_pdf(window))
    tools.title_edit.setText("Hợp đồng dịch vụ 2026")
    tools.author_edit.setText("Công ty AI Việt Nam")
    tools.save_metadata_btn.click()
    tools.bookmarks_edit.setPlainText(
        "1 | Điều 1: Tổng quan | 1\n1 | Điều 2: Thanh toán | 2"
    )
    tools.save_bookmarks_btn.click()
    tools.highlight_btn.click()
    tools.note_text_edit.setText("Đã kiểm duyệt")
    tools.add_note_btn.click()
    tools.compress_btn.click()

    # Verify properties & outline reloaded in MainWindow
    props_dlg = DocumentPropertiesDialog(pdf_path, parent=window)
    qtbot.addWidget(props_dlg)
    assert props_dlg._props.metadata["title"] == "Hợp đồng dịch vụ 2026"
    assert props_dlg._props.bookmarks_count == 2
    assert window.navigation_dock.outline_tree.topLevelItemCount() == 2

    # 4. Store OCR result, run spell correction & search navigation
    box = BoundingBox(20, 20, 300, 60)
    ocr_page = OCRPage(
        page_number=2,
        width=400,
        height=600,
        blocks=(
            OCRBlock(
                lines=(
                    OCRLine(
                        words=(
                            OCRWord("Điều", box, 0.99),
                            OCRWord("khoản", box, 0.99),
                            OCRWord("thanh", box, 0.99),
                            OCRWord("toán", box, 0.99),
                        ),
                        bbox=box,
                    ),
                ),
                bbox=box,
            ),
        ),
    )
    window.document_session.store(ocr_page)
    window.navigation_dock.refresh_status()
    window.navigation_dock.search_input.setText("thanh toán")
    assert window.navigation_dock.search_results.count() == 1
    item = window.navigation_dock.search_results.item(0)
    assert item is not None
    window.navigation_dock._on_search_item_clicked(item)
    assert window.document_session.current_page == 2

    # 5. Configure 6-category Settings & export/import profile
    cfg = ConfigManager(tmp_path / "cfg", use_qsettings=False)
    settings_dlg = SettingsDialog(config=cfg, parent=window)
    qtbot.addWidget(settings_dlg)
    settings_dlg.color_mode_combo.setCurrentIndex(
        settings_dlg.color_mode_combo.findData("sepia")
    )
    settings_dlg.default_dpi_spin.setValue(400)
    settings_dlg.accept()
    assert cfg.load().page_color_mode == "sepia"
    assert cfg.load().default_dpi == 400
