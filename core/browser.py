"""Điều khiển Chrome thật bằng Playwright, giữ session đăng nhập ChatGPT.

Nguyên tắc:
- Dùng launch_persistent_context với 1 thư mục profile cố định => cookie/login
  được lưu lại, login tay 1 lần rồi dùng mãi.
- Chạy hiện cửa sổ (không headless) để đỡ bị chặn bot và để user login tay.
- Không tự động login (dễ dính CAPTCHA / khóa tài khoản).

Module này KHÔNG phụ thuộc PySide6 — sau này UI chỉ việc gọi vào.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import (
    sync_playwright,
    Page,
    BrowserContext,
    TimeoutError as PWTimeout,
)

from config import PROFILE_DIR, CHATGPT_URL, SELECTOR_COMPOSER


# Dùng chung với bản async — đã hỗ trợ cả Windows lẫn macOS.
from core.aio_browser import (  # noqa: E402
    ANTI_THROTTLE_ARGS, _centered_window_args, kill_profile_chrome,
)


class ChatGPTBrowser:
    """Vòng đời 1 phiên trình duyệt điều khiển ChatGPT."""

    def __init__(
        self,
        profile_dir: Path = PROFILE_DIR,
        headless: bool = False,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        self._pw = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    # ------------------------------------------------------------------ #
    # Khởi động / tắt
    # ------------------------------------------------------------------ #
    def start(self) -> Page:
        """Mở Chrome với profile đã lưu. Trả về trang đầu tiên."""
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_profile_lock()
        self._pw = sync_playwright().start()

        launch_kwargs = dict(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",  # giảm crash renderer do thiếu bộ nhớ
                *ANTI_THROTTLE_ARGS,
                *_centered_window_args(1180, 840),  # cửa sổ căn giữa
            ],
        )

        self.context = self._launch_with_retry(launch_kwargs)

        # Giảm dấu hiệu tự động hoá.
        self.context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )

        self.page = (
            self.context.pages[0]
            if self.context.pages
            else self.context.new_page()
        )
        return self.page

    def _launch_with_retry(self, launch_kwargs: dict):
        """Mở persistent context; nếu profile đang bị giữ thì dọn rồi thử lại.

        Ưu tiên Chrome thật; không có thì dùng Chromium bundled.
        """
        def _do_launch():
            try:
                return self._pw.chromium.launch_persistent_context(
                    channel="chrome", **launch_kwargs
                )
            except Exception as e:
                if "existing browser session" in str(e).lower():
                    raise  # để vòng ngoài xử lý (dọn + thử lại)
                return self._pw.chromium.launch_persistent_context(**launch_kwargs)

        try:
            return _do_launch()
        except Exception as e:
            if "existing browser session" in str(e).lower():
                self._kill_profile_chrome()
                time.sleep(1.5)
                self._cleanup_profile_lock()
                return _do_launch()
            raise

    def _cleanup_profile_lock(self) -> None:
        """Xóa các file lock Singleton còn sót (do lần trước tắt đột ngột)."""
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            p = self.profile_dir / name
            try:
                if p.exists() or p.is_symlink():
                    p.unlink()
            except Exception:
                pass

    def _kill_profile_chrome(self) -> None:
        """Tắt tiến trình Chrome đang giữ đúng profile này (Win/macOS/Linux)."""
        kill_profile_chrome(self.profile_dir)

    def close(self) -> None:
        """Đóng trình duyệt & giải phóng Playwright."""
        try:
            if self.context is not None:
                self.context.close()
        finally:
            if self._pw is not None:
                self._pw.stop()
            self.context = None
            self.page = None
            self._pw = None

    # Cho phép dùng: with ChatGPTBrowser() as br:
    def __enter__(self) -> "ChatGPTBrowser":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # ChatGPT
    # ------------------------------------------------------------------ #
    def open_chatgpt(self) -> None:
        """Mở trang ChatGPT."""
        assert self.page is not None, "Chưa gọi start()"
        self.page.goto(CHATGPT_URL, wait_until="domcontentloaded")

    def is_logged_in(self, timeout_ms: int = 8000) -> bool:
        """True nếu ĐÃ đăng nhập thật — kiểm cookie session-token (chắc chắn).

        Không dựa vào DOM vì ChatGPT cho người CHƯA đăng nhập cũng thấy ô nhập
        (chat ẩn danh) → dò DOM dễ nhầm/đua. Cookie session-token là tín hiệu
        dứt khoát.
        """
        assert self.context is not None, "Chưa gọi start()"
        try:
            cookies = self.context.cookies("https://chatgpt.com/")
        except Exception:
            return False
        return any(
            c.get("name", "").startswith("__Secure-next-auth.session-token")
            for c in cookies
        )

    def wait_for_login(
        self, poll_seconds: int = 3, max_wait_seconds: int = 300
    ) -> bool:
        """Chờ user đăng nhập tay trong cửa sổ. Trả True khi phát hiện đã login."""
        assert self.page is not None, "Chưa gọi start()"
        waited = 0
        while waited < max_wait_seconds:
            if self.is_logged_in(timeout_ms=2000):
                return True
            time.sleep(poll_seconds)
            waited += poll_seconds
        return False
