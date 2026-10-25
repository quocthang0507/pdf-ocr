"""Unit tests for auto orientation and deskew functionality."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from src.core.exceptions import PreprocessingError
from src.core.preprocessor import (
    deskew_image,
    detect_orientation,
    detect_skew_angle,
    rotate_orientation,
)


def create_synthetic_text_image(angle: float = 0.0) -> np.ndarray:
    """Create a synthetic document image with multiple horizontal black lines/bars

    on a white canvas, optionally rotated by a specific angle.
    """
    canvas = np.full((600, 400, 3), 255, dtype=np.uint8)
    # Draw several horizontal text-like lines
    for y in range(80, 520, 40):
        cv2.rectangle(canvas, (50, y), (350, y + 8), (0, 0, 0), -1)

    if abs(angle) < 1e-4:
        return canvas

    center = (200, 300)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        canvas,
        matrix,
        (400, 600),
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    return rotated


@pytest.mark.unit
def test_detect_skew_angle_straight_image() -> None:
    img = create_synthetic_text_image(0.0)
    angle = detect_skew_angle(img)
    assert abs(angle) < 0.5


@pytest.mark.unit
def test_detect_skew_angle_positive_skew() -> None:
    target_angle = 5.0
    img = create_synthetic_text_image(target_angle)
    detected_angle = detect_skew_angle(img)
    assert abs(detected_angle - target_angle) < 0.8


@pytest.mark.unit
def test_detect_skew_angle_negative_skew() -> None:
    target_angle = -6.0
    img = create_synthetic_text_image(target_angle)
    detected_angle = detect_skew_angle(img)
    assert abs(detected_angle - target_angle) < 0.8


@pytest.mark.unit
def test_detect_skew_angle_blank_image() -> None:
    blank = np.full((300, 300, 3), 255, dtype=np.uint8)
    angle = detect_skew_angle(blank)
    assert angle == 0.0


@pytest.mark.unit
def test_detect_skew_angle_invalid_input() -> None:
    with pytest.raises(PreprocessingError, match="hợp lệ|mảng"):
        detect_skew_angle("invalid" * 10)  # type: ignore[arg-type]


@pytest.mark.unit
def test_deskew_image_straightens_slanted_image() -> None:
    slanted = create_synthetic_text_image(4.0)
    deskewed, detected = deskew_image(slanted)
    assert abs(detected - 4.0) < 0.8
    assert deskewed.shape == slanted.shape
    assert deskewed.dtype == np.uint8

    # Residual skew on the deskewed image should be negligible
    residual_angle = detect_skew_angle(deskewed)
    assert abs(residual_angle) < 0.6


@pytest.mark.unit
def test_deskew_image_with_explicit_angle() -> None:
    slanted = create_synthetic_text_image(5.0)
    deskewed, applied_angle = deskew_image(slanted, angle=5.0)
    assert applied_angle == 5.0
    residual = detect_skew_angle(deskewed)
    assert abs(residual) < 0.6


@pytest.mark.unit
def test_detect_and_rotate_orientation_90() -> None:
    img = np.full((200, 100, 3), 255, dtype=np.uint8)
    rotated_90 = rotate_orientation(img, 90)
    assert rotated_90.shape == (100, 200, 3)

    rotated_180 = rotate_orientation(img, 180)
    assert rotated_180.shape == (200, 100, 3)

    rotated_270 = rotate_orientation(img, 270)
    assert rotated_270.shape == (100, 200, 3)

    rotated_0 = rotate_orientation(img, 0)
    assert rotated_0.shape == (200, 100, 3)


@pytest.mark.unit
def test_rotate_orientation_invalid_angle() -> None:
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="Góc xoay"):
        rotate_orientation(img, 45)


@pytest.mark.unit
def test_detect_orientation_horizontal_text() -> None:
    img = create_synthetic_text_image(0.0)
    orientation = detect_orientation(img)
    assert orientation in {0, 90, 180, 270}


def _on_gradient(image: np.ndarray) -> np.ndarray:
    """Darken the page from right to left, like a shadow across a scan."""
    ramp = np.linspace(0.3, 1.0, image.shape[1])[None, :, None]
    return (image.astype(np.float64) * ramp).astype(np.uint8)


@pytest.mark.unit
def test_uneven_lighting_does_not_flip_an_upright_page() -> None:
    page = _on_gradient(create_synthetic_text_image(0.0))

    assert detect_orientation(page) == 0


@pytest.mark.unit
def test_skew_is_measured_on_a_shadowed_page() -> None:
    page = _on_gradient(create_synthetic_text_image(5.0))

    assert abs(detect_skew_angle(page) - 5.0) < 0.8


@pytest.mark.unit
def test_deskew_does_not_paint_white_wedges_onto_a_grey_page() -> None:
    grey = np.full((300, 300, 3), 140, dtype=np.uint8)

    deskewed, _ = deskew_image(grey, angle=7.0)

    assert int(deskewed.min()) == 140 and int(deskewed.max()) == 140
