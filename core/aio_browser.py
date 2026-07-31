"""Trình duyệt Playwright ASYNC — 1 profile, nhiều TAB chạy song song.

Async để có thể lái nhiều tab ChatGPT cùng lúc (asyncio.gather) → tạo ảnh
song song, nhanh hơn nhiều so với tuần tự. Selector/logic port từ bản sync
đã kiểm chứng thực chiến (20/20 ảnh).

CHẠY NGẦM (hidden) — KHÁC NHAU THEO HỆ ĐIỀU HÀNH:
- Windows: đặt cửa sổ ở toạ độ ÂM rất lớn → nằm ngoài màn hình, vẫn "visible"
  với Chrome nên không bị bóp hiệu năng.
- macOS: AppKit KÉO cửa sổ về lại màn hình khi toạ độ âm → mẹo cũ VÔ TÁC DỤNG
  (đây là lý do máy Mac "không dùng được chế độ ẩn"). Vì vậy sau khi mở, ta
  dùng CDP đẩy cửa sổ ra ngoài rồi KIỂM TRA LẠI; nếu macOS vẫn kéo về thì
  THU NHỎ (minimize) cửa sổ xuống Dock. Kèm các cờ chống throttle để Chrome
  không "ngủ" khi cửa sổ bị che/thu nhỏ.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    TimeoutError as PWTimeout,
)

from config import PROFILE_DIR, CHATGPT_URL, SELECTOR_COMPOSER

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# Cờ giữ cho Chrome CHẠY HẾT TỐC ĐỘ kể cả khi cửa sổ bị che / thu nhỏ / ngoài
# màn hình. Thiếu mấy cờ này thì chế độ ẩn trên macOS sẽ bị treo giữa chừng
# (Chrome coi cửa sổ là "occluded" → dừng timer, dừng render, ChatGPT đứng).
# CHÚ Ý: không dùng --disable-features ở đây vì sẽ GHI ĐÈ danh sách mặc định
# của Playwright (switch trùng tên bị thay thế, không cộng dồn).
ANTI_THROTTLE_ARGS = [
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
]

_OFFSCREEN_W, _OFFSCREEN_H = 1280, 900


def _screen_size():
    """(w, h) màn hình chính. (0, 0) nếu không lấy được."""
    try:
        if IS_WIN:
            import ctypes
            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        if IS_MAC:
            import ctypes
            import ctypes.util
            cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
            cg.CGMainDisplayID.restype = ctypes.c_uint32
            cg.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
            cg.CGDisplayPixelsWide.restype = ctypes.c_size_t
            cg.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
            cg.CGDisplayPixelsHigh.restype = ctypes.c_size_t
            d = cg.CGMainDisplayID()
            return int(cg.CGDisplayPixelsWide(d)), int(cg.CGDisplayPixelsHigh(d))
    except Exception:
        pass
    return 0, 0


def _virtual_right_edge() -> int:
    """Mép PHẢI của TOÀN BỘ vùng màn hình (gộp mọi màn hình đang cắm).

    Cần con số này để đẩy cửa sổ ra chỗ KHÔNG màn hình nào với tới — nếu chỉ
    lấy bề rộng màn hình chính thì máy 2 màn hình sẽ đẩy cửa sổ 'ẩn' sang đúng
    màn hình thứ hai.
    """
    if IS_MAC:
        try:
            import ctypes
            import ctypes.util

            class _P(ctypes.Structure):
                _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

            class _S(ctypes.Structure):
                _fields_ = [("w", ctypes.c_double), ("h", ctypes.c_double)]

            class _R(ctypes.Structure):
                _fields_ = [("origin", _P), ("size", _S)]

            cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
            cg.CGGetActiveDisplayList.argtypes = [
                ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                ctypes.POINTER(ctypes.c_uint32),
            ]
            cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
            cg.CGDisplayBounds.restype = _R
            ids = (ctypes.c_uint32 * 16)()
            cnt = ctypes.c_uint32(0)
            if cg.CGGetActiveDisplayList(16, ids, ctypes.byref(cnt)) == 0 and cnt.value:
                right = 0
                for i in range(cnt.value):
                    b = cg.CGDisplayBounds(ids[i])
                    right = max(right, int(b.origin.x + b.size.w))
                if right > 0:
                    return right
        except Exception:
            pass
    return _screen_size()[0]


def _centered_window_args(w: int = 1180, h: int = 840):
    """Tính vị trí căn GIỮA màn hình cho cửa sổ Chrome (Windows & macOS)."""
    sw, sh = _screen_size()
    if not sw or not sh:
        return [f"--window-size={w},{h}"]
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    return [f"--window-position={x},{y}", f"--window-size={w},{h}"]


def _offscreen_xy():
    """Toạ độ 'ngoài tầm mắt' theo từng OS."""
    if IS_MAC:
        # macOS KÉO cửa sổ về màn hình khi toạ độ âm (title bar phải nằm dưới
        # thanh menu) → mẹo toạ độ âm của Windows vô tác dụng. Thử đẩy sang
        # PHẢI, vượt qua mép phải của TẤT CẢ màn hình.
        return (_virtual_right_edge() or 1920) + 400, 0
    return -2400, -2400          # Windows/Linux: giá trị đã chạy ổn thực tế


def _offscreen_window_args():
    x, y = _offscreen_xy()
    return [f"--window-position={x},{y}",
            f"--window-size={_OFFSCREEN_W},{_OFFSCREEN_H}"]


class AioBrowser:
    """Vòng đời 1 trình duyệt async dùng chung profile đăng nhập."""

    def __init__(self, profile_dir: Path = PROFILE_DIR, headless: bool = False,
                 hidden: bool = False):
        # headless: ẩn hẳn (ChatGPT CHẶN — Cloudflare) → tránh dùng.
        # hidden : chạy trình duyệt THẬT nhưng đưa cửa sổ ra khỏi tầm mắt
        #          (chạy ngầm, không che, vẫn qua được Cloudflare).
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        self.hidden = hidden
        self._pw = None
        self._hidden_applied = False
        self.context: Optional[BrowserContext] = None

    async def start(self) -> BrowserContext:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_profile_lock()
        self._pw = await async_playwright().start()

        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            *ANTI_THROTTLE_ARGS,
        ]
        if self.hidden and not self.headless:
            args += _offscreen_window_args()
        elif not self.headless:
            # cửa sổ HIỆN (vd đăng nhập) → căn GIỮA màn hình
            args += _centered_window_args(1180, 840)

        kwargs = dict(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            # viewport cố định → layout trang KHÔNG đổi dù cửa sổ bị thu nhỏ
            # hay đẩy ra ngoài màn hình (quan trọng cho chế độ ẩn trên Mac).
            viewport={"width": 1280, "height": 900},
            args=args,
        )
        self.context = await self._launch_with_retry(kwargs)
        await self.context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        # cấp quyền clipboard để dán prompt nguyên khối (tránh xáo trộn ký tự)
        try:
            await self.context.grant_permissions(
                ["clipboard-read", "clipboard-write"], origin="https://chatgpt.com"
            )
        except Exception:
            pass
        await self.apply_hidden()
        return self.context

    async def _launch_with_retry(self, kwargs: dict) -> BrowserContext:
        async def _do():
            try:
                return await self._pw.chromium.launch_persistent_context(
                    channel="chrome", **kwargs
                )
            except Exception as e:
                if "existing browser session" in str(e).lower():
                    raise
                return await self._pw.chromium.launch_persistent_context(**kwargs)

        try:
            return await _do()
        except Exception as e:
            if "existing browser session" in str(e).lower():
                self._kill_profile_chrome()
                self._cleanup_profile_lock()
                return await _do()
            raise

    # ------------------------------------------------------------------ #
    # CHẠY NGẦM
    # ------------------------------------------------------------------ #
    async def apply_hidden(self) -> None:
        """Đảm bảo cửa sổ nằm NGOÀI TẦM MẮT (gọi lại được nhiều lần).

        Windows: cờ --window-position âm đã đủ, chỉ kiểm tra cho chắc.
        macOS  : AppKit có thể đã kéo cửa sổ về màn hình → đẩy lại bằng CDP,
                 vẫn không được thì THU NHỎ xuống Dock.
        """
        if not self.hidden or self.headless or self.context is None:
            return
        try:
            page = await self.first_page()
            cdp = await self.context.new_cdp_session(page)
            try:
                win = await cdp.send("Browser.getWindowForTarget")
                wid = win["windowId"]
                if await self._is_offscreen(cdp, wid):
                    self._hidden_applied = True
                    return
                # thử đẩy ra ngoài màn hình bằng CDP
                left, top = _offscreen_xy()
                await cdp.send("Browser.setWindowBounds", {
                    "windowId": wid,
                    "bounds": {"left": left, "top": top,
                               "width": _OFFSCREEN_W, "height": _OFFSCREEN_H},
                })
                if await self._is_offscreen(cdp, wid):
                    self._hidden_applied = True
                    return
                # macOS ghim cửa sổ trong màn hình → thu nhỏ xuống Dock.
                # Nhờ ANTI_THROTTLE_ARGS + viewport cố định, trang vẫn chạy
                # và vẫn đọc/ghi DOM bình thường khi bị thu nhỏ.
                await cdp.send("Browser.setWindowBounds", {
                    "windowId": wid, "bounds": {"windowState": "minimized"},
                })
                self._hidden_applied = True
            finally:
                try:
                    await cdp.detach()
                except Exception:
                    pass
        except Exception:
            pass

    async def _is_offscreen(self, cdp, wid: int) -> bool:
        """Cửa sổ hiện có nằm hẳn ngoài vùng nhìn thấy không?"""
        try:
            b = (await cdp.send("Browser.getWindowBounds",
                                {"windowId": wid})).get("bounds", {})
        except Exception:
            return False
        if b.get("windowState") == "minimized":
            return True
        left, top = int(b.get("left", 0)), int(b.get("top", 0))
        w, h = int(b.get("width", 0)), int(b.get("height", 0))
        if left + w <= 0 or top + h <= 0:
            return True                      # nằm hẳn bên trái/trên vùng ảo
        right = _virtual_right_edge()        # gộp mọi màn hình → không lọt sang
        if right and left >= right:          # màn hình phụ
            return True
        return False

    async def new_page(self) -> Page:
        assert self.context is not None
        page = await self.context.new_page()
        # tab mới có thể làm macOS bung cửa sổ ra khỏi Dock → ẩn lại
        if self.hidden and self._hidden_applied:
            await self.apply_hidden()
        return page

    async def first_page(self) -> Page:
        assert self.context is not None
        pages = self.context.pages
        return pages[0] if pages else await self.context.new_page()

    async def open_chatgpt(self, page: Page) -> None:
        await page.goto(CHATGPT_URL, wait_until="domcontentloaded")

    async def is_logged_in(self, page: Page = None, timeout_ms: int = 8000) -> bool:
        """True nếu ĐÃ đăng nhập thật — kiểm cookie session-token (chắc chắn)."""
        if self.context is None:
            return False
        try:
            cookies = await self.context.cookies("https://chatgpt.com/")
        except Exception:
            return False
        return any(
            c.get("name", "").startswith("__Secure-next-auth.session-token")
            for c in cookies
        )

    async def close(self) -> None:
        try:
            if self.context is not None:
                await self.context.close()
        except Exception:
            pass  # context/trình duyệt có thể đã chết — bỏ qua
        finally:
            try:
                if self._pw is not None:
                    await self._pw.stop()
            except Exception:
                pass
            self.context = None
            self._pw = None

    # --- dọn lock (giống bản sync) ------------------------------------ #
    def _cleanup_profile_lock(self) -> None:
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            p = self.profile_dir / name
            try:
                if p.exists() or p.is_symlink():
                    p.unlink()
            except Exception:
                pass

    def _kill_profile_chrome(self) -> None:
        kill_profile_chrome(self.profile_dir)


def kill_profile_chrome(profile_dir: Path) -> None:
    """Tắt tiến trình Chrome đang giữ đúng profile này (Windows / macOS / Linux).

    Bản cũ chỉ có nhánh PowerShell → trên Mac profile bị kẹt là app chết hẳn
    ("existing browser session") mà không tự gỡ được.
    """
    prof = str(profile_dir)
    try:
        if IS_WIN:
            ps = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                f"Where-Object {{ $_.CommandLine -like '*{prof}*' }} | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
                "-ErrorAction SilentlyContinue }"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           timeout=20, capture_output=True)
        else:
            subprocess.run(["pkill", "-f", f"--user-data-dir={prof}"],
                           timeout=20, capture_output=True)
    except Exception:
        pass
