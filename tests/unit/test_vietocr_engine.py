"""VietOCR stays lazy and preserves complex Vietnamese Unicode output."""

from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.engines.vietocr_engine import VietOCREngine, _segment_lines
from src.services.weights_manager import ModelWeightsManager

pytestmark = pytest.mark.unit


def test_vietocr_recognizes_vietnamese_and_uses_managed_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    class FakeConfig:
        @staticmethod
        def load_config_from_name(name: str) -> dict[str, object]:
            seen["architecture"] = name
            return {"cnn": {"pretrained": True}}

    class FakePredictor:
        def __init__(self, config: dict[str, object]) -> None:
            seen["config"] = config

        def predict(self, image: object, return_prob: bool = False) -> object:
            assert return_prob
            assert getattr(image, "size", None) == (80, 20)
            assert not isinstance(image, np.ndarray)
            return "Cộng hòa Xã hội chủ nghĩa Việt Nam", 0.99

    modules = {
        "vietocr.tool.config": SimpleNamespace(Cfg=FakeConfig),
        "vietocr.tool.predictor": SimpleNamespace(Predictor=FakePredictor),
    }
    monkeypatch.setattr(
        "src.engines.vietocr_engine.import_module", lambda name: modules[name]
    )
    manager = ModelWeightsManager(tmp_path)
    engine = VietOCREngine(
        weights_manager=manager,
        config={"architecture": "vgg_seq2seq", "device": "auto"},
    )

    assert not engine.is_loaded
    engine.load_model()
    page = engine.recognize(np.zeros((20, 80, 3), dtype=np.uint8), page_number=2)

    assert page.page_number == 2
    assert page.blocks[0].text == "Cộng hòa Xã hội chủ nghĩa Việt Nam"
    assert page.blocks[0].lines[0].words[0].confidence == 0.99
    config = seen["config"]
    assert isinstance(config, dict)
    assert config["weights"] == str(tmp_path / "vietocr" / "vgg_seq2seq.pth")
    assert config["cnn"] == {"pretrained": False}
    assert config["device"] == "cpu"
    engine.unload_model()
    assert not engine.is_loaded


def test_segment_lines_filters_grid_and_orders_text() -> None:
    img = np.full((120, 200, 3), 255, dtype=np.uint8)
    cv2.putText(img, "Line One", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.line(img, (5, 55), (195, 55), (0, 0, 0), 2)
    cv2.putText(img, "Line Two", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    boxes = _segment_lines(img)
    assert len(boxes) == 2
    # Verify reading order top-to-bottom
    assert boxes[0][1] < boxes[1][1]


def test_detached_diacritics_are_folded_into_their_line() -> None:
    """Tone marks rendered at scan resolution must not become their own lines."""
    from src.engines.result_builder import merge_detached_marks

    lines = [(100, 100, 900, 60), (100, 300, 900, 60)]
    marks = [(200, 82, 30, 10), (600, 85, 26, 12), (500, 362, 30, 10)]

    merged = merge_detached_marks(lines + marks)

    assert merged == [(100, 82, 900, 78), (100, 300, 900, 72)]


def test_a_mark_far_from_any_line_is_kept() -> None:
    from src.engines.result_builder import merge_detached_marks

    boxes = [(100, 100, 900, 60), (400, 400, 30, 10)]

    assert merge_detached_marks(boxes) == boxes


def test_merge_detached_marks_leaves_short_real_lines_alone() -> None:
    from src.engines.result_builder import merge_detached_marks

    lines = [(100, 100, 900, 50), (100, 160, 150, 48), (100, 220, 800, 50)]

    assert merge_detached_marks(lines) == lines


def test_vietocr_multi_line_page_recognition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeConfig:
        @staticmethod
        def load_config_from_name(name: str) -> dict[str, object]:
            return {"cnn": {}}

    class FakeBatchPredictor:
        def __init__(self, config: dict[str, object]) -> None:
            pass

        def predict_batch(
            self, images: list[object], return_prob: bool = False
        ) -> tuple[list[str], list[float]]:
            assert return_prob
            return [f"Dòng {i + 1}" for i in range(len(images))], [0.95] * len(images)

    modules = {
        "vietocr.tool.config": SimpleNamespace(Cfg=FakeConfig),
        "vietocr.tool.predictor": SimpleNamespace(Predictor=FakeBatchPredictor),
    }
    monkeypatch.setattr(
        "src.engines.vietocr_engine.import_module", lambda name: modules[name]
    )

    img = np.full((120, 200, 3), 255, dtype=np.uint8)
    cv2.putText(img, "Line One", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.line(img, (5, 55), (195, 55), (0, 0, 0), 2)
    cv2.putText(img, "Line Two", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    manager = ModelWeightsManager(tmp_path)
    engine = VietOCREngine(weights_manager=manager)
    engine.load_model()
    page = engine.recognize(img, page_number=1)

    assert page.page_number == 1
    assert len(page.blocks) == 2
    assert page.blocks[0].text == "Dòng 1"
    assert page.blocks[1].text == "Dòng 2"


@pytest.mark.parametrize("architecture", ["unknown", "", 42])
def test_vietocr_rejects_unknown_architecture(architecture: object) -> None:
    with pytest.raises(Exception, match="architecture"):
        VietOCREngine(config={"architecture": architecture})


def test_lines_glued_by_tight_leading_are_split_apart() -> None:
    """A descender touching the next line must not hide that line from OCR."""
    from src.engines.result_builder import split_touching_lines

    mask = np.zeros((44, 400), dtype=np.uint8)
    for left in range(0, 400, 20):
        mask[0:16, left : left + 10] = 255  # first line of glyphs
        mask[28:44, left : left + 10] = 255  # second line of glyphs
    mask[16:28, 4:6] = 255  # a descender bridging the two lines

    pieces = split_touching_lines(mask, [(0, 0, 400, 44)])

    assert len(pieces) == 2
    first, second = sorted(pieces, key=lambda box: box[1])
    assert first[1] == 0 and first[1] + first[3] <= 28
    assert second[1] >= 16 and second[1] + second[3] == 44


def test_a_single_tall_line_is_not_split() -> None:
    from src.engines.result_builder import split_touching_lines

    mask = np.zeros((30, 400), dtype=np.uint8)
    for left in range(0, 400, 20):
        mask[4:26, left : left + 10] = 255

    assert split_touching_lines(mask, [(0, 4, 400, 22)]) == [(0, 4, 400, 22)]
