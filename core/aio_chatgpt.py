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
import time
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from playwright.async_api import Page, TimeoutError as PWTimeout

from config import CHATGPT_URL

SEL_COMPOSER = "#prompt-textarea"
SEL_FILE_INPUT = 'input[type="file"]'
SEL_SEND_BTN = '[data-testid="send-button"]'
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


class AioSession:
    """Bọc 1 tab đã đăng nhập để thao tác tạo ảnh / hỏi text."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.cancel = None   # threading.Event — set khi user bấm Dừng
        self._net_done = 0   # số luồng trả lời đã kết thúc (theo dõi qua mạng)
        self._net_mark = 0   # mốc _net_done tại lần send() gần nhất
        self.http_error = 0  # mã HTTP lỗi cuối trên endpoint hội thoại
        self._attach_network()

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
        try:
            if "chatgpt.com" in (self.page.url or ""):
                btn = self.page.locator(SEL_NEW_CHAT).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await self.page.wait_for_selector(SEL_COMPOSER, timeout=8000)
                    for _ in range(12):
                        if await self._assistant_count() == 0:
                            self.http_error = 0
                            return
                        await self.page.wait_for_timeout(200)
        except Exception:
            pass
        await self.page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        await self.page.wait_for_selector(SEL_COMPOSER, timeout=30000)
        await self.page.wait_for_timeout(300)
        self.http_error = 0

    async def open_conversation(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded")
        await self.page.wait_for_selector(SEL_COMPOSER, timeout=30000)
        for _ in range(3):
            await self.page.mouse.wheel(0, 2500)
            await self.page.wait_for_timeout(500)
        await self.page.wait_for_timeout(600)

    # ------------------------------------------------------------------ #
    async def upload_images(self, paths: List[Path], timeout_ms: int = 60000) -> int:
        paths = [str(Path(p)) for p in paths]
        before = await self._count_thumbnails()
        await self.page.locator(SEL_FILE_INPUT).first.set_input_files(paths)
        target = before + len(paths)
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            if await self._count_thumbnails() >= target:
                await self.page.wait_for_timeout(500)
                return await self._count_thumbnails()
            await self.page.wait_for_timeout(300)
        return await self._count_thumbnails()

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
        await self.page.locator(SEL_COMPOSER).click()
        await self.page.evaluate(
            """(text) => {
                const el = document.querySelector('#prompt-textarea');
                if (!el) return;
                el.focus();
                const dt = new DataTransfer();
                dt.setData('text/plain', text);
                el.dispatchEvent(new ClipboardEvent('paste',
                    {clipboardData: dt, bubbles: true, cancelable: true}));
            }""",
            clean,
        )
        await self.page.wait_for_timeout(200)
        # kiểm tra, nếu lệch thì thử lại bằng insert_text
        got = await self.page.evaluate(
            "() => (document.querySelector('#prompt-textarea')||{}).innerText || ''"
        )
        if " ".join(got.split()) != clean:
            await self.page.evaluate(
                "() => { const e=document.querySelector('#prompt-textarea');"
                " if(e){e.focus();document.execCommand('selectAll',false,null);} }"
            )
            await self.page.keyboard.press("Delete")
            await self.page.keyboard.insert_text(clean)

    async def _composer_text(self) -> str:
        try:
            return await self.page.evaluate(
                "() => (document.querySelector('#prompt-textarea')||{}).innerText || ''"
            )
        except Exception:
            return ""

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
            if not (await self._composer_text()).strip():
                return True                      # ô đã trống = đã gửi
            try:
                if await self._send_ready():
                    await self.page.locator(SEL_SEND_BTN).first.click()
                else:
                    await self.page.locator(SEL_COMPOSER).click()
                    await self.page.keyboard.press("Enter")
            except Exception:
                try:
                    await self.page.locator(SEL_COMPOSER).click()
                    await self.page.keyboard.press("Enter")
                except Exception:
                    pass
            for _ in range(12):                  # chờ xác nhận ~3s mỗi lần bấm
                await self.page.wait_for_timeout(250)
                self._stop()
                if not (await self._composer_text()).strip():
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

    async def wait_for_image(self, timeout_ms: int = 180000, poll_ms: int = 1000,
                             baseline: Optional[set] = None) -> Optional[str]:
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
        await self.page.wait_for_timeout(800)
        return await self.wait_for_image(timeout_ms=timeout_ms, baseline=baseline)

    def conversation_url(self) -> str:
        return self.page.url
