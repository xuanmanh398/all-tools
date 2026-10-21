import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QClipboard, QIcon
from core.license_manager import (
    get_machine_id, verify_license_online, auto_register_machine,
    save_cached_license, get_cached_license, DEFAULT_SHEET_URL,
    DEFAULT_WEB_APP_URL, parse_expiry_date
)

DARK_DIALOG_QSS = """
QDialog {
    background-color: #181825;
    color: #cdd6f4;
    font-family: 'Segoe UI', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Arial', sans-serif;
    font-size: 13px;
}
QFrame.card {
    background-color: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 8px;
}
QLabel.cardTitle {
    color: #89b4fa;
    font-weight: bold;
    font-size: 13px;
    border: none;
    background: transparent;
}
QLabel.cardHint {
    color: #fab387;
    font-size: 11px;
    border: none;
    background: transparent;
}
QLineEdit {
    background-color: #11111b;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    min-height: 40px;
}
QLineEdit:focus {
    border: 1px solid #89b4fa;
}
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
    font-size: 13px;
    min-height: 40px;
}
QPushButton:hover {
    background-color: #45475a;
}
QPushButton#btnPrimary {
    background-color: #89b4fa;
    color: #11111b;
    font-weight: bold;
    border: none;
    min-height: 40px;
    min-width: 140px;
}
QPushButton#btnPrimary:hover {
    background-color: #b4befe;
}
QPushButton#btnCopy {
    background-color: #a6e3a1;
    color: #11111b;
    font-weight: bold;
    border: none;
    min-height: 40px;
    min-width: 110px;
}
QPushButton#btnCopy:hover {
    background-color: #94e2d5;
}
QPushButton#btnSync {
    background-color: #fab387;
    color: #11111b;
    font-weight: bold;
    border: none;
    min-height: 40px;
    min-width: 110px;
}
QPushButton#btnSync:hover {
    background-color: #f9e2af;
}
QPushButton#btnExit {
    background-color: #313244;
    color: #f38ba8;
    border: 1px solid #f38ba8;
    font-weight: bold;
    min-height: 40px;
}
QPushButton#btnExit:hover {
    background-color: #45475a;
}
"""

class AutoRegisterWorker(QThread):
    finished_signal = Signal(bool, str, dict)

    def __init__(self, web_app_url: str, machine_id: str):
        super().__init__()
        self.web_app_url = web_app_url
        self.machine_id = machine_id

    def run(self):
        try:
            ok, msg, info = auto_register_machine(self.web_app_url, self.machine_id)
            self.finished_signal.emit(ok, msg, info)
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi tự động kết nối: {str(e)}", {})


class LicenseCheckWorker(QThread):
    finished_signal = Signal(bool, str, dict)

    def __init__(self, sheet_url: str, machine_id: str, license_key: str):
        super().__init__()
        self.sheet_url = sheet_url
        self.machine_id = machine_id
        self.license_key = license_key

    def run(self):
        try:
            ok, msg, info = verify_license_online(self.sheet_url, self.machine_id, self.license_key)
            self.finished_signal.emit(ok, msg, info)
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi xác minh bản quyền: {str(e)}", {})


