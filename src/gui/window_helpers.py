"""Stateless helper functions supporting MainWindow session, geometry, and options."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QByteArray, QMimeData, QSettings, SignalInstance
from PySide6.QtWidgets import QApplication, QMainWindow

from src.config import ConfigManager, Preferences
from src.core.document_loader import SUPPORTED_EXTENSIONS
from src.core.exceptions import PDFOCRError
from src.core.models import BoundingBox
from src.engines.engine_registry import EngineRegistry
from src.gui.components.menu_bar import MAX_RECENT_FILES
from src.services.pipeline_service import PipelineService
from src.services.weights_manager import ModelWeightsManager
from src.workers.region_worker import RegionWorker

ORGANIZATION_NAME = "PDF OCR"
APPLICATION_NAME = "PDF OCR Desktop"
RECENT_FILES_KEY = "session/recent_files"
GEOMETRY_KEY = "session/geometry"
WINDOW_STATE_KEY = "session/window_state"
DEFAULT_ENGINE_ID = "vietocr"
DEFAULT_DPI = 300
BATCH_SHUTDOWN_MS = 10_000


def document_name_filter() -> str:
    """Build the file dialog filter from the formats the loader accepts."""
    patterns = " ".join(f"*{extension}" for extension in sorted(SUPPORTED_EXTENSIONS))
    return f"Tài liệu hỗ trợ ({patterns});;Tất cả tệp (*)"


def is_supported_document(path: Path) -> bool:
    """Return whether a path has a supported document or image extension."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def list_folder_documents(folder: Path) -> list[Path]:
    """Return sorted supported document paths inside folder."""
    return sorted(
        (
            entry
            for entry in folder.iterdir()
            if entry.is_file() and is_supported_document(entry)
        ),
        key=lambda entry: entry.name.lower(),
    )


def dropped_documents(mime: QMimeData) -> tuple[Path, ...]:
    """Extract supported local document paths from a drag-and-drop QMimeData."""
    if not mime.hasUrls():
        return ()
    candidates = (Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile())
    return tuple(path for path in candidates if is_supported_document(path))


def default_pipeline() -> PipelineService:
    """Instantiate the default OCR pipeline service using configured weights."""
    try:
        weights_dir = ConfigManager().load().weights_dir
        return PipelineService(weights_manager=ModelWeightsManager(weights_dir))
    except PDFOCRError:
        return PipelineService()


def require_application() -> QApplication:
    """Return the active QApplication instance or raise RuntimeError."""
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        raise RuntimeError("Cần khởi tạo QApplication trước khi mở cửa sổ.")
    return application


def disconnect_all(signal: SignalInstance) -> None:
    """Disconnect all slots from a Qt signal without raising if none are connected."""
    try:
        signal.disconnect()
    except (RuntimeError, TypeError):
        pass


def engine_display_name(engine_id: str) -> str:
    """Look up the human-readable name for a registered OCR engine."""
    for metadata in EngineRegistry.available():
        if metadata.engine_id == engine_id:
            return metadata.name
    return engine_id


def build_engine_config(
    engine_id: str, options: dict[str, object]
) -> dict[str, object] | None:
    """Assemble engine-specific config dictionary from current settings dock options."""
    config: dict[str, object] = {}
    params = options.get("engine_params")
    if isinstance(params, dict) and options.get("engine_id") == engine_id:
        config.update(params)
    supports_tables = any(
        metadata.engine_id == engine_id and metadata.supports_tables
        for metadata in EngineRegistry.available()
    )
    if supports_tables:
        config["use_tables"] = options.get("detect_tables") is not False
    return config or None


def option_text(options: dict[str, object], key: str, default: str) -> str:
    """Return a non-empty string option value from options, or default."""
    value = options.get(key)
    return value if isinstance(value, str) and value else default


def option_number(options: dict[str, object], key: str, default: int) -> int:
    """Return a positive integer option value from options, or default."""
    value = options.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return default
    return value


