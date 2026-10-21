import asyncio
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox, QCheckBox,
    QGroupBox, QMessageBox, QProgressDialog, QInputDialog, QLineEdit
)
from PySide6.QtCore import Qt, QThread, Signal
from core.database import Database
from core.fb_automation import FBAutomationEngine


class GroupScanWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(list)

    def __init__(self, cookie_str: str, proxy: str = "", page_id: str = "", page_name: str = "", page_url: str = "", headless: bool = True):
        super().__init__()
        self.cookie_str = cookie_str
        self.proxy = proxy
        self.page_id = page_id
        self.page_name = page_name
        self.page_url = page_url
        self.headless = headless

    def run(self):
        try:
            engine = FBAutomationEngine()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            def callback(msg):
                self.progress_signal.emit(msg)

            groups = loop.run_until_complete(
                engine.scan_groups(
                    self.cookie_str,
                    self.proxy,
                    page_id=self.page_id,
                    page_name=self.page_name,
                    page_url=self.page_url,
                    headless=self.headless,
                    progress_callback=callback
                )
            )
            loop.close()
            self.finished_signal.emit(groups)
        except Exception as e:
            self.progress_signal.emit(f"Lỗi quét nhóm: {str(e)}")
            self.finished_signal.emit([])


class PageScanWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(list)

    def __init__(self, cookie_str: str, proxy: str = "", headless: bool = True):
        super().__init__()
        self.cookie_str = cookie_str
        self.proxy = proxy
        self.headless = headless

    def run(self):
        try:
            engine = FBAutomationEngine()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            def callback(msg):
                self.progress_signal.emit(msg)

            pages = loop.run_until_complete(engine.scan_pages(self.cookie_str, self.proxy, headless=self.headless, progress_callback=callback))
            loop.close()
            self.finished_signal.emit(pages)
        except Exception as e:
            self.progress_signal.emit(f"Lỗi quét Fanpage: {str(e)}")
            self.finished_signal.emit([])


class InteractivePageSwitchWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(dict)

    def __init__(self, cookie_str: str, proxy: str = "", page_id: str = "", page_name: str = "", page_url: str = ""):
        super().__init__()
        self.cookie_str = cookie_str
        self.proxy = proxy
        self.page_id = page_id
        self.page_name = page_name
        self.page_url = page_url

    def run(self):
        try:
            engine = FBAutomationEngine()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            def callback(msg):
                self.progress_signal.emit(msg)

            res = loop.run_until_complete(
                engine.interactive_switch_page(
                    self.cookie_str,
                    self.proxy,
                    page_id=self.page_id,
                    page_name=self.page_name,
                    page_url=self.page_url,
                    progress_callback=callback
                )
            )
            loop.close()
            self.finished_signal.emit(res)
        except Exception as e:
            self.finished_signal.emit({"success": False, "message": f"Lỗi chuyển Fanpage: {str(e)}"})


class InteractiveJoinGroupWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(dict)

    def __init__(self, cookie_str: str, proxy: str = "", category_name: str = "Mặc định", page_id: str = "", page_name: str = "", page_url: str = ""):
        super().__init__()
        self.cookie_str = cookie_str
        self.proxy = proxy
        self.category_name = category_name
        self.page_id = page_id
        self.page_name = page_name
        self.page_url = page_url

    def run(self):
        try:
            engine = FBAutomationEngine()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            def callback(msg):
                self.progress_signal.emit(msg)

            res = loop.run_until_complete(
                engine.interactive_join_groups_by_category(
                    self.cookie_str,
                    self.proxy,
                    category_name=self.category_name,
                    page_id=self.page_id,
                    page_name=self.page_name,
                    page_url=self.page_url,
                    progress_callback=callback
                )
            )
            loop.close()
            self.finished_signal.emit(res)
        except Exception as e:
            self.finished_signal.emit({"success": False, "message": f"Lỗi tham gia nhóm: {str(e)}"})