class LicenseDialog(QDialog):
    def __init__(self, db, is_blocking: bool = True, parent=None):
        super().__init__(parent)
        self.db = db
        self.is_blocking = is_blocking
        self.machine_id = get_machine_id(self.db)
        self.worker = None
        self.auto_worker = None

        self.setWindowTitle("🛡️ Xác Minh Bản Quyền - Auto Post")
        self.resize(640, 600)
        self.setMinimumSize(600, 560)
        self.setStyleSheet(DARK_DIALOG_QSS)

        # Cài đặt icon cho hộp thoại và taskbar
        from core.database import get_asset_path
        icon_path = get_asset_path("icon.ico")
        if not os.path.exists(icon_path):
            icon_path = get_asset_path("icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.init_ui()
        self.load_current_status()

        # Tự động đẩy mã máy và lấy key khi khởi động hộp thoại
        web_app_url = self.db.get_setting("license_web_app_url") or DEFAULT_WEB_APP_URL
        if web_app_url:
            self.start_auto_register(silent=True)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(24, 20, 24, 20)

        # Header Title
        header_box = QVBoxLayout()
        header_box.setSpacing(4)
        title = QLabel("🛡️ XÁC MINH BẢN QUYỀN PHẦN MỀM")
        title_font = QFont("Segoe UI", 16, QFont.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: #89b4fa; margin-bottom: 2px;")
        title.setAlignment(Qt.AlignCenter)
        header_box.addWidget(title)

        subtitle = QLabel("Hệ thống kiểm tra và xác thực bản quyền trực tuyến")
        subtitle.setStyleSheet("color: #a6adc8; font-size: 12px;")
        subtitle.setAlignment(Qt.AlignCenter)
        header_box.addWidget(subtitle)
        main_layout.addLayout(header_box)

        # 1. Khung Card 1: Machine ID
        card_hwid = QFrame()
        card_hwid.setProperty("class", "card")
        layout_hwid = QVBoxLayout(card_hwid)
        layout_hwid.setSpacing(10)
        layout_hwid.setContentsMargins(16, 14, 16, 14)

        lbl_title_hwid = QLabel("1. Mã Định Danh Máy (Machine ID)")
        lbl_title_hwid.setProperty("class", "cardTitle")
        layout_hwid.addWidget(lbl_title_hwid)
        
        row_hwid = QHBoxLayout()
        row_hwid.setSpacing(10)
        self.txt_hwid = QLineEdit(self.machine_id)
        self.txt_hwid.setReadOnly(True)
        self.txt_hwid.setStyleSheet("font-weight: bold; letter-spacing: 1px; color: #f9e2af; font-size: 13px;")
        row_hwid.addWidget(self.txt_hwid)

        self.btn_copy_hwid = QPushButton("📋 Sao Chép")
        self.btn_copy_hwid.setObjectName("btnCopy")
        self.btn_copy_hwid.clicked.connect(self.copy_hwid)
        row_hwid.addWidget(self.btn_copy_hwid)
        layout_hwid.addLayout(row_hwid)

        lbl_hint = QLabel("💡 Mã máy được dùng để kích hoạt và xác thực bản quyền cho thiết bị này.")
        lbl_hint.setProperty("class", "cardHint")
        layout_hwid.addWidget(lbl_hint)
        main_layout.addWidget(card_hwid)

        # 2. Khung Card 2: Key Bản Quyền
        card_key = QFrame()
        card_key.setProperty("class", "card")
        layout_key = QVBoxLayout(card_key)
        layout_key.setSpacing(10)
        layout_key.setContentsMargins(16, 14, 16, 14)

        lbl_title_key = QLabel("2. Key Bản Quyền (Tự động tạo hoặc dán vào)")
        lbl_title_key.setProperty("class", "cardTitle")
        layout_key.addWidget(lbl_title_key)

        row_key = QHBoxLayout()
        row_key.setSpacing(10)
        self.txt_key = QLineEdit()
        self.txt_key.setPlaceholderText("Key sẽ được tạo tự động từ hệ thống...")
        row_key.addWidget(self.txt_key)

        self.btn_sync = QPushButton("🔄 Kiểm Tra Lại")
        self.btn_sync.setObjectName("btnSync")
        self.btn_sync.setToolTip("Kiểm tra và cập nhật trạng thái bản quyền từ máy chủ")
        self.btn_sync.clicked.connect(lambda: self.start_auto_register(silent=False))
        row_key.addWidget(self.btn_sync)

        self.btn_activate = QPushButton("🔑 Kích Hoạt")
        self.btn_activate.setObjectName("btnPrimary")
        self.btn_activate.clicked.connect(self.start_activation)
        row_key.addWidget(self.btn_activate)
        layout_key.addLayout(row_key)
        main_layout.addWidget(card_key)

        # 3. Khung Card 3: Trạng Thái Bản Quyền
        card_status = QFrame()
        card_status.setProperty("class", "card")
        layout_status = QVBoxLayout(card_status)
        layout_status.setSpacing(8)
        layout_status.setContentsMargins(16, 14, 16, 14)

        lbl_title_status = QLabel("3. Thông Tin Bản Quyền Hiện Tại")
        lbl_title_status.setProperty("class", "cardTitle")
        layout_status.addWidget(lbl_title_status)

        self.lbl_status_icon = QLabel("⚠️ Trạng thái: Đang kết nối máy chủ...")
        self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #fab387; border: none; background: transparent;")
        layout_status.addWidget(self.lbl_status_icon)

        self.lbl_expiry_info = QLabel("Hạn sử dụng: --")
        self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #cdd6f4; border: none; background: transparent;")
        layout_status.addWidget(self.lbl_expiry_info)

        self.lbl_verified_at = QLabel("")
        self.lbl_verified_at.setStyleSheet("font-size: 11px; color: #a6adc8; border: none; background: transparent;")
        layout_status.addWidget(self.lbl_verified_at)

        main_layout.addWidget(card_status)

        # Action Buttons ở Bottom
        main_layout.addStretch()
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)
        bottom_row.addStretch()

        if self.is_blocking:
            self.btn_exit = QPushButton("❌ Thoát Ứng Dụng")
            self.btn_exit.setObjectName("btnExit")
            self.btn_exit.clicked.connect(self.reject)
            bottom_row.addWidget(self.btn_exit)

            self.btn_continue = QPushButton("🚀 Vào Phần Mềm")
            self.btn_continue.setObjectName("btnPrimary")
            self.btn_continue.setEnabled(False)
            self.btn_continue.clicked.connect(self.accept)
            bottom_row.addWidget(self.btn_continue)
        else:
            self.btn_close = QPushButton("Đóng")
            self.btn_close.clicked.connect(self.accept)
            bottom_row.addWidget(self.btn_close)

        main_layout.addLayout(bottom_row)

    def copy_hwid(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.machine_id)
        self.btn_copy_hwid.setText("✅ Đã Chép!")
        QTimer.singleShot(2500, lambda: self.btn_copy_hwid.setText("📋 Sao Chép"))

    def load_current_status(self):
        # Tự động điền lại Key đã lưu trước đó nếu có
        saved_key = self.db.get_setting("license_key") or self.db.get_setting("last_entered_license_key") or ""
        if saved_key:
            self.txt_key.setText(saved_key)

        cached = get_cached_license(self.db)
        if cached and cached.get("machine_id") == self.machine_id:
            # 1. KIỂM TRA TRẠNG THÁI KHÓA TỪ SERVER
            if cached.get("status") in ("BLOCKED", "KHÓA", "TẠM KHÓA", "REVOKED"):
                self.lbl_status_icon.setText("🔴 Trạng thái: Bản Quyền Đã Bị KHÓA!")
                self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #f38ba8; border: none; background: transparent;")
                self.lbl_expiry_info.setText("Bản quyền thiết bị này đã bị Quản trị viên tạm khóa.")
                self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #f38ba8; border: none; background: transparent;")
                if self.is_blocking:
                    self.btn_continue.setEnabled(False)
                return

            # 2. KIỂM TRA TRẠNG THÁI HẾT HẠN
            if cached.get("status") == "EXPIRED":
                self.lbl_status_icon.setText("🔴 Trạng thái: Bản Quyền Đã Hết Hạn!")
                self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #f38ba8; border: none; background: transparent;")
                self.lbl_expiry_info.setText(f"Hạn sử dụng: {cached.get('expiry_display') or 'Đã hết hạn sử dụng'}")
                self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #f38ba8; border: none; background: transparent;")
                if self.is_blocking:
                    self.btn_continue.setEnabled(False)
                return

            raw_expiry = cached.get("expiry_raw", "")
            _, is_valid, msg = parse_expiry_date(raw_expiry)
            if is_valid:
                self.lbl_status_icon.setText("🟢 Trạng thái: Đã Kích Hoạt Bản Quyền")
                self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6e3a1; border: none; background: transparent;")
                self.lbl_expiry_info.setText(f"Hạn sử dụng: {msg}")
                self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #a6e3a1; font-weight: 500; border: none; background: transparent;")
                self.lbl_verified_at.setText(f"Lần kiểm tra gần nhất: {cached.get('verified_at', '')}")
                if self.is_blocking:
                    self.btn_continue.setEnabled(True)
            else:
                self.lbl_status_icon.setText("🔴 Trạng thái: Bản Quyền Đã Hết Hạn!")
                self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #f38ba8; border: none; background: transparent;")
                self.lbl_expiry_info.setText(f"Hạn sử dụng: {msg}")
                self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #f38ba8; border: none; background: transparent;")
                if self.is_blocking:
                    self.btn_continue.setEnabled(False)
        else:
            self.lbl_status_icon.setText("⚠️ Trạng thái: Chưa Kích Hoạt Bản Quyền")
            self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #fab387; border: none; background: transparent;")
            self.lbl_expiry_info.setText("Hệ thống đang kết nối và xác thực thiết bị...")
            if self.is_blocking:
                self.btn_continue.setEnabled(False)

    def start_auto_register(self, silent: bool = False):
        web_app_url = self.db.get_setting("license_web_app_url") or DEFAULT_WEB_APP_URL
        if not web_app_url:
            if not silent:
                self.start_activation()
            return

        self.btn_sync.setEnabled(False)
        self.lbl_status_icon.setText("⏳ Đang kết nối và đồng bộ bản quyền với máy chủ...")
        self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #89b4fa; border: none; background: transparent;")
        if self.is_blocking:
            self.btn_continue.setEnabled(False)

        self.auto_worker = AutoRegisterWorker(web_app_url, self.machine_id)
        self.auto_worker.finished_signal.connect(lambda ok, msg, info: self.on_auto_register_finished(ok, msg, info, silent))
        self.auto_worker.start()

    def on_auto_register_finished(self, ok: bool, message: str, info: dict, silent: bool):
        self.btn_sync.setEnabled(True)
        if ok and info.get("license_key"):
            key = info.get("license_key")
            self.txt_key.setText(key)
            self.db.set_setting("last_entered_license_key", key)

            status = (info.get("status") or "ACTIVE").strip().upper()
            if status in ("BLOCKED", "KHÓA", "TẠM KHÓA", "REVOKED"):
                self.db.set_setting("license_status", "BLOCKED")
                self.lbl_status_icon.setText("🔴 Trạng thái: Bản Quyền Đã Bị KHÓA!")
                self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #f38ba8; border: none; background: transparent;")
                self.lbl_expiry_info.setText("Bản quyền thiết bị này đã bị Quản trị viên tạm khóa.")
                self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #f38ba8; border: none; background: transparent;")
                if self.is_blocking:
                    self.btn_continue.setEnabled(False)
                if not silent:
                    QMessageBox.critical(self, "Bị Khóa", "Bản quyền máy này đang bị khóa bởi Quản trị viên.")
                return

            is_valid = info.get("is_valid", False)
            if is_valid:
                save_cached_license(self.db, info)
                self.lbl_status_icon.setText("🟢 Trạng thái: Đã Kích Hoạt Bản Quyền!")
                self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6e3a1; border: none; background: transparent;")
                self.lbl_expiry_info.setText(f"Hạn sử dụng: {info.get('expiry_display', '')}")
                self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #a6e3a1; font-weight: 500; border: none; background: transparent;")
                self.lbl_verified_at.setText(f"Đồng bộ lúc: {info.get('verified_at', '')}")
                if self.is_blocking:
                    self.btn_continue.setEnabled(True)
                if not silent:
                    QMessageBox.information(self, "Bản Quyền Hợp Lệ", message)
                    if self.is_blocking:
                        self.accept()
            else:
                if self.is_blocking:
                    self.btn_continue.setEnabled(False)

                exp_disp = info.get("expiry_display", "")
                if "hết hạn" in message.lower() or "expired" in message.lower() or "hết hạn" in exp_disp.lower() or status == "EXPIRED":
                    self.db.set_setting("license_status", "EXPIRED")
                    self.db.set_setting("license_expiry_raw", info.get("expiry_raw", ""))
                    self.db.set_setting("license_expiry_display", exp_disp)
                    self.lbl_status_icon.setText("🔴 Trạng thái: Bản Quyền Đã Hết Hạn!")
                    self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #f38ba8; border: none; background: transparent;")
                    self.lbl_expiry_info.setText(f"Hạn sử dụng: {exp_disp or message}")
                    self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #f38ba8; border: none; background: transparent;")
                    if not silent:
                        QMessageBox.warning(self, "Hết Hạn", f"Bản quyền thiết bị này đã hết hạn!\n{exp_disp or message}\nVui lòng liên hệ Quản trị viên để gia hạn.")
                else:
                    self.lbl_status_icon.setText("⏳ Trạng thái: Thiết bị đã được ghi nhận (Chờ kích hoạt)")
                    self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #fab387; border: none; background: transparent;")
                    self.lbl_expiry_info.setText("Vui lòng liên hệ Quản trị viên để kích hoạt thời hạn sử dụng.")
                    self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #fab387; border: none; background: transparent;")
                    if not silent:
                        QMessageBox.information(self, "Thông Báo", "Thiết bị và Key đã được gửi lên hệ thống.\nVui lòng chờ Quản trị viên cấp thời hạn rồi bấm 'Kiểm Tra Lại'!")
        else:
            # Nếu không kết nối được tới máy chủ (ngoại tuyến / mất mạng)
            cached = get_cached_license(self.db)
            if cached and cached.get("machine_id") == self.machine_id:
                if cached.get("status") not in ("BLOCKED", "KHÓA", "TẠM KHÓA", "REVOKED", "EXPIRED"):
                    dt, is_valid, msg = parse_expiry_date(cached.get("expiry_raw", ""))
                    if is_valid:
                        self.lbl_status_icon.setText("🟢 Trạng thái: Bản Quyền Hợp Lệ (Ngoại Tuyến)")
                        self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6e3a1; border: none; background: transparent;")
                        self.lbl_expiry_info.setText(f"Hạn sử dụng: {msg}")
                        self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #a6e3a1; font-weight: 500; border: none; background: transparent;")
                        if self.is_blocking:
                            self.btn_continue.setEnabled(True)
                        return

            self.lbl_status_icon.setText("⚠️ Không thể kết nối tới máy chủ")
            self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #fab387; border: none; background: transparent;")
            if self.is_blocking:
                self.btn_continue.setEnabled(False)
            if not silent:
                self.start_activation()

    def start_activation(self):
        entered_key = self.txt_key.text().strip()
        if not entered_key:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng nhập Key kích hoạt hoặc bấm 'Kiểm Tra Lại'!")
            self.txt_key.setFocus()
            return

        self.db.set_setting("last_entered_license_key", entered_key)
        sheet_url = self.db.get_setting("license_web_app_url") or DEFAULT_WEB_APP_URL or self.db.get_setting("license_sheet_url") or DEFAULT_SHEET_URL
        
        self.btn_activate.setEnabled(False)
        self.btn_activate.setText("⏳ Đang Kiểm Tra...")
        self.lbl_status_icon.setText("⏳ Đang kết nối kiểm tra dữ liệu bản quyền...")
        self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #89b4fa; border: none; background: transparent;")

        self.worker = LicenseCheckWorker(sheet_url, self.machine_id, entered_key)
        self.worker.finished_signal.connect(self.on_activation_finished)
        self.worker.start()

    def on_activation_finished(self, ok: bool, message: str, info: dict):
        self.btn_activate.setEnabled(True)
        self.btn_activate.setText("🔑 Kích Hoạt")

        if ok and info.get("is_valid") is True:
            save_cached_license(self.db, info)
            self.lbl_status_icon.setText("🟢 Trạng thái: Đã Kích Hoạt Thành Công!")
            self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6e3a1; border: none; background: transparent;")
            self.lbl_expiry_info.setText(f"Hạn sử dụng: {info.get('expiry_display', '')}")
            self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #a6e3a1; font-weight: 500; border: none; background: transparent;")
            self.lbl_verified_at.setText(f"Xác thực lúc: {info.get('verified_at', '')}")
            
            if self.is_blocking:
                self.btn_continue.setEnabled(True)

            QMessageBox.information(self, "Kích Hoạt Thành Công", message)
            if self.is_blocking:
                self.accept()
        else:
            if self.is_blocking:
                self.btn_continue.setEnabled(False)

            # Phân biệt rõ Hết Hạn vs Bị Khóa vs Thất Bại
            if "hết hạn" in message.lower() or "expired" in message.lower():
                self.db.set_setting("license_status", "EXPIRED")
                if info.get("expiry_raw"):
                    self.db.set_setting("license_expiry_raw", info.get("expiry_raw"))
                if info.get("expiry_display"):
                    self.db.set_setting("license_expiry_display", info.get("expiry_display"))
                self.lbl_status_icon.setText("🔴 Trạng thái: Bản Quyền Đã Hết Hạn!")
            elif "khóa" in message.lower() or "blocked" in message.lower():
                self.db.set_setting("license_status", "BLOCKED")
                self.lbl_status_icon.setText("🔴 Trạng thái: Bản Quyền Đã Bị KHÓA!")
            else:
                self.lbl_status_icon.setText("❌ Kích hoạt thất bại")

            self.lbl_status_icon.setStyleSheet("font-size: 13px; font-weight: bold; color: #f38ba8; border: none; background: transparent;")
            self.lbl_expiry_info.setText(message)
            self.lbl_expiry_info.setStyleSheet("font-size: 12px; color: #f38ba8; border: none; background: transparent;")
            QMessageBox.critical(self, "Xác Thực Bản Quyền", message)

    def accept(self):
        """Chỉ cho phép vào phần mềm khi bản quyền ĐÃ XÁC MINH THÀNH CÔNG và CÒN HẠN."""
        cached = get_cached_license(self.db)
        if not cached:
            QMessageBox.warning(self, "Chưa Kích Hoạt", "Vui lòng kích hoạt bản quyền trước khi vào phần mềm!")
            return
        
        status = (cached.get("status") or "").upper()
        if status in ("BLOCKED", "KHÓA", "TẠM KHÓA", "REVOKED"):
            QMessageBox.critical(self, "Bị Khóa", "Bản quyền thiết bị này đang bị khóa bởi Quản trị viên!")
            return

        if status == "EXPIRED":
            QMessageBox.critical(self, "Hết Hạn", "Bản quyền đã hết hạn sử dụng. Vui lòng liên hệ Quản trị viên để gia hạn!")
            return

        dt, is_valid, msg = parse_expiry_date(cached.get("expiry_raw", ""))
        if not is_valid:
            QMessageBox.critical(self, "Hết Hạn", f"Bản quyền đã hết hạn! {msg}\nVui lòng liên hệ Quản trị viên để gia hạn.")
            return

        super().accept()
