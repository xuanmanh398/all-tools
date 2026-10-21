import asyncio
import json
import re
import os
import time
import base64
import mimetypes
from typing import List, Dict, Any, Optional, Callable
from playwright.async_api import async_playwright, Page, BrowserContext, Browser
from core.spintax_parser import SpintaxParser
from core.anti_spam import AntiSpamManager, AntiSpamConfig

def get_session_file_path(uid: str, page_id: str = "") -> str:
    """Trả về đường dẫn file lưu session an toàn trong AppData để không bị lỗi phân quyền."""
    from core.database import get_app_data_dir
    session_dir = os.path.join(get_app_data_dir(), "sessions")
    os.makedirs(session_dir, exist_ok=True)
    filename = f"{uid}_{page_id}_state.json" if page_id else f"{uid}_state.json"
    target_path = os.path.join(session_dir, filename)
    
    # Kiểm tra xem có file cũ ở thư mục làm việc cục bộ không để ưu tiên di chuyển sang
    local_path = os.path.join("sessions", filename)
    if not os.path.exists(target_path) and os.path.exists(local_path):
        try:
            import shutil
            shutil.copy2(local_path, target_path)
        except Exception:
            pass
            
    return target_path

class FBAutomationEngine:
    """
    Engine xử lý tự động hóa trình duyệt Facebook sử dụng Playwright (Async).
    """

    @staticmethod
    def parse_cookie_string(cookie_str: str) -> List[Dict[str, Any]]:
        """
        Chuyển đổi chuỗi Cookie (dạng c_user=1000...; xs=2...) thành định dạng Playwright.
        Hoặc hỗ trợ nhận vào định dạng JSON.
        """
        cookie_str = cookie_str.strip()
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
                        "domain": c.get("domain", ".facebook.com"),
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", True),
                        "httpOnly": c.get("httpOnly", False)
                    })
                return formatted
            except Exception:
                pass

        # Nếu là dạng key=value; key2=value2;
        cookies = []
        parts = cookie_str.split(";")
        for part in parts:
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k:
                    cookies.append({
                        "name": k,
                        "value": v,
                        "domain": ".facebook.com",
                        "path": "/",
                        "secure": True
                    })
        return cookies

    @staticmethod
    def extract_uid_from_cookie(cookies: List[Dict[str, Any]]) -> str:
        """Trích xuất UID (c_user) từ danh sách cookie."""
        for c in cookies:
            if c.get("name") == "c_user":
                return c.get("value", "")
        return ""

    @staticmethod
    def extract_i_user_from_cookie(cookies: List[Dict[str, Any]]) -> str:
        """Trích xuất i_user (ID Fanpage đang active) từ danh sách cookie."""
        for c in cookies:
            if c.get("name") == "i_user":
                return c.get("value", "")
        return ""

    async def safe_save_storage_state(self, context: BrowserContext, uid: str, page_id: str = ""):
        """
        Lưu trạng thái phiên (session) an toàn vào ổ đĩa.
        CHỈ lưu khi context thực sự đang ở trạng thái đã đăng nhập (có cookie c_user).
        Tránh trường hợp ghi đè session bằng trạng thái đã đăng xuất / checkpoint.
        """
        if not uid:
            return
        try:
            current_cookies = await context.cookies()
            has_c_user = any(c.get("name") == "c_user" for c in current_cookies)
            if has_c_user:
                save_path = get_session_file_path(uid, page_id)
                await context.storage_state(path=save_path)
        except Exception:
            pass

    @staticmethod
    def get_chromium_executable_path(headless: bool = False) -> Optional[str]:
        """
        Tự động tìm kiếm file thực thi phù hợp cho Chromium ở mọi thư mục/vị trí:
        - Nếu headless=True: ưu tiên chrome-headless-shell.exe, nếu không có thì fallback sang chrome.exe.
        - Nếu headless=False: sử dụng chrome.exe / msedge.exe.
        """
        import sys
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        candidates = [
            os.path.join(base_dir, "ms-playwright"),
            os.path.join(base_dir, "_internal", "ms-playwright"),
            os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local", "ms-playwright"),
        ]

        target_name = "chrome-headless-shell.exe" if headless else "chrome.exe"

        # Lần 1: Tìm kiếm đúng target_name
        for c in candidates:
            if os.path.exists(c):
                for root, dirs, files in os.walk(c):
                    if target_name in files:
                        full_p = os.path.join(root, target_name)
                        if os.path.exists(full_p):
                            return full_p

        # Lần 2: Nếu headless=True mà chưa tìm thấy chrome-headless-shell.exe, fallback sang chrome.exe
        if headless:
            for c in candidates:
                if os.path.exists(c):
                    for root, dirs, files in os.walk(c):
                        if "chrome.exe" in files:
                            full_p = os.path.join(root, "chrome.exe")
                            if os.path.exists(full_p):
                                return full_p

        # Fallback cho Google Chrome, Edge, Cốc Cốc, Brave có sẵn trên mọi phiên bản Windows
        prog_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        prog_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local_app_data = os.environ.get("LOCALAPPDATA", "")

        system_browsers = [
            os.path.join(prog_files, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(prog_files_x86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local_app_data, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(prog_files_x86, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(prog_files, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(local_app_data, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(prog_files, r"CocCoc\Browser\Application\browser.exe"),
            os.path.join(prog_files_x86, r"CocCoc\Browser\Application\browser.exe"),
            os.path.join(local_app_data, r"CocCoc\Browser\Application\browser.exe"),
            os.path.join(prog_files, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.join(prog_files_x86, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        ]
        for b in system_browsers:
            if os.path.exists(b):
                return b

        return None

    async def create_context(self, playwright, cookies: List[Dict[str, Any]], proxy: Optional[str] = None, headless: bool = False, uid: str = "", page_id: str = "") -> tuple[Browser, BrowserContext]:
        """Khởi tạo trình duyệt Chromium và thiết lập Cookie / Session State."""
        launch_args = [
            "--disable-notifications",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--start-maximized"
        ]

        proxy_config = None
        if proxy and proxy.strip():
            proxy_config = {"server": proxy.strip()}

        executable_path = self.get_chromium_executable_path(headless=headless)

        launch_kwargs = {
            "headless": headless,
            "args": launch_args,
            "proxy": proxy_config
        }

        browser = None
        # Chiến lược 1: Dùng executable_path tìm thấy
        if executable_path and os.path.exists(executable_path):
            try:
                launch_kwargs["executable_path"] = executable_path
                browser = await playwright.chromium.launch(**launch_kwargs)
            except Exception as e:
                print(f"[WARNING] Không thể mở trình duyệt từ executable_path ({executable_path}): {e}")
                browser = None

        # Chiến lược 2: Playwright Chromium mặc định
        if browser is None:
            try:
                clean_kwargs = {"headless": headless, "args": launch_args, "proxy": proxy_config}
                browser = await playwright.chromium.launch(**clean_kwargs)
            except Exception as e:
                print(f"[WARNING] Playwright Chromium mặc định không khả dụng: {e}")
                browser = None

        # Chiến lược 3: Microsoft Edge hệ thống (sẵn có 100% trên Windows 10/11)
        if browser is None:
            try:
                browser = await playwright.chromium.launch(channel="msedge", headless=headless, args=launch_args, proxy=proxy_config)
            except Exception as e:
                print(f"[WARNING] Trình duyệt Edge không khả dụng: {e}")
                browser = None

        # Chiến lược 4: Google Chrome hệ thống
        if browser is None:
            try:
                browser = await playwright.chromium.launch(channel="chrome", headless=headless, args=launch_args, proxy=proxy_config)
            except Exception as e:
                print(f"[WARNING] Google Chrome không khả dụng: {e}")
                browser = None

        if browser is None:
            raise RuntimeError("Không thể khởi chạy trình duyệt (Chromium, Edge hoặc Chrome). Vui lòng đảm bảo máy tính đã cài Microsoft Edge hoặc Google Chrome.")

        session_file = None
        if uid and page_id:
            p_file = get_session_file_path(uid, page_id)
            if os.path.exists(p_file):
                session_file = p_file

        if not session_file and uid:
            u_file = get_session_file_path(uid, "")
            if os.path.exists(u_file):
                session_file = u_file

        # Kiểm tra session_file có hợp lệ và chứa c_user hay không
        storage_state = None
        if session_file and os.path.exists(session_file):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    ck_list = data.get("cookies", [])
                    has_c_user = any(c.get("name") == "c_user" for c in ck_list)
                    if has_c_user:
                        storage_state = session_file
                    else:
                        os.remove(session_file)
            except Exception:
                pass

        context = await browser.new_context(
            storage_state=storage_state,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh"
        )

        # Trích xuất cookies hiện tại của context
        current_cookies = await context.cookies()
        has_c_user = any(c.get("name") == "c_user" for c in current_cookies)

        # Nếu storage_state không có c_user hoặc hết hạn, nạp trực tiếp cookies từ DB
        if cookies and not has_c_user:
            await context.add_cookies(cookies)

        return browser, context

    async def verify_account(self, cookie_str: str, proxy: str = "", headless: bool = True) -> Dict[str, Any]:
        """
        Kiểm tra trạng thái Cookie Facebook và lấy tên người dùng.
        """
        cookies = self.parse_cookie_string(cookie_str)
        uid = self.extract_uid_from_cookie(cookies)
        if not uid:
            return {"success": False, "message": "Cookie không hợp lệ hoặc thiếu c_user!"}

        async with async_playwright() as p:
            browser, context = await self.create_context(p, cookies, proxy, headless=headless, uid=uid)
            page = await context.new_page()
            try:
                # Truy cập thẳng /me để Facebook chuyển hướng về trang cá nhân gốc
                await page.goto("https://www.facebook.com/me", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

                current_url = page.url
                if "login" in current_url or "checkpoint" in current_url:
                    return {"success": False, "message": "Tài khoản bị Checkpoint hoặc Cookie đã hết hạn!"}

                # Ưu tiên lấy tên người dùng cá nhân chính xác từ h1 / title trang cá nhân
                name = f"FB User ({uid})"
                try:
                    h1_elem = await page.query_selector("h1")
                    if h1_elem:
                        h1_text = await h1_elem.inner_text()
                        if h1_text and len(h1_text) < 50 and "Facebook" not in h1_text:
                            name = h1_text.strip()
                    if name.startswith("FB User") or "Facebook" in name:
                        title = await page.title()
                        if title and "Facebook" not in title and "Log in" not in title:
                            name = title.strip()
                except Exception:
                    pass

                i_user = self.extract_i_user_from_cookie(cookies)
                await self.safe_save_storage_state(context, uid)
                return {"success": True, "uid": uid, "i_user": i_user, "name": name, "cookie": cookie_str}
            except Exception as e:
                return {"success": False, "message": f"Lỗi truy cập Facebook: {str(e)}"}
            finally:
                await context.close()
                await browser.close()

    async def open_browser_with_cookie(self, cookie_str: str, proxy: str = "", page_id: str = "", progress_callback: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        """
        Mở trình duyệt trực tiếp (Headful) với Cookie đã nhập để người dùng quan sát/thao tác trên Facebook / Fanpage.
        """
        cookies = self.parse_cookie_string(cookie_str)
        uid = self.extract_uid_from_cookie(cookies)
        if not uid:
            return {"success": False, "message": "Cookie không hợp lệ!"}

        browser = None
        context = None
        try:
            async with async_playwright() as p:
                browser, context = await self.create_context(p, cookies, proxy=proxy, headless=False, uid=uid, page_id=page_id)
                page = await context.new_page()
                target_url = f"https://www.facebook.com/{page_id}" if page_id else "https://www.facebook.com/"
                await page.goto(target_url, wait_until="domcontentloaded")
                if progress_callback:
                    progress_callback("Trình duyệt đã mở thành công! Bạn có thể xem/thao tác trên Facebook.\nĐóng cửa sổ trình duyệt khi hoàn tất.")

                while True:
                    if len(context.pages) == 0:
                        break
                    await asyncio.sleep(1)

                new_cookie_str = ""
                try:
                    await self.safe_save_storage_state(context, uid, page_id=page_id)
                    current_cookies = await context.cookies()
                    cookie_parts = [f"{c['name']}={c['value']}" for c in current_cookies if c.get("domain", "").endswith("facebook.com")]
                    new_cookie_str = "; ".join(cookie_parts)
                except Exception:
                    pass

                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

                return {"success": True, "uid": uid, "cookie": new_cookie_str, "message": "Đã đóng trình duyệt và đồng bộ phiên làm việc."}
        except Exception as e:
            try:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception:
                pass
            return {"success": False, "message": f"Lỗi khi mở trình duyệt: {str(e)}"}

    async def login_via_browser(self, proxy: str = "", progress_callback: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        """
        Mở trình duyệt hiển thị (Headful) để người dùng tự nhập Tài khoản & Mật khẩu Facebook bình thường.
        Hệ thống tự động phát hiện khi đăng nhập thành công và trích xuất Session Cookie.
        """
        browser = None
        context = None
        try:
            async with async_playwright() as p:
                browser, context = await self.create_context(p, cookies=[], proxy=proxy, headless=False)
                page = await context.new_page()
                if progress_callback:
                    progress_callback("Đang mở trình duyệt... Vui lòng tự nhập Tài khoản & Mật khẩu trên Facebook.")

                await page.goto("https://www.facebook.com/login/", wait_until="domcontentloaded")

                start_time = time.time()
                max_wait_sec = 300  # 5 phút tối đa

                while time.time() - start_time < max_wait_sec:
                    if page.is_closed():
                        try:
                            await context.close()
                            await browser.close()
                        except Exception:
                            pass
                        return {"success": False, "message": "Cửa sổ trình duyệt đã bị đóng."}

                    cookies = await context.cookies()
                    uid = self.extract_uid_from_cookie(cookies)
                    current_url = page.url

                    if uid and "login" not in current_url and "checkpoint" not in current_url:
                        if progress_callback:
                            progress_callback(f"Đã phát hiện đăng nhập thành công UID: {uid}! Đang lấy Session...")

                        cookie_parts = []
                        for c in cookies:
                            if c.get("domain", "").endswith("facebook.com"):
                                cookie_parts.append(f"{c['name']}={c['value']}")
                        cookie_str = "; ".join(cookie_parts)

                        name = f"FB User ({uid})"
                        try:
                            title = await page.title()
                            if title and "Facebook" not in title and "Log in" not in title and "Đăng nhập" not in title:
                                name = title
                        except Exception:
                            pass

                        try:
                            session_file = get_session_file_path(uid, "")
                            await context.storage_state(path=session_file)
                        except Exception:
                            pass

                        await asyncio.sleep(2)
                        try:
                            await context.close()
                            await browser.close()
                        except Exception:
                            pass
                        return {"success": True, "uid": uid, "name": name, "cookie": cookie_str}

                    await asyncio.sleep(2)

                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass
                return {"success": False, "message": "Quá thời gian chờ đăng nhập (5 phút)."}

        except Exception as e:
            try:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception:
                pass
            return {"success": False, "message": f"Lỗi trong quá trình đăng nhập: {str(e)}"}


    async def interactive_switch_page(
        self,
        cookie_str: str,
        proxy: str = "",
        page_id: str = "",
        page_name: str = "",
        page_url: str = "",
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Mở trình duyệt hiển thị (Headful) để người dùng tự chọn/chuyển sang Fanpage mong muốn trên Facebook.
        Tự động lưu Session State riêng cho Fanpage đó.
        """
        cookies = self.parse_cookie_string(cookie_str)
        uid = self.extract_uid_from_cookie(cookies)
        if not uid:
            return {"success": False, "message": "Cookie tài khoản không hợp lệ!"}

        async with async_playwright() as p:
            browser, context = await self.create_context(p, cookies, proxy, headless=False, uid=uid, page_id=page_id)
            page = await context.new_page()
            try:
                if progress_callback:
                    progress_callback("Đang mở trình duyệt... Vui lòng tự thực hiện chuyển sang Fanpage trên giao diện Facebook.")

                target_url = "https://www.facebook.com/"
                if page_url and page_url.startswith("http"):
                    target_url = page_url
                elif page_id and page_id.isdigit():
                    target_url = f"https://www.facebook.com/profile.php?id={page_id}"

                await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)

                start_time = time.time()
                max_wait_sec = 300

                try:
                    await page.evaluate("""(pname) => {
                        const div = document.createElement('div');
                        div.id = '__agy_page_switch_notice__';
                        div.style.position = 'fixed';
                        div.style.top = '10px';
                        div.style.left = '50%';
                        div.style.transform = 'translateX(-50%)';
                        div.style.zIndex = '999999';
                        div.style.backgroundColor = '#1565c0';
                        div.style.color = '#ffffff';
                        div.style.padding = '12px 24px';
                        div.style.borderRadius = '8px';
                        div.style.boxShadow = '0 4px 12px rgba(0,0,0,0.3)';
                        div.style.fontFamily = 'sans-serif';
                        div.style.fontSize = '15px';
                        div.style.fontWeight = 'bold';
                        div.style.textAlign = 'center';
                        div.innerText = '👉 VUI LÒNG BẤM "CHUYỂN NGAY" HOẶC CHỌN FANPAGE: ' + (pname || 'Mong muốn') + ' \\nSau khi chuyển xong, ĐÓNG CỬA SỔ TRÌNH DUYỆT này để tự động lưu Session!';
                        document.body.appendChild(div);
                    }""", page_name)
                except Exception:
                    pass

                last_save_time = 0
                while time.time() - start_time < max_wait_sec:
                    if page.is_closed():
                        break

                    if time.time() - last_save_time > 3:
                        await self.safe_save_storage_state(context, uid, page_id=page_id)
                        last_save_time = time.time()

                    await asyncio.sleep(1)

                await self.safe_save_storage_state(context, uid, page_id=page_id)

                # Trích xuất chuỗi Cookie mới để cập nhật CSDL
                new_cookie_str = ""
                try:
                    current_cookies = await context.cookies()
                    cookie_parts = [f"{c['name']}={c['value']}" for c in current_cookies if c.get("domain", "").endswith("facebook.com")]
                    new_cookie_str = "; ".join(cookie_parts)
                except Exception:
                    pass

                return {"success": True, "cookie": new_cookie_str, "message": f"Đã lưu thành công Session cho Fanpage '{page_name or uid}'!"}

            except Exception as e:
                return {"success": False, "message": f"Lỗi khi mở trình duyệt chuyển trang: {str(e)}"}
            finally:
                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass


    async def switch_profile_to_page(self, page: Page, page_name: str, page_id: str = "", page_url: str = "", progress_callback: Optional[Callable[[str], None]] = None, uid: str = "") -> bool:
        """
        Thực hiện chuyển đổi profile tài khoản Facebook từ Nick cá nhân sang Fanpage thực sự.
        Tự động lưu Session State ngay sau khi chuyển thành công (Hỗ trợ hoàn toàn chế độ chạy ngầm Headless).
        """
        try:
            if progress_callback:
                progress_callback(f"Đang tiến hành chuyển profile sang Fanpage '{page_name}'...")

            switched = False

            # 1. Phương pháp 1: Truy cập trang cá nhân của Fanpage & Bấm thẻ span "Chuyển ngay" màu xanh
            target_url = ""
            if page_url and page_url.startswith("http"):
                target_url = page_url
            elif page_id and page_id.isdigit():
                target_url = f"https://www.facebook.com/profile.php?id={page_id}"
            elif page_id:
                target_url = f"https://www.facebook.com/{page_id}"
            elif page_name:
                target_url = "https://www.facebook.com/bookmarks/pages/"

            if target_url:
                if progress_callback:
                    progress_callback(f"Truy cập {target_url} để tìm nút 'Chuyển ngay'...")

                await page.goto(target_url, wait_until="domcontentloaded", timeout=40000)
                await asyncio.sleep(4)

                # Chờ thẻ span chứa chữ "Chuyển ngay" nạp trên giao diện (xem hình ảnh chụp của người dùng)
                span_btn = None
                try:
                    span_btn = await page.wait_for_selector("span:has-text('Chuyển ngay'), div[role='button']:has-text('Chuyển ngay'), span:has-text('Switch Now'), div[role='button']:has-text('Switch Now')", timeout=10000)
                except Exception:
                    pass

                if not span_btn:
                    await asyncio.sleep(2)
                    span_btn = await page.query_selector("span:has-text('Chuyển ngay'), div[role='button']:has-text('Chuyển ngay')")

                if span_btn:
                    if progress_callback:
                        progress_callback(f"ĐÃ TÌM THẤY NÚT 'CHUYỂN NGAY'! Đang bấm nút...")

                    # Bấm trực tiếp vào thẻ span và thẻ cha chứa nó
                    try:
                        await page.evaluate("""(el) => {
                            if (el) {
                                el.click();
                                if (el.parentElement) el.parentElement.click();
                                if (el.parentElement && el.parentElement.parentElement) el.parentElement.parentElement.click();
                            }
                        }""", span_btn)
                        await span_btn.click(force=True)
                    except Exception:
                        pass

                    await asyncio.sleep(5)

                    # Kiểm tra xem có Modal xác nhận chuyển
                    try:
                        confirm_btn = await page.query_selector("div[role='dialog'] div[role='button']:has-text('Chuyển'), div[role='dialog'] button:has-text('Chuyển'), div[role='dialog'] div[role='button']:has-text('Switch')")
                        if confirm_btn:
                            await confirm_btn.click(force=True)
                            await asyncio.sleep(4)
                    except Exception:
                        pass

                    switched = True

            # 2. Phương pháp 2: Thử truy cập URL switch direct của Facebook
            if not switched and page_id:
                try:
                    await page.goto(f"https://www.facebook.com/pages/switch/?page_id={page_id}", wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(3.5)

                    clicked_confirm = await page.evaluate('''() => {
                        const btns = Array.from(document.querySelectorAll("div[role='dialog'] div[role='button'], div[role='dialog'] button"));
                        for (let btn of btns) {
                            const t = (btn.innerText || btn.getAttribute("aria-label") || "").toLowerCase();
                            if (t.includes("chuyển") || t.includes("switch")) {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    }''')
                    if clicked_confirm:
                        await asyncio.sleep(4)
                        switched = True
                except Exception:
                    pass

            # 3. Phương pháp 3: Thao tác Menu Avatar góc phải
            if not switched:
                await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                await page.evaluate('''() => {
                    const avatar = document.querySelector("div[aria-label*='Tài khoản'], div[aria-label*='Account'], div[aria-label*='Trang cá nhân'], img[alt*='Trang cá nhân']");
                    if (avatar) avatar.click();
                }''')
                await asyncio.sleep(2.5)

                await page.evaluate('''() => {
                    const seeAll = Array.from(document.querySelectorAll("div[role='menu'] div, div[role='dialog'] div")).find(el => {
                        const t = (el.innerText || "").toLowerCase();
                        return t.includes("xem tất cả trang cá nhân") || t.includes("see all profiles") || t.includes("chuyển sang trang cá nhân khác");
                    });
                    if (seeAll) seeAll.click();
                }''')
                await asyncio.sleep(2.5)

                if page_name:
                    clicked_page = await page.evaluate(f'''(targetName) => {{
                        const pageItem = Array.from(document.querySelectorAll("div[role='menu'] div, div[role='dialog'] div")).find(el => {{
                            const t = (el.innerText || "").toLowerCase();
                            return t.includes(targetName.toLowerCase());
                        }});
                        if (pageItem) {{
                            pageItem.click();
                            return true;
                        }}
                        return false;
                    }}''', page_name)

                    if clicked_page:
                        if progress_callback:
                            progress_callback(f"Đã chọn Fanpage '{page_name}' từ Menu Avatar! Chờ Facebook chuyển...")
                        await asyncio.sleep(5)
                        switched = True

            # Sau khi chuyển đổi thành công, tự động lưu Session State cho Fanpage
            if switched or page_id:
                try:
                    current_cookies = await page.context.cookies()
                    active_uid = uid or self.extract_uid_from_cookie(current_cookies)
                    if active_uid and page_id:
                        await self.safe_save_storage_state(page.context, active_uid, page_id=page_id)
                except Exception:
                    pass

            if progress_callback:
                progress_callback(f"Đã hoàn tất chuyển danh tính sang Fanpage '{page_name}'!")
            return True

        except Exception as e:
            if progress_callback:
                progress_callback(f"Lưu ý khi chuyển profile: {str(e)}")
            return False

    async def ensure_active_profile(
        self,
        page: Page,
        uid: str,
        target_page_name: str = "",
        target_page_id: str = "",
        target_page_url: str = "",
        logger_callback: Optional[Callable[[str, str], None]] = None
    ) -> bool:
        """
        Tự động đảm bảo danh tính hoạt động đúng (Nick cá nhân hoặc Fanpage) trước khi thực hiện tác vụ:
        - Hoạt động mượt mà 100% trong chế độ chạy ngầm (Headless).
        - Nếu chưa ở đúng Fanpage, tự động điều hướng và chuyển sang Fanpage đó.
        - Tự động lưu Session State sau khi chuyển để các lần sau không cần chuyển lại.
        """
        try:
            cookies = await page.context.cookies()
            curr_i_user = self.extract_i_user_from_cookie(cookies)
            curr_uid = uid or self.extract_uid_from_cookie(cookies)

            # Trường hợp 1: Yêu cầu đăng bài với tư cách Fanpage
            if target_page_name or target_page_id:
                if target_page_id and curr_i_user == target_page_id:
                    if logger_callback:
                        logger_callback("INFO", f"Trình duyệt đã ở sẵn danh tính Fanpage '{target_page_name}'.")
                    return True

                if logger_callback:
                    logger_callback("INFO", f"Tự động chuyển Profile Facebook sang Fanpage '{target_page_name}' (Không cần thao tác tay)...")

                def cb(msg):
                    if logger_callback:
                        logger_callback("INFO", msg)

                switched = await self.switch_profile_to_page(
                    page=page,
                    page_name=target_page_name,
                    page_id=target_page_id,
                    page_url=target_page_url,
                    progress_callback=cb,
                    uid=curr_uid
                )
                return switched

            # Trường hợp 2: Yêu cầu đăng bài với tư cách Nick cá nhân
            else:
                if not curr_i_user or curr_i_user == curr_uid:
                    if logger_callback:
                        logger_callback("INFO", "Trình duyệt đã ở sẵn danh tính Nick cá nhân.")
                    return True

                if logger_callback:
                    logger_callback("INFO", "Đang tự động chuyển danh tính về lại Nick cá nhân...")

                await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2.5)

                await page.evaluate('''() => {
                    const avatar = document.querySelector("div[aria-label*='Tài khoản'], div[aria-label*='Account'], div[aria-label*='Trang cá nhân'], img[alt*='Trang cá nhân']");
                    if (avatar) avatar.click();
                }''')
                await asyncio.sleep(2)

                await page.evaluate('''() => {
                    const seeAll = Array.from(document.querySelectorAll("div[role='menu'] div, div[role='dialog'] div")).find(el => {
                        const t = (el.innerText || "").toLowerCase();
                        return t.includes("xem tất cả trang cá nhân") || t.includes("see all profiles") || t.includes("chuyển sang trang cá nhân khác");
                    });
                    if (seeAll) seeAll.click();
                }''')
                await asyncio.sleep(2)

                await page.evaluate(f'''(u) => {{
                    const items = Array.from(document.querySelectorAll("div[role='menu'] div[role='button'], div[role='dialog'] div[role='button']"));
                    if (items.length > 0) items[0].click();
                }}''', curr_uid)
                await asyncio.sleep(4)

                if curr_uid:
                    await self.safe_save_storage_state(page.context, curr_uid, page_id="")
                return True

        except Exception as e:
            if logger_callback:
                logger_callback("WARNING", f"Lỗi khi kiểm tra/chuyển danh tính tự động: {e}")
            return False

    async def scan_groups(self, cookie_str: str, proxy: str = "", page_id: str = "", page_name: str = "", page_url: str = "", headless: bool = True, progress_callback: Optional[Callable[[str], None]] = None) -> List[Dict[str, Any]]:
        """
        Quét tất cả các nhóm mà tài khoản (hoặc Fanpage) đã tham gia (`facebook.com/groups/joins/`).
        """
        cookies = self.parse_cookie_string(cookie_str)
        uid = self.extract_uid_from_cookie(cookies)
        groups = []

        if progress_callback:
            target_desc = f"Fanpage '{page_name}'" if page_name else "Nick cá nhân"
            progress_callback(f"Đang mở trình duyệt để quét nhóm cho {target_desc}...")

        async with async_playwright() as p:
            browser, context = await self.create_context(p, cookies, proxy, headless=headless, uid=uid, page_id=page_id)
            page = await context.new_page()
            try:
                # Nếu chưa có session file riêng cho Fanpage thì mới tiến hành chuyển profile
                session_page_file = get_session_file_path(uid, page_id) if (uid and page_id) else None
                if not (session_page_file and os.path.exists(session_page_file)):
                    if (page_id and page_id.strip()) or (page_name and page_name.strip()) or (page_url and page_url.strip()):
                        await self.switch_profile_to_page(page, page_name=page_name, page_id=page_id, page_url=page_url, progress_callback=progress_callback)

                if progress_callback:
                    progress_callback("Truy cập facebook.com/groups/joins/ (Chế độ quét siêu nhanh)...")

                await page.goto("https://www.facebook.com/groups/joins/", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2.5)

                # Thu thập nhóm trực tiếp trong lúc cuộn trang nhanh
                seen_ids = set()
                scroll_count = 0
                max_scrolls = 60
                same_count = 0
                last_height = 0

                while scroll_count < max_scrolls:
                    scroll_count += 1
                    
                    # Trích xuất toàn bộ link nhóm đang có trong DOM kèm tiêu đề chuẩn tiếng Việt
                    extracted = await page.evaluate('''() => {
                        const items = [];
                        const links = Array.from(document.querySelectorAll("a[href*='/groups/']"));
                        for (let link of links) {
                            const href = link.getAttribute("href") || "";
                            const match = href.match(/facebook\.com\/groups\/([^/?]+)/) || href.match(/\/groups\/([^/?]+)/);
                            if (!match) continue;
                            const g_id = match[1];
                            if (["joins", "feed", "discover", "create", "category", "search", "user"].includes(g_id)) continue;

                            let container = link.closest("div[role='listitem'], div[role='article']") || link.parentElement;
                            let title = "";

                            if (container) {
                                const elements = Array.from(container.querySelectorAll("span, h2, h3, a"));
                                for (let el of elements) {
                                    const txt = (el.innerText || "").trim();
                                    const txtLower = txt.toLowerCase();
                                    if (!txt || txt.length < 2) continue;
                                    if (txtLower.includes("hoạt động") || txtLower.includes("thành viên") || txtLower.includes("bài viết") || txtLower.includes("tham gia") || txtLower.includes("đã tham gia") || txtLower.includes("nhóm công khai") || txtLower.includes("nhóm riêng tư")) continue;
                                    if (txt === g_id || txtLower === "nhóm " + g_id) continue;
                                    title = txt.split('\\n')[0].trim();
                                    if (title && title !== g_id) break;
                                }
                            }

                            if (!title) {
                                const rawText = (link.innerText || "").trim();
                                const lines = rawText.split('\\n').map(l => l.trim()).filter(l => l);
                                for (let l of lines) {
                                    const lLower = l.toLowerCase();
                                    if (!lLower.includes("hoạt động") && !lLower.includes("thành viên") && !lLower.includes("tham gia") && !lLower.includes("đã tham gia")) {
                                        title = l;
                                        break;
                                    }
                                }
                            }

                            if (!title || title.toLowerCase() === g_id.toLowerCase()) {
                                title = (link.getAttribute("aria-label") || link.getAttribute("title") || "").trim();
                            }

                            if (!title || title.toLowerCase() === g_id.toLowerCase()) {
                                title = "Nhóm " + g_id;
                            }

                            items.push({ group_id: g_id, group_name: title });
                        }
                        return items;
                    }''')

                    for item in extracted:
                        g_id = item["group_id"]
                        if g_id not in seen_ids:
                            seen_ids.add(g_id)
                            groups.append({
                                "account_uid": uid,
                                "group_id": g_id,
                                "group_name": item["group_name"],
                                "group_url": f"https://www.facebook.com/groups/{g_id}/",
                                "member_count": "",
                                "privacy": "PUBLIC"
                            })

                    if progress_callback:
                        progress_callback(f"Đang cuộn quét nhóm nhanh ({scroll_count}/{max_scrolls}) - Đã tìm thấy {len(groups)} nhóm...")

                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(0.9)

                    new_height = await page.evaluate("document.body.scrollHeight")
                    if new_height == last_height:
                        same_count += 1
                        if same_count >= 3:
                            break
                    else:
                        same_count = 0
                    last_height = new_height

                if progress_callback:
                    progress_callback(f"Hoàn tất! Đã quét tổng cộng {len(groups)} nhóm!")

            except Exception as e:
                if progress_callback:
                    progress_callback(f"Lỗi khi quét nhóm: {str(e)}")
            finally:
                try:
                    await self.safe_save_storage_state(context, uid, page_id=page_id)
                except Exception:
                    pass
                await context.close()
                await browser.close()

        return groups

    async def interactive_join_groups_by_category(
        self,
        cookie_str: str,
        proxy: str = "",
        page_id: str = "",
        page_name: str = "",
        page_url: str = "",
        category_name: str = "Mặc định",
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Mở trình duyệt hiển thị (Headful) cho phép người dùng tự tìm & bấm Tham gia các nhóm mới trên Facebook.
        Tự động quét các nhóm mới vừa tham gia và gán Lĩnh vực category_name.
        """
        cookies = self.parse_cookie_string(cookie_str)
        uid = self.extract_uid_from_cookie(cookies)
        if not uid:
            return {"success": False, "message": "Cookie tài khoản không hợp lệ!"}

        if progress_callback:
            progress_callback(f"Đang chuẩn bị mở trình duyệt để tham gia nhóm cho Lĩnh Vực '{category_name}'...")

        # 1. Quét danh sách nhóm hiện tại trước khi mở trình duyệt
        existing_groups = await self.scan_groups(cookie_str, proxy, page_id=page_id, page_name=page_name, page_url=page_url, headless=True)
        existing_gids = {g["group_id"] for g in existing_groups}

        async with async_playwright() as p:
            browser, context = await self.create_context(p, cookies, proxy, headless=False, uid=uid, page_id=page_id)
            page = await context.new_page()
            try:
                # Đi tới trang Khám Phá Nhóm của Facebook
                target_url = "https://www.facebook.com/groups/discover/"
                await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)

                # Chèn Banner hướng dẫn trên màn hình
                try:
                    await page.evaluate("""(catName) => {
                        const div = document.createElement('div');
                        div.id = '__agy_join_category_notice__';
                        div.style.position = 'fixed';
                        div.style.top = '10px';
                        div.style.left = '50%';
                        div.style.transform = 'translateX(-50%)';
                        div.style.zIndex = '999999';
                        div.style.backgroundColor = '#7b1fa2';
                        div.style.color = '#ffffff';
                        div.style.padding = '14px 28px';
                        div.style.borderRadius = '10px';
                        div.style.boxShadow = '0 6px 16px rgba(0,0,0,0.4)';
                        div.style.fontFamily = 'sans-serif';
                        div.style.fontSize = '15px';
                        div.style.fontWeight = 'bold';
                        div.style.textAlign = 'center';
                        div.innerText = '👉 BẠN ĐANG TRONG CHẾ ĐỘ THAM GIA NHÓM CHO LĨNH VỰC: ' + (catName || 'Mặc định').toUpperCase() + ' \\n' +
                                        'Hãy tự do tìm kiếm & bấm THAM GIA các nhóm trên Facebook. \\n' +
                                        'Khi hoàn tất, hãy ĐÓNG CỬA SỔ TRÌNH DUYỆT này để phần mềm tự động thêm nhóm mới vào Lĩnh Vực này!';
                        document.body.appendChild(div);
                    }""", category_name)
                except Exception:
                    pass

                start_time = time.time()
                max_wait_sec = 600  # Chờ tối đa 10 phút

                while time.time() - start_time < max_wait_sec:
                    if page.is_closed():
                        break
                    await asyncio.sleep(1)

            except Exception:
                pass
            finally:
                try:
                    await self.safe_save_storage_state(context, uid, page_id=page_id)
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

        # 2. Quét lại danh sách nhóm sau khi đóng trình duyệt
        if progress_callback:
            progress_callback(f"Đang quét lại danh sách nhóm để tự động thêm các nhóm mới vừa tham gia vào Lĩnh Vực '{category_name}'...")

        updated_groups = await self.scan_groups(cookie_str, proxy, page_id=page_id, page_name=page_name, page_url=page_url, headless=True)
        
        new_groups_count = 0
        for g in updated_groups:
            # Nếu là nhóm mới tham gia trong phiên này
            if g["group_id"] not in existing_gids:
                g["category"] = category_name
                new_groups_count += 1

        return {
            "success": True,
            "groups": updated_groups,
            "new_count": new_groups_count,
            "category": category_name,
            "message": f"Đã hoàn tất! Đã lưu {len(updated_groups)} nhóm, trong đó có {new_groups_count} nhóm mới được tự động gán vào Lĩnh Vực '{category_name}'!"
        }

    async def scan_pages(self, cookie_str: str, proxy: str = "", headless: bool = True, progress_callback: Optional[Callable[[str], None]] = None) -> List[Dict[str, Any]]:
        """
        Quét danh sách các Fanpage do tài khoản sở hữu/quản lý.
        """
        cookies = self.parse_cookie_string(cookie_str)
        uid = self.extract_uid_from_cookie(cookies)
        pages_list = []

        if progress_callback:
            progress_callback("Đang mở trình duyệt để quét danh sách Fanpage...")

        async with async_playwright() as p:
            browser, context = await self.create_context(p, cookies, proxy, headless=headless, uid=uid)
            page = await context.new_page()
            try:
                # 1. Thử truy cập trang Quản Lý Fanpage chuẩn của Facebook mới
                if progress_callback:
                    progress_callback("Truy cập https://www.facebook.com/pages/?category=your_pages...")

                await page.goto("https://www.facebook.com/pages/?category=your_pages", wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(4)

                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)

                # Trích xuất danh sách trang từ DOM
                extracted = await page.evaluate('''() => {
                    const results = [];
                    const seen = new Set();
                    const blacklist = new Set([
                        "quảng cáo", "quang cao", "tạo bài viết", "tao bai viet", "tin nhắn", "tin nhan",
                        "hộp thư", "hop thu", "thông tin chi tiết", "thong tin chi tiet", "khám phá", "kham pha",
                        "xem tất cả", "xem tat ca", "meta business suite", "followed pages",
                        "lời mời", "loi moi", "tạo trang", "tao trang", "chuyển ngay", "switch now",
                        "bài viết", "bai viet", "thông báo", "thong bao", "quản lý trang", "quan ly trang",
                        "trang", "pages", "cài đặt", "chưa đọc", "bình luận", "gợi ý", "quản lý",
                        "xem thêm", "đăng nhập", "chuyển", "switch", "all", "ad", "inbox", "insights",
                        "home", "notifications"
                    ]);

                    // Chỉ quét trong vùng nội dung chính div[role='main'] (loại bỏ hoàn toàn sidebar menu trái)
                    const main = document.querySelector("div[role='main']") || document.body;
                    const links = Array.from(main.querySelectorAll("a[href]"));

                    for (let a of links) {
                        const href = a.getAttribute("href") || "";
                        if (!href || href === "#" || href.includes("javascript:")) continue;

                        // Bỏ qua liên kết rác, quảng cáo, tin nhắn, thông báo, v.v.
                        if (href.includes("business.facebook.com") ||
                            href.includes("/ad_center/") || href.includes("/ads/") || href.includes("/ad/") ||
                            href.includes("/latest/") || href.includes("/inbox") || href.includes("/messages/") ||
                            href.includes("/notifications") || href.includes("notif_id=") || href.includes("notif_t=") ||
                            href.includes("/groups/") || href.includes("/marketplace/") || href.includes("/watch/") ||
                            href.includes("/gaming/") || href.includes("/events/") || href.includes("/bookmarks") ||
                            href.includes("/settings") || href.includes("/privacy") || href.includes("/help") ||
                            href.includes("/login") || href.includes("/home.php") || href.includes("/recover/") ||
                            href.includes("/reel/") || href.includes("category=your_pages") || href.includes("category=top") ||
                            href.includes("category=")) {
                            continue;
                        }

                        let rawText = (a.innerText || "").trim();
                        if (!rawText) continue;

                        let name = rawText.split('\\n')[0].trim();
                        let nameLower = name.toLowerCase();

                        // Loại trừ các tên thuộc blacklist hoặc chứa từ khóa rác
                        if (blacklist.has(nameLower) ||
                            nameLower.includes("thông báo") ||
                            nameLower.includes("chưa đọc") ||
                            nameLower.includes("bình luận") ||
                            nameLower.includes("gợi ý") ||
                            name.length < 2) {
                            continue;
                        }

                        let cleanHref = href.split('?')[0].split('#')[0];
                        let p_id = "";

                        if (href.includes("profile.php?id=")) {
                            const m = href.match(/profile\.php\?id=(\d+)/);
                            if (m) p_id = m[1];
                        } else {
                            const parts = cleanHref.replace(/\\/$/, "").split('/');
                            const candidate = parts[parts.length - 1];
                            if (candidate && candidate.length > 1 && !blacklist.has(candidate.toLowerCase())) {
                                p_id = candidate;
                            }
                        }

                        if (!p_id || seen.has(p_id) || blacklist.has(p_id.toLowerCase())) continue;

                        seen.add(p_id);
                        let fullUrl = href.startsWith("http") ? href : ("https://www.facebook.com" + href);
                        results.push({
                            page_id: p_id,
                            page_name: name,
                            page_url: fullUrl
                        });
                    }
                    return results;
                }''')

                for item in extracted:
                    pages_list.append({
                        "account_uid": uid,
                        "page_id": item["page_id"],
                        "page_name": item["page_name"],
                        "page_url": item["page_url"]
                    })

                # 2. Nếu URL 1 chưa tìm thấy trang nào, thử qua bookmark cũ facebook.com/bookmarks/pages/
                if not pages_list:
                    if progress_callback:
                        progress_callback("Thử qua https://www.facebook.com/bookmarks/pages/...")
                    await page.goto("https://www.facebook.com/bookmarks/pages/", wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(4)

                    links = await page.query_selector_all("a[href*='/pages/'], a[href*='facebook.com/']")
                    seen_ids = set()

                    blacklist_words = {
                        "quảng cáo", "tin nhắn", "hộp thư", "thông tin chi tiết", "khám phá", "xem tất cả",
                        "meta business suite", "followed pages", "lời mời", "tạo trang", "chuyển ngay", "switch now",
                        "bài viết", "thông báo", "trang", "pages", "cài đặt"
                    }

                    for link in links:
                        try:
                            href = await link.get_attribute("href")
                            if not href or any(k in href for k in ["bookmarks", "create", "groups", "ad_center", "business.facebook.com", "/latest/", "/inbox"]):
                                continue

                            text = await link.inner_text()
                            text = text.strip().split('\n')[0] if text else ""

                            if text and len(text) > 1 and text.lower() not in blacklist_words and not any(w in text.lower() for w in ["thông báo", "chưa đọc"]):
                                p_id = ""
                                if "profile.php?id=" in href:
                                    m = re.search(r'profile\.php\?id=(\d+)', href)
                                    if m: p_id = m.group(1)
                                else:
                                    p_id = href.rstrip('/').split('?')[0].split('/')[-1]

                                if p_id and p_id not in seen_ids and p_id.lower() not in blacklist_words:
                                    seen_ids.add(p_id)
                                    pages_list.append({
                                        "account_uid": uid,
                                        "page_id": p_id,
                                        "page_name": text,
                                        "page_url": href if href.startswith("http") else f"https://www.facebook.com{href}"
                                    })
                        except Exception:
                            continue

                if progress_callback:
                    progress_callback(f"Đã quét thành công {len(pages_list)} Fanpage!")

            except Exception as e:
                if progress_callback:
                    progress_callback(f"Lỗi khi quét Fanpage: {str(e)}")
            finally:
                await context.close()
                await browser.close()

        return pages_list

    async def post_to_group(
        self,
        page: Page,
        group_url: str,
        content_template: str,
        media_paths: List[str],
        anti_spam: AntiSpamManager,
        logger_callback: Optional[Callable[[str, str], None]] = None,
        post_as_page_name: Optional[str] = None,
        cookie_str: Optional[str] = None
    ) -> bool:
        """
        Thực hiện đăng 1 bài viết lên 1 nhóm Facebook cụ thể (có hỗ trợ chọn Fanpage và tự động khôi phục session).
        """
        try:
            if logger_callback:
                logger_callback("INFO", f"Đang điều hướng đến nhóm: {group_url}")

            await page.goto(group_url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(3.5)

            # Kiểm tra tự động khôi phục nếu Facebook hiển thị bảng yêu cầu Đăng Nhập ("Xem thêm trên Facebook")
            login_selectors = [
                "div[role='dialog']:has-text('Xem thêm trên Facebook')",
                "div[role='dialog']:has-text('Log In')",
                "div[role='dialog']:has-text('Đăng nhập')",
                "form#login_form",
                "input[name='email']"
            ]
            
            needs_recovery = False
            for sel in login_selectors:
                try:
                    elem = await page.query_selector(sel)
                    if elem and await elem.is_visible():
                        needs_recovery = True
                        break
                except Exception:
                    continue

            if needs_recovery:
                if logger_callback:
                    logger_callback("WARNING", "Phát hiện màn hình yêu cầu Đăng Nhập! Đang tự động nạp Cookie khôi phục phiên làm việc...")

                if cookie_str:
                    raw_cookies = self.parse_cookie_string(cookie_str)
                    if raw_cookies:
                        await page.context.add_cookies(raw_cookies)
                        await asyncio.sleep(1)
                        await page.goto(group_url, wait_until="domcontentloaded", timeout=40000)
                        await asyncio.sleep(3.5)

            # Xử lý spintax và anti-spam cho văn bản
            final_text = SpintaxParser.parse(content_template)
            final_text = anti_spam.prepare_text(final_text)
            final_media = anti_spam.prepare_media(media_paths)

            # Tìm nút tạo bài viết ("Bạn viết gì đi...", "Bạn đang nghĩ gì?", "Write something...", v.v.)
            composer_selectors = [
                "div[role='button']:has-text('Bạn viết gì đi')",
                "span:has-text('Bạn viết gì đi')",
                "div[role='button']:has-text('Bạn đang nghĩ gì')",
                "span:has-text('Bạn đang nghĩ gì')",
                "div[role='button']:has-text('Write something')",
                "span:has-text('Write something')",
                "div[role='button']:has-text('Tạo bài viết')",
                "span:has-text('Tạo bài viết')"
            ]

            composer_btn = None
            for sel in composer_selectors:
                try:
                    composer_btn = await page.query_selector(sel)
                    if composer_btn:
                        break
                except Exception:
                    continue

            # Nếu chưa tìm thấy nút tạo bài viết và có tên Fanpage, thử chuyển tương tác switcher
            if not composer_btn and post_as_page_name and post_as_page_name.strip():
                if logger_callback:
                    logger_callback("INFO", f"Đang kiểm tra nút chuyển tương tác Fanpage: '{post_as_page_name}'...")

                switcher_selectors = [
                    "div[aria-label*='Tương tác với tư cách']",
                    "div[aria-label*='Interact as']",
                    "div[aria-label*='Chuyển sang trang']",
                    "div[aria-label*='Switch profile']"
                ]

                switcher_btn = None
                for sel in switcher_selectors:
                    try:
                        switcher_btn = await page.query_selector(sel)
                        if switcher_btn:
                            break
                    except Exception:
                        continue

                if switcher_btn:
                    await switcher_btn.click()
                    await asyncio.sleep(2)

                    page_opt = await page.query_selector(f"div[role='dialog'] div:has-text('{post_as_page_name}')")
                    if not page_opt:
                        page_opt = await page.query_selector(f"div[role='menu'] div:has-text('{post_as_page_name}')")

                    if page_opt:
                        await page_opt.click()
                        if logger_callback:
                            logger_callback("INFO", f"Đã chọn tương tác với tư cách Fanpage '{post_as_page_name}'.")
                        await asyncio.sleep(3)

                # Thử lại tìm nút tạo bài viết sau khi switcher
                for sel in composer_selectors:
                    try:
                        composer_btn = await page.wait_for_selector(sel, timeout=4000)
                        if composer_btn:
                            break
                    except Exception:
                        continue

            if not composer_btn:
                # Thử query selector chung cho bất kỳ button tạo bài viết
                composer_btn = await page.query_selector("div[role='button'][aria-label*='Tạo bài viết'], div[role='button'][aria-label*='Create post']")

            if not composer_btn:
                # Kiểm tra xem có nút "Tham gia nhóm" (Fanpage/Nick chưa tham gia nhóm này)
                join_selectors = [
                    "div[role='button']:has-text('Tham gia nhóm')",
                    "span:has-text('Tham gia nhóm')",
                    "div[role='button']:has-text('Join group')",
                    "span:has-text('Join group')",
                    "div[aria-label*='Tham gia nhóm']",
                    "div[aria-label*='Join group']"
                ]
                join_btn = None
                for sel in join_selectors:
                    try:
                        join_btn = await page.query_selector(sel)
                        if join_btn and await join_btn.is_visible():
                            break
                    except Exception:
                        continue

                if join_btn:
                    if logger_callback:
                        logger_callback("INFO", f"Tài khoản/Fanpage chưa tham gia nhóm này. Đang tự động bấm 'Tham gia nhóm'...")
                    try:
                        await join_btn.click(force=True)
                        await asyncio.sleep(2.5)

                        # Nếu xuất hiện Dialog chọn Profile/Fanpage tham gia
                        if post_as_page_name and post_as_page_name.strip():
                            page_opt = await page.query_selector(f"div[role='dialog'] div:has-text('{post_as_page_name}')")
                            if page_opt:
                                await page_opt.click()
                                await asyncio.sleep(1.5)

                        confirm_join = await page.query_selector("div[role='dialog'] div[role='button']:has-text('Tham gia'), div[role='dialog'] div[role='button']:has-text('Join')")
                        if confirm_join:
                            await confirm_join.click(force=True)
                            await asyncio.sleep(3)
                    except Exception:
                        pass

                    # Thử lại tìm nút tạo bài viết sau khi bấm tham gia
                    for sel in composer_selectors:
                        try:
                            composer_btn = await page.query_selector(sel)
                            if composer_btn:
                                break
                        except Exception:
                            continue

            if not composer_btn:
                if logger_callback:
                    logger_callback("WARNING", "Không tìm thấy nút tạo bài viết (Có thể nhóm bắt duyệt tham gia hoặc cấm đăng bài).")
                return False

            # Bấm mở Modal tạo bài viết (click cả element và parent div[role='button'] để đảm bảo nạp Modal)
            try:
                await composer_btn.click()
            except Exception:
                pass

            await page.evaluate("""(el) => {
                if (el) {
                    el.click();
                    let parent = el.closest("div[role='button']") || el.parentElement;
                    if (parent) parent.click();
                }
            }""", composer_btn)

            await asyncio.sleep(3)

            # Tìm ô nhập văn bản trong Modal (div[role='dialog'])
            editor_selectors = [
                "div[role='dialog'] div[contenteditable='true']",
                "div[role='dialog'] p[data-lexical-text='true']",
                "div[role='dialog'] div[role='textbox']",
                "div[role='dialog'] div[aria-label*='Bạn viết gì đi']",
                "div[role='dialog'] div[aria-label*='Bạn đang nghĩ gì']",
                "div[role='dialog'] div[aria-label*='Write something']",
                "div[role='dialog'] div[aria-label*='Tạo bài viết']",
                "div[contenteditable='true']"
            ]

            editor_elem = None
            for sel in editor_selectors:
                try:
                    editor_elem = await page.wait_for_selector(sel, timeout=4000)
                    if editor_elem:
                        break
                except Exception:
                    continue

            if not editor_elem:
                if logger_callback:
                    logger_callback("ERROR", "Không thể mở khung soạn thảo bài viết!")
                return False

            # Focus và nhấp vào ô nhập văn bản
            try:
                await editor_elem.click(force=True)
                await editor_elem.focus()
            except Exception:
                pass
            await asyncio.sleep(1)

            # Mô phỏng gõ văn bản hoặc chèn trực tiếp văn bản Spintax
            try:
                await page.keyboard.insert_text(final_text)
            except Exception:
                for char in final_text:
                    await page.keyboard.write(char)
                    await asyncio.sleep(anti_spam.get_typing_delay())

            await asyncio.sleep(2)

            # Upload Ảnh / Video nếu có
            if final_media:
                valid_files = [f for f in final_media if os.path.exists(f)]
                if valid_files:
                    if logger_callback:
                        logger_callback("INFO", f"Đang tự động đính kèm {len(valid_files)} tệp phương tiện...")
                    
                    media_attached = False

                    # Cách 1: Tự động dán ảnh (Paste Event Clipboard) trực tiếp vào khung soạn thảo
                    for media_path in valid_files:
                        ext = os.path.splitext(media_path)[1].lower()
                        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']:
                            try:
                                mime, _ = mimetypes.guess_type(media_path)
                                mime = mime or "image/png"
                                with open(media_path, "rb") as mf:
                                    b64_data = base64.b64encode(mf.read()).decode('utf-8')
                                
                                await page.evaluate("""({b64, mime, filename}) => {
                                    const byteCharacters = atob(b64);
                                    const byteNumbers = new Array(byteCharacters.length);
                                    for (let i = 0; i < byteCharacters.length; i++) {
                                        byteNumbers[i] = byteCharacters.charCodeAt(i);
                                    }
                                    const byteArray = new Uint8Array(byteNumbers);
                                    const file = new File([byteArray], filename, { type: mime });

                                    const dt = new DataTransfer();
                                    dt.items.add(file);

                                    const target = document.querySelector("div[role='dialog'] div[contenteditable='true']") || document.querySelector("div[contenteditable='true']");
                                    if (target) {
                                        target.focus();
                                        const pasteEvent = new ClipboardEvent('paste', {
                                            bubbles: true,
                                            cancelable: true,
                                            clipboardData: dt
                                        });
                                        target.dispatchEvent(pasteEvent);
                                    }
                                }""", {"b64": b64_data, "mime": mime, "filename": os.path.basename(media_path)})
                                media_attached = True
                                await asyncio.sleep(2.5)
                            except Exception as pe:
                                if logger_callback:
                                    logger_callback("WARNING", f"Thử dán ảnh trực tiếp: {str(pe)}")

                    # Cách 2: Nếu chưa đính kèm xong, nạp tệp media qua File Input / File Chooser
                    if not media_attached:
                        try:
                            file_input = await page.query_selector("div[role='dialog'] input[type='file'], input[type='file']")
                            if file_input:
                                await file_input.set_input_files(valid_files)
                                media_attached = True
                                await asyncio.sleep(4)
                            else:
                                photo_btn = await page.query_selector(
                                    "div[role='dialog'] div[aria-label*='Ảnh/video'], "
                                    "div[role='dialog'] div[aria-label*='Photo/video'], "
                                    "div[role='dialog'] div[aria-label*='Ảnh']"
                                )
                                if photo_btn:
                                    try:
                                        async with page.expect_file_chooser(timeout=3000) as fc_info:
                                            await photo_btn.click(timeout=3000)
                                        file_chooser = await fc_info.value
                                        await file_chooser.set_files(valid_files)
                                        media_attached = True
                                        await asyncio.sleep(4)
                                    except Exception:
                                        pass
                        except Exception as me:
                            if logger_callback:
                                logger_callback("WARNING", f"Lỗi khi đính kèm tệp media: {str(me)}")

                    if media_attached and logger_callback:
                        logger_callback("INFO", f"Đã hoàn tất đính kèm {len(valid_files)} tệp media vào bài đăng.")

            # Nhấn nút "Đăng" / "Post"
            post_btn_selectors = [
                "div[role='dialog'] div[aria-label='Đăng']",
                "div[role='dialog'] div[role='button']:has-text('Đăng')",
                "div[role='dialog'] div[aria-label='Post']",
                "div[role='dialog'] div[role='button']:has-text('Post')"
            ]

            post_btn = None
            for sel in post_btn_selectors:
                try:
                    post_btn = await page.wait_for_selector(sel, timeout=4000)
                    if post_btn:
                        break
                except Exception:
                    continue

            if not post_btn:
                # Thử tìm selector button Đăng màu xanh cuối Modal
                post_btn = await page.query_selector("div[role='dialog'] div[role='button'][tabindex='0']")

            if not post_btn:
                if logger_callback:
                    logger_callback("ERROR", "Không tìm thấy nút 'Đăng' bài viết!")
                return False

            try:
                await post_btn.click(force=True)
            except Exception:
                pass

            await page.evaluate("""(el) => {
                if (el) {
                    el.click();
                    if (el.parentElement) el.parentElement.click();
                }
            }""", post_btn)

            if logger_callback:
                logger_callback("INFO", "Đã nhấn nút Đăng. Đang chờ Facebook xử lý...")

            await asyncio.sleep(6)
            anti_spam.record_post()
            return True

        except Exception as e:
            if logger_callback:
                logger_callback("ERROR", f"Lỗi ngoại lệ khi đăng bài: {str(e)}")
            return False
