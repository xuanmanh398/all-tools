# -*- coding: utf-8 -*-
"""
Threads Worker Process - Chạy Playwright trên Main Thread của tiến trình riêng biệt.
Loại bỏ 100% lỗi deadlock IOCP Pipe của Windows khi gọi Playwright từ QThread.
"""

import sys
import os
import time
import json
import subprocess

# Xóa bỏ NODE_OPTIONS độc hại từ môi trường hệ thống (ví dụ preload-hook.mjs của OpenClaw)
# gây hỏng giao thức Pipe nhị phân của Playwright node.exe driver
os.environ.pop("NODE_OPTIONS", None)
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

# Chuyển hướng stdout/stderr sang UTF-8 (kể cả khi chạy từ PyInstaller console=False)
if sys.stdout is None:
    try:
        sys.stdout = os.fdopen(1, "w", encoding="utf-8", errors="replace", buffering=1)
    except Exception:
        pass
elif hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if sys.stderr is None:
    try:
        sys.stderr = os.fdopen(2, "w", encoding="utf-8", errors="replace", buffering=1)
    except Exception:
        pass
elif hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Đảm bảo PLAYWRIGHT_BROWSERS_PATH được thiết lập chính xác
def ensure_playwright_browsers_path():
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(app_dir, "ms-playwright"),
        os.path.join(app_dir, "_internal", "ms-playwright"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"),
        os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local", "ms-playwright"),
    ]
    for c in candidates:
        if os.path.exists(c):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = c
            break

ensure_playwright_browsers_path()

from playwright.sync_api import sync_playwright
from core.database import get_app_data_dir
from core.threads_automation import get_threads_session_file_path, ThreadsAutomationEngine
from core.fb_automation import FBAutomationEngine


def emit_progress(msg: str):
    """Gửi thông báo tiến trình về cho tiến trình cha GUI đọc qua stdout."""
    print(f"PROGRESS: {msg}", flush=True)


def emit_result(data: dict):
    """Gửi kết quả cuối cùng về cho tiến trình cha GUI dưới dạng JSON."""
    print(f"RESULT: {json.dumps(data, ensure_ascii=False)}", flush=True)