def create_region_worker(
    *,
    image: np.ndarray,
    region: BoundingBox,
    engine_id: str,
    options: dict[str, object],
    config: dict[str, object] | None,
    weights_manager: ModelWeightsManager | None,
    source_path: str,
    page_number: int,
    native_text: str,
    force_model: bool,
) -> RegionWorker:
    """Instantiate a background RegionWorker from current window state."""
    return RegionWorker(
        image,
        region,
        engine_id,
        option_text(options, "device", "cpu"),
        config=config,
        weights_manager=weights_manager,
        source_path=source_path,
        page_number=page_number,
        preferred_text=native_text if native_text and not force_model else "",
        emit_text=force_model or not bool(native_text),
        merge_paragraphs=options.get("merge_paragraphs") is not False,
        reading_order=options.get("reading_order") is not False,
    )


def read_recent_files(settings: QSettings) -> tuple[str, ...]:
    """Read up to MAX_RECENT_FILES recent file paths from QSettings."""
    stored = settings.value(RECENT_FILES_KEY)
    if isinstance(stored, str):
        stored = [stored]
    if not isinstance(stored, (list, tuple)):
        return ()
    paths = tuple(item for item in stored if isinstance(item, str) and item)
    return paths[:MAX_RECENT_FILES]


def store_recent_file(settings: QSettings, path: Path) -> None:
    """Prepend a path to the recent-files list in QSettings."""
    entry = str(path)
    history = [item for item in read_recent_files(settings) if item != entry]
    history.insert(0, entry)
    settings.setValue(RECENT_FILES_KEY, history[:MAX_RECENT_FILES])


def remove_recent_file_entry(settings: QSettings, path: str) -> None:
    """Remove a specific path from the recent-files list in QSettings."""
    history = [item for item in read_recent_files(settings) if item != path]
    settings.setValue(RECENT_FILES_KEY, history[:MAX_RECENT_FILES])


def restore_window_session(window: QMainWindow, settings: QSettings) -> None:
    """Restore window geometry and dock state, clamping to available screen bounds."""
    geometry = settings.value(GEOMETRY_KEY)
    if isinstance(geometry, QByteArray) and not geometry.isEmpty():
        window.restoreGeometry(geometry)
    state = settings.value(WINDOW_STATE_KEY)
    if isinstance(state, QByteArray) and not state.isEmpty():
        window.restoreState(state)
    fit_to_available_screen(window)


def fit_to_available_screen(window: QMainWindow) -> None:
    """Clamp a non-maximized window's size and position to its screen geometry."""
    if window.isMaximized() or window.isFullScreen():
        return
    screen = window.screen()
    if screen is None:
        return
    available = screen.availableGeometry()
    frame = window.frameGeometry()
    frame_w = frame.width() - window.width()
    frame_h = frame.height() - window.height()
    window.resize(
        min(window.width(), max(1, available.width() - frame_w)),
        min(window.height(), max(1, available.height() - frame_h)),
    )
    frame = window.frameGeometry()
    target_x = min(
        max(frame.left(), available.left()),
        available.right() - frame.width() + 1,
    )
    target_y = min(
        max(frame.top(), available.top()),
        available.bottom() - frame.height() + 1,
    )
    window.move(
        window.x() + target_x - frame.left(),
        window.y() + target_y - frame.top(),
    )


def normalized_region_rect(
    region: BoundingBox | None, displayed: tuple[np.ndarray, int] | None
) -> tuple[float, float, float, float] | None:
    """Convert a pixel BoundingBox into normalized 0..1 coordinates for PDF editing."""
    if region is None or displayed is None:
        return None
    image, _dpi = displayed
    h, w = image.shape[:2]
    if w <= 0 or h <= 0:
        return None
    return (
        max(0.0, min(1.0, region.x1 / w)),
        max(0.0, min(1.0, region.y1 / h)),
        max(0.0, min(1.0, region.x2 / w)),
        max(0.0, min(1.0, region.y2 / h)),
    )


def reload_modified_pdf(window: Any) -> None:
    """Reload the active DocumentSession after an in-place PDF edit."""
    session = window.document_session
    if session is None:
        return
    session.reload()
    window.navigation_dock._populate_outline(session)
    window.guarded(window._show_current_page, title="Tải lại PDF")


def open_pdf_tools_dialog(window: Any) -> None:
    """Launch the unified PDFToolsDialog for the currently open PDF."""
    from src.gui.components.notifications import Severity
    from src.gui.dialogs.pdf_tools_dialog import PDFToolsDialog

    session = window.document_session
    if session is None or not session.is_pdf:
        window.notifications.notify(
            "Vui lòng mở một tệp PDF trước khi dùng Bộ công cụ PDF.",
            Severity.WARNING,
        )
        return
    sel = normalized_region_rect(window._last_region, window._displayed)
    cur_page = session.current_page
    session.close()
    dialog = PDFToolsDialog(
        session.path,
        current_page=cur_page,
        selection_norm=sel,
        parent=window,
    )
    dialog.pdf_modified.connect(lambda _p: reload_modified_pdf(window))
    dialog.exec()


