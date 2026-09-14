"""Image manipulation and conversion utilities."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PIL import Image
from PySide6.QtGui import QImage


def ensure_rgb_ndarray(arr: Any) -> np.ndarray:
    """Ensure the given input is a 3-channel RGB numpy ndarray.

    Args:
        arr: Input array or image representation.

    Returns:
        np.ndarray: 3-channel uint8 RGB numpy ndarray.

    Raises:
        TypeError: If input is not a numpy ndarray.
        ValueError: If ndarray dimensions or channels are unsupported.
    """
    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"Dữ liệu đầu vào phải là numpy ndarray, nhận được: {type(arr).__name__}"
        )

    if arr.ndim == 2:
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)

    if arr.ndim == 3:
        channels = arr.shape[2]
        if channels == 1:
            return cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
        if channels == 3:
            return arr.copy()
        if channels == 4:
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2RGB)
        raise ValueError(f"Số lượng kênh màu không được hỗ trợ: {channels}")

    raise ValueError(
        f"Số chiều mảng không được hỗ trợ: {arr.ndim}D (yêu cầu 2D hoặc 3D)"
    )


def pil_to_ndarray(image: Image.Image) -> np.ndarray:
    """Convert PIL Image to RGB numpy ndarray.

    Args:
        image: PIL Image instance.

    Returns:
        np.ndarray: 3-channel uint8 RGB ndarray.
    """
    rgb_img = image.convert("RGB")
    return np.array(rgb_img, dtype=np.uint8)


def ndarray_to_pil(arr: np.ndarray) -> Image.Image:
    """Convert RGB numpy ndarray to PIL Image.

    Args:
        arr: RGB numpy ndarray.

    Returns:
        Image.Image: PIL RGB Image.
    """
    rgb_arr = ensure_rgb_ndarray(arr)
    return Image.fromarray(rgb_arr)


def validate_image_dimensions(width: int, height: int, max_dim: int = 10000) -> None:
    """Validate image dimensions against reasonable minimum and maximum limits.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        max_dim: Maximum allowed dimension in pixels.

    Raises:
        ValueError: If dimensions are non-positive or exceed max_dim.
    """
    if width <= 0 or height <= 0:
        raise ValueError(
            f"Kích thước ảnh không hợp lệ: chiều rộng={width}, chiều cao={height}. "
            "Kích thước phải lớn hơn 0."
        )
    if width > max_dim or height > max_dim:
        raise ValueError(
            f"Kích thước ảnh vượt quá giới hạn cho phép: "
            f"({width}x{height}) > ({max_dim}x{max_dim})"
        )


def qimage_to_ndarray(qimage: QImage) -> np.ndarray:
    """Convert PySide6 QImage to RGB numpy ndarray.

    Args:
        qimage: QImage instance.

    Returns:
        np.ndarray: RGB numpy ndarray.
    """
    formatted = qimage.convertToFormat(QImage.Format.Format_RGB888)
    width = formatted.width()
    height = formatted.height()
    bytes_per_line = formatted.bytesPerLine()

    ptr = formatted.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((height, bytes_per_line))
    arr = arr[:, : width * 3].reshape((height, width, 3))
    return arr.copy()


def ndarray_to_qimage(arr: np.ndarray) -> QImage:
    """Convert RGB numpy ndarray to PySide6 QImage.

    Args:
        arr: RGB numpy ndarray.

    Returns:
        QImage: PySide6 QImage instance.
    """
    rgb_arr = ensure_rgb_ndarray(arr)
    rgb_arr = np.ascontiguousarray(rgb_arr)
    height, width, channels = rgb_arr.shape
    bytes_per_line = channels * width
    return QImage(
        rgb_arr.data,
        width,
        height,
        bytes_per_line,
        QImage.Format.Format_RGB888,
    ).copy()
