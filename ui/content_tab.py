import os
import subprocess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QTextEdit, QLabel, QListWidget, QGroupBox, QMessageBox, QFileDialog,
    QSplitter, QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from core.database import Database
from core.spintax_parser import SpintaxParser
from core.excel_loader import (
    load_posts_from_excel,
    get_configured_excel_path,
    set_configured_excel_path,
    DEFAULT_EXCEL_PATH
)


class ContentTab(QWidget):
    """
    Tab Quản Lý Mẫu Nội Dung Bài Viết Từ File Excel (.xlsx):
    - Cột A: Nội dung bài viết (hỗ trợ văn bản nhiều dòng, Emoji, Spintax {A|B|C})
    - Cột B: Đường dẫn Folder chứa hình ảnh / video của bài viết đó
    Khi đăng bài sẽ tự động lấy lần lượt từ trên xuống dưới (Mẫu #1 -> Mẫu #N) và lặp vòng liên tục.
    """
    excel_changed = Signal(str)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.excel_posts = []
        self.init_ui()
        self.load_campaigns()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # 1. Thanh chọn & nạp File Excel (.xlsx)
        excel_box = QGroupBox("1. Nguồn Mẫu Bài Viết Từ File Excel (Cột A: Nội Dung Bài Viết | Cột B: Folder Chứa Hình Ảnh)")
        e_layout = QVBoxLayout(excel_box)
        e_layout.setContentsMargins(12, 10, 12, 10)
        e_layout.setSpacing(6)

        path_row = QHBoxLayout()
        lbl_path = QLabel("📄 Đường dẫn File Excel (.xlsx):")
        lbl_path.setStyleSheet("font-weight: bold; color: #cbd5e1;")
        path_row.addWidget(lbl_path)

        self.txt_excel_path = QLineEdit()
        self.txt_excel_path.setPlaceholderText(f"Ví dụ: {DEFAULT_EXCEL_PATH}")
        self.txt_excel_path.setStyleSheet("font-size: 13px; padding: 6px; background-color: #0b0f19; color: #f8fafc; border: 1px solid #334155; border-radius: 5px;")
        self.txt_excel_path.setText(get_configured_excel_path(self.db))
        self.txt_excel_path.editingFinished.connect(self.on_path_edited)
        path_row.addWidget(self.txt_excel_path, stretch=1)

        btn_browse = QPushButton("📂 Chọn File Excel...")
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.setStyleSheet("background-color: #4f46e5; color: white; font-weight: bold; padding: 6px 14px; border-radius: 5px;")
        btn_browse.clicked.connect(self.on_browse_excel)
        path_row.addWidget(btn_browse)

        btn_reload = QPushButton("🔄 Đọc Lại File Excel")
        btn_reload.setCursor(Qt.PointingHandCursor)
        btn_reload.setStyleSheet("background-color: #0288d1; color: white; font-weight: bold; padding: 6px 14px; border-radius: 5px;")
        btn_reload.clicked.connect(self.load_campaigns)
        path_row.addWidget(btn_reload)

        btn_open_excel = QPushButton("📝 Mở File Excel")
        btn_open_excel.setCursor(Qt.PointingHandCursor)
        btn_open_excel.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 12px; border-radius: 5px;")
        btn_open_excel.clicked.connect(self.on_open_excel_file)
        path_row.addWidget(btn_open_excel)

        e_layout.addLayout(path_row)

        info_row = QHBoxLayout()
        self.lbl_summary = QLabel("Đang kiểm tra file Excel...")
        self.lbl_summary.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 12px;")
        info_row.addWidget(self.lbl_summary)
        info_row.addStretch()

        lbl_rule = QLabel("🔁 Quy tắc đăng: Lần lượt theo thứ tự (Mẫu #1 ➔ Mẫu #2 ➔ ... ➔ Hết danh sách tự quay lại Mẫu #1)")
        lbl_rule.setStyleSheet("color: #89b4fa; font-size: 12px; font-style: italic;")
        info_row.addWidget(lbl_rule)
        e_layout.addLayout(info_row)

        main_layout.addWidget(excel_box)

        # 2. Splitter: Bảng danh sách các dòng trong Excel (Trái) & Xem chi tiết mẫu (Phải)
        splitter = QSplitter(Qt.Horizontal)

        # Bên trái: Bảng danh sách mẫu đọc từ Excel
        table_box = QGroupBox("2. Danh Sách Mẫu Bài Viết Trong File Excel (Theo Thứ Tự Đăng Lần Lượt)")
        t_layout = QVBoxLayout(table_box)
        t_layout.setContentsMargins(8, 8, 8, 8)

        self.table_posts = QTableWidget()
        self.table_posts.setColumnCount(4)
        self.table_posts.setHorizontalHeaderLabels([
            "Thứ Tự",
            "Nội Dung Bài Viết (Cột A)",
            "Folder Hình Ảnh (Cột B)",
            "Số Ảnh / Video"
        ])
        header = self.table_posts.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_posts.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_posts.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_posts.itemSelectionChanged.connect(self.on_row_selected)
        t_layout.addWidget(self.table_posts)

        splitter.addWidget(table_box)

        # Bên phải: Xem trước chi tiết dòng đang chọn
        detail_box = QGroupBox("3. Xem Trước Chi Tiết Mẫu Đang Chọn")
        d_layout = QVBoxLayout(detail_box)
        d_layout.setContentsMargins(10, 10, 10, 10)
        d_layout.setSpacing(6)

        self.lbl_detail_title = QLabel("Chọn một dòng bên trái để xem chi tiết")
        self.lbl_detail_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #89b4fa;")
        d_layout.addWidget(self.lbl_detail_title)

        emoji_font = QFont("Segoe UI Emoji", 11)
        self.txt_preview_content = QTextEdit()
        self.txt_preview_content.setFont(emoji_font)
        self.txt_preview_content.setReadOnly(True)
        self.txt_preview_content.setStyleSheet("font-size: 13px; line-height: 1.45; padding: 8px; background-color: #0b0f19; color: #f8fafc; border: 1px solid #1e293b; border-radius: 6px;")
        d_layout.addWidget(self.txt_preview_content, stretch=2)

        btn_spin_bar = QHBoxLayout()
        btn_spin = QPushButton("👁️ Xem Thử Biến Thể Spintax")
        btn_spin.setStyleSheet("background-color: #0288d1; color: white; font-weight: bold; padding: 5px 12px; border-radius: 4px;")
        btn_spin.clicked.connect(self.on_preview_spintax)
        btn_spin_bar.addWidget(btn_spin)

        self.btn_open_folder = QPushButton("📂 Mở Folder Ảnh Của Mẫu Này")
        self.btn_open_folder.setStyleSheet("background-color: #334155; color: #f8fafc; font-weight: bold; padding: 5px 12px; border-radius: 4px;")
        self.btn_open_folder.clicked.connect(self.on_open_selected_folder)
        btn_spin_bar.addWidget(self.btn_open_folder)
        btn_spin_bar.addStretch()
        d_layout.addLayout(btn_spin_bar)

        self.lbl_folder_detail = QLabel("📁 Tệp hình ảnh / video trong Folder (Cột B):")
        self.lbl_folder_detail.setStyleSheet("font-weight: bold; color: #cbd5e1;")
        d_layout.addWidget(self.lbl_folder_detail)

        self.list_media = QListWidget()
        self.list_media.setMaximumHeight(140)
        self.list_media.setStyleSheet("font-size: 12px; background-color: #0b0f19; color: #cbd5e1; border: 1px solid #1e293b; border-radius: 5px;")
        d_layout.addWidget(self.list_media, stretch=1)

        splitter.addWidget(detail_box)
        splitter.setSizes([640, 420])
        main_layout.addWidget(splitter, stretch=1)

    def on_path_edited(self):
        new_path = self.txt_excel_path.text().strip()
        if new_path:
            set_configured_excel_path(self.db, new_path)
            self.load_campaigns()
            self.excel_changed.emit(new_path)

    def on_browse_excel(self):
        cur_path = self.txt_excel_path.text().strip()
        start_dir = os.path.dirname(cur_path) if (cur_path and os.path.exists(os.path.dirname(cur_path))) else r"E:\Affiliate"
        if not os.path.exists(start_dir):
            start_dir = ""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn File Excel Mẫu Bài Viết (.xlsx)",
            start_dir,
            "Excel Files (*.xlsx);;All Files (*.*)"
        )
        if file_path:
            self.txt_excel_path.setText(file_path)
            set_configured_excel_path(self.db, file_path)
            self.load_campaigns()
            self.excel_changed.emit(file_path)

    def on_open_excel_file(self):
        path = self.txt_excel_path.text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Không tìm thấy tệp", f"File Excel không tồn tại tại đường dẫn:\n{path}")
            return
        try:
            os.startfile(path)
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể mở file Excel: {e}")

    def on_open_selected_folder(self):
        row = self.table_posts.currentRow()
        if row < 0 or row >= len(self.excel_posts):
            QMessageBox.information(self, "Thông báo", "Vui lòng chọn một mẫu bài viết trong bảng trước!")
            return
        folder = self.excel_posts[row].get("folder_path", "")
        if not folder:
            QMessageBox.warning(self, "Thông báo", "Mẫu này không khai báo đường dẫn Folder ở Cột B!")
            return
        if not os.path.exists(folder):
            reply = QMessageBox.question(
                self,
                "Thư mục chưa tồn tại",
                f"Thư mục '{folder}' hiện chưa tồn tại trên ổ đĩa.\nBạn có muốn tạo mới thư mục này và mở ngay không?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                try:
                    os.makedirs(folder, exist_ok=True)
                    os.startfile(folder)
                    self.load_campaigns()
                except Exception as e:
                    QMessageBox.warning(self, "Lỗi", f"Không thể tạo thư mục: {e}")
            return
        try:
            os.startfile(folder)
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể mở thư mục: {e}")

    def load_campaigns(self):
        excel_path = self.txt_excel_path.text().strip() or get_configured_excel_path(self.db)
        self.txt_excel_path.setText(excel_path)
        set_configured_excel_path(self.db, excel_path)

        if not os.path.exists(excel_path):
            self.excel_posts = []
            self.table_posts.setRowCount(0)
            self.lbl_summary.setText(f"⚠️ Không tìm thấy file Excel tại: {excel_path}")
            self.lbl_summary.setStyleSheet("color: #f38ba8; font-weight: bold; font-size: 12px;")
            return

        try:
            self.excel_posts = load_posts_from_excel(excel_path)
        except Exception as e:
            self.excel_posts = []
            self.table_posts.setRowCount(0)
            self.lbl_summary.setText(f"❌ Lỗi đọc file Excel: {str(e)}")
            self.lbl_summary.setStyleSheet("color: #f38ba8; font-weight: bold; font-size: 12px;")
            return

        self.table_posts.setRowCount(len(self.excel_posts))
        valid_folder_count = 0
        total_images = 0

        for r_idx, post in enumerate(self.excel_posts):
            seq_item = QTableWidgetItem(f"Mẫu #{post['index']}")
            seq_item.setTextAlignment(Qt.AlignCenter)
            seq_item.setForeground(QColor("#89b4fa"))
            self.table_posts.setItem(r_idx, 0, seq_item)

            content_preview = (post.get("content") or "").replace("\n", " ↵ ")
            if len(content_preview) > 95:
                content_preview = content_preview[:92] + "..."
            content_item = QTableWidgetItem(content_preview)
            content_item.setToolTip(post.get("content") or "")
            self.table_posts.setItem(r_idx, 1, content_item)

            folder_str = post.get("folder_path") or "(Trống)"
            folder_item = QTableWidgetItem(folder_str)
            folder_item.setToolTip(folder_str)
            self.table_posts.setItem(r_idx, 2, folder_item)

            media_count = len(post.get("raw_media_paths") or [])
            total_images += media_count
            if post.get("folder_exists"):
                valid_folder_count += 1
                if media_count > 0:
                    st_text = f"🟢 {media_count} ảnh/video"
                    st_color = QColor("#a6e3a1")
                else:
                    st_text = "🟡 0 tệp (Folder trống)"
                    st_color = QColor("#f9e2af")
            else:
                st_text = "⚪ Chưa có folder"
                st_color = QColor("#94a3b8")

            count_item = QTableWidgetItem(st_text)
            count_item.setForeground(st_color)
            count_item.setTextAlignment(Qt.AlignCenter)
            self.table_posts.setItem(r_idx, 3, count_item)

        self.lbl_summary.setText(
            f"✅ Đã nạp {len(self.excel_posts)} mẫu bài viết từ '{os.path.basename(excel_path)}' "
            f"| 📂 {valid_folder_count}/{len(self.excel_posts)} folder tồn tại | 🖼️ Tổng {total_images} ảnh/video"
        )
        self.lbl_summary.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 12px;")

        if self.excel_posts:
            self.table_posts.selectRow(0)

    def on_row_selected(self):
        row = self.table_posts.currentRow()
        if row < 0 or row >= len(self.excel_posts):
            return
        post = self.excel_posts[row]
        self.lbl_detail_title.setText(f"📋 {post['title']} (Dòng {post['excel_row']} trong Excel)")
        self.txt_preview_content.setPlainText(post.get("content", ""))

        folder = post.get("folder_path") or "(Chưa khai báo)"
        raw_files = post.get("raw_media_paths") or []
        self.lbl_folder_detail.setText(f"📁 Folder Cột B: {folder} ({len(raw_files)} tệp)")

        self.list_media.clear()
        if not post.get("folder_exists"):
            item = QListWidgetItem(f"⚠️ Thư mục '{folder}' hiện chưa tồn tại trên ổ đĩa (Bấm 'Mở Folder' để tạo nhanh)")
            item.setForeground(QColor("#f9e2af"))
            self.list_media.addItem(item)
        elif not raw_files:
            item = QListWidgetItem(f"ℹ️ Thư mục '{folder}' đang trống (Chưa có ảnh/video)")
            item.setForeground(QColor("#94a3b8"))
            self.list_media.addItem(item)
        else:
            for f in raw_files:
                sz_str = ""
                try:
                    sz = os.path.getsize(f)
                    sz_str = f"({sz / (1024 * 1024):.1f} MB)" if sz > 1024 * 1024 else f"({sz / 1024:.0f} KB)"
                except Exception:
                    pass
                item = QListWidgetItem(f"🖼️ {os.path.basename(f)} {sz_str}")
                item.setToolTip(f)
                self.list_media.addItem(item)

    def on_preview_spintax(self):
        text = self.txt_preview_content.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Thông báo", "Mẫu đang chọn không có nội dung văn bản!")
            return
        variations = SpintaxParser.preview_variations(text, count=3)
        preview_str = "\n\n".join(f"=== Biến thể #{i} ===\n{v}" for i, v in enumerate(variations, 1))
        QMessageBox.information(self, "Xem Thử Biến Thể Spintax", preview_str)
