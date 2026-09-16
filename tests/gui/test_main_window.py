"""The desktop shell opens documents safely and remembers the user's session."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence

from src.core.exceptions import DocumentLoadError
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


def _pdf(tmp_path: Path, name: str = "hoa-don.pdf") -> Path:
    document = tmp_path / name
    document.write_bytes(b"%PDF-1.4 fake")
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


