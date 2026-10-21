from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar
)
from PySide6.QtCore import Qt, QPoint, Signal

class FloatingWidget(QWidget):
    show_main_signal = Signal()
    pause_signal = Signal()
    stop_signal = Signal()

    def __init__(self):
        super().__init__()
        self.drag_position = QPoint()
        self.init_ui()

    def init_ui(self):
        # Thiết lập cửa sổ nổi: Không viền, Luôn ở trên cùng, Thu nhỏ gọn
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        # Style sheet tối giản, hiện đại
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 8px;
                font-family: 'Segoe UI', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Arial', sans-serif;
            }
            QLabel {
                font-size: 11px;
                font-weight: bold;
                border: none;
            }
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #45475a;
            }
            QProgressBar {
                border: 1px solid #45475a;
                border-radius: 4px;
                text-align: center;
                font-size: 9px;
                height: 12px;
                background-color: #11111b;
            }
            QProgressBar::chunk {
                background-color: #89b4fa;
                border-radius: 3px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Title bar & Controls
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)

        lbl_title = QLabel("⚡ FB AUTO-POSTER")
        lbl_title.setStyleSheet("color: #89b4fa; font-weight: bold;")
        title_layout.addWidget(lbl_title)

        title_layout.addStretch()

        btn_show = QPushButton("🗔 Mở Giao Diện")
        btn_show.setToolTip("Mở lại cửa sổ chính")
        btn_show.clicked.connect(self.show_main_signal.emit)
        title_layout.addWidget(btn_show)

        layout.addLayout(title_layout)

        # Status text
        self.lbl_status = QLabel("Trạng thái: Sẵn sàng")
        self.lbl_status.setStyleSheet("color: #a6e3a1;")
        layout.addWidget(self.lbl_status)

        # Mini Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_pause = QPushButton("⏸️ Tạm Dừng")
        self.btn_pause.clicked.connect(self.pause_signal.emit)
        btn_layout.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("🛑 Dừng Hẳn")
        self.btn_stop.setStyleSheet("background-color: #f38ba8; color: #11111b;")
        self.btn_stop.clicked.connect(self.stop_signal.emit)
        btn_layout.addWidget(self.btn_stop)

        layout.addLayout(btn_layout)

        self.setFixedSize(260, 110)

    def update_status(self, text: str):
        self.lbl_status.setText(text)

    def update_progress(self, current: int, total: int):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)

    # Thao tác Kéo / Di chuyển Cửa sổ nổi bằng chuột
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
