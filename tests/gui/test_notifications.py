"""In-app notifications inform without blocking, and never outlive the window."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QWidget

from src.gui.components.notifications import (
    DEFAULT_DURATION_MS,
    MAX_VISIBLE_TOASTS,
    NotificationCenter,
    Severity,
    Toast,
)
from src.gui.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def host(qtbot) -> QWidget:
    widget = QWidget()
    widget.resize(600, 400)
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def center(host: QWidget) -> NotificationCenter:
    return NotificationCenter(host)


def test_a_notification_shows_its_message(center: NotificationCenter) -> None:
    toast = center.notify("Đã mở tài liệu.", Severity.SUCCESS)

    assert isinstance(toast, Toast)
    assert toast.message_label.text() == "Đã mở tài liệu."
    assert center.visible_toasts() == [toast]


@pytest.mark.parametrize("severity", list(Severity))
def test_each_severity_has_its_own_colour_and_icon(
    center: NotificationCenter, severity: Severity
) -> None:
    toast = center.notify("Thông báo", severity)

    assert toast.severity is severity
    assert toast.accent_color().isValid()
    assert toast.icon_label.text() != ""


def test_severities_are_visually_distinct(center: NotificationCenter) -> None:
    colours = {
        center.notify("x", severity).accent_color().name() for severity in Severity
    }

    assert len(colours) == len(Severity)


def test_a_notification_does_not_block_the_window(center: NotificationCenter) -> None:
    toast = center.notify("Đang xử lý…", Severity.INFO)

    assert toast.isModal() is False
    assert toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is False


def test_notifications_stack_instead_of_overlapping(
    center: NotificationCenter,
) -> None:
    first = center.notify("Một", Severity.INFO)
    second = center.notify("Hai", Severity.INFO)

    assert second.y() > first.y()
    assert not first.geometry().intersects(second.geometry())


def test_the_oldest_notification_gives_way_when_too_many_arrive(
    center: NotificationCenter,
) -> None:
    for index in range(MAX_VISIBLE_TOASTS + 3):
        center.notify(f"Thông báo {index}", Severity.INFO)

    assert len(center.visible_toasts()) == MAX_VISIBLE_TOASTS
    assert center.visible_toasts()[0].message_label.text() == "Thông báo 3"


def test_a_notification_disappears_on_its_own(
    center: NotificationCenter, qtbot
) -> None:
    center.notify("Tự ẩn", Severity.INFO, duration_ms=60)

    qtbot.waitUntil(lambda: center.visible_toasts() == [], timeout=3000)

    assert center.visible_toasts() == []


def test_closing_a_notification_by_hand_removes_it(
    center: NotificationCenter,
) -> None:
    toast = center.notify("Đóng tay", Severity.WARNING)

    toast.close_button.click()

    assert center.visible_toasts() == []


def test_errors_stay_until_the_user_dismisses_them(
    center: NotificationCenter, qtbot
) -> None:
    toast = center.notify("Không đọc được tệp.", Severity.ERROR)

    qtbot.wait(120)

    assert toast in center.visible_toasts()
    assert toast.duration_ms == 0


def test_the_default_lifetime_is_applied_when_none_is_given(
    center: NotificationCenter,
) -> None:
    toast = center.notify("Mặc định", Severity.SUCCESS)

    assert toast.duration_ms == DEFAULT_DURATION_MS


def test_dismissing_everything_clears_the_stack(center: NotificationCenter) -> None:
    center.notify("Một", Severity.INFO)
    center.notify("Hai", Severity.ERROR)

    center.dismiss_all()

    assert center.visible_toasts() == []


def test_resizing_the_window_keeps_notifications_in_the_corner(
    center: NotificationCenter, host: QWidget
) -> None:
    toast = center.notify("Neo góc", Severity.INFO)
    before = toast.x()

    host.resize(900, 500)
    center.reposition()

    assert toast.x() != before
    assert toast.x() + toast.width() <= host.width()


# -- wired into the window --------------------------------------------------


@pytest.fixture
def window(qtbot, tmp_path) -> MainWindow:
    settings = QSettings(str(tmp_path / "session.ini"), QSettings.Format.IniFormat)
    main_window = MainWindow(settings=settings)
    qtbot.addWidget(main_window)
    return main_window


def test_opening_a_document_notifies_instead_of_interrupting(
    window: MainWindow, tmp_path
) -> None:
    document = tmp_path / "hoa-don.pdf"
    document.write_bytes(b"%PDF-1.4 fake")

    window.open_path(document)

    messages = [
        toast.message_label.text() for toast in window.notifications.visible_toasts()
    ]
    assert any("hoa-don.pdf" in message for message in messages)


def test_a_domain_failure_raises_an_error_notification(window: MainWindow) -> None:
    from src.core.exceptions import DocumentLoadError

    def failing() -> None:
        raise DocumentLoadError("Không mở được tài liệu.")

    window.guarded(failing, title="Mở tệp")

    toasts = window.notifications.visible_toasts()
    assert [toast.severity for toast in toasts] == [Severity.ERROR]
    assert toasts[0].message_label.text() == "Không mở được tài liệu."


def test_an_unexpected_failure_never_leaks_technical_detail(
    window: MainWindow,
) -> None:
    def failing() -> None:
        raise ZeroDivisionError("/home/user/secret/token.txt")

    window.guarded(failing, title="Chạy OCR")

    assert "secret" not in window.notifications.visible_toasts()[0].message_label.text()


def test_closing_the_window_with_notifications_open_is_safe(
    window: MainWindow,
) -> None:
    window.notifications.notify("Còn hiển thị", Severity.INFO)

    window.close()

    assert window.notifications.visible_toasts() == []


def test_toast_style_has_explicit_readable_colors(center: NotificationCenter) -> None:
    toast = center.notify("Thông báo rõ ràng", Severity.SUCCESS)

    style = toast.styleSheet()
    assert "palette(base)" not in style, (
        "Toast không được dùng palette(base) gây tối/đen nền."
    )
    assert "#toast_message" in style, "Cần định dạng màu chữ riêng cho toast message."
    assert "#toast_close" in style, "Cần định dạng nút đóng toast."

