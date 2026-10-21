import sqlite3
import json
import os
import sys
import shutil
from typing import List, Dict, Any, Optional

def get_app_data_dir() -> str:
    """
    Trả về thư mục lưu trữ dữ liệu an toàn và vĩnh viễn cho ứng dụng (Database, Sessions, Media).
    - Khi chạy file EXE đã đóng gói: LUÔN LƯU VÀO %APPDATA%/Auto Post.
      Điều này đảm bảo người dùng KHÔNG BAO GIỜ bị mất tài khoản hay phải đăng nhập lại mỗi khi cài bản mới / cập nhật.
    - Khi chạy môi trường phát triển (Python dev): Lưu tại thư mục project hiện tại.
    """
    if getattr(sys, 'frozen', False):
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        data_dir = os.path.join(appdata, "Auto Post")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    else:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return app_dir

def ensure_sessions_migrated():
    """Tự động di chuyển các file session đăng nhập cũ từ Program Files sang %APPDATA% nếu có."""
    try:
        data_dir = get_app_data_dir()
        target_sessions = os.path.join(data_dir, "sessions")
        os.makedirs(target_sessions, exist_ok=True)

        old_locations = [
            r"C:\Program Files\Auto Post\sessions",
            os.path.join(os.path.dirname(sys.executable), "sessions") if getattr(sys, 'frozen', False) else None
        ]
        for old_loc in old_locations:
            if old_loc and os.path.exists(old_loc) and os.path.abspath(old_loc) != os.path.abspath(target_sessions):
                for item in os.listdir(old_loc):
                    s_file = os.path.join(old_loc, item)
                    d_file = os.path.join(target_sessions, item)
                    if os.path.isfile(s_file) and not os.path.exists(d_file):
                        shutil.copy2(s_file, d_file)
    except Exception:
        pass

