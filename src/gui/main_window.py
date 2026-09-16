"""Desktop shell: commands, session persistence, and the GUI error boundary."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from PySide6.QtCore import QByteArray, QMimeData, QSettings, Qt, Signal
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QWidget,
)

from src.core.document_loader import SUPPORTED_EXTENSIONS
from src.core.exceptions import DocumentLoadError, PDFOCRError
from src.core.models import BoundingBox
from src.gui.components.comparison_dock import ComparisonDock
from src.gui.components.menu_bar import (
    MAX_RECENT_FILES,
    MENU_LAYOUT,
    ApplicationMenuBar,
    RecentFilesMenu,
    create_actions,
    retranslate_actions,
)
from src.gui.components.notifications import NotificationCenter, Severity
from src.gui.components.settings_dock import SettingsDock
from src.gui.components.tool_bar import ApplicationToolBar
from src.gui.dialogs.settings_dialog import SettingsDialog
from src.gui.i18n import translate_menu
from src.utils.logger import logger

ORGANIZATION_NAME = "PDF OCR"
APPLICATION_NAME = "PDF OCR Desktop"
RECENT_FILES_KEY = "session/recent_files"
GEOMETRY_KEY = "session/geometry"
WINDOW_STATE_KEY = "session/window_state"

ResultT = TypeVar("ResultT")


def document_name_filter() -> str:
    """Build the file dialog filter from the formats the loader accepts."""
    patterns = " ".join(f"*{extension}" for extension in sorted(SUPPORTED_EXTENSIONS))
    return f"Tài liệu hỗ trợ ({patterns});;Tất cả tệp (*)"


def _is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


class MainWindow(QMainWindow):
    """Stateful application shell; document work is published, never performed here.

    Every command runs through `guarded`, so a core failure becomes a dialog
    and a log entry instead of an unhandled exception in the Qt event loop.
    """

    document_opened = Signal(str)
    folder_opened = Signal(str)
    ocr_requested = Signal(str)
    export_requested = Signal(str)
    zoom_requested = Signal(int)
    region_ocr_requested = Signal(BoundingBox)
    settings_requested = Signal()

    def __init__(
        self, *, settings: QSettings | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._settings = settings or QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self._current_path: Path | None = None
        self._options: dict[str, object] = {}
        self.setWindowTitle(APPLICATION_NAME)
        self.setAcceptDrops(True)
        self.command_actions = create_actions(self)
        self.recent_files_menu = RecentFilesMenu(self)
        self.setMenuBar(
            ApplicationMenuBar(self.command_actions, self.recent_files_menu, self)
        )
        self.tool_bar = ApplicationToolBar(self.command_actions, self)
        self.addToolBar(self.tool_bar)
        self.setStatusBar(QStatusBar(self))
        self.notifications = NotificationCenter(self)
        self.setCentralWidget(self._create_document_view())
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self._create_options_dock()
        )
        self._connect_commands()
        self._remember_options(self.settings_dock.options())
        self._refresh_recent_menu()
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
        self.set_current_path(resolved)
        self._remember(resolved)
        self.statusBar().showMessage(f"Đã mở {resolved.name}")
        self.notifications.notify(f"Đã mở {resolved.name}", Severity.SUCCESS)
        self.document_opened.emit(str(resolved))

    def open_folder(self, path: str | Path) -> None:
        """Announce a folder of documents for batch processing."""
        self.guarded(lambda: self._open_folder(path), title="Mở thư mục")

    def _open_folder(self, path: str | Path) -> None:
        target = Path(path).expanduser()
        if not target.is_dir():
            raise DocumentLoadError("Không tìm thấy thư mục đã chọn.")
        self.folder_opened.emit(str(target.resolve()))

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

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self.notifications.dismiss_all()
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
            "export": self.request_export,
            "quit": self.request_close,
            "zoom_in": lambda: self.zoom_requested.emit(1),
            "zoom_out": lambda: self.zoom_requested.emit(-1),
            "zoom_reset": lambda: self.zoom_requested.emit(0),
            "run_ocr": self.request_ocr,
            "find_replace": self.open_find_replace,
            "settings": self.request_settings,
            "about": self.show_about,
        }
        for key, handler in handlers.items():
            self.command_actions[key].triggered.connect(handler)
        # A checkable command reports its new state, so it binds to toggled.
        self.command_actions["select_region"].toggled.connect(self.set_region_mode)
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
        self.comparison.set_region_mode(enabled)

    def request_settings(self) -> None:
        self.settings_requested.emit()
        self.guarded(self.open_settings, title="Cài đặt")

    def request_close(self) -> None:
        """Close through the widget API while keeping the command signature void."""
        self.close()

    def request_ocr(self) -> None:
        if self._require_document():
            self.ocr_requested.emit(str(self._current_path))

    def request_export(self) -> None:
        if self._require_document():
            self.export_requested.emit(str(self._current_path))

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
        return self.comparison

    def _create_options_dock(self) -> QDockWidget:
        """Expose the per-run OCR options beside the document."""
        self.settings_dock = SettingsDock(self)
        self.settings_dock.options_changed.connect(self._remember_options)
        container = QDockWidget("Tùy chọn nhận diện", self)
        container.setObjectName("options_dock")
        container.setWidget(self.settings_dock)
        return container

    def ocr_options(self) -> dict[str, object]:
        """Current engine, device, DPI and preprocessing choices."""
        return dict(self._options)

    def _remember_options(self, options: dict[str, object]) -> None:
        self._options = dict(options)

    def open_settings(self) -> None:
        """Show the settings dialog and apply the new weights folder at once."""
        dialog = SettingsDialog(parent=self)
        dialog.weights_directory_changed.connect(self._apply_weights_directory)
        dialog.language_changed.connect(lambda _code: self.retranslate())
        dialog.exec()

    def _apply_weights_directory(self, directory: str) -> None:
        self.statusBar().showMessage(f"Đã áp dụng thư mục weights: {directory}")


def _dropped_documents(mime: QMimeData) -> tuple[Path, ...]:
    if not mime.hasUrls():
        return ()
    candidates = (Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile())
    return tuple(path for path in candidates if _is_supported(path))
