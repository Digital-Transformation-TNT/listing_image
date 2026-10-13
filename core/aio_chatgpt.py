"""Thao tác ChatGPT web ASYNC trên 1 tab (Page).

Port từ core/chatgpt.py (bản sync đã kiểm chứng). Selector giữ nguyên.

CÁCH BIẾT "ChatGPT ĐÃ TRẢ LỜI XONG" (điểm quyết định tốc độ & độ đúng):
1. Đếm số lượt trả lời TRƯỚC khi gửi → chỉ đọc khi đã có LƯỢT MỚI.
   (Bản cũ đọc "assistant cuối cùng" ngay sau khi gửi → gặp câu trả lời CŨ
    đứng yên 3.6s → tưởng xong → parse JSON sai → hỏi lại → lặp vô tận.)
2. Bám luồng mạng: response POST .../conversation kết thúc = ChatGPT nói xong.
   Tín hiệu này chính xác và tới sớm hơn DOM vài giây.
3. Dự phòng: nút "Dừng" biến mất / độ dài text đứng yên.
"""
from __future__ import annotations

import asyncio
import base64
import sys
import time
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from playwright.async_api import Page, TimeoutError as PWTimeout

from config import CHATGPT_URL, OUTPUT_DIR

SEL_COMPOSER = "#prompt-textarea"          # id CŨ — giữ để ưu tiên
# Ô soạn sau khi _mark_composer() đã tìm ra & gắn dấu (xem _FIND_COMPOSER).
SEL_COMPOSER_MARK = '[data-tnt-composer="1"]'
SEL_FILE_INPUT = 'input[type="file"]'
# Nút "+" / đính kèm — dùng khi giao diện không có sẵn ô chọn file ẩn.
SEL_ATTACH_BTN = (
    '[data-testid="composer-plus-btn"], button[aria-label*="Add photos" i], '
    'button[aria-label*="Attach" i], button[aria-label*="Upload" i], '
    'button[aria-label*="Add files" i], button[aria-label*="Đính kèm"], '
    'button[aria-label*="Thêm ảnh"], button[aria-label*="Thêm tệp"]'
)
# Mục trong menu "+" để chọn ảnh/tệp từ máy.
SEL_ATTACH_ITEM = (
    '[role="menuitem"]:has-text("photo"), [role="menuitem"]:has-text("file"), '
    '[role="menuitem"]:has-text("ảnh"), [role="menuitem"]:has-text("tệp")'
)
SEL_SEND_BTN = (
    '[data-testid="send-button"], #composer-submit-button, '
    'button[aria-label="Send prompt"], button[aria-label*="Send message" i], '
    'button[aria-label*="Gửi"]'
)

# Tìm Ô SOẠN TIN. ChatGPT đổi giao diện liên tục (bản 10/2026 có thanh
# "Chat / Work", ô "Ask ChatGPT" không còn id #prompt-textarea) → dò theo NHIỀU
# dấu hiệu, ưu tiên id cũ, chỉ lấy ô ĐANG HIỂN THỊ.
_FIND_COMPOSER = r"""
function __tntComposer() {
    const vis = e => !!e && e.getClientRects().length > 0
        && getComputedStyle(e).visibility !== 'hidden';
    const groups = [
        '#prompt-textarea',
        '[data-testid*="composer" i] [contenteditable="true"]',
        'form [contenteditable="true"][role="textbox"]',
        '.ProseMirror[contenteditable="true"]',
        '[contenteditable="true"][role="textbox"]',
        '[contenteditable="true"][aria-label*="chatgpt" i]',
        '[contenteditable="true"][aria-label*="message" i]',
        'form textarea:not([aria-hidden="true"])',
        'textarea[placeholder]',
    ];
    for (const g of groups)
        for (const e of document.querySelectorAll(g))
            if (vis(e)) return e;
    return null;
}
"""
# Tìm ô soạn + gắn dấu data-tnt-composer để Playwright click được. Trả True/False.
_MARK_COMPOSER_JS = "() => {" + _FIND_COMPOSER + """
    const el = __tntComposer();
    document.querySelectorAll('[data-tnt-composer]').forEach(
        e => { if (e !== el) e.removeAttribute('data-tnt-composer'); });
    if (!el) return false;
    el.setAttribute('data-tnt-composer', '1');
    return true;
}"""
# Chữ đang có trong ô soạn; null = KHÔNG tìm thấy ô (khác với ô trống "").
_COMPOSER_TEXT_JS = "() => {" + _FIND_COMPOSER + """
    const e = __tntComposer();
    if (!e) return null;
    return (e.tagName === 'TEXTAREA' ? e.value : e.innerText) || '';
}"""
SEL_STOP_BTN = (
    'button[data-testid="stop-button"], button[aria-label*="Stop streaming"], '
    'button[aria-label*="Dừng"], button[aria-label*="Ngừng"]'
)
SEL_NEW_CHAT = (
    '[data-testid="create-new-chat-button"], '
    'button[aria-label*="New chat"], a[aria-label*="New chat"], '
    'button[aria-label*="Đoạn chat mới"], a[aria-label*="Đoạn chat mới"]'
)

