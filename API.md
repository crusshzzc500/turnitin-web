# API Minh Chứng

Máy chủ mặc định chạy tại `http://127.0.0.1:8765`.

## Phiên làm việc thử nghiệm

API dùng header `X-Minh-Chung-User` để mô phỏng đăng nhập trong bản MVP. Nếu không gửi header,
máy chủ dùng `demo-admin`. Ba tài khoản có sẵn là `demo-admin`, `demo-instructor` và
`demo-student`. Đây là cơ chế demo, chưa thay thế đăng nhập thật bằng mật khẩu hoặc SSO.

Khi `MINH_CHUNG_PUBLIC_MODE=1`, máy chủ bỏ qua header này, luôn dùng quyền sinh viên, không lưu
bài hoặc báo cáo của khách và khóa API quản trị. Dùng public mode cho website mở tự do.

| Phương thức | Đường dẫn | Mục đích |
| --- | --- | --- |
| `GET` | `/api/session/users` | Danh sách tài khoản demo để đổi vai trò trên giao diện. |
| `GET` | `/api/session` | Người dùng hiện tại, tổ chức, vai trò và quyền thao tác. |
| `GET` | `/api/audit?limit=100` | Nhật ký kiểm toán của tổ chức; chỉ `admin`. |

## Trạng thái và kho dữ liệu

| Phương thức | Đường dẫn | Mục đích |
| --- | --- | --- |
| `GET` | `/api/health` | Kiểm tra máy chủ và trạng thái cấu hình Tavily/Exa/Brave; không lộ API key. |
| `GET` | `/api/ocr/status` | Kiểm tra OCR PDF scan có sẵn trên máy chủ hay không. |
| `GET` | `/api/stats` | Số nguồn, đoạn chỉ mục, bài nộp, báo cáo và hàng đợi crawler. |
| `GET` | `/api/sources?limit=100` | Danh sách nguồn đối chiếu. |
| `POST` | `/api/sources` | Thêm nguồn thủ công. |
| `GET` | `/api/sources/{id}/versions` | Xem lịch sử phiên bản bất biến của một nguồn. |
| `GET` | `/api/reports?limit=20` | Danh sách báo cáo gần nhất. |
| `GET` | `/api/reports/{id}/pdf` | Tải báo cáo PDF trong phạm vi tổ chức hiện tại. |

Ví dụ thêm nguồn:

```json
{
  "title": "Tài liệu công khai",
  "url": "https://example.org/tai-lieu",
  "type": "website",
  "content": "Nội dung văn bản cần đưa vào kho đối chiếu..."
}
```

## Phân tích tài liệu

| Phương thức | Đường dẫn | Mục đích |
| --- | --- | --- |
| `POST` | `/api/analysis-jobs` | Tạo job phân tích văn bản nền và nhận token theo dõi. |
| `POST` | `/api/analysis-jobs/upload` | Tải nguyên tệp nhị phân `.txt`, `.md`, `.docx`, `.pdf` để tạo job nền. |
| `GET` | `/api/analysis-jobs/{id}` | Xem phần trăm tiến trình bằng header `X-Minh-Chung-Job-Token`. |
| `POST` | `/api/analyze` | Phân tích văn bản JSON đồng bộ để tương thích client cũ. |
| `POST` | `/api/analyze-upload` | Đọc tệp base64 đồng bộ để tương thích client cũ. |

Ví dụ phân tích:

```json
{
  "text": "Nội dung bài viết...",
  "saveReport": true,
  "indexForComparison": false,
  "enableWebSearch": false,
  "webSearchMaxResults": 5,
  "settings": {
    "excludeQuotes": true,
    "excludeBibliography": true,
    "minimumWords": 8
  }
}
```

`indexForComparison` mặc định là `false`. Chỉ đặt thành `true` sau khi người nộp
đã đồng ý đưa bài vào kho nội bộ để đối chiếu các lần sau.

