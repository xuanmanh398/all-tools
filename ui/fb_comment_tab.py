import os
import time
import random
import asyncio
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QSpinBox, QCheckBox, QGroupBox, QMessageBox, QProgressBar, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QFrame,
    QFileDialog, QRadioButton, QButtonGroup, QSplitter, QScrollArea,
    QDialog, QDialogButtonBox
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QIcon

from core.database import Database
from core.anti_spam import AntiSpamManager, AntiSpamConfig
from core.spintax_parser import SpintaxParser
from core.fb_automation import FBAutomationEngine
from playwright.async_api import async_playwright


class FBCommentWorker(QThread):
    log_signal = Signal(str, str, str, str, str)  # (timestamp, account_name, target_url, status, message)
    progress_signal = Signal(int, int)  # (current, total)
    stat_signal = Signal(int, int, int)  # (total, success, failed)
    status_text_signal = Signal(str)
    finished_signal = Signal()

    def __init__(
        self,
        db: Database,
        accounts: List[Dict[str, Any]],
        targets: List[str],
        mode: str,
        content_template: str,
        media_paths: List[str],
        auto_like: bool,
        delay_min: int,
        delay_max: int,
        max_per_acc: int,
        headless: bool,
        keyword_posts_count: int = 10,
        group_posts_count: int = 3
    ):
        super().__init__()
        self.db = db
        self.accounts = accounts
        self.raw_targets = targets
        self.mode = mode  # "links", "group_posts", "keyword"
        self.content_template = content_template
        self.media_paths = media_paths
        self.auto_like = auto_like
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.max_per_acc = max_per_acc
        self.headless = headless
        self.keyword_posts_count = keyword_posts_count
        self.group_posts_count = group_posts_count

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
            loop.run_until_complete(self._process_comments())
            loop.close()
        except Exception as e:
            self.log_signal.emit(time.strftime("%H:%M:%S"), "-", "-", "FAILED", f"Lỗi luồng comment: {str(e)}")
        finally:
            self.finished_signal.emit()

    async def _process_comments(self):
        if not self.accounts:
            self.log_signal.emit(time.strftime("%H:%M:%S"), "-", "-", "FAILED", "Chưa chọn tài khoản Facebook nào!")
            return

        engine = FBAutomationEngine()
        resolved_targets: List[str] = []

        # 1. Thu thập danh sách mục tiêu dựa theo chế độ chạy
        if self.mode == "links":
            resolved_targets = [t.strip() for t in self.raw_targets if t.strip()]

        elif self.mode == "group_posts" or self.mode == "keyword":
            # Cần mở 1 tài khoản để quét bài viết trước
            first_acc = self.accounts[0]
            cookies = engine.parse_cookie_string(first_acc["cookie"])
            self.status_text_signal.emit("Đang khởi tạo trình duyệt quét bài viết mục tiêu...")

            async with async_playwright() as p:
                try:
                    browser, context = await engine.create_context(
                        p, cookies, first_acc.get("proxy", ""), headless=self.headless, uid=first_acc.get("uid", "")
                    )
                    page = await context.new_page()

                    if self.mode == "group_posts":
                        for g_target in self.raw_targets:
                            if self.is_stopped:
                                break
                            g_url = g_target.strip()
                            if not g_url.startswith("http"):
                                g_url = f"https://www.facebook.com/groups/{g_url}"
                            
                            self.log_signal.emit(time.strftime("%H:%M:%S"), first_acc.get("name", "Nick"), g_url, "SCANNING", f"Đang quét {self.group_posts_count} bài viết mới trong nhóm...")
                            posts = await engine.scan_group_posts(page, g_url, limit=self.group_posts_count)
                            resolved_targets.extend(posts)

                    elif self.mode == "keyword":
                        for kw in self.raw_targets:
                            if self.is_stopped:
                                break
                            kw_text = kw.strip()
                            if kw_text:
                                self.log_signal.emit(time.strftime("%H:%M:%S"), first_acc.get("name", "Nick"), kw_text, "SCANNING", f"Đang tìm {self.keyword_posts_count} bài viết theo từ khóa '{kw_text}'...")
                                posts = await engine.search_posts_by_keyword(page, kw_text, limit=self.keyword_posts_count)
                                resolved_targets.extend(posts)

                    await context.close()
                    await browser.close()
                except Exception as se:
                    self.log_signal.emit(time.strftime("%H:%M:%S"), "-", "-", "WARNING", f"Lỗi khi quét mục tiêu: {str(se)}")

        # Loại bỏ trùng lặp
        unique_targets = []
        for t in resolved_targets:
            if t not in unique_targets:
                unique_targets.append(t)

        total_targets = len(unique_targets)
        if total_targets == 0:
            self.log_signal.emit(time.strftime("%H:%M:%S"), "-", "-", "FAILED", "Không tìm thấy bài viết mục tiêu nào để bình luận!")
            self.stat_signal.emit(0, 0, 0)
            return

        self.log_signal.emit(time.strftime("%H:%M:%S"), "-", "-", "INFO", f"Bắt đầu chiến dịch comment: Tổng cộng {total_targets} bài viết.")
        self.progress_signal.emit(0, total_targets)
        self.stat_signal.emit(total_targets, 0, 0)

        success_count = 0
        fail_count = 0

        # Bộ đếm số lần comment của từng tài khoản
        acc_counter = {a["uid"]: 0 for a in self.accounts}
        acc_index = 0

        async with async_playwright() as p:
            current_browser = None
            current_context = None
            current_page = None
            current_uid = None

            for idx, target in enumerate(unique_targets, 1):
                if self.is_stopped:
                    self.log_signal.emit(time.strftime("%H:%M:%S"), "-", "-", "SKIPPED", "Chiến dịch đã bị người dùng dừng lại.")
                    break

                while self.is_paused:
                    self.status_text_signal.emit("Đang tạm dừng chiến dịch comment...")
                    await asyncio.sleep(1)
                    if self.is_stopped:
                        break

                if self.is_stopped:
                    break

                # Chọn tài khoản luân phiên
                attempts = 0
                selected_acc = None
                while attempts < len(self.accounts):
                    candidate = self.accounts[acc_index % len(self.accounts)]
                    acc_index += 1
                    attempts += 1
                    if acc_counter[candidate["uid"]] < self.max_per_acc:
                        selected_acc = candidate
                        break

                if not selected_acc:
                    self.log_signal.emit(time.strftime("%H:%M:%S"), "-", "-", "INFO", "Tất cả tài khoản đều đã đạt giới hạn comment tối đa!")
                    break

                acc_uid = selected_acc["uid"]
                acc_name = selected_acc.get("name") or acc_uid

                # Nếu đổi tài khoản, khởi tạo lại browser context mới
                if current_uid != acc_uid:
                    if current_context:
                        try:
                            await current_context.close()
                        except Exception:
                            pass
                    if current_browser:
                        try:
                            await current_browser.close()
                        except Exception:
                            pass

                    current_uid = acc_uid
                    cookies = engine.parse_cookie_string(selected_acc["cookie"])
                    self.status_text_signal.emit(f"Đang mở trình duyệt cho tài khoản: {acc_name}...")
                    try:
                        current_browser, current_context = await engine.create_context(
                            p, cookies, selected_acc.get("proxy", ""), headless=self.headless, uid=acc_uid
                        )
                        current_page = await current_context.new_page()
                    except Exception as be:
                        self.log_signal.emit(time.strftime("%H:%M:%S"), acc_name, target, "FAILED", f"Lỗi mở trình duyệt: {str(be)}")
                        fail_count += 1
                        self.stat_signal.emit(total_targets, success_count, fail_count)
                        continue

                # Thực hiện bình luận
                self.status_text_signal.emit(f"[{idx}/{total_targets}] Đang bình luận bài viết: {target[:40]}...")
                self.log_signal.emit(time.strftime("%H:%M:%S"), acc_name, target, "RUNNING", "Đang xử lý tương tác và bình luận...")

                anti_config = AntiSpamConfig(min_delay=self.delay_min, max_delay=self.delay_max)
                anti_mgr = AntiSpamManager(anti_config)

                result = await engine.comment_on_post(
                    page=current_page,
                    target_url=target,
                    content_template=self.content_template,
                    media_paths=self.media_paths,
                    auto_like=self.auto_like,
                    anti_spam=anti_mgr,
                    cookie_str=selected_acc["cookie"]
                )

                if result.get("success"):
                    success_count += 1
                    acc_counter[acc_uid] += 1
                    cmt_text = result.get("content", self.content_template)[:60]
                    self.log_signal.emit(time.strftime("%H:%M:%S"), acc_name, target, "SUCCESS", f"Bình luận thành công: \"{cmt_text}\"")
                    self.db.add_comment_log(acc_uid, acc_name, target, cmt_text, "SUCCESS", "Thành công")
                else:
                    fail_count += 1
                    err_msg = result.get("message", "Thất bại")
                    self.log_signal.emit(time.strftime("%H:%M:%S"), acc_name, target, "FAILED", err_msg)
                    self.db.add_comment_log(acc_uid, acc_name, target, self.content_template[:60], "FAILED", err_msg)

                self.progress_signal.emit(idx, total_targets)
                self.stat_signal.emit(total_targets, success_count, fail_count)

                # Giãn cách nghỉ (Delay ngẫu nhiên) để chống checkpoint
                if idx < total_targets and not self.is_stopped:
                    delay_seconds = random.randint(self.delay_min, self.delay_max)
                    for remain in range(delay_seconds, 0, -1):
                        if self.is_stopped:
                            break
                        self.status_text_signal.emit(f"Đang chờ {remain}s trước bài tiếp theo (Chống Spam)...")
                        await asyncio.sleep(1)

            # Dọn dẹp trình duyệt khi xong
            if current_context:
                try:
                    await current_context.close()
                except Exception:
                    pass
            if current_browser:
                try:
                    await current_browser.close()
                except Exception:
                    pass

        self.status_text_signal.emit(f"Hoàn thành: {success_count} thành công, {fail_count} thất bại.")
        self.log_signal.emit(time.strftime("%H:%M:%S"), "-", "-", "FINISHED", f"Chiến dịch kết thúc: Thành công {success_count}/{total_targets}.")


