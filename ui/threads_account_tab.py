import asyncio
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QTextEdit, QLineEdit,
    QGroupBox, QMessageBox, QProgressDialog
)
from PySide6.QtCore import Qt, QThread, Signal
from core.database import Database
from core.threads_automation import ThreadsAutomationEngine

class ThreadsBrowserLoginWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(dict)

    def __init__(self, proxy: str = ""):
        super().__init__()
        self.proxy = proxy

    def run(self):
        try:
            engine = ThreadsAutomationEngine()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            def callback(msg):
                self.progress_signal.emit(msg)

            result = loop.run_until_complete(engine.login_via_browser(self.proxy, progress_callback=callback))
            loop.close()
            self.finished_signal.emit(result)
        except Exception as e:
            self.finished_signal.emit({"success": False, "message": f"Lỗi khởi chạy trình duyệt Threads: {str(e)}"})


class ThreadsOpenBrowserWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(dict)

    def __init__(self, cookie_str: str, proxy: str = "", uid: str = ""):
        super().__init__()
        self.cookie_str = cookie_str
        self.proxy = proxy
        self.uid = uid

    def run(self):
        try:
            engine = ThreadsAutomationEngine()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            def callback(msg):
                self.progress_signal.emit(msg)

            res = loop.run_until_complete(
                engine.open_browser_with_cookie(
                    self.cookie_str,
                    proxy=self.proxy,
                    uid=self.uid,
                    progress_callback=callback
                )
            )
            loop.close()
            self.finished_signal.emit(res)
        except Exception as e:
            self.finished_signal.emit({"success": False, "message": f"Lỗi khi mở trình duyệt Threads: {str(e)}"})