# Nhịp hỏi DOM. 500ms đủ mượt mà không tốn CPU; bản cũ 1200ms làm mỗi tin
# nhắn chậm thêm vài giây.
POLL_MS = 500
# Mã HTTP coi là "hết lượt / bị chặn" trên endpoint hội thoại.
LIMIT_STATUS = {403, 429}


class StopRequested(Exception):
    """User bấm Dừng."""


class SendError(Exception):
    """Không gửi được tin nhắn (nút gửi không sẵn sàng / UI đổi)."""


class ChatGPTPageError(RuntimeError):
    """Trang ChatGPT không vào được ô chat (đăng xuất / bị bắt xác minh / đổi giao diện)."""


# Dò TÌNH TRẠNG trang khi không thấy ô chat → báo đúng nguyên nhân cho người dùng.
_DIAGNOSE_JS = """() => {
    const t = ((document.body && document.body.innerText) || '').toLowerCase();
    const url = location.href;
    const cf = !!document.querySelector(
        'iframe[src*="challenges.cloudflare.com"], #challenge-form, '
        + '#cf-challenge-running, #challenge-stage')
        || /verify you are human|xác minh bạn là con người|just a moment|checking your browser|unusual activity/.test(t);
    const login = !!document.querySelector(
        '[data-testid="login-button"], [data-testid="signup-button"]')
        || /auth\\.openai\\.com|\\/auth\\/login|\\/log-?in/.test(url)
        || /session has expired|phiên.*hết hạn|log in again|đăng nhập lại/.test(t);
    return {cf, login, url, title: document.title || ''};
}"""


def explain_page_problem(info: dict) -> str:
    """Đổi kết quả dò trang thành câu báo lỗi tiếng Việt kèm cách xử lý."""
    info = info or {}
    if info.get("cf"):
        return ("ChatGPT đang bắt XÁC MINH 'bạn có phải người thật' (Cloudflare). "
                "Cách xử lý: BỎ TICK 'Chạy ngầm', bấm chạy lại, rồi bấm xác minh "
                "trong cửa sổ Chrome hiện ra (thường chỉ cần 1 lần), sau đó bật "
                "lại 'Chạy ngầm'.")
    if info.get("login"):
        return ("Tài khoản ChatGPT đã bị ĐĂNG XUẤT (phiên hết hạn). Cách xử lý: "
                "chọn đúng tài khoản rồi bấm 'Đăng nhập tài khoản' để đăng nhập lại.")
    where = " ".join(x for x in (info.get("title"), info.get("url")) if x)
    return ("Không thấy ô nhập chat của ChatGPT"
            + (f" (trang đang mở: {where})" if where else "") +
            ". Cách xử lý: BỎ TICK 'Chạy ngầm' và chạy lại để xem cửa sổ Chrome "
            "đang hiện gì; nếu ChatGPT đã đổi giao diện thì cần cập nhật tool.")


