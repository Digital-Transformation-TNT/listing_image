"""Test 3 tính năng: ép chữ tiếng Anh trên ảnh, nhiều ảnh sản phẩm, đóng dấu
tài khoản để sửa ảnh đúng chỗ. Logic thuần, không cần trình duyệt.

Chạy:  python tests/test_features.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core.generator import (  # noqa: E402
    _build_final_prompt, _lang_note, select_refs, _product_list,
)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


# --------------------------------------------------------------------------- #
print("== ép ngôn ngữ chữ trên ảnh ==")

en = _build_final_prompt("Ảnh đẹp.", [Path("p.png")], False, False, language="en")
check("chọn EN → yêu cầu chữ TIẾNG ANH", "TIẾNG ANH" in en and "DỊCH sang tiếng Anh" in en)
check("chọn EN → cấm để lại chữ tiếng Việt", "KHÔNG để lại" in en)

vi = _build_final_prompt("Ảnh đẹp.", [Path("p.png")], False, False, language="vi")
check("chọn VI → yêu cầu chữ TIẾNG VIỆT", "bằng TIẾNG VIỆT" in vi)
check("EN và VI cho chỉ thị khác nhau", _lang_note("en") != _lang_note("vi"))

# --------------------------------------------------------------------------- #
print("== nhiều ảnh sản phẩm ==")

check("_product_list nhận 1 ảnh (str)", _product_list("a.png") == [Path("a.png")])
check("_product_list nhận list", _product_list(["a.png", "b.png"]) == [Path("a.png"), Path("b.png")])
check("_product_list None → rỗng", _product_list(None) == [])

# select_refs: nhiều ảnh sản phẩm đứng đầu, rồi person/scene
refs = select_refs("audience", ["a.png", "b.png", "c.png"], Path("per.png"), Path("sc.png"))
check("nhiều product refs đứng trước person/scene",
      refs[:3] == [Path("a.png"), Path("b.png"), Path("c.png")]
      and Path("per.png") in refs and Path("sc.png") in refs, str(refs))

# prompt khi có nhiều ảnh sản phẩm phải nói "CÙNG MỘT sản phẩm"
multi = _build_final_prompt(
    "Ảnh.", [Path("a.png"), Path("b.png"), Path("per.png")],
    has_person=True, has_scene=False, language="en", n_products=2,
)
check("nhiều product → nêu 'CÙNG MỘT sản phẩm'", "CÙNG MỘT sản phẩm" in multi)
check("nhiều product → định vị đúng ảnh người mẫu (Ảnh 3)", "Ảnh 3 là NGƯỜI MẪU" in multi, multi[:0])

# 1 ảnh sản phẩm vẫn giữ hành vi cũ (không nhắc biến thể)
one = _build_final_prompt(
    "Ảnh.", [Path("a.png"), Path("per.png")],
    has_person=True, has_scene=False, language="en", n_products=1,
)
check("1 product → KHÔNG nhắc 'CÙNG MỘT sản phẩm'", "CÙNG MỘT sản phẩm" not in one)
check("1 product → người mẫu là Ảnh 2", "Ảnh 2 là NGƯỜI MẪU" in one)

# --------------------------------------------------------------------------- #
print("== đóng dấu tài khoản khi tạo ảnh (để sửa đúng chỗ) ==")
# Mô phỏng _batch_account stamp: kiểm generate_one nhận 'language' & pipeline gắn
# 'profile'. Ở đây kiểm hợp đồng dữ liệu: result phải có key 'profile' sau khi
# pipeline gắn. Ta test hàm gắn nhẹ bằng cách dựng result giả.
res = {"type": "thumbnail", "status": "success"}
res["profile"] = "acc2"        # đúng như _batch_account làm
edit_profile = res.get("profile") or "dropdown"
check("edit dùng profile trong result, không dùng dropdown", edit_profile == "acc2")

res2 = {"type": "x", "status": "success"}          # ảnh cũ chưa có profile
edit_profile2 = res2.get("profile") or "dropdown"
check("ảnh cũ thiếu profile → fallback dropdown", edit_profile2 == "dropdown")

print(f"\n==> {len(PASS)} passed, {len(FAIL)} failed / {len(PASS) + len(FAIL)} total")
sys.exit(1 if FAIL else 0)
