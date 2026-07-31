"""Test SỬA ẢNH SONG SONG (nhiều ảnh cùng lúc) + xếp hàng theo tài khoản.

Yêu cầu: đang sửa ảnh 1 vẫn gửi sửa tiếp ảnh 3, 4, 7... Nhưng KHÔNG được mở
2 trình duyệt trên cùng 1 tài khoản (Chrome khoá user-data-dir). Vì vậy:
  - ảnh KHÁC tài khoản  → chạy SONG SONG thật.
  - ảnh CÙNG tài khoản  → xếp HÀNG, chạy lần lượt (xong cái này mới tới cái kia).

Chạy:  python tests/test_edit_concurrent.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# GUI chạy không màn hình để test được trên CI/nền.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
import ui_listing.window as window_mod       # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f"  [{extra}]" if extra and not cond else ""))


class _FakeSignal:
    def connect(self, *_a, **_k):
        pass


class FakeEditWorker:
    """Thay EditWorker thật: KHÔNG mở trình duyệt, chỉ ghi lại tham số."""
    instances = []

    def __init__(self, src, prompt, dest, ref, profile, hidden,
                 conversation_url=""):
        self.src = src
        self.profile = profile
        self.done = _FakeSignal()
        self.failed = _FakeSignal()
        self.started = False
        FakeEditWorker.instances.append(self)

    def start(self):
        self.started = True

    def isRunning(self):
        return self.started


class FakeBtn:
    def __init__(self):
        self.enabled = True
        self.text = "✎ Sửa ảnh này"

    def setEnabled(self, v):
        self.enabled = v

    def setText(self, t):
        self.text = t


class FakeCard:
    def __init__(self, type_, profile):
        self.result = {"type": type_, "profile": profile, "image": "x.png",
                       "conversation_url": ""}
        self.btn_edit = FakeBtn()

    def refresh(self):
        pass


def _job(win, card, prompt="sửa nền"):
    return dict(card=card, prompt=prompt, dest=Path("out.png"), ref=None,
                profile=card.result.get("profile"),
                conv="", src="x.png")


def main():
    app = QApplication.instance() or QApplication([])
    window_mod.EditWorker = FakeEditWorker      # tráo worker giả
    FakeEditWorker.instances.clear()
    win = window_mod.MainWindow()

    a = FakeCard("thumbnail", "acc1")   # ảnh 1 — tài khoản 1
    b = FakeCard("features", "acc1")    # ảnh 3 — CÙNG tài khoản 1
    c = FakeCard("closing", "acc2")     # ảnh 4 — tài khoản 2

    # Đang sửa ảnh 1 (acc1) → gửi tiếp ảnh 3 (acc1) và ảnh 4 (acc2).
    win._enqueue_edit(_job(win, a))
    win._enqueue_edit(_job(win, b))
    win._enqueue_edit(_job(win, c))

    running = {w.profile for w in win.edit_workers}
    check("acc1 + acc2 chạy song song", running == {"acc1", "acc2"},
          str(running))
    check("acc1 chỉ 1 worker (không mở 2 Chrome cùng profile)",
          sum(w.profile == "acc1" for w in win.edit_workers) == 1)
    check("ảnh cùng acc1 phải xếp hàng chờ", len(win._edit_pending) == 1)
    check("thẻ ảnh chờ hiện 'Đang chờ'", "chờ" in b.btn_edit.text.lower())
    check("3 thẻ đều đang bận (disabled)",
          not a.btn_edit.enabled and not b.btn_edit.enabled
          and not c.btn_edit.enabled)

    # Sửa xong ảnh 1 (acc1) → ảnh 3 (acc1) tự tới lượt.
    worker_a = next(w for w in win.edit_workers if w.src == "x.png"
                    and w.profile == "acc1")
    win._after_edit(worker_a)
    check("ảnh 1 xong → thẻ mở lại", a.btn_edit.enabled)
    check("ảnh 3 (acc1) tự chạy sau khi ảnh 1 xong",
          len(win._edit_pending) == 0
          and any(w.profile == "acc1" for w in win.edit_workers)
          and not b.btn_edit.enabled)
    check("vẫn không có 2 worker acc1 cùng lúc",
          sum(w.profile == "acc1" for w in win.edit_workers) == 1)

    # Sửa nốt các worker còn lại → về rảnh.
    for w in list(win.edit_workers):
        win._after_edit(w)
    check("hết job → không còn worker/chờ",
          not win.edit_workers and not win._edit_pending)
    check("mọi thẻ trở lại nút 'Sửa ảnh này'",
          all(x.btn_edit.enabled for x in (a, b, c)))

    # Không cho sửa xen khi đang chạy tác vụ chính.
    win._active = object()
    blocked = win._block_if_editing()  # không đang sửa → không chặn ở đây
    check("không sửa thì tác vụ chính không bị chặn", blocked is False)
    win._active = None

    print(f"\n==> {len(PASS)} passed, {len(FAIL)} failed / {len(PASS)+len(FAIL)} total")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
