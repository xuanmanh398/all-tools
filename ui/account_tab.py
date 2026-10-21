import asyncio
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QTextEdit, QLineEdit,
    QGroupBox, QMessageBox, QProgressDialog
)
from PySide6.QtCore import Qt, QThread, Signal
from core.database import Database
from core.fb_automation import FBAutomationEngine

class AccountVerifyWorker(QThread):
    finished_signal = Signal(dict)

    def __init__(self, cookie_str: str, proxy: str = ""):
        super().__init__()
        self.cookie_str = cookie_str
        self.proxy = proxy

    def run(self):
        try:
            engine = FBAutomationEngine()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(engine.verify_account(self.cookie_str, self.proxy))
            loop.close()
            self.finished_signal.emit(result)
        except Exception as e:
            self.finished_signal.emit({"success": False, "message": f"Lỗi xác minh tài khoản: {str(e)}"})


class BrowserLoginWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(dict)

    def __init__(self, proxy: str = ""):
        super().__init__()
        self.proxy = proxy

    def run(self):
        try:
            engine = FBAutomationEngine()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            def callback(msg):
                self.progress_signal.emit(msg)

            result = loop.run_until_complete(engine.login_via_browser(self.proxy, progress_callback=callback))
            loop.close()
            self.finished_signal.emit(result)
        except Exception as e:
            self.finished_signal.emit({"success": False, "message": f"Lỗi khởi chạy trình duyệt: {str(e)}"})


class OpenBrowserWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(dict)

    def __init__(self, cookie_str: str, proxy: str = "", page_id: str = ""):
        super().__init__()
        self.cookie_str = cookie_str
        self.proxy = proxy
        self.page_id = page_id

    def run(self):
        try:
            engine = FBAutomationEngine()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            def callback(msg):
                self.progress_signal.emit(msg)

            res = loop.run_until_complete(
                engine.open_browser_with_cookie(
                    self.cookie_str,
                    proxy=self.proxy,
                    page_id=self.page_id,
                    progress_callback=callback
                )
            )
            loop.close()
            self.finished_signal.emit(res)
        except Exception as e:
            self.finished_signal.emit({"success": False, "message": f"Lỗi khi mở trình duyệt: {str(e)}"})


