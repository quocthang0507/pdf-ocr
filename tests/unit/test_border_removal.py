"""Unit tests for scanner black border detection and removal."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from src.core.exceptions import PreprocessingError
from src.core.preprocessor import remove_borders


@pytest.fixture
def bordered_image() -> np.ndarray:
    """Create a 500x400 document image with 30px thick black borders on all 4 edges."""
    h, w = 500, 400
    img = np.full((h, w, 3), 255, dtype=np.uint8)

    # Add text inside
    for y in range(80, 420, 50):
        cv2.putText(
            img,
            f"Line content at {y}",
            (60, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 0),
            1,
        )

    # Add black border on all 4 sides
    border_px = 30
    img[:border_px, :] = 0  # top
    img[-border_px:, :] = 0  # bottom
    img[:, :border_px] = 0  # left
    img[:, -border_px:] = 0  # right
    return img


@pytest.fixture
def clean_image() -> np.ndarray:
    """Create a clean document image without black borders."""
    h, w = 300, 300
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    cv2.putText(
        img, "Clean text", (30, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2
    )
    return img


@pytest.mark.unit
def test_remove_borders_removes_outer_black_borders(bordered_image: np.ndarray) -> None:
    cropped = remove_borders(bordered_image, margin=2)
    h_orig, w_orig = bordered_image.shape[:2]
    h_new, w_new = cropped.shape[:2]

    # The black border (>= 30px on each side) should have been cropped
    assert h_new < h_orig - 40
    assert w_new < w_orig - 40

    # Corners and edges of cropped image should no longer be black (0)
    assert np.mean(cropped[0, :]) > 100
    assert np.mean(cropped[-1, :]) > 100
    assert np.mean(cropped[:, 0]) > 100
    assert np.mean(cropped[:, -1]) > 100


@pytest.mark.unit
def test_remove_borders_preserves_clean_image(clean_image: np.ndarray) -> None:
    result = remove_borders(clean_image, margin=0)
    # Dimensions should not shrink significantly on an already clean image
    h_orig, w_orig = clean_image.shape[:2]
    h_res, w_res = result.shape[:2]
    assert abs(h_res - h_orig) <= 4
    assert abs(w_res - w_orig) <= 4


@pytest.mark.unit
def test_remove_borders_asymmetric_borders() -> None:
    h, w = 400, 300
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    cv2.putText(
        img, "Asymmetric test", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 1
    )

    # Black border on top and left only
    img[:40, :] = 10  # top
    img[:, :35] = 10  # left

    cropped = remove_borders(img, margin=0)
    h_res, w_res = cropped.shape[:2]
    assert h_res <= h - 35
    assert w_res <= w - 30


@pytest.mark.unit
def test_remove_borders_invalid_input() -> None:
    with pytest.raises(PreprocessingError, match="hợp lệ|mảng"):
        remove_borders("invalid")  # type: ignore[arg-type]