class FBCommentTab(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.worker: Optional[FBCommentWorker] = None
        self.attached_media_paths: List[str] = []
        self.init_ui()
        self.load_accounts()
        self.load_groups()
        self.load_templates()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(10)

        # -------------------------------------------------------------
        # 1. HEADER BANNER PHONG CÁCH TOOL CHUYÊN NGHIỆP
        # -------------------------------------------------------------
        header_card = QFrame()
        header_card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #111827, stop:1 #1f2937);
                border: 1px solid #374151;
                border-radius: 8px;
                padding: 10px 14px;
            }
        """)
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(4, 2, 4, 2)

        lbl_icon = QLabel("💬")
        lbl_icon.setStyleSheet("font-size: 24px; border: none; background: transparent;")
        h_layout.addWidget(lbl_icon)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(2)
        lbl_title = QLabel("TỰ ĐỘNG BÌNH LUẬN FACEBOOK (AUTO COMMENT)")
        lbl_title.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: bold; border: none; background: transparent;")
        title_vbox.addWidget(lbl_title)

        lbl_desc = QLabel("Tự động like và seeding bình luận theo Link/UID bài viết, bài viết trong Nhóm hoặc Từ khóa tìm kiếm. Hỗ trợ Spintax & chống checkpoint.")
        lbl_desc.setStyleSheet("color: #9ca3af; font-size: 11px; border: none; background: transparent;")
        title_vbox.addWidget(lbl_desc)
        h_layout.addLayout(title_vbox, 1)

        main_layout.addWidget(header_card)

        # -------------------------------------------------------------
        # 2. KHU VỰC CHÍNH: SPLITTER 2 CỘT (CẤU HÌNH & THỰC THI)
        # -------------------------------------------------------------
        splitter = QSplitter(Qt.Horizontal)

        # =============================================================
        # CỘT TRÁI: CẤU HÌNH MỤC TIÊU & NỘI DUNG
        # =============================================================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(10)

        # BOX 1: MỤC TIÊU BÌNH LUẬN
        target_group = QGroupBox("🎯 1. CHỌN MỤC TIÊU BÌNH LUẬN")
        tg_layout = QVBoxLayout(target_group)
        tg_layout.setSpacing(8)

        mode_row = QHBoxLayout()
        self.rb_mode_links = QRadioButton("🔗 Theo Link / ID bài viết")
        self.rb_mode_groups = QRadioButton("👥 Bài viết trong Nhóm")
        self.rb_mode_keyword = QRadioButton("🔍 Theo Từ khóa tìm kiếm")
        self.rb_mode_links.setChecked(True)

        self.btn_group_mode = QButtonGroup(self)
        self.btn_group_mode.addButton(self.rb_mode_links, 1)
        self.btn_group_mode.addButton(self.rb_mode_groups, 2)
        self.btn_group_mode.addButton(self.rb_mode_keyword, 3)
        self.btn_group_mode.idClicked.connect(self.on_mode_changed)

        mode_row.addWidget(self.rb_mode_links)
        mode_row.addWidget(self.rb_mode_groups)
        mode_row.addWidget(self.rb_mode_keyword)
        tg_layout.addLayout(mode_row)

        # Sub-container for Group mode
        self.group_mode_box = QWidget()
        gmb_layout = QHBoxLayout(self.group_mode_box)
        gmb_layout.setContentsMargins(0, 2, 0, 2)
        gmb_layout.addWidget(QLabel("Chọn nhóm:"))
        self.combo_groups = QComboBox()
        self.combo_groups.setMinimumWidth(220)
        gmb_layout.addWidget(self.combo_groups, 1)
        gmb_layout.addWidget(QLabel("Số bài/nhóm:"))
        self.spin_group_posts = QSpinBox()
        self.spin_group_posts.setRange(1, 20)
        self.spin_group_posts.setValue(3)
        gmb_layout.addWidget(self.spin_group_posts)
        self.group_mode_box.setVisible(False)
        tg_layout.addWidget(self.group_mode_box)

        # Sub-container for Keyword mode
        self.keyword_mode_box = QWidget()
        kmb_layout = QHBoxLayout(self.keyword_mode_box)
        kmb_layout.setContentsMargins(0, 2, 0, 2)
        kmb_layout.addWidget(QLabel("Từ khóa:"))
        self.txt_keyword = QLineEdit()
        self.txt_keyword.setPlaceholderText("Ví dụ: thời trang, bán hàng online...")
        kmb_layout.addWidget(self.txt_keyword, 1)
        kmb_layout.addWidget(QLabel("Số bài cần cmt:"))
        self.spin_keyword_posts = QSpinBox()
        self.spin_keyword_posts.setRange(1, 50)
        self.spin_keyword_posts.setValue(10)
        kmb_layout.addWidget(self.spin_keyword_posts)
        self.keyword_mode_box.setVisible(False)
        tg_layout.addWidget(self.keyword_mode_box)

        # Text area cho danh sách Link / UID
        self.lbl_target_hint = QLabel("Danh sách Link hoặc ID bài viết (mỗi dòng 1 bài):")
        self.lbl_target_hint.setStyleSheet("color: #94a3b8; font-size: 11px;")
        tg_layout.addWidget(self.lbl_target_hint)

        self.txt_targets = QTextEdit()
        self.txt_targets.setPlaceholderText(
            "https://www.facebook.com/1000123456789/posts/123456789\n"
            "https://www.facebook.com/groups/12345678/posts/87654321\n"
            "1000123456789_9876543210\n"
            "(Hoặc dán trực tiếp danh sách link/ID bài viết vào đây)"
        )
        self.txt_targets.setFixedHeight(110)
        self.txt_targets.textChanged.connect(self.update_target_count)
        tg_layout.addWidget(self.txt_targets)

        target_actions = QHBoxLayout()
        btn_import_txt = QPushButton("📂 Mở file .txt")
        btn_import_txt.clicked.connect(self.import_targets_from_txt)
        btn_clear_targets = QPushButton("🧹 Xóa hết")
        btn_clear_targets.clicked.connect(lambda: self.txt_targets.clear())
        self.lbl_target_count = QLabel("Tổng số: 0 mục tiêu")
        self.lbl_target_count.setStyleSheet("color: #6366f1; font-weight: bold; font-size: 12px;")

        target_actions.addWidget(btn_import_txt)
        target_actions.addWidget(btn_clear_targets)
        target_actions.addStretch()
        target_actions.addWidget(self.lbl_target_count)
        tg_layout.addLayout(target_actions)

        left_layout.addWidget(target_group)

        # BOX 2: NỘI DUNG BÌNH LUẬN (SPINTAX & ẢNH)
        content_group = QGroupBox("✍️ 2. NỘI DUNG BÌNH LUẬN (SPINTAX & ẢNH)")
        cg_layout = QVBoxLayout(content_group)
        cg_layout.setSpacing(6)

        self.txt_content = QTextEdit()
        self.txt_content.setPlaceholderText(
            "{Chào bạn|Xin chào|Hello shop}! {Sản phẩm này giá sao vậy ạ?|Inbox tư vấn giúp mình nhé|Cho mình xin thông tin chi tiết với ạ!}"
        )
        self.txt_content.setFixedHeight(95)
        cg_layout.addWidget(self.txt_content)

        # Image preview tag
        self.lbl_image_attached = QLabel("Chưa chọn hình ảnh đính kèm")
        self.lbl_image_attached.setStyleSheet("color: #64748b; font-size: 11px;")
        cg_layout.addWidget(self.lbl_image_attached)

        # Utility buttons row
        tools_row = QHBoxLayout()
        btn_spintax_sample = QPushButton("🎲 Mẫu Spintax")
        btn_spintax_sample.setToolTip("Chèn ví dụ cú pháp xoay nội dung {A|B|C}")
        btn_spintax_sample.clicked.connect(self.insert_spintax_sample)

        btn_emoji = QPushButton("😀 Emoji")
        btn_emoji.clicked.connect(self.insert_emoji)

        btn_attach_img = QPushButton("🖼️ Chọn ảnh")
        btn_attach_img.clicked.connect(self.select_comment_image)

        btn_remove_img = QPushButton("❌ Bỏ ảnh")
        btn_remove_img.clicked.connect(self.clear_comment_image)

        btn_test_spintax = QPushButton("👁️ Xem thử")
        btn_test_spintax.setToolTip("Xem thử biến thể ngẫu nhiên khi bình luận")
        btn_test_spintax.clicked.connect(self.test_spintax_preview)

        tools_row.addWidget(btn_spintax_sample)
        tools_row.addWidget(btn_emoji)
        tools_row.addWidget(btn_attach_img)
        tools_row.addWidget(btn_remove_img)
        tools_row.addWidget(btn_test_spintax)
        cg_layout.addLayout(tools_row)

        left_layout.addWidget(content_group)

        # BOX 3: CẤU HÌNH AN TOÀN & CHỐNG CHẶN (ANTI-BAN)
        safety_group = QGroupBox("🛡️ 3. CẤU HÌNH AN TOÀN & CHỐNG CHẶN")
        sg_layout = QVBoxLayout(safety_group)
        sg_layout.setSpacing(6)

        self.chk_auto_like = QCheckBox("👍 Tự động Thích (Like) bài viết trước khi bình luận (Tăng độ uy tín)")
        self.chk_auto_like.setChecked(True)
        sg_layout.addWidget(self.chk_auto_like)

        row_delays = QHBoxLayout()
        row_delays.addWidget(QLabel("Giãn cách nghỉ giữa 2 lần:"))
        self.spin_delay_min = QSpinBox()
        self.spin_delay_min.setRange(5, 300)
        self.spin_delay_min.setValue(15)
        self.spin_delay_min.setSuffix(" giây")

        self.spin_delay_max = QSpinBox()
        self.spin_delay_max.setRange(5, 300)
        self.spin_delay_max.setValue(30)
        self.spin_delay_max.setSuffix(" giây")

        row_delays.addWidget(self.spin_delay_min)
        row_delays.addWidget(QLabel("đến"))
        row_delays.addWidget(self.spin_delay_max)
        row_delays.addStretch()
        sg_layout.addLayout(row_delays)

        row_limits = QHBoxLayout()
        row_limits.addWidget(QLabel("Giới hạn mỗi tài khoản:"))
        self.spin_max_per_acc = QSpinBox()
        self.spin_max_per_acc.setRange(1, 200)
        self.spin_max_per_acc.setValue(20)
        self.spin_max_per_acc.setSuffix(" lần cmt")
        row_limits.addWidget(self.spin_max_per_acc)

        row_limits.addSpacing(15)
        self.chk_headless = QCheckBox("👁️ Mở trực tiếp cửa sổ trình duyệt (để quan sát tool cmt)")
        self.chk_headless.setChecked(True)
        row_limits.addWidget(self.chk_headless)
        row_limits.addStretch()
        sg_layout.addLayout(row_limits)

        left_layout.addWidget(safety_group)
        splitter.addWidget(left_widget)

        # =============================================================
        # CỘT PHẢI: CHỌN TÀI KHOẢN & BẢNG ĐIỀU KHIỂN & NHẬT KÝ
        # =============================================================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(10)

        # BOX 1: CHỌN TÀI KHOẢN FACEBOOK
        acc_group = QGroupBox("👥 TÀI KHOẢN FACEBOOK THAM GIA BÌNH LUẬN")
        ag_layout = QVBoxLayout(acc_group)
        ag_layout.setSpacing(6)

        self.table_accounts = QTableWidget()
        self.table_accounts.setColumnCount(4)
        self.table_accounts.setHorizontalHeaderLabels(["Chọn", "UID Facebook", "Tên Tài Khoản", "Proxy"])
        self.table_accounts.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_accounts.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_accounts.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_accounts.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_accounts.setFixedHeight(120)
        ag_layout.addWidget(self.table_accounts)

        acc_btn_row = QHBoxLayout()
        btn_sel_all = QPushButton("✅ Chọn tất cả")
        btn_sel_all.clicked.connect(self.select_all_accounts)
        btn_desel_all = QPushButton("◻️ Bỏ chọn")
        btn_desel_all.clicked.connect(self.deselect_all_accounts)
        btn_reload_acc = QPushButton("🔄 Làm mới")
        btn_reload_acc.clicked.connect(self.load_accounts)

        acc_btn_row.addWidget(btn_sel_all)
        acc_btn_row.addWidget(btn_desel_all)
        acc_btn_row.addWidget(btn_reload_acc)
        acc_btn_row.addStretch()
        ag_layout.addLayout(acc_btn_row)

        right_layout.addWidget(acc_group)

        # BOX 2: CÁC NÚT ĐIỀU KHIỂN LỚN (ACTION BUTTONS)
        action_bar = QHBoxLayout()
        self.btn_start = QPushButton("▶️ BẮT ĐẦU CHẠY COMMENT")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setFixedHeight(44)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669);
                color: #ffffff;
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 8px;
                padding: 0 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:1 #047857);
            }
        """)
        self.btn_start.clicked.connect(self.start_commenting)

        self.btn_pause = QPushButton("⏸️ TẠM DỪNG")
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setFixedHeight(44)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet("""
            QPushButton {
                background: #f59e0b;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 8px;
                padding: 0 16px;
            }
            QPushButton:hover {
                background: #d97706;
            }
        """)
        self.btn_pause.clicked.connect(self.toggle_pause)

        self.btn_stop = QPushButton("⏹️ DỪNG LẠI")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setFixedHeight(44)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background: #ef4444;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 8px;
                padding: 0 16px;
            }
            QPushButton:hover {
                background: #dc2626;
            }
        """)
        self.btn_stop.clicked.connect(self.stop_commenting)

        action_bar.addWidget(self.btn_start, 2)
        action_bar.addWidget(self.btn_pause, 1)
        action_bar.addWidget(self.btn_stop, 1)
        right_layout.addLayout(action_bar)

        # BOX 3: THỐNG KÊ & TIẾN ĐỘ THỜI GIAN THỰC
        stats_box = QFrame()
        stats_box.setStyleSheet("""
            QFrame {
                background-color: #111625;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 6px 12px;
            }
        """)
        sb_layout = QHBoxLayout(stats_box)
        sb_layout.setContentsMargins(6, 4, 6, 4)

        self.lbl_stat_total = QLabel("🎯 Tổng số: 0")
        self.lbl_stat_total.setStyleSheet("color: #cbd5e1; font-weight: bold;")
        self.lbl_stat_success = QLabel("✅ Thành công: 0")
        self.lbl_stat_success.setStyleSheet("color: #10b981; font-weight: bold;")
        self.lbl_stat_failed = QLabel("❌ Thất bại: 0")
        self.lbl_stat_failed.setStyleSheet("color: #ef4444; font-weight: bold;")
        self.lbl_stat_status = QLabel("Trạng thái: Sẵn sàng")
        self.lbl_stat_status.setStyleSheet("color: #94a3b8; font-style: italic;")

        sb_layout.addWidget(self.lbl_stat_total)
        sb_layout.addWidget(self.lbl_stat_success)
        sb_layout.addWidget(self.lbl_stat_failed)
        sb_layout.addStretch()
        sb_layout.addWidget(self.lbl_stat_status)
        right_layout.addWidget(stats_box)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1e293b;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #3b82f6);
                border-radius: 4px;
            }
        """)
        right_layout.addWidget(self.progress_bar)

        # BOX 4: BẢNG NHẬT KÝ THỰC THI THỜI GIAN THỰC
        self.table_logs = QTableWidget()
        self.table_logs.setColumnCount(5)
        self.table_logs.setHorizontalHeaderLabels(["Giờ", "Tài Khoản", "Mục Tiêu", "Trạng Thái", "Chi Tiết"])
        self.table_logs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_logs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_logs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_logs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_logs.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        right_layout.addWidget(self.table_logs, 1)

        log_actions = QHBoxLayout()
        btn_clear_logs = QPushButton("🧹 Xóa nhật ký")
        btn_clear_logs.clicked.connect(self.clear_logs)
        btn_export_logs = QPushButton("📤 Xuất file kết quả (.txt)")
        btn_export_logs.clicked.connect(self.export_logs)

        log_actions.addWidget(btn_clear_logs)
        log_actions.addWidget(btn_export_logs)
        log_actions.addStretch()
        right_layout.addLayout(log_actions)

        splitter.addWidget(right_widget)
        splitter.setSizes([480, 520])

        main_layout.addWidget(splitter, 1)

    # -------------------------------------------------------------
    # LOGIC XỬ LÝ SỰ KIỆN GIAO DIỆN
    # -------------------------------------------------------------
    def on_mode_changed(self, mode_id: int):
        self.group_mode_box.setVisible(mode_id == 2)
        self.keyword_mode_box.setVisible(mode_id == 3)
        if mode_id == 1:
            self.lbl_target_hint.setText("Danh sách Link hoặc ID bài viết (mỗi dòng 1 bài):")
            self.txt_targets.setPlaceholderText("Dán danh sách link bài viết Facebook hoặc ID bài viết vào đây...")
        elif mode_id == 2:
            self.lbl_target_hint.setText("Hoặc nhập bổ sung Link/ID các Nhóm Facebook khác (mỗi dòng 1 nhóm):")
            self.txt_targets.setPlaceholderText("https://www.facebook.com/groups/12345678\nhttps://www.facebook.com/groups/hoi-kinh-doanh")
        elif mode_id == 3:
            self.lbl_target_hint.setText("Hoặc nhập danh sách nhiều Từ khóa tìm kiếm bài viết (mỗi dòng 1 từ):")
            self.txt_targets.setPlaceholderText("mua bán nhà đất\nthời trang nữ\ntuyển dụng hcm")
        self.update_target_count()

    def update_target_count(self):
        text = self.txt_targets.toPlainText().strip()
        lines = [l for l in text.split("\n") if l.strip()]
        self.lbl_target_count.setText(f"Tổng số: {len(lines)} mục tiêu")

    def import_targets_from_txt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file danh sách mục tiêu", "", "Text Files (*.txt);;All Files (*)")
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                self.txt_targets.setPlainText(content)
                self.update_target_count()
            except Exception as e:
                QMessageBox.warning(self, "Lỗi đọc file", f"Không thể đọc file: {str(e)}")

    def insert_spintax_sample(self):
        sample = "{Chào bạn|Xin chào|Hello bạn}! {Sản phẩm bên mình còn không ạ?|Cho mình xin thêm thông tin và báo giá nhé|Check inbox giúp mình với ạ!}"
        current = self.txt_content.toPlainText()
        if current.strip():
            self.txt_content.setPlainText(current + "\n" + sample)
        else:
            self.txt_content.setPlainText(sample)

    def insert_emoji(self):
        emojis = ["❤️", "🔥", "👍", "👏", "✨", "💯", "🎉", "😍", "🎯", "🌟", "🌸", "💐"]
        dialog = QDialog(self)
        dialog.setWindowTitle("Chọn biểu tượng Emoji")
        d_layout = QVBoxLayout(dialog)
        row = QHBoxLayout()
        for idx, em in enumerate(emojis):
            btn = QPushButton(em)
            btn.setFixedSize(36, 36)
            btn.setStyleSheet("font-size: 16px;")
            btn.clicked.connect(lambda _, e=em: (self.txt_content.insertPlainText(e), dialog.accept()))
            row.addWidget(btn)
            if (idx + 1) % 6 == 0:
                d_layout.addLayout(row)
                row = QHBoxLayout()
        if row.count() > 0:
            d_layout.addLayout(row)
        dialog.exec()

    def select_comment_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh đính kèm bình luận", "", "Image Files (*.jpg *.jpeg *.png *.webp *.gif)")
        if path and os.path.exists(path):
            self.attached_media_paths = [path]
            self.lbl_image_attached.setText(f"🖼️ Đã chọn: {os.path.basename(path)}")
            self.lbl_image_attached.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px;")

    def clear_comment_image(self):
        self.attached_media_paths = []
        self.lbl_image_attached.setText("Chưa chọn hình ảnh đính kèm")
        self.lbl_image_attached.setStyleSheet("color: #64748b; font-size: 11px;")

    def test_spintax_preview(self):
        content = self.txt_content.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "Xem thử", "Vui lòng nhập nội dung Spintax trước khi xem thử.")
            return
        parsed = SpintaxParser.parse(content)
        QMessageBox.information(self, "Xem thử nội dung ngẫu nhiên", f"🎲 KẾT QUẢ SINH NGẪU NHIÊN:\n\n{parsed}")

    def load_accounts(self):
        accounts = self.db.get_accounts()
        self.table_accounts.setRowCount(0)
        for acc in accounts:
            row = self.table_accounts.rowCount()
            self.table_accounts.insertRow(row)

            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked)
            self.table_accounts.setItem(row, 0, chk_item)

            self.table_accounts.setItem(row, 1, QTableWidgetItem(acc["uid"]))
            self.table_accounts.setItem(row, 2, QTableWidgetItem(acc.get("name") or acc["uid"]))
            self.table_accounts.setItem(row, 3, QTableWidgetItem(acc.get("proxy") or "-"))

    def select_all_accounts(self):
        for r in range(self.table_accounts.rowCount()):
            item = self.table_accounts.item(r, 0)
            if item:
                item.setCheckState(Qt.Checked)

    def deselect_all_accounts(self):
        for r in range(self.table_accounts.rowCount()):
            item = self.table_accounts.item(r, 0)
            if item:
                item.setCheckState(Qt.Unchecked)

    def load_groups(self):
        self.combo_groups.clear()
        self.combo_groups.addItem("-- Chọn nhóm từ CSDL --", "")
        groups = self.db.get_groups()
        seen = set()
        for g in groups:
            gid = g.get("group_id") or g.get("group_url")
            if gid and gid not in seen:
                seen.add(gid)
                gname = g.get("group_name") or gid
                self.combo_groups.addItem(f"👥 {gname}", g.get("group_url") or gid)

    def load_templates(self):
        templates = self.db.get_comment_campaigns()
        if templates and not self.txt_content.toPlainText().strip():
            self.txt_content.setPlainText(templates[0]["content"])

    # -------------------------------------------------------------
    # BẮT ĐẦU / TẠM DỪNG / DỪNG TIẾN TRÌNH COMMENT
    # -------------------------------------------------------------
    def start_commenting(self):
        # 1. Thu thập danh sách tài khoản được chọn
        selected_accounts = []
        all_accounts = self.db.get_accounts()
        acc_dict = {a["uid"]: a for a in all_accounts}

        for r in range(self.table_accounts.rowCount()):
            item = self.table_accounts.item(r, 0)
            if item and item.checkState() == Qt.Checked:
                uid_item = self.table_accounts.item(r, 1)
                if uid_item and uid_item.text() in acc_dict:
                    selected_accounts.append(acc_dict[uid_item.text()])

        if not selected_accounts:
            QMessageBox.warning(self, "Chưa chọn tài khoản", "Vui lòng tick chọn ít nhất một tài khoản Facebook để thực hiện bình luận!")
            return

        # 2. Thu thập mục tiêu
        mode_id = self.btn_group_mode.checkedId()
        targets = []
        mode_str = "links"

        if mode_id == 1:
            mode_str = "links"
            raw_text = self.txt_targets.toPlainText().strip()
            targets = [l.strip() for l in raw_text.split("\n") if l.strip()]
            if not targets:
                QMessageBox.warning(self, "Thiếu mục tiêu", "Vui lòng nhập danh sách link bài viết hoặc Post ID Facebook!")
                return

        elif mode_id == 2:
            mode_str = "group_posts"
            combo_val = self.combo_groups.currentData()
            if combo_val:
                targets.append(combo_val)
            raw_text = self.txt_targets.toPlainText().strip()
            if raw_text:
                targets.extend([l.strip() for l in raw_text.split("\n") if l.strip()])
            if not targets:
                QMessageBox.warning(self, "Thiếu nhóm mục tiêu", "Vui lòng chọn nhóm từ danh sách hoặc nhập Link nhóm!")
                return

        elif mode_id == 3:
            mode_str = "keyword"
            kw = self.txt_keyword.text().strip()
            if kw:
                targets.append(kw)
            raw_text = self.txt_targets.toPlainText().strip()
            if raw_text:
                targets.extend([l.strip() for l in raw_text.split("\n") if l.strip()])
            if not targets:
                QMessageBox.warning(self, "Thiếu từ khóa", "Vui lòng nhập từ khóa tìm kiếm bài viết Facebook!")
                return

        # 3. Thu thập nội dung
        content = self.txt_content.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Thiếu nội dung", "Vui lòng nhập nội dung bình luận (có thể dùng Spintax)!")
            return

        # Thiết lập UI khi đang chạy
        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("⏸️ TẠM DỪNG")
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)

        # Khởi chạy Worker Thread
        self.worker = FBCommentWorker(
            db=self.db,
            accounts=selected_accounts,
            targets=targets,
            mode=mode_str,
            content_template=content,
            media_paths=self.attached_media_paths,
            auto_like=self.chk_auto_like.isChecked(),
            delay_min=self.spin_delay_min.value(),
            delay_max=self.spin_delay_max.value(),
            max_per_acc=self.spin_max_per_acc.value(),
            headless=not self.chk_headless.isChecked(),
            keyword_posts_count=self.spin_keyword_posts.value(),
            group_posts_count=self.spin_group_posts.value()
        )

        self.worker.log_signal.connect(self.on_worker_log)
        self.worker.progress_signal.connect(self.on_worker_progress)
        self.worker.stat_signal.connect(self.on_worker_stat)
        self.worker.status_text_signal.connect(self.lbl_stat_status.setText)
        self.worker.finished_signal.connect(self.on_worker_finished)
        self.worker.start()

    def toggle_pause(self):
        if not self.worker:
            return
        if self.worker.is_paused:
            self.worker.resume()
            self.btn_pause.setText("⏸️ TẠM DỪNG")
            self.lbl_stat_status.setText("Trạng thái: Đang tiếp tục chạy...")
        else:
            self.worker.pause()
            self.btn_pause.setText("▶️ TIẾP TỤC")
            self.lbl_stat_status.setText("Trạng thái: Đang tạm dừng")

    def stop_commenting(self):
        if self.worker:
            self.worker.stop()
            self.lbl_stat_status.setText("Trạng thái: Đang dừng tiến trình...")

    def on_worker_log(self, timestamp: str, account_name: str, target: str, status: str, message: str):
        row = self.table_logs.rowCount()
        self.table_logs.insertRow(row)

        self.table_logs.setItem(row, 0, QTableWidgetItem(timestamp))
        self.table_logs.setItem(row, 1, QTableWidgetItem(account_name))

        # Rút ngắn hiển thị mục tiêu
        display_target = target if len(target) <= 35 else (target[:32] + "...")
        t_item = QTableWidgetItem(display_target)
        t_item.setToolTip(target)
        self.table_logs.setItem(row, 2, t_item)

        status_item = QTableWidgetItem()
        if status == "SUCCESS":
            status_item.setText("✅ Thành công")
            status_item.setForeground(QColor("#10b981"))
        elif status == "FAILED":
            status_item.setText("❌ Thất bại")
            status_item.setForeground(QColor("#ef4444"))
        elif status == "RUNNING" or status == "SCANNING":
            status_item.setText("⏳ Đang xử lý")
            status_item.setForeground(QColor("#f59e0b"))
        else:
            status_item.setText(f"ℹ️ {status}")
            status_item.setForeground(QColor("#94a3b8"))

        self.table_logs.setItem(row, 3, status_item)
        self.table_logs.setItem(row, 4, QTableWidgetItem(message))
        self.table_logs.scrollToBottom()

    def on_worker_progress(self, current: int, total: int):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)

    def on_worker_stat(self, total: int, success: int, failed: int):
        self.lbl_stat_total.setText(f"🎯 Tổng số: {total}")
        self.lbl_stat_success.setText(f"✅ Thành công: {success}")
        self.lbl_stat_failed.setText(f"❌ Thất bại: {failed}")

    def on_worker_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸️ TẠM DỪNG")
        self.btn_stop.setEnabled(False)
        self.worker = None

    def clear_logs(self):
        self.table_logs.setRowCount(0)
        self.lbl_stat_total.setText("🎯 Tổng số: 0")
        self.lbl_stat_success.setText("✅ Thành công: 0")
        self.lbl_stat_failed.setText("❌ Thất bại: 0")
        self.progress_bar.setValue(0)
        self.lbl_stat_status.setText("Trạng thái: Sẵn sàng")

    def export_logs(self):
        if self.table_logs.rowCount() == 0:
            QMessageBox.information(self, "Chưa có dữ liệu", "Không có nhật ký nào để xuất!")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Lưu báo cáo kết quả comment", "BaoCao_AutoComment.txt", "Text Files (*.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("=== BÁO CÁO KẾT QUẢ TỰ ĐỘNG BÌNH LUẬN FACEBOOK ===\n\n")
                    for r in range(self.table_logs.rowCount()):
                        time_str = self.table_logs.item(r, 0).text()
                        acc_str = self.table_logs.item(r, 1).text()
                        target_str = self.table_logs.item(r, 2).toolTip() or self.table_logs.item(r, 2).text()
                        st_str = self.table_logs.item(r, 3).text()
                        msg_str = self.table_logs.item(r, 4).text()
                        f.write(f"[{time_str}] | {acc_str} | {target_str} | {st_str} | {msg_str}\n")
                QMessageBox.information(self, "Thành công", f"Đã xuất báo cáo ra file:\n{path}")
            except Exception as e:
                QMessageBox.warning(self, "Lỗi xuất file", f"Không thể lưu file: {str(e)}")
