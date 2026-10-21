import asyncio
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QSpinBox, QCheckBox, QGroupBox, QMessageBox, QProgressBar, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QTimeEdit, QLineEdit, QFrame,
    QDialog
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QTime, QDateTime
from PySide6.QtGui import QFont, QColor
from core.database import Database
from core.anti_spam import AntiSpamManager, AntiSpamConfig
from core.fb_automation import FBAutomationEngine
from playwright.async_api import async_playwright

class PosterWorker(QThread):
    log_signal = Signal(str, str, str, str, str)  # (timestamp, profile_label, group_name, status, message)
    progress_signal = Signal(int, int)  # (current, total)
    status_text_signal = Signal(str)  # Short status for floating widget / tray
    finished_signal = Signal()

    def __init__(self, db: Database, account_uid: str, campaign_id: int, anti_config: AntiSpamConfig, headless: bool = True, post_as_page_name: str = "", category: str = "Tất cả lĩnh vực"):
        super().__init__()
        self.db = db
        self.account_uid = account_uid
        self.campaign_id = campaign_id
        self.anti_config = anti_config
        self.headless = headless
        self.post_as_page_name = post_as_page_name
        self.category = category
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
            loop.run_until_complete(self._process_posting())
            loop.close()
        except Exception as e:
            self.log_signal.emit(time.strftime("%H:%M:%S"), "-", "-", "FAILED", f"Lỗi tiến trình đăng bài: {str(e)}")
        finally:
            self.finished_signal.emit()

    async def _process_posting(self):
        profile_label = f"Fanpage: {self.post_as_page_name}" if self.post_as_page_name else "Nick cá nhân"

        # Lấy thông tin tài khoản
        accounts = self.db.get_accounts()
        target_acc = next((a for a in accounts if a["uid"] == self.account_uid), None)
        if not target_acc:
            self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", "FAILED", "Không tìm thấy tài khoản trong CSDL!")
            return

        # Lấy danh sách nhóm được chọn cho Profile/Fanpage này theo Lĩnh Vực
        pages = self.db.get_pages(self.account_uid)
        page_obj = next((p for p in pages if p["page_name"] == self.post_as_page_name), None)
        target_page_id = page_obj["page_id"] if page_obj else ""

        selected_groups = self.db.get_groups(account_uid=self.account_uid, page_id=target_page_id, category=self.category, only_selected=True)
        if not selected_groups:
            cat_desc = f" thuộc lĩnh vực '{self.category}'" if self.category not in ["Tất cả", "Tất cả lĩnh vực", ""] else ""
            self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", "FAILED", f"Không có nhóm nào được chọn{cat_desc}!")
            return

        # Lấy danh sách mẫu nội dung chiến dịch
        campaigns = self.db.get_campaigns()
        campaign_map = {c["id"]: c for c in campaigns}
        target_camp = campaign_map.get(self.campaign_id)
        if not target_camp and not campaigns:
            self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", "FAILED", "Không tìm thấy mẫu nội dung chiến dịch!")
            return

        anti_spam = AntiSpamManager(self.anti_config)
        engine = FBAutomationEngine()
        cookies = engine.parse_cookie_string(target_acc["cookie"])

        total_groups = len(selected_groups)
        self.progress_signal.emit(0, total_groups)
        self.status_text_signal.emit(f"Bắt đầu chiến dịch [{profile_label}]: 0/{total_groups} nhóm")

        async with async_playwright() as p:
            try:
                browser, context = await engine.create_context(p, cookies, target_acc.get("proxy", ""), headless=self.headless, uid=self.account_uid, page_id=target_page_id)
                page = await context.new_page()

                # Tự động chuyển danh tính sang Fanpage hoặc Nick cá nhân (chạy ngầm 100% không cần người dùng thao tác)
                page_url = page_obj.get("page_url", "") if page_obj else ""
                await engine.ensure_active_profile(
                    page=page,
                    uid=self.account_uid,
                    target_page_name=self.post_as_page_name,
                    target_page_id=target_page_id,
                    target_page_url=page_url,
                    logger_callback=lambda level, msg: self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", level, msg)
                )

                for index, group in enumerate(selected_groups, 1):
                    if self.is_stopped:
                        self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", "SKIPPED", "Tiến trình bị hủy bởi người dùng.")
                        break

                    while self.is_paused:
                        self.status_text_signal.emit(f"[{profile_label}] Đang tạm dừng...")
                        await asyncio.sleep(1)
                        if self.is_stopped:
                            break

                    if self.is_stopped:
                        break

                    g_name = group["group_name"]
                    g_url = group["group_url"]
                    g_cat = group.get("category", "Mặc định")

                    # Xác định bài đăng riêng gán cho nhóm (nếu có)
                    grp_camp_id = group.get("campaign_id") or 0
                    active_camp = campaign_map.get(grp_camp_id) or target_camp
                    if not active_camp and campaigns:
                        active_camp = campaigns[0]

                    camp_title = active_camp["title"] if active_camp else "Mẫu chung"

                    self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, f"{g_name} [{g_cat}]", "POSTING", f"Đang đăng bài '{camp_title}' ({index}/{total_groups})...")
                    self.status_text_signal.emit(f"[{profile_label}] Đăng bài '{camp_title}' ({index}/{total_groups}): {g_name}")

                    success = await engine.post_to_group(
                        page=page,
                        group_url=g_url,
                        content_template=active_camp["content"],
                        media_paths=active_camp["media_paths"],
                        anti_spam=anti_spam,
                        logger_callback=lambda level, msg: self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, g_name, level, msg),
                        post_as_page_name=self.post_as_page_name,
                        cookie_str=target_acc["cookie"]
                    )

                    if success:
                        self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, g_name, "SUCCESS", f"Đăng bài '{camp_title}' thành công!")
                    else:
                        self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, g_name, "FAILED", f"Đăng bài '{camp_title}' thất bại!")

                    self.progress_signal.emit(index, total_groups)

                    # Nghỉ chống Spam nếu chưa phải nhóm cuối cùng
                    if index < total_groups and not self.is_stopped:
                        delay_sec = anti_spam.get_random_delay()
                        self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", "WAITING", f"Nghỉ {delay_sec} giây trước khi đăng nhóm tiếp theo...")
                        for elapsed in range(delay_sec):
                            if self.is_stopped:
                                break
                            while self.is_paused:
                                await asyncio.sleep(1)
                                if self.is_stopped:
                                    break
                            await asyncio.sleep(1)

                        if anti_spam.should_rest() and not self.is_stopped:
                            rest_time = anti_spam.get_rest_duration_sec()
                            self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", "RESTING", f"Tạm nghỉ chống Spam trong {rest_time // 60} phút ({rest_time}s)...")
                            for elapsed in range(rest_time):
                                if self.is_stopped:
                                    break
                                while self.is_paused:
                                    await asyncio.sleep(1)
                                    if self.is_stopped:
                                        break
                                await asyncio.sleep(1)

                try:
                    await engine.safe_save_storage_state(context, self.account_uid, page_id=target_page_id)
                except Exception:
                    pass
                await context.close()
                await browser.close()

            except Exception as e:
                self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", "ERROR", f"Lỗi không xác định: {str(e)}")

        self.status_text_signal.emit(f"Hoàn thành tiến trình đăng bài cho [{profile_label}]!")


class GroupSelectionDialog(QDialog):
    def __init__(self, db: Database, account_uid: str, page_id: str, page_name: str, mode: str, category: str, parent=None):
        super().__init__(parent)
        self.db = db
        self.account_uid = account_uid
        self.page_id = page_id
        self.page_name = page_name
        self.mode = mode
        self.category = category

        profile_title = f"Fanpage '{page_name}'" if page_name else "Nick Cá Nhân"
        if mode == "ALL_PAGES":
            profile_title = "Tất Cả Fanpage"
        elif mode == "ALL_PROFILES":
            profile_title = "Nick Cá Nhân + Tất Cả Fanpage"

        self.setWindowTitle(f"Danh Sách Nhóm Mục Tiêu - {profile_title}")
        self.resize(880, 520)

        layout = QVBoxLayout(self)

        # Top Bar: Info + Search
        top_bar = QHBoxLayout()
        cat_desc = f" | Lĩnh vực: {category}" if category not in ["Tất cả", "Tất cả lĩnh vực", ""] else ""
        self.lbl_title = QLabel(f"📋 Mục tiêu đăng: <b>{profile_title}</b>{cat_desc}")
        self.lbl_title.setStyleSheet("font-size: 13px; color: #89b4fa;")
        top_bar.addWidget(self.lbl_title)

        top_bar.addSpacing(15)
        top_bar.addWidget(QLabel("🔍 Tìm kiếm:"))
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Lọc theo tên hoặc ID nhóm...")
        self.txt_search.textChanged.connect(self.load_table)
        top_bar.addWidget(self.txt_search, stretch=1)

        layout.addLayout(top_bar)

        # Table Widget
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Chọn", "ID Nhóm", "Tên Nhóm", "Lĩnh Vực", "Mẫu Nội Dung Gán Riêng", "Link Nhóm"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        # Bottom Bar: Actions & Summary
        bot_bar = QHBoxLayout()
        btn_sel_all = QPushButton("✅ Chọn Tất Cả")
        btn_sel_all.clicked.connect(lambda: self.toggle_all(True))
        bot_bar.addWidget(btn_sel_all)

        btn_desel_all = QPushButton("❌ Bỏ Chọn Tất Cả")
        btn_desel_all.clicked.connect(lambda: self.toggle_all(False))
        bot_bar.addWidget(btn_desel_all)

        btn_sync = QPushButton("🔄 Đồng Bộ Nhóm Giữa Nick & Fanpage")
        btn_sync.setStyleSheet("background-color: #e65100; color: white; font-weight: bold;")
        btn_sync.clicked.connect(self.on_sync)
        bot_bar.addWidget(btn_sync)

        bot_bar.addStretch()

        self.lbl_count = QLabel("Đã chọn: 0 / 0 nhóm")
        self.lbl_count.setStyleSheet("font-weight: bold; color: #a6e3a1;")
        bot_bar.addWidget(self.lbl_count)

        btn_close = QPushButton("💾 Đóng & Áp Dụng")
        btn_close.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 14px;")
        btn_close.clicked.connect(self.accept)
        bot_bar.addWidget(btn_close)

        layout.addLayout(bot_bar)

        self.load_table()

    def get_groups(self):
        if self.mode == "SINGLE":
            return self.db.get_groups(account_uid=self.account_uid, page_id=self.page_id, category=self.category)
        elif self.mode == "ALL_PAGES":
            pages = self.db.get_pages(self.account_uid)
            res = []
            for p in pages:
                res.extend(self.db.get_groups(account_uid=self.account_uid, page_id=p["page_id"], category=self.category))
            return res
        else: # ALL_PROFILES
            res = self.db.get_groups(account_uid=self.account_uid, page_id="", category=self.category)
            pages = self.db.get_pages(self.account_uid)
            for p in pages:
                res.extend(self.db.get_groups(account_uid=self.account_uid, page_id=p["page_id"], category=self.category))
            return res

    def load_table(self):
        groups = self.get_groups()
        query = self.txt_search.text().strip().lower()
        if query:
            groups = [g for g in groups if query in (g.get("group_name") or "").lower() or query in (g.get("group_id") or "").lower()]

        campaigns = self.db.get_campaigns()
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(groups))

            sel_count = 0
            for row, g in enumerate(groups):
                chk = QCheckBox()
                chk.setChecked(bool(g.get("selected", 0)))
                chk.stateChanged.connect(lambda state, gid=g["id"]: self.on_check_changed(gid, state))
                if g.get("selected"):
                    sel_count += 1

                cell = QWidget()
                cl = QHBoxLayout(cell)
                cl.addWidget(chk)
                cl.setAlignment(Qt.AlignCenter)
                cl.setContentsMargins(0, 0, 0, 0)
                self.table.setCellWidget(row, 0, cell)

                self.table.setItem(row, 1, QTableWidgetItem(g.get("group_id", "")))

                name_item = QTableWidgetItem(g.get("group_name", ""))
                name_item.setToolTip(f"{g.get('group_name', '')}\nID: {g.get('group_id', '')}")
                self.table.setItem(row, 2, name_item)

                self.table.setItem(row, 3, QTableWidgetItem(g.get("category") or "Mặc định"))

                combo = QComboBox()
                combo.addItem("📋 [Theo mẫu chung chiến dịch]", 0)
                cur_camp = g.get("campaign_id") or 0
                cur_idx = 0
                for idx, c in enumerate(campaigns, 1):
                    combo.addItem(f"📝 {c['title']}", c["id"])
                    if c["id"] == cur_camp:
                        cur_idx = idx
                combo.setCurrentIndex(cur_idx)
                combo.currentIndexChanged.connect(lambda idx, gid=g["id"], cb=combo: self.on_camp_changed(gid, cb))
                self.table.setCellWidget(row, 4, combo)

                self.table.setItem(row, 5, QTableWidgetItem(g.get("group_url", "")))

            self.lbl_count.setText(f"Đã chọn: {sel_count} / {len(groups)} nhóm")
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

    def on_check_changed(self, db_id: int, state: int):
        is_chk = (state == Qt.Checked.value or state == 2)
        self.db.update_group_selection(db_id, is_chk)
        groups = self.get_groups()
        sel = sum(1 for g in groups if g.get("selected"))
        self.lbl_count.setText(f"Đã chọn: {sel} / {len(groups)} nhóm")

    def on_camp_changed(self, db_id: int, combo: QComboBox):
        camp_id = combo.currentData()
        self.db.update_group_campaign(db_id, camp_id if camp_id else 0)

    def toggle_all(self, selected: bool):
        if self.mode == "SINGLE":
            self.db.toggle_all_groups_selection(selected, account_uid=self.account_uid, page_id=self.page_id, category=self.category)
        else:
            self.db.toggle_all_groups_selection(selected, account_uid=self.account_uid, category=self.category)
        self.load_table()

    def on_sync(self):
        self.db.sync_groups_across_pages(self.account_uid)
        QMessageBox.information(self, "Thành công", "Đã đồng bộ toàn bộ nhóm giữa Nick cá nhân và tất cả các Fanpage!")
        self.load_table()


