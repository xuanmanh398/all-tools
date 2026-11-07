# ⚡ HƯỚNG DẪN 3 BƯỚC CÀI ĐẶT HỆ THỐNG BẢN QUYỀN CLOUDFLARE D1 (MIỄN PHÍ 100%)

Hệ thống sử dụng **Cloudflare D1 (SQLite Edge)** kết hợp **Cloudflare Worker** giúp phần mềm kiểm tra bản quyền siêu tốc (~40ms), không bị Cold Start như Google Sheet, và có sẵn **Trang Web Quản Trị (Admin Dashboard)** để bạn tạo key, gia hạn, khóa key ngay trên điện thoại hoặc máy tính.

---

### BƯỚC 1: TẠO CƠ SỞ DỮ LIỆU CLOUDFLARE D1
1. Đăng nhập vào [Cloudflare Dashboard](https://dash.cloudflare.com/) (miễn phí).
2. Ở thanh menu bên trái, chọn **Workers & Pages** ➔ chọn **D1 SQL Database**.
3. Bấm **Create database**:
   - Tên cơ sở dữ liệu: `tools_marketing_db`
   - Bấm **Create**.
4. Chọn database vừa tạo, chuyển sang tab **Console**:
   - Mở file `cloudflare_d1/schema.sql` trong thư mục dự án này, copy toàn bộ nội dung.
   - Dán vào ô Console trên Cloudflare rồi bấm **Execute**.
   - *(Cloudflare sẽ tạo bảng `licenses` và thêm sẵn 2 key mẫu để bạn test ngay lập tức).*

---

### BƯỚC 2: TẠO CLOUDFLARE WORKER & LIÊN KẾT DATABASE
1. Tại menu bên trái, chọn **Workers & Pages** ➔ bấm **Create Application** ➔ chọn **Create Worker**:
   - Tên Worker: đặt tên bất kỳ (ví dụ: `tools-marketing-license`).
   - Bấm **Deploy**.
2. Sau khi deploy xong, bấm nút **Edit code**:
   - Xóa toàn bộ mã nguồn mặc định trong ô soạn thảo.
   - Mở file `cloudflare_d1/worker.js` trong thư mục dự án này, copy toàn bộ nội dung và dán vào.
   - Bấm **Save and deploy**.
3. Trở ra trang quản lý Worker đó:
   - Chuyển sang tab **Settings** ➔ chọn mục **Bindings** (hoặc **Variables and Secrets** tùy giao diện mới).
   - Tại mục **D1 Database Bindings**, bấm **Add**:
     - **Variable name**: Gõ chính xác chữ `DB` (viết hoa 2 chữ cái).
     - **D1 database**: Chọn database `tools_marketing_db` bạn đã tạo ở Bước 1.
     - Bấm **Save** (hoặc **Deploy**).

---

### BƯỚC 3: DÙNG TRANG WEB QUẢN TRỊ & KẾT NỐI VÀO PHẦN MỀM
1. Mở đường link của Worker trên trình duyệt (ví dụ: `https://tools-marketing-license.xxx.workers.dev`):
   - Mật khẩu mặc định là: `admin123` (bạn có thể đổi trong file `worker.js`).
   - Bạn sẽ thấy ngay **Trang Web Quản Trị Bản Quyền**: bấm **"➕ Thêm Key Mới"** để tạo key theo ngày (30 ngày, 1 năm, Vĩnh viễn) cho khách.
2. Cập nhật đường link Worker của bạn vào file `core/license_manager.py`:
   - Tìm biến `DEFAULT_D1_WORKER_URL = "https://..."` và thay bằng link Worker của bạn.
