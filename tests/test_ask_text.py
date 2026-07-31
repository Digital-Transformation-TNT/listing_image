"""Test lớp AioSession.ask_text bằng TRANG GIẢ (không cần trình duyệt/mạng).

Mục tiêu: chốt lại lỗi "prompt đi prompt lại mãi không xong" — bản cũ đọc
"câu trả lời assistant cuối cùng" NGAY sau khi gửi, nên khi trong chat đã có
câu trả lời CŨ (đứng yên) thì nó tưởng đó là câu trả lời mới đã xong → JSON
sai → hỏi lại → lặp vô tận.

Chạy:  python tests/test_ask_text.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:                       # console Windows mặc định cp1252 → không in được tiếng Việt
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core.aio_chatgpt import AioSession  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


# --------------------------------------------------------------------------- #
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

    async def count(self):
        return 0

    async def is_visible(self):
        return False

    async def set_input_files(self, paths):
        pass


class FakeKeyboard:
    def __init__(self, page):
        self.page = page

    async def press(self, k):
        if k == "Enter":
            self.page.typed = ""       # Enter = gửi → ô soạn trống

    async def insert_text(self, t):
        pass


class FakePage:
    """Mô phỏng 1 tab ChatGPT theo 'kịch bản' cho trước.

    script: hàm nhận số tick đã trôi qua, trả (assistant_texts, generating).
    """

    def __init__(self, script):
        self.script = script
        self.tick = 0
        self.url = "https://chatgpt.com/"
        self.keyboard = FakeKeyboard(self)
        self.typed = ""

    # -- API Playwright mà AioSession dùng -- #
    def on(self, *a, **kw):
        pass

    def on_send(self):
        self.typed = ""                # bấm nút gửi → ô soạn trống

    def locator(self, sel):
        return FakeLocator(self, sel)

    async def wait_for_timeout(self, ms):
        self.tick += 1
        await asyncio.sleep(0)

    async def wait_for_selector(self, sel, timeout=0):
        pass

    async def goto(self, url, **kw):
        self.url = url

    async def evaluate(self, js, arg=None):
        texts, generating = self.script(self.tick)
        if "author-role=\\\"assistant\\\"" in js or 'author-role="assistant"' in js:
            if "length" in js and "innerText" not in js:
                return len(texts)
            return texts[-1] if texts else ""
        if "aria-disabled" in js or "b.disabled" in js:  # _send_ready → luôn sẵn sàng
            return True
        if "getBoundingClientRect" in js:                 # _is_generating
            return generating
        if "ClipboardEvent" in js:
            self.typed = arg
            return None
        if "prompt-textarea" in js:
            return self.typed          # xác nhận đã gõ đúng / _composer_text
        return None


def run(script, timeout_ms=20000):
    sess = AioSession(FakePage(script))
    return asyncio.run(sess.ask_text("hỏi gì đó", timeout_ms=timeout_ms))


# --------------------------------------------------------------------------- #
print("== ask_text ==")

# 1) KỊCH BẢN GÂY LỖI CŨ: chat đã có 1 câu trả lời CŨ, câu MỚI mãi 8 tick sau
#    mới xuất hiện rồi mới stream dần.
OLD = '{"prompts": []}'          # câu trả lời cũ — hợp lệ nhưng SAI nội dung
NEW = '{"prompts": [1,2,3,4,5,6,7,8,9]}'


def script_stale(tick):
    if tick < 8:
        return [OLD], True             # đang nghĩ, DOM vẫn là câu trả lời cũ
    if tick < 14:
        return [OLD, NEW[:tick]], True  # câu mới đang stream
    return [OLD, NEW], False            # xong


got = run(script_stale)
check("không đọc nhầm câu trả lời CŨ đang đứng yên", got == NEW, f"got={got!r}")

# 2) Trả lời bình thường trong chat TRỐNG.
def script_fresh(tick):
    if tick < 2:
        return [], True
    if tick < 6:
        return [NEW[:tick * 4]], True
    return [NEW], False


got = run(script_fresh)
check("chat trống: lấy đúng câu trả lời đầy đủ", got == NEW, f"got={got!r}")

# 3) Nút 'Dừng' kẹt hiển thị (dương tính giả) → vẫn phải thoát nhờ text đứng yên.
def script_stuck_button(tick):
    if tick < 2:
        return [], True
    return [NEW], True                  # text xong nhưng nút Dừng không tắt


got = run(script_stuck_button)
check("nút Dừng kẹt: vẫn trả về nhờ text đứng yên", got == NEW, f"got={got!r}")

# 4) Luồng mạng báo xong sớm → trả về ngay, không chờ nút Dừng.
def script_net(tick):
    if tick < 2:
        return [], True
    return [NEW], True


sess = AioSession(FakePage(script_net))
sess._net_done = 5                      # giả lập 1 luồng đã kết thúc sau send()


async def _with_net():
    orig = sess.send

    async def send():
        ok = await orig()
        sess._net_done += 1             # mạng đóng ngay sau khi gửi
        return ok                       # PHẢI trả bool để ask_text biết đã gửi
    sess.send = send
    return await sess.ask_text("x", timeout_ms=20000)


got = asyncio.run(_with_net())
check("tín hiệu mạng: chốt xong sớm", got == NEW, f"got={got!r}")

print(f"\n==> {len(PASS)} passed, {len(FAIL)} failed / {len(PASS) + len(FAIL)} total")
sys.exit(1 if FAIL else 0)
