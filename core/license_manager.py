import os
import re
import csv
import io
import uuid
import hashlib
import winreg
import subprocess
import ctypes
from datetime import datetime
from typing import Tuple, Dict, Any, Optional

# Link Cloudflare D1 Worker (Há»‡ thá»‘ng báº£n quyá»n siÃªu tá»‘c ~40ms káº¿t há»£p Web Admin)
# Äiá»n link Worker cá»§a báº¡n táº¡i Ä‘Ã¢y (VD: "https://tools-marketing-license.xxx.workers.dev")
DEFAULT_D1_WORKER_URL = "https://tools-marketing-license.mtools-platform.workers.dev"

# Link Google Sheet quáº£n lÃ½ danh sÃ¡ch Machine ID vÃ  Key kÃ­ch hoáº¡t (Dá»± phÃ²ng)
DEFAULT_SHEET_URL = ""

# Link Google Apps Script Web App (DÃ¹ng Ä‘á»ƒ tá»± Ä‘á»™ng Ä‘áº©y MÃ£ MÃ¡y vÃ  tá»± Ä‘á»™ng táº¡o Key - Dá»± phÃ²ng)
DEFAULT_WEB_APP_URL = ""

DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y %H:%M",
]

_CACHED_MACHINE_ID: Optional[str] = None

def get_windows_machine_guid() -> str:
    """Láº¥y MachineGuid cá»‘ Ä‘á»‹nh tá»« Windows Registry (khÃ´ng thay Ä‘á»•i trá»« khi cÃ i láº¡i Windows)."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        )
        val, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return str(val).strip()
    except Exception:
        return ""

def get_c_drive_volume_serial() -> str:
    """Láº¥y Serial Number cá»§a phÃ¢n vÃ¹ng á»• Ä‘Ä©a C:\\ qua Win32 API (tá»©c thÃ¬, khÃ´ng timeout)."""
    try:
        serial = ctypes.c_ulong()
        kernel32 = ctypes.windll.kernel32
        if kernel32.GetVolumeInformationW("C:\\", None, 0, ctypes.byref(serial), None, None, None, 0):
            return f"{serial.value:08X}"
    except Exception:
        pass
    return ""

def get_cpu_info() -> str:
    """Láº¥y thÃ´ng tin CPU cá»‘ Ä‘á»‹nh tá»« Registry (tá»©c thÃ¬, khÃ´ng dÃ¹ng powershell)."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            0,
            winreg.KEY_READ
        )
        val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        winreg.CloseKey(key)
        return str(val).strip()
    except Exception:
        return ""

def get_bios_info() -> str:
    """Láº¥y thÃ´ng tin BIOS/Mainboard tá»« Registry."""
    for prop in ("BaseBoardSerialNumber", "SystemSerialNumber", "BIOSVersion"):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\BIOS",
                0,
                winreg.KEY_READ
            )
            val, _ = winreg.QueryValueEx(key, prop)
            winreg.CloseKey(key)
            val_str = str(val).strip()
            if val_str and val_str.lower() not in ("none", "default string", "to be filled by o.e.m."):
                return val_str
        except Exception:
            pass
    return ""

def save_persistent_machine_id(machine_id: str, db=None):
    """
    LÆ°u trá»¯ Machine ID vÄ©nh viá»…n vÃ o 3 cáº¥p Ä‘á»™:
    1. SQLite Database
    2. Registry Windows HKCU\\Software\\AutoPost
    3. Tá»‡p tin báº£o máº­t trong %APPDATA%\\Auto Post\\.machine_id
    """
    if not machine_id or not machine_id.startswith("CWAI-"):
        return
    machine_id = machine_id.strip().upper()

    # 1. LÆ°u vÃ o Database
    try:
        if db is not None:
            db.set_setting("persistent_machine_id", machine_id)
        else:
            from core.database import Database
            Database().set_setting("persistent_machine_id", machine_id)
    except Exception:
        pass

    # 2. LÆ°u vÃ o Registry HKCU
    try:
        reg_key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            r"Software\AutoPost",
            0,
            winreg.KEY_WRITE
        )
        winreg.SetValueEx(reg_key, "MachineId", 0, winreg.REG_SZ, machine_id)
        winreg.CloseKey(reg_key)
    except Exception:
        pass

    # 3. LÆ°u vÃ o AppData file
    try:
        appdata = os.environ.get("APPDATA") or ""
        if appdata:
            dir_path = os.path.join(appdata, "Auto Post")
            os.makedirs(dir_path, exist_ok=True)
            with open(os.path.join(dir_path, ".machine_id"), "w", encoding="utf-8") as f:
                f.write(machine_id)
    except Exception:
        pass

