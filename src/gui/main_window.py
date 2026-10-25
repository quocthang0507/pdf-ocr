"""Desktop shell: commands, session persistence, and the GUI error boundary."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar

import numpy as np
from PySide6.QtCore import QObject, QSettings, Qt, QThreadPool, Signal
from PySide6.QtGui import QCloseEvent, QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QWidget,
)

import src.gui.window_helpers as wh
from src.constants import ICON_COLORS
from src.core.exceptions import DocumentLoadError, PDFOCRError
from src.core.models import BoundingBox, OCRPage, OCRTable
from src.core.transcript import apply_transcript
from src.core.transcript import reconstruct_paragraphs as _reconstruct_paragraphs
from src.exporters.exporter_registry import ExporterRegistry
from src.gui.components.comparison_dock import ComparisonDock
from src.gui.components.menu_bar import (
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
from src.gui.window_helpers import (
    APPLICATION_NAME,
    BATCH_SHUTDOWN_MS,
    DEFAULT_DPI,
    DEFAULT_ENGINE_ID,
    GEOMETRY_KEY,
    ORGANIZATION_NAME,
    RECENT_FILES_KEY,
    WINDOW_STATE_KEY,
    build_engine_config,
    create_region_worker,
    default_pipeline,
    disconnect_all,
    document_name_filter,
    dropped_documents,
    engine_display_name,
    fit_to_available_screen,
    is_supported_document,
    list_folder_documents,
    option_number,
    option_text,
    read_recent_files,
    remove_recent_file_entry,
    require_application,
    restore_window_session,
    store_recent_file,
)
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
    merge_region_tables,
    native_region_text,
)
from src.workers.signals import BatchProgress, PageTask

__all__ = [
    "APPLICATION_NAME",
    "MainWindow",
    "ORGANIZATION_NAME",
    "document_name_filter",
]

ResultT = TypeVar("ResultT")


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
        self._pipeline = pipeline or default_pipeline()
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
        self.apply_theme_colors(StyleManager(require_application()).current_theme)
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
        restore_window_session(self, self._settings)

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
        if not is_supported_document(target):
            raise DocumentLoadError("Định dạng tệp này chưa được hỗ trợ.")
        resolved = target.resolve()
        session = self._sessions.get(resolved) or DocumentSession(resolved)
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
        if self._session is not None:
            self.go_to_page(self._session.current_page + delta)

    def go_to_page(self, page_number: int) -> None:
        if self._session is None:
            return
        self._session.go_to(page_number)
        self.guarded(self._show_current_page, title="Xem trang")

    def rotate_current_page(self, delta_degrees: int) -> None:
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
            dpi = option_number(self._options, "dpi", DEFAULT_DPI)
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
        self.guarded(lambda: self._open_folder(path), title="Mở thư mục")

    def _open_folder(self, path: str | Path) -> None:
        target = Path(path).expanduser()
        if not target.is_dir():
            raise DocumentLoadError("Không tìm thấy thư mục đã chọn.")
        folder = target.resolve()
        documents = list_folder_documents(folder)
        if not documents:
            self.notifications.notify(
                "Thư mục không có tài liệu nào được hỗ trợ.", Severity.WARNING
            )
            return
        self.folder_opened.emit(str(folder))
        self._preview_first_readable(documents)
        self.run_batch([str(entry) for entry in documents])

    def _preview_first_readable(self, documents: Sequence[Path]) -> None:
        for document in documents:
            try:
                self._open_path(document)
                return
            except PDFOCRError as error:
                logger.warning("Bỏ qua tài liệu không mở được {}: {}", document, error)

    def guarded(
        self, operation: Callable[[], ResultT], *, title: str
    ) -> ResultT | None:
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
        self.notifications.notify(message, Severity.ERROR)

    def recent_files(self) -> tuple[str, ...]:
        return read_recent_files(self._settings)

    def _remember(self, path: Path) -> None:
        store_recent_file(self._settings, path)
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        self.recent_files_menu.set_paths(self.recent_files())

    def clear_recent_files(self) -> None:
        self._settings.setValue(RECENT_FILES_KEY, [])
        self._refresh_recent_menu()
        self.notifications.notify("Đã xóa lịch sử mở tệp.", Severity.INFO)

    def remove_recent_file(self, path: str) -> None:
        remove_recent_file_entry(self._settings, path)
        self._refresh_recent_menu()

    def show_document_history(self) -> None:
        from src.gui.dialogs.document_history import DocumentHistoryDialog

        dialog = DocumentHistoryDialog(self.recent_files(), parent=self)
        dialog.file_selected.connect(self.open_path)
        dialog.item_removed.connect(self.remove_recent_file)
        dialog.history_cleared.connect(self.clear_recent_files)
        dialog.exec()

    def _fit_to_available_screen(self) -> None:
        fit_to_available_screen(self)

    def save_session(self) -> None:
        self._settings.setValue(GEOMETRY_KEY, self.saveGeometry())
        self._settings.setValue(WINDOW_STATE_KEY, self.saveState())
        self._settings.sync()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.notifications.dismiss_all()
        self._stop_batch()
        self._jobs.waitForDone(BATCH_SHUTDOWN_MS)
        for session in self._sessions.values():
            session.close()
        self.save_session()
        super().closeEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if dropped_documents(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        documents = dropped_documents(event.mimeData())
        if not documents:
            event.ignore()
            return
        event.acceptProposedAction()
        self.open_path(documents[0])

    def _connect_commands(self) -> None:
        wh.connect_window_commands(self)

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

    def apply_theme_colors(self, theme: str) -> None:
        tint = ICON_COLORS.get(theme)
        self.tool_bar.apply_icon_color(QColor(tint) if tint else None)
        if hasattr(self, "notifications"):
            self.notifications.refresh_theme()

    def retranslate(self) -> None:
        retranslate_actions(self.command_actions)
        self.recent_files_menu.setTitle(translate_menu("Tệp &gần đây"))
        for menu, (title, _keys) in zip(
            self.menuBar().actions(), MENU_LAYOUT, strict=True
        ):
            menu.setText(translate_menu(title))

    def open_find_replace(self) -> None:
        self.comparison.open_find_replace()

    def set_region_mode(self, enabled: bool) -> None:
        action = self.command_actions.get("select_region")
        if action is not None and action.isChecked() != enabled:
            action.blockSignals(True)
            action.setChecked(enabled)
            action.blockSignals(False)
        self.comparison.set_region_mode(enabled)

    def recognise_region(self, region: BoundingBox) -> None:
        self._last_region = region
        self.guarded(lambda: self._recognise_region(region), title="OCR vùng chọn")

    def rerun_region(self) -> None:
        region = self._last_region
        if region is None or self._session is None:
            self.notifications.notify("Hãy vẽ một vùng chọn trước.", Severity.INFO)
            return
        self.guarded(
            lambda: self._recognise_region(region, force_model=True),
            title="OCR vùng chọn",
        )

    def _recognise_region(self, region: BoundingBox, force_model: bool = False) -> None:
        session, displayed = self._session, self._displayed
        if session is None or displayed is None:
            return
        image, dpi = displayed
        text = native_region_text(session.path, session.current_page, region, dpi)
        engine_id = option_text(self._options, "engine_id", DEFAULT_ENGINE_ID)
        config = build_engine_config(engine_id, self._options)
        detect_tables = bool(config and config.get("use_tables"))
        model_name = engine_display_name(engine_id)
        self._region_engine_id = engine_id
        if text and not detect_tables and not force_model:
            self.comparison.show_region_result(
                text,
                "Nguồn: lớp chữ có sẵn của PDF (không dùng mô hình). "
                f"Bấm “OCR bằng mô hình” để nhận diện lại bằng {model_name}.",
            )
            self.region_recognised.emit(text)
            return
        worker = create_region_worker(
            image=image,
            region=region,
            engine_id=engine_id,
            options=self._options,
            config=config,
            weights_manager=getattr(self._pipeline, "weights_manager", None),
            source_path=str(session.path),
            page_number=session.current_page,
            native_text=text,
            force_model=force_model,
        )
        worker.signals.finished.connect(self._on_region_recognised)
        worker.signals.page_finished.connect(self._on_region_page_recognised)
        worker.signals.failed.connect(
            lambda message: self._on_region_failed(message, fallback_text=text)
        )
        self._job_signals.add(worker.signals)
        source_msg = (
            f"Nguồn: lớp chữ PDF, bảng biểu được nhận diện bằng mô hình {model_name}"
            if text and not force_model
            else f"Nguồn: mô hình {model_name}"
        )
        self.comparison.show_region_result(
            text if text and not force_model else "Đang nhận diện vùng chọn…",
            source_msg,
        )
        self._jobs.start(worker)

    def _on_region_recognised(self, text: str) -> None:
        self._job_signals.discard(self.sender())
        model_name = engine_display_name(self._region_engine_id)
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
        self._job_signals.discard(self.sender())
        if not isinstance(result, RegionOCRResult):
            raise TypeError("Kết quả vùng OCR không đúng định dạng.")
        session = self._session
        if session is None or str(session.path) != result.source_path:
            return
        if session.current_page != result.page_number:
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
        msg = f"Đã thêm {added} bảng từ vùng chọn. Có thể chỉnh sửa hoặc xuất Excel."
        self.notifications.notify(msg, Severity.SUCCESS)

    def request_settings(self) -> None:
        self.settings_requested.emit()
        self.guarded(self.open_settings, title="Cài đặt")

    def request_close(self) -> None:
        self.close()

    def request_ocr(self) -> None:
        if self._require_document():
            self.ocr_requested.emit(str(self._current_path))
            self.run_batch([str(self._current_path)])

    def request_ocr_page(self, page_number: int = 0) -> None:
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
        return self._batch

    def run_batch(self, documents: Sequence[str]) -> None:
        if not documents:
            return
        self.guarded(lambda: self._run_batch(documents), title="Quét hàng loạt")

    def request_edit_table(self) -> None:
        if self.comparison.table_count() == 0:
            self.notifications.notify(
                "Trang này chưa có bảng biểu. Hãy bật 'Nhận diện bảng biểu' "
                "(mô hình PaddleOCR) rồi chạy OCR.",
                Severity.INFO,
            )
            return
        self.comparison.edit_selected_table()

    def _on_table_edited(self, index: int, table: OCRTable) -> None:
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
        engine_id = option_text(self._options, "engine_id", DEFAULT_ENGINE_ID)
        session = self._pipeline.open_page_session(
            engine_id=engine_id,
            device=option_text(self._options, "device", "cpu"),
            dpi=option_number(self._options, "dpi", DEFAULT_DPI),
            engine_config=build_engine_config(engine_id, self._options),
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

    def _wire_batch_controls(self, manager: BatchManager) -> None:
        if self._batch_controls_wired:
            disconnect_all(self.batch_status.pause_toggled)
            disconnect_all(self.batch_status.cancel_requested)
        manager.progress.connect(self.batch_status.show_progress)
        manager.finished.connect(self._on_batch_finished)
        manager.cancelled.connect(self._on_batch_stopped)
        self.batch_status.pause_toggled.connect(
            lambda paused: manager.pause() if paused else manager.resume()
        )
        self.batch_status.cancel_requested.connect(manager.cancel)
        self._batch_controls_wired = True

    def _on_batch_stopped(self, _progress: object) -> None:
        self.batch_status.set_running(False)

    def _stop_batch(self) -> None:
        if self._batch is None:
            return
        self._batch.manager.cancel()
        self._batch.manager.wait_for_completion(BATCH_SHUTDOWN_MS)

    def _on_page_recognised(self, task: PageTask, page: object) -> None:
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
        session = self._session
        if session is None or not session.has_results():
            self.notifications.notify(
                "Chưa có kết quả nhận diện. Hãy chạy OCR trước.", Severity.WARNING
            )
            return
        filters = export_filters()
        default_label, default_format = filters[0]
        ext = ExporterRegistry.describe(default_format).extensions[0]
        filter_str = ";;".join(label for label, _f in filters)
        selected, chosen = QFileDialog.getSaveFileName(
            self,
            "Xuất tài liệu",
            str(session.path.with_suffix(ext)),
            filter_str,
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
        msg = f"{APPLICATION_NAME}\nNhận diện văn bản và chuyển đổi tài liệu."
        QMessageBox.about(self, "Giới thiệu", msg)

    def _create_document_view(self) -> QWidget:
        self.comparison = ComparisonDock(self)
        self.zoom_requested.connect(self.comparison.apply_zoom)
        self.comparison.region_ocr_requested.connect(self.region_ocr_requested)
        self.comparison.page_change_requested.connect(self.go_to_page)
        self.comparison.page_rotate_requested.connect(self.rotate_current_page)
        self.comparison.region_mode_cancelled.connect(
            lambda: self.set_region_mode(False)
        )
        self.comparison.transcript_edited.connect(self._on_transcript_edited)
        self.comparison.transcript_copied.connect(
            lambda: self.notifications.notify("Đã sao chép văn bản.", Severity.INFO)
        )
        self.comparison.spell_correction_applied.connect(self._on_spell_corrected)
        self.region_ocr_requested.connect(self.recognise_region)
        self.comparison.region_rerun_requested.connect(self.rerun_region)
        return self.comparison

    def _on_spell_corrected(self, changed: bool) -> None:
        msg = (
            "Đã sửa chính tả tiếng Việt (Ctrl+Z để hoàn tác)."
            if changed
            else "Không phát hiện lỗi chính tả cần sửa."
        )
        self.notifications.notify(msg, Severity.SUCCESS if changed else Severity.INFO)

    def _create_navigation_dock(self) -> QDockWidget:
        self.navigation_dock = NavigationDock(self)
        wh.wire_navigation_dock(self, self.navigation_dock)
        container = QDockWidget("Điều hướng và Tài liệu", self)
        container.setObjectName("navigation_dock_container")
        container.setWidget(self.navigation_dock)
        return container

    def _on_search_result_selected(self, page_number: int, query: str) -> None:
        self.go_to_page(page_number)
        self.comparison.highlight_search_query(query)

    def _create_options_dock(self) -> QDockWidget:
        self.settings_dock = SettingsDock(
            self, weights_manager=getattr(self._pipeline, "weights_manager", None)
        )
        self.settings_dock.options_changed.connect(self._remember_options)
        container = QDockWidget("Tùy chọn nhận diện", self)
        container.setObjectName("options_dock")
        container.setWidget(self.settings_dock)
        return container

    def ocr_options(self) -> dict[str, object]:
        return dict(self._options)

    def _remember_options(self, options: dict[str, object]) -> None:
        previous = self._options.get("engine_id")
        self._options = dict(options)
        if previous and previous != options.get("engine_id"):
            if self.comparison.region_panel.isVisibleTo(self.comparison):
                name = engine_display_name(
                    option_text(self._options, "engine_id", DEFAULT_ENGINE_ID)
                )
                self.comparison.set_region_source(
                    f"Đã đổi sang mô hình {name}. Bấm “OCR bằng mô hình” để chạy lại."
                )

    def open_settings(self) -> None:
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
        name = engine_display_name(engine_id)
        self.notifications.notify(
            f"Đã nhập mô hình {Path(path).name} cho {name}.", Severity.SUCCESS
        )

    def _apply_weights_directory(self, directory: str) -> None:
        manager = ModelWeightsManager(directory)
        if hasattr(self._pipeline, "set_weights_manager"):
            self._pipeline.set_weights_manager(manager)
        self.settings_dock.refresh_engine_parameters(manager)
        self.statusBar().showMessage(f"Đã áp dụng thư mục weights: {directory}")
