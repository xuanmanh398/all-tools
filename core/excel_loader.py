import os
import re
import time
import hashlib
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional

DEFAULT_EXCEL_PATH = r"E:\Affiliate\Post.xlsx"

VALID_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.jfif', '.avif'}
VALID_VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
VALID_MEDIA_EXTS = VALID_IMAGE_EXTS | VALID_VIDEO_EXTS


def _natural_sort_key(path: str):
    """Sắp xếp tên file theo thứ tự tự nhiên (VD: 1.jpg, 2.jpg, ..., 10.jpg)."""
    name = os.path.basename(path)
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', name)]


def _get_media_cache_dir() -> str:
    """Thư mục lưu đệm ảnh chuyển đổi từ .webp sang .jpg để tương thích 100% với mọi trình duyệt."""
    try:
        from core.database import get_app_data_dir
        base_dir = get_app_data_dir()
    except Exception:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(base_dir, "media_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def ensure_upload_compatible_media(media_paths: List[str]) -> List[str]:
    """
    Chuyển đổi tự động các tệp .webp sang .jpg chất lượng cao (lưu cache) để đảm bảo
    Facebook và Threads luôn nhận diện và tải ảnh lên thành công 100%.
    """
    if not media_paths:
        return []

    result = []
    cache_dir = _get_media_cache_dir()

    for p in media_paths:
        if not p or not os.path.exists(p):
            continue
        ext = os.path.splitext(p)[1].lower()
        if ext in ('.webp', '.jfif', '.avif', '.bmp'):
            try:
                from PIL import Image
                stat = os.stat(p)
                sig = f"{os.path.abspath(p)}|{stat.st_size}|{int(stat.st_mtime)}"
                h = hashlib.md5(sig.encode("utf-8", errors="ignore")).hexdigest()[:12]
                base_name = os.path.splitext(os.path.basename(p))[0]
                cached_jpg = os.path.join(cache_dir, f"{base_name}_{h}.jpg")
                if not os.path.exists(cached_jpg):
                    with Image.open(p) as img:
                        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                            bg = Image.new("RGB", img.size, (255, 255, 255))
                            rgba = img.convert("RGBA")
                            bg.paste(rgba, mask=rgba.split()[3])
                            bg.save(cached_jpg, "JPEG", quality=95)
                        else:
                            img.convert("RGB").save(cached_jpg, "JPEG", quality=95)
                if os.path.exists(cached_jpg):
                    result.append(cached_jpg)
                    continue
            except Exception:
                pass
        result.append(p)

    return result


def resolve_folder_path(folder_str: str, excel_path: str = "") -> str:
    """Chuẩn hóa đường dẫn thư mục hình ảnh (hỗ trợ cả đường dẫn tuyệt đối và tương đối)."""
    if not folder_str:
        return ""
    cleaned = folder_str.strip().strip('"').strip("'")
    if not cleaned:
        return ""
    if os.path.isabs(cleaned):
        return os.path.normpath(cleaned)
    if excel_path:
        excel_dir = os.path.dirname(os.path.abspath(excel_path))
        cand = os.path.normpath(os.path.join(excel_dir, cleaned))
        if os.path.exists(cand):
            return cand
    return os.path.normpath(cleaned)


def scan_media_in_folder(folder_path: str, excel_path: str = "") -> List[str]:
    """Quét toàn bộ tệp hình ảnh / video hợp lệ trong thư mục được chỉ định ở Cột B."""
    resolved = resolve_folder_path(folder_path, excel_path)
    if not resolved or not os.path.isdir(resolved):
        return []

    files = []
    try:
        for entry in os.listdir(resolved):
            full_path = os.path.join(resolved, entry)
            if os.path.isfile(full_path):
                ext = os.path.splitext(entry)[1].lower()
                if ext in VALID_MEDIA_EXTS:
                    files.append(full_path)
    except Exception:
        return []

    files.sort(key=_natural_sort_key)
    return files


def _col_letters_to_index(col_letters: str) -> int:
    """Chuyển ký hiệu cột Excel ('A', 'B', 'AA'...) sang chỉ số 0-based (A=0, B=1...)."""
    idx = 0
    for ch in col_letters.upper():
        if 'A' <= ch <= 'Z':
            idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx - 1


def _read_xlsx_rows(excel_path: str) -> List[List[str]]:
    """
    Đọc trực tiếp tệp .xlsx bằng thư viện chuẩn Python (zipfile + xml.etree.ElementTree).
    Không phụ thuộc thư viện ngoài, hoạt động 100% trên cả Python và bản đóng gói EXE.
    """
    rows_data: List[List[str]] = []
    with zipfile.ZipFile(excel_path, 'r') as z:
        shared_strings: List[str] = []
        if 'xl/sharedStrings.xml' in z.namelist():
            ss_xml = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in ss_xml.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
                parts = []
                for t in si.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'):
                    if t.text:
                        parts.append(t.text)
                shared_strings.append(''.join(parts))

        # Tìm sheet đầu tiên
        sheet_names = [
            name for name in z.namelist()
            if name.startswith('xl/worksheets/sheet') and name.endswith('.xml')
        ]
        if not sheet_names:
            return []
        sheet_names.sort(key=_natural_sort_key)
        sheet_xml = ET.fromstring(z.read(sheet_names[0]))

        ns_row = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'
        ns_c = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'
        ns_v = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v'
        ns_is = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is'
        ns_t = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'

        for row_elem in sheet_xml.iter(ns_row):
            row_cells: Dict[int, str] = {}
            max_col = 1
            for c_elem in row_elem.findall(ns_c):
                ref = c_elem.attrib.get('r', '')
                col_letters = ''.join(ch for ch in ref if ch.isalpha())
                col_idx = _col_letters_to_index(col_letters) if col_letters else len(row_cells)
                if col_idx > max_col:
                    max_col = col_idx

                cell_type = c_elem.attrib.get('t', '')
                val_str = ''

                if cell_type == 's':
                    v_elem = c_elem.find(ns_v)
                    if v_elem is not None and v_elem.text is not None:
                        try:
                            s_idx = int(v_elem.text)
                            if 0 <= s_idx < len(shared_strings):
                                val_str = shared_strings[s_idx]
                        except Exception:
                            val_str = v_elem.text or ''
                elif cell_type == 'inlineStr':
                    is_elem = c_elem.find(ns_is)
                    if is_elem is not None:
                        parts = [t.text for t in is_elem.iter(ns_t) if t.text]
                        val_str = ''.join(parts)
                else:
                    v_elem = c_elem.find(ns_v)
                    if v_elem is not None and v_elem.text is not None:
                        val_str = v_elem.text

                row_cells[col_idx] = val_str

            row_list = [row_cells.get(i, '') for i in range(max(2, max_col + 1))]
            rows_data.append(row_list)

    return rows_data


DEFAULT_SHORTENER_URL = "https://link.truyennha.id.vn"


def ensure_short_links_in_excel(excel_path: str, worker_url: str = DEFAULT_SHORTENER_URL) -> bool:
    """
    Tự động chuẩn hóa file Excel 4 cột:
    - Nếu Cột A có link: tự động tách chuyển sang Cột B (link gốc).
    - Nếu Cột B có link mà Cột C trống: gọi API rút gọn tạo link https://link.truyennha.id.vn/s/... và ghi vào Cột C.
    - Nếu Cột C đã có rồi: giữ nguyên không tạo thêm.
    """
    if not excel_path or not os.path.exists(excel_path):
        return False
    try:
        import openpyxl
        import requests

        wb = openpyxl.load_workbook(excel_path)
        sheet = wb.active
        modified = False

        for r in range(1, sheet.max_row + 1):
            val_a = sheet.cell(r, 1).value
            val_b = sheet.cell(r, 2).value
            val_c = sheet.cell(r, 3).value

            # Bỏ qua dòng tiêu đề nếu dòng 1 là tên cột
            if r == 1:
                str_a = str(val_a or "").strip().lower()
                str_b = str(val_b or "").strip().lower()
                if "nội dung" in str_a or "content" in str_a or "link" in str_b or "folder" in str_b:
                    continue

            orig_url = str(val_b or "").strip()
            # Nếu cột B chưa có nhưng cột A có URL, tách chuyển sang cột B
            if (not orig_url or not orig_url.startswith("http")) and val_a:
                found = re.findall(r"(https?://[^\s]+)", str(val_a))
                if found:
                    orig_url = found[-1]
                    clean_text = str(val_a).replace(orig_url, "").strip()
                    sheet.cell(r, 1).value = clean_text
                    sheet.cell(r, 2).value = orig_url
                    modified = True

            # Kiểm tra Cột C: nếu Cột B có link mà Cột C trống, tạo link rút gọn mới
            short_val = str(val_c or "").strip()
            if orig_url and orig_url.startswith("http"):
                if not short_val or not short_val.startswith("http"):
                    try:
                        res = requests.post(f"{worker_url}/api/shorten", json={"url": orig_url}, timeout=6)
                        if res.status_code == 200:
                            data = res.json()
                            short_link = data.get("short_url")
                            if short_link:
                                sheet.cell(r, 3).value = short_link
                                modified = True
                    except Exception:
                        pass

        if modified:
            wb.save(excel_path)
            return True
    except Exception:
        pass
    return False


def _is_header_row(col_a: str, col_b: str, excel_path: str = "") -> bool:
    """Kiểm tra xem dòng đầu tiên có phải là dòng tiêu đề cột hay không."""
    a_low = (col_a or "").strip().lower()
    b_low = (col_b or "").strip().lower()

    header_keywords_a = {
        "nội dung", "noi dung", "content", "bài viết", "bai viet",
        "mẫu bài viết", "mau bai viet", "text", "caption", "cột a", "cot a"
    }
    header_keywords_b = {
        "folder", "thư mục", "thu muc", "hình ảnh", "hinh anh", "folder ảnh",
        "folder hình ảnh", "image", "images", "media", "đường dẫn", "duong dan", "cột b", "cot b",
        "link", "link shopee", "link gốc", "url"
    }

    if a_low in header_keywords_a or b_low in header_keywords_b:
        resolved_b = resolve_folder_path(col_b, excel_path)
        if not (resolved_b and os.path.isdir(resolved_b)):
            return True
    return False


def load_posts_from_excel(excel_path: str) -> List[Dict[str, Any]]:
    """
    Đọc danh sách mẫu bài viết từ file Excel (.xlsx):
    - Cấu trúc 4 cột chuẩn:
        + Cột A: Nội dung bài viết
        + Cột B: Link gốc Shopee / Affiliate
        + Cột C: Link rút gọn với domain riêng (link.truyennha.id.vn)
        + Cột D: Folder chứa ảnh sản phẩm
    - Nếu Cột C trống, hệ thống tự động tạo link rút gọn mới và ghi vào Cột C của file Excel.
    - Đăng bài / bình luận sẽ tự động lấy: Nội dung (Cột A) + Link rút gọn (Cột C) và Ảnh (Cột D).
    """
    if not excel_path or not os.path.exists(excel_path):
        return []

    # 1. Tự động kiểm tra và điền link rút gọn vào Cột C nếu còn trống
    try:
        ensure_short_links_in_excel(excel_path)
    except Exception:
        pass

    raw_rows = _read_xlsx_rows(excel_path)
    posts: List[Dict[str, Any]] = []

    for row_idx, row in enumerate(raw_rows, start=1):
        col_a = (row[0] if len(row) > 0 else "") or ""
        col_b = (row[1] if len(row) > 1 else "") or ""
        col_c = (row[2] if len(row) > 2 else "") or ""
        col_d = (row[3] if len(row) > 3 else "") or ""

        col_a = col_a.replace("\r\n", "\n").replace("\r", "\n").strip()
        col_b = col_b.strip()
        col_c = col_c.strip()
        col_d = col_d.strip()

        if not col_a and not col_b and not col_c and not col_d:
            continue

        # Bỏ qua dòng tiêu đề nếu dòng 1 là tên cột
        if row_idx == 1 and _is_header_row(col_a, col_b, excel_path):
            continue

        # Xác định Cấu trúc 4 cột hay 2 cột:
        # Nếu có cột D hoặc cột B/C là URL -> Đây là bảng 4 cột:
        # Folder ảnh ở cột D, Link rút gọn ở cột C, Link gốc ở cột B.
        is_4_cols = bool(col_d) or (col_b.startswith("http") or col_c.startswith("http"))

        if is_4_cols:
            folder_str = col_d
            orig_link = col_b
            short_link = col_c
        else:
            folder_str = col_b
            orig_link = ""
            short_link = ""

        # Nội dung đăng bài / comment: kết hợp Nội dung (Cột A) và Link rút gọn (Cột C)
        final_post_text = col_a
        if short_link:
            final_post_text = f"{col_a}\n{short_link}".strip()

        # Làm sạch ký tự icon lỗi nếu có
        if '\ufffc' in final_post_text or '\ufffd' in final_post_text:
            final_post_text = final_post_text.replace('\ufffc', '🔹').replace('\ufffd', '🔹')

        resolved_folder = resolve_folder_path(folder_str, excel_path)
        folder_exists = bool(resolved_folder and os.path.isdir(resolved_folder))
        raw_media = scan_media_in_folder(folder_str, excel_path) if folder_exists else []
        upload_media = ensure_upload_compatible_media(raw_media)

        seq_num = len(posts) + 1
        first_line = col_a.split('\n')[0].strip() if col_a else "(Không có văn bản)"
        if len(first_line) > 55:
            first_line = first_line[:52] + "..."

        posts.append({
            "id": seq_num,
            "index": seq_num,
            "excel_row": row_idx,
            "title": f"Mẫu #{seq_num}: {first_line}",
            "content": final_post_text,
            "raw_text": col_a,
            "orig_link": orig_link,
            "short_link": short_link,
            "folder_path": resolved_folder or folder_str,
            "raw_folder_path": folder_str,
            "folder_exists": folder_exists,
            "raw_media_paths": raw_media,
            "media_paths": upload_media,
            "images": upload_media,
        })

    return posts


def get_configured_excel_path(db) -> str:
    """Lấy đường dẫn file Excel cấu hình trong CSDL (mặc định: E:\\Affiliate\\Post.xlsx)."""
    saved = ""
    if db is not None:
        try:
            saved = db.get_setting("excel_post_path", "") or ""
        except Exception:
            saved = ""
    saved = str(saved).strip()
    if saved and os.path.exists(saved):
        return saved
    if os.path.exists(DEFAULT_EXCEL_PATH):
        if db is not None and not saved:
            try:
                db.set_setting("excel_post_path", DEFAULT_EXCEL_PATH)
            except Exception:
                pass
        return DEFAULT_EXCEL_PATH
    return saved or DEFAULT_EXCEL_PATH


def set_configured_excel_path(db, excel_path: str):
    """Lưu đường dẫn file Excel vào CSDL."""
    if db is not None and excel_path is not None:
        try:
            db.set_setting("excel_post_path", excel_path.strip())
        except Exception:
            pass


def get_fresh_media_for_post(post_item: Dict[str, Any], excel_path: str = "") -> List[str]:
    """
    Quét lại thư mục hình ảnh của mẫu bài viết ngay tại thời điểm đăng
    (giúp tự động nhận diện ảnh mới thêm vào thư mục mà không cần khởi động lại).
    """
    if not post_item:
        return []
    folder_str = post_item.get("raw_folder_path") or post_item.get("folder_path") or ""
    if folder_str:
        fresh_raw = scan_media_in_folder(folder_str, excel_path)
        if fresh_raw:
            return ensure_upload_compatible_media(fresh_raw)
    existing = post_item.get("media_paths") or post_item.get("images") or []
    return ensure_upload_compatible_media([p for p in existing if os.path.exists(p)])


def combine_folder_images_for_comment(media_paths: List[str]) -> Optional[str]:
    """
    Do khung bình luận Facebook chỉ cho phép đính kèm 1 tệp ảnh duy nhất trên mỗi bình luận,
    khi thư mục mẫu Excel có từ 2 ảnh trở lên, hàm này tự động ghép toàn bộ các ảnh trong
    thư mục thành 1 bức ảnh ghép (collage) độ phân giải cao, sắc nét để hiển thị đầy đủ
    mọi góc chụp sản phẩm trong bình luận Facebook.
    """
    valid_imgs = [
        p for p in (media_paths or [])
        if p and os.path.exists(p) and os.path.splitext(p)[1].lower() in VALID_IMAGE_EXTS
    ]
    if not valid_imgs:
        return None
    if len(valid_imgs) == 1:
        return valid_imgs[0]

    try:
        from PIL import Image
        cache_dir = _get_media_cache_dir()
        sig_parts = []
        for p in valid_imgs:
            st = os.stat(p)
            sig_parts.append(f"{os.path.abspath(p)}|{st.st_size}|{int(st.st_mtime)}")
        h = hashlib.md5("||".join(sig_parts).encode("utf-8", errors="ignore")).hexdigest()[:14]
        out_path = os.path.join(cache_dir, f"fb_cmt_collage_{len(valid_imgs)}imgs_{h}.jpg")
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
            return out_path

        opened = [Image.open(p).convert("RGB") for p in valid_imgs]
        n = len(opened)
        gap = 10

        if n <= 3:
            # Ghép ngang (2 hoặc 3 ảnh cạnh nhau) với cùng chiều cao 1080px
            target_h = 1080
            resized = []
            for im in opened:
                w = max(1, int(im.width * (target_h / max(1, im.height))))
                resized.append(im.resize((w, target_h), Image.Resampling.LANCZOS))
            total_w = sum(im.width for im in resized) + gap * (n - 1)
            canvas = Image.new("RGB", (total_w, target_h), (255, 255, 255))
            x = 0
            for im in resized:
                canvas.paste(im, (x, 0))
                x += im.width + gap
        else:
            # Ghép dạng lưới 2 cột cho từ 4 ảnh trở lên
            cols = 2
            rows = (n + cols - 1) // cols
            cell_w = 720
            cell_h = 720
            total_w = cols * cell_w + (cols - 1) * gap
            total_h = rows * cell_h + (rows - 1) * gap
            canvas = Image.new("RGB", (total_w, total_h), (255, 255, 255))
            for idx, im in enumerate(opened):
                r = idx // cols
                c = idx % cols
                # Cắt giữa (center-crop) hoặc thu phóng vừa ô vuông
                im_ratio = im.width / max(1, im.height)
                if im_ratio > 1.0:
                    new_w = cell_w
                    new_h = max(1, int(cell_w / im_ratio))
                else:
                    new_h = cell_h
                    new_w = max(1, int(cell_h * im_ratio))
                thumb = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
                cell_bg = Image.new("RGB", (cell_w, cell_h), (255, 255, 255))
                cell_bg.paste(thumb, ((cell_w - new_w) // 2, (cell_h - new_h) // 2))
                canvas.paste(cell_bg, (c * (cell_w + gap), r * (cell_h + gap)))

        for im in opened:
            try:
                im.close()
            except Exception:
                pass

        canvas.save(out_path, "JPEG", quality=95)
        return out_path
    except Exception:
        return valid_imgs[0]


