import asyncio
import time
import os
import webbrowser
from typing import List
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QTextEdit, QSpinBox, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QRadioButton, QButtonGroup,
    QProgressBar, QMessageBox, QFileDialog, QTabWidget,
    QLineEdit, QCheckBox, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from core.database import Database
from core.threads_automation import ThreadsAutomationEngine
from core.anti_spam import AntiSpamManager, AntiSpamConfig
from core.spintax_parser import SpintaxParser
from core.excel_loader import (
    load_posts_from_excel,
    get_configured_excel_path,
    set_configured_excel_path,
    DEFAULT_EXCEL_PATH
)


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
        headless: bool = True,
        excel_posts: list = None,
        loop_forever: bool = True,
        min_likes: int = 0,
        human_simulation: bool = True
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
        self.excel_posts = excel_posts or []
        self.loop_forever = loop_forever
        self.min_likes = min_likes
        self.human_simulation = human_simulation
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

        engine = ThreadsAutomationEngine(db=self.db)
        cookie_str = acc.get("cookie", "")
        proxy = acc.get("proxy", "")

        if self.action_mode == "POST":
            await engine.run_posting_session(
                cookie_str=cookie_str,
                excel_posts=self.excel_posts,
                anti_config=self.anti_config,
                proxy=proxy,
                headless=self.headless,
                uid=self.account_uid,
                loop_forever=self.loop_forever,
                is_paused_fn=lambda: self.is_paused,
                is_stopped_fn=lambda: self.is_stopped,
                log_callback=lambda ts, act, tgt, st, msg: self.log_signal.emit(ts, act, tgt, st, msg),
                progress_callback=lambda cur, tot: self.progress_signal.emit(cur, tot)
            )
        else:
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
                success_callback=None,
                excel_posts=self.excel_posts,
                min_likes=self.min_likes,
                human_simulation=self.human_simulation
            )


