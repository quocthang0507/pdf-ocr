"""Unit tests for quantitative OCR benchmark metrics (CER, CAR, WER, SC-3 & SC-4)."""

from __future__ import annotations

import json
import unicodedata

import pytest

from src.core.postprocessor import Postprocessor
from src.services.benchmark_service import (
    BenchmarkSample,
    character_accuracy_rate,
    character_error_rate,
    evaluate_samples,
    word_error_rate,
)

pytestmark = pytest.mark.unit


def test_character_and_word_error_rates_handle_nfc_and_nfd_vietnamese() -> None:
    ref = unicodedata.normalize("NFC", "Cộng hòa xã hội chủ nghĩa Việt Nam")
    hyp_nfd = unicodedata.normalize("NFD", "Cộng hòa xã hội chủ nghĩa Việt Nam")

    assert character_error_rate(ref, hyp_nfd) == pytest.approx(0.0)
    assert character_accuracy_rate(ref, hyp_nfd) == pytest.approx(1.0)
    assert word_error_rate(ref, hyp_nfd) == pytest.approx(0.0)


def test_cer_car_and_wer_on_partial_ocr_errors() -> None:
    ref = "Báo cáo tài chính năm 2026"
    hyp = "Báo cao tài chính năm 2026"  # 1 char substitution ('á' -> 'a')

    cer = character_error_rate(ref, hyp)
    car = character_accuracy_rate(ref, hyp)
    wer = word_error_rate(ref, hyp)

    assert cer == pytest.approx(1 / len(ref))
    assert car == pytest.approx(1.0 - 1 / len(ref))
    assert wer == pytest.approx(1 / 6)


def test_benchmark_report_evaluates_sc3_and_sc4_thresholds() -> None:
    processor = Postprocessor(tone_style="traditional")
    clean_ref = (
        "Có kinh nghiệm quản lý đội nhóm gồm 20 nhân viên cấp dưới. "
        "Tính tổ chức và kỷ luật cao, không ngừng đổi mới."
    )
    clean_raw = (
        "Có kinh nghiệm quản lý đội nhóm gổm 20 nhan vien cấp dưởi. "
        "Tính tổ chửc và kỷ luật cao, không ngửng đổi mởi."
    )
    degraded_ref = "Thương hiệu tiếp cận được tệp khách hàng rộng hơn trong năm 2024."
    degraded_raw = "Thuong hiệu tiếp can đưạc tệp khách hang rộng hon trong năm 2O24."

    samples = [
        BenchmarkSample(
            sample_id="clean_01",
            category="clean_scan_300dpi",
            reference=clean_ref,
            hypothesis=processor.correct_text(clean_raw),
            elapsed_ms=42.5,
        ),
        BenchmarkSample(
            sample_id="degraded_01",
            category="complex_degraded",
            reference=degraded_ref,
            hypothesis=processor.correct_text(degraded_raw),
            elapsed_ms=68.0,
        ),
    ]

    report = evaluate_samples(samples)
    assert report.passes_sc3 is True
    assert report.passes_sc4 is True
    assert report.mean_car >= 0.95
    assert report.mean_elapsed_ms == pytest.approx(55.25)

    md = report.to_markdown()
    assert "SC-3" in md
    assert "SC-4" in md
    payload = json.loads(report.to_json())
    assert payload["passes_sc3"] is True
    assert payload["passes_sc4"] is True
