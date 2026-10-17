"""Unit tests for ChandraOCREngine, DotsOCREngine, and multi-engine model variants."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.constants import BlockType
from src.core.exceptions import OCREngineError
from src.core.transcript import render_transcript
from src.engines.chandra_engine import (
    ChandraOCREngine,
    parse_chandra_output,
)
from src.engines.dots_ocr_engine import (
    DotsOCREngine,
    parse_dots_output,
)
from src.engines.easyocr_engine import EasyOCREngine
from src.engines.paddle_engine import PaddleOCREngine
from src.engines.transformer_engine import TransformerOCREngine
from src.engines.vietocr_engine import VietOCREngine
from src.services.weights_manager import ModelWeightsManager


def test_parse_chandra_html_layout_and_tables() -> None:
    html = (
        '<div data-bbox="[10, 20, 500, 80]" data-label="Title">Báo cáo Tài chính</div>'
        '<div data-bbox="[10, 100, 500, 300]" data-label="Table">'
        "<table><tr><th>Mục</th><th>Giá trị</th></tr>"
        "<tr><td>Doanh thu</td><td>100 tỷ</td></tr></table>"
        "</div>"
    )
    page = parse_chandra_output(html, width=1000, height=1000, page_number=1)

    assert len(page.blocks) == 2
    assert page.blocks[0].block_type == BlockType.TITLE
    assert "Báo cáo Tài chính" in page.blocks[0].text
    assert page.blocks[1].block_type == BlockType.TABLE
    assert len(page.tables) == 1
    assert page.tables[0].rows == (("Mục", "Giá trị"), ("Doanh thu", "100 tỷ"))


def test_parse_chandra_markdown_fallback() -> None:
    markdown = (
        "# Tiêu đề chính\n\nĐoạn văn thứ nhất.\n\n| A | B |\n|---|---|\n| 1 | 2 |"
    )
    page = parse_chandra_output(markdown, width=800, height=600, page_number=2)

    assert page.page_number == 2
    assert len(page.blocks) >= 2
    assert page.blocks[0].block_type == BlockType.HEADING_1
    assert len(page.tables) == 1
    assert page.tables[0].rows == (("A", "B"), ("1", "2"))


def test_chandra_engine_variants_and_vllm_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = ChandraOCREngine(
        config={
            "checkpoint": "datalab-to/chandra-ocr-2",
            "method": "vllm",
            "prompt_type": "ocr",
            "device": "cpu",
        },
    )
    monkeypatch.setattr(
        engine,
        "_infer_vllm",
        lambda _img: (
            '<div data-bbox="[0, 0, 100, 50]" data-label="Text">Chandra v2</div>'
        ),
    )
    engine.load_model()
    try:
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        page = engine.recognize(image, page_number=1)
    finally:
        engine.unload_model()

    assert "Chandra v2" in render_transcript(page)
    assert engine.config["checkpoint"] == "datalab-to/chandra-ocr-2"
    assert engine.config["prompt_type"] == "ocr"


def test_parse_dots_json_layout_and_html_table() -> None:
    payload = [
        {"bbox": [10, 10, 400, 60], "category": "Title", "text": "Hợp đồng Kinh tế"},
        {
            "bbox": [10, 80, 400, 250],
            "category": "Table",
            "text": "<table><tr><td>STT</td><td>Nội dung</td></tr></table>",
        },
        {"bbox": [10, 260, 400, 320], "category": "Formula", "text": "$$E = mc^2$$"},
    ]
    raw = f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
    page = parse_dots_output(raw, width=500, height=500, page_number=1)

    assert len(page.blocks) == 3
    assert page.blocks[0].block_type == BlockType.TITLE
    assert page.blocks[1].block_type == BlockType.TABLE
    assert len(page.tables) == 1
    assert page.tables[0].rows == (("STT", "Nội dung"),)
    assert "$$E = mc^2$$" in page.blocks[2].text


def test_dots_ocr_engine_variants_and_prompt_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = DotsOCREngine(
        config={
            "checkpoint": "rednote-hilab/dots.mocr",
            "method": "vllm",
            "prompt_mode": "ocr",
            "device": "cpu",
        },
    )
    monkeypatch.setattr(
        engine,
        "_infer_vllm",
        lambda _img: json.dumps(
            [{"bbox": [5, 5, 95, 45], "category": "Text", "text": "dots.mocr output"}]
        ),
    )
    engine.load_model()
    try:
        image = np.zeros((60, 120, 3), dtype=np.uint8)
        page = engine.recognize(image, page_number=1)
    finally:
        engine.unload_model()

    assert "dots.mocr output" in render_transcript(page)
    assert engine.config["checkpoint"] == "rednote-hilab/dots.mocr"
    assert engine.config["prompt_mode"] == "ocr"


def test_paddle_engine_accepts_versions_tiers_and_pipeline_modes() -> None:
    engine = PaddleOCREngine(
        config={
            "lang": "vi",
            "device": "cpu",
            "ocr_version": "PP-OCRv5",
            "model_tier": "server",
            "pipeline_mode": "pp_structure_v3",
        },
    )
    legacy, current = engine._build_ocr_options()

    assert legacy["ocr_version"] == "PP-OCRv5"
    assert current["ocr_version"] == "PP-OCRv5"
    assert current["text_detection_model_name"] == "PP-OCRv5_server_det"
    assert current["text_recognition_model_name"] == "PP-OCRv5_server_rec"
    assert engine.config["pipeline_mode"] == "pp_structure_v3"

    with pytest.raises(OCREngineError):
        PaddleOCREngine(config={"ocr_version": "PP-OCRv99"})


def test_vietocr_easyocr_and_trocr_accept_new_variants(tmp_path: Path) -> None:
    EasyOCREngine(
        config={
            "langs": ("vi", "en"),
            "recog_network": "latin_g2",
            "detect_network": "dbnet18",
        }
    )
    VietOCREngine(config={"architecture": "resnet_transformer"})
    TransformerOCREngine(config={"checkpoint": "microsoft/trocr-base-str"})

    manager = ModelWeightsManager(tmp_path)
    assert "resnet_transformer" in {
        v for _, v in manager.list_available_models("vietocr")
    }
    assert "microsoft/trocr-base-str" in {
        v for _, v in manager.list_available_models("trocr")
    }
    assert "datalab-to/chandra-ocr-2" in {
        v for _, v in manager.list_available_models("chandra")
    }
    assert "rednote-hilab/dots.mocr" in {
        v for _, v in manager.list_available_models("dots_ocr")
    }
