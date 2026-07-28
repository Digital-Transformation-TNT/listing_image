"""Cửa sổ chính TNT Listing Image (PySide6)."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QLineEdit, QPlainTextEdit,
    QSpinBox, QComboBox, QCheckBox, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFrame, QTabWidget, QProgressBar, QScrollArea, QSplitter, QMessageBox,
    QSizePolicy, QRadioButton, QButtonGroup, QFileDialog,
)

from config import (
    PROMPT_TYPES, PROMPT_TYPE_LABELS, DEFAULT_TYPES, DEFAULT_CONCURRENCY,
    BASE_DIR, profile_path, list_profile_names, PROFILES_ROOT, load_account_names,
)
from ui_listing import theme
from ui_listing.widgets import ImagePicker, ResultCard, EditDialog, ImageViewer
from ui_listing.workers import (
    PromptWorker, SeoWorker, GenerateWorker, EditWorker, LoginWorker, NamesWorker,
)


NEW_ACC = "➕ Tài khoản mới"


def _card(title: str = "") -> QFrame:
    f = QFrame()
    f.setObjectName("Card")
    return f


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TNT Listing Image — TikTok Shop")
        self.resize(1200, 780)
        self.gen_worker = None
        self.prompt_worker = None
        self.seo_worker = None
        self.login_worker = None
        self.names_worker = None
        self.edit_workers = []
        self.results = []
        self.session_dir = None
        self._last_save_dir = None  # nhớ thư mục tải gần nhất cho lần sau
        self.analysis = {}          # {attributes, theme, seo, prompts}
        self.prompt_boxes = {}      # {type: QPlainTextEdit}
        self._syncing = False
        self.market = "Philippines"
        self._active = None         # worker đang chạy (để Dừng)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(12)

        # header
        head = QHBoxLayout()
        title = QLabel("TNT LISTING IMAGE")
        title.setObjectName("H1")
        sub = QLabel("Tạo bộ ảnh listing + SEO qua ChatGPT — TikTok Shop")
        sub.setProperty("muted", True)
        hv = QVBoxLayout()
        hv.addWidget(title)
        hv.addWidget(sub)
        head.addLayout(hv)
        head.addStretch(1)
        self.btn_stop = QPushButton("⛔ Dừng")
        self.btn_stop.setObjectName("Maroon")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        head.addWidget(self.btn_stop)
        self.lbl_status = QLabel("● Sẵn sàng")
        self.lbl_status.setStyleSheet(f"color:{theme.OK}; font-weight:700;")
        head.addWidget(self.lbl_status)
        outer.addLayout(head)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_left())
        split.addWidget(self._build_right())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([430, 770])
        outer.addWidget(split, 1)

    # ------------------------------------------------------------------ #
    def _build_left(self) -> QWidget:
        wrap = QScrollArea()
        wrap.setWidgetResizable(True)
        wrap.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        wrap.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(2, 2, 12, 2)
        lay.setSpacing(10)

        # --- TÀI KHOẢN + ĐĂNG NHẬP (trên cùng) ---
        acc = _card()
        al = QVBoxLayout(acc)
        al.setContentsMargins(12, 10, 12, 12)
        al.setSpacing(8)
        ah = QLabel("Tài khoản ChatGPT")
        ah.setObjectName("H2")
        al.addWidget(ah)
        self.cb_profile = QComboBox()
        al.addWidget(self._labeled("Tài khoản đang dùng", self.cb_profile))
        self._refresh_profiles()
        brow = QHBoxLayout()
        self.btn_login = QPushButton("Đăng nhập tài khoản này")
        self.btn_login.setObjectName("Maroon")
        self.btn_login.setMinimumHeight(38)
        self.btn_login.clicked.connect(self._on_login)
        self.btn_names = QPushButton("🔄 Cập nhật tên")
        self.btn_names.setMinimumHeight(38)
        self.btn_names.setToolTip("Lấy email các tài khoản đã đăng nhập")
        self.btn_names.clicked.connect(self._on_refresh_names)
        brow.addWidget(self.btn_login, 1)
        brow.addWidget(self.btn_names)
        al.addLayout(brow)
        hint = QLabel("Hết lượt sẽ TỰ chuyển sang tài khoản đã đăng nhập khác; hết sạch thì dừng.")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        al.addWidget(hint)
        loc = QLabel(f"📁 Tài khoản lưu ở: {PROFILES_ROOT}")
        loc.setProperty("muted", True)
        loc.setWordWrap(True)
        loc.setStyleSheet(f"color:{theme.TEXT_MUTED}; font-size:11px;")
        al.addWidget(loc)
        lay.addWidget(acc)

        # --- ẢNH ---
        # Cho phép NHIỀU ảnh sản phẩm: cùng 1 sản phẩm, khác mẫu mã/màu sắc.
        self.pick_product = ImagePicker("Ảnh sản phẩm", required=True, multiple=True)
        self.pick_product.setToolTip(
            "Có thể chọn nhiều ảnh nếu sản phẩm có nhiều mẫu mã/màu (chức năng "
            "giống nhau). App sẽ hiểu đó là cùng một sản phẩm.")
        self.pick_person = ImagePicker("Ảnh người mẫu (tùy chọn)")
        self.pick_scene = ImagePicker("Ảnh bối cảnh (tùy chọn)")
        lay.addWidget(self.pick_product)
        row_ps = QHBoxLayout()
        row_ps.addWidget(self.pick_person)
        row_ps.addWidget(self.pick_scene)
        lay.addLayout(row_ps)

        self.pick_logo = ImagePicker("Logo shop (ẢNH — dán logo thật vào ảnh)")
        lay.addWidget(self.pick_logo)

        # --- CẤU HÌNH ---
        cfg = _card()
        cl = QVBoxLayout(cfg)
        cl.setContentsMargins(12, 10, 12, 12)
        cl.setSpacing(8)
        h = QLabel("Cấu hình")
        h.setObjectName("H2")
        cl.addWidget(h)

        self.ed_info = QPlainTextEdit()
        self.ed_info.setFixedHeight(60)
        self.ed_info.setPlaceholderText("Thông tin thêm về sản phẩm (tùy chọn)")
        cl.addWidget(self._labeled("Mô tả sản phẩm", self.ed_info))

        grid = QGridLayout()
        self.sp_qty = QSpinBox(); self.sp_qty.setRange(1, 9); self.sp_qty.setValue(9)
        self.cb_lang = QComboBox(); self.cb_lang.addItems(["en", "vi"])
        self.sp_conc = QSpinBox(); self.sp_conc.setRange(1, 6); self.sp_conc.setValue(DEFAULT_CONCURRENCY)
        grid.addWidget(QLabel("Số ảnh"), 0, 0); grid.addWidget(self.sp_qty, 1, 0)
        grid.addWidget(QLabel("Ngôn ngữ chữ trên ảnh"), 0, 1); grid.addWidget(self.cb_lang, 1, 1)
        grid.addWidget(QLabel("Số luồng (song song)"), 2, 0); grid.addWidget(self.sp_conc, 3, 0)
        cl.addLayout(grid)

        self.chk_hidden = QCheckBox("Chạy ngầm (không hiện Chrome — vẫn làm việc khác được)")
        self.chk_hidden.setChecked(True)
        self.chk_hidden.setToolTip(
            "Windows: cửa sổ Chrome nằm ngoài màn hình.\n"
            "macOS: macOS không cho đẩy cửa sổ ra ngoài nên app sẽ THU NHỎ cửa sổ "
            "xuống Dock — đừng bấm mở lại cửa sổ đó trong lúc đang chạy.")
        cl.addWidget(self.chk_hidden)

        cl.addWidget(QLabel("Nguồn prompt:"))
        self.rb_chatgpt = QRadioButton("ChatGPT tự tạo (rồi vào sửa)")
        self.rb_manual = QRadioButton("Tôi tự viết prompt")
        self.rb_chatgpt.setChecked(True)
        self.src_group = QButtonGroup(self)
        self.src_group.addButton(self.rb_chatgpt)
        self.src_group.addButton(self.rb_manual)
        self.rb_manual.toggled.connect(self._on_source_changed)
        cl.addWidget(self.rb_chatgpt)
        cl.addWidget(self.rb_manual)
        lay.addWidget(cfg)

        # --- LOẠI ẢNH (đồng bộ với số ảnh) ---
        types_card = _card()
        tl = QVBoxLayout(types_card)
        tl.setContentsMargins(12, 10, 12, 12)
        self.lbl_types = QLabel("Loại ảnh")
        self.lbl_types.setObjectName("H2")
        tl.addWidget(self.lbl_types)
        self.type_checks = {}
        tg = QGridLayout()
        for i, (key, label) in enumerate(PROMPT_TYPES):
            c = QCheckBox(f"{label}")
            c.setChecked(key in DEFAULT_TYPES)
            c.toggled.connect(self._on_type_toggled)
            self.type_checks[key] = c
            tg.addWidget(c, i // 2, i % 2)
        tl.addLayout(tg)
        lay.addWidget(types_card)

        self.sp_qty.valueChanged.connect(self._on_qty_changed)
        self._sync_types_ui()

        # --- NÚT ---
        self.btn_prompt = QPushButton("① Tạo prompt")
        self.btn_prompt.setObjectName("Maroon")
        self.btn_prompt.setMinimumHeight(40)
        self.btn_prompt.clicked.connect(self._on_make_prompts)
        self.btn_gen_all = QPushButton("② TẠO ẢNH + BÀI VIẾT SEO")
        self.btn_gen_all.setObjectName("Primary")
        self.btn_gen_all.setMinimumHeight(44)
        self.btn_gen_all.setEnabled(False)
        self.btn_gen_all.setToolTip("Tạo cả bộ ảnh và bài viết SEO trong 1 lần chạy")
        self.btn_gen_all.clicked.connect(lambda: self._on_generate(want_seo=True))
        self.btn_gen = QPushButton("② Chỉ tạo ảnh")
        self.btn_gen.setMinimumHeight(40)
        self.btn_gen.setEnabled(False)
        self.btn_gen.clicked.connect(lambda: self._on_generate(want_seo=False))
        self.btn_seo = QPushButton("Chỉ tạo bài viết & tiêu đề SEO")
        self.btn_seo.clicked.connect(self._on_make_seo)
        lay.addWidget(self.btn_prompt)
        lay.addWidget(self.btn_gen_all)
        lay.addWidget(self.btn_gen)
        lay.addWidget(self.btn_seo)
        lay.addStretch(1)

        wrap.setMinimumWidth(430)
        return wrap

    # ---- đồng bộ số ảnh <-> loại ảnh ---- #
    def _checked_types(self):
        return [k for k, _ in PROMPT_TYPES if self.type_checks[k].isChecked()]

    def _on_qty_changed(self, val):
        if self._syncing:
            return
        self._syncing = True
        checked = self._checked_types()
        # số loại đang chọn > số ảnh → bỏ bớt từ cuối cho bằng
        for k in reversed(checked):
            if len(self._checked_types()) <= val:
                break
            self.type_checks[k].setChecked(False)
        self._sync_types_ui()
        self._syncing = False

    def _on_type_toggled(self, _checked):
        if self._syncing:
            return
        self._syncing = True
        self._sync_types_ui()
        self._syncing = False

    def _sync_types_ui(self):
        n = len(self._checked_types())
        q = self.sp_qty.value()
        # đủ số ảnh thì khoá các ô chưa chọn
        for k, c in self.type_checks.items():
            if not c.isChecked():
                c.setEnabled(n < q)
        self.lbl_types.setText(f"Loại ảnh (đã chọn {n}/{q})")
        # chế độ tự viết: cập nhật ô nhập theo loại đang chọn (giữ text đã gõ)
        if getattr(self, "rb_manual", None) and self.rb_manual.isChecked():
            self._rebuild_manual_boxes(switch_tab=False)

    def _on_source_changed(self):
        """Đổi nguồn prompt. Chọn 'Tự viết' → hiện ngay ô nhập."""
        if self.rb_manual.isChecked():
            self._rebuild_manual_boxes(switch_tab=True)
            self._logline(">> Chế độ TỰ VIẾT: nhập prompt cho từng ảnh ở tab 'Prompt (sửa)'.")

    def _rebuild_manual_boxes(self, switch_tab: bool = True):
        """Dựng ô nhập prompt rỗng cho các loại đang chọn, GIỮ text đã gõ."""
        types = self._selected_types()
        if not types:
            return
        existing = {t: b.toPlainText() for t, b in self.prompt_boxes.items()}
        prompts = [{"type": t, "label": PROMPT_TYPE_LABELS.get(t, t),
                    "prompt": existing.get(t, "")} for t in types]
        self.analysis = {"attributes": {}, "theme": "",
                         "prompts": prompts, "seo": self.analysis.get("seo", {})}
        self._build_prompt_boxes(prompts, prefill=True)
        self.btn_gen.setEnabled(bool(self.prompt_boxes))
        self.btn_gen_all.setEnabled(bool(self.prompt_boxes))
        if switch_tab:
            self.tabs.setCurrentIndex(1)

    def _labeled(self, text: str, w: QWidget) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        lbl = QLabel(text)
        lbl.setProperty("muted", True)
        v.addWidget(lbl)
        v.addWidget(w)
        return box

    def _build_right(self) -> QWidget:
        self.tabs = QTabWidget()

        # tab tiến độ
        prog = QWidget()
        pl = QVBoxLayout(prog)
        self.bar = QProgressBar()
        self.bar.setValue(0)
        pl.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        pl.addWidget(self.log, 1)
        self.tabs.addTab(prog, "Tiến độ")

        # tab Prompt (sửa từng ảnh)
        ptab = QWidget()
        ptl = QVBoxLayout(ptab)
        note = QLabel(
            "Sửa/viết prompt cho TỪNG ảnh rồi bấm '② TẠO ẢNH'. "
            "(ChatGPT tự tạo → đã điền sẵn để sửa; Tự viết → gõ vào)")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        ptl.addWidget(note)
        pscroll = QScrollArea()
        pscroll.setWidgetResizable(True)
        pscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.prompt_host = QWidget()
        self.prompt_layout = QVBoxLayout(self.prompt_host)
        self.prompt_layout.setAlignment(Qt.AlignTop)
        self.prompt_layout.setSpacing(10)
        pscroll.setWidget(self.prompt_host)
        ptl.addWidget(pscroll, 1)
        self.tabs.addTab(ptab, "Prompt (sửa)")

        # tab ảnh
        gtab = QWidget()
        gtl = QVBoxLayout(gtab)
        gtl.setContentsMargins(0, 0, 0, 0)
        gtl.setSpacing(6)

        # thanh công cụ: tải tất cả ảnh / mở thư mục
        gbar = QHBoxLayout()
        gbar.setContentsMargins(10, 8, 10, 0)
        self.btn_dl_all = QPushButton("⬇ Tải tất cả ảnh về máy")
        self.btn_dl_all.setObjectName("Maroon")
        self.btn_dl_all.clicked.connect(self._on_download_all)
        self.btn_dl_all.setEnabled(False)
        gbar.addWidget(self.btn_dl_all)
        self.btn_open_dir2 = QPushButton("Mở thư mục kết quả")
        self.btn_open_dir2.clicked.connect(self._open_dir)
        gbar.addWidget(self.btn_open_dir2)
        self.lbl_gallery_count = QLabel("")
        self.lbl_gallery_count.setProperty("muted", True)
        gbar.addWidget(self.lbl_gallery_count)
        gbar.addStretch(1)
        gtl.addLayout(gbar)

        gwrap = QScrollArea()
        gwrap.setWidgetResizable(True)
        self.gallery_host = QWidget()
        self.gallery = QGridLayout(self.gallery_host)
        self.gallery.setContentsMargins(10, 10, 10, 10)
        self.gallery.setSpacing(12)
        self.gallery.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        gwrap.setWidget(self.gallery_host)
        gtl.addWidget(gwrap, 1)
        self.tabs.addTab(gtab, "Ảnh kết quả")

        # tab SEO
        seo = QWidget()
        sl = QVBoxLayout(seo)
        btnrow = QHBoxLayout()
        self.btn_copy_seo = QPushButton("Copy SEO")
        self.btn_copy_seo.clicked.connect(self._copy_seo)
        self.btn_open_dir = QPushButton("Mở thư mục kết quả")
        self.btn_open_dir.clicked.connect(self._open_dir)
        btnrow.addWidget(self.btn_copy_seo)
        btnrow.addWidget(self.btn_open_dir)
        btnrow.addStretch(1)
        sl.addLayout(btnrow)
        self.seo_view = QPlainTextEdit()
        self.seo_view.setReadOnly(True)
        sl.addWidget(self.seo_view, 1)
        self.tabs.addTab(seo, "SEO / Bài viết")

        return self.tabs

    # ------------------------------------------------------------------ #
    def _detect_profiles(self):
        """Danh sách tài khoản đã có (lưu ở ổ C — PROFILES_ROOT)."""
        return list_profile_names() or ["default"]

    def _refresh_profiles(self, select: str = None):
        """Nạp lại combo: '➕ Tài khoản mới' + profile đã có (✓/○ + email nếu biết).
        Tên slot lưu ở itemData; hiển thị kèm email."""
        names_map = load_account_names()
        cur = self.cb_profile.currentData() if self.cb_profile.count() else None
        self.cb_profile.blockSignals(True)
        self.cb_profile.clear()
        self.cb_profile.addItem(NEW_ACC, "")
        first_logged = None
        for n in self._detect_profiles():
            logged = self._profile_logged_in(n)
            mark = "✓" if logged else "○"
            email = names_map.get(n, "")
            disp = f"{mark} {n}" + (f"  ·  {email}" if email else "")
            self.cb_profile.addItem(disp, n)
            if logged and first_logged is None:
                first_logged = n
        target = select or cur or first_logged
        if target:
            idx = self.cb_profile.findData(target)
            if idx >= 0:
                self.cb_profile.setCurrentIndex(idx)
        self.cb_profile.blockSignals(False)

    def _next_free_profile(self):
        existing = set(self._detect_profiles())
        i = 2
        while f"acc{i}" in existing:
            i += 1
        return f"acc{i}"

    def _profile_logged_in(self, name: str) -> bool:
        """True nếu profile có cookie session-token (đã đăng nhập, còn khi thoát app)."""
        import sqlite3, shutil, tempfile, os
        pdir = profile_path(None if name == "default" else name)
        src = Path(pdir) / "Default" / "Network" / "Cookies"
        if not src.exists():
            return False
        try:
            tmp = os.path.join(tempfile.gettempdir(), "tnt_ck_check.db")
            shutil.copy(src, tmp)
            con = sqlite3.connect(tmp)
            ok = con.execute(
                "SELECT 1 FROM cookies WHERE name LIKE "
                "'__Secure-next-auth.session-token%' LIMIT 1"
            ).fetchone() is not None
            con.close()
            return ok
        except Exception:
            return False

    def _validate(self):
        pass

    def _selected_types(self):
        return [k for k, _ in PROMPT_TYPES if self.type_checks[k].isChecked()]

    def _selected_raw(self):
        """Tên slot tài khoản đang chọn (từ itemData). '' nếu là 'Tài khoản mới'."""
        d = self.cb_profile.currentData()
        return d or ""

    def _product_extra(self):
        """Các ảnh sản phẩm PHỤ (mẫu mã/màu khác) — bỏ ảnh đầu (ảnh chính)."""
        return [Path(p) for p in self.pick_product.paths[1:]]

    def _profile_name(self):
        n = self._selected_raw()
        return None if not n or n == "default" else n

    def _gen_profile_dir(self):
        """Profile cho tạo prompt/seo: đang chọn, hoặc profile đã login đầu tiên."""
        sel = self._selected_raw()
        if sel:
            return profile_path(None if sel == "default" else sel)
        for n in self._detect_profiles():
            if self._profile_logged_in(n):
                return profile_path(None if n == "default" else n)
        return profile_path(None)

    def _profiles_for_rotation(self):
        """(profile_dir, tên) để xoay: tài khoản đang chọn trước, rồi các tài khoản khác."""
        names = self._detect_profiles()
        sel = self._selected_raw()
        if sel and sel in names:
            ordered = [sel] + [n for n in names if n != sel]
        else:
            ordered = names
        out, seen = [], set()
        for n in ordered:
            if n in seen:
                continue
            seen.add(n)
            out.append((profile_path(None if n == "default" else n), n))
        return out

    def _set_running(self, running: bool, msg: str = ""):
        self.btn_login.setEnabled(not running)
        self.btn_names.setEnabled(not running)
        self.btn_prompt.setEnabled(not running)
        self.btn_seo.setEnabled(not running)
        self.btn_gen.setEnabled((not running) and bool(self.prompt_boxes))
        self.btn_gen_all.setEnabled((not running) and bool(self.prompt_boxes))
        self.btn_stop.setEnabled(running)
        if not running:
            self._active = None
        if running:
            self.lbl_status.setText(f"● {msg or 'Đang chạy...'}")
            self.lbl_status.setStyleSheet(f"color:{theme.ORANGE}; font-weight:700;")
        else:
            self.lbl_status.setText("● Sẵn sàng")
            self.lbl_status.setStyleSheet(f"color:{theme.OK}; font-weight:700;")

    def _on_stop(self):
        if self._active is not None:
            self._logline(">> ⛔ Đang DỪNG... (chờ tác vụ hiện tại nhả ra vài giây)")
            self.btn_stop.setEnabled(False)
            self.btn_stop.setText("Đang dừng...")
            try:
                self._active.request_stop()
            except Exception:
                pass

    def _on_stopped(self):
        self._set_running(False)
        self.btn_stop.setText("⛔ Dừng")
        self._logline(">> ✓ ĐÃ DỪNG theo yêu cầu.")

    def _logline(self, s: str):
        self.log.appendPlainText(s)

    # ------------------------------------------------------------------ #
    def _on_login(self):
        sel = self._selected_raw()
        if not sel:
            # 'Tài khoản mới' → tạo profile trống kế tiếp (tránh đè tài khoản cũ)
            prof = self._next_free_profile()
            self._logline(f">> Thêm TÀI KHOẢN MỚI vào '{prof}'.")
        else:
            prof = sel
            if self._profile_logged_in(prof):
                r = QMessageBox.question(
                    self, "Đã có tài khoản",
                    f"'{prof}' đã đăng nhập rồi. Đăng nhập lại sẽ THAY tài khoản khác "
                    f"vào chỗ này.\nMuốn thêm tài khoản mới thì chọn '➕ Tài khoản mới'.\n\nVẫn tiếp tục?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if r != QMessageBox.Yes:
                    return
        self._pending_login = prof
        self._logline(f">> Mở cửa sổ đăng nhập (profile: {prof}) ở GIỮA màn hình... hãy đăng nhập.")
        self._set_running(True, "Đang chờ đăng nhập")
        self.login_worker = LoginWorker(None if prof == "default" else prof)
        self.login_worker.done.connect(self._on_login_done)
        self.login_worker.failed.connect(self._on_login_fail)
        self.login_worker.start()

    def _on_login_done(self, ok: bool):
        self._set_running(False)
        prof = getattr(self, "_pending_login", "default")
        if ok:
            self._refresh_profiles(select=prof)
            self._logline(f">> ✓ Đăng nhập '{prof}' thành công. Session ĐÃ LƯU (còn khi thoát app & mở lại).")
            QMessageBox.information(self, "Đăng nhập",
                                    f"Đăng nhập '{prof}' thành công!\nSession được lưu lâu dài.")
        else:
            self._logline(">> ✗ Hết thời gian chờ đăng nhập.")

    def _on_login_fail(self, err: str):
        self._set_running(False)
        self._logline(f">> ✗ Lỗi đăng nhập: {err}")

    # ---- Cập nhật tên (email) các tài khoản đã login ---- #
    def _on_refresh_names(self):
        profs = [(profile_path(None if n == "default" else n), n)
                 for n in self._detect_profiles() if self._profile_logged_in(n)]
        if not profs:
            QMessageBox.information(self, "Chưa có",
                                    "Chưa có tài khoản nào đã đăng nhập.")
            return
        self._set_running(True, "Đang lấy tên tài khoản")
        self._logline(f">> Lấy email {len(profs)} tài khoản đã đăng nhập (chạy ngầm)...")
        self.names_worker = NamesWorker(profs, hidden=True)
        self.names_worker.progress.connect(self._on_progress)
        self.names_worker.done.connect(self._on_names_done)
        self.names_worker.failed.connect(self._on_names_fail)
        self.names_worker.start()

    def _on_names_done(self, out: dict):
        self._set_running(False)
        self._refresh_profiles()
        got = [f"{k} = {v}" for k, v in out.items() if v]
        self._logline(">> ✓ Cập nhật tên xong: " +
                      (" | ".join(got) if got else "(không lấy được)"))

    def _on_names_fail(self, err: str):
        self._set_running(False)
        self._logline(f">> ✗ Lỗi cập nhật tên: {err}")

    # ------------------------------------------------------------------ #
    # ---- BƯỚC 1: tạo prompt (tiếng Việt, KHÔNG SEO) ---- #
    def _on_make_prompts(self):
        if not self.pick_product.path:
            QMessageBox.warning(self, "Thiếu ảnh", "Hãy chọn ẢNH SẢN PHẨM (bắt buộc).")
            return
        types = self._selected_types()
        if not types:
            QMessageBox.warning(self, "Thiếu loại ảnh", "Hãy chọn ít nhất 1 loại ảnh.")
            return

        # chế độ tự viết: chỉ mở/refresh ô nhập, không gọi ChatGPT
        if self.rb_manual.isChecked():
            self._rebuild_manual_boxes(switch_tab=True)
            self._logline(">> Chế độ TỰ VIẾT: nhập prompt cho từng ảnh rồi '② TẠO ẢNH'.")
            return

        self.log.clear()
        self.bar.setValue(0)
        self.tabs.setCurrentIndex(0)
        params = dict(
            product=Path(self.pick_product.path),
            product_extra=self._product_extra(),
            types=types,
            language=self.cb_lang.currentText(),
            product_info=self.ed_info.toPlainText().strip(),
            shop="",
            market=self.market,
            quantity=self.sp_qty.value(),
            hidden=self.chk_hidden.isChecked(),
            profile_dir=self._gen_profile_dir(),
            has_person=bool(self.pick_person.path),
            has_scene=bool(self.pick_scene.path),
        )
        self._set_running(True, "Đang tạo prompt")
        self._logline(">> [①] Tạo prompt (tiếng Việt)...")
        self.prompt_worker = PromptWorker(params)
        self._active = self.prompt_worker
        self.prompt_worker.progress.connect(self._on_progress)
        self.prompt_worker.done.connect(self._on_prompts_done)
        self.prompt_worker.failed.connect(self._on_prompts_fail)
        self.prompt_worker.stopped.connect(self._on_stopped)
        self.prompt_worker.start()

    def _on_prompts_done(self, analysis: dict):
        # giữ attributes/theme, gộp seo cũ nếu đã có
        old_seo = self.analysis.get("seo", {})
        self.analysis = analysis
        if old_seo:
            self.analysis["seo"] = old_seo
        prompts = analysis.get("prompts", [])
        self._build_prompt_boxes(prompts, prefill=True)
        self._set_running(False)
        self.tabs.setCurrentIndex(1)   # tab Prompt
        self._logline(f">> ✓ Đã tạo {len(prompts)} prompt. Sửa rồi bấm '② TẠO ẢNH'.")

    def _on_prompts_fail(self, err: str):
        self._set_running(False)
        self._logline(f">> ✗ Lỗi tạo prompt: {err}")
        QMessageBox.critical(self, "Lỗi", f"Tạo prompt lỗi:\n{err}")

    # ---- Tạo bài viết & tiêu đề SEO (riêng) ---- #
    def _on_make_seo(self):
        if not self.pick_product.path:
            QMessageBox.warning(self, "Thiếu ảnh", "Hãy chọn ẢNH SẢN PHẨM (bắt buộc).")
            return
        params = dict(
            product=Path(self.pick_product.path),
            product_info=self.ed_info.toPlainText().strip(),
            shop="",
            market=self.market,
            language=self.cb_lang.currentText(),
            hidden=self.chk_hidden.isChecked(),
            profile_dir=self._gen_profile_dir(),
        )
        self._set_running(True, "Đang tạo SEO")
        self._logline(">> Tạo bài viết & tiêu đề SEO...")
        self.seo_worker = SeoWorker(params)
        self._active = self.seo_worker
        self.seo_worker.progress.connect(self._on_progress)
        self.seo_worker.done.connect(self._on_seo_done)
        self.seo_worker.failed.connect(self._on_seo_fail)
        self.seo_worker.stopped.connect(self._on_stopped)
        self.seo_worker.start()

    def _on_seo_done(self, data: dict):
        self._set_running(False)
        self.analysis["seo"] = data.get("seo", {})
        if not self.analysis.get("attributes"):
            self.analysis["attributes"] = data.get("attributes", {})
        self._fill_seo({"seo": self.analysis["seo"], "theme": self.analysis.get("theme", "")})
        self.tabs.setCurrentIndex(3)   # tab SEO
        self._logline(">> ✓ Đã tạo bài viết & tiêu đề SEO.")

    def _on_seo_fail(self, err: str):
        self._set_running(False)
        self._logline(f">> ✗ Lỗi tạo SEO: {err}")
        QMessageBox.critical(self, "Lỗi", f"Tạo SEO lỗi:\n{err}")

    def _build_prompt_boxes(self, prompts: list, prefill: bool):
        while self.prompt_layout.count():
            it = self.prompt_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self.prompt_boxes = {}
        for p in prompts:
            t = p.get("type")
            card = QFrame()
            card.setObjectName("Card")
            # KHÓA chiều cao card → không bị kéo giãn khi ít ảnh
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            v = QVBoxLayout(card)
            v.setContentsMargins(12, 8, 12, 12)
            v.setSpacing(6)
            lbl = QLabel(f"{p.get('label') or PROMPT_TYPE_LABELS.get(t, t)}  ·  [{t}]")
            lbl.setObjectName("H2")
            v.addWidget(lbl)
            box = QPlainTextEdit()
            box.setFixedHeight(130)
            box.setPlaceholderText("Nhập prompt cho ảnh này...")
            if prefill and p.get("prompt"):
                box.setPlainText(p.get("prompt", ""))
            v.addWidget(box)
            self.prompt_layout.addWidget(card)
            self.prompt_boxes[t] = box
        self.prompt_layout.addStretch(1)   # đẩy các card lên trên, hết giãn

    # ---- BƯỚC 2: tạo ảnh từ prompt (đã sửa), tự xoay tài khoản ---- #
    def _on_generate(self, want_seo: bool = False):
        if not self.prompt_boxes:
            QMessageBox.warning(self, "Chưa có prompt",
                                "Hãy bấm '① Tạo prompt' trước.")
            return
        prompts = []
        for t, box in self.prompt_boxes.items():
            txt = box.toPlainText().strip()
            if txt:
                prompts.append({"type": t, "label": PROMPT_TYPE_LABELS.get(t, t),
                                "prompt": txt, "content": ""})
        if not prompts:
            QMessageBox.warning(self, "Prompt rỗng", "Chưa có prompt nào để tạo ảnh.")
            return
        self._clear_gallery()
        self.bar.setValue(0)
        self.bar.setMaximum(len(prompts))
        self.tabs.setCurrentIndex(0)
        params = dict(
            prompts=prompts,
            product=Path(self.pick_product.path),
            product_extra=self._product_extra(),
            person=Path(self.pick_person.path) if self.pick_person.path else None,
            scene=Path(self.pick_scene.path) if self.pick_scene.path else None,
            attributes=self.analysis.get("attributes", {}),
            theme=self.analysis.get("theme", ""),
            shop="",
            seo=self.analysis.get("seo", {}),
            market=self.market,
            concurrency=self.sp_conc.value(),
            hidden=self.chk_hidden.isChecked(),
            profiles=self._profiles_for_rotation(),
            logo=Path(self.pick_logo.path) if self.pick_logo.path else None,
            want_seo=want_seo,
            product_info=self.ed_info.toPlainText().strip(),
            language=self.cb_lang.currentText(),
        )
        self._set_running(True, "Đang tạo ảnh + SEO" if want_seo else "Đang tạo ảnh")
        self._logline(">> [②] Tạo ảnh"
                      + (" + bài viết SEO" if want_seo else "")
                      + " (tự xoay tài khoản khi hết lượt)...")
        self.gen_worker = GenerateWorker(params)
        self._active = self.gen_worker
        self.gen_worker.progress.connect(self._on_progress)
        self.gen_worker.done.connect(self._on_gen_done)
        self.gen_worker.failed.connect(self._on_gen_fail)
        self.gen_worker.stopped.connect(self._on_stopped)
        self.gen_worker.start()

    def _on_progress(self, event: str, data: dict):
        if event == "analyze_start":
            self._logline(">> Đang phân tích ảnh + sinh prompt...")
        elif event == "analyze_done":
            self._logline(f">> Xong: {data.get('n_prompts')} prompt.")
        elif event == "seo_start":
            self._logline(">> Đang phân tích + viết SEO...")
        elif event == "seo_done":
            self._logline(">> Xong SEO.")
        elif event == "name_start":
            self._logline(f">>   … đang lấy tên '{data.get('profile')}'")
        elif event == "name_done":
            self._logline(f">>   ✓ {data.get('profile')} = {data.get('email') or '(không lấy được)'}")
        elif event == "generate_start":
            self._logline(f">> Tạo {data.get('total')} ảnh (song song {data.get('concurrency')} tab)...")
            self.bar.setMaximum(data.get("total", 9))
        elif event == "account":
            self._logline(f">> ▶ Dùng tài khoản '{data.get('profile')}' ({data.get('remaining')} ảnh còn lại)")
        elif event == "account_skip":
            self._logline(f">>   ⚠ Bỏ qua '{data.get('profile')}' — {data.get('reason')}")
        elif event == "account_limit":
            self._logline(f">>   ⛔ HẾT LƯỢT '{data.get('profile')}' — chuyển tài khoản khác ({data.get('remaining')} ảnh còn lại)")
        elif event == "account_error":
            self._logline(f">>   ⚠ Lỗi tài khoản '{data.get('profile')}': {data.get('error')}")
        elif event == "exhausted":
            self._logline(f">> ✗ ĐÃ HẾT TẤT CẢ TÀI KHOẢN — còn {data.get('remaining')} ảnh chưa tạo. Dừng.")
        elif event == "stopped":
            self._logline(f">> ⛔ ĐÃ DỪNG — còn {data.get('remaining', 0)} ảnh chưa tạo.")
        elif event == "image_done":
            mark = "✓" if data.get("status") == "success" else "✗"
            self._logline(f">>   {mark} [{data.get('done')}/{data.get('total')}] {data.get('type')}")
            self.bar.setValue(data.get("done", self.bar.value()))
        elif event == "done":
            self._logline(f">> HOÀN TẤT: {data.get('ok')}/{data.get('total')} ảnh.")

    def _on_gen_done(self, out: dict):
        self._set_running(False)
        self.results = [r for r in out.get("results", []) if r.get("status") == "success"]
        self.session_dir = out.get("dir")
        self._build_gallery()
        if out.get("seo"):
            self.analysis["seo"] = out.get("seo", {})
            self._fill_seo(out)
        self.tabs.setCurrentIndex(2)   # tab Ảnh kết quả
        skipped = out.get("total", 0) - out.get("ok_count", 0)
        msg = f">> Kết quả tại: {self.session_dir}"
        if skipped > 0:
            msg += f"  (⚠ {skipped} ảnh chưa tạo do hết tài khoản — có thể chạy lại sau)"
        self._logline(msg)

    def _on_gen_fail(self, err: str):
        self._set_running(False)
        self._logline(f">> ✗ LỖI: {err}")
        QMessageBox.critical(self, "Lỗi", f"Tạo ảnh lỗi:\n{err}")

    # ------------------------------------------------------------------ #
    def _clear_gallery(self):
        while self.gallery.count():
            it = self.gallery.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def _build_gallery(self):
        self._clear_gallery()
        cols = 3
        for i, r in enumerate(self.results):
            card = ResultCard(r)
            card.edit_requested.connect(self._on_edit)
            card.view_requested.connect(self._on_view)
            card.download_requested.connect(self._on_download_one)
            self.gallery.addWidget(card, i // cols, i % cols)
        n = len(self.results)
        self.btn_dl_all.setEnabled(n > 0)
        self.lbl_gallery_count.setText(f"{n} ảnh" if n else "")

    def _on_view(self, card: ResultCard):
        ImageViewer(card.result.get("image"),
                    card.result.get("label") or card.result.get("type"), self).exec()

    # ------------------------------------------------------------------ #
    #  TẢI ẢNH VỀ MÁY
    # ------------------------------------------------------------------ #
    @staticmethod
    def _safe_name(s: str) -> str:
        """Bỏ ký tự Windows không cho phép trong tên file."""
        keep = "".join(c for c in (s or "") if c.isalnum() or c in " -_")
        return keep.strip().replace(" ", "_") or "anh"

    def _suggest_name(self, r: dict, idx: int | None = None) -> str:
        """Tên file gợi ý: 01_ten_loai.png"""
        src = Path(r.get("image", ""))
        base = self._safe_name(r.get("type") or r.get("label"))
        prefix = f"{idx:02d}_" if idx is not None else ""
        return f"{prefix}{base}{src.suffix or '.png'}"

    def _on_download_one(self, card: ResultCard):
        """Tải 1 ảnh: hỏi nơi lưu rồi copy."""
        src = card.result.get("image")
        if not src or not Path(src).is_file():
            QMessageBox.warning(self, "Không tìm thấy ảnh",
                                "File ảnh không còn trên máy.")
            return
        target_dir = self._last_save_dir or str(Path.home() / "Downloads")
        dest, _ = QFileDialog.getSaveFileName(
            self, "Lưu ảnh", str(Path(target_dir) / self._suggest_name(card.result)),
            "Ảnh (*.png *.jpg *.jpeg *.webp);;Tất cả (*)")
        if not dest:
            return
        try:
            shutil.copy2(src, dest)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi lưu ảnh", str(e))
            return
        self._last_save_dir = str(Path(dest).parent)
        self._logline(f">> Đã lưu ảnh: {dest}")
        self.statusBar().showMessage(f"Đã lưu: {Path(dest).name}", 4000)

    def _on_download_all(self):
        """Tải TẤT CẢ ảnh: chọn thư mục rồi copy toàn bộ, đánh số theo thứ tự."""
        if not self.results:
            return
        start = self._last_save_dir or str(Path.home() / "Downloads")
        folder = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục lưu tất cả ảnh", start)
        if not folder:
            return

        # Gom vào thư mục con theo phiên để không lẫn với ảnh cũ.
        sub = Path(folder) / (Path(self.session_dir).name if self.session_dir
                              else "listing_images")
        try:
            sub.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi tạo thư mục", str(e))
            return

        ok, fail = 0, []
        for i, r in enumerate(self.results, 1):
            src = r.get("image")
            if not src or not Path(src).is_file():
                fail.append(r.get("type") or f"ảnh {i}")
                continue
            try:
                shutil.copy2(src, sub / self._suggest_name(r, i))
                ok += 1
            except Exception:
                fail.append(r.get("type") or f"ảnh {i}")

        self._last_save_dir = folder
        self._logline(f">> Đã tải {ok}/{len(self.results)} ảnh về: {sub}")
        msg = f"Đã lưu {ok}/{len(self.results)} ảnh vào:\n{sub}"
        if fail:
            msg += "\n\nKhông lưu được: " + ", ".join(fail)
            QMessageBox.warning(self, "Tải xong (có lỗi)", msg)
        else:
            QMessageBox.information(self, "Tải xong", msg)

    def _on_edit(self, card: ResultCard):
        dlg = EditDialog(card.result, self)
        if not dlg.exec():
            return
        prompt, ref = dlg.get_values()
        if not prompt:
            return
        conv = card.result.get("conversation_url")
        if not conv:
            QMessageBox.warning(self, "Không sửa được",
                                "Ảnh này không có link chat để mở lại.")
            return
        # đường dẫn ảnh mới
        base = Path(card.result["image"])
        dest = base.with_name(f"{base.stem}_edit_{int(time.time())}.png")
        card.btn_edit.setEnabled(False)
        card.btn_edit.setText("Đang sửa...")
        # QUAN TRỌNG: mở lại chat bằng ĐÚNG tài khoản đã tạo ảnh này. Nếu bộ ảnh
        # được tạo qua nhiều tài khoản (xoay khi hết lượt), dùng tài khoản đang
        # chọn trên dropdown sẽ mở nhầm sang chat khác (thường là chat gần nhất)
        # → "sửa ảnh nào cũng ra ảnh cuối". Ưu tiên profile lưu trong kết quả.
        edit_profile = card.result.get("profile") or self._profile_name()
        self._logline(
            f">> Sửa ảnh [{card.result.get('type')}] (tài khoản: "
            f"{edit_profile or 'mặc định'}): {prompt[:50]}...")
        self._set_running(True, "Đang sửa ảnh")

        w = EditWorker(conv, prompt, dest,
                       [Path(ref)] if ref else None,
                       edit_profile, self.chk_hidden.isChecked())
        w.done.connect(lambda p, c=card, ww=w: self._on_edit_done(c, p, ww))
        w.failed.connect(lambda e, c=card, ww=w: self._on_edit_fail(c, e, ww))
        self.edit_workers.append(w)
        w.start()

    def _on_edit_done(self, card: ResultCard, new_path: str, worker):
        card.result["image"] = new_path
        card.refresh()
        card.btn_edit.setEnabled(True)
        card.btn_edit.setText("✎ Sửa ảnh này")
        self._set_running(False)
        self._logline(f">> ✓ Đã sửa: {Path(new_path).name}")
        if worker in self.edit_workers:
            self.edit_workers.remove(worker)

    def _on_edit_fail(self, card: ResultCard, err: str, worker):
        card.btn_edit.setEnabled(True)
        card.btn_edit.setText("✎ Sửa ảnh này")
        self._set_running(False)
        self._logline(f">> ✗ Sửa lỗi: {err}")
        if worker in self.edit_workers:
            self.edit_workers.remove(worker)

    # ------------------------------------------------------------------ #
    def _fill_seo(self, out: dict):
        from core.store import seo_text
        self.seo_view.setPlainText(
            seo_text(out.get("seo", {}) or {}, self.cb_lang.currentText()))
        return
        seo = out.get("seo", {}) or {}
        theme_s = out.get("theme", "")
        lines = []
        if theme_s:
            lines += [f"THEME: {theme_s}", ""]
        lines += [
            "SEO NAME:", seo.get("seo_name", ""), "",
            "CTR TITLES:",
        ]
        for i, t in enumerate(seo.get("ctr_titles", []) or [], 1):
            lines.append(f"  {i}. {t}")
        lines += [
            "", "SHORT TITLE:", seo.get("short_title", ""), "",
            "DESCRIPTION (dán vào ô mô tả sản phẩm):", seo.get("description", ""), "",
            "ATTRIBUTES (bảng thông số — điền form sàn):",
        ]
        attrs = seo.get("attributes", {}) or {}
        if isinstance(attrs, dict):
            for k, v in attrs.items():
                lines.append(f"  {k}: {v}")
        lines += [
            "", "KEYWORDS / TAGS:", seo.get("keywords", ""), "",
            "CATEGORY:", seo.get("category", ""),
        ]
        self.seo_view.setPlainText("\n".join(str(x) for x in lines))

    def _copy_seo(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.seo_view.toPlainText())
        self._logline(">> Đã copy SEO vào clipboard.")

    def _open_dir(self):
        if self.session_dir and os.path.isdir(self.session_dir):
            os.startfile(self.session_dir)  # Windows
        else:
            QMessageBox.information(self, "Chưa có", "Chưa có thư mục kết quả.")

    def closeEvent(self, e):
        # tránh treo khi đóng lúc worker đang chạy
        for w in [self.gen_worker, self.prompt_worker, self.seo_worker,
                  self.login_worker, self.names_worker, *self.edit_workers]:
            if w and w.isRunning():
                w.terminate()
        e.accept()
