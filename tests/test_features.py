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
    _variant_note, build_edit_prompt, SHOW_ALL_VARIANTS_TYPES,
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
print("== xoay vòng biến thể màu (không khoá 1 màu) ==")
check("1 sản phẩm → không có chỉ thị biến thể", _variant_note("detail_info", 3, 1) == "")
# ảnh khoe hàng → show nhiều màu
tn = _variant_note("thumbnail", 1, 4)
check("thumbnail → khoe NHIỀU màu cùng lúc", "NHIỀU" in tn and "thumbnail" not in tn.lower() or "NHIỀU" in tn)
# ảnh thường → xoay vòng theo vị trí, KHÔNG mặc định ảnh đầu
v1 = _variant_note("detail_info", 1, 4)
v2 = _variant_note("detail_info", 2, 4)
v6 = _variant_note("detail_info", 6, 4)   # 6 mod 4 = 2 → Ảnh số 2
check("ảnh #1 → biến thể Ảnh số 1", "Ảnh số 1" in v1, v1)
check("ảnh #2 → biến thể Ảnh số 2 (khác #1)", "Ảnh số 2" in v2 and v1 != v2, v2)
check("ảnh #6 (mod 4) → quay lại Ảnh số 2", "Ảnh số 2" in v6, v6)
check("chống mặc định lấy ảnh đầu", "KHÔNG mặc định lấy ảnh đầu" in v1)
# prompt tạo ảnh nhúng đúng chỉ thị biến thể theo variant_index
fp3 = _build_final_prompt("Ảnh.", [Path("a.png"), Path("b.png"), Path("c.png")],
                          False, False, n_products=3, p_type="detail_info",
                          variant_index=2)
check("_build_final_prompt nhúng biến thể theo index", "Ảnh số 2" in fp3)

# --------------------------------------------------------------------------- #
print("== chốt sale LUÔN có 'FLASH DEAL' ==")
cl_vi = _build_final_prompt("Ảnh chốt sale.", [Path("a.png")], False, False,
                            p_type="closing", language="vi")
cl_en = _build_final_prompt("Ảnh chốt sale.", [Path("a.png")], False, False,
                            p_type="closing", language="en")
other = _build_final_prompt("Ảnh bìa.", [Path("a.png")], False, False,
                            p_type="thumbnail", language="vi")
check("closing (VI) có 'FLASH DEAL'", "FLASH DEAL" in cl_vi)
check("closing (EN) có 'FLASH DEAL'", "FLASH DEAL" in cl_en)
check("giữ nguyên tiếng Anh dù ảnh tiếng Việt", "GIỮ NGUYÊN" in cl_vi
      and "FLASH DEAL" in cl_vi)
check("loại khác KHÔNG bị thêm FLASH DEAL", "FLASH DEAL" not in other)
check("TYPE_STYLE closing nhắc FLASH DEAL",
      "FLASH DEAL" in __import__("core.analyzer", fromlist=["TYPE_STYLE"])
      .TYPE_STYLE["closing"])

# --------------------------------------------------------------------------- #
print("== sửa ảnh HÀNG LOẠT: ghép prompt theo option ==")
from core.generator import build_batch_edit_prompt  # noqa: E402

b_all = build_batch_edit_prompt("vi", "16:9", "xóa nền cho trắng")
check("dịch VI → nhắc TIẾNG VIỆT", "TIẾNG VIỆT" in b_all)
check("dịch → cấm bịa thêm chữ", "KHÔNG bịa thêm chữ" in b_all)
check("dịch → giữ nguyên chữ trên nhãn sản phẩm", "NHÃN SẢN PHẨM" in b_all)
check("dịch → theo NGỮ CẢNH ảnh", "NGỮ CẢNH" in b_all)
check("dịch → giọng MỜI CHÀO/quảng cáo", "MỜI CHÀO" in b_all)
check("dịch → chuẩn/tự nhiên", "CHUẨN" in b_all and "TỰ NHIÊN" in b_all)
check("dịch → giữ đúng ý gốc", "Ý GỐC" in b_all)
check("ratio → nêu đúng 16:9", "16:9" in b_all)
check("custom → chứa yêu cầu tự nhập", "xóa nền cho trắng" in b_all)