def open_document_properties_dialog(window: Any) -> None:
    """Launch the DocumentPropertiesDialog for the active document."""
    from src.gui.components.notifications import Severity
    from src.gui.dialogs.document_properties_dialog import DocumentPropertiesDialog

    if window.current_path is None:
        window.notifications.notify(
            "Vui lòng mở một tài liệu để xem thuộc tính.", Severity.WARNING
        )
        return
    dialog = DocumentPropertiesDialog(window.current_path, parent=window)
    dialog.exec()


def _confirm_delete_page(window: Any, page_number: int) -> bool:
    prefs = getattr(window, "_preferences", None)
    if prefs is None or not getattr(prefs, "confirm_page_delete", False):
        return True
    from PySide6.QtWidgets import QMessageBox

    msg = f"Bạn có chắc chắn muốn xóa vĩnh viễn trang {page_number} khỏi tệp PDF?"
    reply = QMessageBox.question(
        window,
        "Xác nhận xóa trang",
        msg,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return bool(reply == QMessageBox.StandardButton.Yes)


def handle_page_context_action(window: Any, action_id: str, page_number: int) -> None:
    """Execute a right-click context action from NavigationDock's page list."""
    from PySide6.QtWidgets import QFileDialog

    from src.core.pdf_editor import (
        delete_pages_from_pdf,
        extract_pages_to_pdf,
        rotate_pages_in_pdf,
    )
    from src.gui.components.notifications import Severity

    session = window.document_session
    if session is None or not session.is_pdf or action_id == "ocr_page":
        return
    if action_id in ("rotate_left", "rotate_right"):
        delta = -90 if action_id == "rotate_left" else 90
        session.close()
        rotate_pages_in_pdf(session.path, [page_number], delta)
        reload_modified_pdf(window)
        window.notifications.notify(
            f"Đã xoay trang {page_number} ({delta:+d}°) và lưu vào PDF.",
            Severity.SUCCESS,
        )
    elif action_id == "delete_page":
        if not _confirm_delete_page(window, page_number):
            return
        session.close()
        delete_pages_from_pdf(session.path, [page_number])
        reload_modified_pdf(window)
        window.notifications.notify(
            f"Đã xóa trang {page_number} khỏi tệp PDF.", Severity.SUCCESS
        )
    elif action_id == "extract_page":
        default_out = session.path.with_stem(f"{session.path.stem}_p{page_number}")
        target, _ = QFileDialog.getSaveFileName(
            window, "Trích xuất trang PDF", str(default_out), "PDF (*.pdf)"
        )
        if target:
            out = extract_pages_to_pdf(session.path, [page_number], target)
            window.notifications.notify(f"Đã trích xuất {out.name}.", Severity.SUCCESS)


def apply_reading_color_mode(window: Any, mode: str) -> None:
    """Switch the page reading color mode (normal, sepia, night) and re-render."""
    combo = window.navigation_dock.reading_mode_combo
    idx = combo.findData(mode)
    if idx >= 0 and combo.currentIndex() != idx:
        combo.blockSignals(True)
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)
    session = window.document_session
    if session is not None:
        session.set_page_color_mode(mode)
        window.guarded(window._show_current_page, title="Đổi chế độ đọc")


def toggle_window_fullscreen(window: QMainWindow, enabled: bool) -> None:
    """Toggle fullscreen mode on the main application window."""
    action = getattr(window, "command_actions", {}).get("toggle_fullscreen")
    if action is not None and action.isChecked() != enabled:
        action.blockSignals(True)
        action.setChecked(enabled)
        action.blockSignals(False)
    if enabled:
        window.showFullScreen()
    else:
        window.showNormal()


