"""QThread workers — chạy pipeline async trong luồng nền, phát signal về GUI.

Nguyên tắc CHỐNG ĐƠ: mọi việc nặng (Playwright/asyncio) chạy trong QThread.run().
GUI thread chỉ nhận signal (Qt tự queue qua thread) → cửa sổ không bao giờ freeze.
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from core.pipeline import (
    make_prompts_pipeline, make_seo_pipeline, generate_from_prompts,
    edit_image, do_login, refresh_account_names,
)
from core.aio_chatgpt import StopRequested
from config import profile_path


class NamesWorker(QThread):
    """Lấy email/tên các tài khoản đã login (mở nhanh, chạy nền)."""
    progress = Signal(str, dict)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, profiles, hidden=True, parent=None):
        super().__init__(parent)
        self.profiles = profiles
        self.hidden = hidden

    def run(self):
        try:
            def cb(e, d):
                self.progress.emit(e, dict(d or {}))
            out = asyncio.run(refresh_account_names(
                self.profiles, hidden=self.hidden, progress=cb))
            self.done.emit(out)
        except Exception as e:
            self.failed.emit(repr(e))


class _CancellableWorker(QThread):
    """Base: có cancel event + request_stop + tín hiệu stopped."""
    progress = Signal(str, dict)
    done = Signal(dict)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, params: dict, parent=None):
        super().__init__(parent)
        self.params = params
        self.cancel_event = threading.Event()

    def request_stop(self):
        self.cancel_event.set()

    def _run_fn(self, fn):
        try:
            def cb(event: str, data: dict):
                self.progress.emit(event, dict(data or {}))
            out = asyncio.run(fn(progress=cb, cancel=self.cancel_event,
                                 **self.params))
            self.done.emit(out)
        except StopRequested:
            self.stopped.emit()
        except Exception as e:
            if self.cancel_event.is_set():
                self.stopped.emit()
            else:
                self.failed.emit(repr(e))


class PromptWorker(_CancellableWorker):
    """① Chỉ tạo PROMPT (tiếng Việt) — không SEO, không ảnh."""
    def run(self):
        self._run_fn(make_prompts_pipeline)


class SeoWorker(_CancellableWorker):
    """Tạo bài viết & tiêu đề SEO (tiếng Anh, đúng docx)."""
    def run(self):
        self._run_fn(make_seo_pipeline)


class GenerateWorker(_CancellableWorker):
    """② Tạo ảnh từ prompt CHO SẴN — tự xoay tài khoản; hủy được."""
    def run(self):
        self._run_fn(generate_from_prompts)


class EditWorker(QThread):
    done = Signal(str)     # đường dẫn ảnh mới
    failed = Signal(str)

    def __init__(self, image_path: str, edit_prompt: str, dest: Path,
                 extra_images: Optional[List[Path]], profile: Optional[str],
                 hidden: bool, conversation_url: str = "", parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.conversation_url = conversation_url
        self.edit_prompt = edit_prompt
        self.dest = dest
        self.extra_images = extra_images
        self.profile = profile
        self.hidden = hidden

    def run(self):
        try:
            out = asyncio.run(edit_image(
                self.image_path, self.edit_prompt, self.dest,
                extra_images=self.extra_images,
                profile_dir=profile_path(self.profile), hidden=self.hidden,
                conversation_url=self.conversation_url,
            ))
            if out:
                self.done.emit(out)
            else:
                self.failed.emit("Không tạo được ảnh mới (có thể hết lượt).")
        except Exception as e:
            self.failed.emit(repr(e))


class LoginWorker(QThread):
    done = Signal(bool)
    failed = Signal(str)

    def __init__(self, profile: Optional[str], parent=None):
        super().__init__(parent)
        self.profile = profile

    def run(self):
        try:
            ok = asyncio.run(do_login(profile_dir=profile_path(self.profile)))
            self.done.emit(ok)
        except Exception as e:
            self.failed.emit(repr(e))