class PosterTab(QWidget):
    status_updated = Signal(str)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.workers = []
        self.fixed_times_list = []
        self.last_triggered_key = ""
        self.last_window_run_ts = 0
        self._is_loading_config = False

        self.init_ui()
        self.load_all_config()
        self.init_scheduler_timer()
        # Không lưu và xóa sạch log trên CSDL khi mở phần mềm
        self.db.clear_logs()
        self.log_table.setRowCount(0)

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Control Panel: Setup Campaign & Anti-Spam
        setup_box = QGroupBox("Cấu Hình Tiến Trình & Anti-Spam Đa Luồng Fanpage")
        s_layout = QVBoxLayout(setup_box)

        # Hàng 1: Tài khoản & Tư cách đăng
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Chọn Tài Khoản:"))
        self.combo_accounts = QComboBox()
        self.combo_accounts.currentIndexChanged.connect(self.on_account_combo_changed)
        r1.addWidget(self.combo_accounts, stretch=1)

        r1.addWidget(QLabel("Đăng bài với tư cách:"))
        self.combo_post_as = QComboBox()
        self.combo_post_as.currentIndexChanged.connect(self.on_post_as_changed)
        r1.addWidget(self.combo_post_as, stretch=1)
        s_layout.addLayout(r1)

        # Hàng 2: Lĩnh vực nhóm & Mẫu nội dung
        r2_sub = QHBoxLayout()
        r2_sub.addWidget(QLabel("Lĩnh Vực Nhóm Đăng:"))
        self.combo_category = QComboBox()
        self.combo_category.currentIndexChanged.connect(self.on_category_changed)
        r2_sub.addWidget(self.combo_category, stretch=1)

        r2_sub.addWidget(QLabel("Chọn Mẫu Nội Dung:"))
        self.combo_campaigns = QComboBox()
        self.combo_campaigns.currentIndexChanged.connect(self.save_all_config)
        self.combo_campaigns.currentIndexChanged.connect(self.update_campaign_preview)
        r2_sub.addWidget(self.combo_campaigns, stretch=1)
        s_layout.addLayout(r2_sub)

        # Vùng xem trước nội dung bài viết FB sẽ đăng
        preview_group = QGroupBox("Xem Trước Bài Viết Sẽ Đăng Lên Facebook (Mẫu Chiến Dịch)")
        prev_layout = QVBoxLayout(preview_group)
        prev_layout.setContentsMargins(6, 6, 6, 6)
        prev_layout.setSpacing(4)

        prev_header = QHBoxLayout()
        self.lbl_camp_preview_info = QLabel("Chưa chọn bài viết")
        self.lbl_camp_preview_info.setStyleSheet("color: #a6adc8; font-size: 11px; font-style: italic;")
        prev_header.addWidget(self.lbl_camp_preview_info)
        prev_header.addStretch()

        btn_spin_test = QPushButton("👁️ Xem Biến Thể Spintax")
        btn_spin_test.setStyleSheet("background-color: #0288d1; color: white; padding: 2px 8px; font-size: 11px; font-weight: bold;")
        btn_spin_test.clicked.connect(self.on_preview_campaign_spin)
        prev_header.addWidget(btn_spin_test)
        prev_layout.addLayout(prev_header)

        self.txt_camp_preview = QTextEdit()
        self.txt_camp_preview.setReadOnly(True)
        self.txt_camp_preview.setFont(QFont("Segoe UI Emoji", 11))
        self.txt_camp_preview.setStyleSheet("background-color: #181825; color: #cdd6f4; font-size: 13px; line-height: 1.4; padding: 6px; border: 1px solid #313244; border-radius: 4px;")
        self.txt_camp_preview.setMinimumHeight(95)
        self.txt_camp_preview.setMaximumHeight(135)
        prev_layout.addWidget(self.txt_camp_preview)
        s_layout.addWidget(preview_group)

        # Anti-Spam Options & Info Label
        r2 = QHBoxLayout()
        self.lbl_group_count = QLabel("Target: 0 nhóm")
        self.lbl_group_count.setStyleSheet("font-weight: bold; color: #4caf50;")
        r2.addWidget(self.lbl_group_count)

        self.btn_manage_groups = QPushButton("📋 Chọn / Xem Nhóm Target")
        self.btn_manage_groups.setStyleSheet("background-color: #313244; color: #89b4fa; font-weight: bold; padding: 3px 8px;")
        self.btn_manage_groups.clicked.connect(self.open_group_selection_dialog)
        r2.addWidget(self.btn_manage_groups)

        self.btn_quick_sync = QPushButton("🔄 Đồng Bộ Nhóm")
        self.btn_quick_sync.setToolTip("Đồng bộ danh sách nhóm giữa Nick cá nhân và tất cả Fanpage")
        self.btn_quick_sync.setStyleSheet("background-color: #313244; color: #fab387; font-weight: bold; padding: 3px 8px;")
        self.btn_quick_sync.clicked.connect(self.quick_sync_groups)
        r2.addWidget(self.btn_quick_sync)

        r2.addSpacing(15)
        r2.addWidget(QLabel("Delay giữa 2 nhóm (Giây):"))
        self.spin_delay_min = QSpinBox()
        self.spin_delay_min.setRange(5, 600)
        self.spin_delay_min.setValue(45)
        self.spin_delay_min.valueChanged.connect(self.save_all_config)
        r2.addWidget(self.spin_delay_min)

        r2.addWidget(QLabel("đến"))
        self.spin_delay_max = QSpinBox()
        self.spin_delay_max.setRange(10, 1200)
        self.spin_delay_max.setValue(120)
        self.spin_delay_max.valueChanged.connect(self.save_all_config)
        r2.addWidget(self.spin_delay_max)

        r2.addWidget(QLabel("Nghỉ (Phút):"))
        self.spin_rest_min = QSpinBox()
        self.spin_rest_min.setRange(1, 120)
        self.spin_rest_min.setValue(10)
        self.spin_rest_min.valueChanged.connect(self.save_all_config)
        r2.addWidget(self.spin_rest_min)

        r2.addWidget(QLabel("Sau số bài đăng:"))
        self.spin_rest_after = QSpinBox()
        self.spin_rest_after.setRange(1, 50)
        self.spin_rest_after.setValue(5)
        self.spin_rest_after.valueChanged.connect(self.save_all_config)
        r2.addWidget(self.spin_rest_after)

        s_layout.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Chế Độ Trình Duyệt:"))
        self.combo_browser_mode = QComboBox()
        self.combo_browser_mode.addItem("👁️ HIỂN THỊ TRÌNH DUYỆT (Quan sát trực tiếp)", False)
        self.combo_browser_mode.addItem("🥷 CHẠY NGẦM HỆ THỐNG (Tự động ẩn trình duyệt)", True)
        self.combo_browser_mode.setStyleSheet("font-weight: bold; padding: 4px;")
        self.combo_browser_mode.currentIndexChanged.connect(self.save_all_config)
        r3.addWidget(self.combo_browser_mode)

        self.chk_hash = QCheckBox("Thêm mã Hash ngẫu nhiên cuối bài")
        self.chk_hash.toggled.connect(self.save_all_config)
        r3.addWidget(self.chk_hash)

        self.chk_shuffle_media = QCheckBox("Xáo trộn thứ tự hình ảnh/video")
        self.chk_shuffle_media.setChecked(True)
        self.chk_shuffle_media.toggled.connect(self.save_all_config)
        r3.addWidget(self.chk_shuffle_media)

        s_layout.addLayout(r3)
        layout.addWidget(setup_box)

        # Lên Lịch Đăng Bài Tự Động (Scheduler)
        self.schedule_box = self.init_scheduler_ui()
        layout.addWidget(self.schedule_box)

        # Execution Buttons & Progress Bar
        exec_box = QGroupBox("Điều Khiển Đăng Bài Tự Động")
        e_layout = QVBoxLayout(exec_box)

        btn_bar = QHBoxLayout()
        self.btn_start = QPushButton("🚀 BẮT ĐẦU ĐĂNG BÀI ĐA LUỒNG")
        self.btn_start.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; font-size: 14px; padding: 8px;")
        self.btn_start.clicked.connect(self.on_start)
        btn_bar.addWidget(self.btn_start)

        self.btn_pause = QPushButton("⏸️ Tạm Dừng")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.on_toggle_pause)
        btn_bar.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("🛑 Dừng Hẳn")
        self.btn_stop.setStyleSheet("background-color: #c62828; color: white; font-weight: bold;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.on_stop)
        btn_bar.addWidget(self.btn_stop)

        e_layout.addLayout(btn_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        e_layout.addWidget(self.progress_bar)

        layout.addWidget(exec_box)

        # Log Console Table (5 Columns)
        self.log_table = QTableWidget()
        self.log_table.setColumnCount(5)
        self.log_table.setHorizontalHeaderLabels(["Thời Gian", "Tư Cách Đăng", "Nhóm Target", "Trạng Thái", "Chi Tiết Thông Báo"])
        self.log_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.log_table)

    def load_combos(self):
        self.load_all_config()

    def on_account_combo_changed(self):
        self.update_pages_combo()
        self.save_all_config()

    def on_post_as_changed(self):
        self.update_categories_combo()
        self.save_all_config()

    def on_category_changed(self):
        self.update_group_count_label()
        self.save_all_config()

    def update_pages_combo(self, desired_page_id=None, desired_mode=None):
        self.combo_post_as.blockSignals(True)
        self.combo_post_as.clear()
        self.combo_post_as.addItem("👤 Nick Cá Nhân (Mặc định)", {"page_id": "", "page_name": "", "mode": "SINGLE"})
        acc_uid = self.combo_accounts.currentData()
        target_idx = 0
        if acc_uid:
            pages = self.db.get_pages(acc_uid)
            for p in pages:
                self.combo_post_as.addItem(f"🚩 Fanpage: {p['page_name']}", {"page_id": p["page_id"], "page_name": p["page_name"], "mode": "SINGLE"})
                if desired_mode == "SINGLE" and desired_page_id == p["page_id"]:
                    target_idx = self.combo_post_as.count() - 1
            if pages:
                self.combo_post_as.addItem("🔥 TẤT CẢ FANPAGE (Chạy Đa Luồng Song Song)", {"mode": "ALL_PAGES"})
                if desired_mode == "ALL_PAGES":
                    target_idx = self.combo_post_as.count() - 1
                self.combo_post_as.addItem("🔥 NICK CÁ NHÂN + TẤT CẢ FANPAGE (Chạy Song Song Tất Cả)", {"mode": "ALL_PROFILES"})
                if desired_mode == "ALL_PROFILES":
                    target_idx = self.combo_post_as.count() - 1

        self.combo_post_as.setCurrentIndex(target_idx)
        self.combo_post_as.blockSignals(False)
        self.update_categories_combo()

    def update_categories_combo(self, desired_category=None):
        acc_uid = self.combo_accounts.currentData()
        page_info = self.combo_post_as.currentData() or {}
        page_id = page_info.get("page_id", "") if isinstance(page_info, dict) else ""
        cats = self.db.get_categories(account_uid=acc_uid, page_id=page_id)

        self.combo_category.blockSignals(True)
        self.combo_category.clear()
        self.combo_category.addItem("Tất cả lĩnh vực")
        cat_idx = 0
        for i, c in enumerate(cats, 1):
            self.combo_category.addItem(c)
            if desired_category and c == desired_category:
                cat_idx = i
        self.combo_category.setCurrentIndex(cat_idx)
        self.combo_category.blockSignals(False)

        self.update_group_count_label()

    def update_group_count_label(self):
        acc_uid = self.combo_accounts.currentData()
        page_info = self.combo_post_as.currentData() or {}
        mode = page_info.get("mode", "SINGLE") if isinstance(page_info, dict) else "SINGLE"
        category = self.combo_category.currentText()

        if mode == "SINGLE":
            page_id = page_info.get("page_id", "")
            groups = self.db.get_groups(account_uid=acc_uid, page_id=page_id, category=category, only_selected=True)
            total = len(groups)
        else:
            all_pages = self.db.get_pages(acc_uid)
            total = 0
            if mode in ["ALL_PAGES", "ALL_PROFILES"]:
                for p in all_pages:
                    total += len(self.db.get_groups(account_uid=acc_uid, page_id=p["page_id"], category=category, only_selected=True))
            if mode == "ALL_PROFILES":
                total += len(self.db.get_groups(account_uid=acc_uid, page_id="", category=category, only_selected=True))

        cat_text = f" [{category}]" if category not in ["Tất cả", "Tất cả lĩnh vực", ""] else ""
        self.lbl_group_count.setText(f"Target: {total} nhóm{cat_text}")
        if total == 0:
            self.lbl_group_count.setStyleSheet("font-weight: bold; color: #f38ba8;")
        else:
            self.lbl_group_count.setStyleSheet("font-weight: bold; color: #4caf50;")

    def open_group_selection_dialog(self):
        acc_uid = self.combo_accounts.currentData()
        if not acc_uid:
            QMessageBox.warning(self, "Thông báo", "Vui lòng chọn tài khoản Facebook!")
            return
        page_info = self.combo_post_as.currentData() or {}
        page_id = page_info.get("page_id", "") if isinstance(page_info, dict) else ""
        page_name = page_info.get("page_name", "") if isinstance(page_info, dict) else ""
        mode = page_info.get("mode", "SINGLE") if isinstance(page_info, dict) else "SINGLE"
        category = self.combo_category.currentText()

        dlg = GroupSelectionDialog(self.db, acc_uid, page_id, page_name, mode, category, parent=self)
        if dlg.exec():
            self.update_group_count_label()
            self.save_all_config()

    def quick_sync_groups(self):
        acc_uid = self.combo_accounts.currentData()
        if not acc_uid:
            QMessageBox.warning(self, "Thông báo", "Vui lòng chọn tài khoản Facebook!")
            return
        self.db.sync_groups_across_pages(acc_uid)
        QMessageBox.information(self, "Thành công", "Đã đồng bộ toàn bộ nhóm giữa Nick cá nhân và tất cả các Fanpage!")
        self.update_group_count_label()
        self.save_all_config()

    # --- SCHEDULER IMPLEMENTATION ---
    def init_scheduler_ui(self) -> QGroupBox:
        box = QGroupBox("⏰ Lên Lịch Đăng Bài Tự Động (Tự Chạy Theo Giờ & Thứ Trong Tuần)")
        b_layout = QVBoxLayout(box)

        # Hàng 1: Bật/Tắt & Chọn chế độ
        r1 = QHBoxLayout()
        self.chk_schedule_enable = QCheckBox("🔔 BẬT HẸN GIỜ ĐĂNG BÀI (Chỉ cần mở phần mềm để đó, đến giờ tự đăng)")
        self.chk_schedule_enable.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6e3a1; padding: 2px;")
        self.chk_schedule_enable.toggled.connect(self.on_schedule_enabled_toggled)
        r1.addWidget(self.chk_schedule_enable)

        r1.addSpacing(20)
        r1.addWidget(QLabel("Chế độ hẹn giờ:"))
        self.combo_schedule_mode = QComboBox()
        self.combo_schedule_mode.addItem("📅 Đăng theo các mốc giờ cố định trong ngày", "FIXED")
        self.combo_schedule_mode.addItem("⏳ Đăng lặp lại trong khung thời gian", "WINDOW")
        self.combo_schedule_mode.currentIndexChanged.connect(self.on_schedule_mode_changed)
        r1.addWidget(self.combo_schedule_mode, stretch=1)
        b_layout.addLayout(r1)

        # Hàng 2: Chọn các thứ trong tuần
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Lặp lại vào các ngày:"))
        self.day_checkboxes = {}
        day_labels = [(1, "Thứ 2"), (2, "Thứ 3"), (3, "Thứ 4"), (4, "Thứ 5"), (5, "Thứ 6"), (6, "Thứ 7"), (7, "Chủ Nhật")]
        for dow, text in day_labels:
            chk = QCheckBox(text)
            chk.setChecked(True)
            chk.toggled.connect(self.save_scheduler_settings)
            self.day_checkboxes[dow] = chk
            r2.addWidget(chk)

        r2.addSpacing(10)
        btn_all = QPushButton("Tất Cả")
        btn_all.setStyleSheet("padding: 2px 6px; font-size: 11px;")
        btn_all.clicked.connect(lambda: self.set_days_preset("ALL"))
        r2.addWidget(btn_all)

        btn_weekdays = QPushButton("T2 - T6")
        btn_weekdays.setStyleSheet("padding: 2px 6px; font-size: 11px;")
        btn_weekdays.clicked.connect(lambda: self.set_days_preset("WEEKDAYS"))
        r2.addWidget(btn_weekdays)

        btn_weekend = QPushButton("T7 & CN")
        btn_weekend.setStyleSheet("padding: 2px 6px; font-size: 11px;")
        btn_weekend.clicked.connect(lambda: self.set_days_preset("WEEKEND"))
        r2.addWidget(btn_weekend)

        r2.addStretch()
        b_layout.addLayout(r2)

        # Hàng 3: Cấu hình giờ (Container động)
        self.frame_fixed = QWidget()
        f_layout = QHBoxLayout(self.frame_fixed)
        f_layout.setContentsMargins(0, 0, 0, 0)
        f_layout.addWidget(QLabel("Mốc giờ đăng:"))
        self.time_picker = QTimeEdit()
        self.time_picker.setDisplayFormat("HH:mm")
        self.time_picker.setTime(QTime(9, 0))
        f_layout.addWidget(self.time_picker)

        btn_add_time = QPushButton("➕ Thêm Giờ")
        btn_add_time.setStyleSheet("background-color: #1976d2; color: white; font-weight: bold; padding: 4px 8px;")
        btn_add_time.clicked.connect(lambda: self.add_fixed_time(self.time_picker.time().toString("HH:mm")))
        f_layout.addWidget(btn_add_time)

        f_layout.addWidget(QLabel("Giờ đã đặt:"))
        self.txt_fixed_display = QLineEdit()
        self.txt_fixed_display.setReadOnly(True)
        self.txt_fixed_display.setPlaceholderText("Chưa có mốc giờ nào (VD: 09:00, 14:30...)")
        f_layout.addWidget(self.txt_fixed_display, stretch=1)

        btn_clear_t = QPushButton("🗑️ Xóa")
        btn_clear_t.clicked.connect(self.clear_fixed_times)
        f_layout.addWidget(btn_clear_t)

        f_layout.addSpacing(10)
        f_layout.addWidget(QLabel("Giờ vàng gợi ý:"))
        for g_time in ["09:00", "11:30", "14:30", "20:00"]:
            btn_gold = QPushButton(f"+ {g_time}")
            btn_gold.setStyleSheet("background-color: #313244; color: #89b4fa; padding: 2px 6px; font-size: 11px;")
            btn_gold.clicked.connect(lambda _, t=g_time: self.add_fixed_time(t))
            f_layout.addWidget(btn_gold)
        b_layout.addWidget(self.frame_fixed)

        self.frame_window = QWidget()
        w_layout = QHBoxLayout(self.frame_window)
        w_layout.setContentsMargins(0, 0, 0, 0)
        w_layout.addWidget(QLabel("Khung giờ bắt đầu từ:"))
        self.time_win_start = QTimeEdit()
        self.time_win_start.setDisplayFormat("HH:mm")
        self.time_win_start.setTime(QTime(8, 30))
        self.time_win_start.timeChanged.connect(self.save_scheduler_settings)
        w_layout.addWidget(self.time_win_start)

        w_layout.addWidget(QLabel("Đến:"))
        self.time_win_end = QTimeEdit()
        self.time_win_end.setDisplayFormat("HH:mm")
        self.time_win_end.setTime(QTime(21, 30))
        self.time_win_end.timeChanged.connect(self.save_scheduler_settings)
        w_layout.addWidget(self.time_win_end)

        w_layout.addWidget(QLabel("Lặp lại sau mỗi (Phút):"))
        self.spin_win_interval = QSpinBox()
        self.spin_win_interval.setRange(10, 720)
        self.spin_win_interval.setValue(60)
        self.spin_win_interval.valueChanged.connect(self.save_scheduler_settings)
        w_layout.addWidget(self.spin_win_interval)
        w_layout.addStretch()
        self.frame_window.setVisible(False)
        b_layout.addWidget(self.frame_window)

        # Hàng 4: Trạng thái & Đồng hồ đếm ngược Realtime
        self.lbl_schedule_status = QLabel("⚪ Trạng thái: Hẹn giờ đang tắt.")
        self.lbl_schedule_status.setStyleSheet("color: #a6adc8; font-size: 13px; font-weight: bold; padding: 6px; background-color: #181825; border-radius: 6px;")
        b_layout.addWidget(self.lbl_schedule_status)

        return box

    def on_schedule_mode_changed(self):
        is_fixed = self.combo_schedule_mode.currentData() == "FIXED"
        self.frame_fixed.setVisible(is_fixed)
        self.frame_window.setVisible(not is_fixed)
        self.save_scheduler_settings()

    def on_schedule_enabled_toggled(self, enabled: bool):
        if enabled:
            self.chk_schedule_enable.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6e3a1; padding: 2px;")
        else:
            self.chk_schedule_enable.setStyleSheet("font-size: 13px; font-weight: bold; color: #f38ba8; padding: 2px;")
        self.save_scheduler_settings()

    def set_days_preset(self, preset: str):
        for dow, chk in self.day_checkboxes.items():
            if preset == "ALL":
                chk.setChecked(True)
            elif preset == "WEEKDAYS":
                chk.setChecked(dow <= 5)
            elif preset == "WEEKEND":
                chk.setChecked(dow > 5)
        self.save_scheduler_settings()

    def add_fixed_time(self, time_str: str):
        time_str = time_str.strip()
        if time_str and time_str not in self.fixed_times_list:
            self.fixed_times_list.append(time_str)
            self.fixed_times_list.sort()
            self.txt_fixed_display.setText(", ".join(self.fixed_times_list))
            self.save_scheduler_settings()

    def clear_fixed_times(self):
        self.fixed_times_list.clear()
        self.txt_fixed_display.clear()
        self.save_scheduler_settings()

    def save_all_config(self):
        if getattr(self, "_is_loading_config", False):
            return

        page_info = self.combo_post_as.currentData() or {}
        mode = page_info.get("mode", "SINGLE") if isinstance(page_info, dict) else "SINGLE"
        page_id = page_info.get("page_id", "") if isinstance(page_info, dict) else ""
        page_name = page_info.get("page_name", "") if isinstance(page_info, dict) else ""

        config = {
            "account_uid": self.combo_accounts.currentData() or "",
            "post_as_mode": mode,
            "post_as_page_id": page_id,
            "post_as_page_name": page_name,
            "category": self.combo_category.currentText() or "Tất cả lĩnh vực",
            "campaign_id": self.combo_campaigns.currentData() or 0,
            "delay_min": self.spin_delay_min.value(),
            "delay_max": self.spin_delay_max.value(),
            "rest_min": self.spin_rest_min.value(),
            "rest_after": self.spin_rest_after.value(),
            "browser_headless": bool(self.combo_browser_mode.currentData()),
            "chk_hash": self.chk_hash.isChecked(),
            "chk_shuffle_media": self.chk_shuffle_media.isChecked(),
            "schedule_enabled": self.chk_schedule_enable.isChecked(),
            "schedule_mode": self.combo_schedule_mode.currentData() or "FIXED",
            "schedule_days": [dow for dow, chk in self.day_checkboxes.items() if chk.isChecked()],
            "schedule_fixed_times": list(self.fixed_times_list),
            "schedule_window_start": self.time_win_start.time().toString("HH:mm"),
            "schedule_window_end": self.time_win_end.time().toString("HH:mm"),
            "schedule_window_interval": self.spin_win_interval.value()
        }
        self.db.set_setting("poster_config", config)
        self.db.set_setting("scheduler_config", {
            "enabled": config["schedule_enabled"],
            "mode": config["schedule_mode"],
            "days": config["schedule_days"],
            "fixed_times": config["schedule_fixed_times"],
            "window_start": config["schedule_window_start"],
            "window_end": config["schedule_window_end"],
            "window_interval": config["schedule_window_interval"]
        })

    def load_all_config(self):
        self._is_loading_config = True
        try:
            config = self.db.get_setting("poster_config", {})
            sched_old = self.db.get_setting("scheduler_config", {})

            # 1. Nạp danh sách tài khoản
            accounts = self.db.get_accounts()
            cur_acc = config.get("account_uid") or self.combo_accounts.currentData()
            self.combo_accounts.blockSignals(True)
            self.combo_accounts.clear()
            acc_idx = 0
            for i, a in enumerate(accounts):
                self.combo_accounts.addItem(f"{a['name']} ({a['uid']})", a['uid'])
                if cur_acc and a['uid'] == cur_acc:
                    acc_idx = i
            if accounts:
                self.combo_accounts.setCurrentIndex(acc_idx)
            self.combo_accounts.blockSignals(False)

            # 2. Nạp danh sách mẫu nội dung (Chiến dịch)
            campaigns = self.db.get_campaigns()
            cur_camp = config.get("campaign_id") or self.combo_campaigns.currentData()
            self.combo_campaigns.blockSignals(True)
            self.combo_campaigns.clear()
            camp_idx = 0
            for i, c in enumerate(campaigns):
                self.combo_campaigns.addItem(c["title"], c["id"])
                if cur_camp and c["id"] == cur_camp:
                    camp_idx = i
            if campaigns:
                self.combo_campaigns.setCurrentIndex(camp_idx)
            self.combo_campaigns.blockSignals(False)

            # 3. Nạp danh sách Tư cách đăng (Fanpage / Nick cá nhân)
            saved_mode = config.get("post_as_mode", "SINGLE")
            saved_page_id = config.get("post_as_page_id", "")
            self.update_pages_combo(desired_page_id=saved_page_id, desired_mode=saved_mode)

            # 4. Nạp danh sách Lĩnh vực
            saved_cat = config.get("category", "Tất cả lĩnh vực")
            self.update_categories_combo(desired_category=saved_cat)

            # 5. Cấu hình Anti-Spam & Trình duyệt
            if "delay_min" in config:
                self.spin_delay_min.setValue(int(config["delay_min"]))
            if "delay_max" in config:
                self.spin_delay_max.setValue(int(config["delay_max"]))
            if "rest_min" in config:
                self.spin_rest_min.setValue(int(config["rest_min"]))
            if "rest_after" in config:
                self.spin_rest_after.setValue(int(config["rest_after"]))

            if "browser_headless" in config:
                b_idx = self.combo_browser_mode.findData(bool(config["browser_headless"]))
                if b_idx >= 0:
                    self.combo_browser_mode.setCurrentIndex(b_idx)

            if "chk_hash" in config:
                self.chk_hash.setChecked(bool(config["chk_hash"]))
            if "chk_shuffle_media" in config:
                self.chk_shuffle_media.setChecked(bool(config["chk_shuffle_media"]))

            # 6. Cấu hình Lịch Hẹn
            sched = config if "schedule_enabled" in config else sched_old
            is_enabled = bool(sched.get("schedule_enabled", sched.get("enabled", False)))
            self.chk_schedule_enable.blockSignals(True)
            self.chk_schedule_enable.setChecked(is_enabled)
            self.chk_schedule_enable.blockSignals(False)
            if is_enabled:
                self.chk_schedule_enable.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6e3a1; padding: 2px;")
            else:
                self.chk_schedule_enable.setStyleSheet("font-size: 13px; font-weight: bold; color: #f38ba8; padding: 2px;")

            sched_mode = sched.get("schedule_mode", sched.get("mode", "FIXED"))
            s_idx = self.combo_schedule_mode.findData(sched_mode)
            if s_idx >= 0:
                self.combo_schedule_mode.setCurrentIndex(s_idx)
            self.on_schedule_mode_changed()

            saved_days = set(sched.get("schedule_days", sched.get("days", [1, 2, 3, 4, 5, 6, 7])))
            for dow, chk in self.day_checkboxes.items():
                chk.blockSignals(True)
                chk.setChecked(dow in saved_days)
                chk.blockSignals(False)

            self.fixed_times_list = list(sched.get("schedule_fixed_times", sched.get("fixed_times", [])))
            self.txt_fixed_display.setText(", ".join(self.fixed_times_list))

            w_start = sched.get("schedule_window_start", sched.get("window_start", "08:30"))
            self.time_win_start.setTime(QTime.fromString(w_start, "HH:mm"))

            w_end = sched.get("schedule_window_end", sched.get("window_end", "21:30"))
            self.time_win_end.setTime(QTime.fromString(w_end, "HH:mm"))

            w_int = sched.get("schedule_window_interval", sched.get("window_interval", 60))
            self.spin_win_interval.setValue(int(w_int))

            self.update_group_count_label()
            self.update_campaign_preview()
        finally:
            self._is_loading_config = False

    def update_campaign_preview(self):
        camp_id = self.combo_campaigns.currentData()
        if not camp_id:
            self.txt_camp_preview.clear()
            self.lbl_camp_preview_info.setText("Chưa chọn bài viết")
            return
        campaigns = self.db.get_campaigns()
        camp = next((c for c in campaigns if c["id"] == camp_id), None)
        if camp:
            content = camp.get("content", "")
            media_count = len(camp.get("images", []))
            self.txt_camp_preview.setPlainText(content)
            self.lbl_camp_preview_info.setText(f"📋 '{camp['title']}' | 📎 {media_count} tệp ảnh/video | 📝 {len(content)} ký tự")
        else:
            self.txt_camp_preview.clear()
            self.lbl_camp_preview_info.setText("Chưa chọn bài viết")

    def on_preview_campaign_spin(self):
        content = self.txt_camp_preview.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "Thông Báo", "Chưa có nội dung bài viết để xem thử biến thể!")
            return
        from core.spintax_parser import SpintaxParser
        parsed = SpintaxParser.parse(content)
        QMessageBox.information(self, "Xem Thử Biến Thể Bài Viết (Spintax Preview)", parsed)

    def save_scheduler_settings(self):
        self.save_all_config()

    def load_scheduler_settings(self):
        self.load_all_config()

    def init_scheduler_timer(self):
        self.scheduler_timer = QTimer(self)
        self.scheduler_timer.setInterval(1000)
        self.scheduler_timer.timeout.connect(self.on_schedule_tick)
        self.scheduler_timer.start()

    def on_schedule_tick(self):
        if not self.chk_schedule_enable.isChecked():
            self.lbl_schedule_status.setText("⚪ Chế độ hẹn giờ đang TẮT. Tích chọn 'Bật hẹn giờ đăng bài' bên trên để tự động chạy.")
            self.lbl_schedule_status.setStyleSheet("color: #a6adc8; font-size: 13px; font-weight: bold; padding: 6px; background-color: #181825; border-radius: 6px;")
            return

        now = QDateTime.currentDateTime()
        selected_days = [dow for dow, chk in self.day_checkboxes.items() if chk.isChecked()]
        if not selected_days:
            self.lbl_schedule_status.setText("⚠️ Chưa chọn ngày lặp lại nào trong tuần (T2 - CN)!")
            self.lbl_schedule_status.setStyleSheet("color: #f38ba8; font-size: 13px; font-weight: bold; padding: 6px; background-color: #181825; border-radius: 6px;")
            return

        mode = self.combo_schedule_mode.currentData()

        # CHẾ ĐỘ 1: CÁC MỐC GIỜ CỐ ĐỊNH
        if mode == "FIXED":
            if not self.fixed_times_list:
                self.lbl_schedule_status.setText("⚠️ Chưa thêm mốc giờ đăng nào! Vui lòng bấm '➕ Thêm Giờ' bên trên.")
                self.lbl_schedule_status.setStyleSheet("color: #f9e2af; font-size: 13px; font-weight: bold; padding: 6px; background-color: #181825; border-radius: 6px;")
                return

            next_run = None
            for day_offset in range(8):
                cand_date = now.date().addDays(day_offset)
                if cand_date.dayOfWeek() not in selected_days:
                    continue

                for t_str in self.fixed_times_list:
                    t_val = QTime.fromString(t_str, "HH:mm")
                    cand_dt = QDateTime(cand_date, t_val)
                    if cand_dt > now.addSecs(-1):
                        if next_run is None or cand_dt < next_run:
                            next_run = cand_dt

                if next_run and next_run > now:
                    break

            if next_run:
                secs_left = now.secsTo(next_run)
                day_names = {1: "Thứ 2", 2: "Thứ 3", 3: "Thứ 4", 4: "Thứ 5", 5: "Thứ 6", 6: "Thứ 7", 7: "Chủ Nhật"}
                day_str = "Hôm nay" if next_run.date() == now.date() else day_names.get(next_run.date().dayOfWeek(), "")

                # Khi đến đúng giờ hẹn
                if secs_left <= 0:
                    trigger_key = next_run.toString("yyyy-MM-dd HH:mm")
                    if self.last_triggered_key != trigger_key:
                        self.last_triggered_key = trigger_key
                        self.trigger_scheduled_run(f"Đúng giờ hẹn {next_run.toString('HH:mm')}")

                h = max(0, secs_left // 3600)
                m = max(0, (secs_left % 3600) // 60)
                s = max(0, secs_left % 60)
                self.lbl_schedule_status.setText(f"⏰ ĐANG BẬT HẸN GIỜ: Lần đăng kế tiếp: {day_str} lúc {next_run.toString('HH:mm:ss')} (Còn lại: {h:02d}h {m:02d}m {s:02d}s)")
                self.lbl_schedule_status.setStyleSheet("color: #a6e3a1; font-size: 13px; font-weight: bold; padding: 6px; background-color: #11111b; border: 1px solid #2e7d32; border-radius: 6px;")

        # CHẾ ĐỘ 2: LẶP LẠI TRONG KHOẢNG THỜI GIAN
        else:
            win_start = self.time_win_start.time()
            win_end = self.time_win_end.time()
            interval_sec = self.spin_win_interval.value() * 60
            curr_dow = now.date().dayOfWeek()

            if curr_dow in selected_days and win_start <= now.time() <= win_end:
                now_ts = time.time()
                elapsed = now_ts - self.last_window_run_ts
                if elapsed >= interval_sec:
                    self.last_window_run_ts = now_ts
                    self.trigger_scheduled_run(f"Khung giờ ({win_start.toString('HH:mm')} - {win_end.toString('HH:mm')})")
                    remaining = interval_sec
                else:
                    remaining = int(interval_sec - elapsed)

                m = remaining // 60
                s = remaining % 60
                self.lbl_schedule_status.setText(f"⏰ ĐANG TRONG KHUNG GIỜ ({win_start.toString('HH:mm')} - {win_end.toString('HH:mm')}): Lần đăng tiếp theo sau {m:02d}m {s:02d}s")
                self.lbl_schedule_status.setStyleSheet("color: #a6e3a1; font-size: 13px; font-weight: bold; padding: 6px; background-color: #11111b; border: 1px solid #2e7d32; border-radius: 6px;")
            else:
                self.lbl_schedule_status.setText(f"⏳ Ngoài khung giờ đăng bài ({win_start.toString('HH:mm')} - {win_end.toString('HH:mm')}). Tự động chạy khi đến khung giờ hẹn.")
                self.lbl_schedule_status.setStyleSheet("color: #fab387; font-size: 13px; font-weight: bold; padding: 6px; background-color: #181825; border-radius: 6px;")

    def trigger_scheduled_run(self, reason: str):
        if any(w.isRunning() for w in self.workers):
            self.add_log_row(time.strftime("%H:%M:%S"), "LỊCH HẸN", "-", "WAITING", f"[{reason}] Đến giờ hẹn nhưng ca đăng trước đang hoạt động, hoãn lại để chống xung đột.")
            return

        acc_uid = self.combo_accounts.currentData()
        camp_id = self.combo_campaigns.currentData()
        if not acc_uid or not camp_id:
            self.add_log_row(time.strftime("%H:%M:%S"), "LỊCH HẸN", "-", "FAILED", f"[{reason}] Lỗi: Chưa chọn Tài khoản hoặc Mẫu nội dung trong cấu hình!")
            return

        camp_title = self.combo_campaigns.currentText()
        page_info = self.combo_post_as.currentData() or {}
        p_name = page_info.get("page_name", "") if isinstance(page_info, dict) else ""
        mode = page_info.get("mode", "SINGLE") if isinstance(page_info, dict) else "SINGLE"
        prof_desc = f"Fanpage: {p_name}" if p_name else "Nick cá nhân"
        if mode == "ALL_PAGES":
            prof_desc = "Tất cả Fanpage"
        elif mode == "ALL_PROFILES":
            prof_desc = "Nick cá nhân + Tất cả Fanpage"

        self.add_log_row(time.strftime("%H:%M:%S"), "LỊCH HẸN", "-", "INFO", f"🔔 [{reason}] Bắt đầu tự động đăng bài theo cấu hình đã lưu: [{prof_desc}] | Mẫu: '{camp_title}'...")
        self.on_start(is_scheduled=True)

    def on_start(self, is_scheduled: bool = False):
        acc_uid = self.combo_accounts.currentData()
        camp_id = self.combo_campaigns.currentData()
        page_info = self.combo_post_as.currentData() or {}
        mode = page_info.get("mode", "SINGLE") if isinstance(page_info, dict) else "SINGLE"
        category = self.combo_category.currentText()

        if not acc_uid:
            if is_scheduled:
                self.add_log_row(time.strftime("%H:%M:%S"), "LỊCH HẸN", "-", "FAILED", "Chưa chọn tài khoản Facebook trong cấu hình!")
            else:
                QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn tài khoản Facebook!")
            return
        if not camp_id:
            if is_scheduled:
                self.add_log_row(time.strftime("%H:%M:%S"), "LỊCH HẸN", "-", "FAILED", "Chưa chọn mẫu nội dung bài đăng!")
            else:
                QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn mẫu nội dung bài đăng!")
            return

        target_configs = []
        all_pages = self.db.get_pages(acc_uid)

        if mode == "SINGLE":
            page_id = page_info.get("page_id", "")
            page_name = page_info.get("page_name", "")
            groups = self.db.get_groups(account_uid=acc_uid, page_id=page_id, category=category, only_selected=True)
            if not groups:
                all_acc_groups = self.db.get_groups(account_uid=acc_uid, only_selected=True)
                if all_acc_groups:
                    target_desc = f"Fanpage '{page_name}'" if page_name else "Nick cá nhân"
                    if is_scheduled:
                        self.db.sync_groups_across_pages(acc_uid)
                        groups = self.db.get_groups(account_uid=acc_uid, page_id=page_id, category=category, only_selected=True)
                        if groups:
                            self.add_log_row(time.strftime("%H:%M:%S"), "LỊCH HẸN", "-", "INFO", f"🔄 Tự động đồng bộ {len(groups)} nhóm sang {target_desc} để thực hiện lịch đăng...")
                    else:
                        reply = QMessageBox.question(
                            self,
                            "Chưa Có Nhóm Nào Được Chọn",
                            f"Chưa có nhóm nào được chọn cho {target_desc}.\n\n"
                            f"Hệ thống phát hiện tài khoản có {len(all_acc_groups)} nhóm ở Fanpage/Nick khác. "
                            f"Bạn có muốn tự động đồng bộ nhóm sang {target_desc} để đăng ngay không?",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.Yes
                        )
                        if reply == QMessageBox.Yes:
                            self.db.sync_groups_across_pages(acc_uid)
                            groups = self.db.get_groups(account_uid=acc_uid, page_id=page_id, category=category, only_selected=True)
                            self.update_group_count_label()

            if groups:
                target_configs.append({"page_id": page_id, "page_name": page_name})
            else:
                target_desc = f"Fanpage '{page_name}'" if page_name else "Nick cá nhân"
                cat_desc = f" thuộc lĩnh vực '{category}'" if category not in ["Tất cả", "Tất cả lĩnh vực", ""] else ""
                msg = f"Chưa chọn nhóm nào{cat_desc} cho {target_desc}!"
                if is_scheduled:
                    self.add_log_row(time.strftime("%H:%M:%S"), "LỊCH HẸN", "-", "FAILED", msg)
                else:
                    QMessageBox.warning(self, "Cảnh báo", msg)
                return

        elif mode == "ALL_PAGES":
            for p in all_pages:
                groups = self.db.get_groups(account_uid=acc_uid, page_id=p["page_id"], category=category, only_selected=True)
                if groups:
                    target_configs.append({"page_id": p["page_id"], "page_name": p["page_name"]})
            if not target_configs:
                all_acc_groups = self.db.get_groups(account_uid=acc_uid, only_selected=True)
                if all_acc_groups:
                    self.db.sync_groups_across_pages(acc_uid)
                    for p in all_pages:
                        groups = self.db.get_groups(account_uid=acc_uid, page_id=p["page_id"], category=category, only_selected=True)
                        if groups:
                            target_configs.append({"page_id": p["page_id"], "page_name": p["page_name"]})
            if not target_configs:
                msg = "Không tìm thấy Fanpage nào có tích chọn nhóm để đăng!"
                if is_scheduled:
                    self.add_log_row(time.strftime("%H:%M:%S"), "LỊCH HẸN", "-", "FAILED", msg)
                else:
                    QMessageBox.warning(self, "Cảnh báo", msg)
                return

        elif mode == "ALL_PROFILES":
            nick_groups = self.db.get_groups(account_uid=acc_uid, page_id="", category=category, only_selected=True)
            if nick_groups:
                target_configs.append({"page_id": "", "page_name": ""})
            for p in all_pages:
                groups = self.db.get_groups(account_uid=acc_uid, page_id=p["page_id"], category=category, only_selected=True)
                if groups:
                    target_configs.append({"page_id": p["page_id"], "page_name": p["page_name"]})
            if not target_configs:
                all_acc_groups = self.db.get_groups(account_uid=acc_uid, only_selected=True)
                if all_acc_groups:
                    self.db.sync_groups_across_pages(acc_uid)
                    nick_groups = self.db.get_groups(account_uid=acc_uid, page_id="", category=category, only_selected=True)
                    if nick_groups:
                        target_configs.append({"page_id": "", "page_name": ""})
                    for p in all_pages:
                        groups = self.db.get_groups(account_uid=acc_uid, page_id=p["page_id"], category=category, only_selected=True)
                        if groups:
                            target_configs.append({"page_id": p["page_id"], "page_name": p["page_name"]})
            if not target_configs:
                msg = "Không tìm thấy Nick cá nhân hay Fanpage nào có tích chọn nhóm!"
                if is_scheduled:
                    self.add_log_row(time.strftime("%H:%M:%S"), "LỊCH HẸN", "-", "FAILED", msg)
                else:
                    QMessageBox.warning(self, "Cảnh báo", msg)
                return

        anti_config = AntiSpamConfig(
            min_delay_sec=self.spin_delay_min.value(),
            max_delay_sec=self.spin_delay_max.value(),
            rest_after_posts=self.spin_rest_after.value(),
            rest_duration_min=self.spin_rest_min.value(),
            randomize_media=self.chk_shuffle_media.isChecked(),
            add_unique_hash=self.chk_hash.isChecked()
        )

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.log_table.setRowCount(0)
        self.workers = []

        headless_mode = bool(self.combo_browser_mode.currentData())

        for cfg in target_configs:
            w = PosterWorker(
                db=self.db,
                account_uid=acc_uid,
                campaign_id=camp_id,
                anti_config=anti_config,
                headless=headless_mode,
                post_as_page_name=cfg["page_name"],
                category=category
            )
            w.log_signal.connect(self.add_log_row)
            w.progress_signal.connect(self.update_progress)
            w.status_text_signal.connect(self.emit_status)
            w.finished_signal.connect(self.on_worker_finished)
            self.workers.append(w)
            w.start()

    def on_toggle_pause(self):
        if not self.workers:
            return
        is_paused = any(w.is_paused for w in self.workers)
        for w in self.workers:
            if is_paused:
                w.resume()
            else:
                w.pause()

        if is_paused:
            self.btn_pause.setText("⏸️ Tạm Dừng")
        else:
            self.btn_pause.setText("▶️ Tiếp Tục")

    def on_stop(self):
        for w in self.workers:
            w.stop()

    def on_worker_finished(self):
        if all(not w.isRunning() for w in self.workers):
            self.btn_start.setEnabled(True)
            self.btn_pause.setEnabled(False)
            self.btn_pause.setText("⏸️ Tạm Dừng")
            self.btn_stop.setEnabled(False)
            self.emit_status("Hoàn thành tất cả các tiến trình đăng bài!")

    def update_progress(self, current: int, total: int):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)

    def emit_status(self, msg: str):
        self.status_updated.emit(msg)

    def add_log_row(self, ts: str, profile_label: str, group_name: str, status: str, message: str):
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)

        self.log_table.setItem(row, 0, QTableWidgetItem(ts))
        self.log_table.setItem(row, 1, QTableWidgetItem(profile_label))
        self.log_table.setItem(row, 2, QTableWidgetItem(group_name))

        st_item = QTableWidgetItem(status)
        if status in ["SUCCESS"]:
            st_item.setForeground(Qt.green)
        elif status in ["FAILED", "ERROR"]:
            st_item.setForeground(Qt.red)
        elif status in ["WAITING", "RESTING", "POSTING"]:
            st_item.setForeground(Qt.yellow)
        self.log_table.setItem(row, 3, st_item)

        self.log_table.setItem(row, 4, QTableWidgetItem(message))
        self.log_table.scrollToBottom()
