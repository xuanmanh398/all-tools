import sys
import os
import subprocess

# Xác định đường dẫn gốc của ứng dụng (hỗ trợ PyInstaller frozen exe)
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Thiết lập đường dẫn trình duyệt Playwright từ APP_DIR
local_ms_playwright = os.path.join(APP_DIR, "ms-playwright")
internal_ms_playwright = os.path.join(APP_DIR, "_internal", "ms-playwright")

if os.path.exists(local_ms_playwright):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = local_ms_playwright
elif os.path.exists(internal_ms_playwright):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = internal_ms_playwright

# Xác định thư mục dữ liệu an toàn có quyền ghi (chống lỗi C:\Program Files quyền Read-Only)
from core.database import get_app_data_dir
DATA_DIR = get_app_data_dir()
try:
    os.chdir(DATA_DIR)
except Exception:
    pass
os.makedirs("sessions", exist_ok=True)
os.makedirs("app_media", exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from ui.main_window import MainWindow

def ensure_playwright_browsers():
    """Kiểm tra và cấu hình trình duyệt cho ứng dụng."""
    try:
        from core.fb_automation import FBAutomationEngine
        # Kiểm tra xem hệ thống đã có trình duyệt phù hợp (Chromium, Edge, Chrome) chưa
        exec_path = FBAutomationEngine.get_chromium_executable_path(headless=False)
        if exec_path and os.path.exists(exec_path):
            return

        # Nếu chưa có và chạy ở môi trường phát triển (không frozen), thử tải Chromium
        if not getattr(sys, 'frozen', False):
            from playwright._impl._driver import compute_driver_executable
            node_exe, cli_js = compute_driver_executable()
            subprocess.run([node_exe, cli_js, "install", "chromium"], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        print(f"[WARNING] Trình duyệt hệ thống: {e}")

def main():
    # Đăng ký AppUserModelID để Windows Taskbar hiển thị chính xác icon phần mềm thay vì icon trắng mặc định
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("autopost.facebook.uploader.app.v1")
    except Exception:
        pass

    # Cấu hình hiển thị cho màn hình Windows High-DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Auto Post")
    app.setOrganizationName("AutoPost")

    # Đặt icon toàn hệ thống
    from core.database import get_asset_path
    icon_path = get_asset_path("icon.ico")
    if not os.path.exists(icon_path):
        icon_path = get_asset_path("icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Cấu hình Font mặc định với Font fallback Emoji hỗ trợ Unicode biểu tượng trên Windows
    QFont.insertSubstitutions("Segoe UI", ["Segoe UI Emoji", "Segoe UI Symbol", "Arial"])
    app_font = QFont("Segoe UI")
    app_font.setFamilies(["Segoe UI", "Segoe UI Emoji", "Segoe UI Symbol", "Arial"])
    app.setFont(app_font)

    ensure_playwright_browsers()

    from core.database import Database
    from core.license_manager import validate_license
    from ui.license_dialog import LicenseDialog
    from PySide6.QtWidgets import QDialog

    db = Database()

    # Bắt buộc luôn mở cửa sổ xác minh key trước khi vào phần mềm
    lic_dialog = LicenseDialog(db, is_blocking=True)
    if lic_dialog.exec() != QDialog.Accepted:
        # Người dùng chưa kích hoạt hoặc hủy bỏ hộp thoại
        sys.exit(0)

    # Kiểm tra lại bản quyền đã xác minh để vào phần mềm tức thì, không làm đơ giao diện
    from core.license_manager import get_cached_license, parse_expiry_date, get_machine_id
    cached = get_cached_license(db)
    if not cached or cached.get("machine_id") != get_machine_id(db):
        sys.exit(0)
    _, is_valid, _ = parse_expiry_date(cached.get("expiry_raw", ""))
    if not is_valid:
        sys.exit(0)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