async def save_debug(page) -> str:
    """Lưu ẢNH CHỤP + MÃ TRANG (.html) vào ket_qua/_loi/ để chẩn đoán lỗi.
    Trả đường dẫn ảnh ('' nếu không lưu được). Không bao giờ ném lỗi."""
    try:
        d = OUTPUT_DIR / "_loi"
        d.mkdir(parents=True, exist_ok=True)
        f = d / time.strftime("chatgpt_%y%m%d_%H%M%S.png")
        await page.screenshot(path=str(f))
        try:
            f.with_suffix(".html").write_text(await page.content(), encoding="utf-8")
        except Exception:
            pass
        return str(f)
    except Exception:
        return ""


class AioSession:
    """Bọc 1 tab đã đăng nhập để thao tác tạo ảnh / hỏi text."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.cancel = None   # threading.Event — set khi user bấm Dừng
        self._net_done = 0   # số luồng trả lời đã kết thúc (theo dõi qua mạng)
        self._net_mark = 0   # mốc _net_done tại lần send() gần nhất
        self.http_error = 0  # mã HTTP lỗi cuối trên endpoint hội thoại
        self.on_step = None  # callback(msg) — ghi nhật ký từng bước lên app
        self._attach_network()

    def _log(self, msg: str) -> None:
        if self.on_step:
            try:
                self.on_step(msg)
            except Exception:
                pass

    def _stop(self):
        if self.cancel is not None and self.cancel.is_set():
            raise StopRequested()

    # ------------------------------------------------------------------ #
    # Theo dõi luồng trả lời qua MẠNG (chỉ nghe, KHÔNG can thiệp vào trang)
    # ------------------------------------------------------------------ #
    def _attach_network(self) -> None:
        def _on_response(resp):
            try:
                if resp.request.method != "POST":
                    return
                if not urlsplit(resp.url).path.endswith("/conversation"):
                    return
                status = resp.status
            except Exception:
                return
            if status in LIMIT_STATUS or status >= 500:
                self.http_error = status
            try:
                asyncio.ensure_future(self._await_finished(resp))
            except Exception:
                self._net_done += 1

        try:
            self.page.on("response", _on_response)
        except Exception:
            pass

    async def _await_finished(self, resp) -> None:
        """Đợi body (SSE) tải xong = ChatGPT đã nói hết câu."""
        try:
            await resp.finished()
        except Exception:
            pass
        self._net_done += 1

    def stream_finished(self) -> bool:
        """Luồng trả lời cho lần send() gần nhất đã kết thúc chưa?"""
        return self._net_done > self._net_mark

    def hit_limit(self) -> bool:
        """Endpoint hội thoại vừa trả 403/429 → gần như chắc chắn hết lượt."""
        return self.http_error in LIMIT_STATUS

    # ------------------------------------------------------------------ #
    async def new_chat(self) -> None:
        """Mở đoạn chat MỚI — ưu tiên điều hướng trong trang (không tải lại).

        Tải lại cả trang ChatGPT tốn 3-6 giây; với 9 ảnh (kèm retry) là cả
        phút chết. Bấm nút 'chat mới' chỉ mất ~0.3s. Có kiểm chứng (composer
        có mặt + 0 lượt trả lời) rồi mới chấp nhận, sai thì tải lại như cũ.
        """
        self._log("mở đoạn chat mới")
        try:
            if "chatgpt.com" in (self.page.url or ""):
                btn = self.page.locator(SEL_NEW_CHAT).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    if not await self._poll_composer(8000):
                        raise PWTimeout("composer")
                    for _ in range(12):
                        if await self._assistant_count() == 0:
                            self.http_error = 0
                            return
                        await self.page.wait_for_timeout(200)
        except Exception:
            pass
        await self.page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        await self.wait_composer()
        await self.page.wait_for_timeout(300)
        self.http_error = 0

    async def wait_composer(self, timeout_ms: int = 30000) -> None:
        """Chờ ô chat xuất hiện. Không thấy → tải lại trang thử thêm 1 lần (mạng
        chậm / trang treo); vẫn không thấy → dò nguyên nhân + chụp màn hình rồi
        báo lỗi DỄ HIỂU thay cho 'Timeout 30000ms exceeded' khó đoán."""
        self._log("chờ ô nhập chat")
        if await self._poll_composer(timeout_ms):
            return
        self._log("chưa thấy ô nhập chat → tải lại trang")
        self._stop()
        try:
            await self.page.reload(wait_until="domcontentloaded")
        except Exception:
            pass
        if await self._poll_composer(timeout_ms):
            return
        raise ChatGPTPageError(await self._diagnose())

    async def _mark_composer(self) -> bool:
        try:
            return bool(await self.page.evaluate(_MARK_COMPOSER_JS))
        except Exception:
            return False

    async def _poll_composer(self, timeout_ms: int) -> bool:
        """Đợi tới khi tìm được ô soạn (đang hiển thị). True nếu thấy."""
        deadline = time.time() + timeout_ms / 1000
        while True:
            self._stop()
            if await self._mark_composer():
                return True
            if time.time() >= deadline:
                return False
            await self.page.wait_for_timeout(300)

    async def _click_composer(self) -> None:
        await self._mark_composer()
        await self.page.locator(SEL_COMPOSER_MARK).first.click()

    async def _diagnose(self) -> str:
        try:
            info = await self.page.evaluate(_DIAGNOSE_JS)
        except Exception:
            info = {}
        f = await save_debug(self.page)
        shot = f" Ảnh chụp màn hình lúc lỗi: {f}" if f else ""
        return explain_page_problem(info) + shot

    async def open_conversation(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded")
        await self.wait_composer()
        for _ in range(3):
            await self.page.mouse.wheel(0, 2500)
            await self.page.wait_for_timeout(500)
        await self.page.wait_for_timeout(600)

    # ------------------------------------------------------------------ #
    async def upload_images(self, paths: List[Path], timeout_ms: int = 60000) -> int:
        paths = [str(Path(p)) for p in paths]
        self._log(f"tải {len(paths)} ảnh lên")
        before = await self._count_thumbnails()
        await self._set_files(paths)
        target = before + len(paths)
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            if await self._count_thumbnails() >= target:
                # Thumbnail đã hiện; upload-lên-server xong hay chưa thì send()
                # vẫn CHỜ nút gửi sẵn sàng nên chỉ cần nghỉ ngắn cho DOM ổn định.
                await self.page.wait_for_timeout(250)
                return await self._count_thumbnails()
            await self.page.wait_for_timeout(300)
        return await self._count_thumbnails()

    async def _set_files(self, paths: List[str]) -> None:
        """Đưa file vào ChatGPT. Ưu tiên ô chọn file ẩn có sẵn; giao diện không
        có thì bấm nút '+'/đính kèm (và mục 'ảnh/tệp' trong menu) để mở hộp
        chọn file rồi nạp file vào đó."""
        inp = self.page.locator(SEL_FILE_INPUT)
        if await inp.count() > 0:
            await inp.first.set_input_files(paths, timeout=15000)
            return
        self._log("không có ô chọn file sẵn → bấm nút đính kèm")
        btn = self.page.locator(SEL_ATTACH_BTN).first
        try:
            async with self.page.expect_file_chooser(timeout=4000) as fc:
                await btn.click(timeout=8000)
            await (await fc.value).set_files(paths)
            return
        except PWTimeout:
            pass
        # nút '+' mở menu → bấm mục ảnh/tệp; hoặc menu đã tạo ra ô chọn file
        inp = self.page.locator(SEL_FILE_INPUT)
        if await inp.count() > 0:
            await inp.first.set_input_files(paths, timeout=15000)
            return
        async with self.page.expect_file_chooser(timeout=8000) as fc:
            await self.page.locator(SEL_ATTACH_ITEM).first.click(timeout=8000)
        await (await fc.value).set_files(paths)

    async def _count_thumbnails(self) -> int:
        try:
            return await self.page.evaluate(
                "() => document.querySelectorAll('img[src^=\"blob:\"]').length"
            )
        except Exception:
            return 0

    # ------------------------------------------------------------------ #
    async def type_prompt(self, text: str) -> None:
        """Nhập prompt vào ô ProseMirror bằng sự kiện PASTE tổng hợp.

        Gõ từng phím / insert_text bị ProseMirror xáo trộn khi text dài. Bắn
        1 sự kiện 'paste' với DataTransfer → ProseMirror chèn đồng bộ 1 lần,
        chính xác, không cần quyền clipboard. Có kiểm tra + fallback.
        """
        clean = " ".join(text.split())
        self._log(f"gõ prompt ({len(clean)} ký tự)")
        await self._click_composer()
        await self.page.evaluate(
            """(text) => {
                const el = document.querySelector('[data-tnt-composer="1"]');
                if (!el) return;
                el.focus();
                if (el.tagName === 'TEXTAREA') {
                    // textarea: sự kiện paste giả KHÔNG tự chèn chữ → gán value
                    // qua setter gốc để React nhận biết thay đổi.
                    const set = Object.getOwnPropertyDescriptor(
                        HTMLTextAreaElement.prototype, 'value').set;
                    set.call(el, text);
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    return;
                }
                const dt = new DataTransfer();
                dt.setData('text/plain', text);
                el.dispatchEvent(new ClipboardEvent('paste',
                    {clipboardData: dt, bubbles: true, cancelable: true}));
            }""",
            clean,
        )
        await self.page.wait_for_timeout(200)
        # kiểm tra, nếu lệch thì thử lại bằng insert_text
        got = await self._composer_text() or ""
        if " ".join(got.split()) != clean:
            await self._click_composer()
            await self.page.keyboard.press(
                "Meta+A" if sys.platform == "darwin" else "Control+A")
            await self.page.keyboard.press("Delete")
            await self.page.keyboard.insert_text(clean)

    async def _composer_text(self) -> Optional[str]:
        """Chữ trong ô soạn; None nếu KHÔNG tìm thấy ô (đừng coi là 'đã gửi')."""
        try:
            return await self.page.evaluate(_COMPOSER_TEXT_JS)
        except Exception:
            return None

    async def _composer_empty(self) -> bool:
        t = await self._composer_text()
        return t is not None and not t.strip()

    async def _send_ready(self) -> bool:
        """Nút gửi ĐÃ SẴN SÀNG chưa? False khi ảnh còn upload (nút bị disabled).

        Đây là mấu chốt: bấm gửi lúc ảnh CHƯA upload xong (nút disabled) → click
        trượt, tin nhắn không đi → ChatGPT không trả lời → treo tới hết timeout."""
        try:
            return await self.page.evaluate(
                """(sel) => {
                    const b = document.querySelector(sel);
                    if (!b) return false;
                    if (b.disabled || b.getAttribute('aria-disabled') === 'true')
                        return false;
                    const r = b.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }""",
                SEL_SEND_BTN,
            )
        except Exception:
            return False

    async def send(self) -> bool:
        """Gửi tin nhắn và XÁC NHẬN đã gửi thật (ô soạn trống đi). Trả True/False.

        Chờ nút gửi SẴN SÀNG (tức ảnh đã upload xong) rồi mới bấm; sau khi bấm
        kiểm tra ô soạn đã trống → chắc chắn tin đã đi. Thử lại vài lần. Nhờ vậy
        không còn cảnh 'gõ xong mà không gửi được → treo mãi'."""
        self._log("gửi tin nhắn")
        self._net_mark = self._net_done   # mốc để biết luồng trả lời NÀY đã xong
        self.http_error = 0               # lỗi cũ không được ảnh hưởng lượt này

        # 1) chờ nút gửi sẵn sàng (bao gồm chờ ảnh upload xong) — tối đa ~45s
        ready_deadline = time.time() + 45
        while time.time() < ready_deadline:
            self._stop()
            if await self._send_ready():
                break
            await self.page.wait_for_timeout(400)

        # 2) gửi + xác nhận đã gửi (ô soạn trống / bắt đầu sinh / luồng mạng chạy)
        for _ in range(6):
            self._stop()
            if await self._composer_empty():
                return True                      # ô đã trống = đã gửi
            try:
                if await self._send_ready():
                    await self.page.locator(SEL_SEND_BTN).first.click()
                else:
                    await self._click_composer()
                    await self.page.keyboard.press("Enter")
            except Exception:
                try:
                    await self._click_composer()
                    await self.page.keyboard.press("Enter")
                except Exception:
                    pass
            for _ in range(12):                  # chờ xác nhận ~3s mỗi lần bấm
                await self.page.wait_for_timeout(250)
                self._stop()
                if await self._composer_empty():
                    return True
                if self.stream_finished() or await self._is_generating():
                    return True
        return False

    # ------------------------------------------------------------------ #
    async def ask_text(self, prompt: str, timeout_ms: int = 180000) -> str:
        """Gửi 1 message text và trả về ĐÚNG câu trả lời MỚI cho message đó.

        Bắt buộc phải thấy LƯỢT TRẢ LỜI MỚI rồi mới đọc → không bao giờ lấy
        nhầm câu trả lời cũ (nguyên nhân vòng lặp hỏi-lại vô tận).
        """
        self._stop()
        before = await self._assistant_count()
        await self.type_prompt(prompt)
        if not await self.send():
            # Không gửi được (ảnh chưa upload xong / UI đổi) → báo lỗi NGAY để
            # caller retry, thay vì chờ mòn hết timeout rồi trả rỗng.
            raise SendError("Không gửi được tin nhắn (nút gửi không sẵn sàng).")

        self._log("chờ ChatGPT trả lời")
        end = time.time() + timeout_ms / 1000
        # (1) chờ có LƯỢT TRẢ LỜI MỚI
        while time.time() < end:
            self._stop()
            if await self._assistant_count() > before or self.stream_finished():
                break
            await self.page.wait_for_timeout(POLL_MS)

        # (2) chờ lượt đó nói xong
        last_len = -1
        stable = 0
        idle = 0
        text = ""
        while time.time() < end:
            self._stop()
            text = await self._last_assistant_text()
            cur = len(text or "")
            if cur == last_len:
                stable += 1
            else:
                stable = 0
                last_len = cur
            if cur > 0:
                # a) luồng mạng đã đóng + DOM đứng yên 1 nhịp → xong (nhanh nhất)
                if self.stream_finished() and stable >= 1:
                    return text
                # b) dự phòng: nút Dừng biến mất
                if not await self._is_generating():
                    idle += 1
                    if idle >= 2 and stable >= 1:
                        return text
                else:
                    idle = 0
                # c) dự phòng cuối: text đứng yên ~8s
                if stable >= 16:
                    return text
            await self.page.wait_for_timeout(POLL_MS)
        return text

    async def _assistant_count(self) -> int:
        try:
            return await self.page.evaluate(
                "() => document.querySelectorAll("
                "'[data-message-author-role=\"assistant\"]').length"
            )
        except Exception:
            return 0

    async def _last_assistant_text(self, min_before: int = 0) -> str:
        try:
            return await self.page.evaluate(
                """() => {
                    const els = [...document.querySelectorAll(
                        '[data-message-author-role="assistant"]')];
                    if (!els.length) return "";
                    return els[els.length - 1].innerText || "";
                }"""
            )
        except Exception:
            return ""

    async def _wait_generation_done(self, timeout_ms: int = 120000,
                                    poll_ms: int = 1000) -> None:
        """Chờ đến khi ChatGPT ngừng sinh (nút Dừng biến mất, ổn định)."""
        deadline = time.time() + timeout_ms / 1000
        await self._wait_generation_started(max_s=12)
        gone = 0
        while time.time() < deadline:
            if not await self._is_generating():
                gone += 1
                if gone >= 2:
                    return
            else:
                gone = 0
            await self.page.wait_for_timeout(poll_ms)

    # ------------------------------------------------------------------ #
    async def generated_srcs(self) -> List[str]:
        try:
            return await self.page.evaluate(
                """() => {
                    const seen = new Set(); const out = [];
                    for (const i of document.querySelectorAll(
                        '[data-testid^="conversation-turn"] img')) {
                        if (/auth0|avatars/.test(i.src)) continue;
                        if (i.closest('[data-message-author-role="user"]')) continue;
                        if (i.naturalWidth <= 200 || i.naturalHeight <= 200) continue;
                        const s = i.currentSrc || i.src;
                        if (!seen.has(s)) { seen.add(s); out.push(s); }
                    }
                    return out;
                }"""
            )
        except Exception:
            return []

    async def wait_for_image(self, timeout_ms: int = 180000, poll_ms: int = 600,
                             baseline: Optional[set] = None) -> Optional[str]:
        self._log("chờ ChatGPT vẽ ảnh")
        base = set(baseline or ())
        deadline = time.time() + timeout_ms / 1000
        await self._wait_generation_started(max_s=20, base=base)
        last_new = None
        stable = 0
        while time.time() < deadline:
            self._stop()
            generating = await self._is_generating()
            new = [s for s in await self.generated_srcs() if s not in base]
            cur = new[-1] if new else None
            if cur:
                if cur == last_new:
                    stable += 1
                else:
                    stable = 0
                    last_new = cur
                # luồng mạng đóng = ảnh cuối cùng đã chốt → khỏi chờ thêm
                if not generating or self.stream_finished() or stable >= 2:
                    return cur
            elif self.hit_limit():
                return None      # 403/429 → không có ảnh, khỏi chờ hết timeout
            await self.page.wait_for_timeout(poll_ms)
        return last_new

    async def _wait_generation_started(self, max_s: int = 20, base=None) -> None:
        end = time.time() + max_s
        while time.time() < end:
            self._stop()
            if await self._is_generating():
                return
            if base is not None:  # ảnh mới đã xuất hiện rồi thì thôi chờ
                if any(s not in base for s in await self.generated_srcs()):
                    return
            await self.page.wait_for_timeout(400)

    async def _is_generating(self) -> bool:
        """Chỉ tính nút Dừng ĐANG HIỂN THỊ (tránh dương tính giả do nút ẩn)."""
        try:
            return await self.page.evaluate(
                """(sel) => {
                    for (const b of document.querySelectorAll(sel)) {
                        const r = b.getBoundingClientRect();
                        const st = getComputedStyle(b);
                        if (r.width > 0 && r.height > 0 &&
                            st.visibility !== 'hidden' && st.display !== 'none')
                            return true;
                    }
                    return false;
                }""",
                SEL_STOP_BTN,
            )
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    async def download_image(self, src: str, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.startswith("http"):
            try:
                resp = await self.page.context.request.get(src, timeout=60000)
                if resp.ok:
                    dest.write_bytes(await resp.body())
                    return dest
            except Exception:
                pass
        data_url = await self.page.evaluate(
            """async (src) => {
                const r = await fetch(src);
                const b = await r.blob();
                return await new Promise(res => {
                    const fr = new FileReader();
                    fr.onload = () => res(fr.result);
                    fr.readAsDataURL(b);
                });
            }""",
            src,
        )
        dest.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
        return dest

    async def refine(self, prompt: str, extra_images=None,
                     timeout_ms: int = 240000):
        """Sửa ảnh trong cuộc chat ĐANG MỞ: gửi prompt sửa (+ ảnh tham chiếu),
        chờ ảnh MỚI. Trả src ảnh mới hoặc None."""
        baseline = set(await self.generated_srcs())
        if extra_images:
            await self.upload_images([Path(p) for p in extra_images])
        await self.type_prompt(prompt)
        if not await self.send():
            return None
        await self.page.wait_for_timeout(400)
        return await self.wait_for_image(timeout_ms=timeout_ms, baseline=baseline)

    def conversation_url(self) -> str:
        return self.page.url
