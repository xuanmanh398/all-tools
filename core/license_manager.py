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

# Link Google Sheet quản lý danh sách Machine ID và Key kích hoạt
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1ZI6E1MnQHLIbzaDtdPLEszIxOZzFNqbh8l_Cx9718II/edit?usp=sharing"

# Link Google Apps Script Web App (Dùng để tự động đẩy Mã Máy và tự động tạo Key)
DEFAULT_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbyoxT3GbOiDz-0P8o3SDfCdI7gDQPIcvERiZy3bVYkVo_frbtb87zp-VhUf0EaY7Grmfg/exec"

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
    """Lấy MachineGuid cố định từ Windows Registry (không thay đổi trừ khi cài lại Windows)."""
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
    """Lấy Serial Number của phân vùng ổ đĩa C:\\ qua Win32 API (tức thì, không timeout)."""
    try:
        serial = ctypes.c_ulong()
        kernel32 = ctypes.windll.kernel32
        if kernel32.GetVolumeInformationW("C:\\", None, 0, ctypes.byref(serial), None, None, None, 0):
            return f"{serial.value:08X}"
    except Exception:
        pass
    return ""

def get_cpu_info() -> str:
    """Lấy thông tin CPU cố định từ Registry (tức thì, không dùng powershell)."""
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
    """Lấy thông tin BIOS/Mainboard từ Registry."""
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
    Lưu trữ Machine ID vĩnh viễn vào 3 cấp độ:
    1. SQLite Database
    2. Registry Windows HKCU\\Software\\AutoPost
    3. Tệp tin bảo mật trong %APPDATA%\\Auto Post\\.machine_id
    """
    if not machine_id or not machine_id.startswith("CWAI-"):
        return
    machine_id = machine_id.strip().upper()

    # 1. Lưu vào Database
    try:
        if db is not None:
            db.set_setting("persistent_machine_id", machine_id)
        else:
            from core.database import Database
            Database().set_setting("persistent_machine_id", machine_id)
    except Exception:
        pass

    # 2. Lưu vào Registry HKCU
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

    # 3. Lưu vào AppData file
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
    Đọc Machine ID đã lưu trước đó từ các nguồn lưu trữ cố định:
    1. DB license_hwid (giữ nguyên key đã kích hoạt thành công)
    2. DB persistent_machine_id
    3. Registry HKCU\\Software\\AutoPost
    4. Tệp tin %APPDATA%\\Auto Post\\.machine_id
    """
    # 1. Kiểm tra SQLite DB
    try:
        target_db = db
        if target_db is None:
            from core.database import Database
            target_db = Database()
        
        # Nếu đã có license_hwid hợp lệ
        hwid = target_db.get_setting("license_hwid")
        if hwid and hwid.strip().startswith("CWAI-"):
            return hwid.strip().upper()
        
        # Hoặc persistent_machine_id đã lưu
        pid = target_db.get_setting("persistent_machine_id")
        if pid and pid.strip().startswith("CWAI-"):
            return pid.strip().upper()
    except Exception:
        pass

    # 2. Kiểm tra Registry HKCU
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

    # 3. Kiểm tra AppData file
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
    Sinh Machine ID duy nhất, cố định 100% theo phần cứng máy tính người dùng.
    Định dạng: CWAI-XXXX-XXXX-XXXX-XXXX
    - Tuyệt đối không dùng uuid.getnode() (bị đổi MAC khi cắm rút mạng/wifi/VPN).
    - Tuyệt đối không gọi powershell/wmic timeout.
    - Lưu vĩnh viễn vào DB, Registry, AppData ngay lần khởi chạy đầu tiên.
    """
    global _CACHED_MACHINE_ID
    if _CACHED_MACHINE_ID:
        return _CACHED_MACHINE_ID

    # 1. Đọc mã máy đã lưu từ trước nếu có
    saved = load_persistent_machine_id(db)
    if saved:
        _CACHED_MACHINE_ID = saved
        save_persistent_machine_id(saved, db)
        return saved

    # 2. Nếu lần đầu tiên chạy máy mới: trích xuất các đặc trưng phần cứng bất biến
    guid = get_windows_machine_guid()
    vol = get_c_drive_volume_serial()
    cpu = get_cpu_info()
    bios = get_bios_info()
    comp_name = os.environ.get("COMPUTERNAME", "")

    # Chuỗi định danh phần cứng kết hợp
    raw_hw = f"{guid}|{vol}|{cpu}|{bios}|{comp_name}".strip().lower()
    sha = hashlib.sha256(raw_hw.encode("utf-8")).hexdigest().upper()
    formatted = f"CWAI-{sha[:4]}-{sha[4:8]}-{sha[8:12]}-{sha[12:16]}"

    _CACHED_MACHINE_ID = formatted
    save_persistent_machine_id(formatted, db)
    return formatted

def normalize_google_sheet_csv_url(url: str) -> str:
    """
    Chuyển đổi URL xem / chỉnh sửa Google Sheet sang định dạng CSV Export trực tiếp.
    Hỗ trợ mọi link Google Sheet chia sẻ (Bất kỳ ai có liên kết đều có thể xem).
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
    Phân tích chuỗi ngày hết hạn từ máy chủ hoặc cache.
    Hỗ trợ mọi định dạng: ISO (YYYY-MM-DD), Date string tiếng Anh (Sat Oct 31 2026...),
    Định dạng Việt Nam (DD/MM/YYYY), hoặc chuỗi chứa 'Hạn: DD/MM/YYYY'.
    """
    if not raw_expiry:
        return None, False, "Chưa thiết lập ngày hết hạn"
    
    raw_clean = str(raw_expiry).strip().upper()
    if any(k in raw_clean for k in ["LIFETIME", "VINH VIEN", "VĨNH VIỄN", "PERMANENT", "FOREVER", "UNLIMITED"]):
        return None, True, "Vĩnh viễn (Không giới hạn thời gian)"

    now = datetime.now()
    dt = None

    # 1. Nhận diện dạng chuỗi ngày tiếng Anh (Sat Oct 31 2026...)
    match_mon = re.search(r"([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})", str(raw_expiry))
    if match_mon:
        m_str, d_str, y_str = match_mon.groups()
        m_num = MONTH_MAP.get(m_str.lower())
        if m_num:
            try:
                dt = datetime(int(y_str), m_num, int(d_str), 23, 59, 59)
            except Exception:
                pass

    # 2. Nhận diện định dạng DD/MM/YYYY (bao gồm cả chuỗi chứa 'Hạn: DD/MM/YYYY')
    if not dt:
        match_dmy = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", str(raw_expiry))
        if match_dmy:
            d, m, y = match_dmy.groups()
            try:
                dt = datetime(int(y), int(m), int(d), 23, 59, 59)
            except Exception:
                pass

    # 3. Nhận diện định dạng ISO YYYY-MM-DD
    if not dt:
        match_ymd = re.search(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})", str(raw_expiry))
        if match_ymd:
            y, m, d = match_ymd.groups()
            try:
                dt = datetime(int(y), int(m), int(d), 23, 59, 59)
            except Exception:
                pass

    # 4. Fallback các định dạng strptime thông thường
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
            return dt, False, f"Đã hết hạn vào ngày {date_str}"
        elif remaining_days == 0:
            return dt, True, f"Hết hạn hôm nay (Hạn: {date_str})"
        else:
            return dt, True, f"Còn {remaining_days} ngày (Hạn: {date_str})"

    return None, False, f"Định dạng ngày không hợp lệ: '{raw_expiry}'"


def auto_register_machine(web_app_url: str = None, machine_id: str = None, db=None) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Tự động gửi Machine ID lên Google Sheet qua Apps Script Web App:
    - Nếu máy chưa có trên Sheet -> Tự động ghi vào Sheet và tự động sinh Key mới.
    - Nếu máy đã có trên Sheet -> Lấy Key và thời hạn hiện tại về.
    Admin chỉ cần mở Google Sheet và sửa cột Expiry_Date (thời hạn)!
    """
    import requests
    if not machine_id:
        machine_id = get_machine_id(db)

    url = (web_app_url or DEFAULT_WEB_APP_URL).strip()
    if not url or "script.google.com" not in url:
        return False, "Cần dán link Web App (Google Apps Script) để tự động đẩy mã máy.", {}

    computer_name = os.environ.get("COMPUTERNAME", "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    }

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
            msg = data.get("message", "Đã kết nối máy chủ thành công!")
            if not is_valid and ("hết hạn" in msg.lower() or "expired" in msg.lower() or "hết hạn" in exp_display.lower()):
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
            return False, f"Lỗi phản hồi từ máy chủ (HTTP {resp.status_code})", {}
    except Exception as e:
        return False, f"Lỗi kết nối khi tự động đăng ký: {str(e)}", {}

def verify_license_online(sheet_url: str, machine_id: str, entered_key: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Tải danh sách bản quyền từ Google Sheet và kiểm tra:
    - Machine_ID có khớp với máy không
    - License_Key có khớp không
    - Status có ở trạng thái ACTIVE không
    - Expiry_Date còn hạn sử dụng không
    """
    import requests

    if not sheet_url:
        return False, "Chưa cấu hình liên kết Google Sheet quản lý bản quyền.", {}
    
    if not machine_id:
        return False, "Không thể xác định Mã Máy (Machine ID).", {}
        
    if not entered_key:
        return False, "Vui lòng nhập Key kích hoạt bản quyền.", {}

    curr_mid = machine_id.strip().upper()
    curr_key = entered_key.strip().upper()

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
        }

        # Nếu là link Apps Script Web App (script.google.com)
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
                        return True, msg or f"Kích hoạt thành công! Hạn dùng: {info['expiry_display']}", info
                    else:
                        return False, msg or "Bản quyền không hợp lệ hoặc đã hết hạn.", info
                except Exception as e:
                    return False, f"Lỗi đọc dữ liệu từ máy chủ: {e}", {}

        # Ngược lại, đọc trực tiếp từ Google Sheet qua CSV export
        csv_url = normalize_google_sheet_csv_url(sheet_url)
        resp = requests.get(csv_url, headers=headers, timeout=12)
        
        # Nếu link gviz không tải được hoặc rỗng, thử link export CSV truyền thống
        if resp.status_code != 200 or len(resp.content.strip()) == 0:
            match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
            if match:
                alt_url = f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv"
                resp_alt = requests.get(alt_url, headers=headers, timeout=12)
                if resp_alt.status_code == 200 and len(resp_alt.content.strip()) > 0:
                    resp = resp_alt

        if resp.status_code != 200:
            return False, f"Không thể tải dữ liệu từ máy chủ (Mã HTTP: {resp.status_code}).", {}

        content = resp.content.decode("utf-8-sig", errors="ignore").strip()
        if not content:
            return False, "Hệ thống bản quyền hiện chưa có dữ liệu.", {}

        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames:
            return False, "Dữ liệu bản quyền rỗng hoặc không đúng định dạng.", {}

        # Chuẩn hóa tên cột để hỗ trợ cả tiếng Anh lẫn tiếng Việt
        field_map = {}
        for f in reader.fieldnames:
            norm = f.strip().lower().replace(" ", "_")
            if norm in ("machine_id", "machineid", "hwid", "ma_may", "mã_máy", "id"):
                field_map["machine_id"] = f
            elif norm in ("license_key", "licensekey", "key", "ma_key", "mã_key", "ma_kich_hoat", "mã_kích_hoạt"):
                field_map["license_key"] = f
            elif norm in ("expiry_date", "expiry", "expire", "han_dung", "hạn_dùng", "ngay_het_han", "ngày_hết_hạn"):
                field_map["expiry_date"] = f
            elif norm in ("status", "trang_thai", "trạng_thái"):
                field_map["status"] = f
            elif norm in ("note", "ghi_chu", "ghi_chú", "khach_hang", "khách_hàng"):
                field_map["note"] = f

        if "machine_id" not in field_map or "license_key" not in field_map:
            return False, "Dữ liệu thiếu cột 'Machine_ID' hoặc 'License_Key'.", {}

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
            return False, "Mã Máy hoặc Key kích hoạt không chính xác trên hệ thống. Vui lòng kiểm tra lại hoặc liên hệ quản trị viên.", {}

        # Kiểm tra trạng thái Status
        status_col = field_map.get("status")
        status_val = (matched_row.get(status_col) or "ACTIVE").strip().upper() if status_col else "ACTIVE"
        
        if status_val not in ("ACTIVE", "HOẠT ĐỘNG", "HOAT DONG", "OK", "ENABLED", "TRUE", "1"):
            info = {
                "machine_id": curr_mid,
                "license_key": curr_key,
                "status": status_val,
                "expiry_raw": "",
                "expiry_display": f"Bị khóa [{status_val}]",
                "note": "",
                "is_valid": False,
                "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            return False, f"Key kích hoạt đang ở trạng thái khóa hoặc tạm ngưng [{status_val}]. Vui lòng liên hệ quản trị viên.", info

        # Kiểm tra thời hạn Expiry_Date
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
            return False, f"Key kích hoạt đã hết hạn! Chi tiết: {expiry_msg}", license_info

        return True, f"Kích hoạt thành công! Hạn dùng: {expiry_msg}", license_info

    except requests.exceptions.RequestException as e:
        return False, f"Lỗi kết nối mạng khi kiểm tra Google Sheet: {str(e)}", {}
    except Exception as e:
        return False, f"Lỗi kiểm tra bản quyền: {str(e)}", {}

def save_cached_license(db, license_info: Dict[str, Any]):
    """Lưu trữ thông tin bản quyền đã kích hoạt vào SQLite để khởi động nhanh."""
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
        print(f"[ERROR] Không thể lưu cache bản quyền: {e}")

def get_cached_license(db) -> Optional[Dict[str, Any]]:
    """Đọc thông tin bản quyền đã lưu từ SQLite."""
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
    """Xóa bỏ bản quyền đã lưu khi key bị thu hồi hoặc đổi key mới."""
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
    Hàm kiểm tra bản quyền toàn diện khi khởi động ứng dụng:
    - CHỈ VÀO ĐƯỢC KHI ĐÃ XÁC MINH KEY THÀNH CÔNG VÀ CÒN HẠN SỬ DỤNG.
    - Luôn kiểm tra trực tuyến với máy chủ để cập nhật trạng thái mới nhất.
    - Nếu máy chủ phản hồi (hết hạn, bị khóa, hoặc không hợp lệ):
      -> Lập tức cập nhật trạng thái trong database và CHẶN, KHÔNG cho vào.
    - Chỉ khi lỗi mạng (không thể kết nối tới máy chủ) mới dùng bộ nhớ đệm cục bộ,
      và cục bộ cũng BẮT BUỘC phải còn hạn và ở trạng thái ACTIVE.
    """
    current_mid = get_machine_id(db)
    # Ưu tiên URL Web App vì Apps Script phản hồi thời gian thực không bị trễ CDN
    target_url = db.get_setting("license_web_app_url") or DEFAULT_WEB_APP_URL or db.get_setting("license_sheet_url") or DEFAULT_SHEET_URL
    cached = get_cached_license(db)

    # 1. Nếu chưa từng kích hoạt bất kỳ key nào
    if not cached:
        return False, "Chưa kích hoạt bản quyền. Vui lòng nhập Key để sử dụng.", {"machine_id": current_mid}

    # 2. Kiểm tra mã máy lưu trong DB có khớp với máy vật lý hiện tại không
    if cached.get("machine_id") != current_mid:
        return False, "Mã Máy không trùng khớp với bản quyền đã đăng ký trước đó.", {"machine_id": current_mid}

    # 3. Kiểm tra trạng thái đã lưu: nếu đã bị KHÓA hoặc HẾT HẠN cục bộ
    cached_status = (cached.get("status") or "").upper()
    if cached_status in ("BLOCKED", "KHÓA", "TẠM KHÓA", "REVOKED"):
        return False, "Bản quyền thiết bị này đang bị khóa bởi Quản trị viên.", cached
    
    # Kiểm tra ngày hết hạn cục bộ trước
    expiry_raw = cached.get("expiry_raw", "")
    _, is_local_date_valid, local_expiry_msg = parse_expiry_date(expiry_raw)
    if not is_local_date_valid:
        db.set_setting("license_status", "EXPIRED")
        cached["status"] = "EXPIRED"
        cached["expiry_display"] = local_expiry_msg
        return False, f"Bản quyền đã hết hạn! {local_expiry_msg}", cached

    # 4. Thử đồng bộ trực tuyến với máy chủ thời gian thực
    try:
        ok, msg, online_info = verify_license_online(target_url, current_mid, cached.get("license_key", ""))
        
        # NẾU MÁY CHỦ PHẢN HỒI THÀNH CÔNG
        # TH1: Key hợp lệ và còn hạn
        if ok and online_info.get("is_valid") is True:
            status = (online_info.get("status") or "ACTIVE").strip().upper()
            if status not in ("ACTIVE", "HOẠT ĐỘNG", "OK"):
                db.set_setting("license_status", "BLOCKED")
                cached["status"] = "BLOCKED"
                return False, f"Bản quyền đang ở trạng thái khóa [{status}].", cached
            
            save_cached_license(db, online_info)
            return True, msg, online_info

        # TH2: Máy chủ phản hồi nhưng BÁO KHÔNG HỢP LỆ (Hết hạn, Bị khóa, Sai key, v.v.)
        # Đây là phản hồi chính thức từ máy chủ, KHÔNG ĐƯỢC fallback về cache cũ!
        server_status = (online_info.get("status") or "").upper()
        if "hết hạn" in msg.lower() or "expired" in msg.lower() or server_status == "EXPIRED" or not online_info.get("is_valid", True):
            # Nếu hết hạn
            if "hết hạn" in msg.lower() or "expired" in msg.lower() or server_status == "EXPIRED":
                db.set_setting("license_status", "EXPIRED")
                if online_info.get("expiry_raw"):
                    db.set_setting("license_expiry_raw", online_info.get("expiry_raw"))
                if online_info.get("expiry_display"):
                    db.set_setting("license_expiry_display", online_info.get("expiry_display"))
                cached["status"] = "EXPIRED"
                if online_info.get("expiry_display"):
                    cached["expiry_display"] = online_info.get("expiry_display")
                return False, msg or "Bản quyền đã hết hạn sử dụng. Vui lòng liên hệ Quản trị viên để gia hạn.", cached

            # Nếu bị khóa
            if "khóa" in msg.lower() or "blocked" in msg.lower() or server_status in ("BLOCKED", "KHÓA", "TẠM KHÓA", "REVOKED"):
                db.set_setting("license_status", "BLOCKED")
                cached["status"] = "BLOCKED"
                return False, msg or "Bản quyền thiết bị này đang bị khóa bởi Quản trị viên.", cached

            # Nếu máy chủ báo lỗi khác (Key không chính xác, v.v.)
            db.set_setting("license_status", "INVALID")
            cached["status"] = "INVALID"
            return False, msg, cached

        # TH3: Nếu chỉ là mất kết nối mạng tạm thời
        cached["expiry_display"] = local_expiry_msg
        return True, f"Bản quyền hợp lệ: {local_expiry_msg}", cached

    except Exception:
        # Lỗi mạng ngoại lệ -> Đã kiểm tra is_local_date_valid ở trên rồi
        cached["expiry_display"] = local_expiry_msg
        return True, f"Bản quyền hợp lệ (Ngoại tuyến): {local_expiry_msg}", cached

