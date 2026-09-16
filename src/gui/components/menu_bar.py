"""Declarative desktop commands and the standard application menu layout."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QMenuBar, QWidget

from src.gui.i18n import translate_menu

MAX_RECENT_FILES = 10
SEPARATOR = "-"
RECENT_FILES_SLOT = "@recent"


@dataclass(frozen=True)
class ActionSpec:
    """One command description, free of Qt object state so it stays shareable."""

    key: str
    text: str
    shortcut: str = ""
    status_tip: str = ""
    checkable: bool = False


ACTION_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec("open_file", "&Mở tệp…", "Ctrl+O", "Mở một tệp PDF hoặc ảnh."),
    ActionSpec(
        "open_folder",
        "Mở &thư mục…",
        "Ctrl+Shift+O",
        "Mở toàn bộ tài liệu trong một thư mục.",
    ),
    ActionSpec("export", "&Xuất tài liệu…", "Ctrl+S", "Xuất kết quả nhận diện ra tệp."),
    ActionSpec("quit", "T&hoát", "Ctrl+Q", "Đóng ứng dụng."),
    ActionSpec(
        "find_replace",
        "&Tìm và thay thế…",
        "Ctrl+H",
        "Sửa hàng loạt các lỗi nhận diện lặp lại.",
    ),
    ActionSpec("zoom_in", "&Phóng to", "Ctrl++", "Phóng to trang tài liệu."),
    ActionSpec("zoom_out", "Thu &nhỏ", "Ctrl+-", "Thu nhỏ trang tài liệu."),
    ActionSpec("zoom_reset", "Vừa &khung", "Ctrl+0", "Hiển thị vừa khung cửa sổ."),
    ActionSpec("run_ocr", "&Chạy OCR", "F5", "Nhận diện văn bản của tài liệu đang mở."),
    ActionSpec(
        "select_region",
        "Chọn &vùng OCR",
        "Ctrl+R",
        "Vẽ một vùng trên trang để chỉ nhận diện phần đó.",
        checkable=True,
    ),
    ActionSpec(
        "settings", "&Cài đặt…", "Ctrl+,", "Cấu hình thư mục weights và thiết bị chạy."
    ),
    ActionSpec(
        "document_history",
        "Lịch sử &mở tệp…",
        "",
        "Xem và quản lý toàn bộ lịch sử các tệp đã mở.",
    ),
    ActionSpec("about", "&Giới thiệu", "", "Thông tin về ứng dụng."),
)

MENU_LAYOUT: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "&Tệp",
        (
            "open_file",
            "open_folder",
            RECENT_FILES_SLOT,
            "document_history",
            SEPARATOR,
            "export",
            SEPARATOR,
            "quit",
        ),
    ),
    ("&Sửa", ("find_replace",)),
    ("&Xem", ("zoom_in", "zoom_out", "zoom_reset")),
    ("&OCR", ("run_ocr", "select_region")),
    ("Công &cụ", ("settings",)),
    ("Trợ &giúp", ("about",)),
)


def retranslate_actions(actions: Mapping[str, QAction]) -> None:
    """Re-label existing commands after the interface language has changed."""
    by_key = {spec.key: spec for spec in ACTION_SPECS}
    for key, action in actions.items():
        spec = by_key.get(key)
        if spec is not None:
            action.setText(translate_menu(spec.text))
            action.setStatusTip(translate_menu(spec.status_tip))


def create_actions(
    parent: QWidget | None = None,
) -> dict[str, QAction]:
    """Instantiate every command action with untranslated baseline strings."""
    actions: dict[str, QAction] = {}
    for spec in ACTION_SPECS:
        action = QAction(spec.text, parent)
        action.setObjectName(f"action_{spec.key}")
        action.setStatusTip(spec.status_tip)
        action.setCheckable(spec.checkable)
        if spec.shortcut:
            action.setShortcut(QKeySequence(spec.shortcut))
        actions[spec.key] = action
    return actions


class RecentFilesMenu(QMenu):
    """History submenu publishing the absolute path the user picked."""

    file_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(translate_menu("Tệp &gần đây"), parent)
        self.setObjectName("menu_recent_files")
        self.set_paths(())

    def set_paths(self, paths: Sequence[str]) -> None:
        """Replace the history, keeping at most MAX_RECENT_FILES newest entries."""
        self.clear()
        for index, path in enumerate(tuple(paths)[:MAX_RECENT_FILES], start=1):
            action = self.addAction(f"&{index}. {Path(path).name}")
            action.setData(path)
            action.setStatusTip(path)
            action.setToolTip(path)
            action.triggered.connect(partial(self.file_selected.emit, path))
        self.setEnabled(bool(paths))


class ApplicationMenuBar(QMenuBar):
    """Standard desktop menu assembled from the shared command table."""

    def __init__(
        self,
        actions: Mapping[str, QAction],
        recent_files_menu: QMenu,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("main_menu_bar")
        for title, keys in MENU_LAYOUT:
            menu = self.addMenu(translate_menu(title))
            self._fill(menu, keys, actions, recent_files_menu)

    @staticmethod
    def _fill(
        menu: QMenu,
        keys: Sequence[str],
        actions: Mapping[str, QAction],
        recent_files_menu: QMenu,
    ) -> None:
        for key in keys:
            if key == SEPARATOR:
                menu.addSeparator()
            elif key == RECENT_FILES_SLOT:
                menu.addMenu(recent_files_menu)
            else:
                menu.addAction(actions[key])
