import asyncio
import time
import os
import webbrowser
from typing import List
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QTextEdit, QSpinBox, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QRadioButton, QButtonGroup,
    QProgressBar, QMessageBox, QFileDialog, QTabWidget, QSplitter
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from core.database import Database
from core.threads_automation import ThreadsAutomationEngine
from core.anti_spam import AntiSpamManager, AntiSpamConfig
from core.spintax_parser import SpintaxParser

class ThreadsActionWorker(QThread):
    log_signal = Signal(str, str, str, str, str)  # (time, action, target, status, message)
    progress_signal = Signal(int, int)  # (cur, total)
    finished_signal = Signal()

    def __init__(
        self,
        db: Database,
        account_uid: str,
        action_mode: str,  # "POST" hoặc "COMMENT"
        content_text: str,
        media_paths: list,
        target_urls: list,
        anti_config: AntiSpamConfig,
        headless: bool = True
    ):
        super().__init__()
        self.db = db
        self.account_uid = account_uid
        self.action_mode = action_mode
        self.content_text = content_text
        self.media_paths = media_paths or []
        self.target_urls = target_urls or []
        self.anti_config = anti_config
        self.headless = headless
        self.is_paused = False
        self.is_stopped = False

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def stop(self):
        self.is_stopped = True

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._process_actions())
            loop.close()
        except Exception as e:
            self.log_signal.emit(time.strftime("%H:%M:%S"), self.action_mode, "-", "FAILED", f"Lỗi tiến trình: {str(e)}")
        finally:
            self.finished_signal.emit()

    async def _process_actions(self):
        accounts = self.db.get_threads_accounts()
        acc = next((a for a in accounts if a["uid"] == self.account_uid), None)
        if not acc:
            self.log_signal.emit(time.strftime("%H:%M:%S"), self.action_mode, "-", "FAILED", "Không tìm thấy tài khoản Threads trong CSDL!")
            return

        engine = ThreadsAutomationEngine()
        cookie_str = acc.get("cookie", "")
        proxy = acc.get("proxy", "")

        anti_mgr = AntiSpamManager(self.anti_config)

        if self.action_mode == "POST":
            # 1. ĐĂNG BÀI MỚI LÊN THREADS
            self.progress_signal.emit(0, 1)
            self.log_signal.emit(time.strftime("%H:%M:%S"), "ĐĂNG BÀI", "Trang cá nhân Threads", "RUNNING", "Đang mở trình duyệt để đăng bài...")

            res = await engine.post_thread(
                cookie_str=cookie_str,
                text=self.content_text,
                media_paths=self.media_paths,
                proxy=proxy,
                headless=self.headless,
                uid=self.account_uid,
                progress_callback=lambda msg: self.log_signal.emit(time.strftime("%H:%M:%S"), "ĐĂNG BÀI", "Trang cá nhân", "RUNNING", msg)
            )

            status = "SUCCESS" if res.get("success") else "FAILED"
            msg = res.get("message", "")
            post_url = res.get("post_url", "")
            if status == "SUCCESS" and post_url and "/post/" in post_url:
                self.log_signal.emit(time.strftime("%H:%M:%S"), "ĐĂNG BÀI", post_url, "SUCCESS", msg)
            else:
                self.log_signal.emit(time.strftime("%H:%M:%S"), "ĐĂNG BÀI", "-", "FAILED", msg)
            self.progress_signal.emit(1, 1)

        else:
            # 2. ĐI BÌNH LUẬN VÀO CÁC BÀI VIẾT THREADS (CHẠY TRÊN 1 TRÌNH DUYỆT DUY NHẤT)
            await engine.run_commenting_session(
                cookie_str=cookie_str,
                target_urls=self.target_urls,
                comment_text=self.content_text,
                media_paths=self.media_paths,
                anti_config=self.anti_config,
                proxy=proxy,
                headless=self.headless,
                uid=self.account_uid,
                is_paused_fn=lambda: self.is_paused,
                is_stopped_fn=lambda: self.is_stopped,
                log_callback=lambda ts, act, tgt, st, msg: self.log_signal.emit(ts, act, tgt, st, msg),
                progress_callback=lambda cur, tot: self.progress_signal.emit(cur, tot),
                success_callback=None
            )