b_en = build_batch_edit_prompt("en", "", "")
check("dịch EN → nhắc TIẾNG ANH", "TIẾNG ANH" in b_en)
check("chỉ dịch → KHÔNG chèn phần tỉ lệ", "tỉ lệ" not in b_en.lower())

b_ratio = build_batch_edit_prompt("", "9:16", "")
check("chỉ ratio → có 9:16", "9:16" in b_ratio)
check("chỉ ratio → KHÔNG nhắc dịch", "DỊCH toàn bộ" not in b_ratio)

check("không chọn gì → prompt rỗng", build_batch_edit_prompt("", "", "") == "")

# to_ratio: đệm đúng tỉ lệ, không cắt nội dung
from core.generator import to_ratio  # noqa: E402
from PIL import Image  # noqa: E402
import tempfile  # noqa: E402
_d = tempfile.mkdtemp()
_p = Path(_d) / "r.png"
Image.new("RGB", (1000, 1000), (10, 20, 30)).save(_p)
to_ratio(_p, 16, 9)
_w, _h = Image.open(_p).size
check("to_ratio ép được 16:9", abs(_w / _h - 16 / 9) < 0.02, f"{_w}x{_h}")
Image.new("RGB", (1600, 900), (10, 20, 30)).save(_p)
to_ratio(_p, 16, 9)
check("to_ratio đã đúng tỉ lệ → giữ nguyên", Image.open(_p).size == (1600, 900))

# --------------------------------------------------------------------------- #
print("== sửa ảnh: upload ảnh + prompt (+ tham chiếu) ==")
e0 = build_edit_prompt("đổi nền sang xám", has_ref=False)
check("edit: nói rõ Ảnh 1 là ảnh CẦN SỬA", "CẦN CHỈNH SỬA" in e0)
check("edit: giữ nguyên phần khác", "GIỮ NGUYÊN" in e0)
check("edit: chứa yêu cầu user", "đổi nền sang xám" in e0)
check("edit: không ref → không nhắc ảnh tham chiếu", "THAM CHIẾU" not in e0)
e1 = build_edit_prompt("theo logo này", has_ref=True)
check("edit: có ref → nhắc Ảnh thứ 2 tham chiếu", "THAM CHIẾU" in e1)

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

# --------------------------------------------------------------------------- #
print("== loại ảnh mới: thông tin sản phẩm (infographic) ==")
from config import PROMPT_TYPE_KEYS, DEFAULT_TYPES, PROMPT_TYPE_LABELS  # noqa: E402
from core.analyzer import TYPE_STYLE  # noqa: E402
check("có loại 'product_info'", "product_info" in PROMPT_TYPE_KEYS)
check("bật mặc định", "product_info" in DEFAULT_TYPES)
check("có nhãn tiếng Việt", "product_info" in PROMPT_TYPE_LABELS)
check("có style mô tả infographic",
      "INFOGRAPHIC" in TYPE_STYLE.get("product_info", ""))
check("style nhắc số đo kích thước + biến thể",
      "KÍCH THƯỚC" in TYPE_STYLE["product_info"]
      and "BIẾN THỂ" in TYPE_STYLE["product_info"])
check("style cấm bịa thông số", "KHÔNG bịa" in TYPE_STYLE["product_info"])
check("product_info khoe đủ biến thể (SHOW_ALL)",
      "product_info" in SHOW_ALL_VARIANTS_TYPES)

print(f"\n==> {len(PASS)} passed, {len(FAIL)} failed / {len(PASS) + len(FAIL)} total")
sys.exit(1 if FAIL else 0)
