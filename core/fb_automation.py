import asyncio
import json
import re
import os
import time
import random
import base64
import mimetypes
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
                browser = await asyncio.wait_for(playwright.chromium.launch(**launch_kwargs), timeout=8)
            except Exception as e:
                print(f"[WARNING] Không thể mở trình duyệt từ executable_path ({executable_path}): {e}")
                browser = None

        # Chiến lược 2: Microsoft Edge hệ thống (sẵn có 100% trên Windows 10/11)
        if browser is None:
            try:
                browser = await asyncio.wait_for(
                    playwright.chromium.launch(channel="msedge", headless=headless, args=launch_args, proxy=proxy_config),
                    timeout=8
                )
            except Exception as e:
                print(f"[WARNING] Trình duyệt Edge không khả dụng: {e}")
                browser = None

        # Chiến lược 3: Google Chrome hệ thống
        if browser is None:
            try:
                browser = await asyncio.wait_for(
                    playwright.chromium.launch(channel="chrome", headless=headless, args=launch_args, proxy=proxy_config),
                    timeout=8
                )
            except Exception as e:
                print(f"[WARNING] Google Chrome không khả dụng: {e}")
                browser = None

        # Chiến lược 4: Playwright Chromium mặc định
        if browser is None:
            try:
                clean_kwargs = {"headless": headless, "args": launch_args, "proxy": proxy_config}
                browser = await asyncio.wait_for(playwright.chromium.launch(**clean_kwargs), timeout=8)
            except Exception as e:
                print(f"[WARNING] Playwright Chromium mặc định không khả dụng: {e}")
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
                        browser = await asyncio.wait_for(
                            playwright.chromium.launch(
                                executable_path=p_path,
                                headless=headless,
                                args=launch_args,
                                proxy=proxy_config
                            ),
                            timeout=8
                        )
                        if browser:
                            break
                    except Exception:
                        pass

        if browser is None:
            raise RuntimeError("Không thể khởi chạy trình duyệt (Chromium, Edge hoặc Chrome). Vui lòng đảm bảo máy tính đã cài Microsoft Edge hoặc Google Chrome.")

        session_file = None
        if uid and page_id:
            p_file = get_session_file_path(uid, page_id)
            if os.path.exists(p_file):
                session_file = p_file

        if not session_file and uid:
            u_file = get_session_file_path(uid, "")
            # Nếu chạy Nick cá nhân (page_id == ""), ưu tiên đồng bộ cookie xác thực mới nhất (c_user, xs, fr, datr, sb)
            # từ các file session Fanpage cùng UID (nếu mới hơn) nhưng bỏ i_user để không bị văng ra màn hình 'Tiếp tục'
            try:
                from core.database import get_app_data_dir
                session_dir = os.path.join(get_app_data_dir(), "sessions")
                if os.path.exists(session_dir):
                    prefix = f"{uid}_"
                    cand_files = [
                        os.path.join(session_dir, fn)
                        for fn in os.listdir(session_dir)
                        if fn.startswith(prefix) and fn.endswith("_state.json")
                    ]
                    if cand_files:
                        newest_f = max(cand_files, key=lambda x: os.path.getmtime(x))
                        u_mtime = os.path.getmtime(u_file) if os.path.exists(u_file) else 0
                        if not page_id and os.path.abspath(newest_f) != os.path.abspath(u_file) and os.path.getmtime(newest_f) > u_mtime:
                            with open(newest_f, "r", encoding="utf-8") as nf:
                                ndata = json.load(nf)
                            n_cookies = [c for c in ndata.get("cookies", []) if c.get("name") != "i_user"]
                            if any(c.get("name") == "c_user" for c in n_cookies):
                                with open(u_file, "w", encoding="utf-8") as uf:
                                    json.dump({"cookies": n_cookies, "origins": ndata.get("origins", [])}, uf)
            except Exception:
                pass
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
            viewport={"width": 1280, "height": 820},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh"
        )

        # Stealth chống phát hiện tự động hóa (Anti-Checkpoint / Anti-Human Verification)
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            if (!window.chrome) { window.chrome = { runtime: {} }; }
            Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
        """)

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
                session_page_file = get_session_file_path(curr_uid, target_page_id) if (curr_uid and target_page_id) else None
                has_saved_page_session = bool(
                    session_page_file and os.path.exists(session_page_file) and curr_i_user and curr_i_user != curr_uid
                )
                if (target_page_id and curr_i_user == target_page_id) or has_saved_page_session:
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

    @staticmethod
    def parse_like_count(text: str) -> int:
        """
        Chuyển đổi chuỗi hiển thị số lượt thích trên Facebook (VD: '315', '1,2K', '1.2K', '2,5N', '15 N', '1,2 Tr', '1.234')
        thành số nguyên chính xác để so sánh với mức Like tối thiểu.
        """
        if not text:
            return 0
        s = str(text).strip().upper()
        for w in ["LƯỢT THÍCH", "LIKES", "LIKE", "THÍCH", "BỎ THÍCH", "UNLIKE", "TẤT CẢ CẢM XÚC", "CẢM XÚC"]:
            s = s.replace(w, "")
        s = s.strip()
        if not s:
            return 0

        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(K|N|M|TR|TRIỆU|B)?", s, re.IGNORECASE)
        if not m:
            return 0
        num_str = m.group(1)
        unit = (m.group(2) or "").upper()

        if unit in ("K", "N"):
            val = float(num_str.replace(",", "."))
            return int(val * 1000)
        if unit in ("M", "TR", "TRIỆU"):
            val = float(num_str.replace(",", "."))
            return int(val * 1000000)
        if unit == "B":
            val = float(num_str.replace(",", "."))
            return int(val * 1000000000)

        # Trường hợp không có hậu tố K/N/M: nếu sau dấu chấm/phẩy có đúng 3 chữ số (VD: 1.250 hoặc 1,250) -> hàng nghìn
        if re.match(r"^\d{1,3}([.,]\d{3})+$", num_str):
            return int(re.sub(r"[.,]", "", num_str))

        try:
            return int(float(num_str.replace(",", ".")))
        except Exception:
            return 0

    async def check_human_verification_challenge(self, page: Page) -> Optional[str]:
        """
        Kiểm tra xem Facebook có đang hiển thị màn hình bắt xác minh con người (Checkpoint / CAPTCHA / Khóa tạm thời) hay không.
        Nếu phát hiện, dừng ngay lập tức để bảo vệ tài khoản.
        """
        try:
            cur_url = (page.url or "").lower()
            if any(k in cur_url for k in ["/checkpoint/", "checkpoint", "/login/", "recover/initiate"]):
                return "Phát hiện Facebook chuyển hướng sang trang Xác minh bảo mật (Checkpoint). Đã tự động dừng phiên để bảo vệ tài khoản!"

            body_text = await page.evaluate("""() => {
                return (document.body && document.body.innerText) ? document.body.innerText.slice(0, 2500) : '';
            }""")
            lower_txt = (body_text or "").lower()
            challenge_keywords = [
                "confirm you're human",
                "confirm you are human",
                "xác nhận bạn là con người",
                "xác minh bạn là người thật",
                "tài khoản của bạn đã bị khóa",
                "we suspended your account",
                "chúng tôi đã đình chỉ tài khoản của bạn",
                "enter the characters you see",
                "nhập các ký tự bạn thấy"
            ]
            for kw in challenge_keywords:
                if kw in lower_txt:
                    return f"Phát hiện yêu cầu xác minh con người từ Facebook ('{kw}'). Đã tự động dừng ngay để tránh khóa tài khoản!"
        except Exception:
            pass
        return None

    async def human_type_text(self, page: Page, editor: Any, text: str, human_simulation: bool = True):
        """
        Nhập nội dung bình luận theo nhịp gõ phím tự nhiên của con người (Human-like Keystroke Simulation)
        kết hợp chèn nhanh các cụm URL/Emoji và tự động kết thúc token Link bằng phím Space để Lexical
        nhận diện Link có thể click trực tiếp.
        """
        if not text:
            return
        try:
            await editor.click(force=True)
            await page.wait_for_timeout(random.randint(250, 500))
        except Exception:
            pass

        if not human_simulation:
            await page.keyboard.insert_text(text)
            if re.search(r"https?://\S+$", text.strip()):
                await page.keyboard.press("Space")
            await page.wait_for_timeout(500)
            return

        tokens = [t for t in re.split(r"(\s+)", text) if t]
        for idx, token in enumerate(tokens):
            is_url = token.startswith("http://") or token.startswith("https://") or token.startswith("www.")
            if is_url:
                # Đảm bảo trước URL có khoảng trắng hoặc xuống dòng rõ ràng
                await page.keyboard.insert_text(token)
                await page.wait_for_timeout(random.randint(120, 240))
                # Nếu URL nằm ở cuối câu, gõ thêm phím Space thật để trình soạn thảo Lexical kích hoạt AutoLinkNode
                if idx == len(tokens) - 1:
                    await page.keyboard.press("Space")
                    await page.wait_for_timeout(random.randint(150, 280))
            elif len(token) > 18 or any(ord(c) > 0xFFFF for c in token):
                await page.keyboard.insert_text(token)
                await page.wait_for_timeout(random.randint(70, 170))
            else:
                for ch in token:
                    if ch == "\n":
                        await page.keyboard.press("Shift+Enter")
                        await page.wait_for_timeout(random.randint(120, 260))
                    elif ch == " ":
                        await page.keyboard.press("Space")
                        await page.wait_for_timeout(random.randint(25, 65))
                    else:
                        await page.keyboard.insert_text(ch)
                        await page.wait_for_timeout(random.randint(18, 55))
                if any(p in token for p in [".", ",", "!", "?", ":"]):
                    await page.wait_for_timeout(random.randint(140, 320))
        await page.wait_for_timeout(random.randint(500, 950))

    async def _scan_fb_feed_posts_with_likes(self, page: Page) -> List[Dict[str, Any]]:
        """
        Quét các bài viết đang hiển thị trên Bảng tin Facebook kèm theo số lượt thích (Likes) thực tế.
        Hỗ trợ chính xác cả 2 giao diện Facebook:
        1. Giao diện nút Pill mới (như trong ảnh chụp Inspect):
           - Nút Bình luận là `div.x9f619.x1ja2u2z.x2lah0s.x1n2onr6.xl56j7k.xozqiw3.x1q0g3np.xpdmqnj.x1g0dm76` (74.52 x 44, Role: generic)
           - Nút Thích nằm ngay bên trái cùng hàng, chứa thẻ số tim `span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.x1xmvt09` (VD: '315', '1,2K')
        2. Giao diện thanh Thích / Bình luận / Chia sẻ truyền thống.
        """
        try:
            raw_items = await page.evaluate("""() => {
                const results = [];
                const seenCodes = new Set();
                const origin = (window.location.origin && window.location.origin.startsWith('http'))
                    ? window.location.origin
                    : 'https://www.facebook.com';

                // Tìm tất cả các pill nút hành động theo đúng cấu trúc DOM Facebook mới:
                // div.x9f619.x1ja2u2z.x2lah0s.x1n2onr6.xl56j7k.xozqiw3.x1q0g3np.xpdmqnj.x1g0dm76
                const pillSelector = 'div.x9f619.x1ja2u2z.x2lah0s.x1n2onr6.xl56j7k.xozqiw3.x1q0g3np.xpdmqnj.x1g0dm76';
                const allPills = Array.from(document.querySelectorAll(pillSelector)).filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.width >= 32 && r.width <= 260 && r.height >= 28 && r.height <= 56 && r.bottom > 0;
                });

                // Gom nhóm các pill nằm trên cùng 1 hàng ngang của cùng 1 bài viết
                const rows = [];
                const usedPills = new Set();

                for (const p of allPills) {
                    if (usedPills.has(p)) continue;
                    // Loại trừ các nút nằm bên trong phần bình luận con bên dưới bài viết
                    if (p.closest('[aria-label*="Bình luận dưới tên"], [aria-label*="Bình luận của "], [aria-label*="Phản hồi "], [aria-label*="Comment by "]')) {
                        continue;
                    }
                    const r1 = p.getBoundingClientRect();
                    // Tìm phần tử cha cấp 2..5 chứa cả hàng nút (Like, Comment, Share)
                    let rowContainer = p.parentElement;
                    for (let d = 0; d < 4 && rowContainer; d++) {
                        const rowCandidates = Array.from(rowContainer.querySelectorAll(pillSelector)).filter(other => {
                            const r2 = other.getBoundingClientRect();
                            return Math.abs(r1.top - r2.top) < 8 && Math.abs(r1.height - r2.height) < 8 && r2.width >= 32;
                        });
                        if (rowCandidates.length >= 2 && rowCandidates.length <= 5) {
                            rowCandidates.forEach(c => usedPills.add(c));
                            // Sắp xếp từ trái sang phải (Nút 0 = Like 👍, Nút 1 = Bình luận 💬, Nút 2 = Chia sẻ ↗️)
                            rowCandidates.sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
                            rows.push({
                                likePill: rowCandidates[0],
                                cmtPill: rowCandidates[1],
                                rowEl: rowContainer
                            });
                            break;
                        }
                        rowContainer = rowContainer.parentElement;
                    }
                }

                // Dự phòng cho giao diện Facebook cổ điển (nếu không dùng pillSelector)
                if (rows.length === 0) {
                    const cmtBtns = Array.from(document.querySelectorAll(
                        'div[aria-label="Viết bình luận"], div[aria-label="Bình luận"], div[aria-label="Comment"], div[aria-label="Leave a comment"]'
                    ));
                    for (const cBtn of cmtBtns) {
                        const rC = cBtn.getBoundingClientRect();
                        if (rC.width < 30 || rC.height < 24) continue;
                        let bar = cBtn.parentElement;
                        for (let d = 0; d < 5 && bar; d++) {
                            const likeBtn = bar.querySelector('div[aria-label="Thích"], div[aria-label="Like"], div[aria-label="Bỏ thích"], div[aria-label="Unlike"]');
                            if (likeBtn) {
                                rows.push({ likePill: likeBtn, cmtPill: cBtn, rowEl: bar });
                                break;
                            }
                            bar = bar.parentElement;
                        }
                    }
                }

                let idxCounter = 0;
                for (const item of rows) {
                    const { likePill, cmtPill, rowEl } = item;
                    if (!likePill || !cmtPill) continue;

                    // Đi ngược lên tìm thẻ khung bài viết (card)
                    let card = rowEl;
                    let postLink = null;
                    for (let depth = 0; depth < 16 && card && card !== document.body; depth++) {
                        postLink = card.querySelector(
                            'a[href*="/posts/"], a[href*="fbid="], a[href*="/photo"], a[href*="/permalink/"], ' +
                            'a[href*="/videos/"], a[href*="/reel/"], a[href*="story_fbid="]'
                        );
                        if (postLink) break;
                        card = card.parentElement;
                    }
                    if (!card || card === document.body) {
                        card = rowEl.parentElement ? (rowEl.parentElement.parentElement || rowEl) : rowEl;
                    }

                    // Nếu thẻ bài viết này đã được xử lý/bỏ qua trước đó thì bỏ qua
                    if (card.getAttribute('data-agy-fb-done') === '1') continue;

                    // 1. Trích xuất số lượt thích từ thẻ chính xác `span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.x1xmvt09` bên trong nút Like
                    let likeText = '';
                    const exactLikeSpans = Array.from(likePill.querySelectorAll(
                        'span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.x1xmvt09, span.x193iq5w, span'
                    ));
                    for (const sp of exactLikeSpans) {
                        const t = (sp.textContent || sp.innerText || '').replace(/\\s+/g, ' ').trim();
                        if (t && /\\d/.test(t) && !['thích', 'like', 'bỏ thích', 'unlike'].includes(t.toLowerCase())) {
                            likeText = t;
                            break;
                        }
                    }
                    if (!likeText) {
                        const rawLike = (likePill.innerText || likePill.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (/\\d/.test(rawLike)) {
                            likeText = rawLike;
                        }
                    }

                    // Dự phòng giao diện cổ điển: số cảm xúc nằm ở thanh trạng thái ngay phía trên hàng nút Like/Comment
                    if (!likeText && card) {
                        const likeRect = likePill.getBoundingClientRect();
                        const cardSpans = Array.from(card.querySelectorAll(
                            'span.xt0b8zv, span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.x1xmvt09, span.x193iq5w'
                        ));
                        for (const sp of cardSpans) {
                            const sr = sp.getBoundingClientRect();
                            if (sr.width > 5 && sr.bottom <= likeRect.top + 8 && sr.top >= likeRect.top - 65 && sr.left < likeRect.right + 120) {
                                const t = (sp.textContent || '').replace(/\\s+/g, ' ').trim();
                                const tl = t.toLowerCase();
                                if (/^\\d/.test(t) && !tl.includes('bình luận') && !tl.includes('comment') && !tl.includes('chia sẻ') && !tl.includes('share')) {
                                    likeText = t;
                                    break;
                                }
                            }
                        }
                    }

                    // 2. Xác định URL hoặc mã định danh duy nhất của bài viết
                    let cleanUrl = '';
                    if (postLink) {
                        const href = postLink.getAttribute('href') || '';
                        if (href) {
                            const fullUrl = href.startsWith('http') ? href : (origin + (href.startsWith('/') ? href : '/' + href));
                            // Giữ lại fbid / story_fbid nếu là link photo.php hoặc permalink.php
                            if (fullUrl.includes('fbid=') || fullUrl.includes('story_fbid=')) {
                                const m = fullUrl.match(/[?&](?:story_)?fbid=([^&]+)/);
                                cleanUrl = m ? (origin + '/?fbid=' + m[1]) : fullUrl.split('&')[0];
                            } else {
                                cleanUrl = fullUrl.split('?')[0].replace(/\\/+$/, '');
                            }
                        }
                    }

                    let postCode = card.getAttribute('data-agy-fb-card') || '';
                    if (!postCode) {
                        if (cleanUrl) {
                            postCode = 'fb_' + cleanUrl.replace(/[^a-zA-Z0-9]/g, '').slice(-28);
                        } else {
                            const snippet = (card.innerText || '').replace(/\\s+/g, '').slice(0, 32);
                            idxCounter += 1;
                            postCode = 'fb_card_' + idxCounter + '_' + snippet.replace(/[^a-zA-Z0-9]/g, '').slice(0, 16);
                        }
                    }
                    if (!cleanUrl) {
                        cleanUrl = origin + '/#' + postCode;
                    }
                    if (seenCodes.has(postCode)) continue;
                    seenCodes.add(postCode);

                    card.setAttribute('data-agy-fb-card', postCode);
                    likePill.setAttribute('data-agy-fb-like-btn', postCode);
                    cmtPill.setAttribute('data-agy-fb-cmt-btn', postCode);

                    results.push({
                        url: cleanUrl,
                        postCode: postCode,
                        likeText: likeText || '0'
                    });
                }
                return results;
            }""")
        except Exception:
            return []

        parsed_list = []
        for item in (raw_items or []):
            l_txt = item.get("likeText", "0")
            likes = self.parse_like_count(l_txt)
            parsed_list.append({
                "url": item.get("url", ""),
                "post_code": item.get("postCode", ""),
                "like_text": l_txt or "0",
                "likes": likes
            })
        return parsed_list

    async def _get_single_fb_post_likes(self, page: Page) -> tuple[int, str]:
        """Lấy số lượt thích khi đang mở trang chi tiết một bài viết Facebook cụ thể."""
        posts = await self._scan_fb_feed_posts_with_likes(page)
        if posts:
            return posts[0]["likes"], posts[0]["like_text"]
        return 0, "0"

    async def _interact_and_open_comment_on_fb_feed(self, page: Page, post_code: str, auto_like: bool = True) -> Any:
        """
        Cuộn mượt tới bài viết trên Bảng tin Facebook, nghỉ đọc bài tự nhiên,
        tự động thả Like (tùy chọn) và nhấn vào nút Bình luận (`div.x9f619.x1ja2u2z...` 💬)
        để mở ô nhập bình luận trực tiếp mà không cần tải lại trang.
        Trả về phần tử `editor` (`div[role="textbox"][contenteditable="true"]`) nếu mở thành công.
        """
        if not post_code:
            return None
        try:
            # 1. Cuộn bài viết vào giữa màn hình mượt mà như người thật
            found = await page.evaluate("""(code) => {
                const cmtBtn = document.querySelector(`[data-agy-fb-cmt-btn="${code}"]`);
                const card = document.querySelector(`[data-agy-fb-card="${code}"]`);
                const target = cmtBtn || card;
                if (!target) return false;
                target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return true;
            }""", post_code)
            if not found:
                return None

            await page.wait_for_timeout(random.randint(1800, 3200))

            # 2. Tự động thả Like bài viết trước khi bình luận (xác suất 70% khi bật mô phỏng người thật)
            if auto_like and random.random() < 0.70:
                try:
                    like_loc = page.locator(f'[data-agy-fb-like-btn="{post_code}"]').first
                    if await like_loc.count() > 0:
                        await like_loc.click(timeout=3000)
                        await page.wait_for_timeout(random.randint(900, 1600))
                except Exception:
                    pass

            # 3. Nhấn vào nút Bình luận (`div.x9f619.x1ja2u2z...` 💬 69) bằng chuột thật của Playwright
            clicked_cmt = False
            try:
                cmt_loc = page.locator(f'[data-agy-fb-cmt-btn="{post_code}"]').first
                if await cmt_loc.count() > 0:
                    await cmt_loc.click(timeout=4000)
                    clicked_cmt = True
            except Exception:
                clicked_cmt = False

            if not clicked_cmt:
                coords = await page.evaluate("""(code) => {
                    const btn = document.querySelector(`[data-agy-fb-cmt-btn="${code}"]`);
                    if (!btn) return null;
                    const r = btn.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }""", post_code)
                if coords:
                    await page.mouse.click(coords["x"], coords["y"])
                    clicked_cmt = True

            await page.wait_for_timeout(random.randint(1600, 2600))

            # 4. Tìm ô nhập bình luận vừa được focus hoặc hiển thị trong Modal / dưới bài viết
            # Ưu tiên 1: Phần tử đang được focus tự động sau khi bấm nút Bình luận
            active_is_editor = await page.evaluate("""() => {
                const el = document.activeElement;
                if (el && el.getAttribute('contenteditable') === 'true' && el.getAttribute('role') === 'textbox') {
                    document.querySelectorAll('[data-agy-fb-active-editor]').forEach(n => n.removeAttribute('data-agy-fb-active-editor'));
                    el.setAttribute('data-agy-fb-active-editor', '1');
                    return true;
                }
                return false;
            }""")
            if active_is_editor:
                ed = await page.query_selector('[data-agy-fb-active-editor="1"]')
                if ed:
                    return ed

            # Ưu tiên 2: Tìm ô nhập bình luận chính (loại trừ các ô 'Trả lời...' bình luận con và loại trừ ô 'Bạn đang nghĩ gì')
            tagged_editor = await page.evaluate("""(code) => {
                document.querySelectorAll('[data-agy-fb-active-editor]').forEach(n => n.removeAttribute('data-agy-fb-active-editor'));

                const isCommentBox = (el) => {
                    const r = el.getBoundingClientRect();
                    if (r.width < 80 || r.height < 14 || r.bottom <= 0) return false;
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    const placeholder = (el.getAttribute('aria-placeholder') || '').toLowerCase();
                    const combined = aria + ' ' + placeholder;
                    // Không lấy ô đăng bài đầu trang ('bạn đang nghĩ gì') hoặc ô phản hồi bình luận con ('trả lời ')
                    if (combined.includes('nghĩ gì') || combined.includes('on your mind')) return false;
                    if (combined.startsWith('trả lời ') || combined.startsWith('reply to ')) return false;
                    return combined.includes('bình luận') || combined.includes('comment') || Boolean(el.closest('div[role="dialog"]'));
                };

                // Nếu nút Bình luận mở ra Modal (div[role="dialog"]), ưu tiên ô textbox trong Modal
                const dialogs = Array.from(document.querySelectorAll('div[role="dialog"]'));
                for (let i = dialogs.length - 1; i >= 0; i--) {
                    const dlg = dialogs[i];
                    const boxes = Array.from(dlg.querySelectorAll('div[role="textbox"][contenteditable="true"], div[contenteditable="true"]'));
                    for (let j = boxes.length - 1; j >= 0; j--) {
                        if (isCommentBox(boxes[j])) {
                            boxes[j].setAttribute('data-agy-fb-active-editor', '1');
                            return true;
                        }
                    }
                }

                // Nếu mở khung bình luận ngay bên dưới bài viết trên Bảng tin
                const cmtBtn = document.querySelector(`[data-agy-fb-cmt-btn="${code}"]`);
                const btnTop = cmtBtn ? cmtBtn.getBoundingClientRect().top : 0;
                const allBoxes = Array.from(document.querySelectorAll('div[role="textbox"][contenteditable="true"]')).filter(isCommentBox);
                // Chọn ô bình luận nằm gần bên dưới nút Bình luận vừa bấm nhất
                let bestBox = null;
                let bestDist = 999999;
                for (const b of allBoxes) {
                    const br = b.getBoundingClientRect();
                    const dist = Math.abs(br.top - btnTop);
                    if (br.top >= btnTop - 40 && dist < bestDist) {
                        bestDist = dist;
                        bestBox = b;
                    }
                }
                if (!bestBox && allBoxes.length > 0) {
                    bestBox = allBoxes[allBoxes.length - 1];
                }
                if (bestBox) {
                    bestBox.setAttribute('data-agy-fb-active-editor', '1');
                    return true;
                }
                return false;
            }""", post_code)

            if tagged_editor:
                return await page.query_selector('[data-agy-fb-active-editor="1"]')
        except Exception:
            pass
        return None

    async def _attach_media_to_fb_comment(self, page: Page, editor: Any, media_files: List[str]) -> bool:
        """
        Đính kèm toàn bộ hình ảnh trong Folder Excel vào ô bình luận Facebook.
        Do khung bình luận Facebook chỉ cho phép 1 file ảnh/bình luận, khi Folder có từ 2 ảnh trở lên,
        hệ thống tự động ghép toàn bộ ảnh trong Folder thành 1 ảnh tổng hợp sắc nét rồi đính kèm vào bình luận.
        """
        valid_files = [f for f in (media_files or []) if os.path.exists(f)]
        if not valid_files:
            return False

        from core.excel_loader import combine_folder_images_for_comment
        target_file = combine_folder_images_for_comment(valid_files) or valid_files[0]

        try:
            mime, _ = mimetypes.guess_type(target_file)
            mime = mime or "image/jpeg"
            with open(target_file, "rb") as mf:
                b64_data = base64.b64encode(mf.read()).decode("utf-8")

            await editor.click(force=True)
            await page.wait_for_timeout(300)

            pasted = await page.evaluate("""({b64, mime, filename}) => {
                const target = document.querySelector('[data-agy-fb-active-editor="1"]') || document.activeElement;
                if (!target) return false;
                const byteCharacters = atob(b64);
                const byteNumbers = new Array(byteCharacters.length);
                for (let i = 0; i < byteCharacters.length; i++) {
                    byteNumbers[i] = byteCharacters.charCodeAt(i);
                }
                const byteArray = new Uint8Array(byteNumbers);
                const file = new File([byteArray], filename, { type: mime });
                const dt = new DataTransfer();
                dt.items.add(file);
                target.focus();
                const pasteEvent = new ClipboardEvent('paste', {
                    bubbles: true,
                    cancelable: true,
                    clipboardData: dt
                });
                target.dispatchEvent(pasteEvent);
                return true;
            }""", {"b64": b64_data, "mime": mime, "filename": os.path.basename(target_file)})

            if pasted:
                await page.wait_for_timeout(random.randint(3800, 5200))
                return True
        except Exception:
            pass

        # Fallback: Tìm input[type="file"] gần khung bình luận
        try:
            fi_list = await page.query_selector_all('input[type="file"][accept*="image"], input[type="file"]')
            if fi_list:
                await fi_list[-1].set_input_files([target_file])
                await page.wait_for_timeout(random.randint(3800, 5200))
                return True
        except Exception:
            pass
        return False

    async def _submit_fb_comment(self, page: Page, editor: Any) -> bool:
        """
        Gửi bình luận trên Facebook bằng click nút gửi (#focused-state-composer-submit / aria-label='Đăng bình luận')
        kết hợp phím Enter.
        Chờ ảnh tải lên hoàn tất (nút gửi hết trạng thái aria-disabled='true') trước khi bấm,
        và chờ trạng thái 'Đang viết...' / 'Posting...' hoàn tất trước khi kết thúc.
        """
        try:
            # Chờ tối đa 15 giây nếu nút gửi đang bị aria-disabled="true" (do đang tải ảnh đính kèm)
            for _ in range(15):
                is_uploading = await page.evaluate("""() => {
                    const submitWrap = document.querySelector(
                        '#focused-state-composer-submit [aria-disabled="true"], ' +
                        'div[aria-label="Đăng bình luận"][aria-disabled="true"], ' +
                        'div[aria-label="Bình luận"][aria-disabled="true"]'
                    );
                    return Boolean(submitWrap);
                }""")
                if not is_uploading:
                    break
                await page.wait_for_timeout(1000)

            send_selector = (
                '#focused-state-composer-submit div[role="button"]:not([aria-disabled="true"]), '
                'div[aria-label="Đăng bình luận"][role="button"]:not([aria-disabled="true"]), '
                'div[aria-label="Bình luận"][role="button"]:not([aria-disabled="true"]), '
                'div[aria-label="Gửi"][role="button"]:not([aria-disabled="true"]), '
                'div[aria-label="Comment"][role="button"]:not([aria-disabled="true"])'
            )

            clicked_send = False
            try:
                loc = page.locator(send_selector).last
                if await loc.count() > 0:
                    await loc.click(timeout=3500)
                    clicked_send = True
            except Exception:
                clicked_send = False

            if not clicked_send:
                clicked_send = await page.evaluate("""(sel) => {
                    const btns = Array.from(document.querySelectorAll(sel));
                    for (let i = btns.length - 1; i >= 0; i--) {
                        const r = btns[i].getBoundingClientRect();
                        if (r.width >= 10 && r.height >= 10) {
                            btns[i].click();
                            return true;
                        }
                    }
                    return false;
                }""", send_selector)

            if not clicked_send:
                # Cách dự phòng: Focus vào ô bình luận và nhấn phím Enter
                try:
                    await editor.click(force=True)
                    await page.wait_for_timeout(200)
                except Exception:
                    pass
                await page.keyboard.press("Enter")

            # Chờ bình luận gửi hoàn tất (hết trạng thái "Đang viết..." / "Posting...") trước khi đóng hộp thoại
            await page.wait_for_timeout(2200)
            for _ in range(12):
                still_posting = await page.evaluate("""() => {
                    const spans = Array.from(document.querySelectorAll('span, div'));
                    for (const el of spans) {
                        const t = (el.innerText || '').trim();
                        if (t === 'Đang viết...' || t === 'Posting...' || t === 'Đang đăng...') {
                            return true;
                        }
                    }
                    return false;
                }""")
                if not still_posting:
                    break
                await page.wait_for_timeout(1000)

            await page.wait_for_timeout(random.randint(1500, 2500))
            return True
        except Exception:
            return False

    async def run_fb_commenting_session(
        self,
        cookie_str: str,
        target_urls: List[str],
        excel_posts: List[Dict[str, Any]],
        anti_config: Any = None,
        proxy: str = "",
        headless: bool = False,
        uid: str = "",
        post_as_page_name: str = "",
        page_id: str = "",
        page_url: str = "",
        min_likes: int = 0,
        human_simulation: bool = True,
        is_paused_fn: Optional[Callable[[], bool]] = None,
        is_stopped_fn: Optional[Callable[[], bool]] = None,
        log_callback: Optional[Callable[[str, str, str, str, str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ):
        """
        Phiên tự động đi bình luận trên Facebook (Bảng tin Trang chủ hoặc danh sách Link bài viết):
        - Lọc chỉ bình luận vào bài viết có số lượt thích (Likes) >= min_likes (đọc từ `span.x193iq5w.xeuugli...`).
        - Nhấn trực tiếp nút Bình luận (`div.x9f619.x1ja2u2z...`) ngay trên Bảng tin.
        - Lấy nội dung (Cột A) và ảnh trong Folder (Cột B) từ file Excel theo vòng lặp tuần tự (Mẫu #1 -> #2 -> ... -> #N -> #1).
        - Kết hợp tự động thả Like, gõ phím theo nhịp người thật và giữ nguyên 1 phiên trình duyệt để chống Checkpoint / Xác minh con người.
        """
        cookies = self.parse_cookie_string(cookie_str)
        if not uid:
            uid = self.extract_uid_from_cookie(cookies)

        from core.excel_loader import get_fresh_media_for_post
        if not anti_config:
            anti_config = AntiSpamConfig()
        anti_mgr = AntiSpamManager(anti_config)

        profile_label = f"Fanpage: {post_as_page_name}" if post_as_page_name else "Nick cá nhân"

        def emit_log(target: str, status: str, msg: str):
            if log_callback:
                log_callback(time.strftime("%H:%M:%S"), profile_label, target, status, msg)

        def get_next_template(seq_idx: int) -> tuple[str, List[str], str]:
            if excel_posts and len(excel_posts) > 0:
                item = excel_posts[seq_idx % len(excel_posts)]
                raw_txt = item.get("content", "")
                files = get_fresh_media_for_post(item)
                if anti_config and getattr(anti_config, "randomize_media", False) and len(files) > 1:
                    random.shuffle(files)
                title = item.get("title") or f"Mẫu #{(seq_idx % len(excel_posts)) + 1}"
                parsed_txt = anti_mgr.process_content(raw_txt or "")
                return parsed_txt.strip(), files, title
            return "", [], "Mẫu trống"

        browser = None
        context = None
        try:
            async with async_playwright() as p:
                browser, context = await self.create_context(
                    p, cookies, proxy=proxy, headless=headless, uid=uid, page_id=page_id
                )
                page = await context.new_page()

                # Chuyển sang đúng tư cách Nick cá nhân hoặc Fanpage
                await self.ensure_active_profile(
                    page=page,
                    uid=uid,
                    target_page_name=post_as_page_name,
                    target_page_id=page_id,
                    target_page_url=page_url,
                    logger_callback=lambda level, msg: emit_log("-", level, msg)
                )

                # --- TRƯỜNG HỢP 1: CÓ DANH SÁCH LINK BÀI VIẾT CỤ THỂ ---
                if target_urls and len(target_urls) > 0:
                    total = len(target_urls)
                    if progress_callback:
                        progress_callback(0, total)

                    for idx, target_url in enumerate(target_urls, 1):
                        if is_stopped_fn and is_stopped_fn():
                            emit_log("-", "STOPPED", "Đã dừng tiến trình bình luận theo yêu cầu.")
                            break

                        while is_paused_fn and is_paused_fn():
                            if is_stopped_fn and is_stopped_fn():
                                break
                            await asyncio.sleep(1)

                        parsed_cmt, valid_files, tpl_title = get_next_template(idx - 1)
                        emit_log(target_url, "POSTING", f"Đang mở bài viết {idx}/{total} [{tpl_title}]: {target_url}...")

                        try:
                            await page.goto(target_url, wait_until="domcontentloaded", timeout=35000)
                            await page.wait_for_timeout(random.randint(3000, 4500))

                            challenge_msg = await self.check_human_verification_challenge(page)
                            if challenge_msg:
                                emit_log(target_url, "FAILED", f"🛡️ {challenge_msg}")
                                break

                            posts = await self._scan_fb_feed_posts_with_likes(page)
                            first_post = posts[0] if posts else None
                            if min_likes > 0 and first_post and first_post["likes"] < min_likes:
                                emit_log(
                                    target_url,
                                    "SKIPPED",
                                    f"⏭️ Bỏ qua bài viết vì có {first_post['like_text']} lượt thích (< mức tối thiểu {min_likes} like)."
                                )
                                continue

                            post_code = first_post["post_code"] if first_post else ""
                            editor = await self._interact_and_open_comment_on_fb_feed(page, post_code, auto_like=human_simulation) if post_code else None
                            if not editor:
                                editor = await page.query_selector('div[role="textbox"][contenteditable="true"][aria-label*="bình luận" i], div[role="textbox"][contenteditable="true"][aria-label*="comment" i]')

                            if not editor:
                                emit_log(target_url, "FAILED", "Không tìm thấy ô bình luận trên bài viết này.")
                                continue

                            if parsed_cmt:
                                await self.human_type_text(page, editor, parsed_cmt, human_simulation=human_simulation)

                            if valid_files:
                                await self._attach_media_to_fb_comment(page, editor, valid_files)

                            if await self._submit_fb_comment(page, editor):
                                anti_mgr.record_post()
                                emit_log(target_url, "SUCCESS", f"✅ Đã bình luận thành công bài #{idx} [{tpl_title}]: {target_url}")
                            else:
                                emit_log(target_url, "FAILED", "Không thể gửi bình luận.")

                        except Exception as e:
                            emit_log(target_url, "FAILED", f"Lỗi thao tác: {str(e)}")

                        if progress_callback:
                            progress_callback(idx, total)

                        if idx < total and not (is_stopped_fn and is_stopped_fn()):
                            delay_sec = anti_mgr.get_random_delay()
                            emit_log("-", "WAITING", f"Nghỉ giãn cách {delay_sec}s trước bài tiếp theo...")
                            for _ in range(delay_sec):
                                if is_stopped_fn and is_stopped_fn():
                                    break
                                await asyncio.sleep(1)

                # --- TRƯỜNG HỢP 2: TỰ ĐỘNG LƯỚT BẢNG TIN FACEBOOK & LỌC BÀI CÓ SỐ LIKE >= MIN_LIKES ---
                else:
                    like_desc = f"Lọc bài >= {min_likes} Likes" if min_likes > 0 else "Mọi bài viết"
                    emit_log(
                        "Bảng tin Facebook",
                        "POSTING",
                        f"Đang mở Bảng tin Facebook ({like_desc} | Mô phỏng người thật chống Checkpoint)..."
                    )
                    await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=35000)
                    await page.wait_for_timeout(random.randint(3500, 5000))

                    if human_simulation:
                        await page.mouse.wheel(0, random.randint(300, 600))
                        await page.wait_for_timeout(random.randint(1500, 2600))

                    seen_codes = set()
                    skipped_low_likes = 0
                    success_count = 0

                    while True:
                        if is_stopped_fn and is_stopped_fn():
                            emit_log("-", "SKIPPED", f"Đã dừng tiến trình. Tổng cộng đã bình luận {success_count} bài viết Facebook.")
                            break

                        while is_paused_fn and is_paused_fn():
                            if is_stopped_fn and is_stopped_fn():
                                break
                            await asyncio.sleep(1)

                        challenge_msg = await self.check_human_verification_challenge(page)
                        if challenge_msg:
                            emit_log("-", "FAILED", f"🛡️ {challenge_msg}")
                            break

                        candidate = None
                        recent_skipped = []
                        for _ in range(10):
                            if is_stopped_fn and is_stopped_fn():
                                break
                            feed_posts = await self._scan_fb_feed_posts_with_likes(page)
                            for fp in feed_posts:
                                code = fp["post_code"]
                                if not code or code in seen_codes:
                                    continue
                                if min_likes > 0 and fp["likes"] < min_likes:
                                    seen_codes.add(code)
                                    skipped_low_likes += 1
                                    recent_skipped.append(f"{fp['like_text']} ({fp['likes']})")
                                    await page.evaluate("""(c) => {
                                        const card = document.querySelector(`[data-agy-fb-card="${c}"]`);
                                        if (card) card.setAttribute('data-agy-fb-done', '1');
                                    }""", code)
                                    continue
                                candidate = fp
                                break

                            if candidate:
                                break

                            await page.mouse.wheel(0, random.randint(600, 1000))
                            await page.wait_for_timeout(random.randint(1800, 2800))

                        if not candidate:
                            sample_str = ", ".join(recent_skipped[-5:]) if recent_skipped else "0"
                            emit_log(
                                "Bảng tin Facebook",
                                "WAITING",
                                f"Đang cuộn tìm bài >= {min_likes} Likes (Đã bỏ qua {skipped_low_likes} bài | Số like đọc được: {sample_str})..."
                            )
                            await page.mouse.wheel(0, random.randint(850, 1350))
                            await page.wait_for_timeout(random.randint(2000, 3200))
                            continue

                        post_code = candidate["post_code"]
                        post_url = candidate["url"]
                        post_like_text = candidate["like_text"]
                        seen_codes.add(post_code)

                        # Đánh dấu bài viết này đã xử lý để lần quét sau không lặp lại
                        await page.evaluate("""(c) => {
                            const card = document.querySelector(`[data-agy-fb-card="${c}"]`);
                            if (card) card.setAttribute('data-agy-fb-done', '1');
                        }""", post_code)

                        parsed_cmt, valid_files, tpl_title = get_next_template(success_count)
                        emit_log(
                            post_url,
                            "POSTING",
                            f"🎯 Đã chọn bài #{success_count + 1} (👍 {post_like_text} lượt thích >= {min_likes}) | Đang bình luận [{tpl_title}]..."
                        )

                        try:
                            editor = await self._interact_and_open_comment_on_fb_feed(
                                page=page,
                                post_code=post_code,
                                auto_like=human_simulation
                            )
                            if not editor:
                                emit_log(post_url, "FAILED", "Không mở được khung bình luận cho bài viết này, chuyển sang bài tiếp theo...")
                                continue

                            if parsed_cmt:
                                await self.human_type_text(page, editor, parsed_cmt, human_simulation=human_simulation)

                            if valid_files:
                                await self._attach_media_to_fb_comment(page, editor, valid_files)

                            if await self._submit_fb_comment(page, editor):
                                success_count += 1
                                anti_mgr.record_post()
                                emit_log(
                                    post_url,
                                    "SUCCESS",
                                    f"✅ Đã bình luận bài #{success_count} (👍 {post_like_text} likes) [{tpl_title}]: {post_url}"
                                )
                                if progress_callback:
                                    progress_callback(success_count, 0)
                            else:
                                emit_log(post_url, "FAILED", "Không thể gửi bình luận.")

                            # Nếu việc bấm nút Bình luận làm mở hộp thoại bài viết (div[role="dialog"]), đóng hộp thoại để quay về Bảng tin
                            has_dialog = await page.evaluate("""() => {
                                const dlg = document.querySelector('div[role="dialog"]');
                                if (!dlg) return false;
                                const closeBtn = dlg.querySelector('div[aria-label="Đóng"], div[aria-label="Close"]');
                                if (closeBtn) {
                                    closeBtn.click();
                                    return true;
                                }
                                return true;
                            }""")
                            if has_dialog:
                                await page.keyboard.press("Escape")
                                await page.wait_for_timeout(1200)

                        except Exception as e:
                            emit_log(post_url, "FAILED", f"Lỗi khi bình luận: {str(e)}")
                            try:
                                await page.keyboard.press("Escape")
                            except Exception:
                                pass

                        # Giãn cách Anti-Spam kèm cuộn nhẹ tự nhiên
                        if not (is_stopped_fn and is_stopped_fn()):
                            delay_sec = anti_mgr.get_random_delay()
                            emit_log("-", "WAITING", f"Nghỉ giãn cách {delay_sec}s trước bài tiếp theo (Mô phỏng đọc bảng tin)...")
                            for sec_i in range(delay_sec):
                                if is_stopped_fn and is_stopped_fn():
                                    break
                                while is_paused_fn and is_paused_fn():
                                    if is_stopped_fn and is_stopped_fn():
                                        break
                                    await asyncio.sleep(1)
                                if human_simulation and sec_i > 0 and sec_i % 18 == 0:
                                    try:
                                        await page.mouse.wheel(0, random.randint(180, 420))
                                    except Exception:
                                        pass
                                await asyncio.sleep(1)

                            if anti_mgr.should_rest() and not (is_stopped_fn and is_stopped_fn()):
                                r_sec = anti_mgr.get_rest_duration_sec()
                                emit_log("-", "RESTING", f"Tạm nghỉ dài {r_sec // 60} phút chống Checkpoint...")
                                for _ in range(r_sec):
                                    if is_stopped_fn and is_stopped_fn():
                                        break
                                    while is_paused_fn and is_paused_fn():
                                        if is_stopped_fn and is_stopped_fn():
                                            break
                                        await asyncio.sleep(1)
                                    await asyncio.sleep(1)

                try:
                    await self.safe_save_storage_state(context, uid, page_id=page_id)
                except Exception:
                    pass
                await context.close()
                await browser.close()
        except Exception as e:
            emit_log("-", "ERROR", f"Lỗi phiên bình luận Facebook: {str(e)}")
            try:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
            except Exception:
                pass

    async def comment_on_post(
        self,
        page: Page,
        target_url: str,
        content_template: str,
        media_paths: Optional[List[str]] = None,
        auto_like: bool = True,
        anti_spam: Optional[AntiSpamManager] = None,
        logger_callback: Optional[Callable[[str, str], None]] = None,
        cookie_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tự động thả like (tùy chọn) và bình luận vào bài viết Facebook (theo URL hoặc Post ID).
        Hỗ trợ Spintax, chống spam, đính kèm ảnh và tự động xử lý các rào cản giao diện.
        """
        try:
            # 1. Chuẩn hóa đường dẫn bài viết
            target_url = target_url.strip()
            if not target_url:
                return {"success": False, "message": "Đường dẫn bài viết trống!"}

            if not target_url.startswith("http://") and not target_url.startswith("https://"):
                # Nếu chỉ là số ID bài viết
                if target_url.isdigit() or ("_" in target_url and target_url.replace("_", "").isdigit()):
                    target_url = f"https://www.facebook.com/{target_url}"
                else:
                    target_url = f"https://www.facebook.com/{target_url}"

            # Đổi m.facebook hoặc mbasic sang www.facebook
            target_url = re.sub(r"https?://(m|mbasic)\.facebook\.com", "https://www.facebook.com", target_url)

            if logger_callback:
                logger_callback("INFO", f"Đang điều hướng đến bài viết: {target_url}")

            await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3.5)

            # Tự đóng các popup hoặc dialog che khuất (như 'Xem thêm trên Facebook' hoặc cookie banner)
            try:
                await page.keyboard.press("Escape")
                close_btn = await page.query_selector("div[aria-label='Đóng'], div[aria-label='Close'], div[role='button']:has-text('Không phải bây giờ')")
                if close_btn and await close_btn.is_visible():
                    await close_btn.click()
            except Exception:
                pass

            # 2. Tự động thả cảm xúc Like nếu được bật
            if auto_like:
                try:
                    if logger_callback:
                        logger_callback("INFO", "Đang kiểm tra và thả Like cho bài viết...")

                    like_selectors = [
                        "div[aria-label='Thích'][role='button']",
                        "div[aria-label='Like'][role='button']",
                        "div[aria-label*='Bày tỏ cảm xúc'][role='button']",
                        "div[role='button']:has-text('Thích')",
                        "span:has-text('Thích')"
                    ]
                    for l_sel in like_selectors:
                        like_btn = await page.query_selector(l_sel)
                        if like_btn and await like_btn.is_visible():
                            # Kiểm tra xem bài viết đã like chưa (aria-pressed='true' hoặc label 'Gỡ thích')
                            aria_pressed = await like_btn.get_attribute("aria-pressed")
                            aria_label = await like_btn.get_attribute("aria-label") or ""
                            if aria_pressed != "true" and "Gỡ" not in aria_label and "Remove" not in aria_label:
                                await like_btn.click()
                                if logger_callback:
                                    logger_callback("INFO", "Đã thả Like thành công!")
                                await asyncio.sleep(1.5)
                                break
                except Exception as le:
                    if logger_callback:
                        logger_callback("WARNING", f"Bỏ qua bước Like: {str(le)}")

            # 3. Chuẩn bị nội dung bình luận (Spintax & Anti-spam)
            final_text = SpintaxParser.parse(content_template)
            if anti_spam:
                final_text = anti_spam.prepare_text(final_text)

            # Cuộn trang nhẹ xuống để khu vực bình luận lọt vào viewport
            try:
                await page.evaluate("window.scrollBy(0, 350)")
            except Exception:
                pass
            await asyncio.sleep(1.5)

            # 4. Tìm ô nhập bình luận
            comment_selectors = [
                "div[role='textbox'][aria-label*='Viết bình luận']",
                "div[role='textbox'][aria-label*='Write a comment']",
                "div[role='textbox'][aria-label*='bình luận']",
                "div[role='textbox'][aria-label*='comment']",
                "div[contenteditable='true'][role='textbox']",
                "div[contenteditable='true'][data-lexical-editor='true']",
                "form div[contenteditable='true']",
                "div[role='dialog'] div[contenteditable='true']",
                "div[contenteditable='true']"
            ]

            comment_box = None
            for sel in comment_selectors:
                try:
                    candidates = await page.query_selector_all(sel)
                    for c in candidates:
                        if await c.is_visible():
                            comment_box = c
                            break
                    if comment_box:
                        break
                except Exception:
                    continue

            # Nếu chưa thấy ô nhập bình luận, thử tìm nút bấm "Bình luận" để kích hoạt ô nhập
            if not comment_box:
                try:
                    open_cmt_btns = [
                        "div[aria-label*='Bình luận'][role='button']",
                        "div[aria-label*='Comment'][role='button']",
                        "div[role='button']:has-text('Bình luận')",
                        "span:has-text('Bình luận')"
                    ]
                    for ob_sel in open_cmt_btns:
                        ob = await page.query_selector(ob_sel)
                        if ob and await ob.is_visible():
                            await ob.click()
                            await asyncio.sleep(2)
                            break
                    
                    # Thử tìm lại ô nhập sau khi bấm nút
                    for sel in comment_selectors:
                        candidates = await page.query_selector_all(sel)
                        for c in candidates:
                            if await c.is_visible():
                                comment_box = c
                                break
                        if comment_box:
                            break
                except Exception:
                    pass

            if not comment_box:
                if logger_callback:
                    logger_callback("ERROR", "Không tìm thấy khung nhập bình luận (Bài viết có thể đã tắt tính năng bình luận hoặc bạn chưa có quyền).")
                return {"success": False, "message": "Không tìm thấy khung nhập bình luận!"}

            # Focus vào khung bình luận
            try:
                await comment_box.scroll_into_view_if_needed()
                await comment_box.click(force=True)
                await comment_box.focus()
            except Exception:
                pass
            await asyncio.sleep(1)

            # Nhập nội dung bình luận
            if logger_callback:
                logger_callback("INFO", f"Đang nhập nội dung bình luận: '{final_text[:50]}...'")

            try:
                await page.keyboard.insert_text(final_text)
            except Exception:
                if anti_spam:
                    for char in final_text:
                        await page.keyboard.write(char)
                        await asyncio.sleep(anti_spam.get_typing_delay())
                else:
                    await page.keyboard.type(final_text, delay=35)

            await asyncio.sleep(2)

            # 5. Đính kèm ảnh nếu có
            if media_paths:
                valid_media = [m for m in media_paths if os.path.exists(m)]
                if valid_media:
                    if logger_callback:
                        logger_callback("INFO", f"Đang đính kèm ảnh bình luận: {os.path.basename(valid_media[0])}...")
                    
                    attached = False
                    # Cách 1: Nạp file vào input type='file' của khung comment
                    try:
                        file_input = await page.query_selector("form input[type='file'][accept*='image'], input[type='file'][accept*='image']")
                        if file_input:
                            await file_input.set_input_files(valid_media[0])
                            attached = True
                            await asyncio.sleep(3)
                    except Exception:
                        attached = False

                    # Cách 2: Dán ảnh Clipboard trực tiếp vào comment box
                    if not attached:
                        try:
                            ext = os.path.splitext(valid_media[0])[1].lower()
                            mime, _ = mimetypes.guess_type(valid_media[0])
                            mime = mime or "image/png"
                            with open(valid_media[0], "rb") as mf:
                                b64 = base64.b64encode(mf.read()).decode('utf-8')
                            
                            await page.evaluate("""({b64, mime, filename}) => {
                                const bytes = atob(b64);
                                const arr = new Uint8Array(bytes.length);
                                for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
                                const file = new File([arr], filename, { type: mime });
                                const dt = new DataTransfer();
                                dt.items.add(file);
                                const target = document.activeElement || document.querySelector("div[role='textbox']");
                                if (target) {
                                    target.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: dt }));
                                }
                            }""", {"b64": b64, "mime": mime, "filename": os.path.basename(valid_media[0])})
                            await asyncio.sleep(3)
                            attached = True
                        except Exception:
                            pass

            # 6. Nhấn Enter hoặc nút gửi để gửi bình luận
            if logger_callback:
                logger_callback("INFO", "Đang gửi bình luận...")

            await page.keyboard.press("Enter")
            await asyncio.sleep(2)

            # Nếu Enter chưa gửi (ví dụ Facebook đòi bấm nút gửi), thử tìm icon/nút Gửi
            try:
                send_btns = [
                    "div[aria-label='Bình luận'][role='button']",
                    "div[aria-label='Comment'][role='button']",
                    "div[aria-label*='Nhấn Enter để gửi']"
                ]
                for s_sel in send_btns:
                    s_btn = await page.query_selector(s_sel)
                    if s_btn and await s_btn.is_visible():
                        await s_btn.click()
                        await asyncio.sleep(1.5)
                        break
            except Exception:
                pass

            await asyncio.sleep(4)

            if anti_spam:
                anti_spam.record_post()

            if logger_callback:
                logger_callback("INFO", f"✅ Đã bình luận thành công vào bài viết!")

            return {"success": True, "message": "Bình luận thành công!", "content": final_text}

        except Exception as e:
            if logger_callback:
                logger_callback("ERROR", f"Lỗi ngoại lệ khi bình luận: {str(e)}")
            return {"success": False, "message": f"Lỗi: {str(e)}"}

    async def scan_group_posts(
        self,
        page: Page,
        group_url: str,
        limit: int = 10,
        logger_callback: Optional[Callable[[str, str], None]] = None
    ) -> List[str]:
        """Quét và trích xuất danh sách link bài viết mới nhất từ một nhóm Facebook."""
        post_urls = []
        try:
            if logger_callback:
                logger_callback("INFO", f"Đang quét bài viết từ nhóm: {group_url}")

            await page.goto(group_url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(3)

            # Cuộn trang 3-5 lần để tải bài viết
            for i in range(4):
                await page.evaluate("window.scrollBy(0, 1000)")
                await asyncio.sleep(1.5)

            # Tìm tất cả thẻ <a> chứa đường dẫn bài viết trong nhóm
            links = await page.query_selector_all("a[href*='/posts/'], a[href*='permalink.php'], a[href*='multi_permalinks']")
            for a in links:
                href = await a.get_attribute("href")
                if href:
                    # Làm sạch URL Facebook
                    if href.startswith("/"):
                        href = f"https://www.facebook.com{href}"
                    # Cắt bỏ các tham số tracking ?__cft__...
                    clean_url = href.split("?")[0]
                    if "/posts/" in clean_url or "permalink.php" in clean_url:
                        if clean_url not in post_urls:
                            post_urls.append(clean_url)
                            if len(post_urls) >= limit:
                                break

            if logger_callback:
                logger_callback("INFO", f"Đã tìm thấy {len(post_urls)} bài viết trong nhóm.")

        except Exception as e:
            if logger_callback:
                logger_callback("WARNING", f"Lỗi khi quét bài viết nhóm: {str(e)}")

        return post_urls

    async def search_posts_by_keyword(
        self,
        page: Page,
        keyword: str,
        limit: int = 10,
        logger_callback: Optional[Callable[[str, str], None]] = None
    ) -> List[str]:
        """Tìm kiếm bài viết trên Facebook theo từ khóa và trích xuất link."""
        import urllib.parse
        post_urls = []
        try:
            encoded_kw = urllib.parse.quote(keyword)
            search_url = f"https://www.facebook.com/search/posts/?q={encoded_kw}"

            if logger_callback:
                logger_callback("INFO", f"Đang tìm kiếm bài viết theo từ khóa '{keyword}'...")

            await page.goto(search_url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(3.5)

            # Cuộn trang để tải thêm bài viết
            for _ in range(4):
                await page.evaluate("window.scrollBy(0, 1200)")
                await asyncio.sleep(1.8)

            links = await page.query_selector_all("a[href*='/posts/'], a[href*='permalink.php'], a[href*='/videos/'], a[href*='/reel/']")
            for a in links:
                href = await a.get_attribute("href")
                if href:
                    if href.startswith("/"):
                        href = f"https://www.facebook.com{href}"
                    clean_url = href.split("?")[0]
                    if clean_url not in post_urls:
                        post_urls.append(clean_url)
                        if len(post_urls) >= limit:
                            break

            if logger_callback:
                logger_callback("INFO", f"Đã tìm thấy {len(post_urls)} bài viết cho từ khóa '{keyword}'.")

        except Exception as e:
            if logger_callback:
                logger_callback("WARNING", f"Lỗi khi tìm bài viết theo từ khóa: {str(e)}")

        return post_urls
