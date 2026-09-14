"""Unit tests for document image enhancement: shadow removal, denoise, and CLAHE."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from src.core.exceptions import PreprocessingError
from src.core.preprocessor import (
    apply_clahe,
    denoise_image,
    enhance_document_image,
    remove_shadows,
)


@pytest.fixture
def shadowed_image() -> np.ndarray:
    """Create a synthetic document image with a dark shadow gradient

    on the left side.
    """
    h, w = 300, 400
    base = np.full((h, w, 3), 240, dtype=np.uint8)

    # Insert some text-like rectangles
    for y in range(40, 260, 40):
        cv2.rectangle(base, (60, y), (340, y + 10), (30, 30, 30), -1)

    # Apply shadow gradient (darker on the left: factor 0.3 to 1.0)
    shadow_mask = np.linspace(0.35, 1.0, w, dtype=np.float32)
    shadow_mask = np.tile(shadow_mask, (h, 1))
    shadowed = (
        (base.astype(np.float32) * shadow_mask[:, :, None])
        .clip(0, 255)
        .astype(np.uint8)
    )
    return shadowed


@pytest.fixture
def noisy_image() -> np.ndarray:
    """Create a synthetic image corrupted by Gaussian noise."""
    base = np.full((150, 150, 3), 200, dtype=np.uint8)
    noise = np.random.normal(0, 25, base.shape).astype(np.float32)
    noisy = np.clip(base.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return noisy


@pytest.fixture
def low_contrast_image() -> np.ndarray:
    """Create a low contrast document image."""
    h, w = 200, 200
    # Background around 140, text around 110
    img = np.full((h, w, 3), 140, dtype=np.uint8)
    cv2.putText(
        img, "SAMPLE", (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (110, 110, 110), 2
    )
    return img


@pytest.mark.unit
def test_remove_shadows_normalizes_background(shadowed_image: np.ndarray) -> None:
    enhanced = remove_shadows(shadowed_image)
    assert enhanced.shape == shadowed_image.shape
    assert enhanced.dtype == np.uint8

    # Compare background near left (formerly dark) vs near right
    # Left background in enhanced should be significantly brighter than in original
    orig_left_mean = np.mean(shadowed_image[10:30, 10:40])
    enh_left_mean = np.mean(enhanced[10:30, 10:40])
    assert enh_left_mean > orig_left_mean + 40


@pytest.mark.unit
def test_remove_shadows_invalid_input() -> None:
    with pytest.raises(PreprocessingError, match="hợp lệ|mảng"):
        remove_shadows("invalid_img")  # type: ignore[arg-type]


@pytest.mark.unit
def test_denoise_image_reduces_noise(noisy_image: np.ndarray) -> None:
    denoised = denoise_image(noisy_image, h=15.0)
    assert denoised.shape == noisy_image.shape
    assert denoised.dtype == np.uint8

    orig_std = float(np.std(noisy_image))
    denoised_std = float(np.std(denoised))
    assert denoised_std < orig_std


@pytest.mark.unit
def test_denoise_image_invalid_input() -> None:
    with pytest.raises(PreprocessingError, match="hợp lệ|mảng"):
        denoise_image([1, 2, 3])  # type: ignore[arg-type]


@pytest.mark.unit
def test_apply_clahe_increases_contrast(low_contrast_image: np.ndarray) -> None:
    enhanced = apply_clahe(low_contrast_image, clip_limit=3.0)
    assert enhanced.shape == low_contrast_image.shape
    assert enhanced.dtype == np.uint8

    orig_std = float(np.std(low_contrast_image))
    enh_std = float(np.std(enhanced))
    assert enh_std > orig_std


@pytest.mark.unit
def test_apply_clahe_invalid_input() -> None:
    with pytest.raises(PreprocessingError, match="hợp lệ|mảng"):
        apply_clahe(None)  # type: ignore[arg-type]


@pytest.mark.unit
def test_enhance_document_image_pipeline(shadowed_image: np.ndarray) -> None:
    enhanced = enhance_document_image(
        shadowed_image,
        remove_shadow=True,
        denoise=True,
        clahe=True,
    )
    assert enhanced.shape == shadowed_image.shape
    assert enhanced.dtype == np.uint8
