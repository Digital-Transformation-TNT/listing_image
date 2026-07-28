"""Widget phụ: ô chọn ảnh, thẻ kết quả, dialog xem/sửa ảnh."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QDialog, QPlainTextEdit, QDialogButtonBox, QWidget,
)

from ui_listing import theme


def _thumb(path: str, w: int, h: int) -> QPixmap:
    pm = QPixmap(str(path))
    if pm.isNull():
        return pm
    return pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)


_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


class ImagePicker(QFrame):
    """Ô chọn ảnh: nút chọn + xem trước + xóa. Hỗ trợ KÉO-THẢ ảnh vào.

    multiple=True: chọn/kéo-thả NHIỀU ảnh (vd 1 sản phẩm nhiều mẫu mã/màu).
    `.path`  = ảnh đầu tiên (giữ tương thích code cũ).
    `.paths` = danh sách toàn bộ ảnh đã chọn.
    """
    changed = Signal()

    def __init__(self, title: str, required: bool = False, multiple: bool = False,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAcceptDrops(True)   # cho phép kéo-thả ảnh
        self.multiple = multiple
        self.paths: list[str] = []
        self._title = title
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)
        star = " *" if required else ""
        multi_hint = " (có thể chọn nhiều ảnh)" if multiple else ""
        cap = QLabel(f"{title}{star}{multi_hint}")
        cap.setObjectName("H2")
        lay.addWidget(cap)
        hint = ("Kéo-thả nhiều ảnh vào đây\nhoặc bấm Chọn ảnh" if multiple
                else "Kéo-thả ảnh vào đây\nhoặc bấm Chọn ảnh")
        self.preview = QLabel(hint)
        self.preview.setProperty("muted", True)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(96)
        self.preview.setStyleSheet(
            f"border:1px dashed {theme.BORDER}; border-radius:8px; color:{theme.TEXT_MUTED};")
        lay.addWidget(self.preview)
        row = QHBoxLayout()
        self.btn = QPushButton("Chọn ảnh")
        self.btn.clicked.connect(self._pick)
        self.btn_clear = QPushButton("Xóa")
        self.btn_clear.clicked.connect(self._clear)
        row.addWidget(self.btn)
        row.addWidget(self.btn_clear)
        lay.addLayout(row)

    # -- tương thích code cũ: .path là ảnh đầu tiên -- #
    @property
    def path(self) -> Optional[str]:
        return self.paths[0] if self.paths else None

    def _pick(self):
        if self.multiple:
            fs, _ = QFileDialog.getOpenFileNames(
                self, "Chọn ảnh (có thể chọn nhiều)", "",
                "Ảnh (*.png *.jpg *.jpeg *.webp)")
            if fs:
                self.add_paths(fs)
        else:
            f, _ = QFileDialog.getOpenFileName(
                self, "Chọn ảnh", "", "Ảnh (*.png *.jpg *.jpeg *.webp)")
            if f:
                self.set_path(f)

    def set_path(self, f: str):
        """Đặt DUY NHẤT 1 ảnh (thay thế danh sách hiện tại)."""
        self.paths = [f]
        self._render()

    def add_paths(self, files):
        """Thêm nhiều ảnh (bỏ trùng, giữ thứ tự)."""
        if not self.multiple:
            if files:
                self.set_path(files[0])
            return
        for f in files:
            if f and f not in self.paths:
                self.paths.append(f)
        self._render()

    def _render(self):
        n = len(self.paths)
        if n == 0:
            self.preview.clear()
            self.preview.setText("Chưa chọn")
        else:
            pm = _thumb(self.paths[0], 220, 120)
            if not pm.isNull():
                self.preview.setPixmap(pm)
            self.preview.setText("" if n == 1 else f"+{n - 1} ảnh khác")
            if n > 1:
                self.preview.setToolTip("\n".join(Path(p).name for p in self.paths))
        self.changed.emit()

    def _clear(self):
        self.paths = []
        self.preview.clear()
        self.preview.setText("Chưa chọn")
        self.preview.setToolTip("")
        self.changed.emit()

    # --- kéo-thả ảnh ---
    def _image_urls(self, md):
        out = []
        if md.hasUrls():
            for u in md.urls():
                f = u.toLocalFile()
                if f and f.lower().endswith(_IMG_EXT):
                    out.append(f)
        return out

    def dragEnterEvent(self, e):
        if self._image_urls(e.mimeData()):
            self.preview.setStyleSheet(
                f"border:2px dashed {theme.ORANGE}; border-radius:8px; color:{theme.ORANGE};")
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self.preview.setStyleSheet(
            f"border:1px dashed {theme.BORDER}; border-radius:8px; color:{theme.TEXT_MUTED};")

    def dropEvent(self, e):
        fs = self._image_urls(e.mimeData())
        self.preview.setStyleSheet(
            f"border:1px dashed {theme.BORDER}; border-radius:8px; color:{theme.TEXT_MUTED};")
        if fs:
            self.add_paths(fs) if self.multiple else self.set_path(fs[0])
            e.acceptProposedAction()


class ResultCard(QFrame):
    """Thẻ 1 ảnh kết quả: xem trước (click phóng to) + nút Sửa + nút Tải về."""
    edit_requested = Signal(object)   # phát chính card
    view_requested = Signal(object)
    download_requested = Signal(object)

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("Thumb")
        self.result = result
        self.setFixedWidth(210)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.img = QLabel()
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setFixedHeight(180)
        self.img.setCursor(Qt.PointingHandCursor)
        self.img.mousePressEvent = lambda e: self.view_requested.emit(self)
        lay.addWidget(self.img)

        cap = QLabel(f"{result.get('label') or result.get('type')}")
        cap.setObjectName("H2")
        cap.setWordWrap(True)
        lay.addWidget(cap)

        self.btn_edit = QPushButton("✎ Sửa ảnh này")
        self.btn_edit.setObjectName("Maroon")
        self.btn_edit.clicked.connect(lambda: self.edit_requested.emit(self))
        lay.addWidget(self.btn_edit)

        self.btn_dl = QPushButton("⬇ Tải ảnh về")
        self.btn_dl.setToolTip("Lưu ảnh này ra thư mục bạn chọn")
        self.btn_dl.clicked.connect(lambda: self.download_requested.emit(self))
        lay.addWidget(self.btn_dl)

        self.refresh()

    def refresh(self):
        pm = _thumb(self.result.get("image"), 190, 180)
        if not pm.isNull():
            self.img.setPixmap(pm)
        else:
            self.img.setText("(lỗi ảnh)")


class ImageViewer(QDialog):
    """Xem ảnh phóng to."""
    def __init__(self, path: str, title: str = "Xem ảnh", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 800)
        lay = QVBoxLayout(self)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        pm = QPixmap(str(path))
        if not pm.isNull():
            lbl.setPixmap(pm.scaled(720, 720, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(lbl)


class EditDialog(QDialog):
    """Nhập prompt sửa ảnh (+ ảnh tham chiếu tùy chọn)."""
    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sửa ảnh bằng prompt")
        self.resize(560, 560)
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(180, 180)
        self.preview.setAlignment(Qt.AlignCenter)
        pm = _thumb(result.get("image"), 180, 180)
        if not pm.isNull():
            self.preview.setPixmap(pm)
        top.addWidget(self.preview)
        info = QLabel(
            f"Loại: {result.get('label') or result.get('type')}\n\n"
            "Nhập yêu cầu chỉnh sửa (tiếng Việt/Anh đều được).\n"
            "Ảnh cũ + ngữ cảnh vẫn được ChatGPT nhớ."
        )
        info.setWordWrap(True)
        info.setProperty("muted", True)
        top.addWidget(info, 1)
        lay.addLayout(top)

        lay.addWidget(QLabel("Yêu cầu sửa:"))
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "VD: đổi nền sang tông xám tối, làm chữ tiêu đề to hơn, thêm bóng đổ...")
        self.prompt.setFixedHeight(90)
        lay.addWidget(self.prompt)

        # Ô upload ảnh tham chiếu: xem trước + KÉO-THẢ + xoá (tái dùng ImagePicker).
        self.ref_picker = ImagePicker("Ảnh tham chiếu (tùy chọn)")
        self.ref_picker.setToolTip(
            "Kéo-thả hoặc chọn 1 ảnh để ChatGPT tham chiếu khi sửa "
            "(VD: ảnh mẫu bố cục, ảnh logo, ảnh màu muốn theo).")
        lay.addWidget(self.ref_picker)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Gửi sửa")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def get_values(self):
        return self.prompt.toPlainText().strip(), self.ref_picker.path
