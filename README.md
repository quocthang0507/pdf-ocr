# pdf-ocr

Ứng dụng desktop OCR đa mô hình theo [kế hoạch triển khai](docs/implementation_plan.md).
Tiến độ được ghi tại [checklist](docs/checklist.md).

## Cài đặt môi trường phát triển

Yêu cầu Python 3.10 trở lên (giai đoạn 1 được kiểm tra với Python 3.12).
Trong PowerShell, tại thư mục dự án:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m pip install -r requirements-dev.txt
```

Nếu không kích hoạt môi trường, dùng `.\.venv\Scripts\python.exe -m ...`.
Gói mặc định chứa GUI, xử lý tài liệu và logging. Các thư viện AI nặng dành cho
provider ở giai đoạn 3 được khai báo riêng trong extra `ocr`; cài bằng
`python -m pip install -e ".[ocr]"`. `requirements.txt` liệt kê toàn bộ stack
và phiên bản tối thiểu theo đặc tả. Chưa tải model weights khi cài đặt hay import.

## Kiểm tra

```powershell
python -m pytest tests/ --cov=src --cov-report=term-missing
python -m ruff check src/ tests/
python -m black --check src/ tests/
python -X utf8 -m isort --check-only src/ tests/
python -m mypy src/
python -m bandit -c pyproject.toml -r src/
```

Coverage yêu cầu tối thiểu 80%; markers gồm `unit`, `integration`, `gui`.
Các kiểm thử nền tảng dùng thư mục tạm và không tải weights hoặc gọi dịch vụ OCR.
Trên Windows, `-X utf8` giúp isort kiểm tra đầy đủ mã nguồn tiếng Việt khi
terminal dùng bảng mã cũ.

## Cấu trúc

- `src/core/`: domain models và ngoại lệ, độc lập GUI.
- `src/services/`: điều phối nghiệp vụ và quản lý weights.
- `src/engines/`, `src/exporters/`: các provider được triển khai sau.
- `src/gui/`, `src/workers/`: giao diện và xử lý nền được triển khai sau.
- `src/utils/`: logging và kiểm tra đường dẫn.
- `src/models/`: weights mặc định; nội dung nhị phân bị loại khỏi Git.
- `packaging/`: cấu hình đóng gói portable được triển khai ở giai đoạn 8.
- `tests/`: kiểm thử unit, integration, GUI và thư mục fixtures.

Giai đoạn 1 cung cấp nền tảng; cửa sổ desktop và entry point `src.main` thuộc
các giai đoạn tích hợp sau, hiện chưa có ứng dụng OCR để chạy.

## Sử dụng nền tảng giai đoạn 1

Khởi tạo storage trước khi import các thư viện OCR để chúng nhận đúng cache:

```python
from src.config import ConfigManager
from src.services.weights_manager import ModelWeightsManager
from src.utils.logger import configure_logging, logger

configure_logging()  # logs/app.log cạnh ứng dụng, xoay vòng 10 MB, giữ 14 ngày
config = ConfigManager()
preferences = config.load()
weights = ModelWeightsManager(preferences.weights_dir)
weights.ensure_disk_space(1024**3)  # kiểm tra trước khi tải model 1 GiB
model_dir = weights.get_engine_weights_dir("vietocr")
logger.info("Dung lượng trống: {:.2f} GiB", weights.get_free_disk_space_gb())
```

`ConfigManager` dùng `config/preferences.ini` (QSettings) cùng bản JSON ghi
atomic tại `config/preferences.json`. JSON được ưu tiên khi hiện diện để tránh
khôi phục cấu hình cũ nếu lần đồng bộ Qt trước đó thất bại. Không có Qt vẫn lưu
và đọc JSON được. Dữ liệu hỏng được giữ nguyên để kiểm tra, đồng thời thử bản sao
QSettings rồi mới dùng mặc định. `Preferences` là dataclass bất biến; dùng
`dataclasses.replace()` và `config.save()` để lưu thay đổi.

Weights mặc định là `<app_root>/src/models/`, không phụ thuộc thư mục chạy lệnh.
Trong bundle, tìm `src/models/` cạnh executable, sau đó `models/`. Đường dẫn tùy
chỉnh có thể ở ổ đĩa khác; tên engine phải là một tên thư mục đơn. Manager kiểm
tra quyền ghi thực tế, dung lượng, traversal và đích symlink/junction. Các hook:

| Biến môi trường | Thư mục con trong weights |
| --- | --- |
| `TORCH_HOME` | `torch/` |
| `HF_HOME` | `huggingface/` |
| `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, `TRANSFORMERS_CACHE` | `huggingface/hub/` |
| `HF_XET_CACHE` | `huggingface/xet/` |
| `HF_ASSETS_CACHE`, `HUGGINGFACE_ASSETS_CACHE` | `huggingface/assets/` |
| `PADDLE_HOME` | `paddle/` |
| `PADDLE_PDX_CACHE_HOME` | `paddle/paddlex/` |
| `EASYOCR_MODULE_PATH` | `easyocr/` |

Các cache phụ dựa trên [tài liệu Hugging Face](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables)
và [mã cache PaddleX](https://github.com/PaddlePaddle/PaddleX/blob/develop/paddlex/utils/cache.py).
Provider ở giai đoạn 3 vẫn cần truyền đường dẫn weights tường minh cho các thư
viện không tuân theo hook. Đổi thư mục khi model đã nạp cần điều phối việc
unload/reload provider; phần nền tảng không tự tải hay di chuyển weights.

Các domain model trong `src/core/models.py` dùng `frozen=True`, bảo vệ cả các
collection lồng nhau bằng tuple. Mỗi model hỗ trợ `with_updates()`, `to_dict()`,
`from_dict()`, `to_json()` và `from_json()`. Tọa độ dùng pixel; `page_number`
bắt đầu từ 1; confidence nằm trong `[0, 1]`. Polygon giữ hình dạng xoay cùng
bounding box bao ngoài. `OCRTable.rows` là ma trận text hình chữ nhật;
metadata gộp ô sẽ được bổ sung cùng bộ trích xuất bảng ở giai đoạn 4.
