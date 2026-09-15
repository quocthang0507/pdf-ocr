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