`enableWebSearch` cũng mặc định là `false`. Khi đặt thành `true`, tối đa `6` đoạn trích nổi bật
được gửi song song sang Tavily để tìm nguồn công khai. Nếu Tavily thiếu nguồn hoặc không dùng được,
Exa `instant` fallback nhận tối đa `2` truy vấn và chỉ trả `highlights` để tiết kiệm quota miễn phí.
Brave là dự phòng tiếp theo khi không có Tavily hoặc Exa. Mỗi truy vấn nhận tối đa `10`
kết quả ứng viên. Tavily mặc định dùng `ultra-fast`, chỉ lấy đoạn tóm tắt và hệ thống trả kết quả
hiện có sau ngân sách chờ mặc định `8` giây. Nguồn phù hợp được lập chỉ mục riêng theo
tổ chức trước khi chạy đối chiếu. Không dùng lựa chọn này cho tài liệu nhạy cảm nếu chưa có chính
sách xử lý dữ liệu với nhà cung cấp tìm kiếm.

Giới hạn upload mặc định là `250000000` byte và có thể đổi bằng
`MINH_CHUNG_DOCUMENT_MAX_BYTES`. Client mới dùng endpoint tải nhị phân để không phải mã hóa cả
tệp sang base64 trong trình duyệt.

Nguồn thủ công, báo cáo và bài nộp nội bộ được giới hạn theo tổ chức. Sinh viên chỉ xem báo cáo
và bài nộp của chính mình. Thêm nguồn cho phép `admin` và `instructor`; API crawler, reindex và
nhật ký kiểm toán chỉ cho phép `admin`.

## Kho bài nộp nội bộ

| Phương thức | Đường dẫn | Mục đích |
| --- | --- | --- |
| `GET` | `/api/submissions?limit=100` | Danh sách bài đã đồng ý lập chỉ mục. |
| `DELETE` | `/api/submissions/{id}` | Rút bài và nguồn liên quan khỏi kho đối chiếu. |

## Crawler

| Phương thức | Đường dẫn | Mục đích |
| --- | --- | --- |
| `POST` | `/api/crawl/seeds` | Thêm tối đa `100` URL hạt giống mỗi lần. |
| `POST` | `/api/crawl/sitemaps` | Đọc sitemap XML và thêm tối đa `50.000` URL vào hàng đợi. |
| `POST` | `/api/crawl/run` | Chạy worker nền với `maxPages` và `maxDepth`. |
| `GET` | `/api/crawl/status` | Xem trạng thái worker và hàng đợi. |
| `GET` | `/api/crawl/operations?limit=50` | Xem queue, URL gần nhất và thống kê theo tên miền. |
| `POST` | `/api/crawl/retry` | Đưa URL lỗi vĩnh viễn trở lại hàng đợi theo giới hạn. |
| `GET` | `/api/search/status` | Kiểm tra backend tìm kiếm đang hoạt động. |
| `POST` | `/api/search/reindex` | Lập lại chỉ mục tìm kiếm từ kho nguồn hiện tại. |

Ví dụ:

```json
{
  "urls": ["https://example.org/tai-lieu-cong-khai"]
}
```

```json
{
  "maxPages": 20,
  "maxDepth": 1
}
```

Crawler mặc định chặn mạng nội bộ, tôn trọng `robots.txt`, giới hạn tốc độ, giới
hạn dung lượng và chỉ đi tiếp trong cùng tên miền. Timeout, lỗi mạng, `429` và
lỗi máy chủ `5xx` được thử lại với backoff theo cấp số nhân. URL vượt số lần thử
giới hạn chuyển sang trạng thái lỗi để quản trị viên xem xét.

## Chuyển sang OpenSearch

SQLite FTS5 là mặc định cho bản đơn máy. Khi corpus lớn hơn, chạy OpenSearch rồi
đặt biến môi trường trước khi khởi động:

```powershell
$env:MINH_CHUNG_SEARCH_BACKEND = 'opensearch'
$env:MINH_CHUNG_OPENSEARCH_URL = 'http://127.0.0.1:9200'
$env:MINH_CHUNG_OPENSEARCH_INDEX = 'minh-chung-chunks'
```

Sau lần chuyển đầu tiên, gọi `POST /api/search/reindex` để đưa nguồn SQLite hiện
có sang OpenSearch. Nạp nguồn mới và xóa bài nội bộ sau đó sẽ tự đồng bộ chỉ mục.
