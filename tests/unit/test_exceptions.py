"""Typed failures can be handled at a single application boundary."""

import pytest

from src.core.exceptions import (
    ConfigError,
    DocumentLoadError,
    ExportError,
    OCREngineError,
    PDFOCRError,
    PreprocessingError,
    WeightsError,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "error_type",
    [
        WeightsError,
        OCREngineError,
        ExportError,
        PreprocessingError,
        DocumentLoadError,
        ConfigError,
    ],
)
def test_errors_have_friendly_defaults_and_share_base(
    error_type: type[PDFOCRError],
) -> None:
    with pytest.raises(PDFOCRError) as caught:
        raise error_type()
    assert type(caught.value) is error_type
    assert str(caught.value)


def test_custom_message_and_original_cause_are_preserved() -> None:
    cause = PermissionError("details for the developer")
    with pytest.raises(WeightsError) as caught:
        raise WeightsError("Vui lòng chọn thư mục có quyền ghi.") from cause
    assert str(caught.value) == "Vui lòng chọn thư mục có quyền ghi."
    assert caught.value.__cause__ is cause
