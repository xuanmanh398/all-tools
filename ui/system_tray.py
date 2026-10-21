import os
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication, QStyle
from PySide6.QtCore import Signal, QObject

class SystemTrayManager(QObject):
    show_main_signal = Signal()
    toggle_floating_signal = Signal()
    toggle_pause_signal = Signal()
    exit_app_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tray_icon = QSystemTrayIcon(parent)

        from core.database import get_asset_path
        from PySide6.QtGui import QIcon
        icon_path = get_asset_path("icon.png")
        if not os.path.exists(icon_path):
            icon_path = get_asset_path("icon.ico")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)
            self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("Auto Post - Phần Mềm Đăng Bài Tự Động")

        # Tạo Context Menu
        self.menu = QMenu()

        self.act_show = self.menu.addAction("🗔 Mở Giao Diện Chính")
        self.act_show.triggered.connect(self.show_main_signal.emit)

        self.act_floating = self.menu.addAction("📌 Bật/Tắt Cửa Sổ Nổi")
        self.act_floating.triggered.connect(self.toggle_floating_signal.emit)

        self.menu.addSeparator()

        self.act_pause = self.menu.addAction("⏸️ Tạm Dừng / Tiếp Tục")
        self.act_pause.triggered.connect(self.toggle_pause_signal.emit)

        self.menu.addSeparator()

        self.act_exit = self.menu.addAction("❌ Thoát Ứng Dụng")
        self.act_exit.triggered.connect(self.exit_app_signal.emit)

        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

    def show(self):
        self.tray_icon.show()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick or reason == QSystemTrayIcon.Trigger:
            self.show_main_signal.emit()

    def send_notification(self, title: str, message: str):
        if self.tray_icon.isSystemTrayAvailable():
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.Information, 3000)
