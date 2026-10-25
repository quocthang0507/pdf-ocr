"""Behavior tests for Vietnamese OCR post-processing."""

from __future__ import annotations

import unicodedata

import pytest

from src.constants import BlockType, PageType
from src.core.models import (
    BoundingBox,
    OCRBlock,
    OCRDocument,
    OCRLine,
    OCRPage,
    OCRTable,
    OCRWord,
)
from src.core.postprocessor import Postprocessor


def _word(text: str, confidence: float = 1.0) -> OCRWord:
    return OCRWord(text, BoundingBox(0, 0, 100, 20), confidence)


@pytest.mark.unit
def test_normalizes_decomposed_unicode_to_nfc() -> None:
    decomposed = unicodedata.normalize("NFD", "Tôi yêu tiếng Việt")

    corrected = Postprocessor().process_word(_word(decomposed))

    assert corrected.text == "Tôi yêu tiếng Việt"
    assert unicodedata.is_normalized("NFC", corrected.text)


@pytest.mark.unit
def test_standardizes_old_vietnamese_tone_positions() -> None:
    corrected = Postprocessor().correct_text("hòa, hóa, khỏe, thúy; HÒA")

    assert corrected == "hoà, hoá, khoẻ, thuý; HOÀ"


@pytest.mark.unit
def test_corrects_character_confusions_only_with_supporting_context() -> None:
    corrected = Postprocessor().correct_text("h0c 1ỗi tàI 2O24 1O1 VIỆT OASIS")

    assert corrected == "hoc lỗi tài 2024 101 VIỆT OASIS"


@pytest.mark.unit
def test_processes_the_complete_immutable_document_tree() -> None:
    box = BoundingBox(0, 0, 200, 50)
    line = OCRLine(words=(_word("Tôi"), _word("h0c")), bbox=box)
    block = OCRBlock(
        lines=(line,), bbox=box, block_type=BlockType.TITLE, reading_order=3
    )
    table = OCRTable(rows=(("Hòa", "2O24"),), bbox=box)
    page = OCRPage(
        page_number=1,
        width=600,
        height=800,
        blocks=(block,),
        tables=(table,),
        page_type=PageType.HYBRID,
        dpi=200,
    )
    document = OCRDocument((page,), source_path="input.pdf", title="Tài liệu")

    processed = Postprocessor().process_document(document)

    assert processed is not document
    assert processed.pages[0].blocks[0].text == "Tôi hoc"
    assert processed.pages[0].tables[0].rows == (("Hoà", "2024"),)
    assert processed.pages[0].blocks[0].block_type == BlockType.TITLE
    assert processed.pages[0].blocks[0].reading_order == 3
    assert processed.source_path == "input.pdf"
    assert processed.title == "Tài liệu"


@pytest.mark.unit
def test_preserves_confidence_and_flags_words_below_eighty_percent() -> None:
    processor = Postprocessor()

    low = processor.process_word(_word("h0c", 0.7999))
    accepted = processor.process_word(_word("h0c", 0.8))

    assert low.confidence == pytest.approx(0.7999)
    assert low.is_low_confidence
    assert accepted.confidence == pytest.approx(0.8)
    assert not accepted.is_low_confidence


@pytest.mark.unit
def test_vietnamese_spell_corrector_fixes_ngram_and_diacritic_errors() -> None:
    from src.core.spell_corrector import VietnameseSpellCorrector, is_valid_token

    corrector = VietnameseSpellCorrector()
    raw = (
        "Có kinh nghiệm lý đội nhóm gổm 20 nhan vien cấp dưởi. "
        "Tính tổ chửc và kỷ luật cao, không ngửng đổi mởi để cải thiện "
        "sản phẩm và dịch vụ đi kèm Luôn đặt trải nghiệm của khách hàng "
        "lên trên cùng và nỗ lực đưa tên tuổi thuong hiệu tiếp can đưạc "
        "tệp người rộng hon."
    )
    fixed = corrector.fix_spelling(raw)

    assert "gồm 20 nhân viên cấp dưới" in fixed
    assert "tổ chức" in fixed
    assert "không ngừng đổi mới" in fixed
    assert "thương hiệu tiếp cận được" in fixed
    assert "rộng hơn" in fixed
    assert is_valid_token("0912345678") is False
    assert is_valid_token("user@example.com") is False
    assert is_valid_token("2026") is False
    assert is_valid_token("Nguyễn_Văn") is False
    assert is_valid_token("trường") is True


@pytest.mark.unit
def test_xycut_projection_and_overlapping_box_merge() -> None:
    import numpy as np

    from src.core.layout_analyzer import (
        merge_overlapping_boxes,
        projection_by_bboxes,
        split_projection_profile,
    )

    boxes = np.array([[10, 10, 50, 30], [70, 10, 110, 30]])
    proj_x = projection_by_bboxes(boxes, axis=0)
    assert proj_x.shape == (110,)
    splits = split_projection_profile(proj_x, min_value=0, min_gap=5)
    assert splits is not None
    starts, ends = splits
    assert list(starts) == [10, 70]
    assert list(ends) == [50, 110]

    merged = merge_overlapping_boxes(
        [
            BoundingBox(10, 10, 60, 40),
            BoundingBox(50, 20, 100, 50),
            BoundingBox(150, 10, 200, 40),
        ]
    )
    assert len(merged) == 2
    assert merged[0] == BoundingBox(10, 10, 100, 50)
    assert merged[1] == BoundingBox(150, 10, 200, 40)


@pytest.mark.unit
def test_spell_corrector_restores_capitals_dropped_by_the_recogniser() -> None:
    from src.core.spell_corrector import VietnameseSpellCorrector

    corrector = VietnameseSpellCorrector()

    assert corrector.fix_spelling("ngành nghề. số lao động") == (
        "ngành nghề. Số lao động"
    )
    assert corrector.fix_spelling("Tôi tên là nguyễn Văn An") == (
        "Tôi tên là Nguyễn Văn An"
    )


@pytest.mark.unit
def test_spell_corrector_leaves_abbreviations_and_common_words_lower_case() -> None:
    from src.core.spell_corrector import VietnameseSpellCorrector

    corrector = VietnameseSpellCorrector()

    for text in ("các loại v.v. và nhiều", "đi từ Hà Nội", "chờ... rồi đi"):
        assert corrector.fix_spelling(text) == text
