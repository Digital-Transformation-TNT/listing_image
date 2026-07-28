"""Test send() KHÔNG treo khi ảnh chưa upload xong (nút gửi đang disabled).

Tái hiện lỗi ảnh chụp: gõ prompt + đính ảnh, nhưng bấm gửi lúc ảnh CHƯA upload
xong (nút gửi disabled) → tin không đi → ChatGPT không trả lời → treo. send()
mới phải CHỜ nút sẵn sàng rồi mới gửi, và xác nhận ô soạn trống.

Chạy:  python tests/test_send.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core.aio_chatgpt import AioSession, SendError  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


class FakeKeyboard:
    def __init__(self, page):
        self.page = page

    async def press(self, k):
        if k == "Enter":
            self.page.on_send()

    async def insert_text(self, t):
        pass


class FakeLocator:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    @property
    def first(self):
        return self

    async def click(self):
        if "send-button" in self.sel:
            self.page.on_send()

    async def wait_for(self, **kw):
        pass


class FakeSendPage:
    """Mô phỏng ô soạn + nút gửi.

    upload_ready_after: số tick nút gửi còn DISABLED (ảnh đang upload).
    never_ready: nút gửi KHÔNG bao giờ bật (mô phỏng UI hỏng) → send phải bỏ cuộc.
    """

    def __init__(self, upload_ready_after=4, never_ready=False):
        self.tick = 0
        self.upload_ready_after = upload_ready_after
        self.never_ready = never_ready
        self.composer = "prompt rất dài đính kèm ảnh"
        self.sent = False
        self.url = "https://chatgpt.com/"
        self.keyboard = FakeKeyboard(self)

    def on(self, *a, **kw):
        pass

    def on_send(self):
        # chỉ gửi được khi nút đã sẵn sàng
        if self._ready():
            self.sent = True
            self.composer = ""      # ô soạn trống = đã gửi

    def _ready(self):
        if self.never_ready:
            return False
        return self.tick >= self.upload_ready_after

    def locator(self, sel):
        return FakeLocator(self, sel)

    async def wait_for_timeout(self, ms):
        self.tick += 1
        await asyncio.sleep(0)

    async def evaluate(self, js, arg=None):
        if "prompt-textarea" in js and "innerText" in js:
            return self.composer
        if "aria-disabled" in js or "b.disabled" in js:
            return self._ready()
        if "getBoundingClientRect" in js:   # is_generating (stop btn)
            return self.sent               # sau khi gửi coi như đang sinh
        return None


def test_waits_for_upload():
    p = FakeSendPage(upload_ready_after=4)
    s = AioSession(p)
    ok = asyncio.run(s.send())
    return ok and p.sent


def test_never_ready_fails_fast():
    p = FakeSendPage(never_ready=True)
    s = AioSession(p)
    ok = asyncio.run(s.send())
    return (ok is False) and (not p.sent)


print("== send() chống treo khi ảnh chưa upload ==")
check("ảnh upload xong muộn → vẫn gửi được (chờ nút sẵn sàng)", test_waits_for_upload())
check("nút gửi không bao giờ bật → send trả False (không treo)", test_never_ready_fails_fast())

# ask_text: gửi hụt → raise SendError NGAY, không chờ mòn hết timeout
def test_ask_text_raises_on_send_fail():
    p = FakeSendPage(never_ready=True)
    s = AioSession(p)

    async def go():
        try:
            await s.ask_text("hỏi gì đó", timeout_ms=5000)
            return "no-raise"
        except SendError:
            return "raised"
    return asyncio.run(go())


check("gửi hụt → ask_text báo lỗi ngay (không treo hết timeout)",
      test_ask_text_raises_on_send_fail() == "raised")

print(f"\n==> {len(PASS)} passed, {len(FAIL)} failed / {len(PASS) + len(FAIL)} total")
sys.exit(1 if FAIL else 0)
