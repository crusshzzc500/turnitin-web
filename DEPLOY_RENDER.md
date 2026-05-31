# Triển khai Minh Chứng trên Render

## Demo công khai an toàn

`render.yaml` cấu hình `MINH_CHUNG_PUBLIC_MODE=1`. Ở chế độ này:

- Khách không thể giả mạo header để trở thành `admin`.
- API crawler, reindex, thêm nguồn thủ công và nhật ký kiểm toán bị khóa.
- Máy chủ không lưu bài nộp hoặc báo cáo của khách.
- Tùy chọn quét web mặc định tắt; chỉ gửi đoạn trích sang nhà cung cấp tìm kiếm bên ngoài khi khách chủ động bật.
- Tavily dùng `fast`, không lấy toàn bộ nội dung trang và có ngân sách chờ tối đa `150` giây.
- Exa chỉ chạy fallback khi Tavily thiếu nguồn, dùng `instant`, lấy `highlights` và nhận tối đa `3`
  truy vấn mỗi báo cáo để tiết kiệm quota miễn phí.
- WebSearchAPI.ai và Linkup chỉ chạy fallback nếu tổng nguồn vẫn thiếu; mỗi bên nhận tối đa `1` truy vấn.
- Serper chỉ chạy fallback cuối nếu tổng nguồn vẫn thiếu, nhận tối đa `1` truy vấn mỗi báo cáo.

Tạo Blueprint từ repository chứa file `render.yaml`, sau đó nhập `TAVILY_API_KEY`, `EXA_API_KEY`,
`WEBSEARCHAPI_API_KEY`, `LINKUP_API_KEY`, `SERPER_API_KEY` hoặc `BRAVE_SEARCH_API_KEY` trong phần Environment
của Render. Không đưa API key vào Git hoặc ZIP.

Render cung cấp biến `PORT`; máy chủ đã tự nhận biến này, bind `0.0.0.0` và mặc định bật public
mode an toàn. Có thể đặt rõ `MINH_CHUNG_PUBLIC_MODE=0` cho một deployment nội bộ riêng.

`render.yaml` đặt giới hạn upload ứng dụng là `250 MB`. Reverse proxy và bộ nhớ của gói Render
thực tế vẫn có thể áp giới hạn thấp hơn; với file lớn thường xuyên nên dùng object storage và
upload nhiều phần thay vì giữ toàn bộ tệp trong RAM.

## Giới hạn của gói miễn phí

Filesystem của Render free có thể mất dữ liệu sau lần deploy hoặc restart. Điều này phù hợp cho
demo public vì tài liệu khách không được lưu. Nó không phù hợp cho corpus dài hạn.

Để vận hành thật:

1. Dùng đăng nhập thật hoặc SSO thay cho tài khoản demo.
2. Chuyển metadata từ SQLite sang PostgreSQL.
3. Dùng OpenSearch cho chỉ mục tìm kiếm.
4. Dùng object storage cho nội dung gốc và phiên bản nguồn.
5. Tách crawler sang worker riêng có queue phân tán.

## Bản nội bộ

Không đặt `MINH_CHUNG_PUBLIC_MODE=1` khi chạy trong mạng nội bộ để thử dashboard quản trị. Bản
demo vẫn dùng header giả lập vai trò, nên chưa được coi là cơ chế đăng nhập production.