def launch_best_browser(p, proxy: str = ""):
    """
    Thử lần lượt các chiến lược mở trình duyệt:
    1. Chromium do Playwright cài đặt (chrome.exe trong ms-playwright) -> Ổn định và nhanh nhất, không bị xung đột với Edge/Chrome đang chạy ngầm.
    2. Microsoft Edge hệ thống (channel="msedge")
    3. Google Chrome hệ thống (channel="chrome")
    4. Playwright Chromium mặc định
    5. Đường dẫn trực tiếp msedge.exe / chrome.exe / CocCoc / Brave
    """
    launch_args = [
        "--disable-notifications",
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--start-maximized"
    ]
    proxy_cfg = {"server": proxy.strip()} if proxy and proxy.strip() else None

    # Chiến lược 1: Playwright Chromium nội bộ (Giống hệt Facebook Automation đang hoạt động 100%)
    try:
        executable_path = FBAutomationEngine.get_chromium_executable_path(headless=False)
        if executable_path and os.path.exists(executable_path):
            print(f"[WORKER] Thử Chiến lược 1 - Chromium: {executable_path}", flush=True)
            emit_progress("Đang khởi động trình duyệt Chromium...")
            kwargs = {
                "executable_path": executable_path,
                "headless": False,
                "args": launch_args,
                "timeout": 12000
            }
            if proxy_cfg:
                kwargs["proxy"] = proxy_cfg
            browser = p.chromium.launch(**kwargs)
            emit_progress("✅ Đã mở Chromium thành công!")
            return browser
    except Exception as e:
        print(f"[WORKER] Chiến lược 1 thất bại: {e}", flush=True)

    # Chiến lược 2: Microsoft Edge hệ thống
    try:
        print("[WORKER] Thử Chiến lược 2 - Microsoft Edge", flush=True)
        emit_progress("Đang thử mở Microsoft Edge...")
        kwargs = {
            "channel": "msedge",
            "headless": False,
            "args": launch_args,
            "timeout": 8000
        }
        if proxy_cfg:
            kwargs["proxy"] = proxy_cfg
        browser = p.chromium.launch(**kwargs)
        emit_progress("✅ Đã mở Microsoft Edge thành công!")
        return browser
    except Exception as e:
        print(f"[WORKER] Chiến lược 2 thất bại: {e}", flush=True)

    # Chiến lược 3: Google Chrome hệ thống
    try:
        print("[WORKER] Thử Chiến lược 3 - Google Chrome", flush=True)
        emit_progress("Đang thử mở Google Chrome...")
        kwargs = {
            "channel": "chrome",
            "headless": False,
            "args": launch_args,
            "timeout": 8000
        }
        if proxy_cfg:
            kwargs["proxy"] = proxy_cfg
        browser = p.chromium.launch(**kwargs)
        emit_progress("✅ Đã mở Google Chrome thành công!")
        return browser
    except Exception as e:
        print(f"[WORKER] Chiến lược 3 thất bại: {e}", flush=True)

    # Chiến lược 4: Playwright Chromium mặc định
    try:
        print("[WORKER] Thử Chiến lược 4 - Playwright Chromium mặc định", flush=True)
        emit_progress("Đang thử mở Chromium mặc định...")
        kwargs = {
            "headless": False,
            "args": launch_args,
            "timeout": 8000
        }
        if proxy_cfg:
            kwargs["proxy"] = proxy_cfg
        browser = p.chromium.launch(**kwargs)
        emit_progress("✅ Đã mở Chromium mặc định thành công!")
        return browser
    except Exception as e:
        print(f"[WORKER] Chiến lược 4 thất bại: {e}", flush=True)

    # Chiến lược 5: Tìm kiếm đường dẫn trực tiếp trên ổ đĩa
    prog_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    prog_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    system_browsers = [
        os.path.join(prog_files_x86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(prog_files, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(local_app_data, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(prog_files, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(prog_files_x86, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(local_app_data, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(prog_files, r"CocCoc\Browser\Application\browser.exe"),
        os.path.join(prog_files_x86, r"CocCoc\Browser\Application\browser.exe"),
        os.path.join(local_app_data, r"CocCoc\Browser\Application\browser.exe"),
        os.path.join(prog_files, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.join(prog_files_x86, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for b_path in system_browsers:
        if os.path.exists(b_path):
            try:
                print(f"[WORKER] Thử Chiến lược 5: {b_path}", flush=True)
                kwargs = {
                    "executable_path": b_path,
                    "headless": False,
                    "args": launch_args,
                    "timeout": 8000
                }
                if proxy_cfg:
                    kwargs["proxy"] = proxy_cfg
                browser = p.chromium.launch(**kwargs)
                emit_progress(f"✅ Đã mở trình duyệt từ {os.path.basename(b_path)}!")
                return browser
            except Exception as e:
                print(f"[WORKER] Chiến lược 5 thất bại ({b_path}): {e}", flush=True)

    raise RuntimeError("Không thể mở trình duyệt (Chromium, Edge hoặc Chrome) trên máy tính. Vui lòng chạy lại file run.bat để cài đặt trình duyệt.")


def handle_login(proxy: str = ""):
    """Thực hiện đăng nhập trực tiếp trên trình duyệt."""
    emit_progress("Đang khởi động trình duyệt Threads...")
    browser = None
    context = None
    try:
        with sync_playwright() as p:
            browser = launch_best_browser(p, proxy=proxy)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                locale="vi-VN"
            )
            page = context.new_page()
            try:
                page.bring_to_front()
            except Exception:
                pass

            emit_progress("Đang tải Threads... Vui lòng xem cửa sổ trình duyệt để đăng nhập!")

            try:
                page.goto("https://www.threads.net/login", wait_until="commit", timeout=25000)
            except Exception:
                try:
                    page.goto("https://www.threads.com/login", wait_until="commit", timeout=25000)
                except Exception:
                    pass

            try:
                page.bring_to_front()
            except Exception:
                pass

            emit_progress("Cửa sổ Threads đã mở! Bạn hãy đăng nhập tài khoản Threads của mình.")

            start_time = time.time()
            while time.time() - start_time < 600:
                if len(context.pages) == 0:
                    emit_result({"success": False, "message": "Cửa sổ trình duyệt đã bị đóng trước khi đăng nhập."})
                    return

                cookies = context.cookies()
                has_session = any(c.get("name") in ("sessionid", "ds_user_id") for c in cookies)
                curr_url = page.url.lower()

                if has_session and ("login" not in curr_url):
                    emit_progress("Đã phát hiện đăng nhập thành công! Đang lưu phiên...")

                    uid = ""
                    for c in cookies:
                        if c.get("name") in ("ds_user_id", "c_user"):
                            uid = c.get("value", "")
                            break

                    username = f"user_{uid}" if uid else "threads_user"
                    try:
                        user_elem = page.query_selector('a[href^="/@"]')
                        if user_elem:
                            href = user_elem.get_attribute("href")
                            if href and href.startswith("/@"):
                                username = href.replace("/@", "").strip("/").strip()
                    except Exception:
                        pass

                    cookie_parts = [f"{c['name']}={c['value']}" for c in cookies if "threads." in c.get("domain", "") or "instagram.com" in c.get("domain", "")]
                    cookie_str = "; ".join(cookie_parts)

                    if uid:
                        try:
                            session_file = get_threads_session_file_path(uid)
                            context.storage_state(path=session_file)
                        except Exception:
                            pass

                    time.sleep(2)
                    try:
                        context.close()
                        browser.close()
                    except Exception:
                        pass

                    emit_result({
                        "success": True,
                        "uid": uid or username,
                        "username": username,
                        "name": f"@{username}",
                        "cookie": cookie_str
                    })
                    return

                time.sleep(1.5)

            emit_result({"success": False, "message": "Quá thời gian chờ đăng nhập (10 phút)."})
    except Exception as e:
        emit_result({"success": False, "message": f"Lỗi khởi chạy trình duyệt: {str(e)}"})
    finally:
        try:
            if context:
                context.close()
            if browser:
                browser.close()
        except Exception:
            pass


def handle_open(cookie_str: str, uid: str = "", proxy: str = ""):
    """Mở trình duyệt cho tài khoản đã có session/cookie."""
    emit_progress("Đang chuẩn bị trình duyệt Threads...")
    browser = None
    context = None
    try:
        with sync_playwright() as p:
            browser = launch_best_browser(p, proxy=proxy)

            session_file = get_threads_session_file_path(uid) if uid else None
            storage_state = None
            if session_file and os.path.exists(session_file):
                try:
                    with open(session_file, "r", encoding="utf-8") as f:
                        s_data = json.load(f)
                        if s_data.get("cookies"):
                            storage_state = session_file
                except Exception:
                    pass

            context = browser.new_context(
                storage_state=storage_state,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                locale="vi-VN"
            )

            if cookie_str:
                try:
                    engine = ThreadsAutomationEngine()
                    parsed = engine.parse_cookie_string(cookie_str)
                    if parsed:
                        context.add_cookies(parsed)
                except Exception:
                    pass

            page = context.new_page()
            try:
                page.bring_to_front()
            except Exception:
                pass

            emit_progress("Trình duyệt đã mở! Đang tải Threads...")

            try:
                page.goto("https://www.threads.net/", wait_until="commit", timeout=25000)
            except Exception:
                try:
                    page.goto("https://www.threads.com/", wait_until="commit", timeout=25000)
                except Exception:
                    pass

            try:
                page.bring_to_front()
            except Exception:
                pass

            emit_progress("Trình duyệt Threads đã mở thành công!\nĐóng cửa sổ trình duyệt khi xem xong để đồng bộ.")

            while len(context.pages) > 0:
                time.sleep(1)

            new_cookie_str = ""
            try:
                if uid:
                    session_file = get_threads_session_file_path(uid)
                    context.storage_state(path=session_file)
                current_cookies = context.cookies()
                parts = [f"{c['name']}={c['value']}" for c in current_cookies if "threads." in c.get("domain", "") or "instagram.com" in c.get("domain", "")]
                new_cookie_str = "; ".join(parts)
            except Exception:
                pass

            emit_result({"success": True, "uid": uid, "cookie": new_cookie_str, "message": "Đã đóng trình duyệt Threads."})
    except Exception as e:
        emit_result({"success": False, "message": f"Lỗi khi mở trình duyệt: {str(e)}"})
    finally:
        try:
            if context:
                context.close()
            if browser:
                browser.close()
        except Exception:
            pass


def main():
    if len(sys.argv) < 2:
        emit_result({"success": False, "message": "Thiếu tham số cho worker."})
        return

    mode = sys.argv[1].lower()
    if mode == "login":
        proxy = sys.argv[2] if len(sys.argv) > 2 else ""
        handle_login(proxy=proxy)
    elif mode == "open":
        uid = sys.argv[2] if len(sys.argv) > 2 else ""
        proxy = sys.argv[3] if len(sys.argv) > 3 else ""
        cookie_file = sys.argv[4] if len(sys.argv) > 4 else ""
        cookie_str = ""
        if cookie_file and os.path.exists(cookie_file):
            try:
                with open(cookie_file, "r", encoding="utf-8") as f:
                    cookie_str = f.read()
            except Exception:
                pass
        handle_open(cookie_str, uid=uid, proxy=proxy)
    else:
        emit_result({"success": False, "message": f"Chế độ {mode} không hợp lệ."})


if __name__ == "__main__":
    main()