def wire_navigation_dock(window: Any, dock: Any) -> None:
    """Connect NavigationDock page, OCR, search, and PDF tool signals to MainWindow."""
    dock.page_selected.connect(window.go_to_page)
    dock.ocr_page_requested.connect(window.request_ocr_page)
    dock.search_result_selected.connect(window._on_search_result_selected)
    dock.page_context_action.connect(
        lambda act, page: window.guarded(
            lambda: handle_page_context_action(window, act, page),
            title="Tác vụ trang",
        )
    )
    dock.pdf_tools_requested.connect(lambda: open_pdf_tools_dialog(window))
    dock.document_properties_requested.connect(
        lambda: open_document_properties_dialog(window)
    )
    dock.reading_mode_changed.connect(
        lambda mode: apply_reading_color_mode(window, mode)
    )


def connect_window_commands(window: Any) -> None:
    """Connect all menu and toolbar QAction commands to MainWindow handlers."""
    handlers = {
        "open_file": window.prompt_open_file,
        "open_folder": window.prompt_open_folder,
        "document_history": window.show_document_history,
        "document_properties": lambda: open_document_properties_dialog(window),
        "export": window.request_export,
        "quit": window.request_close,
        "zoom_in": lambda: window.zoom_requested.emit(1),
        "zoom_out": lambda: window.zoom_requested.emit(-1),
        "zoom_reset": lambda: window.zoom_requested.emit(0),
        "previous_page": lambda: window.show_page_step(-1),
        "next_page": lambda: window.show_page_step(1),
        "color_mode_normal": lambda: apply_reading_color_mode(window, "normal"),
        "color_mode_sepia": lambda: apply_reading_color_mode(window, "sepia"),
        "color_mode_night": lambda: apply_reading_color_mode(window, "night"),
        "run_ocr": window.request_ocr,
        "edit_table": window.request_edit_table,
        "find_replace": window.open_find_replace,
        "pdf_tools": lambda: open_pdf_tools_dialog(window),
        "settings": window.request_settings,
        "about": window.show_about,
    }
    for key, handler in handlers.items():
        if key in window.command_actions:
            window.command_actions[key].triggered.connect(handler)
    window.command_actions["select_region"].toggled.connect(window.set_region_mode)
    window.command_actions["toggle_fullscreen"].toggled.connect(
        lambda enabled: toggle_window_fullscreen(window, enabled)
    )
    layout_action = window.command_actions["toggle_layout"]
    layout_action.setChecked(True)
    layout_action.toggled.connect(window.comparison.set_layout_visible)
    window.comparison.table_edited.connect(window._on_table_edited)
    window.comparison.canvas.block_context_action.connect(
        lambda act, idx: window.guarded(
            lambda: handle_block_context_action(window, act, idx),
            title="Tác vụ khung nhận diện",
        )
    )
    window.comparison.canvas.region_context_action.connect(
        lambda act, reg: window.guarded(
            lambda: handle_region_context_action(window, act, reg),
            title="Tác vụ vùng chọn",
        )
    )
    window.recent_files_menu.file_selected.connect(window.open_path)


def handle_region_context_action(
    window: Any, action_id: str, region: BoundingBox
) -> None:
    """Handle a right-click context action on the selected region in DocumentCanvas."""
    from src.core.pdf_editor import add_highlight_annotation, redact_region_in_pdf
    from src.gui.components.notifications import Severity

    window._last_region = region
    if action_id == "ocr_region":
        window.rerun_last_region_with_model()
        return
    if action_id == "copy_region_image":
        window.notifications.notify(
            "Đã sao chép ảnh vùng chọn vào bộ nhớ tạm.", Severity.INFO
        )
        return
    if action_id == "open_pdf_tools":
        open_pdf_tools_dialog(window)
        return
    session = window.document_session
    norm = normalized_region_rect(region, window._displayed)
    if session is None or not session.is_pdf or norm is None:
        return
    cur_page = session.current_page
    session.close()
    if action_id == "highlight_region":
        add_highlight_annotation(session.path, cur_page, norm)
        reload_modified_pdf(window)
        window.notifications.notify("Đã tô sáng vùng chọn trên PDF.", Severity.SUCCESS)
    elif action_id == "redact_region":
        redact_region_in_pdf(session.path, cur_page, norm)
        reload_modified_pdf(window)
        window.notifications.notify("Đã che mật vùng chọn trên PDF.", Severity.SUCCESS)


