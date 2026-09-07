"""TNT Listing Image — app PySide6 (entry point).

Chạy:  python app_listing.py
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

import tnt_track
from tnt_license import check_license

# Khoá tool trong nhật ký sử dụng — ĐỂ RIÊNG với "listing_image" của bản web,
# gộp chung thì bảng "Chi tiết theo tool" cộng số của hai bản làm một.
FEATURE = "listing_image_app"
from ui_listing.theme import STYLE
from ui_listing.window import MainWindow
from config import migrate_old_profiles


def main():
    # BẢO MẬT LICENSE — kiểm trước MỌI thứ khác. Sai/thiếu license → thoát ngay.
    info = check_license("TNT_Listing")
    # Chỉ ĐỌC tên nhân viên đã ký sẵn trong license.
    tnt_track.init(FEATURE, license_info=info, tool="TNT_Listing")
    # Chuyển profile cũ (cạnh app) sang ổ C 1 lần → update app vẫn giữ login.
    migrate_old_profiles()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("TNT Listing Image")
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    # căn GIỮA màn hình
    try:
        scr = app.primaryScreen().availableGeometry()
        fg = win.frameGeometry()
        fg.moveCenter(scr.center())
        win.move(fg.topLeft())
    except Exception:
        pass
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