class ThreadsPosterTab(QWidget):
    status_updated = Signal(str)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.worker = None
        self.selected_media_paths = []
        self.init_ui()
        self.load_accounts()
        self.load_campaign_templates()
        # Không lưu và không nạp lịch sử cũ: bảng bắt đầu trống hoàn toàn
        self.db.clear_threads_logs()
        self.log_table.setRowCount(0)
        self.success_table.setRowCount(0)
        self.log_stack.setCurrentIndex(1)

    def load_campaigns(self):
        self.load_campaign_templates()

    def on_toggle_pause(self):
        self.on_pause()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Sử dụng QSplitter dọc để người dùng có thể tự do kéo giãn vùng soạn thảo nội dung lớn hơn
        main_splitter = QSplitter(Qt.Vertical)

        # === PHẦN TRÊN: CẤU HÌNH, NỘI DUNG & ĐIỀU KHIỂN ===
        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        # 1. Box Chọn Tài Khoản & Chế Độ Hành Động
        top_box = QGroupBox("1. Thiết Lập Tài Khoản, Chế Độ Đăng / Bình Luận Threads")
        t_layout = QVBoxLayout(top_box)
        t_layout.setContentsMargins(12, 10, 12, 10)

        row_acc = QHBoxLayout()
        row_acc.setSpacing(12)
        
        lbl_acc = QLabel("Chọn Tài Khoản Threads:")
        lbl_acc.setStyleSheet("font-weight: bold; color: #cbd5e1;")
        row_acc.addWidget(lbl_acc)
        
        self.combo_accounts = QComboBox()
        self.combo_accounts.setMinimumHeight(32)
        row_acc.addWidget(self.combo_accounts, stretch=1)

        btn_quick_login = QPushButton("➕ Đăng Nhập TK")
        btn_quick_login.setCursor(Qt.PointingHandCursor)
        btn_quick_login.setToolTip("Mở trình duyệt để đăng nhập tài khoản Threads mới")
        btn_quick_login.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #8b5cf6);
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #7c3aed);
            }
        """)
        btn_quick_login.clicked.connect(self.on_quick_login_clicked)
        row_acc.addWidget(btn_quick_login)

        row_acc.addSpacing(25)
        
        lbl_mode = QLabel("Chế Độ Thực Thi:")
        lbl_mode.setStyleSheet("font-weight: bold; color: #cbd5e1;")
        row_acc.addWidget(lbl_mode)
        
        self.rad_post = QRadioButton("Đăng Bài Mới Lên Threads")
        self.rad_comment = QRadioButton("Đi Bình Luận Vào Bài Viết")
        self.rad_post.setChecked(True)
        self.rad_post.setCursor(Qt.PointingHandCursor)
        self.rad_comment.setCursor(Qt.PointingHandCursor)

        mode_group = QButtonGroup(self)
        mode_group.addButton(self.rad_post)
        mode_group.addButton(self.rad_comment)
        self.rad_post.toggled.connect(self.on_mode_toggled)

        row_acc.addWidget(self.rad_post)
        row_acc.addWidget(self.rad_comment)
        t_layout.addLayout(row_acc)
        top_layout.addWidget(top_box)

        # 2. Box Nội Dung & Mẫu Bài Đăng / Danh Sách Bài Viết Mục Tiêu (VÙNG LỚN DỄ QUAN SÁT)
        content_box = QGroupBox("2. Cấu Hình Nội Dung Bài Viết, Mục Tiêu Threads")
        self.c_layout = QVBoxLayout(content_box)
        self.c_layout.setContentsMargins(12, 10, 12, 10)
        self.c_layout.setSpacing(8)

        # Hàng chọn mẫu nội dung có sẵn & nút spintax preview
        row_camp = QHBoxLayout()
        lbl_camp = QLabel("Chọn Mẫu Bài Viết Có Sẵn (Tùy chọn):")
        lbl_camp.setStyleSheet("color: #94a3b8;")
        row_camp.addWidget(lbl_camp)
        
        self.combo_campaigns = QComboBox()
        self.combo_campaigns.setMinimumHeight(28)
        self.combo_campaigns.currentIndexChanged.connect(self.on_campaign_selected)
        row_camp.addWidget(self.combo_campaigns, stretch=1)

        btn_insert_spintax = QPushButton("➕ Chèn {A|B|C}")
        btn_insert_spintax.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                padding: 4px 10px;
                font-size: 11px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)
        btn_insert_spintax.clicked.connect(self.on_insert_spintax)
        row_camp.addWidget(btn_insert_spintax)

        btn_spin_preview = QPushButton("👁️ Xem Biến Thể Spintax")
        btn_spin_preview.setStyleSheet("""
            QPushButton {
                background-color: #4f46e5;
                color: #ffffff;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4338ca;
            }
        """)
        btn_spin_preview.clicked.connect(self.on_preview_spintax)
        row_camp.addWidget(btn_spin_preview)

        self.lbl_char_count = QLabel("0 ký tự | 0 dòng")
        self.lbl_char_count.setStyleSheet("color: #64748b; font-size: 11px; padding-left: 5px;")
        row_camp.addWidget(self.lbl_char_count)

        self.c_layout.addLayout(row_camp)

        # Tiêu đề khung soạn thảo
        self.lbl_content_title = QLabel("📝 Nội Dung Bài Đăng Threads (Hỗ trợ Spintext {A|B|C}):")
        self.lbl_content_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #cbd5e1;")
        self.c_layout.addWidget(self.lbl_content_title)

        # Khung soạn thảo rộng rãi
        self.txt_content = QTextEdit()
        self.txt_content.setFont(QFont("Segoe UI Emoji", 10))
        self.txt_content.setStyleSheet("""
            QTextEdit {
                font-size: 13px;
                line-height: 1.45;
                padding: 8px;
                background-color: #0b0f19;
                color: #f8fafc;
                border: 1px solid #1e293b;
                border-radius: 6px;
            }
            QTextEdit:focus {
                border: 1px solid #6366f1;
            }
        """)
        self.txt_content.setMinimumHeight(120)
        self.txt_content.setPlaceholderText(
            "✏️ Nhập nội dung bài đăng hoặc bình luận tại đây...\n"
            "Hỗ trợ cấu trúc Spintext để tự động xoay đổi biến thể bài viết khi đăng:\n"
            "Ví dụ: {Chào bạn|Xin chào|Hello} mọi người! {Hôm nay|Tuần này} bên mình có ưu đãi đặc biệt..."
        )
        self.txt_content.textChanged.connect(self.update_char_count)
        self.c_layout.addWidget(self.txt_content)

        # Widget ĐÍNH KÈM HÌNH ẢNH / VIDEO & ĐỊNH DẠNG HỖ TRỢ
        self.post_widget = QWidget()
        pw_layout = QHBoxLayout(self.post_widget)
        pw_layout.setContentsMargins(0, 2, 0, 0)

        lbl_format_hint = QLabel("Định dạng hỗ trợ: Văn bản, Emoji, Xuống dòng")
        lbl_format_hint.setStyleSheet("color: #64748b; font-style: italic; font-size: 11px;")
        pw_layout.addWidget(lbl_format_hint)

        self.lbl_media_count = QLabel("Đính kèm: 0 tệp")
        self.lbl_media_count.setStyleSheet("color: #94a3b8; font-size: 11px;")
        pw_layout.addWidget(self.lbl_media_count)

        pw_layout.addStretch()

        btn_add_media = QPushButton("📷 Chọn Hình Ảnh / Video (Cho Bài Đăng hoặc Bình Luận)")
        btn_add_media.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                padding: 5px 12px;
                font-size: 11px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)
        btn_add_media.clicked.connect(self.on_select_media)
        pw_layout.addWidget(btn_add_media)

        btn_clear_media = QPushButton("🗑️ Xóa Tệp Đính Kèm")
        btn_clear_media.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                padding: 5px 10px;
                font-size: 11px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #ef4444;
                color: #ffffff;
                border: 1px solid #ef4444;
            }
        """)
        btn_clear_media.clicked.connect(self.on_clear_media)
        pw_layout.addWidget(btn_clear_media)
        self.c_layout.addWidget(self.post_widget)

        # Widget dành riêng cho ĐI BÌNH LUẬN (Nhập danh sách link bài viết Threads)
        self.comment_widget = QWidget()
        cw_layout = QVBoxLayout(self.comment_widget)
        cw_layout.setContentsMargins(0, 4, 0, 0)
        lbl_target_hint = QLabel("Danh Sách Link Bài Viết Threads (Mỗi link 1 dòng - Để trống sẽ TỰ ĐỘNG quét & bình luận bài trên Bảng tin):")
        lbl_target_hint.setStyleSheet("color: #cbd5e1; font-weight: bold; font-size: 11px;")
        cw_layout.addWidget(lbl_target_hint)
        
        self.txt_target_urls = QTextEdit()
        self.txt_target_urls.setFont(QFont("Segoe UI Emoji", 10))
        self.txt_target_urls.setStyleSheet("""
            QTextEdit {
                font-size: 12px;
                padding: 6px;
                background-color: #0b0f19;
                color: #f8fafc;
                border: 1px solid #1e293b;
                border-radius: 6px;
            }
            QTextEdit:focus {
                border: 1px solid #6366f1;
            }
        """)
        self.txt_target_urls.setPlaceholderText("https://www.threads.net/@user/post/...\nhttps://www.threads.net/@friend/post/...\n\n(💡 MẸO: Nếu để trống ô này, phần mềm sẽ TỰ ĐỘNG lướt Bảng tin Threads và đi bình luận các bài viết đang thịnh hành)")
        self.txt_target_urls.setMinimumHeight(80)
        cw_layout.addWidget(self.txt_target_urls)
        self.comment_widget.setVisible(False)
        self.c_layout.addWidget(self.comment_widget)

        top_layout.addWidget(content_box)

        # 3. Cấu hình Anti-Spam & Trình Duyệt (Trên 1 hàng ngang duy nhất)
        anti_box = QGroupBox("3. Cấu Hình Giãn Cách Chống Spam (Anti-Spam), Trình Duyệt")
        a_layout = QHBoxLayout(anti_box)
        a_layout.setContentsMargins(12, 10, 12, 10)
        a_layout.setSpacing(8)

        lbl_delay = QLabel("Giãn cách ngẫu nhiên:")
        lbl_delay.setStyleSheet("color: #cbd5e1;")
        a_layout.addWidget(lbl_delay)
        
        self.spin_delay_min = QSpinBox()
        self.spin_delay_min.setRange(5, 3600)
        self.spin_delay_min.setValue(30)
        self.spin_delay_min.setSuffix(" s")
        self.spin_delay_min.setFixedWidth(75)
        a_layout.addWidget(self.spin_delay_min)

        lbl_to = QLabel("đến")
        lbl_to.setStyleSheet("color: #94a3b8;")
        a_layout.addWidget(lbl_to)
        
        self.spin_delay_max = QSpinBox()
        self.spin_delay_max.setRange(5, 3600)
        self.spin_delay_max.setValue(90)
        self.spin_delay_max.setSuffix(" s")
        self.spin_delay_max.setFixedWidth(75)
        a_layout.addWidget(self.spin_delay_max)

        a_layout.addSpacing(15)
        lbl_rest = QLabel("Nghỉ đợi:")
        lbl_rest.setStyleSheet("color: #cbd5e1;")
        a_layout.addWidget(lbl_rest)
        
        self.spin_rest_min = QSpinBox()
        self.spin_rest_min.setRange(1, 60)
        self.spin_rest_min.setValue(5)
        self.spin_rest_min.setSuffix(" phút")
        self.spin_rest_min.setFixedWidth(85)
        a_layout.addWidget(self.spin_rest_min)

        lbl_after = QLabel("sau mỗi")
        lbl_after.setStyleSheet("color: #94a3b8;")
        a_layout.addWidget(lbl_after)
        
        self.spin_rest_after = QSpinBox()
        self.spin_rest_after.setRange(1, 50)
        self.spin_rest_after.setValue(10)
        self.spin_rest_after.setSuffix(" lượt")
        self.spin_rest_after.setFixedWidth(85)
        a_layout.addWidget(self.spin_rest_after)

        a_layout.addSpacing(15)
        lbl_br = QLabel("Trình duyệt:")
        lbl_br.setStyleSheet("color: #cbd5e1;")
        a_layout.addWidget(lbl_br)
        
        self.combo_browser_mode = QComboBox()
        self.combo_browser_mode.addItem("🌐 Hiển thị cửa sổ (Xem thao tác)", False)
        self.combo_browser_mode.addItem("⚡ Chạy ngầm (Headless)", True)
        self.combo_browser_mode.setMinimumHeight(28)
        a_layout.addWidget(self.combo_browser_mode, stretch=1)

        top_layout.addWidget(anti_box)

        # 4. Điều Khiển & Thanh Tiến Trình
        ctl_layout = QHBoxLayout()
        ctl_layout.setSpacing(10)

        self.btn_start = QPushButton("▶ BẮT ĐẦU THỰC HIỆN")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #10b981, stop:1 #059669);
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                padding: 9px 22px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #34d399, stop:1 #10b981);
            }
        """)
        self.btn_start.clicked.connect(self.on_start)
        ctl_layout.addWidget(self.btn_start)

        self.btn_pause = QPushButton("⏸ Tạm Dừng")
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0284c7, stop:1 #0369a1);
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                padding: 9px 18px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #38bdf8, stop:1 #0284c7);
            }
            QPushButton:disabled {
                background-color: #1e293b;
                color: #64748b;
            }
        """)
        self.btn_pause.clicked.connect(self.on_pause)
        ctl_layout.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("⏹ Dừng Hẳn")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ef4444, stop:1 #dc2626);
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                padding: 9px 18px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f87171, stop:1 #ef4444);
            }
            QPushButton:disabled {
                background-color: #1e293b;
                color: #64748b;
            }
        """)
        self.btn_stop.clicked.connect(self.on_stop)
        ctl_layout.addWidget(self.btn_stop)

        ctl_layout.addSpacing(10)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #0b0f19;
                border: 1px solid #1e293b;
                border-radius: 6px;
                text-align: center;
                color: #cbd5e1;
                font-weight: bold;
                height: 26px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #a855f7);
                border-radius: 5px;
            }
        """)
        ctl_layout.addWidget(self.progress_bar, stretch=1)

        top_layout.addLayout(ctl_layout)
        main_splitter.addWidget(top_container)

        # === PHẦN DƯỚI: KHU VỰC BẢNG KẾT QUẢ & NHẬT KÝ ===
        self.result_tabs = QTabWidget()
        self.result_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #1e293b;
                background-color: #111625;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #0d121f;
                color: #94a3b8;
                padding: 8px 18px;
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
        """)

        # Tab 1: Toàn Bộ Nhật Ký (Có Empty State khi 0 nhật ký)
        tab_log_widget = QWidget()
        tab_log_layout = QVBoxLayout(tab_log_widget)
        tab_log_layout.setContentsMargins(6, 6, 6, 6)

        # Stack chuyển đổi giữa bảng nhật ký và màn hình trống
        from PySide6.QtWidgets import QStackedWidget
        self.log_stack = QStackedWidget()

        # Page 0: Màn hình bảng nhật ký
        table_container = QWidget()
        tc_layout = QVBoxLayout(table_container)
        tc_layout.setContentsMargins(0, 0, 0, 0)
        tc_layout.setSpacing(6)

        self.log_table = QTableWidget()
        self.log_table.setColumnCount(5)
        self.log_table.setHorizontalHeaderLabels(["🕒 Thời Gian", "⚙️ Hành Động", "🔗 Mục Tiêu / Link", "🏷️ Trạng Thái", "ℹ️ Chi Tiết"])
        l_header = self.log_table.horizontalHeader()
        l_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        l_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        l_header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.log_table.setColumnWidth(2, 260)
        l_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        l_header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.log_table.cellDoubleClicked.connect(self.on_log_table_double_clicked)
        tc_layout.addWidget(self.log_table)

        btn_clear_log_tbl = QPushButton("🗑️ Xóa Lịch Sử Nhật Ký")
        btn_clear_log_tbl.setStyleSheet("padding: 4px 12px; font-size: 11px;")
        btn_clear_log_tbl.clicked.connect(self.on_clear_logs)
        tc_layout.addWidget(btn_clear_log_tbl, 0, Qt.AlignRight)

        self.log_stack.addWidget(table_container)

        # Page 1: Empty state khi chưa có dòng nhật ký nào
        empty_container = QWidget()
        ec_layout = QVBoxLayout(empty_container)
        ec_layout.setAlignment(Qt.AlignCenter)
        ec_layout.setSpacing(10)

        lbl_empty_icon = QLabel("📄")
        lbl_empty_icon.setAlignment(Qt.AlignCenter)
        lbl_empty_icon.setStyleSheet("font-size: 48px; color: #475569;")
        ec_layout.addWidget(lbl_empty_icon)

        lbl_empty_title = QLabel("Chưa có nhật ký nào")
        lbl_empty_title.setAlignment(Qt.AlignCenter)
        lbl_empty_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #cbd5e1;")
        ec_layout.addWidget(lbl_empty_title)

        lbl_empty_sub = QLabel("Kết quả thực hiện sẽ được hiển thị tại đây.")
        lbl_empty_sub.setAlignment(Qt.AlignCenter)
        lbl_empty_sub.setStyleSheet("font-size: 12px; color: #64748b;")
        ec_layout.addWidget(lbl_empty_sub)

        btn_clear_log_empty = QPushButton("🗑️ Xóa Lịch Sử Nhật Ký")
        btn_clear_log_empty.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                padding: 6px 16px;
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)
        btn_clear_log_empty.clicked.connect(self.on_clear_logs)
        ec_layout.addWidget(btn_clear_log_empty, 0, Qt.AlignCenter)

        self.log_stack.addWidget(empty_container)

        tab_log_layout.addWidget(self.log_stack)

        # Tab 2: Danh Sách Bài Đăng & Bình Luận Thành Công (Nhấn vào mở link)
        tab_success_widget = QWidget()
        tab_success_layout = QVBoxLayout(tab_success_widget)
        tab_success_layout.setContentsMargins(6, 6, 6, 6)

        self.success_table = QTableWidget()
        self.success_table.setColumnCount(5)
        self.success_table.setHorizontalHeaderLabels(["🕒 Thời Gian", "👤 Tài Khoản", "⚙️ Hành Động", "🔗 Liên Kết Bài Viết Threads (Nhấn Để Mở)", "🌐 Thao Tác"])
        s_header = self.success_table.horizontalHeader()
        s_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        s_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        s_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        s_header.setSectionResizeMode(3, QHeaderView.Stretch)
        s_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.success_table.cellClicked.connect(self.on_success_table_clicked)
        tab_success_layout.addWidget(self.success_table)

        row_succ_btns = QHBoxLayout()
        btn_clear_succ = QPushButton("🗑️ Xóa Danh Sách Hiện Tại")
        btn_clear_succ.clicked.connect(lambda: self.success_table.setRowCount(0))
        row_succ_btns.addWidget(btn_clear_succ)

        btn_open_selected = QPushButton("🌐 Mở Bài Viết Đang Chọn")
        btn_open_selected.setStyleSheet("background-color: #4f46e5; color: white; font-weight: bold; padding: 5px 15px;")
        btn_open_selected.clicked.connect(self.on_open_selected_success_link)
        row_succ_btns.addWidget(btn_open_selected)
        tab_success_layout.addLayout(row_succ_btns)

        self.result_tabs.addTab(tab_log_widget, "📋 1. Toàn Bộ Nhật Ký")
        self.result_tabs.addTab(tab_success_widget, "🟢 2. Các Bài Đăng / Bình Luận Thành Công (Nhấn Để Mở)")
        main_splitter.addWidget(self.result_tabs)

        # Thiết lập tỷ lệ ban đầu của Splitter: Vùng nội dung 460px, Bảng kết quả 240px
        main_splitter.setSizes([460, 240])
        layout.addWidget(main_splitter)

    def on_quick_login_clicked(self):
        parent_win = self.window()
        if hasattr(parent_win, 'threads_tabs'):
            parent_win.threads_tabs.setCurrentIndex(0)
            if hasattr(parent_win, 'threads_account_tab'):
                parent_win.threads_account_tab.on_browser_login()

    def load_accounts(self):
        accounts = self.db.get_threads_accounts()
        cur_uid = self.combo_accounts.currentData()
        self.combo_accounts.blockSignals(True)
        self.combo_accounts.clear()
        if not accounts:
            self.combo_accounts.addItem("⚠️ Chưa có tài khoản Threads (Bấm '➕ Đăng Nhập TK')", None)
        else:
            target_idx = 0
            for i, a in enumerate(accounts):
                name_str = a.get("name") or a.get("username") or f"UID: {a.get('uid')}"
                self.combo_accounts.addItem(f"{name_str} ({a['uid']})", a["uid"])
                if cur_uid and a["uid"] == cur_uid:
                    target_idx = i
            self.combo_accounts.setCurrentIndex(target_idx)
        self.combo_accounts.blockSignals(False)

    def load_campaign_templates(self):
        campaigns = self.db.get_campaigns()
        self.combo_campaigns.blockSignals(True)
        self.combo_campaigns.clear()
        self.combo_campaigns.addItem("✏️ [Tự Soạn Nội Dung Trực Tiếp]", None)
        for c in campaigns:
            self.combo_campaigns.addItem(f"📋 {c['title']}", c)
        self.combo_campaigns.blockSignals(False)

    def on_campaign_selected(self):
        camp = self.combo_campaigns.currentData()
        if camp and isinstance(camp, dict):
            self.txt_content.setText(camp.get("content", ""))
            images = camp.get("images", [])
            if images:
                self.selected_media_paths = list(images)
                self.lbl_media_count.setText(f"Đính kèm từ mẫu: {len(self.selected_media_paths)} tệp hình ảnh")

    def update_char_count(self):
        text = self.txt_content.toPlainText()
        chars = len(text)
        lines = len(text.splitlines()) if text else 0
        self.lbl_char_count.setText(f"{chars} ký tự | {lines} dòng")

    def on_insert_spintax(self):
        cursor = self.txt_content.textCursor()
        selected = cursor.selectedText()
        if selected:
            cursor.insertText(f"{{{selected}|biến thể 2|biến thể 3}}")
        else:
            cursor.insertText("{Nội dung 1|Nội dung 2|Nội dung 3}")
        self.txt_content.setFocus()

    def on_preview_spintax(self):
        text = self.txt_content.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Thông Báo", "Vui lòng nhập nội dung bài viết trước khi xem thử biến thể!")
            return
        parsed = SpintaxParser.parse(text)
        QMessageBox.information(self, "Xem Thử Biến Thể Bài Viết (Spintax Preview)", parsed)

    def on_mode_toggled(self):
        # Cả Đăng bài và Bình luận đều hỗ trợ đính kèm media
        self.post_widget.setVisible(True)
        if self.rad_post.isChecked():
            self.lbl_content_title.setText("📝 Nội Dung Bài Đăng Threads (Hỗ trợ Spintax {A|B|C}):")
            self.comment_widget.setVisible(False)
        else:
            self.lbl_content_title.setText("💬 Nội Dung Bình Luận Threads (Hỗ trợ Spintax {A|B|C}):")
            self.comment_widget.setVisible(True)

    def on_select_media(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Chọn Hình Ảnh / Video",
            "",
            "Tệp Đa Phương Tiện (*.jpg *.jpeg *.png *.webp *.mp4 *.mov);;Tất cả tệp (*.*)"
        )
        if files:
            self.selected_media_paths = files
            self.lbl_media_count.setText(f"Đã chọn: {len(files)} tệp đa phương tiện")

    def on_clear_media(self):
        self.selected_media_paths = []
        self.lbl_media_count.setText("Đính kèm: 0 tệp hình ảnh / video")

    def load_history_logs(self):
        pass

    def load_successful_posts(self):
        pass

    def on_success_table_clicked(self, row: int, col: int):
        if col == 3:
            item = self.success_table.item(row, col)
            if item:
                url = item.data(Qt.UserRole) or item.text().replace("🔗 ", "").strip()
                if url and url.startswith("http"):
                    webbrowser.open(url)

    def on_log_table_double_clicked(self, row: int, col: int):
        item = self.log_table.item(row, 2)
        if item:
            text = item.text().strip()
            if text.startswith("http"):
                webbrowser.open(text)

    def on_open_selected_success_link(self):
        cur_row = self.success_table.currentRow()
        if cur_row >= 0:
            item = self.success_table.item(cur_row, 3)
            if item:
                url = item.data(Qt.UserRole) or item.text().replace("🔗 ", "").strip()
                if url and url.startswith("http"):
                    webbrowser.open(url)
                    return
        QMessageBox.information(self, "Thông Báo", "Vui lòng chọn một dòng bài viết thành công có liên kết để mở!")

    def add_success_row(self, ts: str, acc_uid: str, action: str, target: str):
        row = self.success_table.rowCount()
        self.success_table.insertRow(row)
        self.success_table.setItem(row, 0, QTableWidgetItem(ts))
        self.success_table.setItem(row, 1, QTableWidgetItem(acc_uid))
        self.success_table.setItem(row, 2, QTableWidgetItem(action))

        link_item = QTableWidgetItem(f"🔗 {target}")
        link_item.setData(Qt.UserRole, target)
        link_item.setForeground(QColor("#89b4fa"))
        font = link_item.font()
        font.setUnderline(True)
        link_item.setFont(font)
        link_item.setToolTip("Nhấn để mở bài viết trên trình duyệt")
        self.success_table.setItem(row, 3, link_item)

        btn_open = QPushButton("🌐 Mở Bài")
        btn_open.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        btn_open.clicked.connect(lambda _, u=target: webbrowser.open(u))
        self.success_table.setCellWidget(row, 4, btn_open)
        self.success_table.scrollToBottom()

    def add_log_row(self, ts: str, action: str, target: str, status: str, msg: str):
        self.log_stack.setCurrentIndex(0)
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)
        self.log_table.setItem(row, 0, QTableWidgetItem(ts))
        self.log_table.setItem(row, 1, QTableWidgetItem(action))

        target_item = QTableWidgetItem(target)
        if target.startswith("http"):
            target_item.setForeground(QColor("#89b4fa"))
            target_item.setToolTip("Nhấp đúp chuột để mở liên kết")
        self.log_table.setItem(row, 2, target_item)

        s_item = QTableWidgetItem(status)
        if status == "SUCCESS":
            s_item.setForeground(Qt.green)
        elif status == "RUNNING":
            s_item.setForeground(Qt.yellow)
        else:
            s_item.setForeground(Qt.red)
        self.log_table.setItem(row, 3, s_item)

        self.log_table.setItem(row, 4, QTableWidgetItem(msg))
        self.log_table.scrollToBottom()

        # Nếu thành công và có liên kết, thêm ngay vào bảng thành công của lần chạy này
        if status == "SUCCESS" and target.startswith("http"):
            acc_uid = self.combo_accounts.currentData() or ""
            self.add_success_row(ts, acc_uid, action, target)

    def update_progress(self, cur: int, total: int):
        if total > 0:
            pct = int((cur / total) * 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setFormat(f"{cur}/{total} ({pct}%)")

    def on_start(self):
        acc_uid = self.combo_accounts.currentData()
        if not acc_uid:
            QMessageBox.warning(self, "Cảnh Báo", "Vui lòng chọn tài khoản Threads!")
            return

        content = self.txt_content.toPlainText().strip()
        mode = "POST" if self.rad_post.isChecked() else "COMMENT"

        target_urls = []
        if mode == "COMMENT":
            raw_urls = self.txt_target_urls.toPlainText().strip().splitlines()
            target_urls = [u.strip() for u in raw_urls if u.strip().startswith("http")]
            # Khi danh sách link trống, hệ thống sẽ tự động quét bài trên Bảng tin Threads
            if not content and not self.selected_media_paths:
                QMessageBox.warning(self, "Cảnh Báo", "Vui lòng nhập nội dung bình luận hoặc đính kèm ảnh/video!")
                return
        else:
            if not content and not self.selected_media_paths:
                QMessageBox.warning(self, "Cảnh Báo", "Vui lòng nhập nội dung hoặc đính kèm hình ảnh/video để đăng lên Threads!")
                return

        # Làm mới hoàn toàn: chỉ lưu link và thông báo của lần chạy này
        self.db.clear_threads_logs()
        self.log_table.setRowCount(0)
        self.success_table.setRowCount(0)
        self.progress_bar.setValue(0)

        anti_config = AntiSpamConfig(
            min_delay_sec=self.spin_delay_min.value(),
            max_delay_sec=self.spin_delay_max.value(),
            rest_after_posts=self.spin_rest_after.value(),
            rest_duration_min=self.spin_rest_min.value()
        )

        headless = bool(self.combo_browser_mode.currentData())

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)

        self.worker = ThreadsActionWorker(
            db=self.db,
            account_uid=acc_uid,
            action_mode=mode,
            content_text=content,
            media_paths=self.selected_media_paths,
            target_urls=target_urls,
            anti_config=anti_config,
            headless=headless
        )
        self.worker.log_signal.connect(self.add_log_row)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(self.on_worker_finished)
        self.status_updated.emit("Đang khởi động tác vụ Threads...")
        self.worker.start()

    def on_pause(self):
        if not self.worker:
            return
        if self.worker.is_paused:
            self.worker.resume()
            self.btn_pause.setText("⏸️ Tạm Dừng")
            self.status_updated.emit("Tiến trình Threads đang tiếp tục...")
        else:
            self.worker.pause()
            self.btn_pause.setText("▶️ Tiếp Tục")
            self.status_updated.emit("Tiến trình Threads đang tạm dừng...")

    def on_stop(self):
        if self.worker:
            self.worker.stop()
            self.add_log_row(time.strftime("%H:%M:%S"), "-", "-", "STOPPED", "Đang dừng tiến trình Threads...")
            self.status_updated.emit("Đã dừng tiến trình Threads.")

    def on_worker_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setText("⏸️ Tạm Dừng")
        self.status_updated.emit("Tiến trình Threads đã hoàn tất.")
        QMessageBox.information(self, "Hoàn Tất", "Tiến trình Threads đã kết thúc!")

    def on_clear_logs(self):
        self.db.clear_threads_logs()
        self.log_table.setRowCount(0)
        self.success_table.setRowCount(0)
        self.log_stack.setCurrentIndex(1)
