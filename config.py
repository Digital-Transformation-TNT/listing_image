"""Cấu hình đường dẫn & hằng số cho TNT Listing Image."""
import os
import sys
import shutil
from pathlib import Path

# Thư mục app: khi đóng gói exe thì cạnh exe, khi chạy code thì cạnh file này.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

# ---- PROFILE CHROME lưu Ở Ổ C (CỐ ĐỊNH) ------------------------------- #
# Nằm NGOÀI app → update/build lại app vẫn giữ nguyên các tài khoản đã login.
# Có thể đổi chỗ bằng biến môi trường TNT_PROFILES_DIR.
PROFILES_ROOT = Path(
    os.environ.get("TNT_PROFILES_DIR") or (Path.home() / "TNT_Listing" / "profiles")
)


def profile_path(name: str | None = None):
    """Thư mục profile theo TÊN tài khoản, nằm trong PROFILES_ROOT (ổ C)."""
    key = "default" if not name or name == "default" else \
        "".join(c for c in name if c.isalnum() or c in "-_")
    return PROFILES_ROOT / key


PROFILE_DIR = profile_path("default")


import json

ACCOUNTS_FILE = PROFILES_ROOT / "accounts.json"


def load_account_names() -> dict:
    """{profile_name: email/tên tài khoản ChatGPT} đã lưu."""
    try:
        return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_account_name(profile: str, email: str):
    if not email:
        return
    try:
        d = load_account_names()
        d[profile] = email
        PROFILES_ROOT.mkdir(parents=True, exist_ok=True)
        ACCOUNTS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception:
        pass


def list_profile_names():
    """Danh sách tên tài khoản (profile) đã có trong PROFILES_ROOT."""
    names = []
    try:
        for p in sorted(PROFILES_ROOT.iterdir()):
            if p.is_dir() and (p / "Default").exists():
                names.append(p.name)
    except Exception:
        pass
    if "default" in names:
        names = ["default"] + [n for n in names if n != "default"]
    return names


def migrate_old_profiles():
    """Chuyển profile CŨ (cạnh app: .chrome_profile*) sang PROFILES_ROOT (ổ C) 1 lần."""
    try:
        PROFILES_ROOT.mkdir(parents=True, exist_ok=True)
        moves = []
        old_default = BASE_DIR / ".chrome_profile"
        if old_default.exists():
            moves.append((old_default, PROFILES_ROOT / "default"))
        for p in BASE_DIR.glob(".chrome_profile_*"):
            moves.append((p, PROFILES_ROOT / p.name.replace(".chrome_profile_", "")))
        for src, dst in moves:
            if src.exists() and not dst.exists():
                shutil.move(str(src), str(dst))
    except Exception:
        pass

# Dữ liệu đầu vào
DATA_DIR = BASE_DIR / "data"
PRODUCT_DIR = DATA_DIR / "san_pham"      # ảnh sản phẩm
MODEL_DIR = DATA_DIR / "nguoi_mau"       # ảnh người mẫu
INPUT_XLSX = DATA_DIR / "input.xlsx"     # danh sách job

# Kết quả: ket_qua/{id}/v1.png, v2.png ...
OUTPUT_DIR = BASE_DIR / "ket_qua"

# ChatGPT
CHATGPT_URL = "https://chatgpt.com/"

# Selector nhận biết đã đăng nhập (ô nhập prompt của ChatGPT).
# Gom về đây để khi ChatGPT đổi giao diện chỉ sửa 1 chỗ.
SELECTOR_COMPOSER = "#prompt-textarea"

# ------------------------------------------------------------------ #
# LOGIC LISTING (theo tài liệu listing-image-gpt-logic.md)
# ------------------------------------------------------------------ #

# 9 loại ảnh — CẤU TRÚC LISTING CHUẨN theo promt.docx (TikTok Shop PH)
PROMPT_TYPES = [
    ("thumbnail", "Ảnh bìa / đại diện"),
    ("before_after", "Trước & Sau / Kết quả"),
    ("pain_point", "Nỗi đau khách hàng"),
    ("main_benefit", "Công dụng chính"),
    ("features", "Tính năng nổi bật"),
    ("how_to_use", "Cách sử dụng"),
    ("detail_info", "Chi tiết / chất liệu / thành phần"),
    ("product_info", "Thông tin sản phẩm (infographic)"),
    ("audience", "Đối tượng / tình huống dùng"),
    ("closing", "Chốt sale / tạo niềm tin"),
]
PROMPT_TYPE_KEYS = [k for k, _ in PROMPT_TYPES]
PROMPT_TYPE_LABELS = dict(PROMPT_TYPES)

# Mặc định: cả bộ 9 ảnh
DEFAULT_TYPES = list(PROMPT_TYPE_KEYS)

# Loại dùng ảnh người / ảnh cảnh (quyết định lúc chọn ref)
USE_PERSON_TYPES = {
    "thumbnail", "before_after", "pain_point", "how_to_use", "audience"
}
USE_SCENE_TYPES = {"audience", "how_to_use"}

# Số tab tạo ảnh SONG SONG (nút cổ chai tốc độ). Tăng = nhanh hơn nhưng
# rủi ro bị ChatGPT/Cloudflare chặn cao hơn. 3 là mức cân bằng.
DEFAULT_CONCURRENCY = 3

# QC ảnh (vision) — tốn thêm 1 message/ảnh. Tắt để nhanh hơn.
DEFAULT_QC = False

# Ngôn ngữ CHỮ TRÊN ẢNH mặc định — tiếng Anh cho thị trường Philippines.
DEFAULT_LANGUAGE = "en"

# Thị trường mục tiêu
DEFAULT_MARKET = "Philippines"

# Từ ngữ CẤM (dễ vi phạm chính sách) — không được xuất hiện trong text/SEO.
BANNED_CLAIMS = [
    "100%", "cure", "guaranteed", "guarantee", "permanent", "best",
    "number 1", "no.1", "doctor approved", "miracle",
]

# Kích thước ảnh output cố định — VUÔNG 1080x1080
TARGET_SIZE = 1080
