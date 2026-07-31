"""Test THÔNG BÁO RA NGOÀI APP (Windows + macOS) và mở thư mục kết quả.

Kiểm tra 2 đường đi:
  - Windows/Linux → toast của khay hệ thống (QSystemTrayIcon.showMessage).
  - macOS         → osascript native, chạy ở thread phụ; osascript LỖI thì
                    phải quay về toast của Qt (không được mất thông báo).
Kèm: escape AppleScript, và nút "mở thư mục kết quả" đúng lệnh theo từng OS
(os.startfile chỉ có trên Windows).

Chạy:  python tests/test_notify.py
"""
from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# GUI chạy không màn hình để test được trên CI/nền.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication      # noqa: E402
import ui_listing.window as window_mod          # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f"  [{extra}]" if extra and not cond else ""))


def _pump(app, want, timeout=3.0):
    """Chờ signal từ thread phụ về tới GUI thread (có giới hạn thời gian)."""
    t0 = time.time()
    while not want() and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()


def main():
    app = QApplication.instance() or QApplication([])
    win = window_mod.MainWindow()

    toasts = []
    win._show_tray_toast = lambda t, x, s=True: toasts.append((t, x, s))

    # ---- 1) Nhánh Windows/Linux: toast khay hệ thống ---------------- #
    window_mod.IS_MAC = False
    win._notify("Đã tạo ảnh xong", "Xong 9/9 ảnh.", success=True)
    win._notify("Tạo ảnh LỖI", "hết lượt tài khoản", success=False)
    check("Windows: mỗi lần gọi bắn đúng 1 toast", len(toasts) == 2, str(toasts))
    check("Windows: giữ nguyên tiêu đề/nội dung",
          toasts[0][0] == "Đã tạo ảnh xong" and toasts[0][1] == "Xong 9/9 ảnh.")
    check("Windows: lỗi thì success=False (icon cảnh báo)", toasts[1][2] is False)

    # ---- 2) Nhánh macOS: osascript chạy OK -------------------------- #
    cmds, rc = [], [0]
    def fake_run(cmd, **_kw):
        cmds.append(cmd)
        return types.SimpleNamespace(returncode=rc[0])
    real_run = window_mod.subprocess.run
    window_mod.subprocess.run = fake_run
    window_mod.IS_MAC = True

    toasts.clear()
    win._notify("Đã sửa ảnh xong", 'ảnh "A" \\ B\nxuống dòng', success=True)
    _pump(app, lambda: bool(cmds))
    time.sleep(0.2)
    app.processEvents()
    check("macOS: có gọi osascript", bool(cmds), str(cmds))
    script = cmds[-1][2] if cmds else ""
    check("macOS: dùng lệnh display notification",
          script.startswith("display notification "), script)
    check("macOS: escape hết ký tự phá cú pháp AppleScript",
          "\n" not in script and "\\" not in script
          and script.count('"') == 4, script)
    check("macOS: osascript OK thì KHÔNG bắn toast trùng", toasts == [], str(toasts))

    # ---- 3) Nhánh macOS: osascript LỖI → toast dự phòng ------------- #
    rc[0] = 1
    toasts.clear()
    win._notify("Đã dừng", "dừng theo yêu cầu", success=False)
    _pump(app, lambda: bool(toasts))
    check("macOS: osascript lỗi → có toast dự phòng", bool(toasts), str(toasts))
    check("macOS: toast dự phòng giữ đúng nội dung + success",
          toasts[:1] == [("Đã dừng", "dừng theo yêu cầu", False)], str(toasts))

    # ---- 4) Không có osascript (Exception) → vẫn không crash -------- #
    def boom(*_a, **_k):
        raise FileNotFoundError("no osascript")
    window_mod.subprocess.run = boom
    toasts.clear()
    win._notify("Xong", "nội dung", success=True)
    _pump(app, lambda: bool(toasts))
    check("macOS: thiếu osascript → vẫn có toast dự phòng", bool(toasts), str(toasts))
    window_mod.subprocess.run = real_run

    # ---- 5) Mở thư mục kết quả đúng lệnh theo OS -------------------- #
    opened = []
    real_popen = window_mod.subprocess.Popen
    window_mod.subprocess.Popen = lambda cmd, *_a, **_k: opened.append(cmd)
    win.session_dir = str(Path(__file__).resolve().parent)

    window_mod.IS_MAC, window_mod.IS_WIN = True, False
    win._open_dir()
    check("macOS: mở thư mục bằng /usr/bin/open",
          opened[-1:] == [["/usr/bin/open", win.session_dir]], str(opened))

    window_mod.IS_MAC, window_mod.IS_WIN = False, False
    win._open_dir()
    check("Linux: mở thư mục bằng xdg-open",
          opened[-1:] == [["xdg-open", win.session_dir]], str(opened))

    window_mod.subprocess.Popen = real_popen
    check("Windows: có os.startfile để mở thư mục",
          hasattr(os, "startfile") or sys.platform != "win32")

    # ---- 6) Dọn icon khay khi đóng app ------------------------------ #
    win.session_dir = ""
    hidden = []
    if win.tray is not None:
        win.tray.hide = lambda: hidden.append(True)
    win.close()
    check("Đóng app thì gỡ icon khay",
          win.tray is None or hidden == [True])

    print(f"\n==> {len(PASS)} passed, {len(FAIL)} failed / {len(PASS)+len(FAIL)} total")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
