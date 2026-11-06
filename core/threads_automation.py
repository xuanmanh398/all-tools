import asyncio
import json
import re
import os
import time
import random
import subprocess
from typing import List, Dict, Any, Optional, Callable

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

from playwright.async_api import async_playwright, Page, BrowserContext, Browser
from core.spintax_parser import SpintaxParser
from core.database import get_app_data_dir
from core.fb_automation import FBAutomationEngine

def get_threads_session_file_path(uid: str) -> str:
    """Trả về đường dẫn lưu session Threads an toàn trong AppData."""
    session_dir = os.path.join(get_app_data_dir(), "sessions")
    os.makedirs(session_dir, exist_ok=True)
    filename = f"threads_{uid}_state.json"
    target_path = os.path.join(session_dir, filename)
    local_path = os.path.join("sessions", filename)
    if not os.path.exists(target_path) and os.path.exists(local_path):
        try:
            import shutil
            shutil.copy2(local_path, target_path)
        except Exception:
            pass
    return target_path

class ThreadsAutomationEngine:
    """
    Engine tự động hóa thao tác trên Threads (Instagram Threads) sử dụng Playwright (Async).
    Hỗ trợ Đăng nhập trực tiếp, Đăng bài mới, và Bình luận vào bài viết mục tiêu.
    """

    def __init__(self, db: Any = None):
        if db is not None:
            self.db = db
        else:
            try:
                from core.database import Database
                self.db = Database()
            except Exception:
                self.db = None

    @staticmethod
    def parse_cookie_string(cookie_str: str) -> List[Dict[str, Any]]:
        cookie_str = (cookie_str or "").strip()
        if not cookie_str:
            return []

        # Nếu là chuỗi JSON
        if cookie_str.startswith("[") or cookie_str.startswith("{"):
            try:
                data = json.loads(cookie_str)
                if isinstance(data, dict):
                    data = [data]
                formatted = []
                for c in data:
                    formatted.append({
                        "name": c.get("name", ""),
                        "value": c.get("value", ""),
                        "domain": c.get("domain", ".threads.net"),
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", True),
                        "httpOnly": c.get("httpOnly", False)
                    })
                return formatted
            except Exception:
                pass

        # Dạng name=val; name2=val2
        cookies = []
        parts = cookie_str.split(";")
        for part in parts:
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k:
                    cookies.append({
                        "name": k,
                        "value": v,
                        "domain": ".threads.net",
                        "path": "/",
                        "secure": True
                    })
        return cookies

    @staticmethod
    def extract_uid_from_cookie(cookies: List[Dict[str, Any]]) -> str:
        for c in cookies:
            if c.get("name") in ("ds_user_id", "c_user"):
                return c.get("value", "")
        return ""

    async def create_context(
        self,
        playwright,
        cookies: List[Dict[str, Any]],
        proxy: Optional[str] = None,
        headless: bool = False,
        uid: str = ""
    ) -> tuple[Browser, BrowserContext]:
        """Khởi tạo trình duyệt cho Threads với 5 tầng fallback siêu bền (Chromium -> Edge -> Chrome -> System Executable)."""
        launch_args = [
            "--disable-notifications",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--start-maximized"
        ]

        proxy_config = None
        if proxy and proxy.strip():
            proxy_config = {"server": proxy.strip()}

        executable_path = FBAutomationEngine.get_chromium_executable_path(headless=headless)
        launch_kwargs = {
            "headless": headless,
            "args": launch_args,
        }
        if proxy_config:
            launch_kwargs["proxy"] = proxy_config

        browser = None
        # Chiến lược 1: Thử executable_path tìm thấy
        if executable_path and os.path.exists(executable_path):
            try:
                print(f"[THREADS] Đang thử mở trình duyệt (Chiến lược 1: {executable_path})...")
                launch_kwargs["executable_path"] = executable_path
                browser = await asyncio.wait_for(playwright.chromium.launch(**launch_kwargs), timeout=10)
                print("[THREADS] ✅ Chiến lược 1 mở trình duyệt thành công!")
            except Exception as e:
                print(f"[THREADS] ⚠️ Chiến lược 1 không khả dụng: {e}")
                browser = None

        # Chiến lược 2: Microsoft Edge (100% có sẵn trên Windows 10/11)
        if browser is None:
            try:
                print("[THREADS] Đang thử mở Microsoft Edge hệ thống (Chiến lược 2)...")
                edge_kwargs = {"channel": "msedge", "headless": headless, "args": launch_args}
                if proxy_config:
                    edge_kwargs["proxy"] = proxy_config
                browser = await asyncio.wait_for(playwright.chromium.launch(**edge_kwargs), timeout=10)
                print("[THREADS] ✅ Chiến lược 2 (Microsoft Edge) thành công!")
            except Exception as e:
                print(f"[THREADS] ⚠️ Chiến lược 2 (Edge) không khả dụng: {e}")
                browser = None

        # Chiến lược 3: Google Chrome (Kênh channel chính thức)
        if browser is None:
            try:
                print("[THREADS] Đang thử mở Google Chrome hệ thống (Chiến lược 3)...")
                chrome_kwargs = {"channel": "chrome", "headless": headless, "args": launch_args}
                if proxy_config:
                    chrome_kwargs["proxy"] = proxy_config
                browser = await asyncio.wait_for(playwright.chromium.launch(**chrome_kwargs), timeout=10)
                print("[THREADS] ✅ Chiến lược 3 (Google Chrome) thành công!")
            except Exception as e:
                print(f"[THREADS] ⚠️ Chiến lược 3 (Chrome) không khả dụng: {e}")
                browser = None

        # Chiến lược 4: Playwright Chromium mặc định
        if browser is None:
            try:
                print("[THREADS] Đang thử mở Playwright Chromium mặc định (Chiến lược 4)...")
                clean_kwargs = {"headless": headless, "args": launch_args}
                if proxy_config:
                    clean_kwargs["proxy"] = proxy_config
                browser = await asyncio.wait_for(playwright.chromium.launch(**clean_kwargs), timeout=10)
                print("[THREADS] ✅ Chiến lược 4 thành công!")
            except Exception as e:
                print(f"[THREADS] ⚠️ Chiến lược 4 không khả dụng: {e}")
                browser = None

        # Chiến lược 5: Tìm kiếm trực tiếp đường dẫn msedge.exe hoặc chrome.exe phổ biến trên Windows
        if browser is None:
            common_paths = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                r"C:\Program Files\CocCoc\Browser\Application\browser.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\CocCoc\Browser\Application\browser.exe")
            ]
            for p_path in common_paths:
                if os.path.exists(p_path):
                    try:
                        print(f"[THREADS] Đang thử đường dẫn trực tiếp: {p_path}...")
                        p_kwargs = {"executable_path": p_path, "headless": headless, "args": launch_args}
                        if proxy_config:
                            p_kwargs["proxy"] = proxy_config
                        browser = await asyncio.wait_for(playwright.chromium.launch(**p_kwargs), timeout=10)
                        if browser:
                            print(f"[THREADS] ✅ Khởi chạy thành công từ: {p_path}")
                            break
                    except Exception as e:
                        print(f"[THREADS] ⚠️ Lỗi mở từ {p_path}: {e}")

        if browser is None:
            raise RuntimeError("Không thể khởi chạy trình duyệt trên máy tính. Vui lòng đảm bảo máy tính đã cài Microsoft Edge hoặc Google Chrome.")

        session_file = get_threads_session_file_path(uid) if uid else None
        storage_state = None
        if session_file and os.path.exists(session_file):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                    if s_data.get("cookies"):
                        storage_state = session_file
            except Exception:
                storage_state = None

        context = await browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1280, "height": 800},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh"
        )

        # Stealth Script: Ẩn hoàn toàn các dấu hiệu tự động hóa (navigator.webdriver) để chống Threads bắt xác minh con người
        try:
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                if (!window.chrome) {
                    window.chrome = { runtime: {} };
                }
                Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
            """)
        except Exception:
            pass

        if cookies:
            try:
                await context.add_cookies(cookies)
            except Exception:
                pass

        return browser, context

    @staticmethod
    def parse_like_count(raw_text: str) -> int:
        """
        Chuyển đổi chuỗi số lượt thích trên Threads (VD: '1,1K', '572', '1,2 N', '2,5 Tr', '1.250')
        thành số nguyên chính xác để lọc bài viết có tương tác cao.
        """
        if not raw_text:
            return 0
        s = str(raw_text).strip().upper()
        # Loại bỏ các chữ thừa nếu có
        s = re.sub(r'(LƯỢT THÍCH|THÍCH|LIKES|LIKE)', '', s).strip()
        if not s:
            return 0

        multiplier = 1
        if any(suf in s for suf in ['TR', 'TRIỆU', 'M', 'B']):
            multiplier = 1_000_000
            s = re.sub(r'(TRIỆU|TR|M|B)', '', s).strip()
        elif any(suf in s for suf in ['K', 'N', 'NGHÌN']):
            multiplier = 1_000
            s = re.sub(r'(NGHÌN|K|N)', '', s).strip()

        m = re.search(r'(\d+(?:[.,]\d+)?)', s)
        if not m:
            return 0
        num_str = m.group(1)

        try:
            if multiplier > 1:
                num_val = float(num_str.replace(',', '.'))
                return int(num_val * multiplier)
            else:
                # Nếu không có hậu tố K/M/N thì dấu chấm/phẩy (VD: 1.250 hoặc 1,250) là dấu phân cách hàng nghìn
                clean_digits = re.sub(r'[.,\s]', '', num_str)
                return int(clean_digits) if clean_digits.isdigit() else 0
        except Exception:
            return 0

    async def check_human_verification_challenge(self, page: Page) -> Optional[str]:
        """
        Kiểm tra xem Threads có đang hiển thị màn hình yêu cầu xác minh con người (Checkpoint / Challenge)
        hoặc giới hạn thao tác tạm thời hay không.
        """
        try:
            url_low = (page.url or "").lower()
            if "challenge" in url_low or "checkpoint" in url_low or "suspended" in url_low:
                return "Phát hiện URL yêu cầu xác minh tài khoản (Challenge / Checkpoint) trên Threads!"

            body_txt = await page.evaluate("""() => {
                return (document.body && document.body.innerText) ? document.body.innerText.slice(0, 1500) : "";
            }""")
            low = (body_txt or "").lower()
            challenge_phrases = [
                "confirm you're human",
                "confirm it's you",
                "xác nhận bạn là người thật",
                "xác nhận đó là bạn",
                "we restrict certain activity",
                "chúng tôi hạn chế một số hoạt động",
                "try again later",
                "thử lại sau"
            ]
            for phrase in challenge_phrases:
                if phrase in low:
                    return f"Threads đang yêu cầu xác minh hoặc tạm giới hạn thao tác ('{phrase}'). Đã tự động dừng để bảo vệ tài khoản!"
        except Exception:
            pass
        return None

    async def human_type_text(self, page: Page, editor: Any, text: str, human_simulation: bool = True):
        """
        Mô phỏng hành vi gõ phím tự nhiên của người thật (Human Keystroke Cadence):
        - Di chuyển chuột tới vị trí ngẫu nhiên trong ô nhập và click.
        - Gõ từng cụm ký tự ngắn với độ trễ biến thiên và nghỉ nhịp ở dấu câu/khoảng trắng.
        """
        if not text:
            return
        try:
            box = await editor.bounding_box()
            if box and box["width"] > 20 and box["height"] > 10:
                rx = box["x"] + random.uniform(10, min(80, box["width"] - 10))
                ry = box["y"] + random.uniform(5, min(25, box["height"] - 5))
                await page.mouse.move(rx, ry, steps=random.randint(4, 9))
                await page.wait_for_timeout(random.randint(120, 280))
                await page.mouse.click(rx, ry)
            else:
                await editor.click()
        except Exception:
            await editor.click()

        await page.wait_for_timeout(random.randint(350, 700))

        if not human_simulation:
            await page.keyboard.insert_text(text)
            await page.wait_for_timeout(500)
            return

        # Chia văn bản thành các cụm nhỏ tự nhiên (1-3 ký tự) để vừa tạo chuỗi sự kiện phím thật, vừa giữ nguyên Emoji/Unicode
        i = 0
        n = len(text)
        while i < n:
            chunk_len = random.choice([1, 1, 2, 2, 3])
            chunk = text[i:i + chunk_len]
            i += chunk_len
            await page.keyboard.insert_text(chunk)
            if any(c in chunk for c in ['\n', '.', '!', '?', ',']):
                await page.wait_for_timeout(random.randint(140, 320))
            elif ' ' in chunk:
                await page.wait_for_timeout(random.randint(55, 130))
            else:
                await page.wait_for_timeout(random.randint(25, 70))

        await page.wait_for_timeout(random.randint(500, 900))

    async def login_via_browser(
        self,
        proxy: str = "",
        progress_callback: Optional[Callable[[str], None]] = None,
        is_cancelled_fn: Optional[Callable[[], bool]] = None
    ) -> Dict[str, Any]:
        """
        Mở trình duyệt trực tiếp (Headful) tại Threads.net / Threads.com để người dùng tự đăng nhập.
        Tự động phát hiện khi đăng nhập thành công và trích xuất Session Cookie.
        """
        browser = None
        context = None
        try:
            if progress_callback:
                progress_callback("Đang chuẩn bị trình duyệt...")

            async with async_playwright() as p:
                if progress_callback:
                    progress_callback("Đang kết nối hệ thống trình duyệt...")

                browser, context = await self.create_context(p, cookies=[], proxy=proxy, headless=False)
                
                if progress_callback:
                    progress_callback("Trình duyệt đã khởi chạy! Đang mở trang Threads...")

                page = await context.new_page()
                try:
                    await page.bring_to_front()
                except Exception:
                    pass

                if progress_callback:
                    progress_callback("Đang tải trang đăng nhập Threads... Vui lòng xem cửa sổ trình duyệt!")
                print("[THREADS] Cửa sổ trình duyệt đã bật lên! Đang mở threads.net/login...")

                # Thử mở trang login của Threads / Instagram (commit để hiện cửa sổ ngay lập tức)
                try:
                    await page.goto("https://www.threads.net/login", wait_until="commit", timeout=25000)
                except Exception:
                    try:
                        await page.goto("https://www.threads.com/login", wait_until="commit", timeout=25000)
                    except Exception:
                        try:
                            await page.goto("https://www.threads.net/", wait_until="commit", timeout=25000)
                        except Exception:
                            pass

                try:
                    await page.bring_to_front()
                except Exception:
                    pass

                if progress_callback:
                    progress_callback("Cửa sổ Threads đã sẵn sàng! Bạn hãy đăng nhập tài khoản của mình.")

                start_time = time.time()
                max_wait_sec = 600  # 10 phút tối đa để người dùng thoải mái thao tác

                while time.time() - start_time < max_wait_sec:
                    if is_cancelled_fn and is_cancelled_fn():
                        try:
                            await context.close()
                            await browser.close()
                        except Exception:
                            pass
                        return {"success": False, "message": "Người dùng đã hủy đăng nhập."}

                    # Kiểm tra nếu người dùng đã đóng tất cả các tab
                    if len(context.pages) == 0:
                        try:
                            await context.close()
                            await browser.close()
                        except Exception:
                            pass
                        return {"success": False, "message": "Cửa sổ trình duyệt đã bị đóng."}

                    cookies = await context.cookies()
                    uid = self.extract_uid_from_cookie(cookies)
                    
                    # Lấy URL của trang đầu tiên còn mở
                    current_url = ""
                    try:
                        for p in context.pages:
                            if not p.is_closed():
                                current_url = p.url
                                break
                    except Exception:
                        pass

                    # Khi đã có ds_user_id hoặc sessionid và không còn ở trang login
                    has_session = any(c.get("name") in ("sessionid", "ds_user_id") for c in cookies)
                    if has_session and ("login" not in current_url.lower()):
                        if progress_callback:
                            progress_callback("Đã phát hiện đăng nhập thành công! Đang lưu phiên làm việc...")

                        cookie_parts = []
                        for c in cookies:
                            domain = c.get("domain", "")
                            if "threads." in domain or "instagram.com" in domain:
                                cookie_parts.append(f"{c['name']}={c['value']}")
                        cookie_str = "; ".join(cookie_parts)

                        username = f"user_{uid}" if uid else "threads_user"
                        try:
                            for p in context.pages:
                                if not p.is_closed():
                                    user_elem = await p.query_selector('a[href^="/@"]')
                                    if user_elem:
                                        href = await user_elem.get_attribute("href")
                                        if href and href.startswith("/@"):
                                            username = href.replace("/@", "").strip("/").strip()
                                            break
                        except Exception:
                            pass

                        # Lưu session vào ổ đĩa
                        if uid:
                            try:
                                session_file = get_threads_session_file_path(uid)
                                await context.storage_state(path=session_file)
                            except Exception:
                                pass

                        await asyncio.sleep(2)
                        try:
                            await context.close()
                            await browser.close()
                        except Exception:
                            pass
                        return {
                            "success": True,
                            "uid": uid or username,
                            "username": username,
                            "name": f"@{username}",
                            "cookie": cookie_str
                        }

                    await asyncio.sleep(1.5)

                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass
                return {"success": False, "message": "Quá thời gian chờ đăng nhập Threads (10 phút)."}

        except Exception as e:
            try:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception:
                pass
            return {"success": False, "message": f"Lỗi khởi chạy trình duyệt Threads: {str(e)}"}

    async def open_browser_with_cookie(
        self,
        cookie_str: str,
        proxy: str = "",
        uid: str = "",
        progress_callback: Optional[Callable[[str], None]] = None,
        is_cancelled_fn: Optional[Callable[[], bool]] = None
    ) -> Dict[str, Any]:
        """Mở trình duyệt trực tiếp với tài khoản Threads đã lưu để người dùng quan sát/thao tác."""
        cookies = self.parse_cookie_string(cookie_str)
        if not uid:
            uid = self.extract_uid_from_cookie(cookies)

        browser = None
        context = None
        try:
            if progress_callback:
                progress_callback("Đang chuẩn bị trình duyệt Threads...")
            print(f"[THREADS] Bắt đầu mở trình duyệt cho tài khoản UID: {uid}...")

            async with async_playwright() as p:
                if progress_callback:
                    progress_callback("Đang kết nối hệ thống trình duyệt...")

                browser, context = await self.create_context(p, cookies, proxy=proxy, headless=False, uid=uid)
                
                if progress_callback:
                    progress_callback("Trình duyệt đã khởi chạy! Đang tạo tab mới...")
                print("[THREADS] Trình duyệt đã kết nối! Đang tạo tab mới...")

                page = await context.new_page()
                try:
                    await page.bring_to_front()
                except Exception:
                    pass

                if progress_callback:
                    progress_callback("Cửa sổ đã sẵn sàng! Đang tải Threads...")
                print("[THREADS] Cửa sổ trình duyệt đã hiển thị! Đang tải trang threads.net...")

                try:
                    await page.goto("https://www.threads.net/", wait_until="commit", timeout=25000)
                except Exception:
                    try:
                        await page.goto("https://www.threads.com/", wait_until="commit", timeout=25000)
                    except Exception:
                        pass

                try:
                    await page.bring_to_front()
                except Exception:
                    pass

                if progress_callback:
                    progress_callback("Trình duyệt Threads đã mở thành công!\nĐóng cửa sổ trình duyệt khi hoàn tất để đồng bộ.")
                print("[THREADS] Đã mở trang Threads. Đang chờ người dùng đóng trình duyệt...")

                while True:
                    if is_cancelled_fn and is_cancelled_fn():
                        print("[THREADS] Người dùng đã bấm hủy mở trình duyệt.")
                        break
                    if len(context.pages) == 0:
                        print("[THREADS] Người dùng đã đóng tất cả các tab trình duyệt.")
                        break
                    await asyncio.sleep(1)

                new_cookie_str = ""
                try:
                    if uid:
                        session_file = get_threads_session_file_path(uid)
                        await context.storage_state(path=session_file)
                    current_cookies = await context.cookies()
                    parts = [f"{c['name']}={c['value']}" for c in current_cookies if "threads." in c.get("domain", "") or "instagram.com" in c.get("domain", "")]
                    new_cookie_str = "; ".join(parts)
                except Exception:
                    pass

                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

                return {"success": True, "uid": uid, "cookie": new_cookie_str, "message": "Đã đóng trình duyệt Threads và đồng bộ phiên làm việc."}
        except Exception as e:
            try:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception:
                pass
            return {"success": False, "message": f"Lỗi khi mở trình duyệt Threads: {str(e)}"}

    async def post_thread(
        self,
        cookie_str: str,
        text: str,
        media_paths: List[str] = None,
        proxy: str = "",
        headless: bool = True,
        uid: str = "",
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """Đăng một bài viết mới lên trang cá nhân Threads."""
        content = SpintaxParser.parse(text or "").strip()
        if not content and not media_paths:
            return {"success": False, "message": "Nội dung bài đăng Threads không được để trống!"}

        cookies = self.parse_cookie_string(cookie_str)
        if not uid:
            uid = self.extract_uid_from_cookie(cookies)

        browser = None
        context = None
        try:
            async with async_playwright() as p:
                browser, context = await self.create_context(p, cookies, proxy=proxy, headless=headless, uid=uid)
                page = await context.new_page()

                if progress_callback:
                    progress_callback("Đang truy cập Threads...")
                await page.goto("https://www.threads.net/", wait_until="domcontentloaded")
                await page.wait_for_timeout(3500)

                # Kiểm tra nếu đang có modal soạn thảo cũ còn sót lại thì hủy để tránh bị mở 2 lần
                existing_dialog = await page.query_selector('div[role="dialog"]')
                if existing_dialog:
                    cancel_btn = await existing_dialog.query_selector('div[role="button"]:has-text("Hủy"), div[role="button"]:has-text("Cancel")')
                    if cancel_btn:
                        await cancel_btn.click()
                        await page.wait_for_timeout(1000)
                        # Xác nhận hủy bản nháp nếu có
                        discard_btn = await page.query_selector('div[role="button"]:has-text("Bỏ"), div[role="button"]:has-text("Discard")')
                        if discard_btn:
                            await discard_btn.click()
                            await page.wait_for_timeout(1000)

                # Mở hộp thoại Tạo bài viết mới duy nhất (ưu tiên icon Tạo trên thanh điều hướng)
                dialog = await page.query_selector('div[role="dialog"]')
                if not dialog:
                    create_btn = await page.query_selector('nav svg[aria-label="Tạo"], nav svg[aria-label="Create"], svg[aria-label="Tạo"], svg[aria-label="Create"]')
                    if not create_btn:
                        create_btn = await page.query_selector('div:has-text("Bắt đầu chuỗi..."), div:has-text("Start a thread...")')

                    if create_btn:
                        await create_btn.click()
                        try:
                            dialog = await page.wait_for_selector('div[role="dialog"]', timeout=6000)
                        except Exception:
                            dialog = None

                # Định vị khung modal
                container = dialog if dialog else page

                # Tìm ô soạn thảo văn bản
                editor = await container.query_selector('div[role="textbox"][contenteditable="true"], div[contenteditable="true"]')
                if not editor:
                    return {"success": False, "message": "Không tìm thấy khung soạn thảo bài viết trên Threads (Vui lòng kiểm tra lại trạng thái đăng nhập)."}

                await editor.click()
                await page.wait_for_timeout(300)

                # Xóa sạch văn bản cũ (nếu có) và nhập văn bản an toàn không tạo thêm ô nhập
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await page.wait_for_timeout(200)

                if content:
                    if progress_callback:
                        progress_callback("Đang nhập nội dung bài viết...")
                    await page.keyboard.insert_text(content)
                    await page.wait_for_timeout(600)

                # Đính kèm hình ảnh/video nếu có
                if media_paths:
                    valid_files = [p for p in media_paths if os.path.exists(p)]
                    if valid_files:
                        file_input = await container.query_selector('input[type="file"]')
                        if not file_input:
                            file_input = await page.query_selector('input[type="file"]')
                        if file_input:
                            if progress_callback:
                                progress_callback(f"Đang tải lên {len(valid_files)} tệp media...")
                            await file_input.set_input_files(valid_files)
                            # Đợi tệp tải lên và hiển thị xem trước
                            await page.wait_for_timeout(4000)

                # Chờ nút Đăng (Post) sẵn sàng trong modal (y > 200 để loại trừ nút nháp ở thanh feed)
                post_btn = None
                for _ in range(15):
                    all_btns = await page.query_selector_all('div[role="button"]')
                    for b in all_btns:
                        try:
                            txt = (await b.inner_text()).strip()
                            if txt in ["Đăng", "Post", "Chia sẻ"]:
                                box = await b.bounding_box()
                                if box and box["y"] > 200:
                                    dis = await b.get_attribute("aria-disabled")
                                    if dis != "true":
                                        post_btn = b
                                        break
                        except Exception:
                            continue
                    if post_btn:
                        break
                    await page.wait_for_timeout(1000)

                if not post_btn:
                    return {"success": False, "message": "Nút 'Đăng' chưa sẵn sàng hoặc không tìm thấy."}

                if progress_callback:
                    progress_callback("Đang bấm Đăng bài lên Threads...")
                await post_btn.click()

                # Đợi xử lý đăng và modal biến mất
                await page.wait_for_timeout(3000)

                # Thu thập link bài viết vừa đăng chính xác
                post_url = ""
                try:
                    # Kiểm tra thông báo toast "Đã đăng. Xem"
                    view_link = await page.wait_for_selector('a:has-text("Xem"), a:has-text("View")', timeout=3000)
                    if view_link:
                        href = await view_link.get_attribute("href")
                        if href and "/post/" in href:
                            post_url = href if href.startswith("http") else f"https://www.threads.net{href}"
                except Exception:
                    pass

                # Nếu chưa lấy được từ toast, vào trang cá nhân của tài khoản để lấy link bài vừa đăng
                if not post_url and uid:
                    try:
                        accs = self.db.get_threads_accounts() if self.db else []
                        cur_acc = next((a for a in accs if a["uid"] == uid), None)
                        username = cur_acc.get("username") if cur_acc else ""
                        if not username:
                            username = uid
                        if username:
                            if progress_callback:
                                progress_callback("Đang vào trang cá nhân để xác nhận bài đăng và lấy link liên kết...")
                            await page.goto(f"https://www.threads.net/@{username}", wait_until="domcontentloaded")
                            await page.wait_for_timeout(3000)

                            # Chờ tối đa 12 giây để bài viết xuất hiện trên trang cá nhân
                            for attempt in range(6):
                                posts = await page.query_selector_all('a[href*="/post/"]')
                                for p_link in posts:
                                    href = await p_link.get_attribute("href")
                                    if href and "/post/" in href:
                                        post_url = href if href.startswith("http") else f"https://www.threads.net{href}"
                                        break
                                if post_url:
                                    break
                                await page.wait_for_timeout(2000)
                    except Exception:
                        pass

                # Bắt buộc phải có link bài viết chứa /post/ mới coi là hoàn tất thành công
                if not post_url or "/post/" not in post_url:
                    try:
                        await context.close()
                        await browser.close()
                    except Exception:
                        pass
                    return {"success": False, "message": "Bài viết chưa xuất bản lên trang cá nhân hoặc không lấy được liên kết."}

                # Lưu lại session state
                if uid:
                    try:
                        session_file = get_threads_session_file_path(uid)
                        await context.storage_state(path=session_file)
                    except Exception:
                        pass

                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

                return {"success": True, "post_url": post_url, "message": "Đã đăng bài lên Threads thành công!"}

        except Exception as e:
            try:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception:
                pass
            return {"success": False, "message": f"Lỗi khi đăng bài Threads: {str(e)}"}

    async def get_feed_post_urls(
        self,
        cookie_str: str,
        limit: int = 15,
        proxy: str = "",
        headless: bool = True,
        uid: str = "",
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> List[str]:
        """Lướt Bảng tin Threads và tự động thu thập danh sách URL các bài viết đang hiển thị."""
        cookies = self.parse_cookie_string(cookie_str)
        if not uid:
            uid = self.extract_uid_from_cookie(cookies)

        found_urls = []
        browser = None
        context = None
        try:
            async with async_playwright() as p:
                browser, context = await self.create_context(p, cookies, proxy=proxy, headless=headless, uid=uid)
                page = await context.new_page()

                if progress_callback:
                    progress_callback("Đang mở Bảng tin Threads để quét bài viết...")
                await page.goto("https://www.threads.net/", wait_until="domcontentloaded")
                await page.wait_for_timeout(3500)

                # Cuộn trang 3-5 lần để tải thêm các bài viết
                for scroll_idx in range(4):
                    links = await page.query_selector_all('a[href*="/post/"]')
                    for l in links:
                        try:
                            href = await l.get_attribute("href")
                            if href and "/post/" in href:
                                full_url = href if href.startswith("http") else f"https://www.threads.net{href}"
                                clean_url = full_url.split("?")[0].rstrip("/")
                                if clean_url not in found_urls and "/post/" in clean_url:
                                    found_urls.append(clean_url)
                                    if len(found_urls) >= limit:
                                        break
                        except Exception:
                            continue

                    if len(found_urls) >= limit:
                        break

                    await page.evaluate("window.scrollBy(0, 1200)")
                    await page.wait_for_timeout(2000)

                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

        except Exception:
            try:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception:
                pass

        return found_urls

    async def comment_on_thread(
        self,
        cookie_str: str,
        target_url: str,
        comment_text: str,
        media_paths: List[str] = None,
        proxy: str = "",
        headless: bool = True,
        uid: str = "",
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """Đi bình luận (Comment / Reply) vào một bài viết Threads mục tiêu (kèm ảnh/video tùy chọn)."""
        comment_content = SpintaxParser.parse(comment_text or "").strip()
        if not comment_content and not media_paths:
            return {"success": False, "message": "Nội dung bình luận Threads hoặc tệp đính kèm không được để trống!"}

        target_url = (target_url or "").strip()
        if not target_url or "threads.net" not in target_url:
            return {"success": False, "message": f"Link bài viết Threads không hợp lệ: '{target_url}'"}

        cookies = self.parse_cookie_string(cookie_str)
        if not uid:
            uid = self.extract_uid_from_cookie(cookies)

        browser = None
        context = None
        try:
            async with async_playwright() as p:
                browser, context = await self.create_context(p, cookies, proxy=proxy, headless=headless, uid=uid)
                page = await context.new_page()

                if progress_callback:
                    progress_callback(f"Đang mở bài viết mục tiêu: {target_url}...")
                await page.goto(target_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3500)

                # Tìm nút Reply / Trả lời hoặc khung nhập Reply dưới bài viết
                reply_btn = await page.query_selector('svg[aria-label="Reply"], svg[aria-label="Trả lời"], [aria-label*="Reply"], [aria-label*="Trả lời"]')
                if reply_btn:
                    await reply_btn.click()
                    await page.wait_for_timeout(1500)

                # Tìm ô nhập bình luận
                editor = await page.query_selector('div[role="textbox"][contenteditable="true"], div[contenteditable="true"]')
                if not editor:
                    # Thử click vào ô "Trả lời..." / "Reply to..."
                    reply_input = await page.query_selector('div:has-text("Reply to"), div:has-text("Trả lời"), div:has-text("Bình luận")')
                    if reply_input:
                        await reply_input.click()
                        await page.wait_for_timeout(1000)
                        editor = await page.query_selector('div[role="textbox"][contenteditable="true"], div[contenteditable="true"]')

                if not editor:
                    return {"success": False, "message": "Không tìm thấy khung bình luận (bài viết có thể đã tắt bình luận hoặc bị xóa)."}

                await editor.click()
                await page.wait_for_timeout(300)

                # Nhập nội dung bình luận
                if comment_content:
                    if progress_callback:
                        progress_callback("Đang nhập nội dung bình luận...")
                    await page.keyboard.insert_text(comment_content)
                    await page.wait_for_timeout(600)

                # Đính kèm hình ảnh/video nếu có (mở rộng công cụ soạn nếu cần)
                if media_paths:
                    valid_files = [p for p in media_paths if os.path.exists(p)]
                    if valid_files:
                        expand_btn = await page.query_selector('[aria-label="Mở rộng công cụ soạn"]')
                        if expand_btn:
                            await expand_btn.click()
                            await page.wait_for_timeout(1000)
                        file_input = await page.query_selector('input[type="file"]')
                        if file_input:
                            if progress_callback:
                                progress_callback(f"Đang đính kèm {len(valid_files)} tệp media vào bình luận...")
                            await file_input.set_input_files(valid_files)
                            await page.wait_for_timeout(3500)

                # Tìm nút Gửi / Đăng bình luận
                post_btn = None
                for _ in range(15):
                    # Ưu tiên nút icon mũi tên gửi bình luận
                    send_svg = await page.query_selector('svg[aria-label="Câu trả lời"], svg[aria-label="Reply"]')
                    if send_svg:
                        btn_handle = await send_svg.evaluate_handle("el => el.closest(\"div[role='button']\") || el.parentElement")
                        if btn_handle:
                            post_btn = btn_handle.as_element()
                            if post_btn:
                                break

                    # Tìm nút có chữ Đăng/Trả lời ở khu vực dưới bài viết (y > 200)
                    all_btns = await page.query_selector_all('div[role="button"]')
                    for b in all_btns:
                        try:
                            txt = (await b.inner_text()).strip()
                            if txt in ["Đăng", "Trả lời", "Reply", "Post"]:
                                box = await b.bounding_box()
                                if box and box["y"] > 200:
                                    dis = await b.get_attribute("aria-disabled")
                                    if dis != "true":
                                        post_btn = b
                                        break
                        except Exception:
                            continue
                    if post_btn:
                        break
                    await page.wait_for_timeout(1000)

                if not post_btn:
                    return {"success": False, "message": "Không tìm thấy nút gửi bình luận trên Threads."}

                if progress_callback:
                    progress_callback("Đang gửi bình luận vào bài viết...")
                await post_btn.click()
                await page.wait_for_timeout(4000)

                # Lưu session
                if uid:
                    try:
                        session_file = get_threads_session_file_path(uid)
                        await context.storage_state(path=session_file)
                    except Exception:
                        pass

                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

                return {"success": True, "target_url": target_url, "message": f"Đã bình luận thành công vào bài viết: {target_url}"}

        except Exception as e:
            try:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception:
                pass
            return {"success": False, "message": f"Lỗi khi bình luận Threads: {str(e)}"}

    async def run_posting_session(
        self,
        cookie_str: str,
        excel_posts: List[Dict[str, Any]],
        anti_config: Any = None,
        proxy: str = "",
        headless: bool = True,
        uid: str = "",
        loop_forever: bool = True,
        is_paused_fn: Optional[Callable[[], bool]] = None,
        is_stopped_fn: Optional[Callable[[], bool]] = None,
        log_callback: Optional[Callable[[str, str, str, str, str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ):
        """
        Phiên đăng bài Threads tuần tự và lặp vòng liên tục từ danh sách mẫu Excel (Cột A: Nội dung, Cột B: Folder ảnh).
        Giữ nguyên 1 trình duyệt duy nhất xuyên suốt toàn bộ quá trình để tối ưu tốc độ và phiên đăng nhập.
        """
        if not excel_posts:
            if log_callback:
                log_callback(time.strftime("%H:%M:%S"), "ĐĂNG BÀI", "-", "FAILED", "Danh sách mẫu bài viết từ file Excel đang trống!")
            return

        cookies = self.parse_cookie_string(cookie_str)
        if not uid:
            uid = self.extract_uid_from_cookie(cookies)

        from core.anti_spam import AntiSpamManager, AntiSpamConfig
        from core.excel_loader import get_fresh_media_for_post, ensure_upload_compatible_media
        if not anti_config:
            anti_config = AntiSpamConfig()
        anti_mgr = AntiSpamManager(anti_config)

        def emit_log(action: str, target: str, status: str, msg: str):
            if log_callback:
                log_callback(time.strftime("%H:%M:%S"), action, target, status, msg)

        browser = None
        context = None
        try:
            async with async_playwright() as p:
                browser, context = await self.create_context(p, cookies, proxy=proxy, headless=headless, uid=uid)
                page = await context.new_page()

                total_templates = len(excel_posts)
                cycle_count = 0
                total_posted = 0

                while True:
                    cycle_count += 1
                    emit_log(
                        "VÒNG LẶP",
                        f"Vòng #{cycle_count}",
                        "RUNNING",
                        f"🔄 Bắt đầu vòng đăng #{cycle_count} (Lần lượt từ Mẫu #1 -> Mẫu #{total_templates})..."
                    )

                    for idx, post_item in enumerate(excel_posts, start=1):
                        if is_stopped_fn and is_stopped_fn():
                            emit_log("ĐĂNG BÀI", "-", "STOPPED", f"Đã dừng tiến trình theo yêu cầu. Tổng số bài đã đăng: {total_posted}.")
                            break

                        while is_paused_fn and is_paused_fn():
                            if is_stopped_fn and is_stopped_fn():
                                break
                            await asyncio.sleep(1)

                        if is_stopped_fn and is_stopped_fn():
                            break

                        if progress_callback:
                            progress_callback(idx - 1, total_templates)

                        raw_text = post_item.get("content", "")
                        content = SpintaxParser.parse(raw_text or "").strip()
                        valid_files = get_fresh_media_for_post(post_item)
                        folder_disp = post_item.get("folder_path") or "(Không có folder)"
                        item_title = post_item.get("title") or f"Mẫu #{idx}"

                        if not content and not valid_files:
                            emit_log("ĐĂNG BÀI", item_title, "SKIPPED", f"Bỏ qua Mẫu #{idx} vì cả nội dung và thư mục ảnh đều trống.")
                            continue

                        emit_log(
                            "ĐĂNG BÀI",
                            f"Vòng {cycle_count} - Mẫu {idx}/{total_templates}",
                            "RUNNING",
                            f"Đang đăng [{item_title}] | Ảnh đính kèm: {len(valid_files)} tệp ({folder_disp})..."
                        )

                        try:
                            try:
                                await page.goto("https://www.threads.net/", wait_until="domcontentloaded", timeout=30000)
                            except Exception:
                                await page.goto("https://www.threads.com/", wait_until="domcontentloaded", timeout=30000)
                            await page.wait_for_timeout(3500)

                            challenge_msg = await self.check_human_verification_challenge(page)
                            if challenge_msg:
                                emit_log("BẢO VỆ TK", "-", "FAILED", f"🛡️ {challenge_msg}")
                                return

                            # Đóng modal cũ nếu còn sót lại
                            existing_dialog = await page.query_selector('div[role="dialog"]')
                            if existing_dialog:
                                cancel_btn = await existing_dialog.query_selector('div[role="button"]:has-text("Hủy"), div[role="button"]:has-text("Cancel")')
                                if cancel_btn:
                                    await cancel_btn.click()
                                    await page.wait_for_timeout(1000)
                                    discard_btn = await page.query_selector('div[role="button"]:has-text("Bỏ"), div[role="button"]:has-text("Discard")')
                                    if discard_btn:
                                        await discard_btn.click()
                                        await page.wait_for_timeout(1000)

                            # Mở hộp thoại Tạo bài viết mới
                            dialog = await page.query_selector('div[role="dialog"]')
                            if not dialog:
                                create_btn = await page.query_selector('nav svg[aria-label="Tạo"], nav svg[aria-label="Create"], svg[aria-label="Tạo"], svg[aria-label="Create"]')
                                if not create_btn:
                                    create_btn = await page.query_selector('div:has-text("Bắt đầu chuỗi..."), div:has-text("Start a thread..."), div:has-text("Có gì mới?"), div:has-text("What\'s new?")')
                                if create_btn:
                                    await create_btn.click()
                                    try:
                                        dialog = await page.wait_for_selector('div[role="dialog"]', timeout=6000)
                                    except Exception:
                                        dialog = None

                            container = dialog if dialog else page
                            editor = await container.query_selector('div[role="textbox"][contenteditable="true"], div[contenteditable="true"]')
                            if not editor:
                                emit_log("ĐĂNG BÀI", item_title, "FAILED", "Không tìm thấy khung soạn thảo bài viết trên Threads.")
                                continue

                            await editor.click()
                            await page.wait_for_timeout(300)
                            await page.keyboard.press("Control+A")
                            await page.keyboard.press("Backspace")
                            await page.wait_for_timeout(200)

                            if content:
                                await self.human_type_text(page, editor, content, human_simulation=True)

                            if valid_files:
                                file_input = await container.query_selector('input[type="file"]')
                                if not file_input:
                                    file_input = await page.query_selector('input[type="file"]')
                                if file_input:
                                    emit_log("ĐĂNG BÀI", item_title, "RUNNING", f"Đang tải lên {len(valid_files)} ảnh/video từ '{folder_disp}'...")
                                    await file_input.set_input_files(valid_files)
                                    await page.wait_for_timeout(4500)

                            clicked_submit = await self._click_submit_post_or_reply_button(page)
                            if not clicked_submit:
                                emit_log("ĐĂNG BÀI", item_title, "FAILED", "Nút 'Đăng' chưa sẵn sàng hoặc không tìm thấy.")
                                continue

                            await page.wait_for_timeout(3500)

                            post_url = ""
                            try:
                                view_link = await page.wait_for_selector('a:has-text("Xem"), a:has-text("View")', timeout=3500)
                                if view_link:
                                    href = await view_link.get_attribute("href")
                                    if href and "/post/" in href:
                                        post_url = href if href.startswith("http") else f"https://www.threads.net{href}"
                            except Exception:
                                pass

                            if not post_url and uid:
                                try:
                                    accs = self.db.get_threads_accounts() if self.db else []
                                    cur_acc = next((a for a in accs if a["uid"] == uid), None)
                                    username = (cur_acc.get("username") if cur_acc else "") or uid
                                    if username:
                                        await page.goto(f"https://www.threads.net/@{username}", wait_until="domcontentloaded")
                                        await page.wait_for_timeout(3000)
                                        for _ in range(5):
                                            posts_el = await page.query_selector_all('a[href*="/post/"]')
                                            for p_link in posts_el:
                                                href = await p_link.get_attribute("href")
                                                if href and "/post/" in href:
                                                    post_url = href if href.startswith("http") else f"https://www.threads.net{href}"
                                                    break
                                            if post_url:
                                                break
                                            await page.wait_for_timeout(2000)
                                except Exception:
                                    pass

                            total_posted += 1
                            anti_mgr.record_post()
                            target_link = post_url if (post_url and "/post/" in post_url) else "https://www.threads.net/"
                            emit_log(
                                "ĐĂNG BÀI",
                                target_link,
                                "SUCCESS",
                                f"✅ [Vòng #{cycle_count} - Mẫu {idx}/{total_templates}] Đã đăng thành công '{item_title}' ({len(valid_files)} ảnh)!"
                            )

                        except Exception as post_err:
                            emit_log("ĐĂNG BÀI", item_title, "FAILED", f"Lỗi khi đăng Mẫu #{idx}: {str(post_err)}")

                        if progress_callback:
                            progress_callback(idx, total_templates)

                        # Kiểm tra dừng trước khi chờ giãn cách
                        if is_stopped_fn and is_stopped_fn():
                            break
                        if not loop_forever and idx >= total_templates:
                            break

                        delay_sec = anti_mgr.get_random_delay()
                        next_idx = (idx % total_templates) + 1
                        emit_log("ANTI-SPAM", "-", "WAITING", f"Nghỉ giãn cách {delay_sec}s trước khi đăng Mẫu #{next_idx}...")
                        for _ in range(delay_sec):
                            if is_stopped_fn and is_stopped_fn():
                                break
                            while is_paused_fn and is_paused_fn():
                                if is_stopped_fn and is_stopped_fn():
                                    break
                                await asyncio.sleep(1)
                            await asyncio.sleep(1)

                        if anti_mgr.should_rest() and not (is_stopped_fn and is_stopped_fn()):
                            r_min = anti_config.rest_duration_min
                            emit_log("ANTI-SPAM", "-", "RESTING", f"Đã đăng {anti_mgr.post_count} bài. Tạm nghỉ dài {r_min} phút chống spam...")
                            for _ in range(r_min * 60):
                                if is_stopped_fn and is_stopped_fn():
                                    break
                                while is_paused_fn and is_paused_fn():
                                    if is_stopped_fn and is_stopped_fn():
                                        break
                                    await asyncio.sleep(1)
                                await asyncio.sleep(1)

                    if (is_stopped_fn and is_stopped_fn()) or not loop_forever:
                        break

                if uid:
                    try:
                        session_file = get_threads_session_file_path(uid)
                        await context.storage_state(path=session_file)
                    except Exception:
                        pass

                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

        except Exception as e:
            emit_log("ĐĂNG BÀI", "-", "FAILED", f"Lỗi phiên đăng bài Threads: {str(e)}")
            try:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception:
                pass

    async def _scan_feed_posts_with_likes(self, page: Page) -> List[Dict[str, Any]]:
        """
        Quét tất cả các bài viết đang hiển thị trên Bảng tin Threads kèm theo số lượt thích (Likes) thực tế.
        Hỗ trợ cấu trúc DOM mới của Threads:
        - Icon SVG dùng thuộc tính `title="Thích"` / `<title>Thích</title>` (hoặc `aria-label`)
        - Con số lượt thích nằm trong thẻ `span.x1o0tod.x10l6tqk.x13vifvy` bên trong nút Like
        - Nút mở bình luận dùng `title="Bình luận"` / `title="Trả lời"` / `title="Comment"` / `title="Reply"`
        """
        try:
            raw_items = await page.evaluate("""() => {
                const results = [];
                const seen = new Set();
                const origin = (window.location.origin && window.location.origin.startsWith('http'))
                    ? window.location.origin
                    : 'https://www.threads.com';

                const getSvgLabel = (svg) => {
                    const aria = svg.getAttribute('aria-label') || '';
                    const titleAttr = svg.getAttribute('title') || '';
                    const titleEl = svg.querySelector('title');
                    const titleText = titleEl ? (titleEl.textContent || '') : '';
                    return (aria || titleAttr || titleText).trim().toLowerCase();
                };

                // 1. Tìm tất cả icon Trái tim (Thích / Like / Bỏ thích / Unlike) trên Bảng tin
                const allSvgs = Array.from(document.querySelectorAll('svg'));
                const likeSvgs = allSvgs.filter(svg => {
                    const label = getSvgLabel(svg);
                    return label === 'thích' || label === 'like' || label === 'bỏ thích' || label === 'unlike';
                });

                for (const likeSvg of likeSvgs) {
                    // 2. Đi ngược từ <svg> lên khung nút Like (div[role="button"] hoặc container chỉ chứa đúng 1 icon SVG này)
                    let likePill = likeSvg.closest('div[role="button"]') || likeSvg;
                    while (likePill.parentElement && likePill.parentElement.querySelectorAll('svg').length === 1) {
                        likePill = likePill.parentElement;
                    }

                    // 3. Ưu tiên lấy số tim từ thẻ chuẩn xác `span.x1o0tod.x10l6tqk.x13vifvy` (như 6,6K, 1,2K, 250...)
                    let likeText = '';
                    if (likePill) {
                        const exactSpan = likePill.querySelector('span.x1o0tod.x10l6tqk.x13vifvy, span.x1o0tod');
                        if (exactSpan) {
                            likeText = (exactSpan.textContent || exactSpan.innerText || '').replace(/\\s+/g, ' ').trim();
                        } else {
                            const clone = likePill.cloneNode(true);
                            clone.querySelectorAll('svg, title').forEach(s => s.remove());
                            likeText = (clone.innerText || clone.textContent || '').replace(/\\s+/g, ' ').trim();
                        }
                    }
                    // Dự phòng nếu số like nằm ở phần tử kế tiếp ngang hàng với likePill
                    if (!likeText && likePill && likePill.nextElementSibling) {
                        const nextEl = likePill.nextElementSibling;
                        if (nextEl.querySelectorAll('svg').length === 0) {
                            const nextSpan = nextEl.querySelector('span.x1o0tod.x10l6tqk.x13vifvy, span.x1o0tod') || nextEl;
                            likeText = (nextSpan.textContent || nextSpan.innerText || '').replace(/\\s+/g, ' ').trim();
                        }
                    }

                    // 4. Đi ngược từ thanh công cụ lên thẻ bài viết (card) gần nhất có chứa link /post/
                    let card = likePill.parentElement;
                    let postLink = null;
                    for (let depth = 0; depth < 16 && card; depth++) {
                        postLink = card.querySelector('a[href*="/post/"]');
                        if (postLink) break;
                        card = card.parentElement;
                    }
                    if (!card || !postLink) continue;

                    const href = postLink.getAttribute('href') || '';
                    if (!href.includes('/post/')) continue;
                    const fullUrl = href.startsWith('http') ? href : (origin + (href.startsWith('/') ? href : '/' + href));
                    const cleanUrl = fullUrl.split('?')[0].replace(/\\/+$/, '');
                    if (seen.has(cleanUrl)) continue;
                    seen.add(cleanUrl);

                    const postCode = cleanUrl.split('/post/')[1] || '';
                    if (!postCode) continue;

                    // 5. Đánh dấu DOM để Playwright có thể cuộn và click chuột thật vào đúng nút Like / Bình luận của bài này
                    card.setAttribute('data-agy-card', postCode);
                    const clickableLike = likeSvg.closest('div[role="button"]') || likePill;
                    clickableLike.setAttribute('data-agy-like-btn', postCode);

                    const actionBar = likePill.parentElement || card;
                    const cardSvgs = Array.from(actionBar.querySelectorAll('svg'));
                    const replySvg = cardSvgs.find(s => {
                        const lbl = getSvgLabel(s);
                        return lbl === 'bình luận' || lbl === 'trả lời' || lbl === 'comment' || lbl === 'reply';
                    });
                    if (replySvg) {
                        const replyBtn = replySvg.closest('div[role="button"]') || replySvg.parentElement;
                        if (replyBtn) {
                            replyBtn.setAttribute('data-agy-reply-btn', postCode);
                        }
                    }

                    results.push({
                        url: cleanUrl,
                        postCode: postCode,
                        likeText: likeText
                    });
                }
                return results;
            }""")
        except Exception:
            return []

        parsed_list = []
        for item in (raw_items or []):
            l_txt = item.get("likeText", "")
            likes = self.parse_like_count(l_txt)
            parsed_list.append({
                "url": item.get("url", ""),
                "post_code": item.get("postCode", ""),
                "like_text": l_txt or "0",
                "likes": likes
            })
        return parsed_list

    async def _get_single_post_likes(self, page: Page) -> tuple[int, str]:
        """Lấy số lượt thích của bài viết chính khi đang mở trang chi tiết bài viết."""
        try:
            like_text = await page.evaluate("""() => {
                const getSvgLabel = (svg) => {
                    const aria = svg.getAttribute('aria-label') || '';
                    const titleAttr = svg.getAttribute('title') || '';
                    const titleEl = svg.querySelector('title');
                    const titleText = titleEl ? (titleEl.textContent || '') : '';
                    return (aria || titleAttr || titleText).trim().toLowerCase();
                };
                const allSvgs = Array.from(document.querySelectorAll('svg'));
                const likeSvg = allSvgs.find(svg => {
                    const label = getSvgLabel(svg);
                    return label === 'thích' || label === 'like' || label === 'bỏ thích' || label === 'unlike';
                });
                if (!likeSvg) return '';
                let likePill = likeSvg.closest('div[role="button"]') || likeSvg;
                while (likePill.parentElement && likePill.parentElement.querySelectorAll('svg').length === 1) {
                    likePill = likePill.parentElement;
                }
                if (likePill) {
                    const exactSpan = likePill.querySelector('span.x1o0tod.x10l6tqk.x13vifvy, span.x1o0tod');
                    if (exactSpan) {
                        const t = (exactSpan.textContent || exactSpan.innerText || '').replace(/\\s+/g, ' ').trim();
                        if (t) return t;
                    }
                    const clone = likePill.cloneNode(true);
                    clone.querySelectorAll('svg, title').forEach(s => s.remove());
                    const t2 = (clone.innerText || clone.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (t2) return t2;
                }
                return '';
            }""")
            return self.parse_like_count(like_text), (like_text or "0")
        except Exception:
            return 0, "0"

    async def _interact_and_open_reply_on_feed(self, page: Page, post_code: str, auto_like: bool = True) -> bool:
        """
        Cuộn mượt tới bài viết trên Bảng tin, đọc bài tự nhiên, thả tim (tùy chọn)
        và bấm nút Trả lời (Reply) ngay trên Bảng tin bằng sự kiện chuột thật của Playwright
        mà KHÔNG cần tải lại trang (page.goto) — giúp chống bị Threads bắt xác minh con người.
        """
        if not post_code:
            return False
        try:
            # 1. Cuộn bài viết vào giữa màn hình mượt mà như người dùng thật
            found = await page.evaluate("""(code) => {
                const card = document.querySelector(`[data-agy-card="${code}"]`);
                if (card) {
                    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    return true;
                }
                const links = Array.from(document.querySelectorAll('a[href*="/post/"]'));
                const targetLink = links.find(a => (a.getAttribute('href') || '').includes('/post/' + code));
                if (!targetLink) return false;
                targetLink.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return true;
            }""", post_code)
            if not found:
                return False

            # Nghỉ đọc bài tự nhiên 1.8s - 3.4s
            await page.wait_for_timeout(random.randint(1800, 3400))

            # 2. Tự động thả tim bài viết trước khi bình luận (xác suất 72% khi bật)
            if auto_like and random.random() < 0.72:
                try:
                    like_loc = page.locator(f'[data-agy-like-btn="{post_code}"]').first
                    if await like_loc.count() > 0:
                        await like_loc.click(timeout=3000)
                        await page.wait_for_timeout(random.randint(800, 1500))
                except Exception:
                    pass

            # 3. Bấm nút Trả lời (Reply) ngay trên thẻ bài viết ở Bảng tin bằng Playwright click thật
            clicked_reply = False
            try:
                reply_loc = page.locator(f'[data-agy-reply-btn="{post_code}"]').first
                if await reply_loc.count() > 0:
                    await reply_loc.click(timeout=4000)
                    clicked_reply = True
            except Exception:
                clicked_reply = False

            if not clicked_reply:
                clicked_reply = await page.evaluate("""(code) => {
                    const btn = document.querySelector(`[data-agy-reply-btn="${code}"]`);
                    if (btn) {
                        btn.click();
                        return true;
                    }
                    return false;
                }""", post_code)

            if clicked_reply:
                try:
                    await page.wait_for_selector(
                        'div[role="dialog"] div[role="textbox"][contenteditable="true"], div[role="textbox"][contenteditable="true"]',
                        timeout=5000
                    )
                    return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    async def _click_submit_post_or_reply_button(self, page: Page, max_wait_sec: int = 18) -> bool:
        """
        Tìm và nhấn nút 'Đăng' / 'Post' / 'Trả lời' / 'Reply' bên trong hộp thoại soạn bài / bình luận của Threads.
        Hỗ trợ cấu trúc DOM mới của Threads:
        - Nút 'Đăng' là thẻ `div.xc26acl` (Role: generic, như `div.xc26acl.x6s0dn4.xtlf3c...`) hoặc `div[role="button"]`
        - Chỉ tìm nút nằm trong cùng hộp thoại với ô soạn thảo (editor) và nằm trên cùng (không bị lớp phủ che khuất)
        - Chờ ảnh/video tải lên xong (không còn aria-disabled="true") rồi click bằng chuột thật của Playwright.
        """
        for _ in range(max_wait_sec):
            try:
                btn_info = await page.evaluate("""() => {
                    // 1. Tìm ô soạn thảo đang hiển thị trên màn hình (ưu tiên ô cuối cùng trong DOM thuộc modal vừa mở)
                    const editors = Array.from(document.querySelectorAll('div[role="textbox"][contenteditable="true"], div[contenteditable="true"]'));
                    const visibleEditors = editors.filter(el => {
                        const r = el.getBoundingClientRect();
                        return r.width > 20 && r.height > 10;
                    });
                    const editor = visibleEditors[visibleEditors.length - 1] || editors[0] || null;
                    const editorRect = editor ? editor.getBoundingClientRect() : { top: 80, left: 0 };

                    // 2. Xác định phạm vi hộp thoại (modal) chứa ô soạn thảo để không bấm nhầm nút ẩn phía sau nền
                    let scope = document.body;
                    if (editor) {
                        let curr = editor.parentElement;
                        while (curr && curr !== document.body) {
                            if (curr.getAttribute('role') === 'dialog') {
                                scope = curr;
                                break;
                            }
                            const txt = curr.innerText || '';
                            if ((txt.includes('Hủy') || txt.includes('Cancel') || txt.includes('Câu trả lời') || txt.includes('Reply')) &&
                                (txt.includes('Đăng') || txt.includes('Post') || txt.includes('Trả lời') || txt.includes('Reply'))) {
                                const cr = curr.getBoundingClientRect();
                                if (cr.width > 250 && cr.height > 150 && cr.width < window.innerWidth * 0.98) {
                                    scope = curr;
                                    break;
                                }
                            }
                            curr = curr.parentElement;
                        }
                    }

                    // 3. Quét tất cả ứng viên nút 'Đăng' (Ưu tiên thẻ `div.xc26acl` chuẩn xác từ giao diện Threads mới)
                    const candidates = Array.from(scope.querySelectorAll('div.xc26acl, div[role="button"], button, span'));
                    let bestEl = null;
                    let bestScore = -1;

                    for (const el of candidates) {
                        const rawTxt = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                        if (!['đăng', 'post', 'trả lời', 'reply', 'chia sẻ', 'share'].includes(rawTxt)) continue;

                        const rect = el.getBoundingClientRect();
                        if (rect.width < 25 || rect.height < 16 || rect.width > 240 || rect.height > 90) continue;

                        // Nút Đăng trong modal luôn nằm thấp hơn đỉnh của ô nhập văn bản
                        if (editor && rect.top < editorRect.top - 10) continue;

                        // Nếu ảnh đang tải lên, nút hoặc thẻ cha sẽ có aria-disabled="true"
                        if (el.closest('[aria-disabled="true"]')) continue;

                        const style = window.getComputedStyle(el);
                        if (style.pointerEvents === 'none' || style.visibility === 'hidden' || style.display === 'none' || parseFloat(style.opacity || '1') < 0.4) {
                            continue;
                        }

                        // Đảm bảo nút đang hiển thị trên cùng tại tâm của nó (không bị lớp nền modal che)
                        const cx = rect.left + rect.width / 2;
                        const cy = rect.top + rect.height / 2;
                        const topEl = document.elementFromPoint(cx, cy);
                        if (topEl && !el.contains(topEl) && !topEl.contains(el)) {
                            continue;
                        }

                        let score = rect.top * 2 + rect.left;
                        if (el.classList.contains('xc26acl')) score += 10000;
                        if (el.getAttribute('role') === 'button') score += 3000;

                        if (score > bestScore) {
                            bestScore = score;
                            bestEl = el;
                        }
                    }

                    if (!bestEl) return null;

                    document.querySelectorAll('[data-agy-submit-btn]').forEach(n => n.removeAttribute('data-agy-submit-btn'));
                    bestEl.setAttribute('data-agy-submit-btn', 'true');
                    const r = bestEl.getBoundingClientRect();
                    return {
                        x: r.left + r.width / 2,
                        y: r.top + r.height / 2
                    };
                }""")

                if btn_info:
                    clicked = False
                    try:
                        loc = page.locator('[data-agy-submit-btn="true"]').first
                        if await loc.count() > 0:
                            await loc.click(timeout=3500)
                            clicked = True
                    except Exception:
                        clicked = False

                    if not clicked and btn_info.get("x") and btn_info.get("y"):
                        await page.mouse.click(btn_info["x"], btn_info["y"])
                        clicked = True

                    if clicked:
                        await page.wait_for_timeout(1200)
                        # Kiểm tra nếu nút vẫn còn nguyên chưa phản hồi thì click tọa độ trực tiếp thêm 1 lần vào chính giữa thẻ div.xc26acl
                        still_there = await page.evaluate("""() => {
                            const btn = document.querySelector('[data-agy-submit-btn="true"]');
                            if (!btn) return null;
                            const r = btn.getBoundingClientRect();
                            if (r.width > 20 && r.height > 15 && !btn.closest('[aria-disabled="true"]')) {
                                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                            }
                            return null;
                        }""")
                        if still_there:
                            try:
                                await page.mouse.click(still_there["x"], still_there["y"])
                            except Exception:
                                pass
                        return True
            except Exception:
                pass
            await page.wait_for_timeout(1000)
        return False

    async def run_commenting_session(
        self,
        cookie_str: str,
        target_urls: List[str],
        comment_text: str,
        media_paths: List[str] = None,
        anti_config: Any = None,
        proxy: str = "",
        headless: bool = True,
        uid: str = "",
        is_paused_fn: Optional[Callable[[], bool]] = None,
        is_stopped_fn: Optional[Callable[[], bool]] = None,
        log_callback: Optional[Callable[[str, str, str, str, str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        success_callback: Optional[Callable[[str, str], None]] = None,
        excel_posts: Optional[List[Dict[str, Any]]] = None,
        min_likes: int = 0,
        human_simulation: bool = True
    ):
        """
        Phiên bình luận Threads duy nhất (Không bao giờ tắt/bật trình duyệt liên tục).
        - Hỗ trợ lọc bài viết có số lượt thích (Likes) tối thiểu do người dùng tự đặt.
        - Bình luận trực tiếp qua hộp thoại Reply ngay trên Bảng tin (không reload page.goto liên tục),
          kết hợp tự động thả tim và gõ phím theo nhịp người thật để chống bị Threads bắt xác minh con người.
        """
        cookies = self.parse_cookie_string(cookie_str)
        if not uid:
            uid = self.extract_uid_from_cookie(cookies)

        from core.anti_spam import AntiSpamManager, AntiSpamConfig
        from core.excel_loader import get_fresh_media_for_post, ensure_upload_compatible_media
        if not anti_config:
            anti_config = AntiSpamConfig()
        anti_mgr = AntiSpamManager(anti_config)

        def emit_log(action: str, target: str, status: str, msg: str):
            if log_callback:
                log_callback(time.strftime("%H:%M:%S"), action, target, status, msg)

        def get_next_template(seq_idx: int) -> tuple[str, List[str], str]:
            """Lấy mẫu bài viết kế tiếp theo vòng lặp tuần tự (1 -> 2 -> ... -> N -> 1)."""
            if excel_posts and len(excel_posts) > 0:
                item = excel_posts[seq_idx % len(excel_posts)]
                raw_txt = item.get("content", "")
                files = get_fresh_media_for_post(item)
                title = item.get("title") or f"Mẫu #{(seq_idx % len(excel_posts)) + 1}"
                return SpintaxParser.parse(raw_txt or "").strip(), files, title
            files = ensure_upload_compatible_media([m for m in (media_paths or []) if os.path.exists(m)])
            return SpintaxParser.parse(comment_text or "").strip(), files, "Mẫu trực tiếp"

        browser = None
        context = None
        try:
            async with async_playwright() as p:
                browser, context = await self.create_context(p, cookies, proxy=proxy, headless=headless, uid=uid)
                page = await context.new_page()

                # --- TRƯỜNG HỢP 1: CÓ DANH SÁCH LINK CỤ THỂ ---
                if target_urls and len(target_urls) > 0:
                    total = len(target_urls)
                    if progress_callback:
                        progress_callback(0, total)

                    for idx, target_url in enumerate(target_urls, 1):
                        if is_stopped_fn and is_stopped_fn():
                            emit_log("BÌNH LUẬN", "-", "STOPPED", "Đã dừng tiến trình theo yêu cầu.")
                            break

                        while is_paused_fn and is_paused_fn():
                            if is_stopped_fn and is_stopped_fn():
                                break
                            await asyncio.sleep(1)

                        parsed_cmt, valid_files, tpl_title = get_next_template(idx - 1)
                        emit_log("BÌNH LUẬN", target_url, "RUNNING", f"Đang mở bài viết {idx}/{total} [{tpl_title}]: {target_url}...")
                        try:
                            await page.goto(target_url, wait_until="domcontentloaded")
                            await page.wait_for_timeout(random.randint(2800, 4200))

                            challenge_msg = await self.check_human_verification_challenge(page)
                            if challenge_msg:
                                emit_log("BẢO VỆ TK", target_url, "FAILED", f"🛡️ {challenge_msg}")
                                break

                            if min_likes > 0:
                                cur_likes, cur_like_txt = await self._get_single_post_likes(page)
                                if cur_likes < min_likes:
                                    emit_log(
                                        "LỌC LIKE",
                                        target_url,
                                        "SKIPPED",
                                        f"⏭️ Bỏ qua bài viết vì có {cur_like_txt} lượt thích (< mức tối thiểu {min_likes} like)."
                                    )
                                    continue

                            editor = await page.query_selector('div[role="textbox"][contenteditable="true"]')
                            if not editor:
                                reply_btn = await page.query_selector(
                                    'svg[aria-label="Trả lời"], svg[aria-label="Reply"], svg[aria-label="Bình luận"], svg[aria-label="Comment"], '
                                    'svg[title="Trả lời"], svg[title="Reply"], svg[title="Bình luận"], svg[title="Comment"]'
                                )
                                if reply_btn:
                                    await reply_btn.click()
                                    await page.wait_for_timeout(1200)
                                    editor = await page.query_selector('div[role="textbox"][contenteditable="true"]')

                            if not editor:
                                emit_log("BÌNH LUẬN", target_url, "FAILED", "Không tìm thấy khung bình luận (bài có thể đã khóa comment).")
                                continue

                            if parsed_cmt:
                                await self.human_type_text(page, editor, parsed_cmt, human_simulation=human_simulation)

                            if valid_files:
                                exp = await page.query_selector('[aria-label="Mở rộng công cụ soạn"], svg[title="Đính kèm phương tiện"], svg[title="Attach media"]')
                                if exp:
                                    await exp.click()
                                    await page.wait_for_timeout(1000)
                                fi = await page.query_selector('input[type="file"]')
                                if fi:
                                    await fi.set_input_files(valid_files)
                                    await page.wait_for_timeout(3500)

                            # Bấm gửi bình luận (hỗ trợ cả div.xc26acl lẫn div[role="button"])
                            if await self._click_submit_post_or_reply_button(page):
                                await page.wait_for_timeout(3500)
                                anti_mgr.record_post()
                                emit_log("BÌNH LUẬN", target_url, "SUCCESS", f"✅ Đã bình luận thành công bài viết #{idx} [{tpl_title}]: {target_url}")
                                if success_callback:
                                    success_callback(target_url, "BÌNH LUẬN")
                            else:
                                emit_log("BÌNH LUẬN", target_url, "FAILED", "Không tìm thấy nút gửi bình luận.")

                        except Exception as e:
                            emit_log("BÌNH LUẬN", target_url, "FAILED", f"Lỗi thao tác: {str(e)}")

                        if progress_callback:
                            progress_callback(idx, total)

                        # Giãn cách Anti-Spam
                        if idx < total and not (is_stopped_fn and is_stopped_fn()):
                            delay_sec = anti_mgr.get_random_delay()
                            emit_log("ANTI-SPAM", "-", "WAITING", f"Nghỉ giãn cách {delay_sec}s trước bài tiếp theo...")
                            for _ in range(delay_sec):
                                if is_stopped_fn and is_stopped_fn():
                                    break
                                await asyncio.sleep(1)

                            if anti_mgr.should_rest() and not (is_stopped_fn and is_stopped_fn()):
                                r_min = anti_config.rest_duration_min
                                emit_log("ANTI-SPAM", "-", "RESTING", f"Tạm nghỉ dài {r_min} phút chống checkpoint...")
                                for _ in range(r_min * 60):
                                    if is_stopped_fn and is_stopped_fn():
                                        break
                                    await asyncio.sleep(1)

                # --- TRƯỜNG HỢP 2: BÌNH LUẬN BẢNG TIN LIÊN TỤC (LỌC THEO SỐ LIKE TỐI THIỂU & BÌNH LUẬN TRỰC TIẾP TRÊN FEED) ---
                else:
                    like_filter_desc = f" | Lọc bài >= {min_likes} Likes" if min_likes > 0 else " | Mọi bài viết"
                    emit_log(
                        "BÌNH LUẬN",
                        "Bảng tin Threads",
                        "RUNNING",
                        f"Đang mở Bảng tin Threads ({like_filter_desc} | Chế độ mô phỏng người thật chống Checkpoint)..."
                    )
                    try:
                        await page.goto("https://www.threads.net/", wait_until="domcontentloaded", timeout=30000)
                    except Exception:
                        await page.goto("https://www.threads.com/", wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(random.randint(3200, 4800))

                    # Khởi động phiên (Warm-up): Cuộn nhẹ đọc bảng tin như người thật trước khi bắt đầu
                    if human_simulation:
                        await page.mouse.wheel(0, random.randint(250, 500))
                        await page.wait_for_timeout(random.randint(1500, 2600))

                    seen_urls = set()
                    skipped_low_likes = 0
                    success_count = 0

                    while True:
                        if is_stopped_fn and is_stopped_fn():
                            emit_log("BÌNH LUẬN", "-", "STOPPED", f"Đã dừng tiến trình theo yêu cầu. Tổng cộng đã bình luận {success_count} bài.")
                            break

                        while is_paused_fn and is_paused_fn():
                            if is_stopped_fn and is_stopped_fn():
                                break
                            await asyncio.sleep(1)

                        challenge_msg = await self.check_human_verification_challenge(page)
                        if challenge_msg:
                            emit_log("BẢO VỆ TK", "-", "FAILED", f"🛡️ {challenge_msg}")
                            break

                        try:
                            # Quét các bài viết trên Bảng tin đáp ứng điều kiện số Like tối thiểu
                            candidate = None
                            recent_skipped_likes = []
                            for scroll_try in range(10):
                                if is_stopped_fn and is_stopped_fn():
                                    break
                                feed_posts = await self._scan_feed_posts_with_likes(page)
                                for fp in feed_posts:
                                    u = fp["url"]
                                    if not u or u in seen_urls:
                                        continue
                                    if min_likes > 0 and fp["likes"] < min_likes:
                                        seen_urls.add(u)
                                        skipped_low_likes += 1
                                        recent_skipped_likes.append(f"{fp['like_text']} ({fp['likes']})")
                                        continue
                                    candidate = fp
                                    break

                                if candidate:
                                    break

                                # Cuộn trang mượt mà bằng con lăn chuột như người thật
                                scroll_dy = random.randint(550, 950)
                                await page.mouse.wheel(0, scroll_dy)
                                await page.wait_for_timeout(random.randint(1600, 2600))

                            if not candidate:
                                sample_str = ", ".join(recent_skipped_likes[-5:]) if recent_skipped_likes else "0"
                                emit_log(
                                    "LỌC LIKE",
                                    "Bảng tin Threads",
                                    "RUNNING",
                                    f"Đang cuộn tìm bài >= {min_likes} Likes (Đã bỏ qua {skipped_low_likes} bài | Số like đọc được gần nhất: {sample_str})..."
                                )
                                await page.mouse.wheel(0, random.randint(800, 1300))
                                await page.wait_for_timeout(random.randint(2000, 3200))
                                continue

                            next_post_url = candidate["url"]
                            post_code = candidate["post_code"]
                            post_likes = candidate["likes"]
                            post_like_text = candidate["like_text"]
                            seen_urls.add(next_post_url)

                            parsed_cmt, valid_files, tpl_title = get_next_template(success_count)
                            emit_log(
                                "BÌNH LUẬN",
                                next_post_url,
                                "RUNNING",
                                f"🎯 Đã chọn bài #{success_count + 1} (❤️ {post_like_text} lượt thích >= {min_likes}) | Đang bình luận [{tpl_title}]..."
                            )

                            try:
                                # Ưu tiên bình luận trực tiếp qua hộp thoại Reply ngay trên Bảng tin (KHÔNG gọi page.goto)
                                opened_in_feed = await self._interact_and_open_reply_on_feed(
                                    page=page,
                                    post_code=post_code,
                                    auto_like=human_simulation
                                )

                                editor = None
                                if opened_in_feed:
                                    all_editors = await page.query_selector_all(
                                        'div[role="dialog"] div[role="textbox"][contenteditable="true"], '
                                        'div[role="textbox"][contenteditable="true"], div[contenteditable="true"]'
                                    )
                                    for ed in reversed(all_editors):
                                        try:
                                            box = await ed.bounding_box()
                                            if box and box["width"] > 20 and box["height"] > 10:
                                                editor = ed
                                                break
                                        except Exception:
                                            continue

                                if not editor:
                                    # Fallback: Nếu bài viết không mở được modal trên feed thì mới mở trang bài viết
                                    await page.goto(next_post_url, wait_until="domcontentloaded")
                                    await page.wait_for_timeout(random.randint(2800, 3800))
                                    editor = await page.query_selector('div[role="textbox"][contenteditable="true"]')
                                    if not editor:
                                        reply_input = await page.query_selector('div:has-text("Reply to"), div:has-text("Trả lời"), div:has-text("Bình luận")')
                                        if reply_input:
                                            await reply_input.click()
                                            await page.wait_for_timeout(1200)
                                            all_editors = await page.query_selector_all('div[role="textbox"][contenteditable="true"], div[contenteditable="true"]')
                                            for ed in reversed(all_editors):
                                                try:
                                                    box = await ed.bounding_box()
                                                    if box and box["width"] > 20 and box["height"] > 10:
                                                        editor = ed
                                                        break
                                                except Exception:
                                                    continue

                                if not editor:
                                    emit_log("BÌNH LUẬN", next_post_url, "FAILED", "Bài viết này không có khung bình luận hoặc đã bị khóa.")
                                    continue

                                if parsed_cmt:
                                    await self.human_type_text(page, editor, parsed_cmt, human_simulation=human_simulation)

                                if valid_files:
                                    exp = await page.query_selector('[aria-label="Mở rộng công cụ soạn"], svg[title="Đính kèm phương tiện"], svg[title="Attach media"]')
                                    if exp:
                                        try:
                                            await exp.click()
                                            await page.wait_for_timeout(1000)
                                        except Exception:
                                            pass
                                    fi_list = await page.query_selector_all('input[type="file"]')
                                    if fi_list:
                                        await fi_list[-1].set_input_files(valid_files)
                                        await page.wait_for_timeout(random.randint(3800, 5000))

                                # Bấm nút gửi bình luận (Ưu tiên thẻ div.xc26acl trong hộp thoại Câu trả lời)
                                if await self._click_submit_post_or_reply_button(page):
                                    await page.wait_for_timeout(random.randint(3500, 4800))
                                    success_count += 1
                                    anti_mgr.record_post()
                                    emit_log(
                                        "BÌNH LUẬN",
                                        next_post_url,
                                        "SUCCESS",
                                        f"✅ Đã bình luận bài #{success_count} (❤️ {post_like_text} likes) [{tpl_title}]: {next_post_url}"
                                    )
                                    if success_callback:
                                        success_callback(next_post_url, "BÌNH LUẬN")
                                    if progress_callback:
                                        progress_callback(success_count, 0)
                                else:
                                    emit_log("BÌNH LUẬN", next_post_url, "FAILED", "Không tìm thấy nút gửi bình luận.")
                                    # Đóng modal nếu bị kẹt
                                    await page.keyboard.press("Escape")
                                    await page.wait_for_timeout(1000)

                            except Exception as e:
                                emit_log("BÌNH LUẬN", next_post_url, "FAILED", f"Lỗi khi bình luận: {str(e)}")
                                try:
                                    await page.keyboard.press("Escape")
                                except Exception:
                                    pass

                            # Chỉ quay lại Bảng tin nếu trước đó phải rời khỏi trang chủ
                            if "/post/" in (page.url or ""):
                                try:
                                    await page.go_back(wait_until="domcontentloaded")
                                    await page.wait_for_timeout(2000)
                                except Exception:
                                    pass

                            # Giãn cách Anti-Spam (kèm cuộn nhẹ tự nhiên trong lúc chờ)
                            if not (is_stopped_fn and is_stopped_fn()):
                                delay_sec = anti_mgr.get_random_delay()
                                emit_log("ANTI-SPAM", "-", "WAITING", f"Nghỉ giãn cách {delay_sec}s trước bài tiếp theo (Mô phỏng lướt đọc tự nhiên)...")
                                for sec_i in range(delay_sec):
                                    if is_stopped_fn and is_stopped_fn():
                                        break
                                    while is_paused_fn and is_paused_fn():
                                        if is_stopped_fn and is_stopped_fn():
                                            break
                                        await asyncio.sleep(1)
                                    if human_simulation and sec_i > 0 and sec_i % 18 == 0:
                                        try:
                                            await page.mouse.wheel(0, random.randint(150, 350))
                                        except Exception:
                                            pass
                                    await asyncio.sleep(1)

                                if anti_mgr.should_rest() and not (is_stopped_fn and is_stopped_fn()):
                                    r_min = anti_config.rest_duration_min
                                    emit_log("ANTI-SPAM", "-", "RESTING", f"Đã bình luận {anti_mgr.post_count} bài. Tạm nghỉ dài {r_min} phút chống checkpoint...")
                                    for _ in range(r_min * 60):
                                        if is_stopped_fn and is_stopped_fn():
                                            break
                                        while is_paused_fn and is_paused_fn():
                                            if is_stopped_fn and is_stopped_fn():
                                                break
                                            await asyncio.sleep(1)
                                        await asyncio.sleep(1)

                        except Exception as outer_e:
                            emit_log("BÌNH LUẬN", "-", "WARNING", f"Có gián đoạn nhẹ: {str(outer_e)}. Tiếp tục quét Bảng tin...")
                            await asyncio.sleep(2)

                # Lưu session trước khi thoát
                if uid:
                    try:
                        session_file = get_threads_session_file_path(uid)
                        await context.storage_state(path=session_file)
                    except Exception:
                        pass

                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

        except Exception as e:
            emit_log("BÌNH LUẬN", "-", "FAILED", f"Lỗi phiên làm việc: {str(e)}")
            try:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception:
                pass
