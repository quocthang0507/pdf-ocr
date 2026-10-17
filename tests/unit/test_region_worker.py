"""A selected region is read from the text layer when possible, else recognised."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf
import pytest

from src.core.exceptions import OCREngineError
from src.core.models import (
    BoundingBox,
    OCRBlock,
    OCRLine,
    OCRPage,
    OCRTable,
    OCRWord,
)
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.engine_registry import EngineRegistry
from src.workers.region_worker import RegionWorker, native_region_text

pytestmark = pytest.mark.unit

ENGINE_ID = "region-probe"


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "vung.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=100)
        page.insert_text((20, 30), "Phía trên", fontsize=12)
        page.insert_text((20, 80), "Phía dưới", fontsize=12)
        pdf.save(path)
    return path


def test_the_text_layer_inside_the_region_is_returned(tmp_path: Path) -> None:
    # 144 DPI doubles PDF points, so the top line sits around y = 40..60.
    text = native_region_text(_pdf(tmp_path), 1, BoundingBox(20, 20, 380, 90), 144)

    assert text == "Phía trên"


def test_a_region_without_text_returns_nothing(tmp_path: Path) -> None:
    assert (
        native_region_text(_pdf(tmp_path), 1, BoundingBox(300, 90, 390, 110), 144) == ""
    )


def test_an_image_has_no_text_layer(tmp_path: Path) -> None:
    image = tmp_path / "anh.png"
    image.write_bytes(b"not really an image")

    assert native_region_text(image, 1, BoundingBox(0, 0, 10, 10), 72) == ""


@pytest.fixture
def probe_engine():
    calls: list[tuple[int, int]] = []

    class ProbeEngine(BaseOCREngine):
        CONFIG_SCHEMA = {
            "device": ConfigField("cpu", lambda value: isinstance(value, str)),
            "use_tables": ConfigField(False, lambda value: isinstance(value, bool)),
        }

        def _load_model(self) -> None:
            pass

        def _unload_model(self) -> None:
            pass

        def _recognize(self, image: object, page_number: int) -> OCRPage:
            assert isinstance(image, np.ndarray)
            if image.shape[0] == 13:
                raise OCREngineError("Mô hình không đọc được vùng này.")
            calls.append(image.shape[:2])
            box = BoundingBox(0, 0, image.shape[1], image.shape[0])
            line = OCRLine(words=(OCRWord("vùng", box), OCRWord("chọn", box)), bbox=box)
            tables = (
                (OCRTable(rows=(("ô",),), bbox=BoundingBox(5, 5, 30, 20)),)
                if self._config["use_tables"]
                else ()
            )
            return OCRPage(
                page_number=page_number,
                width=float(image.shape[1]),
                height=float(image.shape[0]),
                blocks=(OCRBlock(lines=(line,), bbox=box),),
                tables=tables,
            )

    snapshot = EngineRegistry.snapshot()
    EngineRegistry.register(ENGINE_ID, "Probe", "Vùng")(ProbeEngine)
    yield calls
    EngineRegistry.restore(snapshot)


def test_the_region_is_cropped_before_recognition(qtbot, probe_engine) -> None:
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    worker = RegionWorker(image, BoundingBox(10, 20, 70, 50), ENGINE_ID, "cpu")

    with qtbot.waitSignal(worker.signals.finished) as blocker:
        worker.run()

    assert blocker.args == ["vùng chọn"]
    assert probe_engine == [(30, 60)]


def test_detected_region_tables_are_rebased_to_page_coordinates(
    qtbot, probe_engine
) -> None:
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    worker = RegionWorker(
        image,
        BoundingBox(10, 20, 70, 50),
        ENGINE_ID,
        "cpu",
        config={"use_tables": True},
        source_path="document.pdf",
        page_number=3,
    )

    with qtbot.waitSignal(worker.signals.page_finished) as blocker:
        worker.run()

    result = blocker.args[0]
    assert result.source_path == "document.pdf"
    assert result.page_number == 3
    assert result.page.tables[0].bbox == BoundingBox(15, 25, 40, 40)


def test_region_lines_are_joined_into_one_paragraph(qtbot) -> None:
    class LineEngine(BaseOCREngine):
        CONFIG_SCHEMA = {"device": ConfigField("cpu", lambda value: True)}

        def _load_model(self) -> None:
            pass

        def _unload_model(self) -> None:
            pass

        def _recognize(self, image: object, page_number: int) -> OCRPage:
            blocks = []
            for index, text in enumerate(
                ("Điều 1. Công nhận danh sách", "học viên", "kèm Quyết định này.")
            ):
                box = BoundingBox(10, 10 + index * 30, 400, 30 + index * 30)
                line = OCRLine(words=(OCRWord(text, box),), bbox=box)
                blocks.append(OCRBlock(lines=(line,), bbox=box))
            return OCRPage(page_number, 420.0, 120.0, blocks=tuple(blocks))

    snapshot = EngineRegistry.snapshot()
    EngineRegistry.register("line-probe", "Dòng", "Thử")(LineEngine)
    try:
        image = np.full((120, 420, 3), 255, dtype=np.uint8)
        worker = RegionWorker(image, BoundingBox(0, 0, 420, 120), "line-probe", "cpu")
        with qtbot.waitSignal(worker.signals.finished) as blocker:
            worker.run()
    finally:
        EngineRegistry.restore(snapshot)

    assert blocker.args == ["Điều 1. Công nhận danh sách học viên kèm Quyết định này."]


def test_a_recognition_failure_is_reported(qtbot, probe_engine) -> None:
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    worker = RegionWorker(image, BoundingBox(0, 0, 50, 13), ENGINE_ID, "cpu")

    with qtbot.waitSignal(worker.signals.failed) as blocker:
        worker.run()

    assert blocker.args == ["Mô hình không đọc được vùng này."]


def test_an_unknown_engine_is_reported_without_crashing(qtbot) -> None:
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    worker = RegionWorker(image, BoundingBox(0, 0, 50, 50), "khong-ton-tai", "cpu")

    with qtbot.waitSignal(worker.signals.failed) as blocker:
        worker.run()

    assert blocker.args[0]
