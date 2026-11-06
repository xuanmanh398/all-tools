import os
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QMessageBox, QApplication,
    QPushButton, QHBoxLayout, QLabel, QStackedWidget, QFrame, QScrollArea
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
from ui.home_dashboard import HomeDashboardTab
from ui.fb_comment_tab import FBCommentTab

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
    background-color: #111625;
    border-radius: 8px;
}
QTabBar::tab {
    background-color: #0d121f;
    color: #94a3b8;
    padding: 8px 16px;
    font-weight: bold;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid #1e293b;
    margin-right: 4px;
}
QTabBar::tab:selected {
    background-color: #111625;
    color: #f8fafc;
    border-bottom: 2px solid #6366f1;
}
QGroupBox {
    background-color: #111625;
    border: 1px solid #1e293b;
    border-radius: 8px;
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
    padding: 6px 8px;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #6366f1;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #111625;
    color: #f8fafc;
    selection-background-color: #6366f1;
    selection-color: #ffffff;
    border: 1px solid #1e293b;
}
QTableWidget {
    background-color: #0b0f19;
    gridline-color: #1e293b;
    border: 1px solid #1e293b;
    border-radius: 6px;
    color: #cbd5e1;
}
QHeaderView::section {
    background-color: #111625;
    color: #94a3b8;
    padding: 7px;
    font-weight: bold;
    border: none;
    border-bottom: 1px solid #1e293b;
    border-right: 1px solid #1e293b;
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
QRadioButton {
    color: #cbd5e1;
    spacing: 6px;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1px solid #334155;
    background-color: #0b0f19;
}
QRadioButton::indicator:checked {
    border: 2px solid #6366f1;
    background-color: #6366f1;
}
"""

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        # Không lưu trữ lịch sử nhật ký/bài đăng: dọn dẹp sạch CSDL khi khởi động ứng dụng
        self.db.clear_logs()
        self.db.clear_threads_logs()
        self.setWindowTitle("Tools Marketing - Phần Mềm Marketing Tự Động Facebook & Threads")
        self.resize(1200, 800)
        self.setMinimumSize(1024, 640)
        self.setStyleSheet(DARK_THEME_QSS)

        # Cài đặt icon cho cửa sổ chính và taskbar
        from core.database import get_asset_path
        icon_path = get_asset_path("icon.ico")
        if not os.path.exists(icon_path):
            icon_path = get_asset_path("icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.current_platform = "fb"
        self.init_ui()
        self.init_floating_and_tray()

    def init_ui(self):
        central_widget = QWidget()
        main_h_layout = QHBoxLayout(central_widget)
        main_h_layout.setContentsMargins(0, 0, 0, 0)
        main_h_layout.setSpacing(0)

        # ==========================================
        # 1. THANH SIDEBAR TRÁI (LEFT NAVIGATION)
        # ==========================================
        sidebar = QWidget()
        sidebar.setFixedWidth(230)
        sidebar.setStyleSheet("""
            QWidget {
                background-color: #0d121f;
                border-right: 1px solid #1e293b;
            }
        """)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 16, 12, 14)
        sb_layout.setSpacing(6)

        # Logo & Brand Header
        lbl_brand_icon = QLabel("⚡ Tools Marketing")
        lbl_brand_icon.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: bold; border: none;")
        sb_layout.addWidget(lbl_brand_icon)

        lbl_brand_sub = QLabel("Facebook & Threads Marketing")
        lbl_brand_sub.setWordWrap(True)
        lbl_brand_sub.setStyleSheet("color: #64748b; font-size: 11px; line-height: 1.2; border: none; margin-bottom: 4px;")
        sb_layout.addWidget(lbl_brand_sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #1e293b; background-color: #1e293b; max-height: 1px; border: none;")
        sb_layout.addWidget(sep)
        sb_layout.addSpacing(4)

        # Scroll area for navigation buttons so it never overflows on small screens
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
        """)

        nav_container = QWidget()
        nav_container.setStyleSheet("background: transparent;")
        nav_vbox = QVBoxLayout(nav_container)
        nav_vbox.setContentsMargins(0, 0, 0, 0)
        nav_vbox.setSpacing(3)

        self.nav_buttons = {}

        nav_sections = [
            ("TỔNG QUAN", [
                ("home", "🏠  Trang chủ", self.on_nav_home)
            ]),
            ("FACEBOOK MARKETING", [
                ("fb_comment", "💬  Auto Comment FB", self.on_nav_fb_comment),
                ("fb_post", "🚀  Đăng bài Nhóm FB", self.on_nav_fb_post),
                ("fb_acc", "👥  Tài khoản Facebook", self.on_nav_fb_acc),
                ("fb_group", "📑  Quản lý Nhóm FB", self.on_nav_fb_group),
                ("fb_content", "📝  Mẫu nội dung FB", self.on_nav_fb_content),
            ]),
            ("THREADS MARKETING", [
                ("threads_acc", "👥  Tài khoản Threads", self.on_nav_threads_acc),
                ("threads_post", "🚀  Đăng bài & Cmt Threads", self.on_nav_threads_post),
            ]),
            ("HỆ THỐNG", [
                ("logs", "🕒  Nhật ký hoạt động", self.on_nav_logs),
                ("settings", "⚙️  Cài đặt bản quyền", self.on_nav_settings),
                ("support", "🎧  Hỗ trợ kỹ thuật", self.on_nav_support),
            ]),
        ]

        def make_section_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("""
                QLabel {
                    color: #64748b;
                    font-size: 10px;
                    font-weight: 700;
                    letter-spacing: 0.8px;
                    padding-left: 6px;
                    margin-top: 8px;
                    margin-bottom: 2px;
                    border: none;
                    background: transparent;
                }
            """)
            return lbl

        for section_title, items in nav_sections:
            nav_vbox.addWidget(make_section_label(section_title))
            for key, label, handler in items:
                btn = QPushButton(label)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setFixedHeight(34)
                btn.clicked.connect(handler)
                nav_vbox.addWidget(btn)
                self.nav_buttons[key] = btn

        nav_vbox.addStretch()
        scroll_area.setWidget(nav_container)
        sb_layout.addWidget(scroll_area, 1)

        # License status card at bottom of sidebar
        self.btn_license_card = QPushButton()
        self.btn_license_card.setCursor(Qt.PointingHandCursor)
        self.btn_license_card.clicked.connect(self.open_license_dialog)
        self.btn_license_card.setStyleSheet("""
            QPushButton {
                background-color: #111625;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 10px;
                text-align: left;
            }
            QPushButton:hover {
                border: 1px solid #6366f1;
                background-color: #161e31;
            }
        """)
        sb_layout.addWidget(self.btn_license_card)

        main_h_layout.addWidget(sidebar)

        # ==========================================
        # 2. KHU VỰC NỘI DUNG CHÍNH (RIGHT CONTAINER)
        # ==========================================
        right_container = QWidget()
        rc_layout = QVBoxLayout(right_container)
        rc_layout.setContentsMargins(16, 12, 16, 12)
        rc_layout.setSpacing(10)

        # 2.1 Thanh Header Trên Cùng: Platform Switcher & User Profile
        top_header_layout = QHBoxLayout()
        top_header_layout.setSpacing(10)

        # Platform Switcher Buttons
        self.btn_platform_fb = QPushButton("📘 FACEBOOK MARKETING")
        self.btn_platform_fb.setCursor(Qt.PointingHandCursor)
        self.btn_platform_fb.setFixedHeight(36)
        self.btn_platform_fb.clicked.connect(lambda: self.switch_platform("fb"))

        self.btn_platform_threads = QPushButton("📷 THREADS MARKETING")
        self.btn_platform_threads.setCursor(Qt.PointingHandCursor)
        self.btn_platform_threads.setFixedHeight(36)
        self.btn_platform_threads.clicked.connect(lambda: self.switch_platform("threads"))

        top_header_layout.addWidget(self.btn_platform_fb)
        top_header_layout.addWidget(self.btn_platform_threads)
        top_header_layout.addStretch()

        # Notification Bell & User Greeting Badge
        btn_notif = QPushButton("🔔")
        btn_notif.setCursor(Qt.PointingHandCursor)
        btn_notif.setFixedSize(36, 36)
        btn_notif.setStyleSheet("""
            QPushButton {
                background-color: #111625;
                color: #cbd5e1;
                border: 1px solid #1e293b;
                border-radius: 18px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #1e293b;
                color: #ffffff;
            }
        """)
        btn_notif.clicked.connect(self.on_notification_clicked)
        top_header_layout.addWidget(btn_notif)

        self.lbl_user_badge = QLabel("👤 Xin chào, Người dùng")
        self.lbl_user_badge.setStyleSheet("""
            QLabel {
                background-color: #111625;
                color: #cbd5e1;
                border: 1px solid #1e293b;
                border-radius: 18px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 500;
            }
        """)
        top_header_layout.addWidget(self.lbl_user_badge)
        rc_layout.addLayout(top_header_layout)

        # 2.2 Stacked Widget chứa Tab Facebook và Threads (Trực tiếp, không thanh phụ)
        self.platform_stack = QStackedWidget()

        # --- GIAO DIỆN FACEBOOK ---
        self.fb_tabs = QTabWidget()
        self.home_tab = HomeDashboardTab(self.db)
        self.comment_tab = FBCommentTab(self.db)
        self.poster_tab = PosterTab(self.db)
        self.account_tab = AccountTab(self.db)
        self.group_tab = GroupTab(self.db)
        self.content_tab = ContentTab(self.db)
        self.tabs = self.fb_tabs  # Giữ alias cho tương thích ngược nếu cần

        self.fb_tabs.addTab(self.home_tab, "Trang Chủ")
        self.fb_tabs.addTab(self.comment_tab, "Auto Comment FB")
        self.fb_tabs.addTab(self.poster_tab, "Đăng Bài FB")
        self.fb_tabs.addTab(self.account_tab, "Tài Khoản FB")
        self.fb_tabs.addTab(self.group_tab, "Nhóm FB")
        self.fb_tabs.addTab(self.content_tab, "Mẫu Nội Dung")
        self.fb_tabs.tabBar().setVisible(False)  # Ẩn tab mặc định
        self.fb_tabs.currentChanged.connect(self.on_fb_tab_changed)

        # Đồng bộ tài khoản sang tab comment, poster và home dashboard
        self.account_tab.account_changed.connect(self.comment_tab.load_accounts)
        self.account_tab.account_changed.connect(self.home_tab.refresh_stats)
        self.home_tab.switch_tab_signal.connect(self.handle_home_switch)

        self.platform_stack.addWidget(self.fb_tabs)

        # --- GIAO DIỆN THREADS ---
        self.threads_tabs = QTabWidget()
        self.threads_account_tab = ThreadsAccountTab(self.db)
        self.threads_poster_tab = ThreadsPosterTab(self.db)

        # Đồng bộ tài khoản sang tab poster khi có thêm/xóa/đổi
        self.threads_account_tab.account_changed.connect(self.threads_poster_tab.load_accounts)

        self.threads_tabs.addTab(self.threads_account_tab, "Cấu Hình Tài Khoản")
        self.threads_tabs.addTab(self.threads_poster_tab, "Đăng Bài Threads")
        self.threads_tabs.tabBar().setVisible(False)  # Ẩn tab mặc định
        self.threads_tabs.currentChanged.connect(self.on_threads_tab_changed)

        self.platform_stack.addWidget(self.threads_tabs)

        rc_layout.addWidget(self.platform_stack, 1)

        # 2.3 Bottom Action Controls (Mini Float & Tray Buttons)
        bottom_bar = QHBoxLayout()
        self.lbl_status_quick = QLabel("Trạng thái: Sẵn sàng hoạt động")
        self.lbl_status_quick.setStyleSheet("color: #64748b; font-size: 11px;")
        bottom_bar.addWidget(self.lbl_status_quick)

        bottom_bar.addStretch()

        btn_floating = QPushButton("🚀 Cửa Sổ Nổi Mini")
        btn_floating.setCursor(Qt.PointingHandCursor)
        btn_floating.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #8b5cf6);
                color: #ffffff;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #7c3aed);
            }
        """)
        btn_floating.clicked.connect(self.toggle_floating_widget)
        bottom_bar.addWidget(btn_floating)

        btn_hide_tray = QPushButton("📥 Thu Nhỏ Khay Hệ Thống")
        btn_hide_tray.setCursor(Qt.PointingHandCursor)
        btn_hide_tray.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)
        btn_hide_tray.clicked.connect(self.hide_to_tray)
        bottom_bar.addWidget(btn_hide_tray)

        rc_layout.addLayout(bottom_bar)
        main_h_layout.addWidget(right_container, 1)

        self.setCentralWidget(central_widget)

        # Khởi tạo mặc định: Nền tảng Facebook (Trang chủ)
        self.switch_platform("fb", switch_tab=False)
        self.fb_tabs.setCurrentIndex(0)
        self.set_active_nav("home")
        self.update_license_display()

        # Định kỳ tự động kiểm tra trạng thái bản quyền trực tuyến mỗi 60 giây
        self.license_timer = QTimer(self)
        self.license_timer.setInterval(60000)
        self.license_timer.timeout.connect(self.periodic_license_check)
        self.license_timer.start()

    def set_active_nav(self, active_key: str):
        active_style = """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #6366f1);
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                text-align: left;
                padding-left: 12px;
                border: none;
                font-size: 12.5px;
            }
        """
        inactive_style = """
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                font-weight: 500;
                border-radius: 6px;
                text-align: left;
                padding-left: 12px;
                border: none;
                font-size: 12.5px;
            }
            QPushButton:hover {
                background-color: #1e293b;
                color: #f8fafc;
            }
        """
        for k, btn in self.nav_buttons.items():
            btn.setStyleSheet(active_style if k == active_key else inactive_style)

    def handle_home_switch(self, target: str):
        if target == "fb_comment":
            self.on_nav_fb_comment()
        elif target == "fb_poster":
            self.on_nav_fb_post()
        elif target == "fb_acc":
            self.on_nav_fb_acc()
        elif target == "fb_group":
            self.on_nav_fb_group()
        elif target == "threads":
            self.on_nav_threads_post()

    def on_nav_home(self):
        self.switch_platform("fb", switch_tab=False)
        self.fb_tabs.setCurrentIndex(0)
        self.set_active_nav("home")
        self.home_tab.refresh_stats()

    def on_nav_fb_comment(self):
        self.switch_platform("fb", switch_tab=False)
        self.fb_tabs.setCurrentIndex(1)
        self.set_active_nav("fb_comment")
        self.comment_tab.load_accounts()
        self.comment_tab.load_groups()

    def on_nav_comment(self):
        self.on_nav_fb_comment()

    def on_nav_fb_post(self):
        self.switch_platform("fb", switch_tab=False)
        self.fb_tabs.setCurrentIndex(2)
        self.set_active_nav("fb_post")
        self.poster_tab.load_combos()

    def on_nav_post(self):
        self.on_nav_fb_post()

    def on_nav_fb_acc(self):
        self.switch_platform("fb", switch_tab=False)
        self.fb_tabs.setCurrentIndex(3)
        self.set_active_nav("fb_acc")
        self.account_tab.load_accounts()

    def on_nav_acc(self):
        self.on_nav_fb_acc()

    def on_nav_fb_group(self):
        self.switch_platform("fb", switch_tab=False)
        self.fb_tabs.setCurrentIndex(4)
        self.set_active_nav("fb_group")
        self.group_tab.load_accounts_combo()

    def on_nav_group(self):
        self.on_nav_fb_group()

    def on_nav_fb_content(self):
        self.switch_platform("fb", switch_tab=False)
        self.fb_tabs.setCurrentIndex(5)
        self.set_active_nav("fb_content")
        self.content_tab.load_campaigns()

    def on_nav_content(self):
        self.on_nav_fb_content()

    def on_nav_threads_acc(self):
        self.switch_platform("threads", switch_tab=False)
        self.threads_tabs.setCurrentIndex(0)
        self.set_active_nav("threads_acc")
        self.threads_account_tab.load_accounts()

    def on_nav_threads_post(self):
        self.switch_platform("threads", switch_tab=False)
        self.threads_tabs.setCurrentIndex(1)
        self.set_active_nav("threads_post")
        self.threads_poster_tab.load_accounts()
        self.threads_poster_tab.load_campaigns()

    def on_nav_threads(self):
        self.on_nav_threads_post()

    def on_nav_settings(self):
        self.set_active_nav("settings")
        self.open_license_dialog()

    def on_nav_logs(self):
        self.set_active_nav("logs")
        if self.current_platform == "threads":
            self.threads_tabs.setCurrentIndex(1)
            self.threads_poster_tab.result_tabs.setCurrentIndex(0)
        else:
            self.fb_tabs.setCurrentIndex(1)  # Tab comment

    def on_nav_support(self):
        self.set_active_nav("support")
        QMessageBox.information(
            self,
            "Hỗ Trợ Kỹ Thuật",
            "🎧 HỖ TRỢ KỸ THUẬT & BẢN QUYỀN\n\n"
            "• Phần mềm: Tools Marketing (Facebook & Threads)\n"
            "• Phiên bản: 3.0.0 (Tích hợp Auto Comment & Group Poster)\n"
            "• Tình trạng mạng: Trực tuyến\n"
            "• Mọi thắc mắc kỹ thuật vui lòng liên hệ Admin hệ thống."
        )

    def on_notification_clicked(self):
        QMessageBox.information(
            self,
            "Thông Báo Hệ Thống",
            "🔔 THÔNG BÁO HỆ THỐNG\n\n"
            "• Đã tối ưu hóa tính năng đăng bài và bình luận Threads tự động.\n"
            "• Phiên đăng nhập và CSDL được lưu an toàn tại AppData (không bị mất khi cài đặt bản mới).\n"
            "• Chúc bạn đạt hiệu quả cao với Threads Mass Post!"
        )

    def switch_platform(self, platform: str, switch_tab: bool = True):
        self.current_platform = platform
        if platform == "fb":
            self.platform_stack.setCurrentIndex(0)
            self.btn_platform_fb.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1877f2, stop:1 #0056b3);
                    color: #ffffff;
                    font-size: 12.5px;
                    font-weight: bold;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 16px;
                }
            """)
            self.btn_platform_threads.setStyleSheet("""
                QPushButton {
                    background-color: #111625;
                    color: #94a3b8;
                    font-size: 12.5px;
                    font-weight: 500;
                    border: 1px solid #1e293b;
                    border-radius: 6px;
                    padding: 6px 16px;
                }
                QPushButton:hover {
                    background-color: #1e293b;
                    color: #f8fafc;
                }
            """)
            if switch_tab:
                curr_idx = self.fb_tabs.currentIndex()
                tab_to_nav = {0: "home", 1: "fb_comment", 2: "fb_post", 3: "fb_acc", 4: "fb_group", 5: "fb_content"}
                if curr_idx in tab_to_nav:
                    self.set_active_nav(tab_to_nav[curr_idx])
        else:
            self.platform_stack.setCurrentIndex(1)
            self.btn_platform_threads.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d62976, stop:0.5 #962fbf, stop:1 #4f5bd5);
                    color: #ffffff;
                    font-size: 12.5px;
                    font-weight: bold;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 16px;
                }
            """)
            self.btn_platform_fb.setStyleSheet("""
                QPushButton {
                    background-color: #111625;
                    color: #94a3b8;
                    font-size: 12.5px;
                    font-weight: 500;
                    border: 1px solid #1e293b;
                    border-radius: 6px;
                    padding: 6px 16px;
                }
                QPushButton:hover {
                    background-color: #1e293b;
                    color: #f8fafc;
                }
            """)
            self.threads_poster_tab.load_accounts()
            self.threads_poster_tab.load_campaigns()
            if switch_tab:
                curr_idx = self.threads_tabs.currentIndex()
                if curr_idx == 0:
                    self.set_active_nav("threads_acc")
                else:
                    self.set_active_nav("threads_post")

    def on_fb_tab_changed(self, index: int):
        tab_to_nav = {
            0: "home",
            1: "fb_comment",
            2: "fb_post",
            3: "fb_acc",
            4: "fb_group",
            5: "fb_content",
        }
        if index in tab_to_nav:
            self.set_active_nav(tab_to_nav[index])

    def on_threads_tab_changed(self, index: int):
        tab_to_nav = {
            0: "threads_acc",
            1: "threads_post",
        }
        if index in tab_to_nav:
            self.set_active_nav(tab_to_nav[index])

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
                self.btn_license_card.setText("🚫 Bản Quyền Bị Khóa\nNhấn để gia hạn  >")
                return

            if cached.get("status") == "EXPIRED":
                self.btn_license_card.setText("🔴 Bản Quyền Đã Hết Hạn\nNhấn để gia hạn  >")
                return

            dt, is_valid, msg = parse_expiry_date(cached.get("expiry_raw", ""))
            if not is_valid and cached.get("expiry_display"):
                dt, is_valid, msg = parse_expiry_date(cached.get("expiry_display", ""))

            if is_valid:
                short_msg = msg.split("(")[0].strip() if "(" in msg else msg
                self.btn_license_card.setText(f"🟢 Bản Quyền\n{short_msg}  >")
                return
            else:
                self.btn_license_card.setText("🔴 Bản Quyền Hết Hạn\nNhấn để kích hoạt  >")
                return

        self.btn_license_card.setText("⚠️ Bản Quyền\nChưa kích hoạt  >")

    def open_license_dialog(self):
        from ui.license_dialog import LicenseDialog
        dlg = LicenseDialog(self.db, is_blocking=False, parent=self)
        dlg.exec()
        self.update_license_display()

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
        self.poster_tab.status_updated.connect(lambda msg: self.statusBar().showMessage(msg))
        self.threads_poster_tab.status_updated.connect(self.floating_widget.update_status)
        self.threads_poster_tab.status_updated.connect(lambda msg: self.statusBar().showMessage(msg))

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
