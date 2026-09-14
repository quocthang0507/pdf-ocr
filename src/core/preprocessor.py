"""Document image preprocessing pipeline for OCR preparation."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from src.core.exceptions import PreprocessingError
from src.utils.image_utils import ensure_rgb_ndarray


def _ensure_valid_image(image: Any) -> np.ndarray:
    """Validate image array and return 3-channel RGB ndarray.

    Raises:
        PreprocessingError: If image is invalid or has invalid dimensions.
    """
    if not isinstance(image, np.ndarray):
        raise PreprocessingError(
            "Dữ liệu ảnh không hợp lệ: yêu cầu mảng numpy ndarray, "
            f"nhận được: {type(image).__name__}"
        )
    try:
        rgb = ensure_rgb_ndarray(image)
    except Exception as err:
        raise PreprocessingError(f"Không thể chuẩn hóa kênh màu ảnh: {err}") from err

    h, w = rgb.shape[:2]
    if h == 0 or w == 0:
        raise PreprocessingError(f"Ảnh có kích thước rỗng: ({w}x{h})")
    return rgb


def detect_skew_angle(image: np.ndarray, max_angle: float = 45.0) -> float:
    """Detect document skew angle in degrees (-max_angle to +max_angle).

    Uses Hough Line Transform on high-contrast text lines.

    Args:
        image: Input document image (grayscale or RGB).
        max_angle: Maximum skew angle magnitude to consider.

    Returns:
        float: Estimated skew angle in degrees.
    """
    rgb = _ensure_valid_image(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # Invert binary threshold to identify text pixels
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    pts = cv2.findNonZero(thresh)
    if pts is None or len(pts) < 50:
        return 0.0

    # Detect line segments using Probabilistic Hough Transform
    min_length = max(30, rgb.shape[1] // 6)
    lines = cv2.HoughLinesP(
        thresh,
        rho=1,
        theta=np.pi / 180,
        threshold=80,
        minLineLength=min_length,
        maxLineGap=20,
    )

    if lines is not None and len(lines) > 0:
        angles: list[float] = []
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            dx = float(x2 - x1)
            dy = float(y2 - y1)
            if abs(dx) < 1e-4:
                continue
            deg = -float(np.degrees(np.arctan2(dy, dx)))
            if abs(deg) <= max_angle:
                angles.append(deg)
        if angles:
            return float(np.median(angles))

    # Fallback to minAreaRect if Hough lines are not detected
    rect = cv2.minAreaRect(pts)
    angle = float(rect[-1])
    if angle < -45.0:
        angle = 90.0 + angle
    elif angle > 45.0:
        angle = angle - 90.0

    return float(np.clip(angle, -max_angle, max_angle))


def deskew_image(
    image: np.ndarray,
    angle: float | None = None,
    background_color: tuple[int, int, int] = (255, 255, 255),
) -> tuple[np.ndarray, float]:
    """Rotate image to correct detected or provided skew angle.

    Args:
        image: RGB input image.
        angle: Explicit skew angle in degrees. If None, angle is auto-detected.
        background_color: Fill color for borders introduced during rotation.

    Returns:
        tuple[np.ndarray, float]: (Deskewed RGB image, angle applied in degrees).
    """
    rgb = _ensure_valid_image(image)
    detected_angle = detect_skew_angle(rgb) if angle is None else float(angle)

    if abs(detected_angle) < 0.1:
        return rgb.copy(), 0.0

    h, w = rgb.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, -detected_angle, 1.0)
    deskewed = cv2.warpAffine(
        rgb,
        matrix,
        (w, h),
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=background_color,
    )
    return deskewed, detected_angle


def detect_orientation(image: np.ndarray) -> int:
    """Detect coarse orientation of document (0, 90, 180, 270 degrees).

    Args:
        image: Input document image.

    Returns:
        int: Estimated rotation in {0, 90, 180, 270}.
    """
    rgb = _ensure_valid_image(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Compute projection variance along horizontal vs vertical axes
    h_proj = np.sum(thresh, axis=1, dtype=np.float64)
    v_proj = np.sum(thresh, axis=0, dtype=np.float64)

    h_var = float(np.var(h_proj))
    v_var = float(np.var(v_proj))

    # Higher horizontal variance indicates horizontal text lines (0 or 180)
    if v_var > h_var * 1.5:
        return 90
    return 0


def rotate_orientation(image: np.ndarray, orientation: int) -> np.ndarray:
    """Rotate image to normalize specified orientation back to 0 degrees upright.

    Args:
        image: Input image array.
        orientation: Current orientation in degrees (0, 90, 180, 270).

    Returns:
        np.ndarray: Straightened image array.

    Raises:
        ValueError: If orientation is not in {0, 90, 180, 270}.
    """
    if orientation not in {0, 90, 180, 270}:
        raise ValueError(
            f"Góc xoay không hợp lệ: {orientation}. Chỉ chấp nhận 0, 90, 180, 270."
        )

    rgb = _ensure_valid_image(image)
    if orientation == 0:
        return rgb.copy()
    if orientation == 90:
        return cv2.rotate(rgb, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if orientation == 180:
        return cv2.rotate(rgb, cv2.ROTATE_180)
    return cv2.rotate(rgb, cv2.ROTATE_90_CLOCKWISE)


def remove_shadows(image: np.ndarray, kernel_size: int = 21) -> np.ndarray:
    """Remove uneven background illumination and shadows using morphological closing.

    Args:
        image: Input document image (RGB).
        kernel_size: Size of the morphological structuring element (odd integer).

    Returns:
        np.ndarray: Background-normalized RGB image.
    """
    rgb = _ensure_valid_image(image)
    if kernel_size % 2 == 0:
        kernel_size += 1

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    planes = cv2.split(rgb)
    result_planes: list[np.ndarray] = []

    for plane in planes:
        dilated = cv2.dilate(plane, kernel)
        bg = cv2.medianBlur(dilated, kernel_size)
        diff = 255 - cv2.absdiff(plane, bg)
        dst_plane = np.zeros_like(diff)
        norm = cv2.normalize(
            diff,
            dst_plane,
            alpha=0,
            beta=255,
            norm_type=cv2.NORM_MINMAX,
            dtype=cv2.CV_8U,
        )
        result_planes.append(norm)

    return cv2.merge(result_planes)


def denoise_image(
    image: np.ndarray,
    h: float = 10.0,
    template_window_size: int = 7,
    search_window_size: int = 21,
) -> np.ndarray:
    """Remove noise using Non-Local Means Denoising.

    Args:
        image: Input RGB image.
        h: Filter strength for luminance component (higher = stronger filtering).
        template_window_size: Size in pixels of template patch (odd integer).
        search_window_size: Size in pixels of window used to compute weighted average.

    Returns:
        np.ndarray: Denoised RGB image.
    """
    rgb = _ensure_valid_image(image)
    return cv2.fastNlMeansDenoisingColored(
        rgb,
        None,
        h,
        h,
        template_window_size,
        search_window_size,
    )


def apply_clahe(
    image: np.ndarray,
    clip_limit: float = 2.0,
    tile_grid_size: tuple[int, int] = (8, 8),
) -> np.ndarray:
    """Enhance text contrast using Contrast Limited Adaptive Histogram Equalization.

    Applied specifically to the luminance (L) channel in LAB color space to avoid
    altering color balance.

    Args:
        image: Input RGB image.
        clip_limit: Threshold for contrast limiting.
        tile_grid_size: Grid size for histogram equalization.

    Returns:
        np.ndarray: Contrast-enhanced RGB image.
    """
    rgb = _ensure_valid_image(image)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
    cl = clahe.apply(l_chan)

    merged = cv2.merge((cl, a_chan, b_chan))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2RGB)


def enhance_document_image(
    image: np.ndarray,
    remove_shadow: bool = True,
    denoise: bool = True,
    clahe: bool = True,
) -> np.ndarray:
    """Execute complete enhancement pipeline on document image.

    Args:
        image: Input RGB image.
        remove_shadow: Whether to perform morphological background normalization.
        denoise: Whether to run Non-Local Means denoising.
        clahe: Whether to apply CLAHE contrast enhancement.

    Returns:
        np.ndarray: Enhanced RGB image.
    """
    out = _ensure_valid_image(image)
    if remove_shadow:
        out = remove_shadows(out)
    if denoise:
        out = denoise_image(out)
    if clahe:
        out = apply_clahe(out)
    return out


def remove_borders(
    image: np.ndarray,
    margin: int = 0,
    border_threshold: int = 60,
) -> np.ndarray:
    """Detect and remove dark scanning borders from document edges.

    Args:
        image: Input document image (RGB).
        margin: Additional inward crop pixels if a border was detected.
        border_threshold: Mean intensity below which a row/col is considered border.

    Returns:
        np.ndarray: Cropped RGB image without dark scanner borders.
    """
    rgb = _ensure_valid_image(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape

    top = 0
    while top < h // 3 and float(np.mean(gray[top, :])) < border_threshold:
        top += 1

    bottom = h
    while (
        bottom > (2 * h // 3) and float(np.mean(gray[bottom - 1, :])) < border_threshold
    ):
        bottom -= 1

    left = 0
    while left < w // 3 and float(np.mean(gray[:, left])) < border_threshold:
        left += 1

    right = w
    while (
        right > (2 * w // 3) and float(np.mean(gray[:, right - 1])) < border_threshold
    ):
        right -= 1

    if top > 0 and margin > 0:
        top = min(top + margin, bottom - 1)
    if bottom < h and margin > 0:
        bottom = max(bottom - margin, top + 1)
    if left > 0 and margin > 0:
        left = min(left + margin, right - 1)
    if right < w and margin > 0:
        right = max(right - margin, left + 1)

    return rgb[top:bottom, left:right].copy()
