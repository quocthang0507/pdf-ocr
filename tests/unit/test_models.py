"""Immutable OCR trees preserve geometry, Unicode and structure in serialization."""

import json
from dataclasses import FrozenInstanceError

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

pytestmark = pytest.mark.unit


@pytest.fixture
def document() -> OCRDocument:
    box = BoundingBox(
        10, 20, 190, 60, polygon=((10, 20), (190, 22), (188, 60), (10, 58))
    )
    word = OCRWord(text="Tiếng Việt: ở, ẵ, ệ, đ", bbox=box, confidence=0.79)
    line = OCRLine(words=(word,), bbox=box, font_name="Arial", font_size=12)
    block = OCRBlock(lines=(line,), bbox=box, block_type=BlockType.TITLE)
    table = OCRTable(rows=(("Tên", "Giá"), ("Sách", "50.000")), bbox=box)
    page = OCRPage(
        page_number=1,
        width=600,
        height=800,
        blocks=(block,),
        tables=(table,),
        page_type=PageType.HYBRID,
    )
    return OCRDocument(pages=(page,), source_path="tài liệu.pdf", title="Thử nghiệm")


def test_every_model_rejects_in_place_assignment(document: OCRDocument) -> None:
    page = document.pages[0]
    block = page.blocks[0]
    line = block.lines[0]
    word = line.words[0]
    for model, field in [
        (document, "title"),
        (page, "width"),
        (block, "block_type"),
        (line, "words"),
        (word, "text"),
        (page.tables[0], "rows"),
        (word.bbox, "x1"),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(model, field, None)


def test_nested_input_lists_are_defensively_frozen() -> None:
    points = [[0, 0], [20, 0], [20, 10], [0, 10]]
    box = BoundingBox(0, 0, 20, 10, polygon=points)
    words = [OCRWord("word", box)]
    line = OCRLine(words=words, bbox=box)
    rows = [["original"]]
    table = OCRTable(rows=rows, bbox=box)
    points[0][0] = 99
    words.clear()
    rows[0][0] = "changed"
    assert box.polygon[0] == (0, 0)
    assert line.words[0].text == "word"
    assert table.rows == (("original",),)
    assert isinstance(hash(table), int)


def test_functional_copy_leaves_original_tree_unchanged(document: OCRDocument) -> None:
    word = document.pages[0].blocks[0].lines[0].words[0]
    updated = word.with_updates(text="Đã sửa", confidence=1.0)
    assert word.text == "Tiếng Việt: ở, ẵ, ệ, đ"
    assert updated.text == "Đã sửa"
    assert not updated.is_low_confidence
    with pytest.raises(ValueError):
        word.with_updates(confidence=2.0)


def test_dict_and_json_round_trip_preserve_all_models(document: OCRDocument) -> None:
    payload = document.to_dict()
    assert payload["pages"][0]["page_type"] == "hybrid"
    assert isinstance(payload["pages"], list)
    assert OCRDocument.from_dict(payload) == document
    encoded = document.to_json()
    assert "Tiếng Việt" in encoded
    assert OCRDocument.from_json(encoded) == document
    assert json.loads(encoded) == payload
    payload["pages"][0]["blocks"][0]["lines"][0]["words"][0]["text"] = "changed"
    assert document.pages[0].blocks[0].text == "Tiếng Việt: ở, ẵ, ệ, đ"


def test_each_model_can_round_trip_independently(document: OCRDocument) -> None:
    page = document.pages[0]
    block = page.blocks[0]
    line = block.lines[0]
    word = line.words[0]
    for model in (document, page, block, line, word, word.bbox, page.tables[0]):
        assert type(model).from_json(model.to_json()) == model


def test_polygon_constructor_computes_axis_aligned_envelope() -> None:
    box = BoundingBox.from_polygon(((2, 1), (6, 2), (5, 8), (1, 7)))
    assert (box.x1, box.y1, box.x2, box.y2) == (1, 1, 6, 8)
    assert (box.width, box.height) == (5, 7)


@pytest.mark.parametrize(
    "confidence, expected", [(0, True), (0.7999, True), (0.8, False), (1, False)]
)
def test_low_confidence_threshold(confidence: float, expected: bool) -> None:
    assert (
        OCRWord("text", BoundingBox(0, 0, 1, 1), confidence).is_low_confidence
        is expected
    )


@pytest.mark.parametrize(
    "confidence", [-0.01, 1.01, float("nan"), float("inf"), "0.5", True]
)
def test_invalid_confidence_is_rejected(confidence: object) -> None:
    with pytest.raises(ValueError):
        OCRWord("text", BoundingBox(0, 0, 1, 1), confidence)


@pytest.mark.parametrize(
    "coordinates", [(-1, 0, 1, 1), (3, 0, 1, 1), (0, 2, 1, 1), (0, 0, float("inf"), 1)]
)
def test_invalid_box_is_rejected(coordinates: tuple[float, ...]) -> None:
    with pytest.raises(ValueError):
        BoundingBox(*coordinates)


@pytest.mark.parametrize(
    "polygon", [((0, 0), (1, 1)), ((0, 0), (1, 1), (3, 0)), ((0,), (1, 1), (0, 1))]
)
def test_invalid_polygon_is_rejected(polygon: tuple[tuple[int, ...], ...]) -> None:
    with pytest.raises(ValueError):
        BoundingBox(0, 0, 2, 2, polygon=polygon)


@pytest.mark.parametrize("block_type", list(BlockType))
def test_all_block_types_are_serializable(block_type: BlockType) -> None:
    block = OCRBlock(lines=(), bbox=BoundingBox(0, 0, 10, 10), block_type=block_type)
    assert OCRBlock.from_dict(block.to_dict()).block_type is block_type


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        '{"unexpected": 1}',
        '{"pages": [42]}',
        '{"pages": "text"}',
        '{"pages": [{"page_number": 0, "width": 10, "height": 20}]}',
    ],
)
def test_malformed_document_payload_is_rejected(payload: str) -> None:
    with pytest.raises(ValueError):
        OCRDocument.from_json(payload)


def test_rejects_mutable_objects_in_domain_fields() -> None:
    box = BoundingBox(0, 0, 1, 1)
    with pytest.raises(ValueError):
        OCRLine(words=({"text": "mutable"},), bbox=box)
    with pytest.raises(ValueError):
        OCRWord(text=[], bbox=box)
    with pytest.raises(ValueError):
        OCRTable(rows=((["mutable"],),), bbox=box)


def test_table_requires_rectangular_rows() -> None:
    with pytest.raises(ValueError):
        OCRTable(rows=(("a", "b"), ("c",)), bbox=BoundingBox(0, 0, 1, 1))


def test_oversized_numeric_input_raises_validation_error() -> None:
    with pytest.raises(ValueError):
        BoundingBox.from_dict({"x1": 0, "y1": 0, "x2": 10**400, "y2": 1})
