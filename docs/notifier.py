"""Thông báo RA NGOÀI app cho ứng dụng PySide6 — Windows + macOS + Linux.

Module ĐỘC LẬP, copy nguyên file này sang tool khác là dùng được (không phụ
thuộc gì ngoài PySide6). Hiện thông báo ở góc màn hình KỂ CẢ khi app đã thu nhỏ,
kèm nháy taskbar (Windows) / nảy Dock (macOS). Bấm vào thông báo → mở lại app.

Vì sao tách 2 đường theo hệ điều hành:
- Windows/Linux: dùng toast của khay hệ thống (QSystemTrayIcon.showMessage) —
  chạy tốt, đúng tên/icon app.
- macOS: dùng thông báo NATIVE qua `osascript`. Bản .app đóng gói kiểu ký ad-hoc
  (chưa notarize) THƯỜNG KHÔNG hiện được toast của Qt trên macOS, nên đi đường
  native cho chắc ăn. osascript chạy ở THREAD PHỤ để không làm khựng giao diện;
  nếu nó lỗi thì tự quay về toast của Qt (đỡ mất trắng thông báo).

CÁCH DÙNG (3 bước):
    from notifier import DesktopNotifier

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            ...                                   # dựng UI xong
            self.notifier = DesktopNotifier(self, app_name="Tên App Của Bạn")

        def on_task_done(self):                   # gọi khi 1 bước XONG
            self.notifier.notify("Đã xong", "Đã tạo xong 9 ảnh.")

        def on_task_error(self, msg):             # gọi khi LỖI
            self.notifier.notify("Có lỗi", msg, success=False)

        def closeEvent(self, e):
            self.notifier.shutdown()              # gỡ icon khay khi đóng app
            e.accept()
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon, QStyle, QApplication

IS_MAC = sys.platform == "darwin"


def app_icon(*names: str) -> QIcon:
    """Tìm file icon (vd "logo.ico", "logo.png") cạnh app / trong bản đóng gói.

    Không thấy thì trả về QIcon rỗng để chỗ gọi dùng icon mặc định hệ thống."""
    if not names:
        names = ("logo.icns", "logo.png", "logo.ico") if IS_MAC else \
                ("logo.ico", "logo.png", "logo.icns")
    roots = []
    meipass = getattr(sys, "_MEIPASS", "")     # thư mục tài nguyên khi PyInstaller
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(__file__).resolve().parent)
    for root in roots:
        for name in names:
            try:
                p = root / name
                if p.is_file():
                    ic = QIcon(str(p))
                    if not ic.isNull():
                        return ic
            except Exception:
                pass
    return QIcon()


class DesktopNotifier(QObject):
    """Bắn thông báo ngoài app. Tạo 1 lần trong cửa sổ chính rồi gọi .notify()."""

    # thread phụ (osascript trên macOS) báo về GUI thread khi cần toast dự phòng
    _fallback = Signal(str, str, bool)

    def __init__(self, window, app_name: str = "App"):
        # window: cửa sổ chính (QMainWindow/QWidget) để nháy taskbar + mở lại.
        super().__init__(window)
        self.window = window
        self.app_name = app_name
        self.tray = None
        self._fallback.connect(self._show_tray_toast)
        try:
            icon = window.windowIcon()
            if icon.isNull():
                icon = app_icon()
            if icon.isNull():
                # chưa có file logo → mượn icon chuẩn của hệ thống
                icon = window.style().standardIcon(QStyle.SP_ComputerIcon)
            window.setWindowIcon(icon)
            # macOS/Windows đều có "system tray" (Windows: khay đồng hồ,
            # macOS: menu bar). Có tray thì bấm icon mở lại được app.
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.tray = QSystemTrayIcon(icon, window)
                self.tray.setToolTip(app_name)
                self.tray.activated.connect(self._on_activated)
                self.tray.messageClicked.connect(self.raise_window)
                self.tray.show()
        except Exception:
            self.tray = None

    # ------------------------------------------------------------------ #
    def notify(self, title: str, text: str, success: bool = True):
        """Hiện 1 thông báo ngoài app + gây chú ý (nháy taskbar / nảy Dock).

        CHỈ gọi từ GUI thread (từ worker thì phát Signal về rồi gọi trong slot)."""
        if self.tray is not None:
            try:
                self.tray.setToolTip(f"{self.app_name} — {title}")
            except Exception:
                pass
        if IS_MAC:
            try:
                threading.Thread(target=self._mac_notify_bg,
                                 args=(title, text, success),
                                 daemon=True).start()
            except Exception:
                self._show_tray_toast(title, text, success)
        else:
            self._show_tray_toast(title, text, success)
        try:
            QApplication.alert(self.window, 3000)  # nháy taskbar / nảy Dock
        except Exception:
            pass

    def _show_tray_toast(self, title: str, text: str, success: bool = True):
        """Toast của khay hệ thống (Qt). CHỈ gọi từ GUI thread."""
        icon = (QSystemTrayIcon.Information if success
                else QSystemTrayIcon.Warning)
        try:
            if self.tray is not None:
                self.tray.showMessage(title, text, icon, 10000)  # 10s
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def raise_window(self):
        """Đưa cửa sổ app trở lại (khi bấm vào thông báo / icon khay)."""
        try:
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()
        except Exception:
            pass

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.raise_window()

    # ------------------------------------------------------------------ #
    def _mac_notify_bg(self, title: str, text: str, success: bool):
        """Chạy ở THREAD PHỤ: bắn thông báo native macOS, lỗi thì báo về GUI.

        Lưu ý: osascript trả về 0 kể cả khi người dùng đã TẮT thông báo trong
        System Settings (macOS nuốt im lặng) — nhánh dự phòng chỉ cứu được các
        lỗi cứng: thiếu/không chạy được osascript, bị sandbox chặn..."""
        if not self._notify_mac_native(title, text):
            try:
                self._fallback.emit(title, text, success)
            except Exception:
                pass

    @staticmethod
    def _notify_mac_native(title: str, text: str) -> bool:
        """Thông báo native macOS qua osascript. True nếu chạy trót lọt."""
        def _esc(s: str) -> str:
            # bỏ ký tự phá cú pháp AppleScript
            return (s or "").replace("\\", "").replace('"', "'").replace("\n", " ")
        # đường dẫn tuyệt đối: app mở từ Finder có PATH tối giản, đừng phụ thuộc PATH
        exe = "/usr/bin/osascript" if os.path.exists("/usr/bin/osascript") else "osascript"
        try:
            script = (f'display notification "{_esc(text)}" '
                      f'with title "{_esc(title)}"')
            p = subprocess.run([exe, "-e", script],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=10)
            return p.returncode == 0
        except Exception:
            return False

    def shutdown(self):
        """Gỡ icon khay khi đóng app (gọi trong closeEvent)."""
        try:
            if self.tray is not None:
                self.tray.hide()
        except Exception:
            pass
