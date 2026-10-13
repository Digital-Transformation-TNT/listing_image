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


asyncio.run(run())
print(f"\n==> {len(PASS)} passed, {len(FAIL)} failed / {len(PASS) + len(FAIL)} total")
sys.exit(1 if FAIL else 0)
