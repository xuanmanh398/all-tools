from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame,
    QGridLayout, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from core.database import Database


class HomeDashboardTab(QWidget):
    # Signals để chuyển tab từ các nút thao tác nhanh
    switch_tab_signal = Signal(str)  # "fb_comment", "fb_poster", "fb_acc", "fb_group", "threads"

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(14)

        # -------------------------------------------------------------
        # 1. HERO BANNER CHÀO MỪNG HIỆN ĐẠI
        # -------------------------------------------------------------
        hero_frame = QFrame()
        hero_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1e1b4b, stop:0.5 #312e81, stop:1 #0f172a);
                border: 1px solid #4338ca;
                border-radius: 12px;
                padding: 18px 24px;
            }
        """)
        hf_layout = QHBoxLayout(hero_frame)

        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        lbl_welcome = QLabel("🚀 Chào mừng đến với Tools Marketing")
        lbl_welcome.setStyleSheet("color: #ffffff; font-size: 20px; font-weight: bold; border: none; background: transparent;")
        text_box.addWidget(lbl_welcome)

        lbl_sub = QLabel("Phần mềm tự động hóa marketing Facebook & Threads: Tự động comment seeding, Đăng bài nhóm, Nuôi nick đa tài khoản.")
        lbl_sub.setStyleSheet("color: #c7d2fe; font-size: 13px; border: none; background: transparent;")
        text_box.addWidget(lbl_sub)
        hf_layout.addLayout(text_box, 1)

        btn_quick_comment = QPushButton("💬 Mở Auto Comment Ngay")
        btn_quick_comment.setCursor(Qt.PointingHandCursor)
        btn_quick_comment.setFixedHeight(42)
        btn_quick_comment.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669);
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 8px;
                padding: 0 18px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:1 #047857);
            }
        """)
        btn_quick_comment.clicked.connect(lambda: self.switch_tab_signal.emit("fb_comment"))
        hf_layout.addWidget(btn_quick_comment)

        main_layout.addWidget(hero_frame)

        # -------------------------------------------------------------
        # 2. BỐN THẺ THỐNG KÊ TỔNG QUAN HỆ THỐNG
        # -------------------------------------------------------------
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(12)

        self.card_acc = self._create_stat_card("👥 Tài Khoản Facebook", "0", "Đã kết nối an toàn", "#3b82f6")
        self.card_comment = self._create_stat_card("💬 Auto Comment FB", "Sẵn sàng", "Comment UID / Nhóm / Keyword", "#10b981")
        self.card_groups = self._create_stat_card("📑 Nhóm Facebook", "0", "Nhóm đã quét tham gia", "#8b5cf6")
        self.card_threads = self._create_stat_card("📷 Tài Khoản Threads", "0", "Nền tảng Instagram Threads", "#f59e0b")

        stats_layout.addWidget(self.card_acc)
        stats_layout.addWidget(self.card_comment)
        stats_layout.addWidget(self.card_groups)
        stats_layout.addWidget(self.card_threads)

        main_layout.addLayout(stats_layout)

        # -------------------------------------------------------------
        # 3. DANH MỤC TÍNH NĂNG NHANH (QUICK ACCESS CARDS)
        # -------------------------------------------------------------
        lbl_section_title = QLabel("⚡ TÍNH NĂNG NỔI BẬT & THAO TÁC 1 CHẠM")
        lbl_section_title.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: bold; margin-top: 6px;")
        main_layout.addWidget(lbl_section_title)

        grid_actions = QGridLayout()
        grid_actions.setSpacing(12)

        # Action Card 1: Auto Comment FB (Giống trên video)
        btn_action_comment = self._create_action_card(
            icon="💬",
            title="Tự Động Comment Facebook (Mới)",
            desc="Tự động thả Like và bình luận bài viết theo UID, bài viết trong Nhóm hoặc Từ khóa. Hỗ trợ Spintax xoay nội dung chống spam.",
            btn_text="Khởi Chạy Auto Comment  ➔",
            color="#10b981",
            handler=lambda: self.switch_tab_signal.emit("fb_comment")
        )
        grid_actions.addWidget(btn_action_comment, 0, 0)

        # Action Card 2: Group Auto Poster
        btn_action_post = self._create_action_card(
            icon="🚀",
            title="Đăng Bài Hàng Loạt Lên Nhóm FB",
            desc="Đăng bài viết kèm ảnh/video lên hàng trăm hội nhóm Facebook theo lịch trình hẹn giờ, hỗ trợ đăng với tư cách Fanpage.",
            btn_text="Mở Đăng Bài Nhóm  ➔",
            color="#3b82f6",
            handler=lambda: self.switch_tab_signal.emit("fb_poster")
        )
        grid_actions.addWidget(btn_action_post, 0, 1)

        # Action Card 3: Account Manager
        btn_action_acc = self._create_action_card(
            icon="👥",
            title="Quản Lý Tài Khoản Facebook",
            desc="Đăng nhập không giới hạn nick Facebook bằng Cookie hoặc mở trình duyệt trực tiếp 1 lần, lưu phiên làm việc tự động.",
            btn_text="Quản Lý Tài Khoản  ➔",
            color="#6366f1",
            handler=lambda: self.switch_tab_signal.emit("fb_acc")
        )
        grid_actions.addWidget(btn_action_acc, 1, 0)

        # Action Card 4: Threads Mass Post
        btn_action_threads = self._create_action_card(
            icon="📷",
            title="Đăng Bài Tự Động Lên Threads",
            desc="Tự động nuôi tài khoản và đăng bài viết, hình ảnh, bài bình luận hàng loạt lên nền tảng Instagram Threads.",
            btn_text="Chuyển Sang Threads  ➔",
            color="#f59e0b",
            handler=lambda: self.switch_tab_signal.emit("threads")
        )
        grid_actions.addWidget(btn_action_threads, 1, 1)

        main_layout.addLayout(grid_actions)

        # -------------------------------------------------------------
        # 4. HƯỚNG DẪN BẮT ĐẦU NHANH 3 BƯỚC
        # -------------------------------------------------------------
        guide_box = QFrame()
        guide_box.setStyleSheet("""
            QFrame {
                background-color: #111625;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 12px 16px;
            }
        """)
        gb_layout = QVBoxLayout(guide_box)
        gb_layout.setSpacing(6)

        lbl_guide_title = QLabel("💡 Hướng dẫn bắt đầu nhanh:")
        lbl_guide_title.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px; border: none;")
        gb_layout.addWidget(lbl_guide_title)

        steps_text = QLabel(
            "• Bước 1: Vào mục '👥 Quản lý tài khoản' để nạp Cookie hoặc mở trình duyệt đăng nhập tài khoản Facebook.\n"
            "• Bước 2: Vào mục '💬 Auto Comment FB', chọn phương thức bình luận (theo Link bài viết, Nhóm hoặc Từ khóa) và soạn nội dung Spintax.\n"
            "• Bước 3: Bấm nút '▶️ Bắt đầu chạy comment' để phần mềm tự động tương tác và bình luận an toàn."
        )
        steps_text.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.5; border: none;")
        gb_layout.addWidget(steps_text)

        main_layout.addWidget(guide_box)
        main_layout.addStretch()

        self.refresh_stats()

    def _create_stat_card(self, title: str, value: str, sub: str, accent_color: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: #111625;
                border: 1px solid #1e293b;
                border-left: 4px solid {accent_color};
                border-radius: 8px;
                padding: 10px 14px;
            }}
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("color: #94a3b8; font-size: 12px; border: none;")
        c_layout.addWidget(lbl_t)

        lbl_v = QLabel(value)
        lbl_v.setObjectName("val")
        lbl_v.setStyleSheet(f"color: #ffffff; font-size: 20px; font-weight: bold; border: none; margin: 2px 0;")
        c_layout.addWidget(lbl_v)

        lbl_s = QLabel(sub)
        lbl_s.setStyleSheet("color: #64748b; font-size: 11px; border: none;")
        c_layout.addWidget(lbl_s)
        return card

    def _create_action_card(self, icon: str, title: str, desc: str, btn_text: str, color: str, handler) -> QFrame:
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #111625;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 12px 14px;
            }
            QFrame:hover {
                border: 1px solid #334155;
                background-color: #141c2e;
            }
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setSpacing(6)

        header_row = QHBoxLayout()
        lbl_icon = QLabel(icon)
        lbl_icon.setStyleSheet("font-size: 20px; border: none;")
        header_row.addWidget(lbl_icon)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: bold; border: none;")
        header_row.addWidget(lbl_title, 1)
        c_layout.addLayout(header_row)

        lbl_desc = QLabel(desc)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #94a3b8; font-size: 11px; border: none; min-height: 34px;")
        c_layout.addWidget(lbl_desc)

        btn = QPushButton(btn_text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(32)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #1e293b;
                color: {color};
                font-weight: bold;
                border: 1px solid {color};
                border-radius: 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {color};
                color: #ffffff;
            }}
        """)
        btn.clicked.connect(handler)
        c_layout.addWidget(btn)

        return card

    def refresh_stats(self):
        try:
            fb_accs = len(self.db.get_accounts())
            val_lbl = self.card_acc.findChild(QLabel, "val")
            if val_lbl:
                val_lbl.setText(f"{fb_accs} Tài khoản")

            groups = len(self.db.get_groups())
            val_lbl = self.card_groups.findChild(QLabel, "val")
            if val_lbl:
                val_lbl.setText(f"{groups} Nhóm")

            th_accs = len(self.db.get_threads_accounts())
            val_lbl = self.card_threads.findChild(QLabel, "val")
            if val_lbl:
                val_lbl.setText(f"{th_accs} Tài khoản")
        except Exception:
            pass
