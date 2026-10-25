"""The desktop shell opens documents safely and remembers the user's session."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence

from src.core.exceptions import DocumentLoadError
from src.core.models import BoundingBox, OCRPage, OCRTable
from src.gui.components.menu_bar import MAX_RECENT_FILES
from src.gui.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def settings(tmp_path: Path) -> QSettings:
    store = QSettings(str(tmp_path / "session.ini"), QSettings.Format.IniFormat)
    store.setFallbacksEnabled(False)
    return store


@pytest.fixture
def window(qtbot, settings: QSettings) -> MainWindow:
    main_window = MainWindow(settings=settings)
    qtbot.addWidget(main_window)
    return main_window


def _pdf(tmp_path: Path, name: str = "hoa-don.pdf", pages: int = 1) -> Path:
    import pymupdf

    document = tmp_path / name
    with pymupdf.open() as pdf:
        for number in range(1, pages + 1):
            pdf.new_page(width=200, height=100).insert_text((20, 50), f"Trang {number}")
        pdf.save(document)
    return document


def _messages(window: MainWindow) -> list[str]:
    """The text of every notification currently on screen."""
    return [
        toast.message_label.text() for toast in window.notifications.visible_toasts()
    ]


def _mime_for(path: Path) -> QMimeData:
    """Callers must keep the returned object alive for the event's lifetime."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


def test_menu_bar_offers_the_standard_desktop_menus(window: MainWindow) -> None:
    titles = [action.text() for action in window.menuBar().actions()]

    assert titles == ["&Tệp", "&Sửa", "&Xem", "&OCR", "Công &cụ", "Trợ &giúp"]


@pytest.mark.parametrize(
    ("key", "shortcut"),
    [
        ("open_file", "Ctrl+O"),
        ("export", "Ctrl+S"),
        ("quit", "Ctrl+Q"),
        ("run_ocr", "F5"),
    ],
)
def test_primary_commands_use_standard_shortcuts(
    window: MainWindow, key: str, shortcut: str
) -> None:
    action = window.command_actions[key]

    assert action.shortcut() == QKeySequence(shortcut)


def test_tool_bar_exposes_the_quick_task_commands(window: MainWindow) -> None:
    exposed = {action.objectName() for action in window.tool_bar.actions()}

    assert {"action_open_file", "action_run_ocr", "action_export"} <= exposed
    assert window.tool_bar.objectName(), "Toolbar cần objectName để lưu bố cục."


def test_opening_a_document_announces_it_and_updates_the_title(
    window: MainWindow, qtbot, tmp_path: Path
) -> None:
    document = _pdf(tmp_path)

    with qtbot.waitSignal(window.document_opened) as blocker:
        window.open_path(document)

    assert blocker.args == [str(document.resolve())]
    assert window.current_path == document.resolve()
    assert document.name in window.windowTitle()


def test_recent_files_keep_the_newest_first_without_duplicates(
    window: MainWindow, tmp_path: Path
) -> None:
    first = _pdf(tmp_path, "mot.pdf")
    second = _pdf(tmp_path, "hai.pdf")

    window.open_path(first)
    window.open_path(second)
    window.open_path(first)

    assert window.recent_files() == (str(first.resolve()), str(second.resolve()))


def test_recent_files_history_is_capped(window: MainWindow, tmp_path: Path) -> None:
    for index in range(MAX_RECENT_FILES + 4):
        window.open_path(_pdf(tmp_path, f"trang-{index}.pdf"))

    assert len(window.recent_files()) == MAX_RECENT_FILES
    assert len(window.recent_files_menu.actions()) == MAX_RECENT_FILES


def test_recent_files_menu_reopens_the_chosen_document(
    window: MainWindow, qtbot, tmp_path: Path
) -> None:
    document = _pdf(tmp_path)
    window.open_path(document)
    window.set_current_path(None)

    with qtbot.waitSignal(window.document_opened):
        window.recent_files_menu.actions()[0].trigger()

    assert window.current_path == document.resolve()


