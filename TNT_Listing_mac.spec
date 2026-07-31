# -*- mode: python ; coding: utf-8 -*-
r"""
PyInstaller spec — dựng TNT Listing Image thành .app (macOS).

PHẢI build TRÊN macOS (PyInstaller KHÔNG cross-compile — không build được từ Windows).
Chạy:  bash build_mac.sh

Kết quả:  dist/TNT_Listing.app

>>> CHỐNG LỖI GIAO DIỆN MỜ NHOÈ TRÊN RETINA <<<
Khối BUNDLE(info_plist) bên dưới đặt "NSHighResolutionCapable": True. THIẾU key này
là macOS chạy app ở 1x rồi phóng to -> chữ/ảnh mờ, răng cưa (đúng lỗi gặp ở app trước).
Đừng xoá key đó. app_listing.py cũng đã đặt HighDpiScaleFactorRoundingPolicy.PassThrough.

TRÌNH DUYỆT: tool mở Chrome thật (channel="chrome") -> máy Mac phải CÀI SẴN Google
Chrome. Spec này KHÔNG nhúng Chromium (giống bản Windows).

GATEKEEPER: app chưa notarize sẽ bị macOS chặn khi tải từ mạng. build_mac.sh đã
ad-hoc codesign; người dùng cuối chỉ cần làm 1 lần:
    xattr -dr com.apple.quarantine TNT_Listing.app
hoặc chuột phải -> Open. Muốn double-click mượt hẳn cần Apple Developer ($99) để notarize.
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []

# Logo (nếu có) — icon .app + icon menu bar khi bắn thông báo.
for _logo in ("logo.icns", "logo.png"):
    if os.path.exists(_logo):
        datas.append((_logo, "."))
hiddenimports = ["core", "ui_listing", "tnt_license", "cryptography"]

# Playwright cần kèm driver (node); cryptography có phần Rust (_rust)+cffi -> collect_all
# mới gói đủ, tránh lỗi "No module named 'cryptography'" trên máy đích.
for pkg in ("playwright", "cryptography", "cffi"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += ["cryptography.hazmat.bindings._rust", "_cffi_backend"]

hiddenimports += collect_submodules("core")
hiddenimports += collect_submodules("ui_listing")

a = Analysis(
    ["app_listing.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TNT_Listing",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # app cửa sổ, không console
    disable_windowed_traceback=False,
    icon="logo.icns" if os.path.exists("logo.icns") else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TNT_Listing",
)

app = BUNDLE(
    coll,
    name="TNT_Listing.app",
    icon="logo.icns" if os.path.exists("logo.icns") else None,
    bundle_identifier="com.tntgroup.listingimage",
    info_plist={
        "CFBundleName": "TNT Listing Image",
        "CFBundleDisplayName": "TNT Listing Image",
        # *** BẮT BUỘC: không có key này -> giao diện MỜ NHOÈ trên màn Retina ***
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # App có mở cửa sổ trình duyệt -> không phải agent nền.
        "LSBackgroundOnly": False,
    },
)
