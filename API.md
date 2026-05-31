# API Minh Chứng

Máy chủ mặc định chạy tại `http://127.0.0.1:8765`.

## Phiên làm việc thử nghiệm

API dùng header `X-Minh-Chung-User` để mô phỏng đăng nhập trong bản MVP. Nếu không gửi header,
máy chủ dùng `demo-admin`. Ba tài khoản có sẵn là `demo-admin`, `demo-instructor` và
`demo-student`. Đây là cơ chế demo, chưa thay thế đăng nhập thật bằng mật khẩu hoặc SSO.

| Phương thức | Đường dẫn | Mục đích |
| --- | --- | --- |
| `GET` | `/api/session/users` | Danh sách tài khoản demo để đổi vai trò trên giao diện. |
| `GET` | `/api/session` | Người dùng hiện tại, tổ chức, vai trò và quyền thao tác. |
| `GET` | `/api/audit?limit=100` | Nhật ký kiểm toán của tổ chức; chỉ `admin`. |

## Trạng thái và kho dữ liệu

| Phương thức | Đường dẫn | Mục đích |
| --- | --- | --- |
| `GET` | `/api/health` | Kiểm tra máy chủ đang hoạt động. |
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
| `POST` | `/api/analyze` | Phân tích văn bản JSON. |
| `POST` | `/api/analyze-upload` | Đọc và phân tích tệp base64 `.txt`, `.md`, `.docx`, `.pdf`. |

Ví dụ phân tích:

```json
{
  "text": "Nội dung bài viết...",
  "saveReport": true,
  "indexForComparison": false,
  "settings": {
    "excludeQuotes": true,
    "excludeBibliography": true,
    "minimumWords": 8
  }
}
```

`indexForComparison` mặc định là `false`. Chỉ đặt thành `true` sau khi người nộp
đã đồng ý đưa bài vào kho nội bộ để đối chiếu các lần sau.

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
