# Sổ Tay Hướng Dẫn Sử Dụng

## Ứng Dụng OCR Đa Mô Hình & Chuyển Đổi Tài Liệu

> Ứng dụng desktop nhận diện chữ (OCR) cho tài liệu tiếng Việt: giữ nguyên bố cục nhiều cột,
> tách bảng biểu, xuất ra PDF tìm kiếm được, Word, Excel, Markdown, JSON.
> Chạy được trên **Windows, macOS và Linux**, hoạt động **100% ngoại tuyến** sau khi đã tải mô hình.

---

## Mục lục

1. [Cài đặt](#1-cài-đặt)
2. [Làm quen với giao diện](#2-làm-quen-với-giao-diện)
3. [Quy trình cơ bản: từ tệp đến kết quả](#3-quy-trình-cơ-bản-từ-tệp-đến-kết-quả)
4. [Chọn mô hình và thiết bị chạy](#4-chọn-mô-hình-và-thiết-bị-chạy)
5. [Lưu mô hình vào ổ cứng ngoài](#5-lưu-mô-hình-vào-ổ-cứng-ngoài)
6. [Soát lỗi bằng bộ so sánh song song](#6-soát-lỗi-bằng-bộ-so-sánh-song-song)
7. [Chỉ nhận diện một vùng](#7-chỉ-nhận-diện-một-vùng)
8. [Sửa bảng biểu trước khi xuất Excel](#8-sửa-bảng-biểu-trước-khi-xuất-excel)
9. [Quét hàng loạt](#9-quét-hàng-loạt)
10. [Xuất tài liệu](#10-xuất-tài-liệu)
11. [Giao diện và ngôn ngữ](#11-giao-diện-và-ngôn-ngữ)
12. [Bảng phím tắt](#12-bảng-phím-tắt)
13. [Mẹo tăng độ chính xác](#13-mẹo-tăng-độ-chính-xác)
14. [Xử lý sự cố](#14-xử-lý-sự-cố)
15. [Bản Portable: mang sang máy khác](#15-bản-portable-mang-sang-máy-khác)
16. [Dữ liệu của bạn được lưu ở đâu](#16-dữ-liệu-của-bạn-được-lưu-ở-đâu)

---

## 1. Cài đặt

### 1.1. Dùng bản Portable (khuyến nghị cho người dùng cuối)

Không cần cài Python. Giải nén `pdf-ocr-portable.zip`, mở thư mục `pdf-ocr` và chạy tệp
`pdf-ocr` (trên Windows là `pdf-ocr.exe`). Xem thêm [Mục 15](#15-bản-portable-mang-sang-máy-khác).

### 1.2. Chạy từ mã nguồn (dành cho lập trình viên)

Yêu cầu **Python 3.10 trở lên**.

```bash
git clone <địa-chỉ-kho-mã-nguồn> pdf-ocr
cd pdf-ocr

python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e .            # chỉ phần lõi và giao diện
pip install -r requirements.txt   # kèm toàn bộ mô hình OCR

python -m src.main
```

Trong **VS Code**, nhấn `F5` rồi chọn cấu hình **PDF OCR: chạy ứng dụng**.

### 1.3. Kiểm tra cài đặt

```bash
pytest tests/ --cov=src --cov-report=term-missing
```

---

## 2. Làm quen với giao diện

Cửa sổ chính gồm bốn khu vực:

```
┌───────────────────────────────────────────────────────────────┐
│  Tệp   Sửa   Xem   OCR   Công cụ   Trợ giúp        ← Thanh menu │
├───────────────────────────────────────────────────────────────┤
│  [Mở tệp] [Mở thư mục] │ [Chạy OCR] [Chọn vùng] … ← Thanh công cụ│
├─────────────────────────────────┬─────────────────────────────┤
│                                 │                             │
│   Ảnh trang gốc                 │   Văn bản nhận diện         │
│   (phóng to, kéo thả, khung     │   (sửa trực tiếp,           │
│    bố cục nhiều màu)            │    Undo/Redo, tô vàng        │
│                                 │    chỗ nghi ngờ)            │
│        ← Bộ so sánh lỗi →       │                             │
├─────────────────────────────────┴──────────┬──────────────────┤
│  Đã xong 12/40 · Lỗi 0 · Còn lại: 1 phút   │ Tùy chọn nhận diện│
│  [▓▓▓▓▓░░░░░] [Tạm dừng] [Hủy]   ← Thanh   │  Mô hình OCR …    │
│                                   trạng thái│  Thiết bị …       │
└────────────────────────────────────────────┴──────────────────┘
```

**Màu khung bố cục** trên ảnh cho biết loại khối:

| Màu | Loại khối |
| :-- | :-- |
| Xanh dương | Đoạn văn bản thường |
| Tím hồng | Tiêu đề |
| Xanh lá | Bảng biểu |
| Cam | Hình ảnh |
| Đỏ (nét đứt) | Khối đang chọn / vùng bạn vừa vẽ |

---

## 3. Quy trình cơ bản: từ tệp đến kết quả

1. **Mở tài liệu** — `Ctrl+O`, hoặc **kéo thả** tệp PDF/ảnh thẳng vào cửa sổ.
   Định dạng hỗ trợ: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.webp`.
2. **Chọn mô hình và thiết bị** ở dock *Tùy chọn nhận diện* bên phải ([Mục 4](#4-chọn-mô-hình-và-thiết-bị-chạy)).
3. **Chạy OCR** — `F5`. Quá trình chạy nền: giao diện vẫn thao tác được, thanh trạng thái
   hiển thị phần trăm và thời gian còn lại.
4. **Soát lỗi** ở bộ so sánh song song ([Mục 6](#6-soát-lỗi-bằng-bộ-so-sánh-song-song)).
5. **Xuất tệp** — `Ctrl+S` ([Mục 10](#10-xuất-tài-liệu)).

> **PDF đã có sẵn lớp text** (xuất từ Word, trình duyệt…) được đọc thẳng, **không cần OCR**:
> nhanh dưới 1 giây mỗi trang và chính xác 100%. Ứng dụng tự nhận biết, bạn không phải làm gì.

---

## 4. Chọn mô hình và thiết bị chạy

Dock **Tùy chọn nhận diện** (bên phải cửa sổ):

| Mục | Ý nghĩa | Gợi ý |
| :-- | :-- | :-- |
| **Mô hình OCR** | Bộ nhận diện sẽ dùng | `VietOCR` cho văn bản tiếng Việt; `TrOCR` cho chữ viết tay; `PaddleOCR` khi tài liệu nhiều bảng |
| **Thiết bị** | CPU hay GPU | Để `Tự động phát hiện` |
| **Độ phân giải** | DPI khi dựng ảnh từ PDF | 300 DPI là mặc định tốt; 400–600 cho chữ rất nhỏ |
| **Tiền xử lý ảnh** | Bật/tắt từng bộ lọc | Giữ bật tất cả, trừ khi ảnh đã sạch sẵn |
| **Nhận diện bảng biểu** | Dựng lưới hàng/cột từ bảng | Cần `PaddleOCR`; có thể sửa bảng trước khi xuất |
| **Thứ tự đọc nhiều cột** | Đọc lần lượt từng cột | Giữ bật để tránh ghép chữ xuyên cột |
| **Gộp dòng thành đoạn** | Nối các dòng cùng đoạn | Tắt nếu cần giữ riêng từng dòng OCR |

Kết quả có nhãn tiêu đề cấp 1–3 khi cỡ chữ/chiều cao dòng nổi bật rõ so với văn bản thường;
nhãn chú thích được nhận diện theo tiền tố như `Hình 1` hoặc `Table 2`. Nếu trang không có
bằng chứng rõ về kiểu chữ, khối vẫn được giữ là đoạn văn thay vì đoán cấp tiêu đề.

Bốn bộ lọc tiền xử lý chạy theo thứ tự: **tự xoay đúng hướng → làm thẳng ảnh nghiêng →
cắt viền thừa → tăng cường chất lượng ảnh**.

### Về GPU

Vào **Công cụ → Cài đặt → Thiết bị thực thi**. Ứng dụng tự dò card đồ họa và hiển thị
tên cùng dung lượng VRAM, ví dụ *"Đã phát hiện NVIDIA RTX 4090 với 24.0 GB VRAM"*.
Nếu máy không có GPU CUDA, dòng chữ sẽ ghi rõ và ứng dụng chạy bằng CPU — chậm hơn
nhưng kết quả không đổi. Chế độ `Tự động` chọn GPU khi có và lùi về CPU khi không.

---

## 5. Lưu mô hình vào ổ cứng ngoài

Các mô hình OCR nặng vài GB. Mặc định chúng nằm trong thư mục ứng dụng
(`src/models/`), **không bao giờ** ghi vào `C:\Users\...\.cache` làm đầy ổ hệ thống.

Để chuyển sang ổ ngoài:

1. **Công cụ → Cài đặt** (`Ctrl+,`).
2. Ở mục **Thư mục mô hình & weights**, bấm **Duyệt…** và chọn thư mục trên ổ ngoài,
   ví dụ `E:\PDF-OCR-Models`.
3. Đọc dòng **Dung lượng trống** ngay bên dưới để chắc chắn ổ đủ chỗ.
4. Nếu đã tải mô hình từ trước, bấm **Di chuyển weights sang thư mục mới**. Thanh tiến trình
   hiển thị tiến độ sao chép.
5. Bấm **OK**.

> **An toàn dữ liệu:** thao tác di chuyển **sao chép trước, xóa sau**. Nếu bạn hủy giữa chừng
> hoặc rút nhầm ổ cứng, mô hình gốc vẫn còn nguyên. Ứng dụng cũng từ chối những đường dẫn
> chứa `..` và những thư mục đích nằm bên trong thư mục nguồn.

Sau khi đổi, các biến môi trường cache của PyTorch, HuggingFace, PaddleOCR và EasyOCR
đều được chuyển hướng vào thư mục bạn chọn.

---

## 6. Soát lỗi bằng bộ so sánh song song

Đây là phần giúp bạn sửa nhanh nhất.

- **Từ văn bản sang ảnh:** đặt con trỏ vào một đoạn ở khung phải → khung trái tự cuộn đến
  đúng khối tương ứng và tô viền đỏ.
- **Từ ảnh sang văn bản:** bấm vào một khung bố cục ở khung trái → con trỏ nhảy tới đoạn đó.
- **Tô vàng:** những từ mô hình không chắc chắn (độ tin cậy dưới 80%) có nền vàng nhạt.
  Hãy đọc kỹ những chỗ này trước tiên.
- **Sửa trực tiếp:** gõ thẳng vào khung phải. `Ctrl+Z` hoàn tác, `Ctrl+Y` làm lại.
- **Phóng to ảnh:** lăn chuột trên ảnh, hoặc `Ctrl` `+` / `Ctrl` `-`; `Ctrl+0` để vừa khung.
  Kéo thả chuột để di chuyển ảnh.

### Sửa hàng loạt một lỗi lặp lại

Mô hình thường sai cùng một chỗ trên nhiều trang (ví dụ `đuợc` thay vì `được`).

1. `Ctrl+H` mở hộp thoại **Tìm và thay thế**.
2. Gõ chữ sai vào ô **Tìm**, chữ đúng vào ô **Thay bằng**.
3. Bấm **Thay tất cả**.

> Toàn bộ lần thay thế hàng loạt chỉ tính là **một bước hoàn tác**: bấm `Ctrl+Z` một lần
> là quay lại nguyên trạng, không phải bấm hàng chục lần.

Tùy chọn **Phân biệt hoa thường** và **Đúng toàn bộ từ** giúp thu hẹp phạm vi tìm.

---

## 7. Chỉ nhận diện một vùng

Khi bạn chỉ cần một đoạn hoặc một bảng trong trang:

1. Bấm **Chọn vùng OCR** trên thanh công cụ, hoặc `Ctrl+R`.
2. Kéo chuột vẽ hình chữ nhật trên ảnh. Vùng chọn hiện nét đứt màu đỏ.
3. Kết quả của riêng vùng đó hiển thị ngay dưới khung văn bản.
4. Bấm `Ctrl+R` lần nữa để tắt chế độ vẽ và quay lại kéo thả ảnh như thường.

Vùng chọn luôn được cắt gọn trong phạm vi trang, kéo theo chiều nào cũng cho hình chữ nhật hợp lệ.
Nếu đang chọn **PaddleOCR** và bật **Nhận diện bảng biểu**, bảng tìm thấy trong vùng sẽ được thêm vào
kết quả trang hiện tại, hiện trong danh sách bảng và có thể chỉnh sửa hoặc xuất ra Excel. Với PDF có
lớp chữ, nội dung chữ dùng trực tiếp từ PDF; phần nhận diện cấu trúc bảng vẫn chạy nền.

---

## 8. Sửa bảng biểu trước khi xuất Excel

**Nhấp đúp** vào một khung bảng (viền xanh lá) trên ảnh để mở trình sửa bảng:

- Sửa nội dung từng ô bằng cách nhấp đúp vào ô đó.
- **Thêm dòng** / **Xóa dòng** / **Thêm cột** / **Xóa cột**.
- Bấm **OK** để ghi nhận.

Trình sửa luôn giữ bảng ở dạng chữ nhật hợp lệ: không cho xóa dòng hoặc cột cuối cùng, và
tự bỏ những ô gộp không còn nằm trong kích thước mới.

---

## 9. Quét hàng loạt

1. **Tệp → Mở thư mục** (`Ctrl+Shift+O`), hoặc chọn nhiều tệp.
2. Nhấn `F5`. Cửa sổ **Quét hàng loạt** hiện ra, liệt kê từng tài liệu kèm trạng thái:
   **Chờ → Đang chạy → Xong** (hoặc **Lỗi**).
3. Thanh trạng thái và cửa sổ batch hiển thị phần trăm, số trang đã xong, số trang lỗi và
   **thời gian còn lại** ước tính theo tốc độ thực tế.

| Nút | Tác dụng |
| :-- | :-- |
| **Tạm dừng** | Không nhận trang mới; trang đang chạy vẫn hoàn tất bình thường |
| **Tiếp tục** | Chạy tiếp từ chỗ dừng |
| **Hủy** | Bỏ mọi trang chưa bắt đầu; không để lại tệp dở dang |

Một trang lỗi **không làm dừng cả lượt quét** — ứng dụng ghi nhận và chạy tiếp trang sau.
Đóng cửa sổ batch giữa chừng sẽ tự hủy lượt quét và chờ luồng nền dừng hẳn, không bỏ sót
tiến trình chạy ngầm.

> Toàn bộ quá trình chạy trên luồng nền. Bộ nhớ RAM và VRAM được thu hồi **sau mỗi trang**,
> nên quét 100 trang liên tục không làm ứng dụng phình bộ nhớ.

---

## 10. Xuất tài liệu

`Ctrl+S`, hoặc **Tệp → Xuất tài liệu**.

| Định dạng | Đuôi | Dùng khi nào |
| :-- | :-- | :-- |
| **PDF tìm kiếm được** | `.pdf` | Lưu trữ: giữ nguyên ảnh gốc, thêm lớp text ẩn để `Ctrl+F` tìm được |
| **Word** | `.docx` | Cần sửa tiếp, giữ tiêu đề và bảng |
| **Excel** | `.xlsx` | Chỉ lấy bảng biểu, mỗi bảng một sheet |
| **Markdown** | `.md` | Đưa vào tài liệu kỹ thuật, wiki |
| **Văn bản thuần** | `.txt` | Chỉ cần nội dung chữ |
| **JSON** | `.json` | Lập trình: kèm tọa độ và độ tin cậy từng từ |

Mọi tệp xuất đều **ghi nguyên tử**: ứng dụng ghi ra tệp tạm rồi mới đổi tên. Nếu hết dung
lượng hoặc mất quyền ghi giữa chừng, tệp cũ của bạn vẫn nguyên vẹn, không có tệp dở dang.

---

## 11. Giao diện và ngôn ngữ

**Công cụ → Cài đặt → Giao diện**:

- **Chủ đề:** `Theo hệ thống` / `Sáng` / `Tối`. Đổi là áp dụng ngay, không cần khởi động lại.
- **Ngôn ngữ:** `Tiếng Việt` / `English`. Cũng áp dụng ngay.

Cả hai lựa chọn được ghi nhớ cho lần mở sau.

---

## 12. Bảng phím tắt

| Phím tắt | Chức năng |
| :-- | :-- |
| `Ctrl+O` | Mở tệp |
| `Ctrl+Shift+O` | Mở thư mục |
| `Ctrl+S` | Xuất tài liệu |
| `Ctrl+Q` | Thoát |
| `F5` | Chạy OCR |
| `Ctrl+R` | Bật/tắt chế độ chọn vùng OCR |
| `Ctrl+H` | Tìm và thay thế |
| `Ctrl+Z` | Hoàn tác |
| `Ctrl+Y` | Làm lại |
| `Ctrl` `+` | Phóng to |
| `Ctrl` `-` | Thu nhỏ |
| `Ctrl+0` | Vừa khung cửa sổ |
| `Ctrl+,` | Mở Cài đặt |

Menu **Tệp → Tệp gần đây** lưu 10 tài liệu mở gần nhất.
Vị trí cửa sổ và cách bố trí các dock được ghi nhớ giữa các lần chạy.

---

## 13. Mẹo tăng độ chính xác

**Về tài liệu đầu vào**

- Scan ở **300 DPI** trở lên. Dưới 200 DPI chữ nhỏ sẽ mất nét.
- Chụp bằng điện thoại: đặt giấy trên nền phẳng, đủ sáng, tránh bóng tay và nếp gấp.
  Ứng dụng tự làm thẳng ảnh nghiêng và xóa bóng, nhưng ảnh gốc tốt vẫn cho kết quả tốt hơn.
- Scan **đen trắng có ngưỡng cứng** thường kém hơn scan **thang xám**.

**Về lựa chọn trong ứng dụng**

- PDF đã có lớp text: cứ mở bình thường, đừng ép chạy OCR — kết quả trích xuất trực tiếp
  luôn chính xác hơn.
- Chữ rất nhỏ hoặc dấu bị dính: nâng **Độ phân giải** lên 400–600 DPI.
- Tài liệu nhiều bảng: chọn **PaddleOCR**.
- Chữ viết tay: chọn **TrOCR**.
- Ảnh đã được xử lý sạch từ trước: **tắt** các bộ lọc tiền xử lý để tránh xử lý chồng.
- Chỉ cần một đoạn nhỏ: dùng **chọn vùng** (`Ctrl+R`) — nhanh hơn và ít nhiễu hơn.

**Về khâu soát lỗi**

- Luôn xem trước các từ **tô vàng**.
- Gặp lỗi lặp lại, dùng `Ctrl+H` **Thay tất cả** thay vì sửa thủ công từng chỗ.

---

## 14. Xử lý sự cố

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
| :-- | :-- | :-- |
| *"Định dạng tệp này chưa được hỗ trợ."* | Đuôi tệp ngoài danh sách ở [Mục 3](#3-quy-trình-cơ-bản-từ-tệp-đến-kết-quả) | Chuyển sang PDF hoặc PNG |
| *"Không thể mở tài liệu…"* | PDF đặt mật khẩu, hoặc tệp hỏng | Bỏ mật khẩu rồi mở lại |
| *"Không đủ dung lượng trống."* | Ổ đĩa đầy khi tải hoặc di chuyển mô hình | Dọn ổ, hoặc đổi sang ổ khác ở Cài đặt |
| *"Không thể tải mô hình. Vui lòng kiểm tra kết nối mạng…"* | Mất mạng khi tải lần đầu | Kiểm tra mạng; ứng dụng đã tự thử lại 3 lần |
| *"Tệp tải về không đạt kiểm tra toàn vẹn SHA256."* | Tải bị hỏng giữa chừng | Tải lại; tệp hỏng đã tự bị xóa, không lưu vào máy |
| *"Không phát hiện GPU CUDA…"* | Máy không có card NVIDIA, hoặc thiếu driver | Dùng CPU, hoặc cài lại driver CUDA |
| Chạy OCR rất chậm | Đang chạy bằng CPU, hoặc DPI quá cao | Hạ DPI về 300; bật GPU nếu có |
| Kết quả sai nhiều dấu | Ảnh mờ hoặc độ phân giải thấp | Scan lại ở 300+ DPI; xem [Mục 13](#13-mẹo-tăng-độ-chính-xác) |
| Chữ cột 1 bị nối sang cột 2 | Khoảng cách cột trong bản gốc quá hẹp | Dùng **chọn vùng** để nhận diện từng cột riêng |

Thông báo lỗi hiện ở góc dưới bên phải dưới dạng thẻ màu. Thẻ **lỗi (đỏ)** ở lại đến khi bạn
đóng; thẻ thành công và thông tin tự ẩn sau vài giây. Nhật ký chi tiết dành cho kỹ thuật viên
nằm trong thư mục `logs/` ([Mục 16](#16-dữ-liệu-của-bạn-được-lưu-ở-đâu)).

> **Lưu ý về chính tả:** ứng dụng chuẩn hóa vị trí dấu thanh theo kiểu `hoà`, `khoẻ`, `thuý`
> (dấu đặt trên nguyên âm thứ hai của `oa`, `oe`, `uy`). Nếu tài liệu của bạn cần kiểu cũ
> (`hòa`, `khỏe`, `thúy`), hãy dùng `Ctrl+H` để đổi lại sau khi nhận diện.

---

## 15. Bản Portable: mang sang máy khác

Bản Portable chạy trên máy **không cài Python và không có Internet**.

**Tạo bản Portable** (trên máy đã cài đặt mã nguồn):

```bash
python packaging/build_portable.py --with-weights
```

Kết quả: `dist/pdf-ocr/` và tệp nén `dist/pdf-ocr-portable.zip`.

**Mang sang máy khác:**

1. Chép cả thư mục `pdf-ocr` (hoặc giải nén tệp zip) sang máy đích — USB, ổ ngoài đều được.
2. Bảo đảm thư mục `models` nằm **ngay cạnh** tệp chạy:

   ```
   pdf-ocr/
   ├── pdf-ocr(.exe)     ← tệp chạy
   ├── _internal/        ← thư viện đi kèm
   ├── models/           ← mô hình OCR (bắt buộc để chạy ngoại tuyến)
   ├── config/           ← cấu hình, tự tạo khi chạy lần đầu
   └── logs/             ← nhật ký, tự tạo khi chạy lần đầu
   ```

3. Chạy tệp `pdf-ocr`. Ứng dụng tự tìm thư mục `models` bên cạnh và nhận diện hoàn toàn
   ngoại tuyến.

Nếu quên `--with-weights`, hãy chép tay thư mục `src/models` của máy nguồn vào thành
`pdf-ocr/models` trên máy đích.

---

## 16. Dữ liệu của bạn được lưu ở đâu

Ứng dụng **không ghi gì vào thư mục hệ thống ẩn**. Mọi thứ nằm trong thư mục ứng dụng:

| Thư mục / tệp | Nội dung |
| :-- | :-- |
| `config/settings.db` | Cơ sở dữ liệu SQLite: cài đặt, tham số mô hình, thông số phiên làm việc |
| `config/preferences.json` | Bản sao cấu hình dạng văn bản, dễ đọc và sao lưu |
| `config/preferences.ini` | Bản sao cho Qt |
| `logs/app.log` | Nhật ký ứng dụng, tự xoay vòng 10 MB, giữ 14 ngày |
| `src/models/` (hoặc `models/`) | Mô hình OCR và cache của PyTorch, HuggingFace, PaddleOCR, EasyOCR |

Sao lưu thư mục `config` là đủ để giữ lại toàn bộ tùy chỉnh của bạn.
Nhật ký **không ghi nội dung tài liệu** của bạn.

---

*Gặp vấn đề chưa có trong sổ tay này? Hãy gửi kèm tệp `logs/app.log` khi báo lỗi.*
