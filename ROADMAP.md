# Lộ trình phát triển Minh Chứng

## 1. Định vị đúng bài toán

Minh Chứng nên được gọi là nền tảng **đối chiếu và hỗ trợ rà soát liêm chính
học thuật**, không phải công cụ tự động kết luận đạo văn.

Turnitin cũng phân biệt hai khái niệm này: báo cáo tương đồng tô sáng phần văn bản
giống nguồn trong cơ sở dữ liệu để người đọc đánh giá bối cảnh. Tỷ lệ cao không
tự động đồng nghĩa với đạo văn và tỷ lệ thấp không bảo đảm bài viết không có vấn
đề.

## 2. Nền móng hiện có

- Máy chủ API Python, SQLite và chỉ mục toàn văn FTS5.
- Giao diện tải hoặc dán `.txt`, `.md`, `.docx`, `.pdf`.
- Tỷ lệ tương đồng, đoạn tô màu, danh sách nguồn và bộ lọc.
- Cảnh báo ký tự vô hình, ký tự giả dạng và định dạng DOCX đáng ngờ.
- Crawler đọc `robots.txt`, giới hạn tốc độ và chặn mạng nội bộ.
- Retry crawler có backoff, dashboard queue/lỗi và lịch sử phiên bản nguồn.
- Kho bài nộp nội bộ theo lựa chọn đồng ý; có thao tác rút khỏi kho đối chiếu.
- Lịch sử báo cáo phía máy chủ và tài liệu API.
- Lớp tìm kiếm tách rời với adapter OpenSearch và thao tác reindex.
- Ba vai trò demo, phạm vi dữ liệu theo tổ chức và nhật ký kiểm toán.
- Xuất báo cáo PDF; OCR fallback tùy chọn cho PDF scan khi có Tesseract.
- WebDiscovery qua Tavily hoặc Brave theo opt-in, có namespace nguồn riêng theo tổ chức.

## 3. Hướng triển khai được khuyến nghị

### Giai đoạn 1: sản phẩm thử nghiệm

Mục tiêu: dùng nội bộ tại một đơn vị nhỏ và đo nhu cầu thực tế.

- Thay phiên demo bằng đăng nhập thật, SSO và quản lý tài khoản.
- Nhận `.docx`, `.pdf`, `.txt`; tách nội dung đã có, cần bổ sung lưu phiên bản.
- Kho bài nộp nội bộ theo lựa chọn đồng ý đã có, cần bổ sung phân quyền tổ chức.
- Bộ máy tìm đoạn trùng theo cụm từ, n-gram và mức tương đồng câu.
- Mở rộng mẫu PDF có thương hiệu và cấu hình báo cáo theo tổ chức.
- Mã hóa dữ liệu, nhật ký truy cập, chính sách xóa và thời hạn lưu trữ.

### Giai đoạn 2: dữ liệu mở rộng

Mục tiêu: tăng độ phủ nguồn, đặc biệt cho tiếng Việt.

- Crawler có `robots.txt`, giới hạn tốc độ, nhập sitemap, retry và dashboard đơn
  máy; cần bổ sung chính sách bản quyền, nhiều worker và metrics tập trung.
- Lập chỉ mục nguồn mở: luận văn công khai, tạp chí mở, website giáo dục và kho
  nội bộ đã được cấp quyền.
- Kết nối dữ liệu thư mục để nhận diện nguồn học thuật và gợi ý trích dẫn.
- Phân loại kết quả: trích dẫn hợp lệ, tài liệu tham khảo, mẫu biểu, đoạn cần rà
  soát và dấu hiệu sửa ký tự để né kiểm tra.

### Giai đoạn 3: tích hợp tổ chức

Mục tiêu: vận hành ở quy mô trường học.

- Tích hợp LMS qua LTI 1.3 hoặc API.
- Hàng đợi xử lý, webhook, giám sát lỗi và đo thời gian tạo báo cáo.
- Không gian dữ liệu riêng theo tổ chức.
- Trang thống kê cho quản trị viên và quy trình khiếu nại hoặc giải trình.

## 4. Hai con đường dữ liệu

### Tích hợp Turnitin Core API

Phù hợp khi cần chất lượng nguồn nhanh và khách hàng đã có giấy phép. Ứng dụng
có thể giữ giao diện riêng, gửi tệp, nhận webhook, yêu cầu tạo báo cáo và mở
Viewer URL theo quy trình chính thức. Đây là tích hợp Turnitin, không phải sản
phẩm độc lập.

### Xây kho nguồn độc lập

Phù hợp khi muốn làm sản phẩm riêng cho thị trường Việt Nam. Lợi thế có thể nằm
ở dữ liệu tiếng Việt, trải nghiệm học tập và chính sách riêng tư. Chi phí lớn
nhất là thu thập nguồn hợp pháp, làm sạch dữ liệu và xây chỉ mục, không phải là
giao diện.

Hướng thực tế nhất là **hybrid**: bắt đầu bằng kho nội bộ và nguồn mở tiếng Việt,
sau đó bổ sung đối tác dữ liệu hoặc tích hợp API được cấp phép cho từng nhóm
khách hàng.

## 5. Cách làm tốt hơn cho người dùng Việt Nam

- Giải thích lý do mỗi đoạn bị đánh dấu thay vì chỉ đưa ra phần trăm.
- Gợi ý bổ sung trích dẫn theo từng kiểu tài liệu.
- Chế độ tự rà soát trước khi nộp, có hướng dẫn sửa bài.
- Nhận diện tốt tiêu đề, tài liệu tham khảo và cách trích dẫn tiếng Việt.
- Theo dõi lịch sử soạn thảo khi người học đồng ý, thay vì chỉ chấm bản cuối.
- Không gắn nhãn “do AI viết” như một kết luận. Nếu thêm tín hiệu AI, phải công
  bố giới hạn và kiểm định riêng cho tiếng Việt.

## 6. Nguồn tham khảo chính thức

- [Turnitin: Understanding the similarity score](https://guides.turnitin.com/hc/en-us/articles/23435833938701-Understanding-the-similarity-score)
- [Turnitin: Overview of the new Similarity Report experience](https://guides.turnitin.com/hc/en-us/articles/24194876779661-Overview-of-the-new-Similarity-Report-experience)
- [Turnitin: How exclusion filters refine the Similarity Report](https://guides.turnitin.com/hc/en-us/articles/23539146689549-How-exclusion-filters-refine-the-Similarity-Report)
- [Turnitin Core API: Information for integrators](https://developers.turnitin.com/turnitin-core-api/information-for-ithenticate-integrators)
- [Turnitin: Using the AI Writing Report](https://guides.turnitin.com/hc/en-us/articles/22774058814093-Using-the-AI-Writing-Report)