class AccountTab(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.init_ui()
        self.load_accounts()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Direct Browser Login Button
        browser_login_box = QGroupBox("Phương Thức 1: Đăng Nhập Trực Tiếp Bằng Trình Duyệt (Khuyên Dùng)")
        b_layout = QVBoxLayout(browser_login_box)

        self.btn_browser_login = QPushButton("🌐 ĐĂNG NHẬP TRỰC TIẾP TRÊN TRÌNH DUYỆT (Không cần Cookie)")
        self.btn_browser_login.setStyleSheet(
            "background-color: #1565c0; color: white; font-weight: bold; font-size: 14px; padding: 10px;"
        )
        self.btn_browser_login.clicked.connect(self.on_browser_login)
        b_layout.addWidget(self.btn_browser_login)

        lbl_desc = QLabel("Mở cửa sổ Facebook thật. Bạn tự gõ Tài khoản & Mật khẩu -> Phần mềm tự động lưu phiên làm việc.")
        lbl_desc.setStyleSheet("color: #a6adc8; font-style: italic;")
        b_layout.addWidget(lbl_desc)

        layout.addWidget(browser_login_box)

        # Group box: Manual Cookie Add
        input_box = QGroupBox("Phương Thức 2: Nhập Chuỗi Cookie / JSON Thủ Công")
        input_layout = QVBoxLayout(input_box)

        cookie_layout = QHBoxLayout()
        cookie_layout.addWidget(QLabel("Chuỗi Cookie (hoặc JSON):"))
        self.txt_cookie = QTextEdit()
        self.txt_cookie.setPlaceholderText("Dán Cookie Facebook tại đây (VD: c_user=1000...; xs=2... hoặc định dạng JSON)...")
        self.txt_cookie.setMaximumHeight(60)
        cookie_layout.addWidget(self.txt_cookie)
        input_layout.addLayout(cookie_layout)

        proxy_layout = QHBoxLayout()
        proxy_layout.addWidget(QLabel("Proxy (Tùy chọn):"))
        self.txt_proxy = QLineEdit()
        self.txt_proxy.setPlaceholderText("VD: http://username:password@ip:port")
        proxy_layout.addWidget(self.txt_proxy)

        self.btn_add_account = QPushButton("Thêm Bằng Cookie")
        self.btn_add_account.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 14px;")
        self.btn_add_account.clicked.connect(self.on_add_account)
        proxy_layout.addWidget(self.btn_add_account)

        input_layout.addLayout(proxy_layout)
        layout.addWidget(input_box)

        # Table Account List
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["STT", "UID Facebook", "Tên Tài Khoản", "Proxy", "Trạng Thái", "Hành Động"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        # Refresh button
        btn_refresh = QPushButton("Làm Mới Danh Sách Tài Khoản")
        btn_refresh.clicked.connect(self.load_accounts)
        layout.addWidget(btn_refresh)

    def load_accounts(self):
        accounts = self.db.get_accounts()
        self.table.setRowCount(len(accounts))

        for row, acc in enumerate(accounts):
            self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.table.setItem(row, 1, QTableWidgetItem(acc["uid"]))
            self.table.setItem(row, 2, QTableWidgetItem(acc["name"]))
            self.table.setItem(row, 3, QTableWidgetItem(acc.get("proxy", "") or "Trực tiếp"))
            
            status_item = QTableWidgetItem(acc["status"])
            if acc["status"] == "ACTIVE":
                status_item.setForeground(Qt.green)
            else:
                status_item.setForeground(Qt.red)
            self.table.setItem(row, 4, status_item)

            # Action cell widget with Open Browser & Delete buttons
            cell_widget = QWidget()
            cw_layout = QHBoxLayout(cell_widget)
            cw_layout.setContentsMargins(2, 2, 2, 2)

            btn_open = QPushButton("🌐 Mở Trình Duyệt")
            btn_open.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 3px 6px;")
            btn_open.clicked.connect(lambda _, a=acc: self.on_open_browser_account(a))
            cw_layout.addWidget(btn_open)

            btn_del = QPushButton("Xóa")
            btn_del.setStyleSheet("background-color: #c62828; color: white; padding: 3px 6px;")
            uid = acc["uid"]
            btn_del.clicked.connect(lambda _, u=uid: self.on_delete_account(u))
            cw_layout.addWidget(btn_del)

            self.table.setCellWidget(row, 5, cell_widget)

    def on_open_browser_account(self, acc: dict):
        desc = f"Tài khoản {acc['name']} (UID: {acc['uid']})"

        self.progress_dialog = QProgressDialog(f"Trình duyệt đang mở tại Facebook cho {desc}!\nBạn có thể quan sát/thao tác bình thường.\nSau khi xong, ĐÓNG CỬA SỔ TRÌNH DUYỆT để phần mềm tự động lưu phiên...", "Đóng Hủy", 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        self.open_worker = OpenBrowserWorker(acc["cookie"], proxy=acc.get("proxy", ""), page_id="")
        self.open_worker.progress_signal.connect(self.progress_dialog.setLabelText)
        self.open_worker.finished_signal.connect(self.on_open_browser_finished)
        self.open_worker.start()

    def on_open_browser_finished(self, res: dict):
        self.progress_dialog.close()
        if res.get("cookie") and res.get("uid"):
            self.db.update_account_cookie(res["uid"], res["cookie"])
            self.load_accounts()

    def on_browser_login(self):
        proxy = self.txt_proxy.text().strip()

        self.progress_dialog = QProgressDialog("Đang chuẩn bị trình duyệt...", "Hủy", 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        self.browser_worker = BrowserLoginWorker(proxy=proxy)
        self.browser_worker.progress_signal.connect(self.progress_dialog.setLabelText)
        self.browser_worker.finished_signal.connect(self.on_browser_login_finished)
        self.browser_worker.start()

    def on_browser_login_finished(self, result: dict):
        self.progress_dialog.close()

        if result.get("success"):
            uid = result["uid"]
            name = result["name"]
            cookie = result["cookie"]
            proxy = self.txt_proxy.text().strip()

            self.db.save_account(uid, name, cookie, proxy)
            self.load_accounts()

            # Tự động quét luôn danh sách Fanpage sau khi đăng nhập thành công
            self.auto_scan_pages_after_login(uid, name, cookie, proxy)
        else:
            QMessageBox.warning(self, "Thông báo đăng nhập", result.get("message", "Đăng nhập chưa hoàn tất."))

    def auto_scan_pages_after_login(self, uid: str, name: str, cookie: str, proxy: str):
        from ui.group_tab import PageScanWorker

        self.progress_dialog = QProgressDialog(
            f"Đã đăng nhập thành công tài khoản: {name}!\nĐang tự động quét các Fanpage do tài khoản sở hữu...",
            "Bỏ qua", 0, 0, self
        )
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        self.page_scan_worker = PageScanWorker(cookie, proxy=proxy, headless=True)
        self.page_scan_worker.progress_signal.connect(self.progress_dialog.setLabelText)
        self.page_scan_worker.finished_signal.connect(lambda pages: self.on_auto_scan_pages_finished(uid, name, pages))
        self.page_scan_worker.start()

    def on_auto_scan_pages_finished(self, uid: str, name: str, pages: list):
        self.progress_dialog.close()
        page_msg = ""
        if pages:
            self.db.save_pages(uid, pages)
            page_msg = f"\n🚩 Đã tự động tìm thấy và lưu {len(pages)} Fanpage!"
        else:
            page_msg = "\n(Tài khoản chưa quản lý Fanpage nào hoặc Fanpage đã ẩn)"

        QMessageBox.information(
            self,
            "Đăng Nhập Thành Công",
            f"✅ Đã kết nối tài khoản: {name} (UID: {uid}){page_msg}\n\nToàn bộ Cookie & Session đã được lưu an toàn. Từ nay phần mềm sẽ tự động đăng nhập và tự động chuyển sang Fanpage khi đăng bài (kể cả chạy ngầm)!"
        )
        self.txt_cookie.clear()
        self.txt_proxy.clear()
        self.load_accounts()

    def on_add_account(self):
        cookie = self.txt_cookie.toPlainText().strip()
        proxy = self.txt_proxy.text().strip()

        if not cookie:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng nhập Cookie Facebook!")
            return

        self.btn_add_account.setEnabled(False)
        self.btn_add_account.setText("Đang kiểm tra...")

        self.worker = AccountVerifyWorker(cookie, proxy)
        self.worker.finished_signal.connect(self.on_verify_finished)
        self.worker.start()

    def on_verify_finished(self, result: dict):
        self.btn_add_account.setEnabled(True)
        self.btn_add_account.setText("Thêm Bằng Cookie")

        if result.get("success"):
            uid = result["uid"]
            name = result["name"]
            cookie = result["cookie"]
            proxy = self.txt_proxy.text().strip()

            self.db.save_account(uid, name, cookie, proxy)
            i_user = result.get("i_user")
            page_msg = ""
            if i_user and i_user != uid:
                self.db.save_pages(uid, [{
                    "account_uid": uid,
                    "page_id": i_user,
                    "page_name": f"Fanpage ({i_user})",
                    "page_url": f"https://www.facebook.com/{i_user}"
                }])
                page_msg = f"\n🚩 Đã tự động phát hiện Fanpage đính kèm (ID: {i_user})!"

            QMessageBox.information(self, "Thành công", f"Đã thêm tài khoản cá nhân: {name} (UID: {uid}){page_msg}")
            self.txt_cookie.clear()
            self.txt_proxy.clear()
            self.load_accounts()
        else:
            QMessageBox.critical(self, "Lỗi", result.get("message", "Xác thực tài khoản thất bại!"))

    def on_delete_account(self, uid: str):
        reply = QMessageBox.question(self, "Xác nhận xóa", f"Bạn có chắc muốn xóa tài khoản UID: {uid}?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.db.delete_account(uid)
            self.load_accounts()