def load_persistent_machine_id(db=None) -> Optional[str]:
    """
    Äá»c Machine ID Ä‘Ã£ lÆ°u trÆ°á»›c Ä‘Ã³ tá»« cÃ¡c nguá»“n lÆ°u trá»¯ cá»‘ Ä‘á»‹nh:
    1. DB license_hwid (giá»¯ nguyÃªn key Ä‘Ã£ kÃ­ch hoáº¡t thÃ nh cÃ´ng)
    2. DB persistent_machine_id
    3. Registry HKCU\\Software\\AutoPost
    4. Tá»‡p tin %APPDATA%\\Auto Post\\.machine_id
    """
    # 1. Kiá»ƒm tra SQLite DB
    try:
        target_db = db
        if target_db is None:
            from core.database import Database
            target_db = Database()
        
        # Náº¿u Ä‘Ã£ cÃ³ license_hwid há»£p lá»‡
        hwid = target_db.get_setting("license_hwid")
        if hwid and hwid.strip().startswith("CWAI-"):
            return hwid.strip().upper()
        
        # Hoáº·c persistent_machine_id Ä‘Ã£ lÆ°u
        pid = target_db.get_setting("persistent_machine_id")
        if pid and pid.strip().startswith("CWAI-"):
            return pid.strip().upper()
    except Exception:
        pass

    # 2. Kiá»ƒm tra Registry HKCU
    try:
        reg_key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\AutoPost",
            0,
            winreg.KEY_READ
        )
        val, _ = winreg.QueryValueEx(reg_key, "MachineId")
        winreg.CloseKey(reg_key)
        if val and str(val).strip().startswith("CWAI-"):
            return str(val).strip().upper()
    except Exception:
        pass

    # 3. Kiá»ƒm tra AppData file
    try:
        appdata = os.environ.get("APPDATA") or ""
        if appdata:
            path = os.path.join(appdata, "Auto Post", ".machine_id")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    val = f.read().strip()
                if val.startswith("CWAI-"):
                    return val.upper()
    except Exception:
        pass

    return None

def get_machine_id(db=None) -> str:
    """
    Sinh Machine ID duy nháº¥t, cá»‘ Ä‘á»‹nh 100% theo pháº§n cá»©ng mÃ¡y tÃ­nh ngÆ°á»i dÃ¹ng.
    Äá»‹nh dáº¡ng: CWAI-XXXX-XXXX-XXXX-XXXX
    - Tuyá»‡t Ä‘á»‘i khÃ´ng dÃ¹ng uuid.getnode() (bá»‹ Ä‘á»•i MAC khi cáº¯m rÃºt máº¡ng/wifi/VPN).
    - Tuyá»‡t Ä‘á»‘i khÃ´ng gá»i powershell/wmic timeout.
    - LÆ°u vÄ©nh viá»…n vÃ o DB, Registry, AppData ngay láº§n khá»Ÿi cháº¡y Ä‘áº§u tiÃªn.
    """
    global _CACHED_MACHINE_ID
    if _CACHED_MACHINE_ID:
        return _CACHED_MACHINE_ID

    # 1. Äá»c mÃ£ mÃ¡y Ä‘Ã£ lÆ°u tá»« trÆ°á»›c náº¿u cÃ³
    saved = load_persistent_machine_id(db)
    if saved:
        _CACHED_MACHINE_ID = saved
        save_persistent_machine_id(saved, db)
        return saved

    # 2. Náº¿u láº§n Ä‘áº§u tiÃªn cháº¡y mÃ¡y má»›i: trÃ­ch xuáº¥t cÃ¡c Ä‘áº·c trÆ°ng pháº§n cá»©ng báº¥t biáº¿n
    guid = get_windows_machine_guid()
    vol = get_c_drive_volume_serial()
    cpu = get_cpu_info()
    bios = get_bios_info()
    comp_name = os.environ.get("COMPUTERNAME", "")

    # Chuá»—i Ä‘á»‹nh danh pháº§n cá»©ng káº¿t há»£p
    raw_hw = f"{guid}|{vol}|{cpu}|{bios}|{comp_name}".strip().lower()
    sha = hashlib.sha256(raw_hw.encode("utf-8")).hexdigest().upper()
    formatted = f"CWAI-{sha[:4]}-{sha[4:8]}-{sha[8:12]}-{sha[12:16]}"

    _CACHED_MACHINE_ID = formatted
    save_persistent_machine_id(formatted, db)
    return formatted

def normalize_google_sheet_csv_url(url: str) -> str:
    """
    Chuyá»ƒn Ä‘á»•i URL xem / chá»‰nh sá»­a Google Sheet sang Ä‘á»‹nh dáº¡ng CSV Export trá»±c tiáº¿p.
    Há»— trá»£ má»i link Google Sheet chia sáº» (Báº¥t ká»³ ai cÃ³ liÃªn káº¿t Ä‘á»u cÃ³ thá»ƒ xem).
    """
    if not url:
        return ""
    url = url.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        return url
    
    sheet_id = match.group(1)
    gid_match = re.search(r"[#&?]gid=([0-9]+)", url)
    gid = gid_match.group(1) if gid_match else "0"
    
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={gid}"

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}

