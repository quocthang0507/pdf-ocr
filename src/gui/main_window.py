"""Desktop shell: commands, session persistence, and the GUI error boundary."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar

import numpy as np
from PySide6.QtCore import (
    QByteArray,
    QMimeData,
    QObject,
    QSettings,
    Qt,
    QThreadPool,
    Signal,
    SignalInstance,
)
from PySide6.QtGui import QCloseEvent, QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from src.config import ConfigManager
from src.constants import ICON_COLORS
from src.core.document_loader import SUPPORTED_EXTENSIONS
from src.core.exceptions import DocumentLoadError, PDFOCRError
from src.core.models import BoundingBox, OCRPage, OCRTable
from src.core.transcript import (
    apply_transcript,
)
from src.core.transcript import reconstruct_paragraphs as _reconstruct_paragraphs
from src.engines.engine_registry import EngineRegistry
from src.exporters.exporter_registry import ExporterRegistry
from src.gui.components.comparison_dock import ComparisonDock
from src.gui.components.menu_bar import (
    MAX_RECENT_FILES,
    MENU_LAYOUT,
    ApplicationMenuBar,
    RecentFilesMenu,
    create_actions,
    retranslate_actions,
)
from src.gui.components.navigation_dock import NavigationDock
from src.gui.components.notifications import NotificationCenter, Severity
from src.gui.components.settings_dock import SettingsDock
from src.gui.components.status_bar import BatchStatusBar
from src.gui.components.tool_bar import ApplicationToolBar
from src.gui.dialogs.batch_dialog import BatchDialog
from src.gui.dialogs.settings_dialog import SettingsDialog
from src.gui.document_session import DocumentSession
from src.gui.i18n import translate_menu
from src.gui.styles.style_manager import StyleManager
from src.services.pipeline_service import PageOptions, PipelineService
from src.services.weights_manager import ModelWeightsManager
from src.utils.logger import logger
from src.workers.batch_manager import BatchManager
from src.workers.export_worker import (
    ExportWorker,
    export_filters,
    resolve_export_target,
)
from src.workers.region_worker import (
    RegionOCRResult,
    RegionWorker,
    merge_region_tables,
    native_region_text,
)
from src.workers.signals import BatchProgress, PageTask

ORGANIZATION_NAME = "PDF OCR"
APPLICATION_NAME = "PDF OCR Desktop"
RECENT_FILES_KEY = "session/recent_files"
GEOMETRY_KEY = "session/geometry"
WINDOW_STATE_KEY = "session/window_state"
DEFAULT_ENGINE_ID = "vietocr"
DEFAULT_DPI = 300
BATCH_SHUTDOWN_MS = 10_000

ResultT = TypeVar("ResultT")


def document_name_filter() -> str:
    """Build the file dialog filter from the formats the loader accepts."""
    patterns = " ".join(f"*{extension}" for extension in sorted(SUPPORTED_EXTENSIONS))
    return f"Tài liệu hỗ trợ ({patterns});;Tất cả tệp (*)"


def _is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


class MainWindow(QMainWindow):
    """Stateful application shell; document work is published, never performed here."""

    document_opened = Signal(str)
    folder_opened = Signal(str)
    ocr_requested = Signal(str)
    export_requested = Signal(str)
    export_completed = Signal(str)
    export_failed = Signal(str)
    region_recognised = Signal(str)
    region_failed = Signal(str)
    zoom_requested = Signal(int)
    region_ocr_requested = Signal(BoundingBox)
    settings_requested = Signal()

    def __init__(
        self,
        *,
        settings: QSettings | None = None,
        pipeline: PipelineService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings or QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self._current_path: Path | None = None
        self._options: dict[str, object] = {}
        self._pipeline = pipeline or _default_pipeline()
        self._batch: BatchDialog | None = None
        self._batch_controls_wired = False
        self._last_region: BoundingBox | None = None
        self._region_engine_id = DEFAULT_ENGINE_ID
        self._session: DocumentSession | None = None
        self._sessions: dict[Path, DocumentSession] = {}
        self._jobs = QThreadPool(self)
        self._job_signals: set[QObject] = set()
        self._displayed: tuple[np.ndarray, int] | None = None
        self.setWindowTitle(APPLICATION_NAME)
        self.setAcceptDrops(True)
        self.command_actions = create_actions(self)
        self.recent_files_menu = RecentFilesMenu(self)
        self.setMenuBar(
            ApplicationMenuBar(self.command_actions, self.recent_files_menu, self)
        )
        self.tool_bar = ApplicationToolBar(self.command_actions, self)
        self.addToolBar(self.tool_bar)
        self.apply_theme_colors(StyleManager(self._application()).current_theme)
        self.batch_status = BatchStatusBar(self)
        self.setStatusBar(self.batch_status)
        self.notifications = NotificationCenter(self)
        self.setCentralWidget(self._create_document_view())
        self.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self._create_navigation_dock()
        )
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self._create_options_dock()
        )
        self._connect_commands()
        self._remember_options(self.settings_dock.options())
        self._refresh_recent_menu()
        self._refresh_page_controls()
        self._restore_session()

    # -- document session -------------------------------------------------

    @property
    def current_path(self) -> Path | None:
        return self._current_path

    def set_current_path(self, path: Path | None) -> None:
        """Track the active document and mirror it in the window title."""
        self._current_path = path
        name = APPLICATION_NAME if path is None else f"{path.name} — {APPLICATION_NAME}"
        self.setWindowTitle(name)

    def open_path(self, path: str | Path) -> None:
        """Open one document through the error boundary."""
        self.guarded(lambda: self._open_path(path), title="Mở tệp")

    def _open_path(self, path: str | Path) -> None:
        target = Path(path).expanduser()
        if not target.is_file():
            raise DocumentLoadError("Không tìm thấy tệp đã chọn.")
        if not _is_supported(target):
            raise DocumentLoadError("Định dạng tệp này chưa được hỗ trợ.")
        resolved = target.resolve()
        session = self._sessions.get(resolved) or DocumentSession(resolved)
        # Reading the page count opens the file, so a corrupt one fails here,
        # before the document already on screen is replaced.
        if session.page_count < 1:
            raise DocumentLoadError("Tài liệu không có trang nào.")
        self.set_region_mode(False)
        self._activate(session)
        self.set_current_path(resolved)
        self._remember(resolved)
        self.statusBar().showMessage(f"Đã mở {resolved.name}")
        self.notifications.notify(f"Đã mở {resolved.name}", Severity.SUCCESS)
        self.document_opened.emit(str(resolved))

    def _activate(self, session: DocumentSession) -> None:
        """Make a document current, releasing the file of the previous one."""
        if self._session is not None and self._session is not session:
            self._session.close()
        self._sessions[session.path] = session
        self._session = session
        self.navigation_dock.set_session(session)
        self._show_current_page()

    @property
    def document_session(self) -> DocumentSession | None:
        return self._session

    def show_page_step(self, delta: int) -> None:
        """Move through the open document one page at a time."""
        if self._session is not None:
            self.go_to_page(self._session.current_page + delta)

    def go_to_page(self, page_number: int) -> None:
        """Show another page of the open document; out-of-range is clamped."""
        if self._session is None:
            return
        self._session.go_to(page_number)
        self.guarded(self._show_current_page, title="Xem trang")

    def rotate_current_page(self, delta_degrees: int) -> None:
        """Rotate the currently displayed page and refresh the view."""
        if self._session is None:
            return
        self._session.rotate_page(self._session.current_page, delta_degrees)
        self.guarded(self._show_current_page, title="Xoay trang")

    def _show_current_page(self) -> None:
        session = self._session
        if session is None:
            return
        number = session.current_page
        result = session.result(number)
        if result is None:
            dpi = self._option_number("dpi", DEFAULT_DPI)
            image = session.image(number, dpi=dpi)
            native = session.native_text(number, dpi=dpi)
            self.comparison.set_image(image, text=_reconstruct_paragraphs(native))
        else:
            dpi = result.dpi
            image = session.image_for(result)
            self.comparison.set_page(result, image)
        self._displayed = (image, dpi)
        self._refresh_page_controls()

    def _refresh_page_controls(self) -> None:
        session = self._session
        total = session.page_count if session is not None else 0
        current = session.current_page if session is not None else 0
        self.comparison.set_page_info(current, total)
        self.navigation_dock.refresh_status()
        self.command_actions["previous_page"].setEnabled(current > 1)
        self.command_actions["next_page"].setEnabled(0 < current < total)
        self.command_actions["edit_table"].setEnabled(self.comparison.table_count() > 0)

    def open_folder(self, path: str | Path) -> None:
        """Announce a folder of documents for batch processing."""
        self.guarded(lambda: self._open_folder(path), title="Mở thư mục")

    def _open_folder(self, path: str | Path) -> None:
        target = Path(path).expanduser()
        if not target.is_dir():
            raise DocumentLoadError("Không tìm thấy thư mục đã chọn.")
        folder = target.resolve()
        documents = sorted(
            (entry for entry in folder.iterdir() if entry.is_file()),
            key=lambda entry: entry.name.lower(),
        )
        documents = [entry for entry in documents if _is_supported(entry)]
        if not documents:
            self.notifications.notify(
                "Thư mục không có tài liệu nào được hỗ trợ.", Severity.WARNING
            )
            return
        self.folder_opened.emit(str(folder))
        self._preview_first_readable(documents)
        self.run_batch([str(entry) for entry in documents])

    def _preview_first_readable(self, documents: Sequence[Path]) -> None:
        """Show the first document that opens; a corrupt one must not block the rest."""
        for document in documents:
            try:
                self._open_path(document)
            except PDFOCRError as error:
                logger.warning("Bỏ qua tài liệu không mở được {}: {}", document, error)
                continue
            return

    # -- error boundary ---------------------------------------------------

    def guarded(
        self, operation: Callable[[], ResultT], *, title: str
    ) -> ResultT | None:
        """Run a command so no failure escapes into the Qt event loop."""
        try:
            return operation()
        except PDFOCRError as error:
            logger.exception("Lệnh '{}' thất bại.", title)
            self.report_error(str(error))
        except Exception:
            logger.exception("Lệnh '{}' gặp lỗi không mong đợi.", title)
            self.report_error(PDFOCRError.default_message)
        return None

    def report_error(self, message: str) -> None:
        """Surface a failure without interrupting; an error toast waits to be read."""
        self.notifications.notify(message, Severity.ERROR)

    # -- recent files -----------------------------------------------------

    def recent_files(self) -> tuple[str, ...]:
        """Read the stored history defensively; settings files are user editable."""
        stored = self._settings.value(RECENT_FILES_KEY)
        if isinstance(stored, str):
            stored = [stored]
        if not isinstance(stored, (list, tuple)):
            return ()
        paths = tuple(item for item in stored if isinstance(item, str) and item)
        return paths[:MAX_RECENT_FILES]

    def _remember(self, path: Path) -> None:
        entry = str(path)
        history = [item for item in self.recent_files() if item != entry]
        history.insert(0, entry)
        self._settings.setValue(RECENT_FILES_KEY, history[:MAX_RECENT_FILES])
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        self.recent_files_menu.set_paths(self.recent_files())

    def clear_recent_files(self) -> None:
        """Clear the stored recent files history."""
        self._settings.setValue(RECENT_FILES_KEY, [])
        self._refresh_recent_menu()
        self.notifications.notify(
            "Đã xóa lịch sử mở tệp.", Severity.INFO, duration_ms=1500
        )

    def remove_recent_file(self, path: str) -> None:
        """Remove a single file path from the stored recent files history."""
        history = [item for item in self.recent_files() if item != path]
        self._settings.setValue(RECENT_FILES_KEY, history[:MAX_RECENT_FILES])
        self._refresh_recent_menu()

    def show_document_history(self) -> None:
        """Display the interactive DocumentHistoryDialog."""
        from src.gui.dialogs.document_history import DocumentHistoryDialog

        dialog = DocumentHistoryDialog(self.recent_files(), parent=self)
        dialog.file_selected.connect(self.open_path)
        dialog.item_removed.connect(self.remove_recent_file)
        dialog.history_cleared.connect(self.clear_recent_files)
        dialog.exec()

    # -- window state -----------------------------------------------------

    def save_session(self) -> None:
        """Persist geometry and dock layout so the next launch feels unchanged."""
        self._settings.setValue(GEOMETRY_KEY, self.saveGeometry())
        self._settings.setValue(WINDOW_STATE_KEY, self.saveState())
        self._settings.sync()

    def _restore_session(self) -> None:
        geometry = self._settings.value(GEOMETRY_KEY)
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)
        state = self._settings.value(WINDOW_STATE_KEY)
        if isinstance(state, QByteArray) and not state.isEmpty():
            self.restoreState(state)
        self._fit_to_available_screen()

    def _fit_to_available_screen(self) -> None:
        """Keep a restored window and its bottom controls above the taskbar."""
        if self.isMaximized() or self.isFullScreen():
            return
        screen = self.screen()
        if screen is None:
            return

        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame_width = frame.width() - self.width()
        frame_height = frame.height() - self.height()
        self.resize(
            min(self.width(), max(1, available.width() - frame_width)),
            min(self.height(), max(1, available.height() - frame_height)),
        )

        frame = self.frameGeometry()
        target_x = min(
            max(frame.left(), available.left()),
            available.right() - frame.width() + 1,
        )
        target_y = min(
            max(frame.top(), available.top()),
            available.bottom() - frame.height() + 1,
        )
        self.move(self.x() + target_x - frame.left(), self.y() + target_y - frame.top())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self.notifications.dismiss_all()
        self._stop_batch()
        self._jobs.waitForDone(BATCH_SHUTDOWN_MS)
        for session in self._sessions.values():
            session.close()
        self.save_session()
        super().closeEvent(event)

    # -- drag and drop ----------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if _dropped_documents(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        documents = _dropped_documents(event.mimeData())
        if not documents:
            event.ignore()
            return
        event.acceptProposedAction()
        self.open_path(documents[0])

    # -- commands ---------------------------------------------------------

    def _connect_commands(self) -> None:
        handlers: dict[str, Callable[[], None]] = {
            "open_file": self.prompt_open_file,
            "open_folder": self.prompt_open_folder,
            "document_history": self.show_document_history,
            "export": self.request_export,
            "quit": self.request_close,
            "zoom_in": lambda: self.zoom_requested.emit(1),
            "zoom_out": lambda: self.zoom_requested.emit(-1),
            "zoom_reset": lambda: self.zoom_requested.emit(0),
            "previous_page": lambda: self.show_page_step(-1),
            "next_page": lambda: self.show_page_step(1),
            "run_ocr": self.request_ocr,
            "edit_table": self.request_edit_table,
            "find_replace": self.open_find_replace,
            "settings": self.request_settings,
            "about": self.show_about,
        }
        for key, handler in handlers.items():
            if key in self.command_actions:
                self.command_actions[key].triggered.connect(handler)
        # A checkable command reports its new state, so it binds to toggled.
        self.command_actions["select_region"].toggled.connect(self.set_region_mode)
        layout_action = self.command_actions["toggle_layout"]
        layout_action.setChecked(True)
        layout_action.toggled.connect(self.comparison.set_layout_visible)
        self.comparison.table_edited.connect(self._on_table_edited)
        self.recent_files_menu.file_selected.connect(self.open_path)

    def prompt_open_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Mở tệp", str(Path.home()), document_name_filter()
        )
        if selected:
            self.open_path(selected)

    def prompt_open_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Mở thư mục", str(Path.home())
        )
        if selected:
            self.open_folder(selected)

    @staticmethod
    def _application() -> QApplication:
        application = QApplication.instance()
        if not isinstance(application, QApplication):
            raise RuntimeError("Cần khởi tạo QApplication trước khi mở cửa sổ.")
        return application

    def apply_theme_colors(self, theme: str) -> None:
        """Re-tint the tool bar icons so they stay visible in the current theme."""
        tint = ICON_COLORS.get(theme)
        self.tool_bar.apply_icon_color(QColor(tint) if tint else None)

    def retranslate(self) -> None:
        """Re-label the shell after the interface language has changed."""
        retranslate_actions(self.command_actions)
        self.recent_files_menu.setTitle(translate_menu("Tệp &gần đây"))
        for menu, (title, _keys) in zip(
            self.menuBar().actions(), MENU_LAYOUT, strict=True
        ):
            menu.setText(translate_menu(title))

    def open_find_replace(self) -> None:
        """Open the bulk-correction panel for the transcript."""
        self.comparison.open_find_replace()

    def set_region_mode(self, enabled: bool) -> None:
        """Turn region drawing on the page on or off."""
        action = self.command_actions.get("select_region")
        if action is not None and action.isChecked() != enabled:
            action.blockSignals(True)
            action.setChecked(enabled)
            action.blockSignals(False)
        self.comparison.set_region_mode(enabled)

    def recognise_region(self, region: BoundingBox) -> None:
        """Read the drawn rectangle: from the text layer, else with the OCR model."""
        self._last_region = region
        self.guarded(lambda: self._recognise_region(region), title="OCR vùng chọn")

    def rerun_region(self) -> None:
        """Read the last region again with the model chosen in the options dock."""
        region = self._last_region
        if region is None or self._session is None:
            self.notifications.notify("Hãy vẽ một vùng chọn trước.", Severity.INFO)
            return
        self.guarded(
            lambda: self._recognise_region(region, force_model=True),
            title="OCR vùng chọn",
        )

    def _engine_name(self, engine_id: str) -> str:
        for metadata in EngineRegistry.available():
            if metadata.engine_id == engine_id:
                return metadata.name
        return engine_id

    def _recognise_region(self, region: BoundingBox, force_model: bool = False) -> None:
        session, displayed = self._session, self._displayed
        if session is None or displayed is None:
            return
        image, dpi = displayed
        text = native_region_text(session.path, session.current_page, region, dpi)
        engine_id = self._option_text("engine_id", DEFAULT_ENGINE_ID)
        config = self._engine_config(engine_id)
        detect_tables = bool(config and config.get("use_tables"))
        model_name = self._engine_name(engine_id)
        self._region_engine_id = engine_id
        if text and not detect_tables and not force_model:
            self.comparison.show_region_result(
                text,
                "Nguồn: lớp chữ có sẵn của PDF (không dùng mô hình). "
                f"Bấm “OCR bằng mô hình” để nhận diện lại bằng {model_name}.",
            )
            self.region_recognised.emit(text)
            return
        worker = RegionWorker(
            image,
            region,
            engine_id,
            self._option_text("device", "cpu"),
            config=config,
            weights_manager=getattr(self._pipeline, "weights_manager", None),
            source_path=str(session.path),
            page_number=session.current_page,
            preferred_text=text if text and not force_model else "",
            emit_text=force_model or not bool(text),
            merge_paragraphs=self._options.get("merge_paragraphs") is not False,
            reading_order=self._options.get("reading_order") is not False,
        )
        worker.signals.finished.connect(self._on_region_recognised)
        worker.signals.page_finished.connect(self._on_region_page_recognised)
        worker.signals.failed.connect(
            lambda message: self._on_region_failed(message, fallback_text=text)
        )
        self._job_signals.add(worker.signals)
        self.comparison.show_region_result(
            text if text and not force_model else "Đang nhận diện vùng chọn…",
            (
                "Nguồn: lớp chữ của PDF; bảng biểu được nhận diện bằng mô hình "
                f"{model_name}"
                if text and not force_model
                else f"Nguồn: mô hình {model_name}"
            ),
        )
        self._jobs.start(worker)

    def _on_region_recognised(self, text: str) -> None:
        self._job_signals.discard(self.sender())
        model_name = self._engine_name(self._region_engine_id)
        self.comparison.show_region_result(
            text or "Không tìm thấy chữ trong vùng chọn.",
            f"Nguồn: mô hình {model_name}. Dùng “Chèn vào bản chép” để đưa vào "
            "văn bản hoặc “Sao chép”.",
        )
        self.region_recognised.emit(text)

    def _on_region_failed(self, message: str, *, fallback_text: str = "") -> None:
        self._job_signals.discard(self.sender())
        if not fallback_text:
            self.comparison.show_region_result("")
        self.report_error(message)
        self.region_failed.emit(message)

    def _on_region_page_recognised(self, result: object) -> None:
        """Persist detected region tables in the current page for editing/export."""
        self._job_signals.discard(self.sender())
        if not isinstance(result, RegionOCRResult):
            raise TypeError("Kết quả vùng OCR không đúng định dạng.")
        session = self._session
        if (
            session is None
            or str(session.path) != result.source_path
            or session.current_page != result.page_number
        ):
            return
        page = session.result(result.page_number)
        if page is None:
            return
        updated, added = merge_region_tables(page, result.page.tables)
        if not added:
            return
        session.store(updated)
        if session is self._session:
            self.guarded(self._show_current_page, title="Hiển thị bảng vùng chọn")
        self.notifications.notify(
            f"Đã thêm {added} bảng từ vùng chọn. Có thể chỉnh sửa hoặc xuất Excel.",
            Severity.SUCCESS,
        )

    def request_settings(self) -> None:
        self.settings_requested.emit()
        self.guarded(self.open_settings, title="Cài đặt")

    def request_close(self) -> None:
        """Close through the widget API while keeping the command signature void."""
        self.close()

    def request_ocr(self) -> None:
        if self._require_document():
            self.ocr_requested.emit(str(self._current_path))
            self.run_batch([str(self._current_path)])

    def request_ocr_page(self, page_number: int = 0) -> None:
        """Run OCR on a single page (defaults to the current page) in the background."""
        if not self._require_document() or self._session is None:
            return
        target = page_number if page_number >= 1 else self._session.current_page
        self.ocr_requested.emit(str(self._current_path))
        self.guarded(
            lambda: self._run_batch([str(self._current_path)], single_page=target),
            title="OCR trang",
        )

    @property
    def batch_dialog(self) -> BatchDialog | None:
        """The batch window of the run in progress, if one is open."""
        return self._batch

    def run_batch(self, documents: Sequence[str]) -> None:
        """Recognise documents in the background, never on the GUI thread."""
        if not documents:
            return
        self.guarded(lambda: self._run_batch(documents), title="Quét hàng loạt")

    def request_edit_table(self) -> None:
        """Open the grid editor for a table of the page on screen."""
        if self.comparison.table_count() == 0:
            self.notifications.notify(
                "Trang này chưa có bảng biểu. Hãy bật 'Nhận diện bảng biểu' "
                "(mô hình PaddleOCR) rồi chạy OCR.",
                Severity.INFO,
            )
            return
        self.comparison.edit_selected_table()

    def _on_table_edited(self, index: int, table: OCRTable) -> None:
        """Fold a grid edit into the page model so Excel/Word exports include it."""
        session = self._session
        if session is None:
            return
        result = session.result(session.current_page)
        if result is None or not 0 <= index < len(result.tables):
            return
        tables = list(result.tables)
        tables[index] = table
        session.store(result.with_updates(tables=tuple(tables)))
        self.notifications.notify("Đã cập nhật bảng biểu.", Severity.SUCCESS)

    def _run_batch(
        self, documents: Sequence[str], *, single_page: int | None = None
    ) -> None:
        engine_id = self._option_text("engine_id", DEFAULT_ENGINE_ID)
        session = self._pipeline.open_page_session(
            engine_id=engine_id,
            device=self._option_text("device", "cpu"),
            dpi=self._option_number("dpi", DEFAULT_DPI),
            engine_config=self._engine_config(engine_id),
            page_options=PageOptions.from_mapping(self._options),
        )
        manager = BatchManager(
            lambda task: session.recognise(
                task.document_path, single_page or task.page_number
            ),
            page_counter=(lambda _p: 1) if single_page else session.page_count,
        )
        dialog = BatchDialog(manager, documents, self)
        dialog.page_ready.connect(self._on_page_recognised)
        dialog.batch_finished.connect(lambda _progress: session.close())
        self._wire_batch_controls(manager)
        self._batch = dialog
        self.batch_status.set_running(True)
        dialog.start()

    def _engine_config(self, engine_id: str) -> dict[str, object] | None:
        """Engine settings from the dock; table support only where it exists."""
        config: dict[str, object] = {}
        params = self._options.get("engine_params")
        if isinstance(params, dict) and self._options.get("engine_id") == engine_id:
            config.update(params)
        supports_tables = any(
            metadata.engine_id == engine_id and metadata.supports_tables
            for metadata in EngineRegistry.available()
        )
        if supports_tables:
            config["use_tables"] = self._options.get("detect_tables") is not False
        return config or None

    def _option_text(self, key: str, default: str) -> str:
        """Read a dock option defensively; it may be missing or the wrong shape."""
        value = self._options.get(key)
        return value if isinstance(value, str) and value else default

    def _option_number(self, key: str, default: int) -> int:
        value = self._options.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return default
        return value

    def _wire_batch_controls(self, manager: BatchManager) -> None:
        if self._batch_controls_wired:
            self._disconnect_all(self.batch_status.pause_toggled)
            self._disconnect_all(self.batch_status.cancel_requested)
        manager.progress.connect(self.batch_status.show_progress)
        manager.finished.connect(self._on_batch_finished)
        manager.cancelled.connect(self._on_batch_stopped)
        self.batch_status.pause_toggled.connect(
            lambda paused: manager.pause() if paused else manager.resume()
        )
        self.batch_status.cancel_requested.connect(manager.cancel)
        self._batch_controls_wired = True

    @staticmethod
    def _disconnect_all(signal: SignalInstance) -> None:
        """Drop every existing listener; a signal with none yet is not an error."""
        try:
            signal.disconnect()
        except (RuntimeError, TypeError):
            pass

    def _on_batch_stopped(self, _progress: object) -> None:
        self.batch_status.set_running(False)

    def _stop_batch(self) -> None:
        """Cancel a running batch and let its in-flight page finish first."""
        if self._batch is None:
            return
        self._batch.manager.cancel()
        self._batch.manager.wait_for_completion(BATCH_SHUTDOWN_MS)

    def _on_page_recognised(self, task: PageTask, page: object) -> None:
        """Keep the result with its document and show it if it is on screen."""
        if not isinstance(page, OCRPage):
            return
        path = Path(task.document_path)
        session = self._sessions.get(path)
        if session is None:
            session = DocumentSession(path)
            self._sessions[path] = session
        session.store(page)
        if session is self._session:
            if page.page_number == session.current_page:
                self.guarded(self._show_current_page, title="Hiển thị kết quả")
            else:
                self.navigation_dock.refresh_status()

    def _on_batch_finished(self, progress: BatchProgress) -> None:
        self.batch_status.set_running(False)
        summary = f"Đã nhận diện {progress.completed}/{progress.total} trang"
        if progress.failed:
            self.notifications.notify(
                f"{summary}, {progress.failed} trang lỗi.", Severity.WARNING
            )
        else:
            self.notifications.notify(f"{summary}.", Severity.SUCCESS)

    def _on_transcript_edited(self, text: str) -> None:
        """Fold the edit into the page model so an export includes it."""
        session = self._session
        if session is None:
            return
        result = session.result(session.current_page)
        if result is not None:
            session.store(apply_transcript(result, text))

    def request_export(self) -> None:
        if self._require_document():
            self.export_requested.emit(str(self._current_path))
            self.guarded(self._export, title="Xuất tài liệu")

    def _export(self) -> None:
        """Ask where to save, then write the file off the GUI thread."""
        session = self._session
        if session is None or not session.has_results():
            self.notifications.notify(
                "Chưa có kết quả nhận diện. Hãy chạy OCR trước.", Severity.WARNING
            )
            return
        filters = export_filters()
        default_label, default_format = filters[0]
        extension = ExporterRegistry.describe(default_format).extensions[0]
        selected, chosen = QFileDialog.getSaveFileName(
            self,
            "Xuất tài liệu",
            str(session.path.with_suffix(extension)),
            ";;".join(label for label, _format in filters),
            default_label,
        )
        if not selected:
            return
        format_id, destination = resolve_export_target(selected, chosen)
        worker = ExportWorker(session.document(), format_id, destination)
        worker.signals.finished.connect(self._on_export_finished)
        worker.signals.failed.connect(self._on_export_failed)
        self._job_signals.add(worker.signals)
        self.command_actions["export"].setEnabled(False)
        self._jobs.start(worker)

    def _settle_export(self) -> None:
        self._job_signals.discard(self.sender())
        self.command_actions["export"].setEnabled(True)

    def _on_export_finished(self, path: str) -> None:
        self._settle_export()
        self.notifications.notify(f"Đã xuất {Path(path).name}", Severity.SUCCESS)
        self.export_completed.emit(path)

    def _on_export_failed(self, message: str) -> None:
        self._settle_export()
        self.report_error(message)
        self.export_failed.emit(message)

    def _require_document(self) -> bool:
        if self._current_path is not None:
            return True
        self.notifications.notify(
            "Vui lòng mở một tài liệu trước khi chạy OCR.", Severity.WARNING
        )
        return False

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "Giới thiệu",
            f"{APPLICATION_NAME}\nNhận diện văn bản và chuyển đổi tài liệu.",
        )

    def _create_document_view(self) -> QWidget:
        """Build the verification editor and route view commands into it."""
        self.comparison = ComparisonDock(self)
        self.zoom_requested.connect(self.comparison.apply_zoom)
        self.comparison.region_ocr_requested.connect(self.region_ocr_requested)
        self.comparison.page_change_requested.connect(self.go_to_page)
        self.comparison.page_rotate_requested.connect(self.rotate_current_page)
        self.comparison.region_mode_cancelled.connect(
            lambda: self.set_region_mode(False)
        )
        self.comparison.transcript_edited.connect(self._on_transcript_edited)
        self.region_ocr_requested.connect(self.recognise_region)
        self.comparison.region_rerun_requested.connect(self.rerun_region)
        return self.comparison

    def _create_navigation_dock(self) -> QDockWidget:
        """Build the left navigation and document info dock."""
        self.navigation_dock = NavigationDock(self)
        self.navigation_dock.page_selected.connect(self.go_to_page)
        self.navigation_dock.ocr_page_requested.connect(self.request_ocr_page)
        container = QDockWidget("Điều hướng & Tài liệu", self)
        container.setObjectName("navigation_dock_container")
        container.setWidget(self.navigation_dock)
        return container

    def _create_options_dock(self) -> QDockWidget:
        """Expose the per-run OCR options beside the document."""
        self.settings_dock = SettingsDock(
            self, weights_manager=getattr(self._pipeline, "weights_manager", None)
        )
        self.settings_dock.options_changed.connect(self._remember_options)
        container = QDockWidget("Tùy chọn nhận diện", self)
        container.setObjectName("options_dock")
        container.setWidget(self.settings_dock)
        return container

    def ocr_options(self) -> dict[str, object]:
        """Current engine, device, DPI and preprocessing choices."""
        return dict(self._options)

    def _remember_options(self, options: dict[str, object]) -> None:
        previous = self._options.get("engine_id")
        self._options = dict(options)
        changed = previous is not None and previous != options.get("engine_id")
        if changed and self.comparison.region_panel.isVisibleTo(self.comparison):
            name = self._engine_name(self._option_text("engine_id", DEFAULT_ENGINE_ID))
            self.comparison.set_region_source(
                f"Đã đổi sang mô hình {name}. Bấm “OCR bằng mô hình” để nhận "
                "diện lại vùng này."
            )

    def open_settings(self) -> None:
        """Show the settings dialog and apply the new weights folder at once."""
        dialog = SettingsDialog(parent=self)
        dialog.weights_directory_changed.connect(self._apply_weights_directory)
        dialog.model_imported.connect(self._on_model_imported)
        dialog.language_changed.connect(lambda _code: self.retranslate())
        dialog.theme_changed.connect(self.apply_theme_colors)
        dialog.exec()

    def _on_model_imported(self, engine_id: str, path: str) -> None:
        self.settings_dock.refresh_engine_parameters(
            getattr(self._pipeline, "weights_manager", None)
        )
        self.settings_dock.add_custom_model_choice(engine_id, path)
        self.notifications.notify(
            f"Đã nhập mô hình {Path(path).name} cho {self._engine_name(engine_id)}.",
            Severity.SUCCESS,
        )

    def _apply_weights_directory(self, directory: str) -> None:
        manager = ModelWeightsManager(directory)
        if hasattr(self._pipeline, "set_weights_manager"):
            self._pipeline.set_weights_manager(manager)
        self.settings_dock.refresh_engine_parameters(manager)
        self.statusBar().showMessage(f"Đã áp dụng thư mục weights: {directory}")


def _default_pipeline() -> PipelineService:
    try:
        weights_dir = ConfigManager().load().weights_dir
        return PipelineService(weights_manager=ModelWeightsManager(weights_dir))
    except PDFOCRError:
        return PipelineService()


def _dropped_documents(mime: QMimeData) -> tuple[Path, ...]:
    if not mime.hasUrls():
        return ()
    candidates = (Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile())
    return tuple(path for path in candidates if _is_supported(path))
