import sys
import os
import subprocess

# Xóa bỏ NODE_OPTIONS độc hại từ môi trường hệ thống (ví dụ preload-hook.mjs của OpenClaw)
# gây hỏng giao thức Pipe nhị phân của Playwright node.exe driver
os.environ.pop("NODE_OPTIONS", None)
os.environ["PYTHONIOENCODING"] = "utf-8"

if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
try:
    import playwright._impl._driver as _pw_driver
    _orig_get_driver_env = _pw_driver.get_driver_env
    def _clean_get_driver_env():
        env = _orig_get_driver_env()
        env.pop("NODE_OPTIONS", None)
        return env
    _pw_driver.get_driver_env = _clean_get_driver_env
except Exception:
    pass

# Xác định đường dẫn gốc của ứng dụng (hỗ trợ PyInstaller frozen exe)
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Thiết lập đường dẫn trình duyệt Playwright từ APP_DIR
local_ms_playwright = os.path.join(APP_DIR, "ms-playwright")
internal_ms_playwright = os.path.join(APP_DIR, "_internal", "ms-playwright")
user_ms_playwright = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")

if os.path.exists(local_ms_playwright):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = local_ms_playwright
elif os.path.exists(internal_ms_playwright):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = internal_ms_playwright
elif os.path.exists(user_ms_playwright):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = user_ms_playwright

if len(sys.argv) > 1 and sys.argv[1] == "--threads-worker":
    sys.argv.pop(1)
    from core.threads_worker import main as worker_main
    worker_main()
    sys.exit(0)


if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")
    except Exception:
        pass

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
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("toolsmarketing.app.v1")
    except Exception:
        pass

    # Cấu hình hiển thị cho màn hình Windows High-DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Tools Marketing")
    app.setOrganizationName("ToolsMarketing")

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

    # Kiểm tra bản quyền hiện tại: nếu đã kích hoạt hợp lệ thì vào thẳng ứng dụng
    from core.license_manager import get_cached_license, parse_expiry_date, get_machine_id
    cached = get_cached_license(db)
    has_valid_license = False
    if cached and cached.get("machine_id") == get_machine_id(db):
        _, is_valid, _ = parse_expiry_date(cached.get("expiry_raw", ""))
        if is_valid and cached.get("status") not in ("BLOCKED", "KHÓA", "TẠM KHÓA", "REVOKED", "EXPIRED"):
            has_valid_license = True

    # Nếu chưa kích hoạt hoặc hết hạn: mở hộp thoại xác minh bản quyền
    if not has_valid_license:
        lic_dialog = LicenseDialog(db, is_blocking=True)
        if lic_dialog.exec() != QDialog.Accepted:
            sys.exit(0)

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
