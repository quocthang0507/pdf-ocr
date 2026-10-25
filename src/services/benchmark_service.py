"""Quantitative OCR accuracy and latency benchmarking service (CER, CAR, WER)."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

SC3_CLEAN_SCAN_TARGET_CAR = 0.95
SC4_DEGRADED_SCAN_TARGET_CAR = 0.85

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("Văn bản đầu vào phải là chuỗi str.")
    nfc = unicodedata.normalize("NFC", text).strip()
    return _WHITESPACE_RE.sub(" ", nfc)


def levenshtein_distance(seq_a: Sequence[Any], seq_b: Sequence[Any]) -> int:
    """Compute exact Levenshtein edit distance in O(min(N, M)) space."""
    if len(seq_a) < len(seq_b):
        seq_a, seq_b = seq_b, seq_a
    if not seq_b:
        return len(seq_a)
    previous = list(range(len(seq_b) + 1))
    for i, item_a in enumerate(seq_a, start=1):
        current = [i]
        for j, item_b in enumerate(seq_b, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (0 if item_a == item_b else 1)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Compute Character Error Rate (CER) after NFC and whitespace normalization."""
    ref = _normalize_text(reference)
    hyp = _normalize_text(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein_distance(ref, hyp) / len(ref)


def character_accuracy_rate(reference: str, hypothesis: str) -> float:
    """Compute Character Accuracy Rate (CAR = max(0, 1 - CER))."""
    return max(0.0, 1.0 - character_error_rate(reference, hypothesis))


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Compute Word Error Rate (WER) after NFC and whitespace normalization."""
    ref_words = _normalize_text(reference).split()
    hyp_words = _normalize_text(hypothesis).split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return levenshtein_distance(ref_words, hyp_words) / len(ref_words)


@dataclass(frozen=True)
class BenchmarkSample:
    """One ground-truth vs. OCR hypothesis evaluation record."""

    sample_id: str
    category: str
    reference: str
    hypothesis: str
    elapsed_ms: float = 0.0

    @property
    def cer(self) -> float:
        return character_error_rate(self.reference, self.hypothesis)

    @property
    def car(self) -> float:
        return character_accuracy_rate(self.reference, self.hypothesis)

    @property
    def wer(self) -> float:
        return word_error_rate(self.reference, self.hypothesis)


@dataclass(frozen=True)
class BenchmarkReport:
    """Aggregated OCR benchmark metrics with SC-3 and SC-4 acceptance verdicts."""

    samples: tuple[BenchmarkSample, ...]
    mean_cer: float
    mean_car: float
    mean_wer: float
    mean_elapsed_ms: float
    category_car: Mapping[str, float]
    passes_sc3: bool
    passes_sc4: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": len(self.samples),
            "mean_cer": round(self.mean_cer, 4),
            "mean_car": round(self.mean_car, 4),
            "mean_wer": round(self.mean_wer, 4),
            "mean_elapsed_ms": round(self.mean_elapsed_ms, 2),
            "category_car": {k: round(v, 4) for k, v in self.category_car.items()},
            "passes_sc3": self.passes_sc3,
            "passes_sc4": self.passes_sc4,
            "samples": [
                {
                    "sample_id": s.sample_id,
                    "category": s.category,
                    "cer": round(s.cer, 4),
                    "car": round(s.car, 4),
                    "wer": round(s.wer, 4),
                    "elapsed_ms": round(s.elapsed_ms, 2),
                }
                for s in self.samples
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        sc3_badge = "ĐẠT" if self.passes_sc3 else "CHƯA ĐẠT"
        sc4_badge = "ĐẠT" if self.passes_sc4 else "CHƯA ĐẠT"
        lines = [
            "# Báo Cáo Đo Kiểm Chất Lượng OCR Tiếng Việt",
            "",
            f"- **Số mẫu kiểm thử:** {len(self.samples)}",
            f"- **CAR trung bình:** {self.mean_car * 100:.2f}%",
            f"- **CER trung bình:** {self.mean_cer * 100:.2f}%",
            f"- **WER trung bình:** {self.mean_wer * 100:.2f}%",
            f"- **Độ trễ trung bình:** {self.mean_elapsed_ms:.1f} ms/trang",
            f"- **Nghiệm thu SC-3 (Scan rõ 300 DPI >= 95%):** {sc3_badge}",
            f"- **Nghiệm thu SC-4 (Scan phức tạp/mờ >= 85%):** {sc4_badge}",
            "",
            "| Mã mẫu | Phân loại | CAR (%) | CER (%) | WER (%) | Thời gian (ms) |",
            "| :--- | :--- | :---: | :---: | :---: | :---: |",
        ]
        for s in self.samples:
            lines.append(
                f"| `{s.sample_id}` | `{s.category}` | {s.car * 100:.2f}% | "
                f"{s.cer * 100:.2f}% | {s.wer * 100:.2f}% | {s.elapsed_ms:.1f} |"
            )
        return "\n".join(lines)


def evaluate_samples(samples: Sequence[BenchmarkSample]) -> BenchmarkReport:
    """Aggregate sample metrics into an immutable BenchmarkReport."""
    items = tuple(samples)
    if not items:
        return BenchmarkReport(
            samples=(),
            mean_cer=0.0,
            mean_car=1.0,
            mean_wer=0.0,
            mean_elapsed_ms=0.0,
            category_car={},
            passes_sc3=True,
            passes_sc4=True,
        )
    mean_cer = sum(s.cer for s in items) / len(items)
    mean_car = sum(s.car for s in items) / len(items)
    mean_wer = sum(s.wer for s in items) / len(items)
    mean_ms = sum(s.elapsed_ms for s in items) / len(items)
    by_cat: dict[str, list[float]] = {}
    for s in items:
        by_cat.setdefault(s.category, []).append(s.car)
    cat_car = {cat: sum(vals) / len(vals) for cat, vals in by_cat.items()}
    sc3 = cat_car.get("clean_scan_300dpi", 1.0) >= SC3_CLEAN_SCAN_TARGET_CAR
    sc4 = cat_car.get("complex_degraded", 1.0) >= SC4_DEGRADED_SCAN_TARGET_CAR
    return BenchmarkReport(
        samples=items,
        mean_cer=mean_cer,
        mean_car=mean_car,
        mean_wer=mean_wer,
        mean_elapsed_ms=mean_ms,
        category_car=cat_car,
        passes_sc3=sc3,
        passes_sc4=sc4,
    )
