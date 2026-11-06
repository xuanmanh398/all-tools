import os
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QMessageBox, QApplication,
    QPushButton, QHBoxLayout, QLabel, QStackedWidget, QFrame
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QIcon, QFont
from core.database import Database
from ui.account_tab import AccountTab
from ui.group_tab import GroupTab
from ui.content_tab import ContentTab
from ui.poster_tab import PosterTab
from ui.threads_account_tab import ThreadsAccountTab
from ui.threads_poster_tab import ThreadsPosterTab
from ui.floating_widget import FloatingWidget
from ui.system_tray import SystemTrayManager


class PeriodicLicenseCheckWorker(QThread):
    finished_signal = Signal(bool, str, dict)

    def __init__(self, db):
        super().__init__()
        self.db = db

    def run(self):
        try:
            from core.license_manager import validate_license
            is_valid, msg, info = validate_license(self.db, timeout_online=6)
            self.finished_signal.emit(is_valid, msg, info)
        except Exception:
            pass


DARK_THEME_QSS = """
QMainWindow, QWidget {
    background-color: #0b0f19;
    color: #cbd5e1;
    font-family: 'Segoe UI', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Arial', sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #1e293b;
    background-color: #111827;
    border-radius: 10px;
}
QTabBar::tab {
    background-color: #0d1323;
    color: #94a3b8;
    padding: 8px 16px;
    font-weight: bold;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid #1e293b;
    margin-right: 4px;
}
QTabBar::tab:selected {
    background-color: #111827;
    color: #f8fafc;
    border-bottom: 2px solid #2563eb;
}
QGroupBox {
    background-color: #111827;
    border: 1px solid #1e293b;
    border-radius: 10px;
    margin-top: 10px;
    padding-top: 15px;
    font-weight: bold;
    color: #f8fafc;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #f8fafc;
    font-weight: bold;
}
QPushButton {
    background-color: #1e293b;
    color: #cbd5e1;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #334155;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #0f172a;
}
QLineEdit, QTextEdit, QComboBox, QSpinBox {
    background-color: #0b0f19;
    color: #f8fafc;
    border: 1px solid #1e293b;
    border-radius: 6px;
    padding: 6px 10px;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #2563eb;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #111827;
    color: #f8fafc;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
    border: 1px solid #1e293b;
}
QTableWidget {
    background-color: #0b0f19;
    gridline-color: #1e293b;
    border: 1px solid #1e293b;
    border-radius: 8px;
    color: #cbd5e1;
}
QHeaderView::section {
    background-color: #0f172a;
    color: #64748b;
    padding: 8px 10px;
    font-weight: bold;
    font-size: 11px;
    border: none;
    border-bottom: 1px solid #1e293b;
}
QScrollBar:vertical {
    background: #0b0f19;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #1e293b;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #334155;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: #0b0f19;
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #1e293b;
    min-width: 20px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: #334155;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QCheckBox {
    color: #cbd5e1;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #334155;
    background-color: #0b0f19;
}
QCheckBox::indicator:checked {
    background-color: #2563eb;
    border: 1px solid #3b82f6;
}
QRadioButton {
    color: #cbd5e1;
    spacing: 6px;
}
QRadioButton::indicator {
    width: 15px;
    height: 15px;
    border-radius: 8px;
    border: 2px solid #475569;
    background-color: #0b0f19;
}
QRadioButton::indicator:checked {
    border: 4px solid #3b82f6;
    background-color: #ffffff;
}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        # Không lưu trữ lịch sử nhật ký/bài đăng: dọn dẹp sạch CSDL khi khởi động ứng dụng
        self.db.clear_logs()
        self.db.clear_threads_logs()
        self.setWindowTitle("Threads Mass Post & FB Auto-Poster — Phần Mềm Tự Động Đăng Bài & Tương Tác Đa Luồng")
        self.resize(1360, 820)
        self.setMinimumSize(1120, 680)
        self.setStyleSheet(DARK_THEME_QSS)

        from core.database import get_asset_path
        icon_path = get_asset_path("icon.ico")
        if not os.path.exists(icon_path):
            icon_path = get_asset_path("icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.current_platform = "fb"
        self.nav_buttons = {}
        self.init_ui()
        self.init_floating_and_tray()

    def init_ui(self):
        central_widget = QWidget()
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # =========================================================================
        # 1. THANH HEADER TRÊN CÙNG (THEO PHONG CÁCH ẢNH 2 - MODERN SAAS DASHBOARD)
        # =========================================================================
        header_bar = QFrame()
        header_bar.setFixedHeight(62)
        header_bar.setStyleSheet("""
            QFrame {
                background-color: #0d1323;
                border-bottom: 1px solid #1e293b;
            }
        """)
        h_layout = QHBoxLayout(header_bar)
        h_layout.setContentsMargins(18, 8, 18, 8)
        h_layout.setSpacing(12)

        # Logo Badge ⚡
        lbl_logo_badge = QLabel("⚡")
        lbl_logo_badge.setFixedSize(36, 36)
        lbl_logo_badge.setAlignment(Qt.AlignCenter)
        lbl_logo_badge.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3b82f6, stop:1 #4f46e5);
                color: #ffffff;
                font-size: 17px;
                font-weight: bold;
                border-radius: 9px;
                border: none;
            }
        """)
        h_layout.addWidget(lbl_logo_badge)

        # Brand Title & Subtitle
        brand_col = QVBoxLayout()
        brand_col.setContentsMargins(0, 0, 0, 0)
        brand_col.setSpacing(1)
        lbl_brand_title = QLabel("Threads Mass Post & FB Auto-Poster")
        lbl_brand_title.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: bold; border: none; background: transparent;")
        lbl_brand_sub = QLabel("Phần Mềm Tự Động Đăng Bài & Tương Tác Đa Luồng")
        lbl_brand_sub.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        brand_col.addWidget(lbl_brand_title)
        brand_col.addWidget(lbl_brand_sub)
        h_layout.addLayout(brand_col)

        h_layout.addSpacing(14)

        # Platform Switcher Pills
        self.btn_platform_fb = QPushButton("📘  Nền Tảng Facebook")
        self.btn_platform_fb.setCursor(Qt.PointingHandCursor)
        self.btn_platform_fb.setFixedHeight(36)
        self.btn_platform_fb.clicked.connect(lambda: self.switch_platform("fb"))

        self.btn_platform_threads = QPushButton("🧵  Nền Tảng Threads")
        self.btn_platform_threads.setCursor(Qt.PointingHandCursor)
        self.btn_platform_threads.setFixedHeight(36)
        self.btn_platform_threads.clicked.connect(lambda: self.switch_platform("threads"))

        h_layout.addWidget(self.btn_platform_fb)
        h_layout.addWidget(self.btn_platform_threads)

        # Vách ngăn mỏng
        v_sep = QFrame()
        v_sep.setFrameShape(QFrame.VLine)
        v_sep.setFixedHeight(24)
        v_sep.setStyleSheet("background-color: #1e293b; border: none; max-width: 1px;")
        h_layout.addWidget(v_sep)

        # Step / Sub-View Pills nằm gọn ngay trên thanh Header để chuyển nhanh giữa Dashboard và Quản lý TK/Nhóm
        self.step_stack = QStackedWidget()
        self.step_stack.setStyleSheet("background: transparent; border: none;")

        # Step Bar: Facebook
        step_fb_widget = QWidget()
        step_fb_widget.setStyleSheet("background: transparent; border: none;")
        s_fb_layout = QHBoxLayout(step_fb_widget)
        s_fb_layout.setContentsMargins(0, 0, 0, 0)
        s_fb_layout.setSpacing(6)

        self.btn_step_fb4 = QPushButton("🚀 Bảng Điều Khiển")
        self.btn_step_fb1 = QPushButton("👤 Tài Khoản FB")
        self.btn_step_fb2 = QPushButton("👥 Quản Lý Nhóm")
        self.btn_step_fb3 = QPushButton("📄 Kho Mẫu Excel")

        # Giữ đúng thứ tự index của self.fb_tabs: 0=Account, 1=Group, 2=Content, 3=Poster
        self.fb_step_buttons = [self.btn_step_fb1, self.btn_step_fb2, self.btn_step_fb3, self.btn_step_fb4]
        for idx, b in [(3, self.btn_step_fb4), (0, self.btn_step_fb1), (1, self.btn_step_fb2), (2, self.btn_step_fb3)]:
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(32)
            b.clicked.connect(lambda _, i=idx: self.fb_tabs.setCurrentIndex(i))
            s_fb_layout.addWidget(b)
        self.step_stack.addWidget(step_fb_widget)

        # Step Bar: Threads
        step_th_widget = QWidget()
        step_th_widget.setStyleSheet("background: transparent; border: none;")
        s_th_layout = QHBoxLayout(step_th_widget)
        s_th_layout.setContentsMargins(0, 0, 0, 0)
        s_th_layout.setSpacing(6)

        self.btn_step_th2 = QPushButton("🚀 Bảng Điều Khiển Threads")
        self.btn_step_th1 = QPushButton("👤 Tài Khoản Threads")

        self.th_step_buttons = [self.btn_step_th1, self.btn_step_th2]
        for idx, b in [(1, self.btn_step_th2), (0, self.btn_step_th1)]:
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(32)
            b.clicked.connect(lambda _, i=idx: self.threads_tabs.setCurrentIndex(i))
            s_th_layout.addWidget(b)
        self.step_stack.addWidget(step_th_widget)

        h_layout.addWidget(self.step_stack)
        h_layout.addStretch()

        # Nút Mini Widget & Ẩn Khay gọn trên Header
        btn_floating = QPushButton("🪟 Mini")
        btn_floating.setCursor(Qt.PointingHandCursor)
        btn_floating.setToolTip("Mở cửa sổ nổi điều khiển nhanh")
        btn_floating.setFixedHeight(30)
        btn_floating.setStyleSheet("""
            QPushButton {
                background-color: #111827;
                color: #94a3b8;
                border: 1px solid #1e293b;
                border-radius: 15px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #1e293b;
                color: #f8fafc;
            }
        """)
        btn_floating.clicked.connect(self.toggle_floating_widget)
        h_layout.addWidget(btn_floating)

        self.btn_license_card = QPushButton("🟢 Bản Quyền")
        self.btn_license_card.setCursor(Qt.PointingHandCursor)
        self.btn_license_card.setFixedHeight(30)
        self.btn_license_card.clicked.connect(self.open_license_dialog)
        self.btn_license_card.setStyleSheet("""
            QPushButton {
                background-color: #111827;
                color: #cbd5e1;
                border: 1px solid #1e293b;
                border-radius: 15px;
                padding: 4px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                border: 1px solid #2563eb;
                color: #ffffff;
            }
        """)
        h_layout.addWidget(self.btn_license_card)

        # Status Badge: "● Sẵn sàng hoạt động" (Giống hệt Ảnh 2)
        self.lbl_status_quick = QLabel("●  Sẵn sàng hoạt động")
        self.lbl_status_quick.setFixedHeight(30)
        self.lbl_status_quick.setStyleSheet("""
            QLabel {
                background-color: #052e16;
                color: #10b981;
                border: 1px solid #065f46;
                border-radius: 15px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        h_layout.addWidget(self.lbl_status_quick)

        # User Badge: "👤 Xin chào, Người dùng" (Giống hệt Ảnh 2)
        self.lbl_user_badge = QLabel("👤  Xin chào, Người dùng")
        self.lbl_user_badge.setFixedHeight(30)
        self.lbl_user_badge.setStyleSheet("""
            QLabel {
                background-color: #111827;
                color: #cbd5e1;
                border: 1px solid #1e293b;
                border-radius: 15px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 500;
            }
        """)
        h_layout.addWidget(self.lbl_user_badge)

        root_layout.addWidget(header_bar)

        # =========================================================================
        # 2. VÙNG NỘI DUNG CHÍNH (FULL-WIDTH DASHBOARD)
        # =========================================================================
        body_container = QWidget()
        body_layout = QVBoxLayout(body_container)
        body_layout.setContentsMargins(16, 12, 16, 12)
        body_layout.setSpacing(0)

        self.platform_stack = QStackedWidget()

        # --- GIAO DIỆN FACEBOOK ---
        self.fb_tabs = QTabWidget()
        self.fb_tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")
        self.account_tab = AccountTab(self.db)
        self.group_tab = GroupTab(self.db)
        self.content_tab = ContentTab(self.db)
        self.poster_tab = PosterTab(self.db)
        self.tabs = self.fb_tabs

        self.fb_tabs.addTab(self.account_tab, "Tài Khoản FB")
        self.fb_tabs.addTab(self.group_tab, "Nhóm FB")
        self.fb_tabs.addTab(self.content_tab, "Mẫu Nội Dung")
        self.fb_tabs.addTab(self.poster_tab, "Đăng Bài FB")
        self.fb_tabs.tabBar().setVisible(False)
        self.fb_tabs.currentChanged.connect(self.on_fb_tab_changed)

        self.platform_stack.addWidget(self.fb_tabs)

        # --- GIAO DIỆN THREADS ---
        self.threads_tabs = QTabWidget()
        self.threads_tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")
        self.threads_account_tab = ThreadsAccountTab(self.db)
        self.threads_poster_tab = ThreadsPosterTab(self.db)

        self.threads_account_tab.account_changed.connect(self.threads_poster_tab.load_accounts)
        self.content_tab.excel_changed.connect(lambda _: self.poster_tab.load_all_config())
        self.content_tab.excel_changed.connect(lambda _: self.threads_poster_tab.load_campaign_templates())

        self.threads_tabs.addTab(self.threads_account_tab, "Cấu Hình Tài Khoản")
        self.threads_tabs.addTab(self.threads_poster_tab, "Đăng Bài Threads")
        self.threads_tabs.tabBar().setVisible(False)
        self.threads_tabs.currentChanged.connect(self.on_threads_tab_changed)

        self.platform_stack.addWidget(self.threads_tabs)

        body_layout.addWidget(self.platform_stack, 1)
        root_layout.addWidget(body_container, 1)

        self.setCentralWidget(central_widget)

        # Mặc định mở Bảng Điều Khiển Facebook (giống Ảnh 2)
        self.switch_platform("fb")
        self.fb_tabs.setCurrentIndex(3)
        if len(self.db.get_threads_accounts()) > 0:
            self.threads_tabs.setCurrentIndex(1)
        else:
            self.threads_tabs.setCurrentIndex(0)

        self.update_license_display()

        self.license_timer = QTimer(self)
        self.license_timer.setInterval(60000)
        self.license_timer.timeout.connect(self.periodic_license_check)
        self.license_timer.start()

    def set_active_nav(self, active_key: str):
        pass

    def on_nav_home(self):
        if self.current_platform == "threads":
            self.threads_tabs.setCurrentIndex(1)
        else:
            self.fb_tabs.setCurrentIndex(3)

    def on_nav_post(self):
        self.on_nav_home()

    def on_nav_acc(self):
        if self.current_platform == "threads":
            self.threads_tabs.setCurrentIndex(0)
        else:
            self.fb_tabs.setCurrentIndex(0)

    def on_nav_settings(self):
        self.open_license_dialog()

    def on_nav_logs(self):
        self.on_nav_home()

    def on_nav_support(self):
        QMessageBox.information(
            self,
            "Hỗ Trợ Kỹ Thuật",
            "🎧 HỖ TRỢ KỸ THUẬT & BẢN QUYỀN\n\n"
            "• Phần mềm: Threads Mass Post & FB Auto-Poster\n"
            "• Phiên bản: 2.2.0 (Cloud License)\n"
            "• Tình trạng mạng: Trực tuyến\n"
            "• Mọi thắc mắc kỹ thuật vui lòng liên hệ Admin hệ thống."
        )

    def on_notification_clicked(self):
        pass

    def switch_platform(self, platform: str):
        self.current_platform = platform
        active_platform_css = """
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid #3b82f6;
                border-radius: 7px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """
        inactive_platform_css = """
            QPushButton {
                background-color: #111827;
                color: #94a3b8;
                font-size: 12px;
                font-weight: 500;
                border: 1px solid #1e293b;
                border-radius: 7px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background-color: #1e293b;
                color: #f8fafc;
            }
        """
        if platform == "fb":
            self.platform_stack.setCurrentIndex(0)
            self.step_stack.setCurrentIndex(0)
            self.btn_platform_fb.setStyleSheet(active_platform_css)
            self.btn_platform_threads.setStyleSheet(inactive_platform_css)
            self.update_fb_step_styles(self.fb_tabs.currentIndex())
        else:
            self.platform_stack.setCurrentIndex(1)
            self.step_stack.setCurrentIndex(1)
            self.btn_platform_threads.setStyleSheet(active_platform_css)
            self.btn_platform_fb.setStyleSheet(inactive_platform_css)
            self.threads_poster_tab.load_accounts()
            self.threads_poster_tab.load_campaigns()
            self.update_threads_step_styles(self.threads_tabs.currentIndex())

    def _step_button_styles(self):
        active_css = """
            QPushButton {
                background-color: #1e293b;
                color: #60a5fa;
                font-weight: bold;
                font-size: 11px;
                border-radius: 6px;
                border: 1px solid #2563eb;
                padding: 4px 10px;
            }
        """
        inactive_css = """
            QPushButton {
                background-color: transparent;
                color: #64748b;
                font-weight: 500;
                font-size: 11px;
                border-radius: 6px;
                border: 1px solid transparent;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #111827;
                color: #cbd5e1;
            }
        """
        return active_css, inactive_css

    def update_threads_step_styles(self, active_idx: int):
        active_css, inactive_css = self._step_button_styles()
        for i, btn in enumerate(self.th_step_buttons):
            btn.setStyleSheet(active_css if i == active_idx else inactive_css)

    def update_fb_step_styles(self, active_idx: int):
        active_css, inactive_css = self._step_button_styles()
        for i, btn in enumerate(self.fb_step_buttons):
            btn.setStyleSheet(active_css if i == active_idx else inactive_css)

    def on_fb_tab_changed(self, index: int):
        self.update_fb_step_styles(index)
        if index == 1:
            self.group_tab.load_accounts_combo()
        elif index == 2:
            self.content_tab.load_campaigns()
        elif index == 3:
            self.poster_tab.load_combos()

    def on_threads_tab_changed(self, index: int):
        self.update_threads_step_styles(index)
        if index == 1:
            self.threads_poster_tab.load_accounts()
            self.threads_poster_tab.load_campaigns()

    def on_tab_changed(self, index: int):
        self.on_fb_tab_changed(index)

    def periodic_license_check(self):
        if hasattr(self, 'license_check_worker') and self.license_check_worker.isRunning():
            return
        self.license_check_worker = PeriodicLicenseCheckWorker(self.db)
        self.license_check_worker.finished_signal.connect(self.on_periodic_license_result)
        self.license_check_worker.start()

    def on_periodic_license_result(self, is_valid: bool, msg: str, info: dict):
        if not is_valid:
            if "kết nối" in msg.lower() or "timeout" in msg.lower() or "mạng" in msg.lower() or "http" in msg.lower():
                return
            self.license_timer.stop()
            QMessageBox.critical(
                self,
                "Bản Quyền Bị Khóa",
                f"⚠️ {msg}\nPhần mềm sẽ tự động đóng lại."
            )
            QApplication.quit()
        else:
            self.update_license_display()

    def update_license_display(self):
        from core.license_manager import get_cached_license, parse_expiry_date, get_machine_id
        cached = get_cached_license(self.db)
        if cached and cached.get("machine_id") == get_machine_id(self.db):
            if cached.get("status") in ("BLOCKED", "KHÓA", "TẠM KHÓA", "REVOKED"):
                self.btn_license_card.setText("🚫 Bản Quyền Khóa")
                return

            if cached.get("status") == "EXPIRED":
                self.btn_license_card.setText("🔴 Hết Hạn")
                return

            dt, is_valid, msg = parse_expiry_date(cached.get("expiry_raw", ""))
            if not is_valid and cached.get("expiry_display"):
                dt, is_valid, msg = parse_expiry_date(cached.get("expiry_display", ""))

            if is_valid:
                short_msg = msg.split("(")[0].strip() if "(" in msg else msg
                self.btn_license_card.setText(f"🟢 {short_msg}")
                return
            else:
                self.btn_license_card.setText("🔴 Hết Hạn")
                return

        self.btn_license_card.setText("⚠️ Bản Quyền")

    def open_license_dialog(self):
        from ui.license_dialog import LicenseDialog
        dlg = LicenseDialog(self.db, is_blocking=False, parent=self)
        dlg.exec()
        self.update_license_display()

    def _on_status_message(self, msg: str):
        short = msg if len(msg) <= 36 else msg[:34] + "..."
        self.lbl_status_quick.setText(f"●  {short}")

    def init_floating_and_tray(self):
        self.floating_widget = FloatingWidget()
        self.floating_widget.show_main_signal.connect(self.show_main_from_tray)
        self.floating_widget.pause_signal.connect(self.poster_tab.on_toggle_pause)
        self.floating_widget.stop_signal.connect(self.poster_tab.on_stop)

        self.tray_manager = SystemTrayManager(self)
        self.tray_manager.show_main_signal.connect(self.show_main_from_tray)
        self.tray_manager.toggle_floating_signal.connect(self.toggle_floating_widget)
        self.tray_manager.toggle_pause_signal.connect(self.poster_tab.on_toggle_pause)
        self.tray_manager.exit_app_signal.connect(self.force_exit_app)
        self.tray_manager.show()

        self.poster_tab.status_updated.connect(self.floating_widget.update_status)
        self.poster_tab.status_updated.connect(self._on_status_message)
        self.threads_poster_tab.status_updated.connect(self.floating_widget.update_status)
        self.threads_poster_tab.status_updated.connect(self._on_status_message)

    def toggle_floating_widget(self):
        if self.floating_widget.isVisible():
            self.floating_widget.hide()
        else:
            self.floating_widget.show()

    def hide_to_tray(self):
        self.hide()
        self.floating_widget.show()
        self.tray_manager.send_notification("Auto-Poster", "Ứng dụng đang chạy ngầm trên Khay hệ thống!")

    def show_main_from_tray(self):
        self.showNormal()
        self.activateWindow()

    def force_exit_app(self):
        QApplication.quit()

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self,
            "Xác Nhận Đóng",
            "Bạn muốn thu nhỏ ứng dụng xuống Khay hệ thống (Chạy ngầm) hay Thoát hẳn?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            event.ignore()
            self.hide_to_tray()
        elif reply == QMessageBox.No:
            event.accept()
            QApplication.quit()
        else:
            event.ignore()