class GroupTab(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.init_ui()
        self.load_accounts_combo()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Top Control Box
        top_box = QGroupBox("Quản Lý & Quét Nhóm Đã Tham Gia (Nick Cá Nhân / Fanpage)")
        top_layout = QVBoxLayout(top_box)

        # Hàng 1: Lựa chọn Tài khoản, Trang & Lĩnh vực
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Chọn Tài Khoản:"))
        self.combo_accounts = QComboBox()
        self.combo_accounts.currentIndexChanged.connect(self.on_account_changed)
        r1.addWidget(self.combo_accounts, stretch=1)

        r1.addWidget(QLabel("Quét/Xem với tư cách:"))
        self.combo_profile_mode = QComboBox()
        self.combo_profile_mode.currentIndexChanged.connect(self.on_profile_mode_changed)
        r1.addWidget(self.combo_profile_mode, stretch=1)

        r1.addWidget(QLabel("Lọc Theo Lĩnh Vực:"))
        self.combo_category_filter = QComboBox()
        self.combo_category_filter.currentIndexChanged.connect(self.load_groups)
        r1.addWidget(self.combo_category_filter, stretch=1)

        top_layout.addLayout(r1)

        # Hàng 2: Các nút hành động chính
        r2 = QHBoxLayout()
        self.btn_add_page_manual = QPushButton("➕ Thêm Fanpage Thủ Công")
        self.btn_add_page_manual.setStyleSheet("background-color: #4a148c; color: white; font-weight: bold; padding: 6px 8px;")
        self.btn_add_page_manual.clicked.connect(self.on_add_page_manual)
        r2.addWidget(self.btn_add_page_manual)

        self.btn_scan_pages = QPushButton("🚩 1. Quét Fanpage")
        self.btn_scan_pages.setStyleSheet("background-color: #7b1fa2; color: white; font-weight: bold; padding: 6px 8px;")
        self.btn_scan_pages.clicked.connect(self.on_scan_pages)
        r2.addWidget(self.btn_scan_pages)

        self.btn_interactive_switch = QPushButton("🌐 2. Tự Chọn Trang & Lưu Session")
        self.btn_interactive_switch.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 8px;")
        self.btn_interactive_switch.clicked.connect(self.on_interactive_switch)
        r2.addWidget(self.btn_interactive_switch)

        self.btn_add_groups_manual = QPushButton("📋 Thêm/Nhập Nhóm Thủ Công")
        self.btn_add_groups_manual.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 6px 8px;")
        self.btn_add_groups_manual.clicked.connect(self.on_add_groups_manual)
        r2.addWidget(self.btn_add_groups_manual)

        self.btn_scan = QPushButton("🔍 3. Quét Nhóm Đã Tham Gia")
        self.btn_scan.setStyleSheet("background-color: #1976d2; color: white; font-weight: bold; padding: 6px 8px;")
        self.btn_scan.clicked.connect(self.on_scan_groups)
        r2.addWidget(self.btn_scan)

        self.btn_interactive_join = QPushButton("➕ 4. Tham Gia Nhóm Mới")
        self.btn_interactive_join.setStyleSheet("background-color: #6a1b9a; color: white; font-weight: bold; padding: 6px 8px;")
        self.btn_interactive_join.clicked.connect(self.on_interactive_join_groups)
        r2.addWidget(self.btn_interactive_join)

        self.btn_sync_groups = QPushButton("🔄 5. Đồng Bộ Nhóm Cho Tất Cả Fanpage")
        self.btn_sync_groups.setStyleSheet("background-color: #e65100; color: white; font-weight: bold; padding: 6px 8px;")
        self.btn_sync_groups.clicked.connect(self.on_sync_groups)
        r2.addWidget(self.btn_sync_groups)

        top_layout.addLayout(r2)

        # Hàng 3: Tìm kiếm nhóm theo từ khóa & Tùy chọn hiển thị trình duyệt
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("🔍 Tìm Kiếm Nhóm:"))
        self.txt_search_keyword = QLineEdit()
        self.txt_search_keyword.setPlaceholderText("Nhập tên nhóm hoặc ID nhóm để lọc nhanh...")
        self.txt_search_keyword.textChanged.connect(self.load_groups)
        r3.addWidget(self.txt_search_keyword, stretch=1)

        r3.addSpacing(15)
        self.chk_show_browser = QCheckBox("Bật trình duyệt khi quét")
        self.chk_show_browser.setChecked(True)
        r3.addWidget(self.chk_show_browser)

        top_layout.addLayout(r3)

        layout.addWidget(top_box)

        # Table Group List (8 Cột)
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["Chọn", "ID Nhóm", "Tên Nhóm", "Lĩnh Vực", "Bài Đăng Gán (Nội dung)", "Quyền Riêng Tư", "Link Nhóm", "Xóa"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        # Bottom Selection Controls
        bot_layout = QHBoxLayout()
        btn_select_all = QPushButton("Chọn Tất Cả")
        btn_select_all.clicked.connect(lambda: self.toggle_all(True))
        bot_layout.addWidget(btn_select_all)

        btn_deselect_all = QPushButton("Bỏ Chọn Tất Cả")
        btn_deselect_all.clicked.connect(lambda: self.toggle_all(False))
        bot_layout.addWidget(btn_deselect_all)

        self.btn_set_category = QPushButton("🏷️ Gán Lĩnh Vực Cho Nhóm Đã Chọn")
        self.btn_set_category.setStyleSheet("background-color: #1565c0; color: white; font-weight: bold;")
        self.btn_set_category.clicked.connect(self.on_set_category_batch)
        bot_layout.addWidget(self.btn_set_category)

        self.btn_set_campaign = QPushButton("📝 Gán Bài Đăng Cho Nhóm Đã Chọn")
        self.btn_set_campaign.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold;")
        self.btn_set_campaign.clicked.connect(self.on_set_campaign_batch)
        bot_layout.addWidget(self.btn_set_campaign)

        self.btn_clear_groups = QPushButton("🗑️ Xóa Bộ Nhớ Nhóm")
        self.btn_clear_groups.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold;")
        self.btn_clear_groups.clicked.connect(self.on_clear_groups)
        bot_layout.addWidget(self.btn_clear_groups)

        bot_layout.addStretch()

        self.lbl_summary = QLabel("Tổng nhóm: 0 | Đã chọn: 0")
        bot_layout.addWidget(self.lbl_summary)

        layout.addLayout(bot_layout)

    def load_accounts_combo(self):
        accounts = self.db.get_accounts()
        self.combo_accounts.clear()
        for acc in accounts:
            self.combo_accounts.addItem(f"{acc['name']} ({acc['uid']})", acc['uid'])
        self.on_account_changed()

    def on_account_changed(self):
        self.combo_profile_mode.blockSignals(True)
        self.combo_profile_mode.clear()
        self.combo_profile_mode.addItem("👤 Nick Cá Nhân (Mặc định)", "")
        account_uid = self.get_selected_account_uid()
        if account_uid:
            pages = self.db.get_pages(account_uid)
            for p in pages:
                self.combo_profile_mode.addItem(f"🚩 Fanpage đính kèm: {p['page_name']}", p)
        self.combo_profile_mode.setCurrentIndex(0)
        self.combo_profile_mode.blockSignals(False)

        self.load_categories_combo()
        self.load_groups()

    def on_profile_mode_changed(self):
        self.load_categories_combo()
        self.load_groups()

    def load_categories_combo(self):
        account_uid = self.get_selected_account_uid()
        page_id, _, _ = self.get_selected_page_info()
        cats = self.db.get_categories(account_uid=account_uid, page_id=page_id)
        
        self.combo_category_filter.blockSignals(True)
        current_cat = self.combo_category_filter.currentText()
        self.combo_category_filter.clear()
        self.combo_category_filter.addItem("Tất cả lĩnh vực")
        for c in cats:
            self.combo_category_filter.addItem(c)

        index = self.combo_category_filter.findText(current_cat)
        if index >= 0:
            self.combo_category_filter.setCurrentIndex(index)
        else:
            self.combo_category_filter.setCurrentIndex(0)
        self.combo_category_filter.blockSignals(False)

    def get_selected_account_uid(self):
        return self.combo_accounts.currentData()

    def get_selected_page_info(self) -> tuple[str, str, str]:
        data = self.combo_profile_mode.currentData()
        if isinstance(data, dict):
            return data.get("page_id", ""), data.get("page_name", ""), data.get("page_url", "")
        return "", "", ""

    def load_groups(self):
        account_uid = self.get_selected_account_uid()
        page_id, _, _ = self.get_selected_page_info()
        category_filter = self.combo_category_filter.currentText()
        
        groups = self.db.get_groups(account_uid=account_uid, page_id=page_id, category=category_filter)
        campaigns = self.db.get_campaigns()

        query = self.txt_search_keyword.text().strip().lower() if hasattr(self, 'txt_search_keyword') else ""
        if query:
            groups = [
                g for g in groups
                if query in (g.get("group_name") or "").lower() or query in (g.get("group_id") or "").lower()
            ]

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(groups))

            selected_count = 0
            for row, g in enumerate(groups):
                chk = QCheckBox()
                chk.setChecked(bool(g["selected"]))
                chk.stateChanged.connect(lambda state, db_id=g["id"]: self.on_check_changed(db_id, state))
                if g["selected"]:
                    selected_count += 1

                cell_widget = QWidget()
                cw_layout = QHBoxLayout(cell_widget)
                cw_layout.addWidget(chk)
                cw_layout.setAlignment(Qt.AlignCenter)
                cw_layout.setContentsMargins(0, 0, 0, 0)
                self.table.setCellWidget(row, 0, cell_widget)

                self.table.setItem(row, 1, QTableWidgetItem(g["group_id"]))
                
                # Tên nhóm đầy đủ kèm Tooltip khi rê chuột
                item_name = QTableWidgetItem(g["group_name"])
                item_name.setToolTip(f"Tên đầy đủ: {g['group_name']}\nID: {g['group_id']}")
                self.table.setItem(row, 2, item_name)

                # Cột Lĩnh Vực
                item_cat = QTableWidgetItem(g.get("category") or "Mặc định")
                item_cat.setToolTip("Lĩnh vực nhóm (Ví dụ: Tuyển dụng, Thời trang, Bất động sản...)")
                self.table.setItem(row, 3, item_cat)

                # Cột Bài Đăng Gán (Nội dung riêng)
                combo_camp = QComboBox()
                combo_camp.addItem("📋 [Bài chung theo chiến dịch]", 0)
                cur_camp_id = g.get("campaign_id") or 0
                selected_idx = 0
                for idx, c in enumerate(campaigns, 1):
                    combo_camp.addItem(f"📝 {c['title']}", c["id"])
                    if c["id"] == cur_camp_id:
                        selected_idx = idx
                combo_camp.setCurrentIndex(selected_idx)
                combo_camp.currentIndexChanged.connect(lambda idx, db_id=g["id"], cb=combo_camp: self.on_group_campaign_changed(db_id, cb))
                self.table.setCellWidget(row, 4, combo_camp)

                self.table.setItem(row, 5, QTableWidgetItem(g["privacy"]))
                self.table.setItem(row, 6, QTableWidgetItem(g["group_url"]))

                btn_del = QPushButton("Xóa")
                btn_del.setStyleSheet("background-color: #c62828; color: white;")
                btn_del.clicked.connect(lambda _, gid=g["id"]: self.on_delete_group(gid))
                self.table.setCellWidget(row, 7, btn_del)

            self.lbl_summary.setText(f"Tổng nhóm: {len(groups)} | Đã chọn: {selected_count}")
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

    def on_group_campaign_changed(self, db_id: int, combo: QComboBox):
        camp_id = combo.currentData()
        self.db.update_group_campaign(db_id, camp_id if camp_id else 0)

    def on_set_campaign_batch(self):
        account_uid = self.get_selected_account_uid()
        page_id, _, _ = self.get_selected_page_info()
        category_filter = self.combo_category_filter.currentText()

        groups = self.db.get_groups(account_uid=account_uid, page_id=page_id, category=category_filter, only_selected=True)
        if not groups:
            QMessageBox.warning(self, "Thông báo", "Vui lòng chọn tích ít nhất 1 nhóm để gán Bài Đăng!")
            return

        campaigns = self.db.get_campaigns()
        if not campaigns:
            QMessageBox.warning(self, "Thông báo", "Chưa có mẫu nội dung bài đăng nào! Vui lòng vào tab 'Nội Dung Bài Đăng' để tạo bài đăng trước.")
            return

        options = ["📋 [Bài chung theo chiến dịch]"] + [f"📝 {c['title']}" for c in campaigns]
        item, ok = QInputDialog.getItem(self, "Gán Bài Đăng Hàng Loạt", f"Chọn bài đăng riêng gán cho {len(groups)} nhóm đã chọn:", options, 0, False)

        if ok and item:
            if item == "📋 [Bài chung theo chiến dịch]":
                target_camp_id = 0
                title_str = "[Bài chung]"
            else:
                idx = options.index(item) - 1
                target_camp_id = campaigns[idx]["id"]
                title_str = campaigns[idx]["title"]

            db_ids = [g["id"] for g in groups]
            self.db.update_groups_campaign_batch(db_ids, target_camp_id)
            QMessageBox.information(self, "Thành công", f"Đã gán bài đăng '{title_str}' cho {len(groups)} nhóm!")
            self.load_groups()

    def on_add_page_manual(self):
        account_uid = self.get_selected_account_uid()
        if not account_uid:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn tài khoản Facebook!")
            return

        page_id, ok1 = QInputDialog.getText(self, "Thêm Fanpage Thủ Công", "Nhập ID Fanpage (UID Fanpage, ví dụ: 61550350391507):")
        if not ok1 or not page_id.strip():
            return
        
        page_name, ok2 = QInputDialog.getText(self, "Tên Fanpage", "Nhập Tên Hiển Thị Fanpage (Ví dụ: Shop Thời Trang Hot):")
        if not ok2 or not page_name.strip():
            page_name = f"Fanpage ({page_id.strip()})"

        page_id_str = page_id.strip()
        page_name_str = page_name.strip()
        page_url_str = f"https://www.facebook.com/{page_id_str}"

        self.db.save_pages(account_uid, [{
            "account_uid": account_uid,
            "page_id": page_id_str,
            "page_name": page_name_str,
            "page_url": page_url_str
        }])

        QMessageBox.information(self, "Thành công", f"Đã thêm Fanpage '{page_name_str}' (ID: {page_id_str})!")
        self.on_account_changed()

    def on_add_groups_manual(self):
        account_uid = self.get_selected_account_uid()
        if not account_uid:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn tài khoản Facebook!")
            return

        page_id, page_name, _ = self.get_selected_page_info()
        cats = self.db.get_categories(account_uid=account_uid, page_id=page_id)
        
        cat_options = ["Mặc định"] + [c for c in cats if c != "Mặc định"]
        target_cat, ok_cat = QInputDialog.getItem(self, "Chọn Lĩnh Vực Nhóm", "Chọn Lĩnh Vực cho danh sách nhóm nhập thủ công:", cat_options, 0, True)
        if not ok_cat or not target_cat:
            return

        text, ok = QInputDialog.getMultiLineText(
            self,
            "Nhập Danh Sách Nhóm Thủ Công",
            f"Dán danh sách Link Nhóm hoặc ID Nhóm (Mỗi dòng 1 nhóm):\n"
            f"Ví dụ:\nhttps://www.facebook.com/groups/123456789\n987654321, Hội Mua Bán Quần Áo",
            ""
        )

        if not ok or not text.strip():
            return

        lines = text.strip().splitlines()
        added_groups = []
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            parts = [p.strip() for p in line_str.split(",")]
            main_token = parts[0]
            g_name = parts[1] if len(parts) > 1 else ""

            g_id = ""
            if "facebook.com/groups/" in main_token:
                sub = main_token.split("facebook.com/groups/")[1].split("/")[0].split("?")[0]
                g_id = sub
            else:
                g_id = main_token

            if g_id:
                if not g_name:
                    g_name = f"Nhóm ({g_id})"
                g_url = f"https://www.facebook.com/groups/{g_id}"
                added_groups.append({
                    "group_id": g_id,
                    "group_name": g_name,
                    "group_url": g_url,
                    "member_count": "",
                    "privacy": "UNKNOWN",
                    "category": target_cat.strip()
                })

        if added_groups:
            self.db.save_groups(account_uid, added_groups, page_id=page_id, page_name=page_name, default_category=target_cat.strip())
            QMessageBox.information(self, "Thành công", f"Đã thêm thành công {len(added_groups)} nhóm vào Lĩnh Vực '{target_cat}'!")
            self.load_categories_combo()
            self.load_groups()
        else:
            QMessageBox.warning(self, "Thông báo", "Không tìm thấy Link hoặc ID Nhóm hợp lệ trong nội dung đã dán.")

    def on_set_category_batch(self):
        account_uid = self.get_selected_account_uid()
        page_id, _, _ = self.get_selected_page_info()
        category_filter = self.combo_category_filter.currentText()

        groups = self.db.get_groups(account_uid=account_uid, page_id=page_id, category=category_filter, only_selected=True)
        if not groups:
            QMessageBox.warning(self, "Thông báo", "Vui lòng chọn tích ít nhất 1 nhóm để gán Lĩnh vực!")
            return

        db_ids = [g["id"] for g in groups]
        cats = self.db.get_categories(account_uid=account_uid, page_id=page_id)
        
        options = ["+ Nhập Lĩnh Vực Mới..."] + cats
        item, ok = QInputDialog.getItem(self, "Gán Lĩnh Vực Hàng Loạt", f"Chọn hoặc nhập Lĩnh Vực mới cho {len(groups)} nhóm đã chọn:", options, 0, True)

        if ok and item:
            target_cat = item.strip()
            if target_cat == "+ Nhập Lĩnh Vực Mới...":
                new_cat, ok_new = QInputDialog.getText(self, "Nhập Lĩnh Vực Mới", "Tên Lĩnh Vực mới (Ví dụ: Tuyển dụng, Mua bán thời trang, Bất động sản...):")
                if ok_new and new_cat.strip():
                    target_cat = new_cat.strip()
                else:
                    return

            self.db.update_groups_category_batch(db_ids, target_cat)
            QMessageBox.information(self, "Thành công", f"Đã gán Lĩnh Vực '{target_cat}' cho {len(groups)} nhóm!")
            self.load_categories_combo()
            self.load_groups()

    def on_check_changed(self, db_id: int, state: int):
        is_checked = (state == Qt.Checked.value or state == 2)
        self.db.update_group_selection(db_id, is_checked)
        self.load_groups()

    def toggle_all(self, selected: bool):
        account_uid = self.get_selected_account_uid()
        page_id, _, _ = self.get_selected_page_info()
        category_filter = self.combo_category_filter.currentText()
        self.db.toggle_all_groups_selection(selected, account_uid=account_uid, page_id=page_id, category=category_filter)
        self.load_groups()
        self.load_groups()

    def on_delete_group(self, db_id: int):
        self.db.delete_group(db_id)
        self.load_groups()

    def on_scan_groups(self):
        account_uid = self.get_selected_account_uid()
        if not account_uid:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn tài khoản để quét nhóm!")
            return

        accounts = self.db.get_accounts()
        target_acc = next((a for a in accounts if a["uid"] == account_uid), None)
        if not target_acc:
            return

        page_id, page_name, page_url = self.get_selected_page_info()
        target_desc = f"Fanpage '{page_name}'" if page_name else "Nick cá nhân"
        headless_mode = not self.chk_show_browser.isChecked()

        self.progress_dialog = QProgressDialog(f"Đang chuẩn bị quét nhóm cho {target_desc}...", "Hủy", 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        self.worker = GroupScanWorker(
            target_acc["cookie"],
            target_acc.get("proxy", ""),
            page_id=page_id,
            page_name=page_name,
            page_url=page_url,
            headless=headless_mode
        )
        self.worker.progress_signal.connect(self.progress_dialog.setLabelText)
        self.worker.finished_signal.connect(self.on_scan_finished)
        self.worker.start()

    def on_scan_finished(self, groups: list):
        self.progress_dialog.close()
        account_uid = self.get_selected_account_uid()
        page_id, page_name, _ = self.get_selected_page_info()
        if groups and account_uid:
            self.db.save_groups(account_uid, groups, page_id=page_id, page_name=page_name)
            QMessageBox.information(self, "Thành công", f"Đã quét và lưu {len(groups)} nhóm cho {page_name or 'Nick cá nhân'}!")
            self.load_groups()
        else:
            QMessageBox.warning(self, "Thông báo", "Không tìm thấy nhóm mới hoặc có lỗi khi quét.")

    def on_sync_groups(self):
        account_uid = self.get_selected_account_uid()
        if not account_uid:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn tài khoản Facebook để đồng bộ nhóm!")
            return

        self.db.sync_groups_across_pages(account_uid)
        QMessageBox.information(self, "Thành công", "Đã đồng bộ toàn bộ danh sách nhóm sang tất cả các Fanpage thuộc tài khoản này!")
        self.load_categories_combo()
        self.load_groups()

    def on_scan_pages(self):
        account_uid = self.get_selected_account_uid()
        if not account_uid:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn tài khoản để quét Fanpage!")
            return

        accounts = self.db.get_accounts()
        target_acc = next((a for a in accounts if a["uid"] == account_uid), None)
        if not target_acc:
            return

        headless_mode = not self.chk_show_browser.isChecked()

        self.progress_dialog = QProgressDialog("Đang chuẩn bị quét danh sách Fanpage...", "Hủy", 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        self.page_worker = PageScanWorker(target_acc["cookie"], target_acc.get("proxy", ""), headless=headless_mode)
        self.page_worker.progress_signal.connect(self.progress_dialog.setLabelText)
        self.page_worker.finished_signal.connect(self.on_scan_pages_finished)
        self.page_worker.start()

    def on_scan_pages_finished(self, pages: list):
        self.progress_dialog.close()
        account_uid = self.get_selected_account_uid()
        if pages and account_uid:
            self.db.save_pages(account_uid, pages)
            QMessageBox.information(self, "Thành công", f"Đã quét và lưu {len(pages)} Fanpage!")
            self.on_account_changed()
        else:
            QMessageBox.warning(self, "Thông báo", "Không tìm thấy Fanpage nào hoặc có lỗi khi quét.")

    def on_interactive_switch(self):
        account_uid = self.get_selected_account_uid()
        if not account_uid:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn tài khoản Facebook!")
            return

        accounts = self.db.get_accounts()
        target_acc = next((a for a in accounts if a["uid"] == account_uid), None)
        if not target_acc:
            return

        page_id, page_name, page_url = self.get_selected_page_info()
        target_desc = f"Fanpage '{page_name}'" if page_name else "Nick cá nhân"

        self.progress_dialog = QProgressDialog(
            f"Trình duyệt đã mở! Vui lòng chọn/chuyển sang {target_desc} trên trình duyệt Facebook.\nSau khi chuyển xong, ĐÓNG TRÌNH DUYỆT để phần mềm lưu phiên...",
            "Đóng Hủy",
            0,
            0,
            self
        )
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        self.switch_worker = InteractivePageSwitchWorker(
            target_acc["cookie"],
            target_acc.get("proxy", ""),
            page_id=page_id,
            page_name=page_name,
            page_url=page_url
        )
        self.switch_worker.progress_signal.connect(self.progress_dialog.setLabelText)
        self.switch_worker.finished_signal.connect(self.on_interactive_switch_finished)
        self.switch_worker.start()

    def on_interactive_switch_finished(self, result: dict):
        self.progress_dialog.close()
        account_uid = self.get_selected_account_uid()
        if result.get("success"):
            if result.get("cookie") and account_uid:
                self.db.update_account_cookie(account_uid, result["cookie"])
            QMessageBox.information(self, "Thành công", result.get("message", "Đã lưu Session Fanpage thành công!"))
        else:
            QMessageBox.warning(self, "Thông báo", result.get("message", "Chưa hoàn tất lưu Session."))

    def on_interactive_join_groups(self):
        account_uid = self.get_selected_account_uid()
        if not account_uid:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn tài khoản Facebook!")
            return

        accounts = self.db.get_accounts()
        target_acc = next((a for a in accounts if a["uid"] == account_uid), None)
        if not target_acc:
            return

        page_id, page_name, page_url = self.get_selected_page_info()
        cats = self.db.get_categories(account_uid=account_uid, page_id=page_id)
        
        options = ["+ Nhập Lĩnh Vực Mới..."] + [c for c in cats if c != "Mặc định"] + ["Mặc định"]
        item, ok = QInputDialog.getItem(
            self,
            "Chọn Lĩnh Vực Cho Nhóm Mới",
            "Chọn hoặc nhập tên Lĩnh Vực (Tuyển dụng, Thời trang...) để tự động gán các nhóm mới tham gia:",
            options,
            0,
            True
        )

        if not ok or not item:
            return

        target_cat = item.strip()
        if target_cat == "+ Nhập Lĩnh Vực Mới...":
            new_cat, ok_new = QInputDialog.getText(
                self,
                "Nhập Lĩnh Vực Mới",
                "Tên Lĩnh Vực mới (Ví dụ: Tuyển dụng, Mua bán thời trang, Bất động sản...):"
            )
            if ok_new and new_cat.strip():
                target_cat = new_cat.strip()
            else:
                return

        target_desc = f"Fanpage '{page_name}'" if page_name else "Nick cá nhân"

        self.progress_dialog = QProgressDialog(
            f"Trình duyệt đang mở tại Facebook Groups Discover cho {target_desc}!\n"
            f"Hãy tự do tìm kiếm & bấm THAM GIA các nhóm mới thuộc Lĩnh Vực '{target_cat}'.\n"
            f"Sau khi hoàn tất, ĐÓNG CỬA SỔ TRÌNH DUYỆT để phần mềm tự động thêm nhóm vào Lĩnh Vực '{target_cat}'...",
            "Hủy",
            0,
            0,
            self
        )
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        self.join_worker = InteractiveJoinGroupWorker(
            target_acc["cookie"],
            target_acc.get("proxy", ""),
            category_name=target_cat,
            page_id=page_id,
            page_name=page_name,
            page_url=page_url
        )
        self.join_worker.progress_signal.connect(self.progress_dialog.setLabelText)
        self.join_worker.finished_signal.connect(self.on_interactive_join_finished)
        self.join_worker.start()

    def on_interactive_join_finished(self, result: dict):
        self.progress_dialog.close()
        account_uid = self.get_selected_account_uid()
        page_id, page_name, _ = self.get_selected_page_info()
        
        if result.get("success"):
            groups = result.get("groups", [])
            category_name = result.get("category", "Mặc định")
            if groups and account_uid:
                self.db.save_groups(account_uid, groups, page_id=page_id, page_name=page_name, default_category=category_name)
            
            QMessageBox.information(
                self,
                "Thành công",
                result.get("message", "Đã cập nhật danh sách nhóm!")
            )
            self.load_categories_combo()
            self.load_groups()
        else:
            QMessageBox.warning(self, "Thông báo", result.get("message", "Có lỗi xảy ra trong quá trình tham gia nhóm."))

    def on_clear_groups(self):
        account_uid = self.get_selected_account_uid()
        page_id, page_name, _ = self.get_selected_page_info()
        target_desc = f"Fanpage '{page_name}'" if page_name else "Nick cá nhân"

        if not account_uid:
            return

        reply = QMessageBox.question(
            self,
            "Xác nhận xóa bộ nhớ nhóm",
            f"Bạn có chắc muốn xóa TOÀN BỘ danh sách nhóm đã quét cho {target_desc}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.db.clear_groups(account_uid=account_uid, page_id=page_id)
            self.load_groups()
            QMessageBox.information(self, "Thông báo", f"Đã xóa toàn bộ bộ nhớ nhóm của {target_desc}!")