def handle_block_context_action(window: Any, action_id: str, index: int) -> None:
    """Handle a right-click context action on a recognized bounding box."""
    from src.gui.components.notifications import Severity

    items = window.comparison.canvas.block_items()
    if not 0 <= index < len(items):
        return
    block = items[index].block
    if action_id == "copy_block_image":
        window.notifications.notify(
            "Đã sao chép ảnh vùng khung vào bộ nhớ tạm.", Severity.INFO
        )
    elif action_id == "ocr_block":
        window._last_region = block.bbox
        window.rerun_last_region_with_model()
    elif action_id in ("highlight_block", "redact_block"):
        reg_action = (
            "highlight_region" if action_id == "highlight_block" else "redact_region"
        )
        handle_region_context_action(window, reg_action, block.bbox)


def load_safe_preferences() -> Preferences:
    """Load Preferences from ConfigManager, falling back to defaults on error."""
    try:
        return ConfigManager(use_qsettings=False).load()
    except Exception:
        return Preferences()


def apply_default_zoom_mode(window: Any, mode: str) -> None:
    """Apply the configured default zoom mode onto the comparison canvas."""
    canvas = window.comparison.canvas
    if not canvas.has_page():
        return
    if mode == "fit_width":
        canvas.fit_width()
    elif mode == "actual_size":
        canvas.set_zoom_factor(1.0)
    else:
        canvas.reset_zoom()


def apply_preferences_to_window(window: Any, prefs: Preferences) -> None:
    """Propagate all 6-category Preferences live across MainWindow and its docks."""
    window._preferences = prefs
    window.settings_dock.apply_preferences(prefs)
    window.navigation_dock.set_thumbnails_enabled(prefs.show_thumbnails)
    window.comparison.set_confidence_threshold(prefs.confidence_threshold)
    window.comparison.set_spell_options(
        custom_dictionary=prefs.custom_dictionary,
        tone_style=prefs.tone_style,
    )
    postprocessor = getattr(getattr(window, "_pipeline", None), "postprocessor", None)
    if postprocessor is not None and hasattr(postprocessor, "set_options"):
        postprocessor.set_options(
            tone_style=prefs.tone_style,
            custom_dictionary=prefs.custom_dictionary,
        )
    for sess in getattr(window, "_sessions", {}).values():
        sess.set_cache_size(prefs.cache_size_pages)
        sess.set_page_color_mode(prefs.page_color_mode)
    apply_reading_color_mode(window, prefs.page_color_mode)
    apply_default_zoom_mode(window, prefs.default_zoom_mode)


def default_export_dialog_args(
    source_path: Path, prefs: Preferences
) -> tuple[str, str, str]:
    """Return (default_save_path, filter_str, default_label) using Preferences."""
    from src.exporters import ExporterRegistry
    from src.workers.export_worker import export_filters

    filters = export_filters()
    target_fmt = ExporterRegistry._resolve_id(prefs.default_export_format)
    chosen_pair = next(
        ((lbl, fmt) for lbl, fmt in filters if fmt == target_fmt),
        filters[0],
    )

    default_label, default_format = chosen_pair
    ext = ExporterRegistry.describe(default_format).extensions[0]
    base_dir = Path(prefs.output_dir) if prefs.output_dir else source_path.parent
    save_path = str(base_dir / f"{source_path.stem}{ext}")
    filter_str = ";;".join(label for label, _f in filters)
    return save_path, filter_str, default_label


def create_document_session(window: Any, resolved: Path) -> Any:
    """Create or retrieve a DocumentSession, prompting for a PDF password if locked."""
    from src.core.exceptions import PasswordRequiredError
    from src.gui.document_session import DocumentSession

    existing = window._sessions.get(resolved)
    if existing is not None:
        return existing
    prefs = getattr(window, "_preferences", Preferences())
    session = DocumentSession(
        resolved,
        cache_size=prefs.cache_size_pages,
        color_mode=prefs.page_color_mode,
    )
    try:
        _ = session.page_count
        return session
    except PasswordRequiredError:
        from PySide6.QtWidgets import QInputDialog, QLineEdit

        pwd, ok = QInputDialog.getText(
            window,
            "Mở khóa PDF",
            f"Tệp '{resolved.name}' được bảo vệ bằng mật khẩu:",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not pwd:
            raise
        unlocked = DocumentSession(
            resolved,
            cache_size=prefs.cache_size_pages,
            color_mode=prefs.page_color_mode,
            password=pwd,
        )
        _ = unlocked.page_count
        return unlocked