def get_asset_path(filename: str) -> str:
    """Tìm đường dẫn tệp trong assets ở mọi môi trường (dev, PyInstaller root, PyInstaller _internal)."""
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    candidates = [
        os.path.join(app_dir, "assets", filename),
        os.path.join(app_dir, "_internal", "assets", filename),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", filename),
        os.path.join(os.getcwd(), "assets", filename),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return os.path.join(app_dir, "assets", filename)

def get_default_db_path() -> str:
    data_dir = get_app_data_dir()
    db_path = os.path.join(data_dir, "app_data.db")
    
    # Tự động di chuyển session cũ
    ensure_sessions_migrated()

    # Nếu file db chưa tồn tại ở data_dir nhưng có file db ở bản cũ hoặc thư mục cài đặt:
    if not os.path.exists(db_path):
        candidate_sources = []
        if getattr(sys, 'frozen', False):
            candidate_sources.append(os.path.join(os.path.dirname(sys.executable), "app_data.db"))
            candidate_sources.append(r"C:\Program Files\Auto Post\app_data.db")
        else:
            candidate_sources.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app_data.db"))
            
        for cand in candidate_sources:
            if cand and os.path.exists(cand) and os.path.abspath(cand) != os.path.abspath(db_path):
                try:
                    shutil.copy2(cand, db_path)
                    break
                except Exception:
                    pass
    return db_path

class Database:
    def __init__(self, db_path: str = None):
        if db_path is None:
            self.db_path = get_default_db_path()
        else:
            self.db_path = db_path
            
        parent_dir = os.path.dirname(os.path.abspath(self.db_path))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Bảng Tài Khoản Facebook
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid TEXT UNIQUE,
                    name TEXT,
                    cookie TEXT,
                    proxy TEXT DEFAULT '',
                    status TEXT DEFAULT 'ACTIVE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Kiểm tra xem bảng groups cũ có cấu trúc UNIQUE(account_uid, group_id) cũ hay không để nâng cấp
            try:
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='groups'")
                row = cursor.fetchone()
                if row and row[0] and "page_id, group_id" not in row[0]:
                    cursor.execute("ALTER TABLE groups RENAME TO groups_old")
                    cursor.execute("""
                        CREATE TABLE groups (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            account_uid TEXT,
                            page_id TEXT DEFAULT '',
                            page_name TEXT DEFAULT '',
                            group_id TEXT,
                            group_name TEXT,
                            group_url TEXT,
                            member_count TEXT DEFAULT '',
                            privacy TEXT DEFAULT 'UNKNOWN',
                            selected INTEGER DEFAULT 1,
                            UNIQUE(account_uid, page_id, group_id)
                        )
                    """)
                    cursor.execute("""
                        INSERT INTO groups (account_uid, page_id, page_name, group_id, group_name, group_url, member_count, privacy, selected)
                        SELECT account_uid, '', '', group_id, group_name, group_url, member_count, privacy, selected FROM groups_old
                    """)
                    cursor.execute("DROP TABLE groups_old")
            except Exception:
                pass

            # Bảng Nhóm Facebook nếu chưa tồn tại
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_uid TEXT,
                    page_id TEXT DEFAULT '',
                    page_name TEXT DEFAULT '',
                    group_id TEXT,
                    group_name TEXT,
                    group_url TEXT,
                    member_count TEXT DEFAULT '',
                    privacy TEXT DEFAULT 'UNKNOWN',
                    selected INTEGER DEFAULT 1,
                    category TEXT DEFAULT 'Mặc định',
                    UNIQUE(account_uid, page_id, group_id)
                )
            """)

            try:
                cursor.execute("ALTER TABLE groups ADD COLUMN category TEXT DEFAULT 'Mặc định'")
            except Exception:
                pass

            try:
                cursor.execute("ALTER TABLE groups ADD COLUMN campaign_id INTEGER DEFAULT 0")
            except Exception:
                pass

            # Bảng Chiến Dịch / Mẫu Nội Dung
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    content TEXT,
                    media_paths TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Bảng Fanpage Facebook
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_uid TEXT,
                    page_id TEXT,
                    page_name TEXT,
                    page_url TEXT,
                    UNIQUE(account_uid, page_id)
                )
            """)

            # Bảng Nhật Ký Đăng Bài (Logs)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    account_uid TEXT,
                    group_id TEXT,
                    group_name TEXT,
                    status TEXT,
                    message TEXT
                )
            """)

            # Bảng Cấu Hình Ứng Dụng & Lên Lịch Đăng (Settings)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Bảng Tài Khoản Threads
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS threads_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid TEXT UNIQUE,
                    username TEXT,
                    name TEXT,
                    cookie TEXT,
                    proxy TEXT DEFAULT '',
                    status TEXT DEFAULT 'ACTIVE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Bảng Nhật Ký Hoạt Động Threads
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS threads_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    account_uid TEXT,
                    action_type TEXT,
                    target_url TEXT DEFAULT '',
                    status TEXT,
                    message TEXT
                )
            """)

            conn.commit()

    # --- ACCOUNTS ---
    def save_account(self, uid: str, name: str, cookie: str, proxy: str = "") -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO accounts (uid, name, cookie, proxy, status)
                VALUES (?, ?, ?, ?, 'ACTIVE')
                ON CONFLICT(uid) DO UPDATE SET
                    name=excluded.name,
                    cookie=excluded.cookie,
                    proxy=excluded.proxy,
                    status='ACTIVE'
            """, (uid, name, cookie, proxy))
            conn.commit()
            return cursor.lastrowid

    def get_accounts(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accounts ORDER BY id DESC")
            return [dict(row) for row in cursor.fetchall()]

    def delete_account(self, uid: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM accounts WHERE uid=?", (uid,))
            cursor.execute("DELETE FROM groups WHERE account_uid=?", (uid,))
            conn.commit()

    def update_account_cookie(self, uid: str, new_cookie_str: str):
        if not uid or not new_cookie_str:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE accounts SET cookie=? WHERE uid=?", (new_cookie_str, uid))
            conn.commit()

    # --- GROUPS ---
    def save_groups(self, account_uid: str, groups: List[Dict[str, Any]], page_id: str = "", page_name: str = "", default_category: Optional[str] = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for g in groups:
                g_id = g.get("group_id")
                if not g_id:
                    continue

                # Ưu tiên: 1. g['category'] -> 2. row['category'] -> 3. default_category -> 4. 'Mặc định'
                cursor.execute("SELECT category, campaign_id FROM groups WHERE account_uid=? AND page_id=? AND group_id=?", (account_uid, page_id, g_id))
                row = cursor.fetchone()
                existing_category = g.get("category") or (row["category"] if (row and row["category"]) else None) or default_category or "Mặc định"
                existing_campaign_id = g.get("campaign_id") or (row["campaign_id"] if (row and row["campaign_id"]) else 0)

                cursor.execute("DELETE FROM groups WHERE account_uid=? AND page_id=? AND group_id=?", (account_uid, page_id, g_id))
                try:
                    cursor.execute("""
                        INSERT INTO groups (account_uid, page_id, page_name, group_id, group_name, group_url, member_count, privacy, selected, category, campaign_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """, (
                        account_uid,
                        page_id,
                        page_name,
                        g_id,
                        g.get("group_name"),
                        g.get("group_url"),
                        g.get("member_count", ""),
                        g.get("privacy", "UNKNOWN"),
                        existing_category,
                        existing_campaign_id
                    ))
                except sqlite3.IntegrityError:
                    cursor.execute("DELETE FROM groups WHERE account_uid=? AND group_id=?", (account_uid, g_id))
                    cursor.execute("""
                        INSERT INTO groups (account_uid, page_id, page_name, group_id, group_name, group_url, member_count, privacy, selected, category, campaign_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """, (
                        account_uid,
                        page_id,
                        page_name,
                        g_id,
                        g.get("group_name"),
                        g.get("group_url"),
                        g.get("member_count", ""),
                        g.get("privacy", "UNKNOWN"),
                        existing_category,
                        existing_campaign_id
                    ))
            conn.commit()

    def get_groups(self, account_uid: Optional[str] = None, page_id: Optional[str] = None, category: Optional[str] = None, only_selected: bool = False) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM groups WHERE 1=1"
            params = []
            if account_uid:
                query += " AND account_uid=?"
                params.append(account_uid)
            if page_id is not None:
                query += " AND page_id=?"
                params.append(page_id)
            if category and category not in ["Tất cả", "Tất cả lĩnh vực", ""]:
                query += " AND category=?"
                params.append(category)
            if only_selected:
                query += " AND selected=1"
            query += " ORDER BY id DESC"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def update_group_selection(self, group_db_id: int, selected: bool):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE groups SET selected=? WHERE id=?", (1 if selected else 0, group_db_id))
            conn.commit()

    def update_group_category(self, group_db_id: int, category: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE groups SET category=? WHERE id=?", (category.strip() or 'Mặc định', group_db_id))
            conn.commit()

    def update_groups_category_batch(self, group_db_ids: List[int], category: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cat = category.strip() or "Mặc định"
            for db_id in group_db_ids:
                cursor.execute("UPDATE groups SET category=? WHERE id=?", (cat, db_id))
            conn.commit()

    def update_group_campaign(self, group_db_id: int, campaign_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE groups SET campaign_id=? WHERE id=?", (campaign_id, group_db_id))
            conn.commit()

    def update_groups_campaign_batch(self, group_db_ids: List[int], campaign_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for db_id in group_db_ids:
                cursor.execute("UPDATE groups SET campaign_id=? WHERE id=?", (campaign_id, db_id))
            conn.commit()

    def sync_groups_across_pages(self, account_uid: str):
        """
        Đồng bộ danh sách tất cả các nhóm đã chọn sang TOÀN BỘ các Fanpage thuộc cùng tài khoản.
        """
        if not account_uid:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT group_id, group_name, group_url, member_count, privacy, category, campaign_id
                FROM groups WHERE account_uid=? AND selected=1
            """, (account_uid,))
            all_groups = cursor.fetchall()
            if not all_groups:
                return

            cursor.execute("SELECT page_id, page_name FROM pages WHERE account_uid=?", (account_uid,))
            pages = cursor.fetchall()

            target_pages = [{"page_id": "", "page_name": ""}] + [dict(p) for p in pages]

            for p in target_pages:
                pid = p["page_id"]
                pname = p["page_name"]
                for g in all_groups:
                    cursor.execute("""
                        INSERT INTO groups (account_uid, page_id, page_name, group_id, group_name, group_url, member_count, privacy, selected, category, campaign_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                        ON CONFLICT(account_uid, page_id, group_id) DO UPDATE SET
                            selected=1,
                            category=excluded.category,
                            campaign_id=excluded.campaign_id
                    """, (account_uid, pid, pname, g["group_id"], g["group_name"], g["group_url"], g["member_count"], g["privacy"], g["category"], g["campaign_id"]))
            conn.commit()

    def get_categories(self, account_uid: Optional[str] = None, page_id: Optional[str] = None) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT DISTINCT category FROM groups WHERE category IS NOT NULL AND category != ''"
            params = []
            if account_uid:
                query += " AND account_uid=?"
                params.append(account_uid)
                if page_id is not None:
                    query += " AND page_id=?"
                    params.append(page_id)
            query += " ORDER BY category ASC"
            cursor.execute(query, params)
            cats = [row["category"] for row in cursor.fetchall()]
            if "Mặc định" not in cats:
                cats.insert(0, "Mặc định")
            return cats

    def toggle_all_groups_selection(self, selected: bool, account_uid: Optional[str] = None, page_id: Optional[str] = None, category: Optional[str] = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "UPDATE groups SET selected=?"
            params = [1 if selected else 0]
            if account_uid:
                query += " WHERE account_uid=?"
                params.append(account_uid)
                if page_id is not None:
                    query += " AND page_id=?"
                    params.append(page_id)
                if category and category not in ["Tất cả", "Tất cả lĩnh vực", ""]:
                    query += " AND category=?"
                    params.append(category)
            cursor.execute(query, params)
            conn.commit()

    def delete_group(self, group_db_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM groups WHERE id=?", (group_db_id,))
            conn.commit()

    def clear_groups(self, account_uid: Optional[str] = None, page_id: Optional[str] = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "DELETE FROM groups WHERE 1=1"
            params = []
            if account_uid:
                query += " AND account_uid=?"
                params.append(account_uid)
                if page_id is not None:
                    query += " AND page_id=?"
                    params.append(page_id)
            cursor.execute(query, params)
            conn.commit()

    # --- CAMPAIGNS ---
    def save_campaign(self, title: str, content: str, media_paths: List[str]) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO campaigns (title, content, media_paths)
                VALUES (?, ?, ?)
            """, (title, content, json.dumps(media_paths)))
            conn.commit()
            return cursor.lastrowid

    def get_campaigns(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM campaigns ORDER BY id DESC")
            rows = cursor.fetchall()
            res = []
            for r in rows:
                item = dict(r)
                item["media_paths"] = json.loads(item["media_paths"]) if item["media_paths"] else []
                res.append(item)
            return res

    def delete_campaign(self, campaign_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
            conn.commit()

    # --- PAGES ---
    def save_pages(self, account_uid: str, pages: List[Dict[str, Any]], clear_existing: bool = True):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if clear_existing and pages:
                cursor.execute("DELETE FROM pages WHERE account_uid=?", (account_uid,))
            for p in pages:
                p_id = p.get("page_id")
                if not p_id:
                    continue
                cursor.execute("""
                    INSERT OR REPLACE INTO pages (account_uid, page_id, page_name, page_url)
                    VALUES (?, ?, ?, ?)
                """, (account_uid, p_id, p.get("page_name"), p.get("page_url")))
            conn.commit()

    def get_pages(self, account_uid: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pages WHERE account_uid=? ORDER BY id DESC", (account_uid,))
            return [dict(row) for row in cursor.fetchall()]

    # --- LOGS ---
    def add_log(self, account_uid: str, group_id: str, group_name: str, status: str, message: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO logs (account_uid, group_id, group_name, status, message)
                VALUES (?, ?, ?, ?, ?)
            """, (account_uid, group_id, group_name, status, message))
            conn.commit()

    log_post = add_log

    def get_logs(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def clear_logs(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM logs")
            conn.commit()

    # --- SETTINGS / SCHEDULER ---
    def set_setting(self, key: str, value: Any):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            val_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            cursor.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """, (key, val_str))
            conn.commit()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = cursor.fetchone()
            if row:
                raw = row[0]
                try:
                    return json.loads(raw)
                except Exception:
                    return raw
            return default

    # --- THREADS ACCOUNTS ---
    def save_threads_account(self, uid: str, username: str, name: str, cookie: str, proxy: str = "") -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO threads_accounts (uid, username, name, cookie, proxy, status)
                VALUES (?, ?, ?, ?, ?, 'ACTIVE')
                ON CONFLICT(uid) DO UPDATE SET
                    username=excluded.username,
                    name=excluded.name,
                    cookie=excluded.cookie,
                    proxy=excluded.proxy,
                    status='ACTIVE'
            """, (uid, username, name, cookie, proxy))
            conn.commit()
            return cursor.lastrowid

    def get_threads_accounts(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM threads_accounts ORDER BY id DESC")
            return [dict(row) for row in cursor.fetchall()]

    def delete_threads_account(self, uid: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM threads_accounts WHERE uid = ?", (uid,))
            conn.commit()

    def update_threads_cookie(self, uid: str, new_cookie: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE threads_accounts SET cookie = ? WHERE uid = ?", (new_cookie, uid))
            conn.commit()

    # --- THREADS LOGS ---
    def add_threads_log(self, account_uid: str, action_type: str, target_url: str, status: str, message: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO threads_logs (account_uid, action_type, target_url, status, message)
                VALUES (?, ?, ?, ?, ?)
            """, (account_uid, action_type, target_url, status, message))
            conn.commit()

    def get_threads_logs(self, limit: int = 150) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM threads_logs ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_threads_successful_posts(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM threads_logs 
                WHERE status = 'SUCCESS' AND target_url != '' AND target_url != '-' AND target_url LIKE 'http%'
                ORDER BY id DESC LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def clear_threads_logs(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM threads_logs")
            conn.commit()
