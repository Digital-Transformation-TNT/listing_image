"""Test: không vào được ô chat ChatGPT → báo lỗi ĐÚNG NGUYÊN NHÂN (không còn
'Timeout 30000ms exceeded' khó hiểu). Dùng Chromium thật + trang ChatGPT GIẢ
(chặn mạng, trả HTML tự dựng) nên không cần đăng nhập.

Chạy:  python tests/test_page_error.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from playwright.async_api import async_playwright  # noqa: E402

from core.aio_chatgpt import (  # noqa: E402
    AioSession, ChatGPTPageError, explain_page_problem,
)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


PAGES = {
    "ok": '<div id="prompt-textarea" contenteditable="true">&nbsp;</div>',
    "cloudflare": "<h1>Verify you are human</h1>"
                  '<iframe src="https://challenges.cloudflare.com/x"></iframe>',
    "logout": '<p>Your session has expired.</p><button data-testid="login-button">Log in</button>',
    "unknown": "<title>Something else</title><p>Maintenance</p>",
}

print("== câu báo lỗi ==")
check("Cloudflare → hướng dẫn bỏ chạy ngầm", "Chạy ngầm" in explain_page_problem({"cf": True}))
check("đăng xuất → hướng dẫn đăng nhập lại", "Đăng nhập" in explain_page_problem({"login": True}))
check("không rõ → nêu trang đang mở",
      "Maint" in explain_page_problem({"title": "Maint", "url": "https://chatgpt.com/"}))
check("không có thông tin vẫn ra câu báo", "ô nhập chat" in explain_page_problem({}))


async def run():
    exe = "/opt/pw-browsers/chromium"
    async with async_playwright() as p:
        kw = {"executable_path": exe} if os.path.exists(exe) else {}
        b = await p.chromium.launch(**kw)
        try:
            for kind, html in PAGES.items():
                page = await b.new_page()

                async def handle(route, _request=None, html=html):
                    await route.fulfill(status=200, content_type="text/html",
                                        body=f"<html><body>{html}</body></html>")
                await page.route("https://chatgpt.com/**", handle)
                await page.goto("https://chatgpt.com/")
                s = AioSession(page)
                err = None
                try:
                    await s.wait_composer(timeout_ms=800)
                except ChatGPTPageError as e:
                    err = str(e)
                if kind == "ok":
                    check("trang bình thường → không lỗi", err is None, err or "")
                elif kind == "cloudflare":
                    check("nhận ra bị bắt xác minh", err and "XÁC MINH" in err, err or "")
                elif kind == "logout":
                    check("nhận ra bị đăng xuất", err and "ĐĂNG XUẤT" in err, err or "")
                else:
                    check("lỗi lạ → nêu trang + gợi ý", err and "Something else" in err, err or "")
                if err:
                    check(f"[{kind}] có chụp màn hình", "Ảnh chụp màn hình" in err, err)
                await page.close()
        finally:
            await b.close()


# Giao diện MỚI (10/2026): ô soạn KHÔNG còn id #prompt-textarea.
SEND_JS = ("<script>document.addEventListener('click', ev => {"
           "  if (!ev.target.closest('[data-testid=send-button]')) return;"
           "  const c = document.querySelector('[contenteditable=true], textarea');"
           "  if (c.tagName === 'TEXTAREA') c.value = ''; else c.innerText = '';"
           "  window.__sent = (window.__sent || 0) + 1; });</script>")
NEW_UI = {
    "contenteditable": '<form><div class="ProseMirror" contenteditable="true" '
                       'role="textbox" style="min-height:40px">&nbsp;</div>'
                       '<button type="button" data-testid="send-button">Send</button></form>',
    "textarea": '<form><textarea placeholder="Ask ChatGPT"></textarea>'
                '<button type="button" data-testid="send-button">Send</button></form>',
}


async def run_new_ui():
    exe = "/opt/pw-browsers/chromium"
    async with async_playwright() as p:
        kw = {"executable_path": exe} if os.path.exists(exe) else {}
        b = await p.chromium.launch(**kw)
        try:
            for kind, html in NEW_UI.items():
                page = await b.new_page()

                async def handle(route, _request=None, html=html):
                    await route.fulfill(status=200, content_type="text/html",
                                        body=f"<html><body>{html}{SEND_JS}</body></html>")
                await page.route("https://chatgpt.com/**", handle)
                await page.goto("https://chatgpt.com/")
                s = AioSession(page)
                err = None
                try:
                    await s.wait_composer(timeout_ms=2000)
                except ChatGPTPageError as e:
                    err = str(e)
                check(f"[{kind}] tìm được ô soạn kiểu mới", err is None, err or "")
                await s.type_prompt("Xin chào   ChatGPT ơi")
                got = await s._composer_text()
                check(f"[{kind}] gõ đúng nội dung", (got or "").strip() == "Xin chào ChatGPT ơi", repr(got))
                ok = await s.send()
                sent = await page.evaluate("() => window.__sent || 0")
                check(f"[{kind}] gửi được + xác nhận ô trống", ok and sent >= 1, f"ok={ok} sent={sent}")
                await page.close()
            # Không có ô soạn → KHÔNG được báo 'đã gửi' nhầm
            page = await b.new_page()
            await page.set_content("<p>trống</p>")
            s = AioSession(page)
            check("không thấy ô soạn → không coi là ô trống/đã gửi",
                  await s._composer_text() is None and not await s._composer_empty())
            await page.close()
        finally:
            await b.close()


# Không có ô chọn file sẵn: nút '+' trực tiếp mở hộp chọn file, hoặc mở MENU
# rồi mới có mục 'Add photos & files'.
UPLOAD_UI = {
    "plus_direct": '<button aria-label="Add photos & files" onclick="'
                   "const i=document.createElement('input');i.type='file';i.multiple=true;"
                   "i.onchange=()=>{window.__files=i.files.length;};i.click();"
                   '">+</button>',
    "plus_menu": '<button data-testid="composer-plus-btn" onclick="'
                 "document.getElementById('m').style.display='block'"
                 '">+</button><div id="m" style="display:none">'
                 '<div role="menuitem" onclick="'
                 "const i=document.createElement('input');i.type='file';i.multiple=true;"
                 "i.onchange=()=>{window.__files=i.files.length;};i.click();"
                 '">Add photos &amp; files</div></div>',
}


# Nhiều ô chọn file ẩn: ô ĐẦU là camera 1 file ('Take a photo') — lỗi thật 14/10.
INPUT_UI = {
    "camera_first": '<input id="cam" type="file" class="hidden" accept="image/*" '
                    'capture="environment" aria-label="Take a photo">'
                    '<input id="multi" type="file" multiple accept="image/*">',
    "single_only": '<input id="one" type="file" accept="image/*">',
}


async def run_inputs():
    import tempfile
    exe = "/opt/pw-browsers/chromium"
    tmp = Path(tempfile.mkdtemp())
    files = []
    for n in ("a.png", "b.png", "c.png"):
        f = tmp / n
        f.write_bytes(b"x")
        files.append(f)
    async with async_playwright() as p:
        kw = {"executable_path": exe} if os.path.exists(exe) else {}
        b = await p.chromium.launch(**kw)
        try:
            for kind, html in INPUT_UI.items():
                page = await b.new_page()
                await page.set_content(html)
                await page.evaluate("() => document.querySelectorAll('input').forEach(i => {"
                                    "i.onchange = () => { window.__got = (window.__got || [])"
                                    ".concat([i.id + ':' + i.files.length]); }; })")
                s = AioSession(page)
                err = ""
                try:
                    await s.upload_images(files, timeout_ms=300)
                except Exception as e:
                    err = repr(e)
                got = await page.evaluate("() => window.__got || []")
                if kind == "camera_first":
                    check("bỏ qua ô camera, nạp 3 ảnh vào ô nhiều file",
                          got == ["multi:3"] and not err, f"{got} {err}")
                else:
                    check("chỉ có ô 1 file → nạp lần lượt 3 lần",
                          got == ["one:1"] * 3 and not err, f"{got} {err}")
                await page.close()
        finally:
            await b.close()


async def run_upload():
    import tempfile
    exe = "/opt/pw-browsers/chromium"
    tmp = Path(tempfile.mkdtemp())
    files = []
    for n in ("a.png", "b.png"):
        f = tmp / n
        f.write_bytes(b"x")
        files.append(f)
    async with async_playwright() as p:
        kw = {"executable_path": exe} if os.path.exists(exe) else {}
        b = await p.chromium.launch(**kw)
        try:
            for kind, html in UPLOAD_UI.items():
                page = await b.new_page()
                await page.set_content(html)
                s = AioSession(page)
                steps = []
                s.on_step = steps.append
                try:
                    await s.upload_images(files, timeout_ms=500)
                except Exception as e:
                    steps.append(repr(e))
                got = await page.evaluate("() => window.__files || 0")
                check(f"[{kind}] tải ảnh qua nút đính kèm", got == 2, f"files={got} {steps}")
                check(f"[{kind}] có ghi nhật ký bước", any("tải 2 ảnh" in x for x in steps), str(steps))
                await page.close()
        finally:
            await b.close()


asyncio.run(run())
asyncio.run(run_new_ui())
asyncio.run(run_upload())
asyncio.run(run_inputs())
print(f"\n==> {len(PASS)} passed, {len(FAIL)} failed / {len(PASS) + len(FAIL)} total")
sys.exit(1 if FAIL else 0)
