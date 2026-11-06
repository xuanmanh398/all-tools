import asyncio
import os
import time
import webbrowser
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QSpinBox, QCheckBox, QGroupBox, QMessageBox, QProgressBar, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QFrame,
    QDialog, QFileDialog, QRadioButton, QButtonGroup
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QColor
from core.database import Database
from core.anti_spam import AntiSpamManager, AntiSpamConfig
from core.fb_automation import FBAutomationEngine
from core.excel_loader import (
    get_configured_excel_path,
    set_configured_excel_path,
    get_fresh_media_for_post,
    DEFAULT_EXCEL_PATH
)
from playwright.async_api import async_playwright


class PosterWorker(QThread):
    log_signal = Signal(str, str, str, str, str)  # (timestamp, profile_label, group_name, status, message)
    progress_signal = Signal(int, int)  # (current, total)
    status_text_signal = Signal(str)  # Short status for floating widget / tray
    finished_signal = Signal()

    def __init__(
        self,
        db: Database,
        account_uid: str,
        campaign_id: int,
        anti_config: AntiSpamConfig,
        headless: bool = True,
        post_as_page_name: str = "",
        category: str = "Tất cả lĩnh vực",
        loop_forever: bool = True,
        action_mode: str = "POST_GROUPS",
        min_likes: int = 0,
        human_simulation: bool = True,
        target_urls: list = None,
        browser_channel: str = "chrome"
    ):
        super().__init__()
        self.db = db
        self.account_uid = account_uid
        self.campaign_id = campaign_id
        self.anti_config = anti_config
        self.headless = headless
        self.post_as_page_name = post_as_page_name
        self.category = category
        self.loop_forever = loop_forever
        self.action_mode = action_mode
        self.min_likes = min_likes
        self.human_simulation = human_simulation
        self.target_urls = target_urls or []
        self.browser_channel = browser_channel or "chrome"
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

        accounts = self.db.get_accounts()
        target_acc = next((a for a in accounts if a["uid"] == self.account_uid), None)
        if not target_acc:
            self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", "FAILED", "Không tìm thấy tài khoản trong CSDL!")
            return

        pages = self.db.get_pages(self.account_uid)
        page_obj = next((p for p in pages if p["page_name"] == self.post_as_page_name), None)
        target_page_id = page_obj["page_id"] if page_obj else ""
        page_url = page_obj.get("page_url", "") if page_obj else ""

        campaigns = self.db.get_campaigns()
        campaign_map = {c["id"]: c for c in campaigns}
        target_camp = campaign_map.get(self.campaign_id) if self.campaign_id and self.campaign_id > 0 else None
        if not target_camp and not campaigns:
            self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", "FAILED", "Không tìm thấy mẫu nội dung trong file Excel!")
            return

        # --- CHẾ ĐỘ ĐI BÌNH LUẬN BẢNG TIN FACEBOOK / LINK BÀI VIẾT (LỌC THEO SỐ LIKE TỐI THIỂU) ---
        if self.action_mode == "COMMENT_FEED":
            excel_list = [target_camp] if target_camp else list(campaigns)
            engine = FBAutomationEngine(browser_channel=self.browser_channel)
            self.status_text_signal.emit(f"[{profile_label}] Đang bình luận Facebook (Lọc >= {self.min_likes} Likes)...")
            await engine.run_fb_commenting_session(
                cookie_str=target_acc["cookie"],
                target_urls=self.target_urls,
                excel_posts=excel_list,
                anti_config=self.anti_config,
                proxy=target_acc.get("proxy", ""),
                headless=self.headless,
                uid=self.account_uid,
                post_as_page_name=self.post_as_page_name,
                page_id=target_page_id,
                page_url=page_url,
                min_likes=self.min_likes,
                human_simulation=self.human_simulation,
                is_paused_fn=lambda: self.is_paused,
                is_stopped_fn=lambda: self.is_stopped,
                log_callback=lambda ts, prof, tgt, st, msg: self.log_signal.emit(ts, prof, tgt, st, msg),
                progress_callback=lambda cur, tot: self.progress_signal.emit(cur, tot if tot > 0 else cur)
            )
            self.status_text_signal.emit(f"Hoàn thành tiến trình bình luận Facebook cho [{profile_label}]!")
            return

        selected_groups = self.db.get_groups(
            account_uid=self.account_uid,
            page_id=target_page_id,
            category=self.category,
            only_selected=True
        )
        if not selected_groups:
            cat_desc = f" thuộc lĩnh vực '{self.category}'" if self.category not in ["Tất cả", "Tất cả lĩnh vực", ""] else ""
            self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", "FAILED", f"Không có nhóm nào được chọn{cat_desc}!")
            return

        anti_spam = AntiSpamManager(self.anti_config)
        engine = FBAutomationEngine(browser_channel=self.browser_channel)
        cookies = engine.parse_cookie_string(target_acc["cookie"])

        total_groups = len(selected_groups)
        self.progress_signal.emit(0, total_groups)
        self.status_text_signal.emit(f"Bắt đầu chiến dịch [{profile_label}]: 0/{total_groups} nhóm")

        try:
            excel_cursor = int(self.db.get_setting("fb_excel_cursor", 0) or 0)
        except Exception:
            excel_cursor = 0

        async with async_playwright() as p:
            try:
                browser, context = await engine.create_context(
                    p, cookies, target_acc.get("proxy", ""),
                    headless=self.headless, uid=self.account_uid, page_id=target_page_id
                )
                page = await context.new_page()

                await engine.ensure_active_profile(
                    page=page,
                    uid=self.account_uid,
                    target_page_name=self.post_as_page_name,
                    target_page_id=target_page_id,
                    target_page_url=page_url,
                    logger_callback=lambda level, msg: self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", level, msg)
                )

                cycle_num = 0
                while True:
                    cycle_num += 1
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

                        grp_camp_id = group.get("campaign_id") or 0
                        active_camp = campaign_map.get(grp_camp_id) if grp_camp_id > 0 else target_camp
                        if not active_camp and campaigns:
                            active_camp = campaigns[excel_cursor % len(campaigns)]
                            excel_cursor = (excel_cursor + 1) % len(campaigns)
                            try:
                                self.db.set_setting("fb_excel_cursor", excel_cursor)
                            except Exception:
                                pass

                        camp_title = active_camp["title"] if active_camp else "Mẫu Excel"
                        fresh_media = get_fresh_media_for_post(active_camp)

                        self.log_signal.emit(
                            time.strftime("%H:%M:%S"),
                            profile_label,
                            f"{g_name} [{g_cat}]",
                            "POSTING",
                            f"[Vòng {cycle_num}] Đang đăng '{camp_title}' ({len(fresh_media)} ảnh) vào nhóm ({index}/{total_groups})..."
                        )
                        self.status_text_signal.emit(f"[{profile_label}] Đăng '{camp_title}' ({index}/{total_groups}): {g_name}")

                        success = await engine.post_to_group(
                            page=page,
                            group_url=g_url,
                            content_template=active_camp["content"],
                            media_paths=fresh_media,
                            anti_spam=anti_spam,
                            logger_callback=lambda level, msg: self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, g_name, level, msg),
                            post_as_page_name=self.post_as_page_name,
                            cookie_str=target_acc["cookie"]
                        )

                        if success:
                            self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, g_name, "SUCCESS", f"Đăng bài '{camp_title}' thành công! | {g_url}")
                        else:
                            self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, g_name, "FAILED", f"Đăng bài '{camp_title}' thất bại!")

                        self.progress_signal.emit(index, total_groups)

                        has_more = (index < total_groups) or self.loop_forever
                        if has_more and not self.is_stopped:
                            delay_sec = anti_spam.get_random_delay()
                            self.log_signal.emit(time.strftime("%H:%M:%S"), profile_label, "-", "WAITING", f"Nghỉ {delay_sec} giây trước khi đăng bài tiếp theo...")
                            for _ in range(delay_sec):
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
                                for _ in range(rest_time):
                                    if self.is_stopped:
                                        break
                                    while self.is_paused:
                                        await asyncio.sleep(1)
                                        if self.is_stopped:
                                            break
                                    await asyncio.sleep(1)

                    if self.is_stopped or not self.loop_forever:
                        break
                    self.log_signal.emit(
                        time.strftime("%H:%M:%S"),
                        profile_label,
                        "-",
                        "INFO",
                        f"🔄 Đã hoàn tất vòng #{cycle_num}. Tự động lặp lại vòng #{cycle_num + 1} với mẫu Excel tiếp theo..."
                    )

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

        top_bar = QHBoxLayout()
        cat_desc = f" | Lĩnh vực: {category}" if category not in ["Tất cả", "Tất cả lĩnh vực", ""] else ""
        self.lbl_title = QLabel(f"📋 Mục tiêu đăng: <b>{profile_title}</b>{cat_desc}")
        self.lbl_title.setStyleSheet("font-size: 13px; color: #60a5fa;")
        top_bar.addWidget(self.lbl_title)

        top_bar.addSpacing(15)
        top_bar.addWidget(QLabel("🔍 Tìm kiếm:"))
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Lọc theo tên hoặc ID nhóm...")
        self.txt_search.textChanged.connect(self.load_table)
        top_bar.addWidget(self.txt_search, stretch=1)

        layout.addLayout(top_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Chọn", "ID Nhóm", "Tên Nhóm", "Lĩnh Vực", "Mẫu Nội Dung Gán Riêng", "Link Nhóm"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        bot_bar = QHBoxLayout()
        btn_sel_all = QPushButton("✅ Chọn Tất Cả")
        btn_sel_all.clicked.connect(lambda: self.toggle_all(True))
        bot_bar.addWidget(btn_sel_all)

        btn_desel_all = QPushButton("❌ Bỏ Chọn Tất Cả")
        btn_desel_all.clicked.connect(lambda: self.toggle_all(False))
        bot_bar.addWidget(btn_desel_all)

        btn_sync = QPushButton("🔄 Đồng Bộ Nhóm Giữa Nick & Fanpage")
        btn_sync.setStyleSheet("background-color: #d97706; color: white; font-weight: bold;")
        btn_sync.clicked.connect(self.on_sync)
        bot_bar.addWidget(btn_sync)

        bot_bar.addStretch()

        self.lbl_count = QLabel("Đã chọn: 0 / 0 nhóm")
        self.lbl_count.setStyleSheet("font-weight: bold; color: #10b981;")
        bot_bar.addWidget(self.lbl_count)

        btn_close = QPushButton("💾 Đóng & Áp Dụng")
        btn_close.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 6px 14px;")
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
        else:
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
        self._is_loading_config = False
        self.preview_tpl_idx = 0
        self.success_post_count = 0

        self.init_ui()
        self.load_all_config()
        self.db.clear_logs()
        self.log_table.setRowCount(0)

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

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)

        # =========================================================================
        # PHẦN 1: LƯỚI 3 CỘT CARD CẤU HÌNH (THEO ĐÚNG BỐ CỤC ẢNH 2, BỎ ĐẶT LỊCH)
        # =========================================================================
        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)

        # -------------------------------------------------------------------------
        # CARD 1: 1. NGUỒN & TÀI KHOẢN
        # -------------------------------------------------------------------------
        card1 = self._create_card_frame()
        c1_layout = QVBoxLayout(card1)
        c1_layout.setContentsMargins(16, 14, 16, 14)
        c1_layout.setSpacing(10)

        # Header Card 1
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

        # Chọn Tài Khoản FB
        lbl_acc = QLabel("Chọn Tài Khoản FB")
        lbl_acc.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        c1_layout.addWidget(lbl_acc)

        self.combo_accounts = QComboBox()
        self.combo_accounts.setFixedHeight(36)
        self.combo_accounts.currentIndexChanged.connect(self.on_account_combo_changed)
        c1_layout.addWidget(self.combo_accounts)

        # Đăng bài với tư cách
        lbl_post_as = QLabel("Đăng bài với tư cách")
        lbl_post_as.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        c1_layout.addWidget(lbl_post_as)

        self.combo_post_as = QComboBox()
        self.combo_post_as.setFixedHeight(36)
        self.combo_post_as.currentIndexChanged.connect(self.on_post_as_changed)
        c1_layout.addWidget(self.combo_post_as)

        # Chế Độ Hành Động (2 Tile Chọn Giống Ảnh 2)
        lbl_mode = QLabel("Chế Độ Hành Động")
        lbl_mode.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        c1_layout.addWidget(lbl_mode)

        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(10)

        # Tile 1: Đăng Bài Vào Nhóm
        self.tile_post_groups = QFrame()
        self.tile_post_groups.setCursor(Qt.PointingHandCursor)
        self.tile_post_groups.mousePressEvent = lambda e: self.rad_fb_post_groups.setChecked(True)
        t1_l = QVBoxLayout(self.tile_post_groups)
        t1_l.setContentsMargins(12, 10, 12, 10)
        t1_l.setSpacing(6)
        t1_top = QHBoxLayout()
        lbl_t1_ico = QLabel("📮")
        lbl_t1_ico.setStyleSheet("font-size: 15px; border: none; background: transparent;")
        t1_top.addWidget(lbl_t1_ico)
        t1_top.addStretch()
        self.rad_fb_post_groups = QRadioButton()
        self.rad_fb_post_groups.setChecked(True)
        self.rad_fb_post_groups.setStyleSheet("border: none; background: transparent;")
        t1_top.addWidget(self.rad_fb_post_groups)
        t1_l.addLayout(t1_top)
        lbl_t1_txt = QLabel("Đăng Bài Vào Nhóm")
        lbl_t1_txt.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 12px; border: none; background: transparent;")
        t1_l.addWidget(lbl_t1_txt)
        tiles_row.addWidget(self.tile_post_groups, 1)

        # Tile 2: Bình Luận Bảng Tin
        self.tile_comment_feed = QFrame()
        self.tile_comment_feed.setCursor(Qt.PointingHandCursor)
        self.tile_comment_feed.mousePressEvent = lambda e: self.rad_fb_comment_feed.setChecked(True)
        t2_l = QVBoxLayout(self.tile_comment_feed)
        t2_l.setContentsMargins(12, 10, 12, 10)
        t2_l.setSpacing(6)
        t2_top = QHBoxLayout()
        lbl_t2_ico = QLabel("💬")
        lbl_t2_ico.setStyleSheet("font-size: 15px; border: none; background: transparent;")
        t2_top.addWidget(lbl_t2_ico)
        t2_top.addStretch()
        self.rad_fb_comment_feed = QRadioButton()
        self.rad_fb_comment_feed.setStyleSheet("border: none; background: transparent;")
        t2_top.addWidget(self.rad_fb_comment_feed)
        t2_l.addLayout(t2_top)
        lbl_t2_txt = QLabel("Bình Luận Bảng Tin")
        lbl_t2_txt.setStyleSheet("color: #cbd5e1; font-weight: bold; font-size: 12px; border: none; background: transparent;")
        t2_l.addWidget(lbl_t2_txt)
        tiles_row.addWidget(self.tile_comment_feed, 1)

        self.fb_mode_group = QButtonGroup(self)
        self.fb_mode_group.addButton(self.rad_fb_post_groups)
        self.fb_mode_group.addButton(self.rad_fb_comment_feed)
        self.rad_fb_post_groups.toggled.connect(self.on_fb_action_mode_changed)

        c1_layout.addLayout(tiles_row)

        # Khung lọc số Like tối thiểu (Hiện khi chọn Bình Luận Bảng Tin)
        self.fb_comment_widget = self._create_inner_box()
        fb_cw_layout = QVBoxLayout(self.fb_comment_widget)
        fb_cw_layout.setContentsMargins(10, 8, 10, 8)
        fb_cw_layout.setSpacing(6)

        fb_like_row = QHBoxLayout()
        fb_like_row.setSpacing(4)
        lbl_fb_min_likes = QLabel("👍 Like tối thiểu:")
        lbl_fb_min_likes.setStyleSheet("color: #60a5fa; font-weight: bold; font-size: 11px; border: none; background: transparent;")
        fb_like_row.addWidget(lbl_fb_min_likes)

        saved_fb_min_likes = int(self.db.get_setting("fb_min_likes", 100) or 0)
        self.spin_fb_min_likes = QSpinBox()
        self.spin_fb_min_likes.setRange(0, 1000000)
        self.spin_fb_min_likes.setSingleStep(50)
        self.spin_fb_min_likes.setValue(saved_fb_min_likes)
        self.spin_fb_min_likes.setSuffix(" Likes")
        self.spin_fb_min_likes.setFixedHeight(26)
        self.spin_fb_min_likes.setStyleSheet("font-weight: bold; color: #f8fafc; background-color: #111827; padding: 2px 6px; border: 1px solid #2563eb; border-radius: 4px; font-size: 11px;")
        self.spin_fb_min_likes.valueChanged.connect(self.save_all_config)
        fb_like_row.addWidget(self.spin_fb_min_likes)

        for preset_val, preset_lbl in [(0, "0"), (50, "50+"), (100, "100+"), (500, "500+"), (1000, "1K+")]:
            btn_p = QPushButton(preset_lbl)
            btn_p.setCursor(Qt.PointingHandCursor)
            btn_p.setFixedHeight(24)
            btn_p.setStyleSheet("background-color: #1e293b; color: #cbd5e1; padding: 1px 6px; font-size: 10px; border-radius: 4px; border: 1px solid #334155;")
            btn_p.clicked.connect(lambda _, v=preset_val: self.spin_fb_min_likes.setValue(v))
            fb_like_row.addWidget(btn_p)
        fb_cw_layout.addLayout(fb_like_row)

        self.txt_fb_target_urls = QLineEdit()
        self.txt_fb_target_urls.setPlaceholderText("Link bài viết cụ thể (Để trống = Tự lướt Bảng tin FB)")
        self.txt_fb_target_urls.setFixedHeight(26)
        self.txt_fb_target_urls.setStyleSheet("background-color: #111827; color: #cbd5e1; padding: 2px 8px; border: 1px solid #1e293b; border-radius: 4px; font-size: 11px;")
        fb_cw_layout.addWidget(self.txt_fb_target_urls)

        self.fb_comment_widget.setVisible(False)
        c1_layout.addWidget(self.fb_comment_widget)

        # ANTI-SPAM & BẢO MẬT
        lbl_sec = QLabel("ANTI-SPAM & BẢO MẬT")
        lbl_sec.setStyleSheet("color: #64748b; font-size: 10px; font-weight: bold; letter-spacing: 0.5px; border: none; background: transparent; margin-top: 2px;")
        c1_layout.addWidget(lbl_sec)

        self.chk_fb_human_sim = QCheckBox("Chống xác minh con người / Checkpoint tự động")
        self.chk_fb_human_sim.setChecked(True)
        self.chk_fb_human_sim.toggled.connect(self.save_all_config)
        c1_layout.addWidget(self._create_check_row(self.chk_fb_human_sim))

        self.chk_shuffle_media = QCheckBox("Xáo trộn thứ tự hình ảnh/video ngẫu nhiên")
        self.chk_shuffle_media.setChecked(True)
        self.chk_shuffle_media.toggled.connect(self.save_all_config)
        c1_layout.addWidget(self._create_check_row(self.chk_shuffle_media))

        self.chk_hash = QCheckBox("Thêm mã Hash ngẫu nhiên cuối bài")
        self.chk_hash.toggled.connect(self.save_all_config)
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

        # Header Card 2
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

        btn_spin_test = QPushButton("🔀 Xem Biến Spintax")
        btn_spin_test.setCursor(Qt.PointingHandCursor)
        btn_spin_test.setStyleSheet("""
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
        btn_spin_test.clicked.connect(self.on_preview_campaign_spin)
        c2_header.addWidget(btn_spin_test)
        c2_layout.addLayout(c2_header)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        c2_layout.addWidget(sep2)

        # Box Chọn File Excel
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
        btn_pick_excel = QPushButton("📄  Chọn File Excel")
        btn_pick_excel.setCursor(Qt.PointingHandCursor)
        btn_pick_excel.setFixedHeight(34)
        btn_pick_excel.setStyleSheet("""
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
        btn_pick_excel.clicked.connect(self.on_pick_excel_file)
        eb_btns.addWidget(btn_pick_excel, 1)

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
        btn_reload_excel.clicked.connect(self.load_all_config)
        eb_btns.addWidget(btn_reload_excel)
        eb_layout.addLayout(eb_btns)

        self.combo_campaigns = QComboBox()
        self.combo_campaigns.setVisible(False)
        self.combo_campaigns.currentIndexChanged.connect(self.save_all_config)
        self.combo_campaigns.currentIndexChanged.connect(self.update_campaign_preview)
        eb_layout.addWidget(self.combo_campaigns)

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

        # Khung Social Post Preview (Giống hệt Ảnh 2)
        social_preview_box = self._create_inner_box()
        sp_layout = QVBoxLayout(social_preview_box)
        sp_layout.setContentsMargins(12, 10, 12, 10)
        sp_layout.setSpacing(6)

        # Dòng Avatar FB + Tên tư cách đăng
        sp_author_row = QHBoxLayout()
        sp_author_row.setSpacing(8)
        lbl_fb_ava = QLabel("FB")
        lbl_fb_ava.setFixedSize(24, 24)
        lbl_fb_ava.setAlignment(Qt.AlignCenter)
        lbl_fb_ava.setStyleSheet("background-color: #1e3a8a; color: #60a5fa; font-weight: bold; font-size: 10px; border-radius: 12px; border: none;")
        sp_author_row.addWidget(lbl_fb_ava)

        self.lbl_preview_author = QLabel("Nick Cá Nhân")
        self.lbl_preview_author.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 12px; border: none; background: transparent;")
        sp_author_row.addWidget(self.lbl_preview_author)
        sp_author_row.addStretch()
        sp_layout.addLayout(sp_author_row)

        # Nội dung bài viết mẫu
        self.txt_camp_preview = QTextEdit()
        self.txt_camp_preview.setReadOnly(True)
        self.txt_camp_preview.setFont(QFont("Segoe UI Emoji", 10))
        self.txt_camp_preview.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                color: #cbd5e1;
                font-size: 12px;
                line-height: 1.45;
                padding: 2px 0px;
                border: none;
            }
        """)
        self.txt_camp_preview.setMinimumHeight(95)
        sp_layout.addWidget(self.txt_camp_preview, 1)

        sp_sep = QFrame()
        sp_sep.setFrameShape(QFrame.HLine)
        sp_sep.setStyleSheet("background-color: #1e293b; border: none; max-height: 1px;")
        sp_layout.addWidget(sp_sep)

        # Footer: Đường dẫn ảnh bên trái | Spintax Active bên phải
        sp_footer = QHBoxLayout()
        self.lbl_camp_preview_info = QLabel("Đường dẫn ảnh: -")
        self.lbl_camp_preview_info.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        sp_footer.addWidget(self.lbl_camp_preview_info, 1)

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

        # Header Card 3
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

        # Box Nhóm Target & Delay
        target_box = self._create_inner_box()
        tb_layout = QVBoxLayout(target_box)
        tb_layout.setContentsMargins(12, 10, 12, 10)
        tb_layout.setSpacing(8)

        tb_top = QHBoxLayout()
        self.lbl_group_count = QLabel("Nhóm Target (0 Nhóm)")
        self.lbl_group_count.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 12px; border: none; background: transparent;")
        tb_top.addWidget(self.lbl_group_count)
        tb_top.addStretch()

        self.btn_manage_groups = QPushButton("📋 Chọn nhóm")
        self.btn_manage_groups.setCursor(Qt.PointingHandCursor)
        self.btn_manage_groups.setFixedHeight(26)
        self.btn_manage_groups.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #60a5fa;
                border: 1px solid #334155;
                border-radius: 5px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)
        self.btn_manage_groups.clicked.connect(self.open_group_selection_dialog)
        tb_top.addWidget(self.btn_manage_groups)

        self.btn_quick_sync = QPushButton("🔄 Đồng bộ")
        self.btn_quick_sync.setCursor(Qt.PointingHandCursor)
        self.btn_quick_sync.setFixedHeight(26)
        self.btn_quick_sync.setToolTip("Đồng bộ danh sách nhóm giữa Nick cá nhân và tất cả Fanpage")
        self.btn_quick_sync.setStyleSheet("""
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
        self.btn_quick_sync.clicked.connect(self.quick_sync_groups)
        tb_top.addWidget(self.btn_quick_sync)
        tb_layout.addLayout(tb_top)

        # Lĩnh vực nhóm (ẩn gọn nếu chỉ có Tất cả lĩnh vực hoặc chọn nhanh)
        cat_row = QHBoxLayout()
        lbl_cat = QLabel("Lĩnh vực:")
        lbl_cat.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        cat_row.addWidget(lbl_cat)
        self.combo_category = QComboBox()
        self.combo_category.setFixedHeight(28)
        self.combo_category.setStyleSheet("background-color: #111827; border: 1px solid #1e293b; border-radius: 5px; font-size: 11px; padding: 2px 8px;")
        self.combo_category.currentIndexChanged.connect(self.on_category_changed)
        cat_row.addWidget(self.combo_category, 1)
        tb_layout.addLayout(cat_row)

        # Hàng nhãn Delay & Nghỉ
        delay_lbl_row = QHBoxLayout()
        lbl_dl = QLabel("Delay giữa 2 nhóm (s)")
        lbl_dl.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        delay_lbl_row.addWidget(lbl_dl, 1)
        lbl_rst = QLabel("Nghỉ (Phút) / Sau số bài")
        lbl_rst.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        delay_lbl_row.addWidget(lbl_rst, 1)
        tb_layout.addLayout(delay_lbl_row)

        # Hàng 4 ô SpinBox (Giống hệt Ảnh 2: [ 46 ] đến [ 120 ] | [ 10 ] [ 5 ])
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
        self.spin_delay_min.setRange(5, 600)
        self.spin_delay_min.setValue(46)
        self.spin_delay_min.setAlignment(Qt.AlignCenter)
        self.spin_delay_min.setFixedHeight(32)
        self.spin_delay_min.setStyleSheet(spin_css)
        self.spin_delay_min.valueChanged.connect(self.save_all_config)
        delay_inp_row.addWidget(self.spin_delay_min, 1)

        lbl_den = QLabel("đến")
        lbl_den.setAlignment(Qt.AlignCenter)
        lbl_den.setStyleSheet("color: #64748b; font-size: 11px; border: none; background: transparent;")
        delay_inp_row.addWidget(lbl_den)

        self.spin_delay_max = QSpinBox()
        self.spin_delay_max.setRange(10, 1200)
        self.spin_delay_max.setValue(120)
        self.spin_delay_max.setAlignment(Qt.AlignCenter)
        self.spin_delay_max.setFixedHeight(32)
        self.spin_delay_max.setStyleSheet(spin_css)
        self.spin_delay_max.valueChanged.connect(self.save_all_config)
        delay_inp_row.addWidget(self.spin_delay_max, 1)

        delay_inp_row.addSpacing(6)

        self.spin_rest_min = QSpinBox()
        self.spin_rest_min.setRange(1, 120)
        self.spin_rest_min.setValue(10)
        self.spin_rest_min.setAlignment(Qt.AlignCenter)
        self.spin_rest_min.setFixedHeight(32)
        self.spin_rest_min.setStyleSheet(spin_css)
        self.spin_rest_min.valueChanged.connect(self.save_all_config)
        delay_inp_row.addWidget(self.spin_rest_min, 1)

        self.spin_rest_after = QSpinBox()
        self.spin_rest_after.setRange(1, 50)
        self.spin_rest_after.setValue(5)
        self.spin_rest_after.setAlignment(Qt.AlignCenter)
        self.spin_rest_after.setFixedHeight(32)
        self.spin_rest_after.setStyleSheet(spin_css)
        self.spin_rest_after.valueChanged.connect(self.save_all_config)
        delay_inp_row.addWidget(self.spin_rest_after, 1)

        tb_layout.addLayout(delay_inp_row)
        c3_layout.addWidget(target_box)

        # Chế Độ Trình Duyệt
        lbl_br_mode = QLabel("Chế Độ Trình Duyệt")
        lbl_br_mode.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        c3_layout.addWidget(lbl_br_mode)

        self.combo_browser_mode = QComboBox()
        self.combo_browser_mode.setFixedHeight(36)
        self.combo_browser_mode.addItem("Hiển thị Trình Duyệt (Quan sát trực tiếp)", False)
        self.combo_browser_mode.addItem("Chạy Ngầm Hệ Thống (Tự động ẩn trình duyệt)", True)
        self.combo_browser_mode.currentIndexChanged.connect(self.save_all_config)
        c3_layout.addWidget(self.combo_browser_mode)

        lbl_engine = QLabel("🌐 Trình Duyệt Chạy:")
        lbl_engine.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        c3_layout.addWidget(lbl_engine)

        self.combo_browser_engine = QComboBox()
        self.combo_browser_engine.setFixedHeight(36)
        self.combo_browser_engine.addItem("🌐 Google Chrome (Mặc định FB - Chạy song song độc lập)", "chrome")
        self.combo_browser_engine.addItem("🌐 Microsoft Edge", "msedge")
        self.combo_browser_engine.addItem("🌐 Playwright Chromium", "chromium")
        c3_layout.addWidget(self.combo_browser_engine)

        # Các Checkbox tuỳ chọn tiến trình (Giống Ảnh 2)
        self.chk_loop_forever = QCheckBox("Đăng vòng lặp liên tục (1 ➔ N ➔ 1)")
        self.chk_loop_forever.setChecked(True)
        self.chk_loop_forever.toggled.connect(self.save_all_config)
        c3_layout.addWidget(self._create_check_row(self.chk_loop_forever))

        self.chk_combine_comment_imgs = QCheckBox("Ghép toàn bộ ảnh trong Folder khi bình luận FB")
        self.chk_combine_comment_imgs.setChecked(True)
        self.chk_combine_comment_imgs.toggled.connect(self.save_all_config)
        c3_layout.addWidget(self._create_check_row(self.chk_combine_comment_imgs))

        c3_layout.addStretch()
        cards_row.addWidget(card3, 1)

        main_layout.addLayout(cards_row)

        # =========================================================================
        # PHẦN 2: THANH TIẾN TRÌNH TỔNG THỂ & CỤM NÚT ĐIỀU KHIỂN (GIỐNG HỆT ẢNH 2)
        # =========================================================================
        exec_card = self._create_card_frame()
        exec_card.setFixedHeight(64)
        e_layout = QHBoxLayout(exec_card)
        e_layout.setContentsMargins(18, 10, 18, 10)
        e_layout.setSpacing(20)

        # Cột trái: Tiến trình tổng thể + Thanh Progress mỏng
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

        # Cụm 3 nút điều khiển bên phải: ▶ BẮT ĐẦU CHẠY | ⏸ Tạm Dừng | ⏹ Dừng Hẳn
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
        self.btn_pause.clicked.connect(self.on_toggle_pause)
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
        # PHẦN 3: BẢNG CHI TIẾT THÔNG BÁO & LỊCH SỬ HOẠT ĐỘNG (GIỐNG HỆT ẢNH 2)
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
        self.log_table.setHorizontalHeaderLabels(["THỜI GIAN", "TƯ CÁCH ĐĂNG", "NHÓM TARGET", "TRẠNG THÁI", "CHI TIẾT"])
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setShowGrid(False)
        self.log_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.log_table.setColumnWidth(2, 270)
        self.log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.log_table.cellClicked.connect(self.on_log_cell_clicked)
        log_layout.addWidget(self.log_table, 1)

        main_layout.addWidget(log_card, 1)

        self._update_action_tile_styles()

    def _update_action_tile_styles(self):
        is_comment = self.rad_fb_comment_feed.isChecked()
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
        self.tile_post_groups.setStyleSheet(inactive_tile_css if is_comment else active_tile_css)
        self.tile_comment_feed.setStyleSheet(active_tile_css if is_comment else inactive_tile_css)

    def load_combos(self):
        self.load_all_config()

    def on_account_combo_changed(self):
        self.update_pages_combo()
        self.save_all_config()

    def on_post_as_changed(self):
        self.update_categories_combo()
        self.update_campaign_preview()
        self.save_all_config()

    def on_category_changed(self):
        self.update_group_count_label()
        self.save_all_config()

    def on_fb_action_mode_changed(self):
        is_comment = self.rad_fb_comment_feed.isChecked()
        self.fb_comment_widget.setVisible(is_comment)
        self._update_action_tile_styles()
        self.save_all_config()

    def update_pages_combo(self, desired_page_id=None, desired_mode=None):
        self.combo_post_as.blockSignals(True)
        self.combo_post_as.clear()
        self.combo_post_as.addItem("Nick Cá Nhân (Mặc định)", {"page_id": "", "page_name": "", "mode": "SINGLE"})
        acc_uid = self.combo_accounts.currentData()
        target_idx = 0
        if acc_uid:
            pages = self.db.get_pages(acc_uid)
            for p in pages:
                self.combo_post_as.addItem(f"Fanpage: {p['page_name']}", {"page_id": p["page_id"], "page_name": p["page_name"], "mode": "SINGLE"})
                if desired_mode == "SINGLE" and desired_page_id == p["page_id"]:
                    target_idx = self.combo_post_as.count() - 1
            if pages:
                self.combo_post_as.addItem("🔥 TẤT CẢ FANPAGE (Chạy Đa Luồng Song Song)", {"mode": "ALL_PAGES"})
                if desired_mode == "ALL_PAGES":
                    target_idx = self.combo_post_as.count() - 1
                self.combo_post_as.addItem("🔥 NICK CÁ NHÂN + TẤT CẢ FANPAGE (Chạy Song Song)", {"mode": "ALL_PROFILES"})
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

        self.lbl_group_count.setText(f"Nhóm Target ({total} Nhóm)")

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

    def on_prev_template(self):
        campaigns = self.db.get_campaigns()
        if not campaigns:
            return
        self.preview_tpl_idx = (self.preview_tpl_idx - 1) % len(campaigns)
        self.update_campaign_preview()

    def on_next_template(self):
        campaigns = self.db.get_campaigns()
        if not campaigns:
            return
        self.preview_tpl_idx = (self.preview_tpl_idx + 1) % len(campaigns)
        self.update_campaign_preview()

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
            "fb_action_mode": "COMMENT_FEED" if self.rad_fb_comment_feed.isChecked() else "POST_GROUPS",
            "fb_min_likes": self.spin_fb_min_likes.value(),
            "fb_human_sim": self.chk_fb_human_sim.isChecked(),
            "category": self.combo_category.currentText() or "Tất cả lĩnh vực",
            "campaign_id": -1,
            "delay_min": self.spin_delay_min.value(),
            "delay_max": self.spin_delay_max.value(),
            "rest_min": self.spin_rest_min.value(),
            "rest_after": self.spin_rest_after.value(),
            "browser_headless": bool(self.combo_browser_mode.currentData()),
            "chk_hash": self.chk_hash.isChecked(),
            "chk_shuffle_media": self.chk_shuffle_media.isChecked(),
            "chk_loop_forever": self.chk_loop_forever.isChecked()
        }
        self.db.set_setting("poster_config", config)
        self.db.set_setting("fb_min_likes", config["fb_min_likes"])

    def load_all_config(self):
        self._is_loading_config = True
        try:
            config = self.db.get_setting("poster_config", {})

            # 1. Nạp danh sách tài khoản
            accounts = self.db.get_accounts()
            cur_acc = config.get("account_uid") or self.combo_accounts.currentData()
            self.combo_accounts.blockSignals(True)
            self.combo_accounts.clear()
            acc_idx = 0
            for i, a in enumerate(accounts):
                pages_cnt = len(self.db.get_pages(a['uid']))
                suffix = " [Multi-Account]" if pages_cnt > 0 else ""
                self.combo_accounts.addItem(f"{a['name']} ({a['uid']}){suffix}", a['uid'])
                if cur_acc and a['uid'] == cur_acc:
                    acc_idx = i
            if accounts:
                self.combo_accounts.setCurrentIndex(acc_idx)
            self.combo_accounts.blockSignals(False)

            # 2. Nạp danh sách mẫu nội dung từ file Excel
            campaigns = self.db.get_campaigns()
            self.combo_campaigns.blockSignals(True)
            self.combo_campaigns.clear()
            excel_path = get_configured_excel_path(self.db)
            self.combo_campaigns.addItem(
                f"🔁 [Xoay Vòng Tất Cả {len(campaigns)} Mẫu Trong '{os.path.basename(excel_path)}']",
                -1
            )
            for c in campaigns:
                self.combo_campaigns.addItem(c["title"], c["id"])
            self.combo_campaigns.setCurrentIndex(0)
            self.combo_campaigns.blockSignals(False)

            self.lbl_excel_badge.setText(f"{len(campaigns)} Mẫu sẵn sàng")

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
            if "chk_loop_forever" in config:
                self.chk_loop_forever.setChecked(bool(config["chk_loop_forever"]))

            if "fb_action_mode" in config:
                if config["fb_action_mode"] == "COMMENT_FEED":
                    self.rad_fb_comment_feed.setChecked(True)
                else:
                    self.rad_fb_post_groups.setChecked(True)
                self.on_fb_action_mode_changed()
            if "fb_min_likes" in config:
                self.spin_fb_min_likes.setValue(int(config["fb_min_likes"]))
            if "fb_human_sim" in config:
                self.chk_fb_human_sim.setChecked(bool(config["fb_human_sim"]))

            self.update_group_count_label()
            self.update_campaign_preview()
        finally:
            self._is_loading_config = False

    def on_pick_excel_file(self):
        cur_path = get_configured_excel_path(self.db)
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
            set_configured_excel_path(self.db, file_path)
            self.preview_tpl_idx = 0
            self.load_all_config()

    def update_campaign_preview(self):
        page_info = self.combo_post_as.currentData() or {}
        p_name = page_info.get("page_name", "") if isinstance(page_info, dict) else ""
        mode = page_info.get("mode", "SINGLE") if isinstance(page_info, dict) else "SINGLE"
        if mode == "ALL_PAGES":
            author_str = "Tất cả Fanpage"
        elif mode == "ALL_PROFILES":
            author_str = "Nick cá nhân + Tất cả Fanpage"
        elif p_name:
            author_str = f"Fanpage: {p_name}"
        else:
            author_str = "Nick Cá Nhân"
        self.lbl_preview_author.setText(author_str)

        campaigns = self.db.get_campaigns()
        excel_path = get_configured_excel_path(self.db)
        if not campaigns:
            self.lbl_preview_title.setText("Xem Trước Bài Viết (Chưa có mẫu)")
            self.lbl_tpl_counter.setText("0 / 0")
            self.txt_camp_preview.setPlainText(f"⚠️ Chưa có mẫu bài viết nào trong file Excel:\n{excel_path}")
            self.lbl_camp_preview_info.setText("Đường dẫn ảnh: (Trống)")
            return

        if self.preview_tpl_idx >= len(campaigns):
            self.preview_tpl_idx = 0

        camp = campaigns[self.preview_tpl_idx]
        idx_1 = self.preview_tpl_idx + 1
        self.lbl_preview_title.setText(f"Xem Trước Bài Viết (Mẫu #{idx_1})")
        self.lbl_tpl_counter.setText(f"{idx_1} / {len(campaigns)}")

        content = camp.get("content", "")
        media_count = len(camp.get("raw_media_paths") or camp.get("media_paths") or [])
        folder_str = camp.get("folder_path", "")
        self.txt_camp_preview.setPlainText(content)
        self.lbl_camp_preview_info.setText(f"Đường dẫn ảnh: {folder_str} ({media_count} ảnh)")

    def on_preview_campaign_spin(self):
        content = self.txt_camp_preview.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "Thông Báo", "Chưa có nội dung bài viết để xem thử biến thể!")
            return
        from core.spintax_parser import SpintaxParser
        parsed = SpintaxParser.parse(content)
        QMessageBox.information(self, "Xem Thử Biến Thể Bài Viết (Spintax Preview)", parsed)

    def on_start(self):
        acc_uid = self.combo_accounts.currentData()
        camp_id = -1  # Mặc định xoay vòng lần lượt toàn bộ mẫu trong file Excel
        page_info = self.combo_post_as.currentData() or {}
        mode = page_info.get("mode", "SINGLE") if isinstance(page_info, dict) else "SINGLE"
        category = self.combo_category.currentText()

        if not acc_uid:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn tài khoản Facebook!")
            return

        campaigns = self.db.get_campaigns()
        if not campaigns:
            QMessageBox.warning(self, "Cảnh báo", "Không tìm thấy mẫu nội dung nào trong file Excel! Vui lòng kiểm tra lại file Excel.")
            return

        target_configs = []
        all_pages = self.db.get_pages(acc_uid)
        action_mode = "COMMENT_FEED" if self.rad_fb_comment_feed.isChecked() else "POST_GROUPS"
        min_likes = self.spin_fb_min_likes.value()
        human_sim = self.chk_fb_human_sim.isChecked()
        raw_urls = [u.strip() for u in self.txt_fb_target_urls.text().replace("\n", ",").split(",") if u.strip()]

        if action_mode == "COMMENT_FEED":
            if mode == "SINGLE":
                page_id = page_info.get("page_id", "")
                page_name = page_info.get("page_name", "")
                target_configs.append({"page_id": page_id, "page_name": page_name})
            elif mode == "ALL_PAGES":
                for p in all_pages:
                    target_configs.append({"page_id": p["page_id"], "page_name": p["page_name"]})
                if not target_configs:
                    target_configs.append({"page_id": "", "page_name": ""})
            elif mode == "ALL_PROFILES":
                target_configs.append({"page_id": "", "page_name": ""})
                for p in all_pages:
                    target_configs.append({"page_id": p["page_id"], "page_name": p["page_name"]})
        elif mode == "SINGLE":
            page_id = page_info.get("page_id", "")
            page_name = page_info.get("page_name", "")
            groups = self.db.get_groups(account_uid=acc_uid, page_id=page_id, category=category, only_selected=True)
            if not groups:
                all_acc_groups = self.db.get_groups(account_uid=acc_uid, only_selected=True)
                if all_acc_groups:
                    target_desc = f"Fanpage '{page_name}'" if page_name else "Nick cá nhân"
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
                QMessageBox.warning(self, "Cảnh báo", f"Chưa chọn nhóm nào{cat_desc} cho {target_desc}!")
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
                QMessageBox.warning(self, "Cảnh báo", "Không tìm thấy Fanpage nào có tích chọn nhóm để đăng!")
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
                QMessageBox.warning(self, "Cảnh báo", "Không tìm thấy Nick cá nhân hay Fanpage nào có tích chọn nhóm!")
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
        self.success_post_count = 0
        self.lbl_success_counter.setText("●  Đã đăng 0 bài thành công")
        self.progress_bar.setValue(0)
        self.lbl_progress_pct.setText("0% (Đang chạy...)")
        self.workers = []

        headless_mode = bool(self.combo_browser_mode.currentData())
        loop_forever = self.chk_loop_forever.isChecked()
        browser_channel = self.combo_browser_engine.currentData() or "chrome"

        for cfg in target_configs:
            w = PosterWorker(
                db=self.db,
                account_uid=acc_uid,
                campaign_id=camp_id,
                anti_config=anti_config,
                headless=headless_mode,
                post_as_page_name=cfg["page_name"],
                category=category,
                loop_forever=loop_forever,
                action_mode=action_mode,
                min_likes=min_likes,
                human_simulation=human_sim,
                target_urls=raw_urls,
                browser_channel=browser_channel
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
            self.btn_pause.setText("⏸   Tạm Dừng")
        else:
            self.btn_pause.setText("▶   Tiếp Tục")

    def on_stop(self):
        for w in self.workers:
            w.stop()

    def on_worker_finished(self):
        if all(not w.isRunning() for w in self.workers):
            self.btn_start.setEnabled(True)
            self.btn_pause.setEnabled(False)
            self.btn_pause.setText("⏸   Tạm Dừng")
            self.btn_stop.setEnabled(False)
            self.progress_bar.setValue(100)
            self.lbl_progress_pct.setText("100% (Hoàn thành)")
            self.emit_status("Hoàn thành tất cả các tiến trình đăng bài!")

    def update_progress(self, current: int, total: int):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)
            status_suffix = "Hoàn thành" if pct >= 100 else f"{current}/{total}"
            self.lbl_progress_pct.setText(f"{pct}% ({status_suffix})")
        elif current > 0:
            self.progress_bar.setValue(min(100, current * 10))
            self.lbl_progress_pct.setText(f"Đã xử lý {current} bài")

    def emit_status(self, msg: str):
        self.lbl_log_status.setText(f"Trạng thái: {msg}")
        self.status_updated.emit(msg)

    def on_log_cell_clicked(self, row: int, col: int):
        for check_col in (2, 4):
            item = self.log_table.item(row, check_col)
            if item:
                url = item.data(Qt.UserRole) or ""
                if not url:
                    txt = item.text().strip()
                    if "http://" in txt or "https://" in txt:
                        for part in txt.split():
                            if part.startswith("http://") or part.startswith("https://"):
                                url = part.strip()
                                break
                if url and url.startswith("http"):
                    if col in (2, 4):
                        webbrowser.open(url)
                        return

    def add_log_row(self, ts: str, profile_label: str, group_name: str, status: str, message: str):
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)

        ts_item = QTableWidgetItem(ts)
        ts_item.setForeground(QColor("#64748b"))
        self.log_table.setItem(row, 0, ts_item)

        prof_item = QTableWidgetItem(profile_label)
        prof_item.setForeground(QColor("#f8fafc"))
        font_bold = prof_item.font()
        font_bold.setBold(True)
        prof_item.setFont(font_bold)
        self.log_table.setItem(row, 1, prof_item)

        grp_item = QTableWidgetItem(group_name)
        if group_name.startswith("http"):
            grp_item.setData(Qt.UserRole, group_name)
            grp_item.setForeground(QColor("#60a5fa"))
        else:
            grp_item.setForeground(QColor("#94a3b8"))
        self.log_table.setItem(row, 2, grp_item)

        if status == "SUCCESS":
            self.success_post_count += 1
            self.lbl_success_counter.setText(f"●  Đã đăng {self.success_post_count} bài thành công")
            st_item = QTableWidgetItem("Thành công")
            st_item.setForeground(QColor("#10b981"))
        elif status in ["FAILED", "ERROR"]:
            st_item = QTableWidgetItem("Thất bại")
            st_item.setForeground(QColor("#ef4444"))
        elif status == "POSTING":
            st_item = QTableWidgetItem("Đang xử lý")
            st_item.setForeground(QColor("#38bdf8"))
        elif status in ["WAITING", "RESTING"]:
            st_item = QTableWidgetItem("Đang nghỉ")
            st_item.setForeground(QColor("#f59e0b"))
        else:
            st_item = QTableWidgetItem(status)
            st_item.setForeground(QColor("#94a3b8"))
        st_item.setFont(font_bold)
        self.log_table.setItem(row, 3, st_item)

        # Kiểm tra xem có URL trong message hoặc group_name để hiển thị "Xem bài viết" giống Ảnh 2
        extracted_url = ""
        if group_name.startswith("http"):
            extracted_url = group_name
        for token in message.split():
            if token.startswith("http://") or token.startswith("https://"):
                extracted_url = token.strip()
                break

        detail_item = QTableWidgetItem(message)
        if extracted_url:
            detail_item.setData(Qt.UserRole, extracted_url)
            detail_item.setToolTip(f"Nhấn để mở bài viết: {extracted_url}")
            if status == "SUCCESS":
                detail_item.setForeground(QColor("#3b82f6"))
        self.log_table.setItem(row, 4, detail_item)
        self.log_table.scrollToBottom()
