from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame,
    QGridLayout, QApplication, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from core.database import Database
from core.license_manager import get_cached_license, get_machine_id, parse_expiry_date


WEBSITE_URL = "https://link.truyennha.id.vn/tai-va-huong-dan"
ZALO_NUMBER = "0963913615"
ZALO_URL = f"https://zalo.me/{ZALO_NUMBER}"


class HomeDashboardTab(QWidget):
    # Giữ signal để tương thích với MainWindow
    switch_tab_signal = Signal(str)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(16)

        # -------------------------------------------------------------
        # 1. HERO BANNER GIỚI THIỆU PHẦN MỀM
        # -------------------------------------------------------------
        hero_frame = QFrame()
        hero_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1e1b4b, stop:0.55 #312e81, stop:1 #0f172a);
                border: 1px solid #4338ca;
                border-radius: 12px;
                padding: 18px 24px;
            }
        """)
        hf_layout = QHBoxLayout(hero_frame)
        hf_layout.setSpacing(16)

        text_box = QVBoxLayout()
        text_box.setSpacing(5)
        lbl_welcome = QLabel("⚡ Tools Marketing & Auto Post")
        lbl_welcome.setStyleSheet("color: #ffffff; font-size: 21px; font-weight: bold; border: none; background: transparent;")
        text_box.addWidget(lbl_welcome)

        lbl_sub = QLabel(
            "Tự động đăng bài Group Facebook, Threads & Comment Seeding • "
            "Chỉ 149k/tháng (Dùng thử FREE 5 ngày) • Nhận phát triển tools theo yêu cầu"
        )
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet("color: #c7d2fe; font-size: 13px; border: none; background: transparent;")
        text_box.addWidget(lbl_sub)
        hf_layout.addLayout(text_box, 1)

        btn_open_web = QPushButton("🌐 Mở Website Chính Thức")
        btn_open_web.setCursor(Qt.PointingHandCursor)
        btn_open_web.setFixedHeight(42)
        btn_open_web.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #06b6d4);
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 8px;
                padding: 0 18px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4ed8, stop:1 #0891b2);
            }
        """)
        btn_open_web.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WEBSITE_URL)))
        hf_layout.addWidget(btn_open_web)

        main_layout.addWidget(hero_frame)

        # -------------------------------------------------------------
        # 2. KHỐI THÔNG TIN BẢN QUYỀN & WEBSITE / HỖ TRỢ (2 CỘT)
        # -------------------------------------------------------------
        grid = QGridLayout()
        grid.setSpacing(14)

        # --- CỘT 1: THÔNG TIN BẢN QUYỀN ---
        lic_card = self._create_info_card("🛡️ THÔNG TIN BẢN QUYỀN", "#10b981")
        lic_layout = lic_card.layout()

        self.lbl_lic_status = QLabel("Trạng thái: Đang kiểm tra...")
        self.lbl_lic_status.setStyleSheet("color: #a6e3a1; font-size: 14px; font-weight: bold; border: none;")
        lic_layout.addWidget(self.lbl_lic_status)

        self.lbl_lic_expiry = QLabel("Thời hạn: --")
        self.lbl_lic_expiry.setStyleSheet("color: #e2e8f0; font-size: 13px; border: none;")
        lic_layout.addWidget(self.lbl_lic_expiry)

        self.lbl_lic_machine = QLabel("Mã máy: --")
        self.lbl_lic_machine.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_lic_machine.setStyleSheet("color: #94a3b8; font-size: 12px; font-family: Consolas, monospace; border: none;")
        lic_layout.addWidget(self.lbl_lic_machine)

        self.lbl_lic_key = QLabel("Key bản quyền: --")
        self.lbl_lic_key.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_lic_key.setStyleSheet("color: #94a3b8; font-size: 12px; font-family: Consolas, monospace; border: none;")
        lic_layout.addWidget(self.lbl_lic_key)

        lic_btn_row = QHBoxLayout()
        lic_btn_row.setSpacing(8)

        btn_copy_mid = QPushButton("📋 Copy Mã Máy")
        btn_copy_mid.setCursor(Qt.PointingHandCursor)
        btn_copy_mid.setFixedHeight(34)
        btn_copy_mid.setStyleSheet(self._btn_style("#334155", "#475569", "#f8fafc"))
        btn_copy_mid.clicked.connect(self._copy_machine_id)
        lic_btn_row.addWidget(btn_copy_mid)

        btn_manage_lic = QPushButton("🔑 Quản Lý / Gia Hạn Key")
        btn_manage_lic.setCursor(Qt.PointingHandCursor)
        btn_manage_lic.setFixedHeight(34)
        btn_manage_lic.setStyleSheet(self._btn_style("#065f46", "#047857", "#ecfdf5"))
        btn_manage_lic.clicked.connect(self._open_license_dialog)
        lic_btn_row.addWidget(btn_manage_lic)

        lic_layout.addStretch()
        lic_layout.addLayout(lic_btn_row)
        grid.addWidget(lic_card, 0, 0)

        # --- CỘT 2: WEBSITE & TẢI PHIÊN BẢN MỚI ---
        web_card = self._create_info_card("🌐 WEBSITE & TÀI LIỆU HƯỚNG DẪN", "#3b82f6")
        web_layout = web_card.layout()

        lbl_web_desc = QLabel(
            "Trang chủ chính thức để tải bộ cài mới nhất, xem hướng dẫn sử dụng chi tiết và kiểm tra bảng giá gói dịch vụ."
        )
        lbl_web_desc.setWordWrap(True)
        lbl_web_desc.setStyleSheet("color: #cbd5e1; font-size: 12.5px; border: none;")
        web_layout.addWidget(lbl_web_desc)

        lbl_web_url = QLabel(f"Link: {WEBSITE_URL}")
        lbl_web_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl_web_url.setStyleSheet("color: #60a5fa; font-size: 12.5px; font-weight: bold; border: none;")
        web_layout.addWidget(lbl_web_url)

        lbl_price = QLabel("💎 Gói bản quyền: 149.000đ / tháng (Máy mới miễn phí 5 ngày dùng thử)")
        lbl_price.setWordWrap(True)
        lbl_price.setStyleSheet("color: #fde047; font-size: 12.5px; font-weight: bold; border: none;")
        web_layout.addWidget(lbl_price)

        web_btn_row = QHBoxLayout()
        web_btn_row.setSpacing(8)

        btn_copy_web = QPushButton("📋 Copy Link Website")
        btn_copy_web.setCursor(Qt.PointingHandCursor)
        btn_copy_web.setFixedHeight(34)
        btn_copy_web.setStyleSheet(self._btn_style("#334155", "#475569", "#f8fafc"))
        btn_copy_web.clicked.connect(lambda: self._copy_and_notify(WEBSITE_URL, "Đã copy link Website!"))
        web_btn_row.addWidget(btn_copy_web)

        btn_visit_web = QPushButton("🚀 Truy Cập Trang Tải")
        btn_visit_web.setCursor(Qt.PointingHandCursor)
        btn_visit_web.setFixedHeight(34)
        btn_visit_web.setStyleSheet(self._btn_style("#1d4ed8", "#2563eb", "#ffffff"))
        btn_visit_web.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WEBSITE_URL)))
        web_btn_row.addWidget(btn_visit_web)

        web_layout.addStretch()
        web_layout.addLayout(web_btn_row)
        grid.addWidget(web_card, 0, 1)

        main_layout.addLayout(grid)

        # -------------------------------------------------------------
        # 3. KHỐI LIÊN HỆ ADMIN, BÁO LỖI & DỊCH VỤ PHÁT TRIỂN TOOLS
        # -------------------------------------------------------------
        support_card = self._create_info_card("🎧 LIÊN HỆ ADMIN & BÁO LỖI KỸ THUẬT", "#f59e0b")
        sup_layout = support_card.layout()

        sup_row = QHBoxLayout()
        sup_row.setSpacing(18)

        sup_info = QVBoxLayout()
        sup_info.setSpacing(6)

        lbl_zalo = QLabel(f"💬 Zalo Quản Trị Viên: {ZALO_NUMBER}")
        lbl_zalo.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl_zalo.setStyleSheet("color: #34d399; font-size: 15px; font-weight: bold; border: none;")
        sup_info.addWidget(lbl_zalo)

        lbl_bug = QLabel(
            "• Báo lỗi phần mềm: Vui lòng chụp ảnh màn hình lỗi kèm Mã Máy (Machine ID) gửi qua Zalo Admin để được xử lý nhanh nhất.\n"
            "• Gia hạn / Nâng cấp bản quyền: Nhắn Mã Máy qua Zalo 0963913615 để kích hoạt gói 149k/tháng hoặc vĩnh viễn.\n"
            "• Dịch vụ riêng: Nhận code & phát triển tools tự động hóa Facebook, Threads, TikTok, Shopee theo yêu cầu."
        )
        lbl_bug.setWordWrap(True)
        lbl_bug.setStyleSheet("color: #cbd5e1; font-size: 12.5px; line-height: 1.5; border: none;")
        sup_info.addWidget(lbl_bug)
        sup_row.addLayout(sup_info, 1)

        sup_btns = QVBoxLayout()
        sup_btns.setSpacing(8)

        btn_zalo = QPushButton("💬 Nhắn Zalo Admin")
        btn_zalo.setCursor(Qt.PointingHandCursor)
        btn_zalo.setFixedSize(190, 38)
        btn_zalo.setStyleSheet(self._btn_style("#059669", "#047857", "#ffffff"))
        btn_zalo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ZALO_URL)))
        sup_btns.addWidget(btn_zalo)

        btn_copy_zalo = QPushButton(f"📋 Copy SĐT: {ZALO_NUMBER}")
        btn_copy_zalo.setCursor(Qt.PointingHandCursor)
        btn_copy_zalo.setFixedSize(190, 36)
        btn_copy_zalo.setStyleSheet(self._btn_style("#334155", "#475569", "#f8fafc"))
        btn_copy_zalo.clicked.connect(lambda: self._copy_and_notify(ZALO_NUMBER, f"Đã copy số Zalo Admin: {ZALO_NUMBER}"))
        sup_btns.addWidget(btn_copy_zalo)

        sup_btns.addStretch()
        sup_row.addLayout(sup_btns)
        sup_layout.addLayout(sup_row)

        main_layout.addWidget(support_card)
        main_layout.addStretch()

        self.refresh_stats()

    def _create_info_card(self, title: str, accent_color: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: #111625;
                border: 1px solid #1e293b;
                border-top: 3px solid {accent_color};
                border-radius: 10px;
                padding: 14px 18px;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setSpacing(8)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet(f"color: {accent_color}; font-size: 13px; font-weight: bold; letter-spacing: 0.5px; border: none;")
        layout.addWidget(lbl_t)
        return card

    def _btn_style(self, bg: str, hover_bg: str, fg: str) -> str:
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-radius: 7px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """

    def _copy_and_notify(self, text: str, msg: str):
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Thông báo", msg)

    def _copy_machine_id(self):
        mid = get_machine_id(self.db)
        self._copy_and_notify(mid, f"Đã copy Mã Máy:\n{mid}")

    def _open_license_dialog(self):
        from ui.license_dialog import LicenseDialog
        dlg = LicenseDialog(self.db, is_blocking=False, parent=self)
        dlg.exec()
        self.refresh_stats()
        win = self.window()
        if hasattr(win, "update_license_display"):
            win.update_license_display()

    def refresh_stats(self):
        try:
            mid = get_machine_id(self.db)
            self.lbl_lic_machine.setText(f"Mã máy: {mid}")

            cached = get_cached_license(self.db)
            if not cached or cached.get("machine_id") != mid:
                self.lbl_lic_status.setText("Trạng thái: ⚠️ Chưa kích hoạt bản quyền")
                self.lbl_lic_status.setStyleSheet("color: #facc15; font-size: 14px; font-weight: bold; border: none;")
                self.lbl_lic_expiry.setText("Thời hạn: Chưa có dữ liệu")
                self.lbl_lic_key.setText("Key bản quyền: Chưa gán")
                return

            key = cached.get("license_key") or "--"
            self.lbl_lic_key.setText(f"Key bản quyền: {key}")

            status = (cached.get("status") or "").upper()
            if status in ("BLOCKED", "KHÓA", "TẠM KHÓA", "REVOKED"):
                self.lbl_lic_status.setText("Trạng thái: 🚫 Đã bị khóa")
                self.lbl_lic_status.setStyleSheet("color: #f87171; font-size: 14px; font-weight: bold; border: none;")
                self.lbl_lic_expiry.setText("Thời hạn: Vui lòng liên hệ Admin để mở khóa")
                return

            if status == "EXPIRED":
                self.lbl_lic_status.setText("Trạng thái: 🔴 Đã hết hạn")
                self.lbl_lic_status.setStyleSheet("color: #f87171; font-size: 14px; font-weight: bold; border: none;")
                self.lbl_lic_expiry.setText(f"Thời hạn: {cached.get('expiry_display', 'Đã hết hạn')}")
                return

            _, is_valid, msg = parse_expiry_date(cached.get("expiry_raw", ""))
            if not is_valid and cached.get("expiry_display"):
                _, is_valid, msg = parse_expiry_date(cached.get("expiry_display", ""))

            if is_valid:
                self.lbl_lic_status.setText("Trạng thái: 🟢 Bản quyền đang hoạt động")
                self.lbl_lic_status.setStyleSheet("color: #34d399; font-size: 14px; font-weight: bold; border: none;")
                self.lbl_lic_expiry.setText(f"Thời hạn: {msg}")
            else:
                self.lbl_lic_status.setText("Trạng thái: 🔴 Bản quyền hết hạn / không hợp lệ")
                self.lbl_lic_status.setStyleSheet("color: #f87171; font-size: 14px; font-weight: bold; border: none;")
                self.lbl_lic_expiry.setText(f"Thời hạn: {msg}")
        except Exception:
            pass
