# 🛡️ HƯỚNG DẪN CẤU HÌNH GOOGLE APPS SCRIPT ĐỂ CẤP KEY TỰ ĐỘNG

Tệp Google Sheet của bạn:
👉 **[Mở Google Sheet Quản Lý Bản Quyền](https://docs.google.com/spreadsheets/d/1ZI6E1MnQHLIbzaDtdPLEszIxOZzFNqbh8l_Cx9718II/edit?usp=sharing)**

Phần mềm đã được liên kết trực tiếp và cố định với Google Sheet trên, **không có nút cấu hình admin trên giao diện phần mềm** để đảm bảo bảo mật và giao diện tinh gọn nhất cho người dùng.

---

## BƯỚC 1: Dán Mã Apps Script Vào Google Sheet (Chỉ cần làm 1 lần duy nhất)

1. Mở link Google Sheet: `https://docs.google.com/spreadsheets/d/1ZI6E1MnQHLIbzaDtdPLEszIxOZzFNqbh8l_Cx9718II/edit`
2. Trên thanh menu của Google Sheet, bấm: **Tiện ích mở rộng** (Extensions) -> **Apps Script**.
3. Trong trình soạn thảo mở ra, xóa toàn bộ mã có sẵn trong file `Code.gs`.
4. Mở tệp **[`google_apps_script.js`](file:///e:/CwAI/CwAI_FB_Upload/google_apps_script.js)** trong thư mục dự án, sao chép toàn bộ nội dung và dán vào.
5. Bấm biểu tượng đĩa mềm **💾 Lưu dự án (Save)**.
6. Quay lại trang Google Sheet và bấm phím **F5** (Tải lại trang).

> **Kết quả:** Trên thanh menu của Google Sheet sẽ xuất hiện menu mới tên là:
> **`🛡️ Quản Lý Bản Quyền`**

---

## BƯỚC 2: Khởi Tạo Tiêu Đề Bảng (Nếu Bảng Rỗng)

- Bấm vào menu **`🛡️ Quản Lý Bản Quyền`** -> Chọn **`📋 Khởi Tạo Tiêu Đề Cột`**.
- Google sẽ yêu cầu bạn cấp quyền lần đầu (Bấm *Tiếp tục* -> Chọn tài khoản Google của bạn -> Bấm *Nâng cao / Advanced* -> Bấm *Đi tới dự án (Không an toàn)* -> Bấm *Cho phép*).
- Bảng tính sẽ tự động tạo đẹp mắt 5 cột:
  - **`Machine_ID`**: Mã định danh máy khách gửi.
  - **`License_Key`**: Key kích hoạt.
  - **`Expiry_Date`**: Hạn sử dụng (VD: `2026-12-31` hoặc `LIFETIME`).
  - **`Status`**: Trạng thái (`ACTIVE` hoặc `BLOCKED`).
  - **`Note`**: Tên / SĐT khách hàng.

---

## BƯỚC 3: Quy Trình Cấp Key Khi Có Khách Hàng Mới

1. Khách hàng mở phần mềm, hộp thoại bản quyền hiện lên:
   - Khách bấm nút **`📋 Sao Chép`** để lấy Mã Máy (Ví dụ: `CWAI-CEC8-66BB-5043-A9C4`) và gửi cho bạn qua Zalo/Facebook.
2. Bạn mở Google Sheet -> Bấm menu: **`🛡️ Quản Lý Bản Quyền`** -> **`➕ Tạo Key Mới Cho Khách`**:
   - **Hộp thoại 1:** Dán Mã Máy của khách vào.
   - **Hộp thoại 2:** Nhập số ngày khách mua (Ví dụ: `30`, `90`, `365`) hoặc gõ `LIFETIME` nếu mua vĩnh viễn.
   - **Hộp thoại 3:** Ghi tên khách hoặc SĐT để lưu vào ghi chú.
3. Apps Script sẽ **tự động sinh Key ngẫu nhiên**, tính hạn sử dụng và điền vào bảng tính, đồng thời bật popup hiện rõ Key cho bạn.
4. Bạn sao chép Key đó gửi cho khách.
5. Khách dán Key vào phần mềm và bấm **`🔑 Kích Hoạt Ngay`**:
   - Phần mềm tự động kết nối đối soát với Google Sheet theo Mã Máy đó.
   - Nếu đúng Key và chưa hết hạn -> Phần mềm được mở khóa ngay lập tức!

---

## BƯỚC 4: Khóa Hoặc Gia Hạn Key Từ Xa

- **Khóa khách hàng:** Chọn dòng của khách hàng đó trên Google Sheet -> Bấm menu **`🛡️ Quản Lý Bản Quyền`** -> Chọn **`🔒 Khóa Key`** (Status chuyển thành `BLOCKED`). Phần mềm của khách sẽ lập tức bị chặn.
- **Gia hạn:** Chọn dòng của khách -> Bấm menu **`🛡️ Quản Lý Bản Quyền`** -> Chọn **`📅 Gia Hạn Thêm 30 Ngày`**.