def parse_expiry_date(raw_expiry: str) -> Tuple[Optional[datetime], bool, str]:
    """
    PhÃ¢n tÃ­ch chuá»—i ngÃ y háº¿t háº¡n tá»« mÃ¡y chá»§ hoáº·c cache.
    Há»— trá»£ má»i Ä‘á»‹nh dáº¡ng: ISO (YYYY-MM-DD), Date string tiáº¿ng Anh (Sat Oct 31 2026...),
    Äá»‹nh dáº¡ng Viá»‡t Nam (DD/MM/YYYY), hoáº·c chuá»—i chá»©a 'Háº¡n: DD/MM/YYYY'.
    """
    if not raw_expiry:
        return None, False, "ChÆ°a thiáº¿t láº­p ngÃ y háº¿t háº¡n"
    
    raw_clean = str(raw_expiry).strip().upper()
    if any(k in raw_clean for k in ["LIFETIME", "VINH VIEN", "VÄ¨NH VIá»„N", "PERMANENT", "FOREVER", "UNLIMITED"]):
        return None, True, "VÄ©nh viá»…n (KhÃ´ng giá»›i háº¡n thá»i gian)"

    now = datetime.now()
    dt = None

    # 1. Nháº­n diá»‡n dáº¡ng chuá»—i ngÃ y tiáº¿ng Anh (Sat Oct 31 2026...)
    match_mon = re.search(r"([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})", str(raw_expiry))
    if match_mon:
        m_str, d_str, y_str = match_mon.groups()
        m_num = MONTH_MAP.get(m_str.lower())
        if m_num:
            try:
                dt = datetime(int(y_str), m_num, int(d_str), 23, 59, 59)
            except Exception:
                pass

    # 2. Nháº­n diá»‡n Ä‘á»‹nh dáº¡ng DD/MM/YYYY (bao gá»“m cáº£ chuá»—i chá»©a 'Háº¡n: DD/MM/YYYY')
    if not dt:
        match_dmy = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", str(raw_expiry))
        if match_dmy:
            d, m, y = match_dmy.groups()
            try:
                dt = datetime(int(y), int(m), int(d), 23, 59, 59)
            except Exception:
                pass

    # 3. Nháº­n diá»‡n Ä‘á»‹nh dáº¡ng ISO YYYY-MM-DD
    if not dt:
        match_ymd = re.search(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})", str(raw_expiry))
        if match_ymd:
            y, m, d = match_ymd.groups()
            try:
                dt = datetime(int(y), int(m), int(d), 23, 59, 59)
            except Exception:
                pass

    # 4. Fallback cÃ¡c Ä‘á»‹nh dáº¡ng strptime thÃ´ng thÆ°á»ng
    if not dt:
        for fmt in DATE_FORMATS:
            try:
                parsed = datetime.strptime(str(raw_expiry).strip(), fmt)
                if "%H" not in fmt:
                    parsed = parsed.replace(hour=23, minute=59, second=59)
                dt = parsed
                break
            except ValueError:
                continue

    if dt:
        is_valid = dt >= now
        date_str = dt.strftime("%d/%m/%Y")
        remaining_days = (dt - now).days
        if not is_valid or remaining_days < 0:
            return dt, False, f"ÄÃ£ háº¿t háº¡n vÃ o ngÃ y {date_str}"
        elif remaining_days == 0:
            return dt, True, f"Háº¿t háº¡n hÃ´m nay (Háº¡n: {date_str})"
        else:
            return dt, True, f"CÃ²n {remaining_days} ngÃ y (Háº¡n: {date_str})"

    return None, False, f"Äá»‹nh dáº¡ng ngÃ y khÃ´ng há»£p lá»‡: '{raw_expiry}'"