class ThreadsAccountTab(QWidget):
    account_changed = Signal()

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.init_ui()
        self.load_accounts()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # Phương Thức 1: Đăng nhập trực tiếp bằng trình duyệt
        browser_login_box = QGroupBox("Phương Thức 1: Đăng Nhập Trực Tiếp Bằng Trình Duyệt Threads (Khuyên Dùng)")
        b_layout = QVBoxLayout(browser_login_box)

        self.btn_browser_login = QPushButton("🌐 ĐĂNG NHẬP TRỰC TIẾP TRÊN TRÌNH DUYỆT THREADS (Không cần Cookie)")
        self.btn_browser_login.setStyleSheet(
            "background-color: #000000; color: #ffffff; font-weight: bold; font-size: 14px; padding: 10px; border: 1px solid #45475a; border-radius: 6px;"
        )
        self.btn_browser_login.clicked.connect(self.on_browser_login)
        b_layout.addWidget(self.btn_browser_login)

        lbl_desc = QLabel("Mở cửa sổ Threads thật. Bạn tự gõ Tài khoản / Mật khẩu Threads / Instagram -> Phần mềm tự động lưu phiên làm việc.")
        lbl_desc.setStyleSheet("color: #a6adc8; font-style: italic; font-size: 12px;")
        b_layout.addWidget(lbl_desc)

        layout.addWidget(browser_login_box)

        # Phương Thức 2: Nhập chuỗi Cookie thủ công
        manual_box = QGroupBox("Phương Thức 2: Nhập Chuỗi Cookie / JSON Thủ Công")
        m_layout = QVBoxLayout(manual_box)

        row_cookie = QHBoxLayout()
        row_cookie.addWidget(QLabel("Chuỗi Cookie (hoặc JSON):"))
        self.txt_cookie = QTextEdit()
        self.txt_cookie.setPlaceholderText("Dán Cookie Threads tại đây (VD: sessionid=...; ds_user_id=... hoặc định dạng JSON)...")
        self.txt_cookie.setMaximumHeight(65)
        row_cookie.addWidget(self.txt_cookie)
        m_layout.addLayout(row_cookie)

        row_proxy = QHBoxLayout()
        row_proxy.addWidget(QLabel("Proxy (Tùy chọn):"))
        self.txt_proxy = QLineEdit()
        self.txt_proxy.setPlaceholderText("VD: http://username:password@ip:port")
        row_proxy.addWidget(self.txt_proxy)

        self.btn_add_manual = QPushButton("Thêm Bằng Cookie")
        self.btn_add_manual.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 15px;")
        self.btn_add_manual.clicked.connect(self.on_add_manual)
        row_proxy.addWidget(self.btn_add_manual)

        m_layout.addLayout(row_proxy)
        layout.addWidget(manual_box)

        # Bảng danh sách tài khoản Threads
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "STT", "UID Threads", "Tên Tài Khoản", "Proxy", "Trạng Thái", "Hành Động"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        layout.addWidget(self.table)

        btn_refresh = QPushButton("🔄 Làm Mới Danh Sách Tài Khoản Threads")
        btn_refresh.clicked.connect(self.load_accounts)
        layout.addWidget(btn_refresh)

    def load_accounts(self):
        accounts = self.db.get_threads_accounts()
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(accounts))
            for row, acc in enumerate(accounts):
                # STT
                self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))

                # UID
                self.table.setItem(row, 1, QTableWidgetItem(acc.get("uid", "")))

                # Tên / Username
                display_name = acc.get("name") or acc.get("username") or f"Threads User ({acc.get('uid', '')})"
                self.table.setItem(row, 2, QTableWidgetItem(display_name))

                # Proxy
                proxy_str = acc.get("proxy") or "Trực tiếp"
                self.table.setItem(row, 3, QTableWidgetItem(proxy_str))

                # Trạng Thái
                status_item = QTableWidgetItem(acc.get("status", "ACTIVE"))
                status_item.setForeground(Qt.green)
                self.table.setItem(row, 4, status_item)

                # Nút Hành Động: Mở Trình Duyệt & Xóa
                btn_widget = QWidget()
                btn_layout = QHBoxLayout(btn_widget)
                btn_layout.setContentsMargins(4, 2, 4, 2)
                btn_layout.setSpacing(6)

                btn_open = QPushButton("🌐 Mở Trình Duyệt")
                btn_open.setStyleSheet("background-color: #00897b; color: white; font-weight: bold; padding: 4px 8px;")
                btn_open.clicked.connect(lambda _, a=acc: self.on_open_browser(a))
                btn_layout.addWidget(btn_open)

                btn_del = QPushButton("Xóa")
                btn_del.setStyleSheet("background-color: #c62828; color: white; padding: 4px 8px;")
                btn_del.clicked.connect(lambda _, u=acc["uid"]: self.on_delete_account(u))
                btn_layout.addWidget(btn_del)

                self.table.setCellWidget(row, 5, btn_widget)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        self.account_changed.emit()

    def on_browser_login(self):
        proxy = self.txt_proxy.text().strip()

        self.progress_dialog = QProgressDialog("Đang chuẩn bị trình duyệt Threads...", "Hủy", 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        self.browser_worker = ThreadsBrowserLoginWorker(proxy=proxy)
        self.browser_worker.progress_signal.connect(self.progress_dialog.setLabelText)
        self.browser_worker.finished_signal.connect(self.on_browser_login_finished)
        self.browser_worker.start()

    def on_browser_login_finished(self, result: dict):
        self.progress_dialog.close()
        if result.get("success"):
            uid = result["uid"]
            username = result.get("username", "")
            name = result.get("name", f"@{username}")
            cookie = result["cookie"]
            proxy = self.txt_proxy.text().strip()

            self.db.save_threads_account(uid, username, name, cookie, proxy)
            self.load_accounts()
            QMessageBox.information(
                self,
                "Đăng Nhập Thành Công",
                f"✅ Đã kết nối tài khoản Threads: {name} (UID: {uid})!\nPhiên đăng nhập đã được lưu trữ an toàn."
            )
            self.txt_cookie.clear()
            self.txt_proxy.clear()
        else:
            QMessageBox.warning(self, "Thông Báo Đăng Nhập", result.get("message", "Đăng nhập Threads chưa hoàn tất."))

    def on_open_browser(self, acc: dict):
        self.progress_dialog = QProgressDialog(
            f"Trình duyệt Threads đang mở cho tài khoản {acc.get('name', '')}!\nSau khi xong, ĐÓNG CỬA SỔ TRÌNH DUYỆT để lưu phiên...",
            "Đóng", 0, 0, self
        )
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        self.open_worker = ThreadsOpenBrowserWorker(acc["cookie"], proxy=acc.get("proxy", ""), uid=acc.get("uid", ""))
        self.open_worker.progress_signal.connect(self.progress_dialog.setLabelText)
        self.open_worker.finished_signal.connect(self.on_open_browser_finished)
        self.open_worker.start()

    def on_open_browser_finished(self, res: dict):
        self.progress_dialog.close()
        if res.get("cookie") and res.get("uid"):
            self.db.update_threads_cookie(res["uid"], res["cookie"])
            self.load_accounts()

    def on_add_manual(self):
        cookie = self.txt_cookie.toPlainText().strip()
        proxy = self.txt_proxy.text().strip()

        if not cookie:
            QMessageBox.warning(self, "Cảnh Báo", "Vui lòng nhập chuỗi Cookie Threads!")
            return

        engine = ThreadsAutomationEngine()
        cookies = engine.parse_cookie_string(cookie)
        uid = engine.extract_uid_from_cookie(cookies)
        if not uid:
            uid = f"user_{int(time.time())}"

        name = f"Threads User ({uid})"
        self.db.save_threads_account(uid, uid, name, cookie, proxy)
        self.txt_cookie.clear()
        self.txt_proxy.clear()
        self.load_accounts()
        QMessageBox.information(self, "Thành Công", f"Đã lưu tài khoản Threads với UID: {uid}!")

    def on_delete_account(self, uid: str):
        reply = QMessageBox.question(
            self,
            "Xác Nhận Xóa",
            f"Bạn có chắc chắn muốn xóa tài khoản Threads (UID: {uid}) khỏi phần mềm?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.db.delete_threads_account(uid)
            self.load_accounts()
