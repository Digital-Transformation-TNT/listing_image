# Thông báo ra ngoài app (PySide6) — hướng dẫn tái sử dụng

Tài liệu này ghi lại tính năng **thông báo hiện ra ngoài app** (hiện cả khi đã
thu nhỏ tool), để gắn sang bất kỳ tool PySide6 nào khác.

- **Windows / Linux:** toast ở khay hệ thống (`QSystemTrayIcon.showMessage`).
- **macOS:** thông báo native qua `osascript` (bản `.app` ký ad-hoc thường KHÔNG
  hiện được toast của Qt → phải đi đường native). Chạy ở **thread phụ** nên
  không làm khựng giao diện; **osascript lỗi thì tự quay về toast của Qt**.
- Cả 2: **nháy taskbar (Win) / nảy Dock (Mac)** để gây chú ý; **bấm vào thông
  báo hoặc icon khay → mở lại app**.
- Có file `logo.ico` / `logo.icns` / `logo.png` cạnh app thì tự lấy làm icon
  khay + icon cửa sổ; không có thì dùng icon mặc định của hệ thống.

Có thể gọi khi: xong 1 bước cần thao tác tiếp, khi lỗi, khi dừng...

---

## Cách dùng nhanh (3 bước)

Copy file [`notifier.py`](notifier.py) vào project, rồi:

```python
from notifier import DesktopNotifier

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # ... dựng UI xong ...
        self.notifier = DesktopNotifier(self, app_name="Tên App Của Bạn")

    def on_done(self):                      # gọi khi 1 bước XONG
        self.notifier.notify("Đã xong", "Đã tạo xong 9 ảnh.")

    def on_error(self, msg):                # gọi khi LỖI
        self.notifier.notify("Có lỗi", msg, success=False)

    def closeEvent(self, e):
        self.notifier.shutdown()            # gỡ icon khay khi đóng
        e.accept()
```

**Lưu ý luồng nền (worker/QThread):** đừng gọi `notify()` trực tiếp từ thread
nền. Hãy phát `Signal` về GUI thread rồi gọi trong slot (giống mọi thao tác UI
của Qt). Ví dụ: `worker.done.connect(self.on_done)`.

---

## Toàn bộ code (nếu không muốn thêm file riêng)

Nếu muốn nhúng thẳng vào cửa sổ chính thay vì thêm `notifier.py`, dán các phần
sau vào class cửa sổ:

```python
import os, subprocess, sys, threading
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QSystemTrayIcon, QStyle, QApplication

IS_MAC = sys.platform == "darwin"

class MainWindow(QMainWindow):
    # thread phụ (osascript) báo về GUI thread khi cần toast dự phòng
    notify_fallback = Signal(str, str, bool)

# --- trong __init__, SAU khi dựng UI xong: ---
self._setup_tray()

# --- các method thêm vào class ---
def _setup_tray(self):
    self.tray = None
    self.notify_fallback.connect(self._show_tray_toast)
    try:
        icon = self.windowIcon()
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.setWindowIcon(icon)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip("Tên App")
            self.tray.activated.connect(self._on_tray_activated)
            self.tray.messageClicked.connect(self._raise_app)
            self.tray.show()
    except Exception:
        self.tray = None

def _on_tray_activated(self, reason):
    if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
        self._raise_app()

def _raise_app(self):
    try:
        self.showNormal(); self.raise_(); self.activateWindow()
    except Exception:
        pass

def _notify(self, title, text, success=True):        # gọi từ GUI thread
    if self.tray is not None:
        try: self.tray.setToolTip(f"Tên App — {title}")
        except Exception: pass
    if IS_MAC:
        # osascript ở thread phụ: không làm khựng UI, lỗi thì fallback
        threading.Thread(target=self._mac_notify_bg,
                         args=(title, text, success), daemon=True).start()
    else:
        self._show_tray_toast(title, text, success)
    try: QApplication.alert(self, 3000)
    except Exception: pass

def _show_tray_toast(self, title, text, success=True):   # CHỈ ở GUI thread
    icon = (QSystemTrayIcon.Information if success
            else QSystemTrayIcon.Warning)
    try:
        if self.tray is not None:
            self.tray.showMessage(title, text, icon, 10000)
    except Exception: pass

def _mac_notify_bg(self, title, text, success):          # THREAD PHỤ
    if not self._notify_mac_native(title, text):
        self.notify_fallback.emit(title, text, success)

@staticmethod
def _notify_mac_native(title, text) -> bool:
    def _esc(s): return (s or "").replace("\\","").replace('"',"'").replace("\n"," ")
    # đường dẫn tuyệt đối: app mở từ Finder có PATH tối giản
    exe = "/usr/bin/osascript" if os.path.exists("/usr/bin/osascript") else "osascript"
    try:
        p = subprocess.run(
            [exe, "-e",
             f'display notification "{_esc(text)}" with title "{_esc(title)}"'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        return p.returncode == 0
    except Exception:
        return False

# --- trong closeEvent: ---
try:
    if self.tray is not None: self.tray.hide()
except Exception: pass
```

> ⚠️ `osascript` trả về **0 kể cả khi người dùng đã tắt thông báo** trong System
> Settings (macOS nuốt im lặng). Nhánh dự phòng chỉ cứu được **lỗi cứng**: thiếu
> `osascript`, bị sandbox chặn, sai cú pháp AppleScript.

---

## Lưu ý ĐÓNG GÓI (quan trọng)

### macOS (.app qua PyInstaller)
- Trong spec `BUNDLE(...)` phải có `bundle_identifier`, ví dụ
  `bundle_identifier="com.congty.tenapp"` — để thông báo được gắn đúng danh tính app.
- Nên **ad-hoc codesign** sau khi build: `codesign --force --deep --sign - Ten.app`.
- **Không cần** khai báo quyền gì thêm cho `osascript display notification`
  (nó KHÔNG điều khiển app khác nên không cần quyền Automation).
- Lần đầu chạy, macOS có thể hỏi cho phép thông báo → chọn **Allow**. Nếu không
  thấy: **System Settings → Notifications** bật lên, và tắt **Do Not Disturb / Focus**.

### Windows (.exe qua PyInstaller)
- Không cần cấu hình thêm. Toast dùng khay hệ thống có sẵn.
- Không thấy toast? **Settings → Notifications** bật lên, tắt **Focus assist**.

### Icon (cả 2 hệ)
- Bỏ `logo.ico` (Windows) / `logo.icns` (macOS) / `logo.png` vào thư mục dự án
  là spec tự nhặt vào `datas` và code tự lấy làm icon khay + icon cửa sổ.
- Không có file logo thì dùng icon máy tính mặc định — thông báo vẫn chạy bình thường.

---

## Vì sao macOS dùng osascript thay vì toast Qt?

`QSystemTrayIcon.showMessage()` trên macOS đi qua UNUserNotificationCenter, yêu
cầu app có **chữ ký hợp lệ** — bản đóng gói ký **ad-hoc** (chưa mua Apple
Developer để notarize) thường **bị bỏ qua trong im lặng** (không hiện gì). Trong
khi `osascript display notification` là công cụ có SẴN trên mọi máy macOS và
luôn hiện được banner. Vì vậy code chọn native cho macOS, Qt toast cho Windows.

> Đánh đổi: thông báo osascript hiện dưới tên "Script Editor" (không phải tên
> app). Muốn hiện đúng tên app + icon thì phải **notarize** app (cần tài khoản
> Apple Developer $99/năm) rồi có thể chuyển macOS về dùng `showMessage` của Qt.
