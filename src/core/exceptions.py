"""Application failures with safe default messages for presentation boundaries."""


class PDFOCRError(Exception):
    """Base error; detailed technical causes belong in chained exceptions/logs."""

    default_message = "Không thể hoàn thành thao tác. Vui lòng thử lại."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class WeightsError(PDFOCRError):
    """Model storage, download, or integrity failure."""

    default_message = "Không thể truy cập weights. Vui lòng kiểm tra thư mục mô hình."


class OCREngineError(PDFOCRError):
    """An OCR provider could not initialize or recognize text."""

    default_message = "Nhận diện thất bại. Vui lòng thử mô hình OCR khác."


class ExportError(PDFOCRError):
    """An output document could not be written."""

    default_message = "Không thể xuất tài liệu. Vui lòng kiểm tra thư mục đích."


class PreprocessingError(PDFOCRError):
    """An input image could not be prepared for recognition."""

    default_message = "Không thể xử lý ảnh. Vui lòng kiểm tra ảnh đầu vào."


class DocumentLoadError(PDFOCRError):
    """An input document could not be opened."""

    default_message = "Không thể mở tài liệu. Vui lòng kiểm tra định dạng và mật khẩu."


class ConfigError(PDFOCRError):
    """Preferences or application logging could not be persisted."""

    default_message = "Không thể lưu cấu hình. Vui lòng kiểm tra quyền ghi thư mục."
