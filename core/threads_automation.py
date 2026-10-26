import asyncio
import json
import re
import os
import time
from typing import List, Dict, Any, Optional, Callable
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
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-session-crashed-bubble"
        ]

        proxy_config = None
        if proxy and proxy.strip():
            proxy_config = {"server": proxy.strip()}

        executable_path = FBAutomationEngine.get_chromium_executable_path(headless=headless)
        launch_kwargs = {
            "headless": headless,
            "args": launch_args,
            "proxy": proxy_config
        }

        browser = None
        # Chiến lược 1: Thử executable_path tìm thấy
        if executable_path and os.path.exists(executable_path):
            try:
                launch_kwargs["executable_path"] = executable_path
                browser = await playwright.chromium.launch(**launch_kwargs)
            except Exception:
                browser = None

        # Chiến lược 2: Microsoft Edge (100% có sẵn trên Windows 10/11)
        if browser is None:
            try:
                browser = await playwright.chromium.launch(channel="msedge", headless=headless, args=launch_args, proxy=proxy_config)
            except Exception:
                browser = None

        # Chiến lược 3: Google Chrome (Kênh channel chính thức)
        if browser is None:
            try:
                browser = await playwright.chromium.launch(channel="chrome", headless=headless, args=launch_args, proxy=proxy_config)
            except Exception:
                browser = None

        # Chiến lược 4: Playwright Chromium mặc định
        if browser is None:
            try:
                clean_kwargs = {"headless": headless, "args": launch_args, "proxy": proxy_config}
                browser = await playwright.chromium.launch(**clean_kwargs)
            except Exception:
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
                        browser = await playwright.chromium.launch(
                            executable_path=p_path,
                            headless=headless,
                            args=launch_args,
                            proxy=proxy_config
                        )
                        if browser:
                            break
                    except Exception:
                        pass

        if browser is None:
            raise RuntimeError("Không thể khởi chạy trình duyệt trên máy tính. Vui lòng đảm bảo máy tính đã cài Microsoft Edge hoặc Google Chrome.")

        session_file = get_threads_session_file_path(uid) if uid else None
        storage_state = session_file if (session_file and os.path.exists(session_file)) else None

        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        context = await browser.new_context(
            storage_state=storage_state,
            viewport=None,
            user_agent=user_agent,
            locale="vi-VN"
        )

        if cookies:
            try:
                await context.add_cookies(cookies)
            except Exception:
                pass

        return browser, context

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
            async with async_playwright() as p:
                browser, context = await self.create_context(p, cookies=[], proxy=proxy, headless=False)
                page = await context.new_page()

                if progress_callback:
                    progress_callback("Đang mở Threads... Vui lòng đăng nhập tài khoản Threads trên trình duyệt.")

                # Thử mở trang login của Threads / Instagram
                try:
                    await page.goto("https://www.threads.net/login", wait_until="domcontentloaded", timeout=45000)
                except Exception:
                    try:
                        await page.goto("https://www.threads.com/login", wait_until="domcontentloaded", timeout=45000)
                    except Exception:
                        try:
                            await page.goto("https://www.threads.net/", wait_until="domcontentloaded", timeout=45000)
                        except Exception:
                            pass

                try:
                    await page.bring_to_front()
                except Exception:
                    pass

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
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """Mở trình duyệt trực tiếp với tài khoản Threads đã lưu để người dùng quan sát/thao tác."""
        cookies = self.parse_cookie_string(cookie_str)
        if not uid:
            uid = self.extract_uid_from_cookie(cookies)

        browser = None
        context = None
        try:
            async with async_playwright() as p:
                browser, context = await self.create_context(p, cookies, proxy=proxy, headless=False, uid=uid)
                page = await context.new_page()
                try:
                    await page.goto("https://www.threads.net/", wait_until="domcontentloaded", timeout=45000)
                except Exception:
                    try:
                        await page.goto("https://www.threads.com/", wait_until="domcontentloaded", timeout=45000)
                    except Exception:
                        pass

                try:
                    await page.bring_to_front()
                except Exception:
                    pass

                if progress_callback:
                    progress_callback("Trình duyệt Threads đã mở thành công!\nĐóng cửa sổ trình duyệt khi hoàn tất để đồng bộ.")

                while True:
                    if len(context.pages) == 0:
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
        success_callback: Optional[Callable[[str, str], None]] = None
    ):
        """
        Phiên bình luận Threads duy nhất (Không bao giờ tắt/bật trình duyệt liên tục).
        - Nếu target_urls có danh sách link: Lần lượt mở và bình luận từng link trên cùng 1 trình duyệt.
        - Nếu target_urls rỗng: Tự động lướt Bảng tin Threads và bình luận liên tục cho đến khi người dùng bấm Dừng thủ công.
        """
        cookies = self.parse_cookie_string(cookie_str)
        if not uid:
            uid = self.extract_uid_from_cookie(cookies)

        from core.anti_spam import AntiSpamManager, AntiSpamConfig
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

                        emit_log("BÌNH LUẬN", target_url, "RUNNING", f"Đang mở bài viết {idx}/{total}: {target_url}...")
                        try:
                            await page.goto(target_url, wait_until="domcontentloaded")
                            await page.wait_for_timeout(3000)

                            editor = await page.query_selector('div[role="textbox"][contenteditable="true"]')
                            if not editor:
                                emit_log("BÌNH LUẬN", target_url, "FAILED", "Không tìm thấy khung bình luận (bài có thể đã khóa comment).")
                                continue

                            parsed_cmt = SpintaxParser.parse(comment_text or "").strip()
                            await editor.click()
                            await page.wait_for_timeout(300)
                            if parsed_cmt:
                                await page.keyboard.insert_text(parsed_cmt)
                                await page.wait_for_timeout(500)

                            if media_paths:
                                valid_files = [m for m in media_paths if os.path.exists(m)]
                                if valid_files:
                                    exp = await page.query_selector('[aria-label="Mở rộng công cụ soạn"]')
                                    if exp:
                                        await exp.click()
                                        await page.wait_for_timeout(1000)
                                    fi = await page.query_selector('input[type="file"]')
                                    if fi:
                                        await fi.set_input_files(valid_files)
                                        await page.wait_for_timeout(3500)

                            # Bấm gửi
                            post_btn = None
                            for _ in range(10):
                                send_svg = await page.query_selector('svg[aria-label="Câu trả lời"], svg[aria-label="Reply"]')
                                if send_svg:
                                    h = await send_svg.evaluate_handle("el => el.closest(\"div[role='button']\") || el.parentElement")
                                    if h:
                                        post_btn = h.as_element()
                                        if post_btn:
                                            break
                                if not post_btn:
                                    all_b = await page.query_selector_all('div[role="button"]')
                                    for b in all_b:
                                        txt = (await b.inner_text()).strip()
                                        if txt in ["Đăng", "Trả lời", "Reply", "Post"]:
                                            box = await b.bounding_box()
                                            if box and box["y"] > 200:
                                                dis = await b.get_attribute("aria-disabled")
                                                if dis != "true":
                                                    post_btn = b
                                                    break
                                if post_btn:
                                    break
                                await page.wait_for_timeout(1000)

                            if post_btn:
                                await post_btn.click()
                                await page.wait_for_timeout(3500)
                                anti_mgr.record_post()
                                emit_log("BÌNH LUẬN", target_url, "SUCCESS", f"Đã bình luận thành công bài viết #{idx}: {target_url}")
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

                # --- TRƯỜNG HỢP 2: BÌNH LUẬN BẢNG TIN LIÊN TỤC (TẮT THỦ CÔNG MỚI THÔI) ---
                else:
                    emit_log("BÌNH LUẬN", "Bảng tin Threads", "RUNNING", "Đang mở Bảng tin Threads. Chế độ bình luận liên tục (cho đến khi bạn bấm Dừng thủ công)...")
                    await page.goto("https://www.threads.net/", wait_until="domcontentloaded")
                    await page.wait_for_timeout(3500)

                    seen_urls = set()
                    success_count = 0

                    while True:
                        if is_stopped_fn and is_stopped_fn():
                            emit_log("BÌNH LUẬN", "-", "STOPPED", f"Đã dừng tiến trình theo yêu cầu. Tổng cộng đã bình luận {success_count} bài.")
                            break

                        while is_paused_fn and is_paused_fn():
                            if is_stopped_fn and is_stopped_fn():
                                break
                            await asyncio.sleep(1)

                        try:
                            # Quét các bài viết trên feed chưa từng bình luận
                            next_post_url = None
                            for scroll_try in range(5):
                                links = await page.query_selector_all('a[href*="/post/"]')
                                for l in links:
                                    try:
                                        href = await l.get_attribute("href")
                                        if href and "/post/" in href:
                                            full = href if href.startswith("http") else f"https://www.threads.net{href}"
                                            clean = full.split("?")[0].rstrip("/")
                                            if clean not in seen_urls:
                                                next_post_url = clean
                                                break
                                    except Exception:
                                        continue

                                if next_post_url:
                                    break

                                # Nếu chưa có bài mới, cuộn trang xuống
                                await page.evaluate("window.scrollBy(0, 1500)")
                                await page.wait_for_timeout(2000)

                            if not next_post_url:
                                emit_log("BÌNH LUẬN", "Bảng tin Threads", "RUNNING", "Đang tải thêm bài viết mới từ Bảng tin...")
                                await page.goto("https://www.threads.net/", wait_until="domcontentloaded")
                                await page.wait_for_timeout(3000)
                                for _ in range(3):
                                    await page.evaluate("window.scrollBy(0, 1800)")
                                    await page.wait_for_timeout(1500)
                                continue

                            # Đã tìm thấy bài viết mục tiêu mới trên feed
                            seen_urls.add(next_post_url)
                            emit_log("BÌNH LUẬN", next_post_url, "RUNNING", f"Đang mở bài viết #{success_count + 1} trên Bảng tin: {next_post_url}...")

                            try:
                                await page.goto(next_post_url, wait_until="domcontentloaded")
                                await page.wait_for_timeout(3000)

                                editor = await page.query_selector('div[role="textbox"][contenteditable="true"]')
                                if not editor:
                                    reply_input = await page.query_selector('div:has-text("Reply to"), div:has-text("Trả lời"), div:has-text("Bình luận")')
                                    if reply_input:
                                        await reply_input.click()
                                        await page.wait_for_timeout(1000)
                                        editor = await page.query_selector('div[role="textbox"][contenteditable="true"]')

                                if not editor:
                                    emit_log("BÌNH LUẬN", next_post_url, "FAILED", "Bài viết này không có khung bình luận hoặc đã bị khóa.")
                                    await page.goto("https://www.threads.net/", wait_until="domcontentloaded")
                                    await page.wait_for_timeout(2000)
                                    continue

                                parsed_cmt = SpintaxParser.parse(comment_text or "").strip()
                                await editor.click()
                                await page.wait_for_timeout(300)
                                if parsed_cmt:
                                    await page.keyboard.insert_text(parsed_cmt)
                                    await page.wait_for_timeout(500)

                                if media_paths:
                                    valid_files = [m for m in media_paths if os.path.exists(m)]
                                    if valid_files:
                                        exp = await page.query_selector('[aria-label="Mở rộng công cụ soạn"]')
                                        if exp:
                                            await exp.click()
                                            await page.wait_for_timeout(1000)
                                        fi = await page.query_selector('input[type="file"]')
                                        if fi:
                                            await fi.set_input_files(valid_files)
                                            await page.wait_for_timeout(3500)

                                # Bấm nút gửi bình luận
                                post_btn = None
                                for _ in range(10):
                                    send_svg = await page.query_selector('svg[aria-label="Câu trả lời"], svg[aria-label="Reply"]')
                                    if send_svg:
                                        h = await send_svg.evaluate_handle("el => el.closest(\"div[role='button']\") || el.parentElement")
                                        if h:
                                            post_btn = h.as_element()
                                            if post_btn:
                                                break
                                    if not post_btn:
                                        all_b = await page.query_selector_all('div[role="button"]')
                                        for b in all_b:
                                            txt = (await b.inner_text()).strip()
                                            if txt in ["Đăng", "Trả lời", "Reply", "Post"]:
                                                box = await b.bounding_box()
                                                if box and box["y"] > 200:
                                                    dis = await b.get_attribute("aria-disabled")
                                                    if dis != "true":
                                                        post_btn = b
                                                        break
                                    if post_btn:
                                        break
                                    await page.wait_for_timeout(1000)

                                if post_btn:
                                    await post_btn.click()
                                    await page.wait_for_timeout(3500)
                                    success_count += 1
                                    anti_mgr.record_post()
                                    emit_log("BÌNH LUẬN", next_post_url, "SUCCESS", f"Đã gửi bình luận thành công vào bài viết #{success_count}: {next_post_url}")
                                    if success_callback:
                                        success_callback(next_post_url, "BÌNH LUẬN")
                                    if progress_callback:
                                        progress_callback(success_count, 0)
                                else:
                                    emit_log("BÌNH LUẬN", next_post_url, "FAILED", "Không tìm thấy nút gửi bình luận.")

                            except Exception as e:
                                emit_log("BÌNH LUẬN", next_post_url, "FAILED", f"Lỗi khi bình luận: {str(e)}")

                            # Quay lại Bảng tin để tiếp tục tìm bài
                            try:
                                await page.goto("https://www.threads.net/", wait_until="domcontentloaded")
                                await page.wait_for_timeout(2500)
                            except Exception:
                                pass

                            # Giãn cách Anti-Spam
                            if not (is_stopped_fn and is_stopped_fn()):
                                delay_sec = anti_mgr.get_random_delay()
                                emit_log("ANTI-SPAM", "-", "WAITING", f"Nghỉ giãn cách {delay_sec}s trước bài tiếp theo...")
                                for _ in range(delay_sec):
                                    if is_stopped_fn and is_stopped_fn():
                                        break
                                    await asyncio.sleep(1)

                                if anti_mgr.should_rest() and not (is_stopped_fn and is_stopped_fn()):
                                    r_min = anti_config.rest_duration_min
                                    emit_log("ANTI-SPAM", "-", "RESTING", f"Đã bình luận {anti_mgr.post_count} bài. Tạm nghỉ dài {r_min} phút chống checkpoint...")
                                    for _ in range(r_min * 60):
                                        if is_stopped_fn and is_stopped_fn():
                                            break
                                        await asyncio.sleep(1)

                        except Exception as outer_e:
                            emit_log("BÌNH LUẬN", "-", "WARNING", f"Có gián đoạn nhẹ: {str(outer_e)}. Tự động phục hồi Bảng tin...")
                            try:
                                await page.goto("https://www.threads.net/", wait_until="domcontentloaded")
                                await page.wait_for_timeout(3000)
                            except Exception:
                                pass

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
