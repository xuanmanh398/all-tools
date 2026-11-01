import sys
import os
import time
import json
import subprocess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QTextEdit, QLineEdit,
    QGroupBox, QMessageBox, QProgressDialog
)
from PySide6.QtCore import Qt, QThread, Signal
from core.database import Database
from core.threads_automation import ThreadsAutomationEngine, get_threads_session_file_path


def get_worker_command(args_list):
    """Xác định lệnh gọi worker chính xác cho cả dev mode (python) và frozen exe."""
    if getattr(sys, 'frozen', False):
        return [sys.executable, "--threads-worker"] + args_list
    else:
        main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        return [sys.executable, "-u", main_py, "--threads-worker"] + args_list


class ThreadsBrowserLoginWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(dict)

    def __init__(self, proxy: str = ""):
        super().__init__()
        self.proxy = proxy
        self.proc = None
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            try:
                self.proc.kill()
            except Exception:
                pass

    def run(self):
        try:
            self.progress_signal.emit("Đang chuẩn bị trình duyệt Threads...")
            cmd = get_worker_command(["login", self.proxy])
            print(f"[THREADS] Khởi chạy tiến trình độc lập: {' '.join(cmd)}")

            env = os.environ.copy()
            env.pop("NODE_OPTIONS", None)

            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env
            )

            result_data = None
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("PROGRESS:"):
                    msg = line[len("PROGRESS:"):].strip()
                    self.progress_signal.emit(msg)
                elif line.startswith("RESULT:"):
                    try:
                        result_data = json.loads(line[len("RESULT:"):].strip())
                    except Exception:
                        pass
                    break
                else:
                    print(f"[WORKER] {line}")

            try:
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            if self.is_cancelled:
                self.finished_signal.emit({"success": False, "message": "Người dùng đã hủy đăng nhập."})
            elif result_data:
                self.finished_signal.emit(result_data)
            else:
                self.finished_signal.emit({"success": False, "message": "Tiến trình trình duyệt đã kết thúc."})

        except Exception as e:
            self.finished_signal.emit({"success": False, "message": f"Lỗi khởi chạy tiến trình: {str(e)}"})


class ThreadsOpenBrowserWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(dict)

    def __init__(self, cookie_str: str, proxy: str = "", uid: str = ""):
        super().__init__()
        self.cookie_str = cookie_str
        self.proxy = proxy
        self.uid = uid
        self.proc = None
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            try:
                self.proc.kill()
            except Exception:
                pass

    def run(self):
        cookie_file = None
        try:
            self.progress_signal.emit("Đang chuẩn bị trình duyệt Threads...")
            
            temp_cookie_path = ""
            if self.cookie_str:
                from core.database import get_app_data_dir
                temp_dir = os.path.join(get_app_data_dir(), "temp")
                os.makedirs(temp_dir, exist_ok=True)
                temp_cookie_path = os.path.join(temp_dir, f"open_{self.uid or 'temp'}.txt")
                with open(temp_cookie_path, "w", encoding="utf-8") as f:
                    f.write(self.cookie_str)
                cookie_file = temp_cookie_path

            cmd = get_worker_command(["open", self.uid, self.proxy, temp_cookie_path])
            print(f"[THREADS] Khởi chạy tiến trình mở trình duyệt: {' '.join(cmd)}")

            env = os.environ.copy()
            env.pop("NODE_OPTIONS", None)

            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env
            )

            result_data = None
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("PROGRESS:"):
                    msg = line[len("PROGRESS:"):].strip()
                    self.progress_signal.emit(msg)
                elif line.startswith("RESULT:"):
                    try:
                        result_data = json.loads(line[len("RESULT:"):].strip())
                    except Exception:
                        pass
                    break
                else:
                    print(f"[WORKER] {line}")

            try:
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            if self.is_cancelled:
                self.finished_signal.emit({"success": False, "message": "Người dùng đã đóng trình duyệt."})
            elif result_data:
                self.finished_signal.emit(result_data)
            else:
                self.finished_signal.emit({"success": False, "message": "Tiến trình trình duyệt đã kết thúc."})

        except Exception as e:
            self.finished_signal.emit({"success": False, "message": f"Lỗi khởi chạy tiến trình: {str(e)}"})
        finally:
            if cookie_file and os.path.exists(cookie_file):
                try:
                    os.remove(cookie_file)
                except Exception:
                    pass


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

        self.progress_dialog = QProgressDialog(
            "Đang mở trình duyệt Threads...\n(Vui lòng xem cửa sổ trình duyệt trên màn hình hoặc thanh tác vụ Taskbar để đăng nhập)",
            "Hủy", 0, 0, self
        )
        self.progress_dialog.setWindowTitle("Đăng Nhập Threads Trực Tiếp")
        self.progress_dialog.setWindowModality(Qt.NonModal)
        self.progress_dialog.show()

        self.browser_worker = ThreadsBrowserLoginWorker(proxy=proxy)
        self.browser_worker.progress_signal.connect(self.progress_dialog.setLabelText)
        self.browser_worker.finished_signal.connect(self.on_browser_login_finished)
        self.progress_dialog.canceled.connect(self.browser_worker.cancel)
        self.browser_worker.start()

    def on_browser_login_finished(self, result: dict):
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
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
            msg = result.get("message", "Đăng nhập Threads chưa hoàn tất.")
            if "hủy" not in msg.lower():
                QMessageBox.warning(self, "Thông Báo Đăng Nhập", msg)

    def on_open_browser(self, acc: dict):
        self.progress_dialog = QProgressDialog(
            f"Đang chuẩn bị mở trình duyệt cho tài khoản {acc.get('name', '')}...",
            "Hủy", 0, 0, self
        )
        self.progress_dialog.setWindowTitle("Mở Trình Duyệt Threads")
        self.progress_dialog.setWindowModality(Qt.NonModal)
        self.progress_dialog.show()

        self.open_worker = ThreadsOpenBrowserWorker(acc["cookie"], proxy=acc.get("proxy", ""), uid=acc.get("uid", ""))
        self.open_worker.progress_signal.connect(self.progress_dialog.setLabelText)
        self.open_worker.finished_signal.connect(self.on_open_browser_finished)
        self.progress_dialog.canceled.connect(self.open_worker.cancel)
        self.open_worker.start()

    def on_open_browser_finished(self, res: dict):
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
        if res.get("cookie") and res.get("uid"):
            self.db.update_threads_cookie(res["uid"], res["cookie"])
            self.load_accounts()
        if not res.get("success"):
            msg = res.get("message", "Không thể mở trình duyệt Threads.")
            if "hủy" not in msg.lower():
                QMessageBox.warning(self, "Thông Báo", msg)

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