def auto_register_machine(web_app_url: str = None, machine_id: str = None, db=None) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Tá»± Ä‘á»™ng gá»­i Machine ID lÃªn mÃ¡y chá»§ (Cloudflare D1 Worker hoáº·c Google Sheet Web App):
    - Kiá»ƒm tra xem mÃ¡y Ä‘Ã£ Ä‘Æ°á»£c cáº¥p Key chÆ°a Ä‘á»ƒ tá»± Ä‘á»™ng náº¡p vá» mÃ¡y.
    """
    import requests
    if not machine_id:
        machine_id = get_machine_id(db)

    url = (web_app_url or (db.get_setting("license_d1_url") if db else "") or DEFAULT_D1_WORKER_URL or DEFAULT_WEB_APP_URL).strip()
    if not url:
        return False, "ChÆ°a cáº¥u hÃ¬nh Ä‘Æ°á»ng dáº«n mÃ¡y chá»§ báº£n quyá»n.", {}

    computer_name = os.environ.get("COMPUTERNAME", "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    }

    # 1. Há»– TRá»¢ CLOUDFLARE D1 WORKER (SiÃªu tá»‘c ~40ms)
    if "workers.dev" in url or "cloudflare" in url or "/api/" in url:
        endpoint = url.rstrip("/")
        if not endpoint.endswith("/api/auto-register") and not endpoint.endswith("/api/verify"):
            endpoint += "/api/auto-register"
        elif endpoint.endswith("/api/verify"):
            endpoint = endpoint.replace("/api/verify", "/api/auto-register")

        try:
            resp = requests.post(
                endpoint,
                json={"machine_id": machine_id, "computer_name": computer_name},
                headers={**headers, "Content-Type": "application/json"},
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                key = (data.get("license_key") or "").strip()
                exp_raw = (data.get("expiry_raw") or "").strip()
                exp_display = (data.get("expiry_display") or "").strip()
                status = (data.get("status") or "ACTIVE").strip()
                is_valid = bool(data.get("valid", False))
                msg = data.get("message", "ÄÃ£ káº¿t ná»‘i mÃ¡y chá»§ Cloudflare D1 thÃ nh cÃ´ng!")
                info = {
                    "machine_id": machine_id,
                    "license_key": key,
                    "expiry_raw": exp_raw,
                    "expiry_display": exp_display,
                    "status": status,
                    "note": data.get("customer_name", ""),
                    "is_valid": is_valid,
                    "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                return is_valid, msg, info
            else:
                return False, f"MÃ¡y chá»§ Cloudflare pháº£n há»“i mÃ£ lá»—i {resp.status_code}", {}
        except Exception as e:
            return False, f"Lá»—i káº¿t ná»‘i mÃ¡y chá»§ Cloudflare: {str(e)}", {}

    if "script.google.com" not in url:
        return False, "ÄÆ°á»ng dáº«n mÃ¡y chá»§ khÃ´ng há»£p lá»‡.", {}

    try:
        resp = requests.get(
            url,
            params={
                "action": "auto_register",
                "machine_id": machine_id,
                "computer_name": computer_name
            },
            headers=headers,
            timeout=15,
            allow_redirects=True
        )
        if resp.status_code == 200:
            data = resp.json()
            key = (data.get("license_key") or "").strip()
            exp_raw = (data.get("expiry_raw") or "").strip()
            exp_display = (data.get("expiry_display") or "").strip()
            status = (data.get("status") or "ACTIVE").strip()
            is_valid = bool(data.get("valid", False))
            msg = data.get("message", "ÄÃ£ káº¿t ná»‘i mÃ¡y chá»§ thÃ nh cÃ´ng!")
            if not is_valid and ("háº¿t háº¡n" in msg.lower() or "expired" in msg.lower() or "háº¿t háº¡n" in exp_display.lower()):
                status = "EXPIRED"

            info = {
                "machine_id": machine_id,
                "license_key": key,
                "expiry_raw": exp_raw,
                "expiry_display": exp_display,
                "status": status,
                "note": data.get("note", ""),
                "is_valid": is_valid,
                "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            return True, msg, info
        else:
            return False, f"Lá»—i pháº£n há»“i tá»« mÃ¡y chá»§ (HTTP {resp.status_code})", {}
    except Exception as e:
        return False, f"Lá»—i káº¿t ná»‘i khi tá»± Ä‘á»™ng Ä‘Äƒng kÃ½: {str(e)}", {}

def verify_license_online(sheet_url: str, machine_id: str, entered_key: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    XÃ¡c thá»±c báº£n quyá»n trá»±c tuyáº¿n:
    1. Æ¯u tiÃªn kiá»ƒm tra qua Cloudflare D1 Worker (náº¿u link lÃ  workers.dev hoáº·c Ä‘Ã£ cáº¥u hÃ¬nh D1).
    2. Fallback sang Google Apps Script Web App hoáº·c Google Sheet CSV.
    """
    import requests

    if not sheet_url:
        return False, "ChÆ°a cáº¥u hÃ¬nh liÃªn káº¿t mÃ¡y chá»§ báº£n quyá»n.", {}
    
    if not machine_id:
        return False, "KhÃ´ng thá»ƒ xÃ¡c Ä‘á»‹nh MÃ£ MÃ¡y (Machine ID).", {}
        
    if not entered_key:
        return False, "Vui lÃ²ng nháº­p Key kÃ­ch hoáº¡t báº£n quyá»n.", {}

    curr_mid = machine_id.strip().upper()
    curr_key = entered_key.strip().upper()

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
        }

        # -------------------------------------------------------------
        # 1. XÃC THá»°C QUA CLOUDFLARE D1 WORKER (Tá»‘c Ä‘á»™ ~40ms)
        # -------------------------------------------------------------
        if "workers.dev" in sheet_url or "cloudflare" in sheet_url or "/api/" in sheet_url:
            verify_endpoint = sheet_url.rstrip("/")
            if not verify_endpoint.endswith("/api/verify"):
                if verify_endpoint.endswith("/api/auto-register"):
                    verify_endpoint = verify_endpoint.replace("/api/auto-register", "/api/verify")
                else:
                    verify_endpoint += "/api/verify"

            resp = requests.post(
                verify_endpoint,
                json={"machine_id": curr_mid, "license_key": curr_key},
                headers={**headers, "Content-Type": "application/json"},
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                is_valid = bool(data.get("valid", False))
                msg = data.get("message", "")
                status = (data.get("status") or ("ACTIVE" if is_valid else "EXPIRED")).strip().upper()
                exp_raw = str(data.get("expiry_raw") or "")
                exp_disp = str(data.get("expiry_display") or "")
                info = {
                    "machine_id": curr_mid,
                    "license_key": curr_key,
                    "status": status,
                    "expiry_raw": exp_raw,
                    "expiry_display": exp_disp,
                    "note": data.get("customer_name", "") or data.get("note", ""),
                    "is_valid": is_valid,
                    "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                if is_valid:
                    return True, msg or f"KÃ­ch hoáº¡t thÃ nh cÃ´ng! Háº¡n dÃ¹ng: {exp_disp}", info
                else:
                    return False, msg or "Báº£n quyá»n khÃ´ng há»£p lá»‡ hoáº·c Ä‘Ã£ háº¿t háº¡n.", info
            else:
                try:
                    err_json = resp.json()
                    return False, err_json.get("message") or err_json.get("error") or f"Lá»—i mÃ¡y chá»§ (HTTP {resp.status_code})", {}
                except Exception:
                    return False, f"Lá»—i pháº£n há»“i tá»« mÃ¡y chá»§ Cloudflare D1 (HTTP {resp.status_code})", {}

        # -------------------------------------------------------------
        # 2. XÃC THá»°C QUA GOOGLE APPS SCRIPT WEB APP (Dá»± phÃ²ng)
        # -------------------------------------------------------------
        if "script.google.com" in sheet_url:
            resp = requests.get(
                sheet_url,
                params={"action": "check", "machine_id": curr_mid, "key": curr_key},
                headers=headers,
                timeout=12,
                allow_redirects=True
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    is_valid = bool(data.get("valid", False))
                    msg = data.get("message", "")
                    status = (data.get("status") or ("ACTIVE" if is_valid else "EXPIRED")).strip().upper()
                    exp_raw = str(data.get("expiry_raw") or "")
                    exp_disp = str(data.get("expiry_display") or "")
                    info = {
                        "machine_id": curr_mid,
                        "license_key": curr_key,
                        "status": status,
                        "expiry_raw": exp_raw,
                        "expiry_display": exp_disp,
                        "note": data.get("note", ""),
                        "is_valid": is_valid,
                        "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    if is_valid:
                        return True, msg or f"KÃ­ch hoáº¡t thÃ nh cÃ´ng! Háº¡n dÃ¹ng: {info['expiry_display']}", info
                    else:
                        return False, msg or "Báº£n quyá»n khÃ´ng há»£p lá»‡ hoáº·c Ä‘Ã£ háº¿t háº¡n.", info
                except Exception as e:
                    return False, f"Lá»—i Ä‘á»c dá»¯ liá»‡u tá»« mÃ¡y chá»§: {e}", {}

        # NgÆ°á»£c láº¡i, Ä‘á»c trá»±c tiáº¿p tá»« Google Sheet qua CSV export
        csv_url = normalize_google_sheet_csv_url(sheet_url)
        resp = requests.get(csv_url, headers=headers, timeout=12)
        
        # Náº¿u link gviz khÃ´ng táº£i Ä‘Æ°á»£c hoáº·c rá»—ng, thá»­ link export CSV truyá»n thá»‘ng
        if resp.status_code != 200 or len(resp.content.strip()) == 0:
            match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
            if match:
                alt_url = f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv"
                resp_alt = requests.get(alt_url, headers=headers, timeout=12)
                if resp_alt.status_code == 200 and len(resp_alt.content.strip()) > 0:
                    resp = resp_alt

        if resp.status_code != 200:
            return False, f"KhÃ´ng thá»ƒ táº£i dá»¯ liá»‡u tá»« mÃ¡y chá»§ (MÃ£ HTTP: {resp.status_code}).", {}

        content = resp.content.decode("utf-8-sig", errors="ignore").strip()
        if not content:
            return False, "Há»‡ thá»‘ng báº£n quyá»n hiá»‡n chÆ°a cÃ³ dá»¯ liá»‡u.", {}

        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames:
            return False, "Dá»¯ liá»‡u báº£n quyá»n rá»—ng hoáº·c khÃ´ng Ä‘Ãºng Ä‘á»‹nh dáº¡ng.", {}

        # Chuáº©n hÃ³a tÃªn cá»™t Ä‘á»ƒ há»— trá»£ cáº£ tiáº¿ng Anh láº«n tiáº¿ng Viá»‡t
        field_map = {}
        for f in reader.fieldnames:
            norm = f.strip().lower().replace(" ", "_")
            if norm in ("machine_id", "machineid", "hwid", "ma_may", "mÃ£_mÃ¡y", "id"):
                field_map["machine_id"] = f
            elif norm in ("license_key", "licensekey", "key", "ma_key", "mÃ£_key", "ma_kich_hoat", "mÃ£_kÃ­ch_hoáº¡t"):
                field_map["license_key"] = f
            elif norm in ("expiry_date", "expiry", "expire", "han_dung", "háº¡n_dÃ¹ng", "ngay_het_han", "ngÃ y_háº¿t_háº¡n"):
                field_map["expiry_date"] = f
            elif norm in ("status", "trang_thai", "tráº¡ng_thÃ¡i"):
                field_map["status"] = f
            elif norm in ("note", "ghi_chu", "ghi_chÃº", "khach_hang", "khÃ¡ch_hÃ ng"):
                field_map["note"] = f

        if "machine_id" not in field_map or "license_key" not in field_map:
            return False, "Dá»¯ liá»‡u thiáº¿u cá»™t 'Machine_ID' hoáº·c 'License_Key'.", {}

        curr_mid = machine_id.strip().upper()
        curr_key = entered_key.strip().upper()

        matched_row = None
        for row in reader:
            row_mid = (row.get(field_map["machine_id"]) or "").strip().upper()
            row_key = (row.get(field_map["license_key"]) or "").strip().upper()
            
            if row_mid == curr_mid and row_key == curr_key:
                matched_row = row
                break

        if not matched_row:
            return False, "MÃ£ MÃ¡y hoáº·c Key kÃ­ch hoáº¡t khÃ´ng chÃ­nh xÃ¡c trÃªn há»‡ thá»‘ng. Vui lÃ²ng kiá»ƒm tra láº¡i hoáº·c liÃªn há»‡ quáº£n trá»‹ viÃªn.", {}

        # Kiá»ƒm tra tráº¡ng thÃ¡i Status
        status_col = field_map.get("status")
        status_val = (matched_row.get(status_col) or "ACTIVE").strip().upper() if status_col else "ACTIVE"
        
        if status_val not in ("ACTIVE", "HOáº T Äá»˜NG", "HOAT DONG", "OK", "ENABLED", "TRUE", "1"):
            info = {
                "machine_id": curr_mid,
                "license_key": curr_key,
                "status": status_val,
                "expiry_raw": "",
                "expiry_display": f"Bá»‹ khÃ³a [{status_val}]",
                "note": "",
                "is_valid": False,
                "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            return False, f"Key kÃ­ch hoáº¡t Ä‘ang á»Ÿ tráº¡ng thÃ¡i khÃ³a hoáº·c táº¡m ngÆ°ng [{status_val}]. Vui lÃ²ng liÃªn há»‡ quáº£n trá»‹ viÃªn.", info

        # Kiá»ƒm tra thá»i háº¡n Expiry_Date
        expiry_col = field_map.get("expiry_date")
        expiry_val = (matched_row.get(expiry_col) or "LIFETIME").strip() if expiry_col else "LIFETIME"
        dt, is_valid, expiry_msg = parse_expiry_date(expiry_val)

        note_col = field_map.get("note")
        note_val = (matched_row.get(note_col) or "").strip() if note_col else ""

        license_info = {
            "machine_id": curr_mid,
            "license_key": curr_key,
            "status": "ACTIVE" if is_valid else "EXPIRED",
            "expiry_raw": expiry_val,
            "expiry_display": expiry_msg,
            "note": note_val,
            "is_valid": is_valid,
            "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        if not is_valid:
            return False, f"Key kÃ­ch hoáº¡t Ä‘Ã£ háº¿t háº¡n! Chi tiáº¿t: {expiry_msg}", license_info

        return True, f"KÃ­ch hoáº¡t thÃ nh cÃ´ng! Háº¡n dÃ¹ng: {expiry_msg}", license_info

    except requests.exceptions.RequestException as e:
        return False, f"Lá»—i káº¿t ná»‘i máº¡ng khi kiá»ƒm tra Google Sheet: {str(e)}", {}
    except Exception as e:
        return False, f"Lá»—i kiá»ƒm tra báº£n quyá»n: {str(e)}", {}

def save_cached_license(db, license_info: Dict[str, Any]):
    """LÆ°u trá»¯ thÃ´ng tin báº£n quyá»n Ä‘Ã£ kÃ­ch hoáº¡t vÃ o SQLite Ä‘á»ƒ khá»Ÿi Ä‘á»™ng nhanh."""
    try:
        raw_exp = str(license_info.get("expiry_raw", ""))
        dt, is_valid, msg = parse_expiry_date(raw_exp)
        if dt:
            clean_raw = dt.strftime("%Y-%m-%d")
        else:
            clean_raw = raw_exp

        disp = license_info.get("expiry_display", "")
        if not disp and msg:
            disp = msg

        db.set_setting("license_hwid", license_info.get("machine_id", ""))
        db.set_setting("license_key", license_info.get("license_key", ""))
        db.set_setting("license_expiry_raw", clean_raw)
        db.set_setting("license_expiry_display", disp)
        db.set_setting("license_status", license_info.get("status", "ACTIVE"))
        db.set_setting("license_note", license_info.get("note", ""))
        db.set_setting("license_verified_at", license_info.get("verified_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    except Exception as e:
        print(f"[ERROR] KhÃ´ng thá»ƒ lÆ°u cache báº£n quyá»n: {e}")

def get_cached_license(db) -> Optional[Dict[str, Any]]:
    """Äá»c thÃ´ng tin báº£n quyá»n Ä‘Ã£ lÆ°u tá»« SQLite."""
    try:
        hwid = db.get_setting("license_hwid")
        key = db.get_setting("license_key")
        if not hwid or not key:
            return None
        
        return {
            "machine_id": hwid,
            "license_key": key,
            "expiry_raw": db.get_setting("license_expiry_raw", ""),
            "expiry_display": db.get_setting("license_expiry_display", ""),
            "status": db.get_setting("license_status", "UNKNOWN"),
            "note": db.get_setting("license_note", ""),
            "verified_at": db.get_setting("license_verified_at", "")
        }
    except Exception:
        return None

def clear_cached_license(db):
    """XÃ³a bá» báº£n quyá»n Ä‘Ã£ lÆ°u khi key bá»‹ thu há»“i hoáº·c Ä‘á»•i key má»›i."""
    try:
        db.set_setting("license_hwid", "")
        db.set_setting("license_key", "")
        db.set_setting("license_expiry_raw", "")
        db.set_setting("license_expiry_display", "")
        db.set_setting("license_status", "REVOKED")
    except Exception:
        pass

def validate_license(db, timeout_online: int = 6) -> Tuple[bool, str, Dict[str, Any]]:
    """
    HÃ m kiá»ƒm tra báº£n quyá»n toÃ n diá»‡n khi khá»Ÿi Ä‘á»™ng á»©ng dá»¥ng:
    - CHá»ˆ VÃ€O ÄÆ¯á»¢C KHI ÄÃƒ XÃC MINH KEY THÃ€NH CÃ”NG VÃ€ CÃ’N Háº N Sá»¬ Dá»¤NG.
    - LuÃ´n kiá»ƒm tra trá»±c tuyáº¿n vá»›i mÃ¡y chá»§ Ä‘á»ƒ cáº­p nháº­t tráº¡ng thÃ¡i má»›i nháº¥t.
    - Náº¿u mÃ¡y chá»§ pháº£n há»“i (háº¿t háº¡n, bá»‹ khÃ³a, hoáº·c khÃ´ng há»£p lá»‡):
      -> Láº­p tá»©c cáº­p nháº­t tráº¡ng thÃ¡i trong database vÃ  CHáº¶N, KHÃ”NG cho vÃ o.
    - Chá»‰ khi lá»—i máº¡ng (khÃ´ng thá»ƒ káº¿t ná»‘i tá»›i mÃ¡y chá»§) má»›i dÃ¹ng bá»™ nhá»› Ä‘á»‡m cá»¥c bá»™,
      vÃ  cá»¥c bá»™ cÅ©ng Báº®T BUá»˜C pháº£i cÃ²n háº¡n vÃ  á»Ÿ tráº¡ng thÃ¡i ACTIVE.
    """
    current_mid = get_machine_id(db)
    # Æ¯u tiÃªn: Cloudflare D1 Worker -> Google Apps Script Web App -> Google Sheet CSV
    target_url = (
        db.get_setting("license_d1_url")
        or DEFAULT_D1_WORKER_URL
        or db.get_setting("license_web_app_url")
        or DEFAULT_WEB_APP_URL
        or db.get_setting("license_sheet_url")
        or DEFAULT_SHEET_URL
    )
    cached = get_cached_license(db)

    # 1. Náº¿u chÆ°a tá»«ng kÃ­ch hoáº¡t báº¥t ká»³ key nÃ o
    if not cached:
        return False, "ChÆ°a kÃ­ch hoáº¡t báº£n quyá»n. Vui lÃ²ng nháº­p Key Ä‘á»ƒ sá»­ dá»¥ng.", {"machine_id": current_mid}

    # 2. Kiá»ƒm tra mÃ£ mÃ¡y lÆ°u trong DB cÃ³ khá»›p vá»›i mÃ¡y váº­t lÃ½ hiá»‡n táº¡i khÃ´ng
    if cached.get("machine_id") != current_mid:
        return False, "MÃ£ MÃ¡y khÃ´ng trÃ¹ng khá»›p vá»›i báº£n quyá»n Ä‘Ã£ Ä‘Äƒng kÃ½ trÆ°á»›c Ä‘Ã³.", {"machine_id": current_mid}

    # 3. Kiá»ƒm tra tráº¡ng thÃ¡i Ä‘Ã£ lÆ°u: náº¿u Ä‘Ã£ bá»‹ KHÃ“A hoáº·c Háº¾T Háº N cá»¥c bá»™
    cached_status = (cached.get("status") or "").upper()
    if cached_status in ("BLOCKED", "KHÃ“A", "Táº M KHÃ“A", "REVOKED"):
        return False, "Báº£n quyá»n thiáº¿t bá»‹ nÃ y Ä‘ang bá»‹ khÃ³a bá»Ÿi Quáº£n trá»‹ viÃªn.", cached
    
    # Kiá»ƒm tra ngÃ y háº¿t háº¡n cá»¥c bá»™ trÆ°á»›c
    expiry_raw = cached.get("expiry_raw", "")
    _, is_local_date_valid, local_expiry_msg = parse_expiry_date(expiry_raw)
    if not is_local_date_valid:
        db.set_setting("license_status", "EXPIRED")
        cached["status"] = "EXPIRED"
        cached["expiry_display"] = local_expiry_msg
        return False, f"Báº£n quyá»n Ä‘Ã£ háº¿t háº¡n! {local_expiry_msg}", cached

    # 4. Thá»­ Ä‘á»“ng bá»™ trá»±c tuyáº¿n vá»›i mÃ¡y chá»§ thá»i gian thá»±c
    try:
        ok, msg, online_info = verify_license_online(target_url, current_mid, cached.get("license_key", ""))
        
        # Náº¾U MÃY CHá»¦ PHáº¢N Há»’I THÃ€NH CÃ”NG
        # TH1: Key há»£p lá»‡ vÃ  cÃ²n háº¡n
        if ok and online_info.get("is_valid") is True:
            status = (online_info.get("status") or "ACTIVE").strip().upper()
            if status not in ("ACTIVE", "HOáº T Äá»˜NG", "OK"):
                db.set_setting("license_status", "BLOCKED")
                cached["status"] = "BLOCKED"
                return False, f"Báº£n quyá»n Ä‘ang á»Ÿ tráº¡ng thÃ¡i khÃ³a [{status}].", cached
            
            save_cached_license(db, online_info)
            return True, msg, online_info

        # TH2: MÃ¡y chá»§ pháº£n há»“i nhÆ°ng BÃO KHÃ”NG Há»¢P Lá»† (Háº¿t háº¡n, Bá»‹ khÃ³a, Sai key, v.v.)
        # ÄÃ¢y lÃ  pháº£n há»“i chÃ­nh thá»©c tá»« mÃ¡y chá»§, KHÃ”NG ÄÆ¯á»¢C fallback vá» cache cÅ©!
        server_status = (online_info.get("status") or "").upper()
        if "háº¿t háº¡n" in msg.lower() or "expired" in msg.lower() or server_status == "EXPIRED" or not online_info.get("is_valid", True):
            # Náº¿u háº¿t háº¡n
            if "háº¿t háº¡n" in msg.lower() or "expired" in msg.lower() or server_status == "EXPIRED":
                db.set_setting("license_status", "EXPIRED")
                if online_info.get("expiry_raw"):
                    db.set_setting("license_expiry_raw", online_info.get("expiry_raw"))
                if online_info.get("expiry_display"):
                    db.set_setting("license_expiry_display", online_info.get("expiry_display"))
                cached["status"] = "EXPIRED"
                if online_info.get("expiry_display"):
                    cached["expiry_display"] = online_info.get("expiry_display")
                return False, msg or "Báº£n quyá»n Ä‘Ã£ háº¿t háº¡n sá»­ dá»¥ng. Vui lÃ²ng liÃªn há»‡ Quáº£n trá»‹ viÃªn Ä‘á»ƒ gia háº¡n.", cached

            # Náº¿u bá»‹ khÃ³a
            if "khÃ³a" in msg.lower() or "blocked" in msg.lower() or server_status in ("BLOCKED", "KHÃ“A", "Táº M KHÃ“A", "REVOKED"):
                db.set_setting("license_status", "BLOCKED")
                cached["status"] = "BLOCKED"
                return False, msg or "Báº£n quyá»n thiáº¿t bá»‹ nÃ y Ä‘ang bá»‹ khÃ³a bá»Ÿi Quáº£n trá»‹ viÃªn.", cached

            # Náº¿u mÃ¡y chá»§ bÃ¡o lá»—i khÃ¡c (Key khÃ´ng chÃ­nh xÃ¡c, v.v.)
            db.set_setting("license_status", "INVALID")
            cached["status"] = "INVALID"
            return False, msg, cached

        # TH3: Náº¿u chá»‰ lÃ  máº¥t káº¿t ná»‘i máº¡ng táº¡m thá»i
        cached["expiry_display"] = local_expiry_msg
        return True, f"Báº£n quyá»n há»£p lá»‡: {local_expiry_msg}", cached

    except Exception:
        # Lá»—i máº¡ng ngoáº¡i lá»‡ -> ÄÃ£ kiá»ƒm tra is_local_date_valid á»Ÿ trÃªn rá»“i
        cached["expiry_display"] = local_expiry_msg
        return True, f"Báº£n quyá»n há»£p lá»‡ (Ngoáº¡i tuyáº¿n): {local_expiry_msg}", cached