class ThreadsPosterTab(QWidget):
    status_updated = Signal(str)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.worker = None
        self.selected_media_paths = []
        self.excel_posts = []
        self.preview_tpl_idx = 0
        self.success_post_count = 0

        self.init_ui()
        self.load_accounts()
        self.load_campaign_templates()
        self.db.clear_threads_logs()
        self.log_table.setRowCount(0)
        self.success_table.setRowCount(0)

    def _create_card_frame(self) -> QFrame:
        card = QFrame()
        card.setObjectName("dashCard")
        card.setStyleSheet("""
            QFrame#dashCard {
                background-color: #111827;
                border: 1px solid #1e293b;
                border-radius: 12px;
            }
        """)
        return card

    def _create_inner_box(self) -> QFrame:
        box = QFrame()
        box.setObjectName("innerBox")
        box.setStyleSheet("""
            QFrame#innerBox {
                background-color: #0b0f19;
                border: 1px solid #1e293b;
                border-radius: 8px;
            }
        """)
        return box

    def _create_check_row(self, checkbox: QCheckBox) -> QFrame:
        row_frame = QFrame()
        row_frame.setObjectName("chkRow")
        row_frame.setStyleSheet("""
            QFrame#chkRow {
                background-color: #0b0f19;
                border: 1px solid #1e293b;
                border-radius: 7px;
            }
            QFrame#chkRow:hover {
                border: 1px solid #334155;
            }
        """)
        rl = QHBoxLayout(row_frame)
        rl.setContentsMargins(10, 7, 10, 7)
        checkbox.setStyleSheet("border: none; background: transparent; color: #cbd5e1; font-size: 12px;")
        rl.addWidget(checkbox)
        return row_frame

    def load_campaigns(self):
        self.load_campaign_templates()

    def on_toggle_pause(self):
        self.on_pause()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)

        # =========================================================================
        # PHẦN 1: LƯỚI 3 CỘT CARD CẤU HÌNH THREADS (THEO PHONG CÁCH ẢNH 2)
        # =========================================================================
        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)

        # -------------------------------------------------------------------------
        # CARD 1: 1. NGUỒN & TÀI KHOẢN THREADS
        # -------------------------------------------------------------------------
        card1 = self._create_card_frame()
        c1_layout = QVBoxLayout(card1)
        c1_layout.setContentsMargins(16, 14, 16, 14)
        c1_layout.setSpacing(10)

        c1_header = QHBoxLayout()
        lbl_num1 = QLabel("1")
        lbl_num1.setFixedSize(22, 22)
        lbl_num1.setAlignment(Qt.AlignCenter)
        lbl_num1.setStyleSheet("background-color: #1e3a8a; color: #60a5fa; font-weight: bold; font-size: 11px; border-radius: 5px; border: none;")
        c1_header.addWidget(lbl_num1)

        lbl_title1 = QLabel("Nguồn & Tài Khoản")
        lbl_title1.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: bold; border: none; background: transparent;")
        c1_header.addWidget(lbl_title1)
        c1_header.addStretch()

        lbl_sub1 = QLabel("Cấu hình chính")
        lbl_sub1.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        c1_header.addWidget(lbl_sub1)
        c1_layout.addLayout(c1_header)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        c1_layout.addWidget(sep1)

        # Chọn Tài Khoản Threads
        acc_top_row = QHBoxLayout()
        lbl_acc = QLabel("Chọn Tài Khoản Threads")
        lbl_acc.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        acc_top_row.addWidget(lbl_acc)
        acc_top_row.addStretch()

        btn_quick_login = QPushButton("➕ Thêm / Đăng Nhập TK")
        btn_quick_login.setCursor(Qt.PointingHandCursor)
        btn_quick_login.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #3b82f6;
                border: none;
                font-size: 11px;
                font-weight: bold;
                padding: 0;
            }
            QPushButton:hover {
                color: #60a5fa;
                text-decoration: underline;
            }
        """)
        btn_quick_login.clicked.connect(self.on_quick_login_clicked)
        acc_top_row.addWidget(btn_quick_login)
        c1_layout.addLayout(acc_top_row)

        self.combo_accounts = QComboBox()
        self.combo_accounts.setFixedHeight(36)
        self.combo_accounts.currentIndexChanged.connect(self.update_preview_card)
        c1_layout.addWidget(self.combo_accounts)

        # Chế Độ Hành Động Threads (2 Tile Chọn Giống Ảnh 2)
        lbl_mode = QLabel("Chế Độ Hành Động")
        lbl_mode.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        c1_layout.addWidget(lbl_mode)

        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(10)

        self.tile_post = QFrame()
        self.tile_post.setCursor(Qt.PointingHandCursor)
        self.tile_post.mousePressEvent = lambda e: self.rad_post.setChecked(True)
        t1_l = QVBoxLayout(self.tile_post)
        t1_l.setContentsMargins(12, 10, 12, 10)
        t1_l.setSpacing(6)
        t1_top = QHBoxLayout()
        lbl_t1_ico = QLabel("📮")
        lbl_t1_ico.setStyleSheet("font-size: 15px; border: none; background: transparent;")
        t1_top.addWidget(lbl_t1_ico)
        t1_top.addStretch()
        self.rad_post = QRadioButton()
        self.rad_post.setChecked(True)
        self.rad_post.setStyleSheet("border: none; background: transparent;")
        t1_top.addWidget(self.rad_post)
        t1_l.addLayout(t1_top)
        lbl_t1_txt = QLabel("Đăng Bài Threads")
        lbl_t1_txt.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 12px; border: none; background: transparent;")
        t1_l.addWidget(lbl_t1_txt)
        tiles_row.addWidget(self.tile_post, 1)

        self.tile_comment = QFrame()
        self.tile_comment.setCursor(Qt.PointingHandCursor)
        self.tile_comment.mousePressEvent = lambda e: self.rad_comment.setChecked(True)
        t2_l = QVBoxLayout(self.tile_comment)
        t2_l.setContentsMargins(12, 10, 12, 10)
        t2_l.setSpacing(6)
        t2_top = QHBoxLayout()
        lbl_t2_ico = QLabel("💬")
        lbl_t2_ico.setStyleSheet("font-size: 15px; border: none; background: transparent;")
        t2_top.addWidget(lbl_t2_ico)
        t2_top.addStretch()
        self.rad_comment = QRadioButton()
        self.rad_comment.setStyleSheet("border: none; background: transparent;")
        t2_top.addWidget(self.rad_comment)
        t2_l.addLayout(t2_top)
        lbl_t2_txt = QLabel("Bình Luận Bảng Tin")
        lbl_t2_txt.setStyleSheet("color: #cbd5e1; font-weight: bold; font-size: 12px; border: none; background: transparent;")
        t2_l.addWidget(lbl_t2_txt)
        tiles_row.addWidget(self.tile_comment, 1)

        mode_group = QButtonGroup(self)
        mode_group.addButton(self.rad_post)
        mode_group.addButton(self.rad_comment)
        self.rad_post.toggled.connect(self.on_mode_toggled)

        c1_layout.addLayout(tiles_row)

        # Khung Lọc Số Like Tối Thiểu (Khi chọn Bình Luận Bảng Tin)
        self.comment_widget = self._create_inner_box()
        cw_layout = QVBoxLayout(self.comment_widget)
        cw_layout.setContentsMargins(10, 8, 10, 8)
        cw_layout.setSpacing(6)

        like_filter_row = QHBoxLayout()
        like_filter_row.setSpacing(4)
        lbl_min_likes = QLabel("❤️ Like tối thiểu:")
        lbl_min_likes.setStyleSheet("color: #f43f5e; font-weight: bold; font-size: 11px; border: none; background: transparent;")
        like_filter_row.addWidget(lbl_min_likes)

        saved_min_likes = int(self.db.get_setting("threads_min_likes", 100) or 0)
        self.spin_min_likes = QSpinBox()
        self.spin_min_likes.setRange(0, 1000000)
        self.spin_min_likes.setSingleStep(50)
        self.spin_min_likes.setValue(saved_min_likes)
        self.spin_min_likes.setSuffix(" Likes")
        self.spin_min_likes.setFixedHeight(26)
        self.spin_min_likes.setStyleSheet("font-weight: bold; color: #f8fafc; background-color: #111827; padding: 2px 6px; border: 1px solid #f43f5e; border-radius: 4px; font-size: 11px;")
        self.spin_min_likes.valueChanged.connect(lambda val: self.db.set_setting("threads_min_likes", int(val)))
        like_filter_row.addWidget(self.spin_min_likes)

        for preset_val, preset_lbl in [(0, "0"), (100, "100+"), (500, "500+"), (1000, "1K+")]:
            btn_p = QPushButton(preset_lbl)
            btn_p.setCursor(Qt.PointingHandCursor)
            btn_p.setFixedHeight(24)
            btn_p.setStyleSheet("background-color: #1e293b; color: #cbd5e1; border: 1px solid #334155; padding: 1px 6px; font-size: 10px; border-radius: 4px;")
            btn_p.clicked.connect(lambda _, v=preset_val: self.spin_min_likes.setValue(v))
            like_filter_row.addWidget(btn_p)
        cw_layout.addLayout(like_filter_row)

        self.txt_target_urls = QTextEdit()
        self.txt_target_urls.setPlaceholderText("Link bài viết cụ thể (Để trống = Tự lướt Bảng tin Threads lọc theo số Like)")
        self.txt_target_urls.setFixedHeight(42)
        self.txt_target_urls.setStyleSheet("background-color: #111827; color: #cbd5e1; padding: 4px 8px; border: 1px solid #1e293b; border-radius: 4px; font-size: 11px;")
        cw_layout.addWidget(self.txt_target_urls)

        self.comment_widget.setVisible(False)
        c1_layout.addWidget(self.comment_widget)

        # ANTI-SPAM & BẢO MẬT
        lbl_sec = QLabel("ANTI-SPAM & BẢO MẬT")
        lbl_sec.setStyleSheet("color: #64748b; font-size: 10px; font-weight: bold; letter-spacing: 0.5px; border: none; background: transparent; margin-top: 2px;")
        c1_layout.addWidget(lbl_sec)

        self.chk_human_sim = QCheckBox("Chống xác minh con người / Checkpoint tự động")
        self.chk_human_sim.setChecked(True)
        c1_layout.addWidget(self._create_check_row(self.chk_human_sim))

        self.chk_shuffle_media = QCheckBox("Xáo trộn thứ tự hình ảnh/video ngẫu nhiên")
        self.chk_shuffle_media.setChecked(True)
        c1_layout.addWidget(self._create_check_row(self.chk_shuffle_media))

        self.chk_hash = QCheckBox("Thêm mã Hash ngẫu nhiên cuối bài")
        c1_layout.addWidget(self._create_check_row(self.chk_hash))

        c1_layout.addStretch()
        cards_row.addWidget(card1, 1)

        # -------------------------------------------------------------------------
        # CARD 2: 2. NỘI DUNG & SPINTAX
        # -------------------------------------------------------------------------
        card2 = self._create_card_frame()
        c2_layout = QVBoxLayout(card2)
        c2_layout.setContentsMargins(16, 14, 16, 14)
        c2_layout.setSpacing(10)

        c2_header = QHBoxLayout()
        lbl_num2 = QLabel("2")
        lbl_num2.setFixedSize(22, 22)
        lbl_num2.setAlignment(Qt.AlignCenter)
        lbl_num2.setStyleSheet("background-color: #1e3a8a; color: #60a5fa; font-weight: bold; font-size: 11px; border-radius: 5px; border: none;")
        c2_header.addWidget(lbl_num2)

        lbl_title2 = QLabel("Nội Dung & Spintax")
        lbl_title2.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: bold; border: none; background: transparent;")
        c2_header.addWidget(lbl_title2)
        c2_header.addStretch()

        btn_spin_preview = QPushButton("🔀 Xem Biến Spintax")
        btn_spin_preview.setCursor(Qt.PointingHandCursor)
        btn_spin_preview.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #3b82f6;
                border: none;
                font-size: 11px;
                font-weight: bold;
                padding: 2px 4px;
            }
            QPushButton:hover {
                color: #60a5fa;
                text-decoration: underline;
            }
        """)
        btn_spin_preview.clicked.connect(self.on_preview_spintax)
        c2_header.addWidget(btn_spin_preview)
        c2_layout.addLayout(c2_header)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        c2_layout.addWidget(sep2)

        excel_box = self._create_inner_box()
        eb_layout = QVBoxLayout(excel_box)
        eb_layout.setContentsMargins(12, 10, 12, 10)
        eb_layout.setSpacing(8)

        eb_top = QHBoxLayout()
        lbl_excel_title = QLabel("Mẫu Bài Viết (Excel)")
        lbl_excel_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        eb_top.addWidget(lbl_excel_title)
        eb_top.addStretch()

        self.lbl_excel_badge = QLabel("0 Mẫu sẵn sàng")
        self.lbl_excel_badge.setStyleSheet("""
            QLabel {
                background-color: #052e16;
                color: #10b981;
                border: 1px solid #065f46;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: bold;
            }
        """)
        eb_top.addWidget(self.lbl_excel_badge)
        eb_layout.addLayout(eb_top)

        eb_btns = QHBoxLayout()
        eb_btns.setSpacing(8)
        btn_browse_excel = QPushButton("📄  Chọn File Excel")
        btn_browse_excel.setCursor(Qt.PointingHandCursor)
        btn_browse_excel.setFixedHeight(34)
        btn_browse_excel.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #3b82f6;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        btn_browse_excel.clicked.connect(self.on_browse_excel)
        eb_btns.addWidget(btn_browse_excel, 1)

        btn_reload_excel = QPushButton("🔄")
        btn_reload_excel.setCursor(Qt.PointingHandCursor)
        btn_reload_excel.setFixedSize(34, 34)
        btn_reload_excel.setToolTip("Đọc lại file Excel mẫu bài viết")
        btn_reload_excel.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-radius: 6px;
                font-size: 13px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)
        btn_reload_excel.clicked.connect(self.load_campaign_templates)
        eb_btns.addWidget(btn_reload_excel)
        eb_layout.addLayout(eb_btns)

        self.txt_excel_path = QLineEdit()
        self.txt_excel_path.setText(get_configured_excel_path(self.db))
        self.txt_excel_path.setVisible(False)
        eb_layout.addWidget(self.txt_excel_path)

        c2_layout.addWidget(excel_box)

        # Header Xem Trước Bài Viết (Mẫu #k) + Điều hướng < k / N >
        prev_nav_row = QHBoxLayout()
        self.lbl_preview_title = QLabel("Xem Trước Bài Viết (Mẫu #1)")
        self.lbl_preview_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        prev_nav_row.addWidget(self.lbl_preview_title)
        prev_nav_row.addStretch()

        self.btn_prev_tpl = QPushButton("‹")
        self.btn_prev_tpl.setCursor(Qt.PointingHandCursor)
        self.btn_prev_tpl.setFixedSize(22, 22)
        self.btn_prev_tpl.setStyleSheet("background-color: transparent; color: #94a3b8; border: none; font-size: 15px; font-weight: bold; padding: 0;")
        self.btn_prev_tpl.clicked.connect(self.on_prev_template)
        prev_nav_row.addWidget(self.btn_prev_tpl)

        self.lbl_tpl_counter = QLabel("1 / 1")
        self.lbl_tpl_counter.setStyleSheet("color: #94a3b8; font-size: 11px; border: none; background: transparent; padding: 0 4px;")
        prev_nav_row.addWidget(self.lbl_tpl_counter)

        self.btn_next_tpl = QPushButton("›")
        self.btn_next_tpl.setCursor(Qt.PointingHandCursor)
        self.btn_next_tpl.setFixedSize(22, 22)
        self.btn_next_tpl.setStyleSheet("background-color: transparent; color: #94a3b8; border: none; font-size: 15px; font-weight: bold; padding: 0;")
        self.btn_next_tpl.clicked.connect(self.on_next_template)
        prev_nav_row.addWidget(self.btn_next_tpl)

        c2_layout.addLayout(prev_nav_row)

        # Khung Social Post Preview
        social_preview_box = self._create_inner_box()
        sp_layout = QVBoxLayout(social_preview_box)
        sp_layout.setContentsMargins(12, 10, 12, 10)
        sp_layout.setSpacing(6)

        sp_author_row = QHBoxLayout()
        sp_author_row.setSpacing(8)
        lbl_th_ava = QLabel("TH")
        lbl_th_ava.setFixedSize(24, 24)
        lbl_th_ava.setAlignment(Qt.AlignCenter)
        lbl_th_ava.setStyleSheet("background-color: #312e81; color: #a5b4fc; font-weight: bold; font-size: 10px; border-radius: 12px; border: none;")
        sp_author_row.addWidget(lbl_th_ava)

        self.lbl_preview_author = QLabel("Tài khoản Threads")
        self.lbl_preview_author.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 12px; border: none; background: transparent;")
        sp_author_row.addWidget(self.lbl_preview_author)
        sp_author_row.addStretch()
        sp_layout.addLayout(sp_author_row)

        self.txt_content = QTextEdit()
        self.txt_content.setReadOnly(True)
        self.txt_content.setFont(QFont("Segoe UI Emoji", 10))
        self.txt_content.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                color: #cbd5e1;
                font-size: 12px;
                line-height: 1.45;
                padding: 2px 0px;
                border: none;
            }
        """)
        self.txt_content.setMinimumHeight(95)
        sp_layout.addWidget(self.txt_content, 1)

        sp_sep = QFrame()
        sp_sep.setFrameShape(QFrame.HLine)
        sp_sep.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        sp_layout.addWidget(sp_sep)

        sp_footer = QHBoxLayout()
        self.lbl_media_count = QLabel("Đường dẫn ảnh: -")
        self.lbl_media_count.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        sp_footer.addWidget(self.lbl_media_count, 1)

        lbl_spintax_active = QLabel("Spintax Active")
        lbl_spintax_active.setStyleSheet("color: #3b82f6; font-size: 11px; font-weight: 600; text-decoration: underline; border: none; background: transparent;")
        sp_footer.addWidget(lbl_spintax_active)
        sp_layout.addLayout(sp_footer)

        c2_layout.addWidget(social_preview_box, 1)
        cards_row.addWidget(card2, 1)

        # -------------------------------------------------------------------------
        # CARD 3: 3. TIẾN TRÌNH & TARGET
        # -------------------------------------------------------------------------
        card3 = self._create_card_frame()
        c3_layout = QVBoxLayout(card3)
        c3_layout.setContentsMargins(16, 14, 16, 14)
        c3_layout.setSpacing(10)

        c3_header = QHBoxLayout()
        lbl_num3 = QLabel("3")
        lbl_num3.setFixedSize(22, 22)
        lbl_num3.setAlignment(Qt.AlignCenter)
        lbl_num3.setStyleSheet("background-color: #422006; color: #f59e0b; font-weight: bold; font-size: 11px; border-radius: 5px; border: none;")
        c3_header.addWidget(lbl_num3)

        lbl_title3 = QLabel("Tiến Trình & Target")
        lbl_title3.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: bold; border: none; background: transparent;")
        c3_header.addWidget(lbl_title3)
        c3_header.addStretch()

        lbl_sub3 = QLabel("Đa luồng")
        lbl_sub3.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        c3_header.addWidget(lbl_sub3)
        c3_layout.addLayout(c3_header)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.HLine)
        sep3.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        c3_layout.addWidget(sep3)

        target_box = self._create_inner_box()
        tb_layout = QVBoxLayout(target_box)
        tb_layout.setContentsMargins(12, 10, 12, 10)
        tb_layout.setSpacing(8)

        tb_top = QHBoxLayout()
        self.lbl_content_title = QLabel("Bảng Tin Threads")
        self.lbl_content_title.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 12px; border: none; background: transparent;")
        tb_top.addWidget(self.lbl_content_title)
        tb_top.addStretch()

        btn_open_folder = QPushButton("📂 Mở Folder Ảnh")
        btn_open_folder.setCursor(Qt.PointingHandCursor)
        btn_open_folder.setFixedHeight(26)
        btn_open_folder.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-radius: 5px;
                padding: 2px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)
        btn_open_folder.clicked.connect(self.on_open_selected_folder)
        tb_top.addWidget(btn_open_folder)
        tb_layout.addLayout(tb_top)

        delay_lbl_row = QHBoxLayout()
        lbl_dl = QLabel("Delay giữa 2 lượt (s)")
        lbl_dl.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        delay_lbl_row.addWidget(lbl_dl, 1)
        lbl_rst = QLabel("Nghỉ (Phút) / Sau số bài")
        lbl_rst.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        delay_lbl_row.addWidget(lbl_rst, 1)
        tb_layout.addLayout(delay_lbl_row)

        delay_inp_row = QHBoxLayout()
        delay_inp_row.setSpacing(6)

        spin_css = """
            QSpinBox {
                background-color: #111827;
                color: #f8fafc;
                border: 1px solid #1e293b;
                border-radius: 6px;
                padding: 4px 6px;
                font-weight: bold;
                font-size: 12px;
            }
            QSpinBox:focus {
                border: 1px solid #2563eb;
            }
        """

        self.spin_delay_min = QSpinBox()
        self.spin_delay_min.setRange(5, 3600)
        self.spin_delay_min.setValue(45)
        self.spin_delay_min.setAlignment(Qt.AlignCenter)
        self.spin_delay_min.setFixedHeight(32)
        self.spin_delay_min.setStyleSheet(spin_css)
        delay_inp_row.addWidget(self.spin_delay_min, 1)

        lbl_den = QLabel("đến")
        lbl_den.setAlignment(Qt.AlignCenter)
        lbl_den.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        delay_inp_row.addWidget(lbl_den)

        self.spin_delay_max = QSpinBox()
        self.spin_delay_max.setRange(5, 3600)
        self.spin_delay_max.setValue(120)
        self.spin_delay_max.setAlignment(Qt.AlignCenter)
        self.spin_delay_max.setFixedHeight(32)
        self.spin_delay_max.setStyleSheet(spin_css)
        delay_inp_row.addWidget(self.spin_delay_max, 1)

        delay_inp_row.addSpacing(6)

        self.spin_rest_min = QSpinBox()
        self.spin_rest_min.setRange(1, 60)
        self.spin_rest_min.setValue(8)
        self.spin_rest_min.setAlignment(Qt.AlignCenter)
        self.spin_rest_min.setFixedHeight(32)
        self.spin_rest_min.setStyleSheet(spin_css)
        delay_inp_row.addWidget(self.spin_rest_min, 1)

        self.spin_rest_after = QSpinBox()
        self.spin_rest_after.setRange(1, 50)
        self.spin_rest_after.setValue(8)
        self.spin_rest_after.setAlignment(Qt.AlignCenter)
        self.spin_rest_after.setFixedHeight(32)
        self.spin_rest_after.setStyleSheet(spin_css)
        delay_inp_row.addWidget(self.spin_rest_after, 1)

        tb_layout.addLayout(delay_inp_row)
        c3_layout.addWidget(target_box)

        lbl_br = QLabel("Chế Độ Trình Duyệt")
        lbl_br.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        c3_layout.addWidget(lbl_br)

        self.combo_browser_mode = QComboBox()
        self.combo_browser_mode.setFixedHeight(36)
        self.combo_browser_mode.addItem("Hiển thị Trình Duyệt (Quan sát trực tiếp)", False)
        self.combo_browser_mode.addItem("Chạy Ngầm Hệ Thống (Headless)", True)
        c3_layout.addWidget(self.combo_browser_mode)

        self.chk_loop_forever = QCheckBox("Đăng vòng lặp liên tục (1 ➔ N ➔ 1)")
        self.chk_loop_forever.setChecked(True)
        c3_layout.addWidget(self._create_check_row(self.chk_loop_forever))

        c3_layout.addStretch()
        cards_row.addWidget(card3, 1)

        main_layout.addLayout(cards_row)

        # =========================================================================
        # PHẦN 2: THANH TIẾN TRÌNH TỔNG THỂ & CỤM NÚT ĐIỀU KHIỂN
        # =========================================================================
        exec_card = self._create_card_frame()
        exec_card.setFixedHeight(64)
        e_layout = QHBoxLayout(exec_card)
        e_layout.setContentsMargins(18, 10, 18, 10)
        e_layout.setSpacing(20)

        prog_col = QVBoxLayout()
        prog_col.setContentsMargins(0, 0, 0, 0)
        prog_col.setSpacing(6)

        prog_top = QHBoxLayout()
        lbl_prog_title = QLabel("Tiến trình tổng thể")
        lbl_prog_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        prog_top.addWidget(lbl_prog_title)
        prog_top.addStretch()

        self.lbl_progress_pct = QLabel("0% (Sẵn sàng)")
        self.lbl_progress_pct.setStyleSheet("color: #06b6d4; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        prog_top.addWidget(self.lbl_progress_pct)
        prog_col.addLayout(prog_top)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1e293b;
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #10b981);
                border-radius: 3px;
            }
        """)
        prog_col.addWidget(self.progress_bar)
        e_layout.addLayout(prog_col, 1)

        e_layout.addSpacing(20)

        self.btn_start = QPushButton("▶   BẮT ĐẦU CHẠY")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setFixedSize(165, 38)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #4f46e5);
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #60a5fa;
                border-radius: 8px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4ed8, stop:1 #4338ca);
            }
            QPushButton:disabled {
                background-color: #1e293b;
                color: #64748b;
                border: 1px solid #334155;
            }
        """)
        self.btn_start.clicked.connect(self.on_start)
        e_layout.addWidget(self.btn_start)

        self.btn_pause = QPushButton("⏸   Tạm Dừng")
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setFixedSize(115, 38)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                font-weight: 600;
                font-size: 12px;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
            QPushButton:disabled {
                background-color: #0f172a;
                color: #475569;
                border: 1px solid #1e293b;
            }
        """)
        self.btn_pause.clicked.connect(self.on_pause)
        e_layout.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("⏹   Dừng Hẳn")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setFixedSize(115, 38)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background-color: #2d1219;
                color: #f87171;
                font-weight: 600;
                font-size: 12px;
                border: 1px solid #7f1d1d;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #451a23;
                color: #fca5a5;
            }
            QPushButton:disabled {
                background-color: #1a1118;
                color: #7f1d1d;
                border: 1px solid #31151c;
            }
        """)
        self.btn_stop.clicked.connect(self.on_stop)
        e_layout.addWidget(self.btn_stop)

        main_layout.addWidget(exec_card)

        # =========================================================================
        # PHẦN 3: BẢNG CHI TIẾT THÔNG BÁO & LỊCH SỬ HOẠT ĐỘNG
        # =========================================================================
        log_card = self._create_card_frame()
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(16, 12, 16, 12)
        log_layout.setSpacing(8)

        log_header = QHBoxLayout()
        lbl_log_title = QLabel("Chi Tiết Thông Báo & Lịch Sử Hoạt Động")
        lbl_log_title.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: bold; border: none; background: transparent;")
        log_header.addWidget(lbl_log_title)

        log_header.addSpacing(12)
        self.lbl_log_status = QLabel("Trạng thái: Sẵn sàng hoạt động")
        self.lbl_log_status.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        log_header.addWidget(self.lbl_log_status)

        log_header.addStretch()

        self.lbl_success_counter = QLabel("●  Đã đăng 0 bài thành công")
        self.lbl_success_counter.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        log_header.addWidget(self.lbl_success_counter)

        log_layout.addLayout(log_header)

        self.log_table = QTableWidget()
        self.log_table.setColumnCount(5)
        self.log_table.setHorizontalHeaderLabels(["THỜI GIAN", "HÀNH ĐỘNG", "MỤC TIÊU / LINK", "TRẠNG THÁI", "CHI TIẾT"])
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setShowGrid(False)
        self.log_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        l_header = self.log_table.horizontalHeader()
        l_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        l_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        l_header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.log_table.setColumnWidth(2, 260)
        l_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        l_header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.log_table.cellClicked.connect(self.on_log_table_double_clicked)
        log_layout.addWidget(self.log_table, 1)

        # Giữ biến tương thích ngược
        self.result_tabs = QTabWidget()
        self.success_table = QTableWidget()
        self.table_excel = QTableWidget()

        main_layout.addWidget(log_card, 1)

        self._update_tile_styles()

    def _update_tile_styles(self):
        is_comment = self.rad_comment.isChecked()
        active_tile_css = """
            QFrame {
                background-color: #132247;
                border: 1px solid #2563eb;
                border-radius: 8px;
            }
        """
        inactive_tile_css = """
            QFrame {
                background-color: #0b0f19;
                border: 1px solid #1e293b;
                border-radius: 8px;
            }
            QFrame:hover {
                border: 1px solid #334155;
            }
        """
        self.tile_post.setStyleSheet(inactive_tile_css if is_comment else active_tile_css)
        self.tile_comment.setStyleSheet(active_tile_css if is_comment else inactive_tile_css)

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
            self.combo_accounts.addItem("⚠️ Chưa có tài khoản Threads (Bấm '➕ Thêm / Đăng Nhập TK')", None)
        else:
            target_idx = 0
            for i, a in enumerate(accounts):
                name_str = a.get("name") or a.get("username") or f"UID: {a.get('uid')}"
                self.combo_accounts.addItem(f"{name_str} ({a['uid']})", a["uid"])
                if cur_uid and a["uid"] == cur_uid:
                    target_idx = i
            self.combo_accounts.setCurrentIndex(target_idx)
        self.combo_accounts.blockSignals(False)
        self.update_preview_card()

    def on_browse_excel(self):
        cur_path = self.txt_excel_path.text().strip()
        start_dir = os.path.dirname(cur_path) if (cur_path and os.path.exists(os.path.dirname(cur_path))) else r"E:\Affiliate"
        if not os.path.exists(start_dir):
            start_dir = ""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn File Excel Mẫu Bài Viết (.xlsx)",
            start_dir,
            "Excel Files (*.xlsx);;All Files (*.*)"
        )
        if file_path:
            self.txt_excel_path.setText(file_path)
            set_configured_excel_path(self.db, file_path)
            self.preview_tpl_idx = 0
            self.load_campaign_templates()

    def on_open_selected_folder(self):
        if not self.excel_posts:
            return
        idx = min(self.preview_tpl_idx, len(self.excel_posts) - 1)
        folder = self.excel_posts[idx].get("folder_path", "")
        if folder and os.path.exists(folder):
            os.startfile(folder)

    def on_prev_template(self):
        if not self.excel_posts:
            return
        self.preview_tpl_idx = (self.preview_tpl_idx - 1) % len(self.excel_posts)
        self.update_preview_card()

    def on_next_template(self):
        if not self.excel_posts:
            return
        self.preview_tpl_idx = (self.preview_tpl_idx + 1) % len(self.excel_posts)
        self.update_preview_card()

    def load_campaign_templates(self):
        excel_path = get_configured_excel_path(self.db)
        if hasattr(self, "txt_excel_path"):
            self.txt_excel_path.setText(excel_path)

        if not excel_path or not os.path.exists(excel_path):
            self.excel_posts = []
            self.lbl_excel_badge.setText("0 Mẫu sẵn sàng")
            self.update_preview_card()
            return

        try:
            self.excel_posts = load_posts_from_excel(excel_path)
        except Exception:
            self.excel_posts = []

        self.lbl_excel_badge.setText(f"{len(self.excel_posts)} Mẫu sẵn sàng")
        self.lbl_content_title.setText(f"Threads ({len(self.excel_posts)} Mẫu Excel)")
        self.update_preview_card()

    def update_preview_card(self):
        acc_txt = self.combo_accounts.currentText() or "Tài khoản Threads"
        self.lbl_preview_author.setText(acc_txt.split("(")[0].strip() if "(" in acc_txt else acc_txt)

        if not self.excel_posts:
            self.lbl_preview_title.setText("Xem Trước Bài Viết (Chưa có mẫu)")
            self.lbl_tpl_counter.setText("0 / 0")
            self.txt_content.setPlainText("⚠️ Chưa có mẫu bài viết nào trong file Excel.")
            self.lbl_media_count.setText("Đường dẫn ảnh: (Trống)")
            return

        if self.preview_tpl_idx >= len(self.excel_posts):
            self.preview_tpl_idx = 0

        post = self.excel_posts[self.preview_tpl_idx]
        idx_1 = self.preview_tpl_idx + 1
        self.lbl_preview_title.setText(f"Xem Trước Bài Viết (Mẫu #{idx_1})")
        self.lbl_tpl_counter.setText(f"{idx_1} / {len(self.excel_posts)}")
        self.txt_content.setPlainText(post.get("content", ""))
        self.selected_media_paths = list(post.get("media_paths") or [])
        folder = post.get("folder_path") or ""
        cnt = len(post.get("raw_media_paths") or [])
        self.lbl_media_count.setText(f"Đường dẫn ảnh: {folder} ({cnt} ảnh)")

    def on_preview_spintax(self):
        text = self.txt_content.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Thông Báo", "Chưa có nội dung mẫu để xem thử biến thể!")
            return
        parsed = SpintaxParser.parse(text)
        QMessageBox.information(self, "Xem Thử Biến Thể Bài Viết (Spintax Preview)", parsed)

    def on_mode_toggled(self):
        self.comment_widget.setVisible(self.rad_comment.isChecked())
        self._update_tile_styles()

    def on_log_table_double_clicked(self, row: int, col: int):
        item = self.log_table.item(row, 2)
        if item:
            text = item.text().strip()
            if text.startswith("http"):
                webbrowser.open(text)

    def add_log_row(self, ts: str, action: str, target: str, status: str, msg: str):
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)

        ts_item = QTableWidgetItem(ts)
        ts_item.setForeground(QColor("#64748b"))
        self.log_table.setItem(row, 0, ts_item)

        act_item = QTableWidgetItem(action)
        act_item.setForeground(QColor("#f8fafc"))
        font_bold = act_item.font()
        font_bold.setBold(True)
        act_item.setFont(font_bold)
        self.log_table.setItem(row, 1, act_item)

        target_item = QTableWidgetItem(target)
        if target.startswith("http"):
            target_item.setForeground(QColor("#60a5fa"))
            target_item.setToolTip("Nhấn để mở liên kết")
        else:
            target_item.setForeground(QColor("#94a3b8"))
        self.log_table.setItem(row, 2, target_item)

        if status == "SUCCESS":
            self.success_post_count += 1
            self.lbl_success_counter.setText(f"●  Đã đăng {self.success_post_count} bài thành công")
            s_item = QTableWidgetItem("Thành công")
            s_item.setForeground(QColor("#10b981"))
        elif status == "RUNNING":
            s_item = QTableWidgetItem("Đang xử lý")
            s_item.setForeground(QColor("#38bdf8"))
        else:
            s_item = QTableWidgetItem(status)
            s_item.setForeground(QColor("#ef4444"))
        s_item.setFont(font_bold)
        self.log_table.setItem(row, 3, s_item)

        self.log_table.setItem(row, 4, QTableWidgetItem(msg))
        self.log_table.scrollToBottom()

    def update_progress(self, cur: int, total: int):
        if total > 0:
            pct = int((cur / total) * 100)
            self.progress_bar.setValue(pct)
            self.lbl_progress_pct.setText(f"{pct}% ({cur}/{total})")

    def on_start(self):
        acc_uid = self.combo_accounts.currentData()
        if not acc_uid:
            QMessageBox.warning(self, "Cảnh Báo", "Vui lòng chọn tài khoản Threads!")
            return

        self.load_campaign_templates()
        if not self.excel_posts:
            excel_path = self.txt_excel_path.text().strip()
            QMessageBox.warning(
                self,
                "Chưa Có Mẫu Bài Viết Excel",
                f"Không tìm thấy mẫu bài viết nào trong file Excel:\n{excel_path}\n\n"
                "Vui lòng chọn đúng file Excel (.xlsx) có Cột A là Nội dung, Cột B là Folder chứa hình ảnh!"
            )
            return

        mode = "POST" if self.rad_post.isChecked() else "COMMENT"
        target_urls = []
        if mode == "COMMENT":
            raw_urls = self.txt_target_urls.toPlainText().strip().splitlines()
            target_urls = [u.strip() for u in raw_urls if u.strip().startswith("http")]

        first_content = self.excel_posts[0].get("content", "")
        first_media = self.excel_posts[0].get("media_paths", [])
        loop_forever = self.chk_loop_forever.isChecked()

        self.db.clear_threads_logs()
        self.log_table.setRowCount(0)
        self.success_post_count = 0
        self.lbl_success_counter.setText("●  Đã đăng 0 bài thành công")
        self.progress_bar.setValue(0)
        self.lbl_progress_pct.setText("0% (Đang chạy...)")

        anti_config = AntiSpamConfig(
            min_delay_sec=self.spin_delay_min.value(),
            max_delay_sec=self.spin_delay_max.value(),
            rest_after_posts=self.spin_rest_after.value(),
            rest_duration_min=self.spin_rest_min.value(),
            randomize_media=self.chk_shuffle_media.isChecked(),
            add_unique_hash=self.chk_hash.isChecked()
        )

        headless = bool(self.combo_browser_mode.currentData())

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)

        self.worker = ThreadsActionWorker(
            db=self.db,
            account_uid=acc_uid,
            action_mode=mode,
            content_text=first_content,
            media_paths=first_media,
            target_urls=target_urls,
            anti_config=anti_config,
            headless=headless,
            excel_posts=list(self.excel_posts),
            loop_forever=loop_forever,
            min_likes=self.spin_min_likes.value() if mode == "COMMENT" else 0,
            human_simulation=self.chk_human_sim.isChecked()
        )
        self.worker.log_signal.connect(self.add_log_row)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(self.on_worker_finished)
        self.lbl_log_status.setText("Trạng thái: Đang chạy tác vụ Threads...")
        self.status_updated.emit("Đang khởi động tác vụ Threads...")
        self.worker.start()

    def on_pause(self):
        if not self.worker:
            return
        if self.worker.is_paused:
            self.worker.resume()
            self.btn_pause.setText("⏸   Tạm Dừng")
            self.status_updated.emit("Tiến trình Threads đang tiếp tục...")
        else:
            self.worker.pause()
            self.btn_pause.setText("▶   Tiếp Tục")
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
        self.btn_pause.setText("⏸   Tạm Dừng")
        self.progress_bar.setValue(100)
        self.lbl_progress_pct.setText("100% (Hoàn thành)")
        self.lbl_log_status.setText("Trạng thái: Hoàn thành")
        self.status_updated.emit("Tiến trình Threads đã hoàn tất.")
