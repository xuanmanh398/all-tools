import os
import shutil
import hashlib
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QTextEdit, QLabel, QListWidget, QGroupBox, QMessageBox, QFileDialog,
    QSplitter, QListWidgetItem, QDialog, QGridLayout, QTabWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from core.database import Database
from core.spintax_parser import SpintaxParser


class EmojiPickerPopup(QDialog):
    """Cửa sổ Modal chọn Icon / Emoji đa dạng theo từng chủ đề bán hàng & tiếp thị."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("😊 Bảng Chọn Icon / Emoji Bán Hàng")
        self.setMinimumSize(440, 340)
        self.selected_emoji = ""

        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        categories = {
            "Đầu Dòng / Bullet": ["🔹", "🔸", "📌", "📍", "✅", "✔️", "👉", "➡️", "▶️", "🔘", "▪️", "◽"],
            "Gây Chú Ý": ["🚀", "🔥", "💡", "⚡", "💥", "📢", "🎯", "🌟", "💎", "🎁", "🏆", "👑"],
            "Bán Hàng / Giá": ["🛒", "💵", "💰", "🏷️", "💯", "☎️", "📞", "📩", "✉️", "🌐", "🏠", "📱"],
            "Cảm Xúc": ["😊", "👍", "❤️", "👏", "🎉", "🤩", "😎", "🥳", "🤝", "⭐", "✨", "💯"]
        }

        emoji_font = QFont("Segoe UI Emoji", 14)

        for cat_name, emojis in categories.items():
            cat_widget = QWidget()
            grid = QGridLayout(cat_widget)
            for idx, em in enumerate(emojis):
                btn = QPushButton(em)
                btn.setFont(emoji_font)
                btn.setFixedSize(48, 48)
                btn.setStyleSheet("font-size: 20px; padding: 4px; background-color: #313244; color: white;")
                btn.clicked.connect(lambda _, e=em: self.select_emoji(e))
                grid.addWidget(btn, idx // 4, idx % 4)
            tabs.addTab(cat_widget, cat_name)

        layout.addWidget(tabs)

    def select_emoji(self, emoji: str):
        self.selected_emoji = emoji
        self.accept()


class ContentTab(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.media_paths = []
        self.init_ui()
        self.load_campaigns()

    def init_ui(self):
        main_layout = QHBoxLayout(self)

        # Splitter: Left (Campaign Editor), Right (Saved Campaigns List)
        splitter = QSplitter(Qt.Horizontal)

        # Left Widget: Editor
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)

        # Title
        title_box = QGroupBox("1. Tiêu Đề Chiến Dịch Mẫu")
        t_layout = QVBoxLayout(title_box)
        self.txt_title = QLineEdit()
        self.txt_title.setStyleSheet("font-size: 14px; padding: 6px;")
        self.txt_title.setPlaceholderText("VD: Mẫu Đăng Bài Bán Hàng Sản Phẩm A...")
        t_layout.addWidget(self.txt_title)
        editor_layout.addWidget(title_box)

        # Spintax Editor Box
        content_box = QGroupBox("2. Nội Dung Bài Viết (Hỗ trợ Spintax)")
        c_layout = QVBoxLayout(content_box)

        # Hàng 1: Nút Spintax, Xem Trước & Công Cụ Icon
        spintax_bar = QHBoxLayout()
        btn_add_spintax = QPushButton("➕ Thêm {A|B|C}")
        btn_add_spintax.setStyleSheet("padding: 5px 10px; font-weight: bold;")
        btn_add_spintax.clicked.connect(self.insert_spintax_template)
        spintax_bar.addWidget(btn_add_spintax)

        btn_preview = QPushButton("👁️ Xem Trước Biến Thể")
        btn_preview.setStyleSheet("background-color: #0288d1; color: white; padding: 5px 10px; font-weight: bold;")
        btn_preview.clicked.connect(self.on_preview_spintax)
        spintax_bar.addWidget(btn_preview)

        btn_emoji_picker = QPushButton("😊 Bảng Icon / Emoji")
        btn_emoji_picker.setStyleSheet("background-color: #7b1fa2; color: white; padding: 5px 10px; font-weight: bold;")
        btn_emoji_picker.clicked.connect(self.open_emoji_picker)
        spintax_bar.addWidget(btn_emoji_picker)

        btn_clean_icons = QPushButton("🧹 Sửa Lỗi Icon Bị Ẩn (￼)")
        btn_clean_icons.setStyleSheet("background-color: #d84315; color: white; padding: 5px 10px; font-weight: bold;")
        btn_clean_icons.setToolTip("Tự động chuyển các ký tự icon bị lỗi/ẩn (do copy-paste từ Facebook) thành icon 🔹")
        btn_clean_icons.clicked.connect(self.on_clean_broken_icons)
        spintax_bar.addWidget(btn_clean_icons)

        spintax_bar.addStretch()
        c_layout.addLayout(spintax_bar)

        # Hàng 2: Thanh chèn nhanh các Icon phổ biến
        quick_bar = QHBoxLayout()
        quick_bar.addWidget(QLabel("Chèn nhanh Icon:"))
        quick_emojis = ["🚀", "🔥", "📌", "💡", "⚡", "💎", "✅", "👉", "🎯", "🚩", "🔹", "🔸", "🛒", "💵", "🎁", "📞"]
        
        emoji_font = QFont("Segoe UI Emoji", 11)
        for em in quick_emojis:
            btn_em = QPushButton(em)
            btn_em.setFont(emoji_font)
            btn_em.setFixedSize(30, 28)
            btn_em.setStyleSheet("font-size: 14px; padding: 0px; background-color: #313244; color: white;")
            btn_em.clicked.connect(lambda _, e=em: self.insert_emoji(e))
            quick_bar.addWidget(btn_em)

        quick_bar.addStretch()
        c_layout.addLayout(quick_bar)

        self.txt_content = QTextEdit()
        self.txt_content.setFont(emoji_font)
        self.txt_content.setStyleSheet("font-size: 14px; line-height: 1.45; padding: 8px;")
        self.txt_content.setMinimumHeight(240)
        self.txt_content.setPlaceholderText(
            "Nhập nội dung bài đăng tại đây.\n"
            "Ví dụ cú pháp Spintax:\n"
            "{Xin chào|Chào bạn|Hi} mọi người! Hôm nay bên mình {giảm giá|khuyến mãi} {20%|30%}.\n"
            "Liên hệ: {0901234567|0987654321}."
        )
        self.txt_content.textChanged.connect(self.update_content_stats)
        c_layout.addWidget(self.txt_content)

        stat_bar = QHBoxLayout()
        self.lbl_content_stats = QLabel("📝 0 ký tự | 0 dòng")
        self.lbl_content_stats.setStyleSheet("color: #a6adc8; font-size: 11px; padding: 2px;")
        stat_bar.addWidget(self.lbl_content_stats)
        stat_bar.addStretch()
        c_layout.addLayout(stat_bar)
        editor_layout.addWidget(content_box, stretch=2)

        # Spintax Preview Box
        preview_box = QGroupBox("Xem Trước Kết Quả Ngẫu Nhiên")
        p_layout = QVBoxLayout(preview_box)
        self.txt_preview = QTextEdit()
        self.txt_preview.setFont(emoji_font)
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setStyleSheet("font-size: 13px; padding: 8px; background-color: #1e1e2e; color: #a6e3a1;")
        self.txt_preview.setMinimumHeight(140)
        p_layout.addWidget(self.txt_preview)
        editor_layout.addWidget(preview_box, stretch=1)

        # Media Attachments Box
        media_box = QGroupBox("3. Đính Kèm Hình Ảnh / Video")
        m_layout = QVBoxLayout(media_box)

        m_btn_bar = QHBoxLayout()
        btn_add_media = QPushButton("📁 Thêm Ảnh/Video")
        btn_add_media.clicked.connect(self.on_add_media)
        m_btn_bar.addWidget(btn_add_media)

        btn_clear_media = QPushButton("🗑️ Xóa Media")
        btn_clear_media.clicked.connect(self.on_clear_media)
        m_btn_bar.addWidget(btn_clear_media)
        m_btn_bar.addStretch()
        m_layout.addLayout(m_btn_bar)

        self.list_media = QListWidget()
        self.list_media.setMaximumHeight(70)
        m_layout.addWidget(self.list_media)
        editor_layout.addWidget(media_box)

        # Save Button
        self.btn_save = QPushButton("💾 Lưu Mẫu Nội Dung Này")
        self.btn_save.setStyleSheet("background-color: #2e7d32; color: white; font-size: 14px; font-weight: bold; padding: 10px;")
        self.btn_save.clicked.connect(self.on_save_campaign)
        editor_layout.addWidget(self.btn_save)

        splitter.addWidget(editor_widget)

        # Right Widget: Saved Campaigns
        saved_widget = QWidget()
        saved_layout = QVBoxLayout(saved_widget)

        saved_box = QGroupBox("Danh Sách Nội Dung Đã Lưu")
        s_box_layout = QVBoxLayout(saved_box)

        self.list_campaigns = QListWidget()
        self.list_campaigns.setStyleSheet("font-size: 13px;")
        self.list_campaigns.itemClicked.connect(self.on_select_campaign)
        s_box_layout.addWidget(self.list_campaigns)

        btn_del_camp = QPushButton("Xóa Mẫu Được Chọn")
        btn_del_camp.setStyleSheet("background-color: #c62828; color: white; font-weight: bold; padding: 6px;")
        btn_del_camp.clicked.connect(self.on_delete_campaign)
        s_box_layout.addWidget(btn_del_camp)

        saved_layout.addWidget(saved_box)
        splitter.addWidget(saved_widget)

        splitter.setSizes([700, 300])
        main_layout.addWidget(splitter)

    def insert_spintax_template(self):
        self.txt_content.insertPlainText("{Nội dung 1|Nội dung 2|Nội dung 3}")

    def insert_emoji(self, emoji: str):
        self.txt_content.insertPlainText(emoji)
        self.txt_content.setFocus()

    def open_emoji_picker(self):
        dialog = EmojiPickerPopup(self)
        if dialog.exec() == QDialog.Accepted and dialog.selected_emoji:
            self.insert_emoji(dialog.selected_emoji)

    def on_clean_broken_icons(self):
        text = self.txt_content.toPlainText()
        broken_count = text.count('\ufffc') + text.count('\ufffd')
        if broken_count == 0:
            QMessageBox.information(self, "Thông báo", "Nội dung bài viết không có icon lỗi (￼) nào!")
            return

        cleaned = text.replace('\ufffc', '🔹').replace('\ufffd', '🔹')
        self.txt_content.setText(cleaned)
        QMessageBox.information(self, "Thành công", f"Đã tự động chuyển đổi {broken_count} vị trí icon bị lỗi (￼) thành icon '🔹'!")

    def update_content_stats(self):
        text = self.txt_content.toPlainText()
        chars = len(text)
        lines = len(text.splitlines()) if text else 0
        words = len(text.split()) if text else 0
        self.lbl_content_stats.setText(f"📝 {chars} ký tự | {words} từ | {lines} dòng")

    def on_preview_spintax(self):
        text = self.txt_content.toPlainText().strip()
        if not text:
            self.txt_preview.setText("Vui lòng nhập nội dung Spintax trước!")
            return
        variations = SpintaxParser.preview_variations(text, count=3)
        preview_str = ""
        for i, var in enumerate(variations, 1):
            preview_str += f"=== Mẫu Biến Thể {i} ===\n{var}\n\n"
        self.txt_preview.setText(preview_str.strip())

    def copy_to_app_media(self, source_path: str) -> str:
        """Sao chép hình ảnh/video vào thư mục app_media của phần mềm để bảo toàn dữ liệu vĩnh viễn."""
        if not source_path:
            return source_path

        media_dir = os.path.abspath("app_media")
        os.makedirs(media_dir, exist_ok=True)

        # Nếu file đã nằm trong thư mục app_media thì không cần copy lại
        try:
            abs_source = os.path.abspath(source_path)
            if abs_source.startswith(media_dir):
                return abs_source
        except Exception:
            pass

        if not os.path.exists(source_path):
            return source_path

        base_name = os.path.basename(source_path)
        name, ext = os.path.splitext(base_name)

        # Tạo mã băm ngắn để tránh xung đột tên file
        try:
            with open(source_path, "rb") as f:
                h = hashlib.md5(f.read(16384)).hexdigest()[:6]
        except Exception:
            h = str(int(time.time()))[-6:]

        safe_name = f"{name}_{h}{ext}"
        target_path = os.path.join(media_dir, safe_name)

        try:
            if not os.path.exists(target_path):
                shutil.copy2(source_path, target_path)
            return target_path
        except Exception as e:
            print(f"[WARNING] Không thể sao chép media vào app_media: {e}")
            return source_path

    def on_add_media(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn hình ảnh hoặc video (Tự động lưu vào bộ nhớ phần mềm)", "", "Media Files (*.jpg *.jpeg *.png *.mp4 *.mov *.avi)"
        )
        if files:
            for f in files:
                saved_path = self.copy_to_app_media(f)
                if saved_path not in self.media_paths:
                    self.media_paths.append(saved_path)

                    size_text = ""
                    try:
                        sz = os.path.getsize(saved_path)
                        if sz > 1024 * 1024:
                            size_text = f"({sz / (1024 * 1024):.1f} MB)"
                        else:
                            size_text = f"({sz / 1024:.0f} KB)"
                    except Exception:
                        pass

                    item = QListWidgetItem(f"📁 {os.path.basename(saved_path)} {size_text}  [Đã lưu trong bộ nhớ phần mềm]")
                    item.setToolTip(saved_path)
                    self.list_media.addItem(item)

    def on_clear_media(self):
        self.media_paths.clear()
        self.list_media.clear()

    def on_save_campaign(self):
        title = self.txt_title.text().strip()
        content = self.txt_content.toPlainText().strip()
        
        # Tự động lọc bỏ \ufffc nếu có
        if '\ufffc' in content or '\ufffd' in content:
            content = content.replace('\ufffc', '🔹').replace('\ufffd', '🔹')
            self.txt_content.setText(content)

        if not title or not content:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng điền đầy đủ Tiêu đề và Nội dung bài đăng!")
            return

        # Đảm bảo toàn bộ media được copy vào app_media
        safe_media = []
        for p in self.media_paths:
            safe_p = self.copy_to_app_media(p)
            safe_media.append(safe_p)
        self.media_paths = safe_media

        self.db.save_campaign(title, content, self.media_paths)
        QMessageBox.information(self, "Thành công", f"Đã lưu mẫu nội dung '{title}'!\nCác file ảnh/video đã được lưu trữ an toàn trong thư mục phần mềm.")
        self.load_campaigns()

    def load_campaigns(self):
        self.list_campaigns.clear()
        campaigns = self.db.get_campaigns()
        for c in campaigns:
            item = QListWidgetItem(f"{c['title']} (Media: {len(c['media_paths'])})")
            item.setData(Qt.UserRole, c)
            self.list_campaigns.addItem(item)

    def on_select_campaign(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if data:
            self.txt_title.setText(data["title"])
            content = data["content"]
            if '\ufffc' in content or '\ufffd' in content:
                content = content.replace('\ufffc', '🔹').replace('\ufffd', '🔹')
            self.txt_content.setText(content)
            self.on_clear_media()
            self.media_paths = list(data["media_paths"])
            for f in self.media_paths:
                # Tự động sao chép vào app_media nếu file cũ còn tồn tại
                actual_path = self.copy_to_app_media(f)
                if os.path.exists(actual_path):
                    size_text = ""
                    try:
                        sz = os.path.getsize(actual_path)
                        size_text = f"({sz / (1024 * 1024):.1f} MB)" if sz > 1024 * 1024 else f"({sz / 1024:.0f} KB)"
                    except Exception:
                        pass
                    item = QListWidgetItem(f"📁 {os.path.basename(actual_path)} {size_text}  [Đã lưu an toàn]")
                else:
                    item = QListWidgetItem(f"⚠️ {os.path.basename(actual_path)}  [File không tồn tại]")
                item.setToolTip(actual_path)
                self.list_media.addItem(item)
            self.on_preview_spintax()

    def on_delete_campaign(self):
        item = self.list_campaigns.currentItem()
        if not item:
            return
        data = item.data(Qt.UserRole)
        if data:
            self.db.delete_campaign(data["id"])
            self.load_campaigns()