def test_dropping_a_supported_file_opens_it(
    window: MainWindow, qtbot, tmp_path: Path
) -> None:
    document = _pdf(tmp_path)
    mime = _mime_for(document)
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    with qtbot.waitSignal(window.document_opened):
        window.dropEvent(event)

    assert window.current_path == document.resolve()


def test_drag_enter_is_accepted_only_for_supported_documents(
    window: MainWindow, tmp_path: Path
) -> None:
    supported = _pdf(tmp_path)
    unsupported = tmp_path / "ghi-chu.exe"
    unsupported.write_bytes(b"binary")
    supported_mime = _mime_for(supported)
    unsupported_mime = _mime_for(unsupported)

    def drag_event(mime: QMimeData) -> QDragEnterEvent:
        return QDragEnterEvent(
            QPoint(5, 5),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    accepted = drag_event(supported_mime)
    window.dragEnterEvent(accepted)
    rejected = drag_event(unsupported_mime)
    window.dragEnterEvent(rejected)

    assert accepted.isAccepted() is True
    assert rejected.isAccepted() is False


def test_unsupported_file_reports_a_friendly_message(
    window: MainWindow, tmp_path: Path
) -> None:
    unsupported = tmp_path / "bang-tinh.xyz"
    unsupported.write_text("dữ liệu", encoding="utf-8")

    window.open_path(unsupported)

    assert _messages(window) == ["Định dạng tệp này chưa được hỗ trợ."]
    assert window.current_path is None


def test_error_boundary_keeps_domain_errors_readable(window: MainWindow) -> None:
    def failing() -> None:
        raise DocumentLoadError()

    result = window.guarded(failing, title="Mở tệp")

    assert result is None
    assert _messages(window) == [DocumentLoadError.default_message]


def test_error_boundary_hides_technical_detail_of_unexpected_errors(
    window: MainWindow,
) -> None:
    def failing() -> None:
        raise ZeroDivisionError("/home/user/secret/token.txt")

    window.guarded(failing, title="Chạy OCR")

    assert _messages(window) and "secret" not in _messages(window)[0]


def test_running_ocr_without_a_document_asks_the_user_to_open_one(
    window: MainWindow,
) -> None:
    emitted: list[str] = []
    window.ocr_requested.connect(emitted.append)

    window.command_actions["run_ocr"].trigger()

    assert emitted == []
    assert _messages(window) == ["Vui lòng mở một tài liệu trước khi chạy OCR."]


def test_running_ocr_announces_the_open_document(
    window: MainWindow, qtbot, tmp_path: Path
) -> None:
    document = _pdf(tmp_path)
    window.open_path(document)

    with qtbot.waitSignal(window.ocr_requested) as blocker:
        window.command_actions["run_ocr"].trigger()

    assert blocker.args == [str(document.resolve())]


@pytest.mark.parametrize(
    ("key", "step"), [("zoom_in", 1), ("zoom_out", -1), ("zoom_reset", 0)]
)
def test_zoom_commands_publish_the_requested_step(
    window: MainWindow, qtbot, key: str, step: int
) -> None:
    with qtbot.waitSignal(window.zoom_requested) as blocker:
        window.command_actions[key].trigger()

    assert blocker.args == [step]


def test_window_layout_survives_a_restart(qtbot, settings: QSettings) -> None:
    first = MainWindow(settings=settings)
    qtbot.addWidget(first)
    first.resize(620, 430)
    first.save_session()

    second = MainWindow(settings=settings)
    qtbot.addWidget(second)

    assert second.size() == first.size()


def test_restored_window_stays_inside_the_available_screen(
    window: MainWindow,
) -> None:
    available = window.screen().availableGeometry()
    window.resize(
        min(620, available.width()),
        min(430, available.height()),
    )
    window.move(available.right(), available.bottom())

    window._fit_to_available_screen()

    assert available.contains(window.frameGeometry())


def test_opening_a_valid_pdf_renders_it_on_canvas(
    window: MainWindow, qtbot, tmp_path: Path
) -> None:
    import pymupdf

    doc = pymupdf.open()
    page1 = doc.new_page(width=300, height=400)
    page1.insert_text((50, 50), "Trang 1")
    page2 = doc.new_page(width=300, height=400)
    page2.insert_text((50, 50), "Trang 2")
    pdf_path = tmp_path / "tai-lieu.pdf"
    pdf_path.write_bytes(doc.tobytes())
    doc.close()

    with qtbot.waitSignal(window.document_opened):
        window.open_path(pdf_path)

    assert window.comparison.total_pages() == 2
    assert window.comparison.current_page() == 1
    assert window.comparison.page_label.text() == "Trang 1 / 2"
    assert window.comparison.canvas.page_size().width() > 0
    assert "Trang 1" in window.comparison.transcript()

    # Flip to page 2
    window.comparison.next_page_btn.click()
    assert window.comparison.current_page() == 2
    assert window.comparison.page_label.text() == "Trang 2 / 2"
    assert "Trang 2" in window.comparison.transcript()


def test_page_recognition_updates_current_comparison_dock(
    window: MainWindow, tmp_path: Path
) -> None:
    import pymupdf

    from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord
    from src.workers.signals import PageTask

    doc = pymupdf.open()
    doc.new_page(width=300, height=400)
    pdf_path = tmp_path / "single.pdf"
    pdf_path.write_bytes(doc.tobytes())
    doc.close()

    window.open_path(pdf_path)

    word = OCRWord("Recognised", BoundingBox(10, 10, 80, 40), 0.99)
    line = OCRLine(words=(word,), bbox=BoundingBox(10, 10, 80, 40))
    block = OCRBlock(lines=(line,), bbox=BoundingBox(10, 10, 80, 40))
    page = OCRPage(page_number=1, width=300, height=400, blocks=(block,))

    task = PageTask(document_path=str(pdf_path.resolve()), page_number=1)
    window._on_page_recognised(task, page)

    assert "Recognised" in window.comparison.transcript()
    assert len(window.comparison.canvas.block_items()) == 1


def test_clear_and_remove_recent_files(window: MainWindow, tmp_path: Path) -> None:
    p1 = tmp_path / "file1.pdf"
    p2 = tmp_path / "file2.pdf"
    p1.touch()
    p2.touch()

    window._remember(p1)
    window._remember(p2)
    assert len(window.recent_files()) == 2

    window.remove_recent_file(str(p1.resolve()))
    assert len(window.recent_files()) == 1
    assert str(p2.resolve()) in window.recent_files()

    window.clear_recent_files()
    assert len(window.recent_files()) == 0


def test_document_history_action_opens_dialog(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.gui.dialogs.document_history import DocumentHistoryDialog

    opened = False

    def mock_exec(self: DocumentHistoryDialog) -> int:
        nonlocal opened
        opened = True
        return 0

    monkeypatch.setattr(DocumentHistoryDialog, "exec", mock_exec)

    action = window.command_actions.get("document_history")
    assert action is not None
    action.trigger()

    assert opened is True


def test_tool_bar_icons_follow_the_theme(window: MainWindow) -> None:
    """Platform icons are drawn dark and would vanish on a dark tool bar."""
    action = window.command_actions["open_file"]

    window.apply_theme_colors("light")
    light = action.icon().pixmap(18, 18).toImage()
    window.apply_theme_colors("dark")
    dark = action.icon().pixmap(18, 18).toImage()

    assert not light.isNull() and not dark.isNull()
    assert light != dark


def test_the_options_dock_defaults_to_the_vietnamese_engine(
    window: MainWindow,
) -> None:
    assert window.settings_dock.engine_combo.currentData() == "vietocr"


# -- page preview and navigation ---------------------------------------------


def test_opening_a_document_shows_its_first_page(
    window: MainWindow, tmp_path: Path
) -> None:
    window.open_path(_pdf(tmp_path, pages=3))

    assert not window.comparison.canvas.page_size().isEmpty()
    assert window.comparison.page_label.text() == "Trang 1 / 3"


def test_the_pages_can_be_browsed_in_order(window: MainWindow, tmp_path: Path) -> None:
    window.open_path(_pdf(tmp_path, pages=3))

    window.command_actions["next_page"].trigger()
    window.command_actions["next_page"].trigger()

    assert window.comparison.page_label.text() == "Trang 3 / 3"
    assert window.command_actions["next_page"].isEnabled() is False
    assert window.command_actions["previous_page"].isEnabled() is True


def test_page_commands_are_off_until_a_document_is_open(window: MainWindow) -> None:
    assert window.command_actions["next_page"].isEnabled() is False
    assert window.command_actions["previous_page"].isEnabled() is False
    assert window.comparison.page_label.text() == "Trang 0 / 0"


def test_page_commands_use_the_page_keys(window: MainWindow) -> None:
    assert window.command_actions["next_page"].shortcut() == QKeySequence("PgDown")
    assert window.command_actions["previous_page"].shortcut() == QKeySequence("PgUp")


def test_a_corrupt_document_is_refused_without_replacing_the_open_one(
    window: MainWindow, tmp_path: Path
) -> None:
    good = _pdf(tmp_path, "tot.pdf")
    window.open_path(good)
    broken = tmp_path / "hong.pdf"
    broken.write_bytes(b"%PDF-1.4 hong")

    window.open_path(broken)

    assert window.current_path == good.resolve()
    assert any(
        toast.severity.name == "ERROR"
        for toast in window.notifications.visible_toasts()
    )


def test_closing_the_window_during_a_batch_stops_it_cleanly(
    qtbot, settings: QSettings, tmp_path: Path
) -> None:
    import time

    from src.core.models import OCRPage

    class SlowSession:
        def page_count(self, _path: object) -> int:
            return 5

        def recognise(self, _path: object, number: int) -> OCRPage:
            time.sleep(0.05)
            return OCRPage(page_number=number, width=10, height=10)

        def close(self) -> None:
            pass

    class SlowPipeline:
        def open_page_session(self, **_options: object) -> SlowSession:
            return SlowSession()

    window = MainWindow(settings=settings, pipeline=SlowPipeline())
    qtbot.addWidget(window)
    window.open_path(_pdf(tmp_path, pages=5))
    window.command_actions["run_ocr"].trigger()
    batch = window.batch_dialog
    assert batch is not None

    window.close()

    assert batch.manager.is_running is False


# -- recognised results -------------------------------------------------------


class _RecordingSession:
    """Recognises instantly, returning one known word per page."""

    def __init__(self, pages: int) -> None:
        self.pages = pages

    def page_count(self, _path: object) -> int:
        return self.pages

    def recognise(self, _path: object, number: int):
        from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord

        box = BoundingBox(20, 20, 200, 60)
        word = OCRWord(f"kết-quả-{number}", box, 0.5 if number == 1 else 0.99)
        line = OCRLine(words=(word,), bbox=box)
        return OCRPage(
            page_number=number,
            width=400,
            height=200,
            blocks=(OCRBlock(lines=(line,), bbox=box),),
            dpi=144,
        )

    def close(self) -> None:
        pass


def _recognised_window(
    qtbot, settings: QSettings, tmp_path: Path, pages: int = 2
) -> MainWindow:
    class Pipeline:
        def open_page_session(self, **_options: object) -> _RecordingSession:
            return _RecordingSession(pages)

    window = MainWindow(settings=settings, pipeline=Pipeline())
    qtbot.addWidget(window)
    window.open_path(_pdf(tmp_path, pages=pages))
    window.command_actions["run_ocr"].trigger()
    batch = window.batch_dialog
    assert batch is not None
    assert batch.manager.wait_for_completion(10_000)
    return window


def test_recognised_text_appears_beside_the_page(
    qtbot, settings: QSettings, tmp_path: Path
) -> None:
    window = _recognised_window(qtbot, settings, tmp_path)

    assert window.comparison.transcript() == "kết-quả-1"
    assert len(window.comparison.canvas.block_items()) == 1


def test_each_page_shows_its_own_result(
    qtbot, settings: QSettings, tmp_path: Path
) -> None:
    window = _recognised_window(qtbot, settings, tmp_path)

    window.command_actions["next_page"].trigger()

    assert window.comparison.transcript() == "kết-quả-2"


def test_the_page_image_matches_the_result_coordinates(
    qtbot, settings: QSettings, tmp_path: Path
) -> None:
    window = _recognised_window(qtbot, settings, tmp_path)

    size = window.comparison.canvas.page_size()
    assert (size.width(), size.height()) == (400, 200)


def test_edits_in_the_transcript_are_kept_for_export(
    qtbot, settings: QSettings, tmp_path: Path
) -> None:
    window = _recognised_window(qtbot, settings, tmp_path)

    window.comparison.editor.setPlainText("đã-sửa")

    session = window.document_session
    assert session is not None
    result = session.result(1)
    assert result is not None
    assert result.blocks[0].lines[0].words[0].text == "đã-sửa"


def test_edits_survive_moving_to_another_page_and_back(
    qtbot, settings: QSettings, tmp_path: Path
) -> None:
    window = _recognised_window(qtbot, settings, tmp_path)
    window.comparison.editor.setPlainText("đã-sửa")

    window.command_actions["next_page"].trigger()
    window.command_actions["previous_page"].trigger()

    assert window.comparison.transcript() == "đã-sửa"


def test_a_finished_run_reports_how_many_pages_were_recognised(
    qtbot, settings: QSettings, tmp_path: Path
) -> None:
    window = _recognised_window(qtbot, settings, tmp_path)

    assert "Đã nhận diện 2/2 trang" in " ".join(_messages(window))


# -- export -------------------------------------------------------------------


def _choose_save_path(monkeypatch: pytest.MonkeyPatch, path: Path, chosen: str):
    import src.gui.main_window as main_window_module

    offered: dict[str, object] = {}

    def fake_dialog(_parent, _title, directory, filters, selected):
        offered.update(directory=directory, filters=filters, selected=selected)
        return (str(path), chosen) if path != Path("") else ("", "")

    monkeypatch.setattr(
        main_window_module.QFileDialog, "getSaveFileName", staticmethod(fake_dialog)
    )
    return offered


def test_exporting_writes_the_recognised_and_edited_text(
    qtbot, settings: QSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _recognised_window(qtbot, settings, tmp_path)
    window.comparison.editor.setPlainText("đã-sửa")
    target = tmp_path / "ket-qua.md"
    _choose_save_path(monkeypatch, target, "Markdown (*.md *.markdown)")

    with qtbot.waitSignal(window.export_completed, timeout=10_000) as blocker:
        window.command_actions["export"].trigger()

    assert blocker.args == [str(target.resolve())]
    content = target.read_text(encoding="utf-8")
    assert "đã-sửa" in content and "kết-quả-2" in content
    assert any("ket-qua.md" in message for message in _messages(window))


def test_the_save_dialog_suggests_a_name_beside_the_document(
    qtbot, settings: QSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _recognised_window(qtbot, settings, tmp_path)
    offered = _choose_save_path(monkeypatch, Path(""), "")

    window.command_actions["export"].trigger()

    assert offered["directory"] == str(tmp_path.resolve() / "hoa-don.docx")
    assert str(offered["selected"]).startswith("Microsoft Word")


def test_exporting_before_recognition_asks_to_run_ocr_first(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_path(_pdf(tmp_path))
    offered = _choose_save_path(monkeypatch, tmp_path / "x.docx", "")

    window.command_actions["export"].trigger()

    assert offered == {}
    assert _messages(window)[-1] == "Chưa có kết quả nhận diện. Hãy chạy OCR trước."


def test_a_failed_export_is_reported(
    qtbot, settings: QSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _recognised_window(qtbot, settings, tmp_path)
    _choose_save_path(monkeypatch, tmp_path / "khong-co" / "x.txt", "")

    with qtbot.waitSignal(window.export_failed, timeout=10_000):
        window.command_actions["export"].trigger()

    assert "Thư mục đích không tồn tại." in _messages(window)


# -- folders --------------------------------------------------------------------


def _folder_window(qtbot, settings: QSettings) -> MainWindow:
    class Pipeline:
        def open_page_session(self, **_options: object) -> _RecordingSession:
            return _RecordingSession(1)

    window = MainWindow(settings=settings, pipeline=Pipeline())
    qtbot.addWidget(window)
    return window


def test_opening_a_folder_recognises_every_supported_document(
    qtbot, settings: QSettings, tmp_path: Path
) -> None:
    folder = tmp_path / "ho-so"
    folder.mkdir()
    first = _pdf(folder, "a.pdf")
    second = _pdf(folder, "b.pdf")
    (folder / "ghi-chu.txt").write_text("bỏ qua", encoding="utf-8")
    window = _folder_window(qtbot, settings)

    window.open_folder(folder)

    batch = window.batch_dialog
    assert batch is not None
    assert batch.manager.wait_for_completion(10_000)
    assert window.current_path == first.resolve()
    assert batch.manager.pages_per_document() == {
        str(first.resolve()): 1,
        str(second.resolve()): 1,
    }


def test_results_for_other_documents_are_ready_when_opened(
    qtbot, settings: QSettings, tmp_path: Path
) -> None:
    folder = tmp_path / "ho-so"
    folder.mkdir()
    _pdf(folder, "a.pdf")
    second = _pdf(folder, "b.pdf")
    window = _folder_window(qtbot, settings)
    window.open_folder(folder)
    batch = window.batch_dialog
    assert batch is not None
    assert batch.manager.wait_for_completion(10_000)

    window.open_path(second)

    assert window.comparison.transcript() == "kết-quả-1"


def test_a_folder_without_documents_is_reported(
    window: MainWindow, tmp_path: Path
) -> None:
    (tmp_path / "trong").mkdir()

    window.open_folder(tmp_path / "trong")

    assert window.batch_dialog is None
    assert _messages(window) == ["Thư mục không có tài liệu nào được hỗ trợ."]


def test_a_corrupt_document_in_a_folder_does_not_stop_the_others(
    qtbot, settings: QSettings, tmp_path: Path
) -> None:
    folder = tmp_path / "ho-so"
    folder.mkdir()
    (folder / "a-hong.pdf").write_bytes(b"%PDF-1.4 hong")
    good = _pdf(folder, "b.pdf")
    window = _folder_window(qtbot, settings)

    window.open_folder(folder)

    assert window.current_path == good.resolve()
    assert window.batch_dialog is not None


# -- region OCR -----------------------------------------------------------------


def test_a_region_over_real_text_reads_the_text_layer(
    qtbot, window: MainWindow, tmp_path: Path
) -> None:
    window.open_path(_pdf(tmp_path))
    # At the default 300 DPI "Trang 1" (baseline 50 pt) sits near y = 170..215 px.
    region = BoundingBox(40, 120, 700, 260)

    with qtbot.waitSignal(window.region_recognised) as blocker:
        window.comparison.canvas.region_selected.emit(region)

    assert blocker.args == ["Trang 1"]
    assert window.comparison.region_result() == "Trang 1"


def test_a_region_on_a_scan_is_recognised_in_the_background(
    qtbot, window: MainWindow, tmp_path: Path
) -> None:
    import numpy as np

    from src.core.models import OCRBlock, OCRLine, OCRPage, OCRWord
    from src.engines.base_engine import BaseOCREngine, ConfigField
    from src.engines.engine_registry import EngineRegistry

    class ScanEngine(BaseOCREngine):
        CONFIG_SCHEMA = {"device": ConfigField("cpu", lambda v: isinstance(v, str))}

        def _load_model(self) -> None:
            pass

        def _unload_model(self) -> None:
            pass

        def _recognize(self, image: object, page_number: int) -> OCRPage:
            assert isinstance(image, np.ndarray)
            box = BoundingBox(0, 0, image.shape[1], image.shape[0])
            line = OCRLine(words=(OCRWord("chữ-quét", box),), bbox=box)
            return OCRPage(
                page_number=page_number,
                width=float(image.shape[1]),
                height=float(image.shape[0]),
                blocks=(OCRBlock(lines=(line,), bbox=box),),
            )

    snapshot = EngineRegistry.snapshot()
    EngineRegistry.register("scan-probe", "Quét", "Thử")(ScanEngine)
    try:
        blank = tmp_path / "quet.pdf"
        import pymupdf

        with pymupdf.open() as pdf:
            pdf.new_page(width=200, height=100)
            pdf.save(blank)
        window.open_path(blank)
        window.settings_dock.options_changed.emit(
            {"engine_id": "scan-probe", "device": "cpu", "dpi": 300}
        )

        with qtbot.waitSignal(window.region_recognised, timeout=10_000) as blocker:
            window.comparison.canvas.region_selected.emit(BoundingBox(10, 10, 300, 200))
    finally:
        EngineRegistry.restore(snapshot)

    assert blocker.args == ["chữ-quét"]
    assert window.comparison.region_result() == "chữ-quét"


def test_a_failed_region_recognition_is_reported(
    qtbot, window: MainWindow, tmp_path: Path
) -> None:
    import pymupdf

    blank = tmp_path / "quet.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=200, height=100)
        pdf.save(blank)
    window.open_path(blank)
    window.settings_dock.options_changed.emit(
        {"engine_id": "khong-ton-tai", "device": "cpu", "dpi": 300}
    )

    with qtbot.waitSignal(window.region_failed, timeout=10_000):
        window.comparison.canvas.region_selected.emit(BoundingBox(10, 10, 300, 200))

    assert window.comparison.region_result() == ""
    toasts = window.notifications.visible_toasts()
    assert any(toast.severity.name == "ERROR" for toast in toasts)


def test_a_text_layer_region_explains_its_source_and_can_be_rerun_with_the_model(
    qtbot, window: MainWindow, tmp_path: Path
) -> None:
    import numpy as np

    from src.core.models import OCRBlock, OCRLine, OCRPage, OCRWord
    from src.engines.base_engine import BaseOCREngine, ConfigField
    from src.engines.engine_registry import EngineRegistry

    class ProbeEngine(BaseOCREngine):
        CONFIG_SCHEMA = {"device": ConfigField("cpu", lambda v: isinstance(v, str))}

        def _load_model(self) -> None:
            pass

        def _unload_model(self) -> None:
            pass

        def _recognize(self, image: object, page_number: int) -> OCRPage:
            assert isinstance(image, np.ndarray)
            box = BoundingBox(0, 0, image.shape[1], image.shape[0])
            line = OCRLine(words=(OCRWord("từ-mô-hình", box),), bbox=box)
            return OCRPage(
                page_number=page_number,
                width=float(image.shape[1]),
                height=float(image.shape[0]),
                blocks=(OCRBlock(lines=(line,), bbox=box),),
            )

    snapshot = EngineRegistry.snapshot()
    EngineRegistry.register("rerun-probe", "Mô hình thử", "Thử")(ProbeEngine)
    try:
        window.open_path(_pdf(tmp_path))
        with qtbot.waitSignal(window.region_recognised):
            window.comparison.canvas.region_selected.emit(
                BoundingBox(40, 120, 700, 260)
            )
        assert "lớp chữ" in window.comparison.region_source_label.text()

        window.settings_dock.options_changed.emit(
            {"engine_id": "rerun-probe", "device": "cpu", "dpi": 300}
        )
        assert "Mô hình thử" in window.comparison.region_source_label.text()

        with qtbot.waitSignal(window.region_recognised, timeout=10_000) as blocker:
            window.comparison.region_rerun_button.click()
    finally:
        EngineRegistry.restore(snapshot)

    assert blocker.args == ["từ-mô-hình"]
    assert window.comparison.region_result() == "từ-mô-hình"
    assert "Mô hình thử" in window.comparison.region_source_label.text()


def test_region_text_can_be_inserted_into_the_transcript(
    window: MainWindow, tmp_path: Path
) -> None:
    window.open_path(_pdf(tmp_path))
    window.comparison.show_region_result("Đoạn chèn", "Nguồn: thử")

    window.comparison.region_insert_button.click()

    assert "Đoạn chèn" in window.comparison.transcript()


def test_tables_recognised_in_a_region_are_saved_on_the_current_page(
    qtbot, window: MainWindow, tmp_path: Path
) -> None:
    from src.workers.region_worker import RegionOCRResult

    document = _pdf(tmp_path)
    window.open_path(document)
    assert window.document_session is not None
    page = OCRPage(page_number=1, width=600, height=300)
    window.document_session.store(page)
    table = OCRTable(
        rows=(("Item", "Qty"), ("Paper", "2")),
        bbox=BoundingBox(20, 30, 200, 90),
    )

    window._on_region_page_recognised(
        RegionOCRResult(str(document.resolve()), 1, page.with_updates(tables=(table,)))
    )

    updated = window.document_session.result(1)
    assert updated is not None
    assert updated.tables == (table,)
    assert any(block.block_type.value == "table" for block in updated.blocks)
    assert "Paper | 2" in window.comparison.transcript()


def test_selecting_search_result_in_navigation_dock_navigates_and_highlights_query(
    qtbot, settings: QSettings, tmp_path: Path
) -> None:
    window = _recognised_window(qtbot, settings, tmp_path)

    window.navigation_dock.search_input.setText("kết-quả-2")
    assert window.navigation_dock.search_results.count() == 1
    item = window.navigation_dock.search_results.item(0)
    assert item is not None
    window.navigation_dock.search_results.itemClicked.emit(item)

    assert window.comparison.page_spin.value() == 2
    assert window.comparison.editor.textCursor().selectedText() == "kết-quả-2"


def test_window_supports_reading_color_modes_and_page_context_edits(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    document = _pdf(tmp_path, pages=3)
    window.open_path(document)
    assert window.document_session is not None

    window.command_actions["color_mode_sepia"].trigger()
    assert window.document_session.page_color_mode == "sepia"
    assert window.navigation_dock.reading_mode_combo.currentData() == "sepia"

    window.command_actions["color_mode_night"].trigger()
    assert window.document_session.page_color_mode == "night"

    # Trigger delete_page via NavigationDock context action
    window.navigation_dock.trigger_page_action("delete_page", 2)
    assert window.document_session.page_count == 2


def test_opening_another_document_clears_the_previous_run_summary(
    window: MainWindow, tmp_path: Path
) -> None:
    window.batch_status.count_label.setText("Đã xong 1/1 · Lỗi 0")
    window.batch_status.eta_label.setText("Còn lại: —")

    window.open_path(_pdf(tmp_path, "khac.pdf"))

    assert window.batch_status.count_label.text() == ""
    assert window.batch_status.eta_label.text() == ""


def test_switching_to_paddle_warns_about_missing_vietnamese_letters(
    window: MainWindow,
) -> None:
    combo = window.settings_dock.engine_combo
    combo.setCurrentIndex(combo.findData("paddle"))

    assert any(
        "PaddleOCR bỏ sót chữ tiếng Việt" in toast.message_label.text()
        for toast in window.notifications.visible_toasts()
    )
