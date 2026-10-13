"""Test: trích thuộc tính chi tiết (đặc tả sản phẩm vào prompt) + QC tự tạo lại.
Logic thuần, không cần trình duyệt (generate_one / qc_image được giả lập).

Chạy:  python tests/test_attr_qc.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core.analyzer import attrs_complete, ATTR_RULES  # noqa: E402
from core.generator import _product_spec_note, _build_final_prompt  # noqa: E402
from core.qc import qc_failed, _parts_summary  # noqa: E402
from core import pipeline  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


ATTRS = {
    "product_type": "mascara",
    "parts": [
        {"name": "thân tuýp", "color": "trắng ngà bóng", "finish": "glossy", "shape": "thuôn"},
        {"name": "nắp", "color": "tím than ánh kim", "finish": "metallic", "shape": "có gân"},
    ],
    "applicator": "chổi chuốt mi",
    "exact_label_string": "QICIY 7D Colossal",
    "notable_details": ["nắp có gân dọc"],
}

# --------------------------------------------------------------------------- #
print("== trích thuộc tính: luật + kiểm tra đủ ==")
check("luật yêu cầu màu cụ thể", "CỤ THỂ" in ATTR_RULES)
check("luật cấm tự sửa chính tả nhãn", "KHÔNG tự sửa" in ATTR_RULES)
check("luật cấm bịa dụng cụ", "KHÔNG bịa" in ATTR_RULES)
check("đủ: có loại + bộ phận có tên & màu", attrs_complete(ATTRS))
check("thiếu product_type → chưa đủ", not attrs_complete({"parts": ATTRS["parts"]}))
check("không có bộ phận → chưa đủ", not attrs_complete({"product_type": "x", "parts": []}))
check("bộ phận thiếu màu → chưa đủ",
      not attrs_complete({"product_type": "x", "parts": [{"name": "thân"}]}))
check("KHÔNG bắt buộc nhãn (đồ không có chữ vẫn đủ)",
      attrs_complete({"product_type": "x", "parts": [{"name": "a", "color": "b"}]}))
check("dữ liệu rác không làm văng lỗi", not attrs_complete("abc") and not attrs_complete(None))

# --------------------------------------------------------------------------- #
print("== đặc tả sản phẩm vào prompt tạo ảnh ==")
spec = _product_spec_note(ATTRS, 1)
check("có tên bộ phận", "thân tuýp" in spec and "nắp" in spec)
check("1 màu → có màu bộ phận", "tím than ánh kim" in spec)
check("có dụng cụ đi kèm", "chổi chuốt mi" in spec)
check("có chữ nhãn nguyên văn", '"QICIY 7D Colossal"' in spec)
multi = _product_spec_note(ATTRS, 3)
check("nhiều biến thể → BỎ màu (không khoá 1 màu)",
      "tím than" not in multi and "thân tuýp" in multi)
check("không có thuộc tính → rỗng", _product_spec_note(None) == "" and _product_spec_note({}) == "")
check("bộ phận hỏng dữ liệu bị bỏ qua",
      _product_spec_note({"parts": ["x", {"color": "đỏ"}]}) == "")
fp = _build_final_prompt("Ảnh đẹp.", [Path("p.png")], False, False, attributes=ATTRS)
check("prompt cuối chứa đặc tả", "ĐẶC TẢ SẢN PHẨM" in fp and "QICIY 7D Colossal" in fp)
fp0 = _build_final_prompt("Ảnh đẹp.", [Path("p.png")], False, False)
check("không truyền thuộc tính → prompt như cũ", "ĐẶC TẢ SẢN PHẨM" not in fp0)

# --------------------------------------------------------------------------- #
print("== QC ==")
check("product_match=False → hỏng", qc_failed({"product_match": False}))
check("product_match=True → đạt", not qc_failed({"product_match": True}))
check("thiếu trường / rác → coi là đạt", not qc_failed({}) and not qc_failed(None))
check("QC 1 màu có màu bộ phận", "trắng ngà bóng" in _parts_summary(ATTRS, 1))
check("QC nhiều biến thể bỏ màu", "trắng ngà" not in _parts_summary(ATTRS, 2))


def run_checked(gen_results, qc_results, qc=True):
    """Chạy _generate_checked với generate_one/qc_image giả. Trả (res, số lần gen, số lần qc)."""
    calls = {"gen": 0, "qc": 0}
    gens, qcs = list(gen_results), list(qc_results)

    async def fake_gen(*a, **k):
        calls["gen"] += 1
        return dict(gens.pop(0))

    async def fake_qc(*a, **k):
        calls["qc"] += 1
        return dict(qcs.pop(0))

    old_gen, old_qc = pipeline.generate_one, pipeline.qc_image
    pipeline.generate_one, pipeline.qc_image = fake_gen, fake_qc
    try:
        res = asyncio.run(pipeline._generate_checked(
            None, {"type": "thumbnail", "prompt": "x"}, [Path("a.png")], None, None,
            Path("o.png"), ATTRS, "", "", None, "en", 1, qc))
    finally:
        pipeline.generate_one, pipeline.qc_image = old_gen, old_qc
    return res, calls["gen"], calls["qc"]


OK1 = {"status": "success", "image": "1.png"}
OK2 = {"status": "success", "image": "2.png"}
ERR = {"status": "error", "image": None}
GOOD, BAD = {"product_match": True}, {"product_match": False}

res, g, q = run_checked([OK1], [], qc=False)
check("QC tắt → tạo 1 lần, không soi", g == 1 and q == 0 and "qc" not in res)
res, g, q = run_checked([OK1], [GOOD])
check("QC đạt → không tạo lại", g == 1 and q == 1 and res["image"] == "1.png")
res, g, q = run_checked([OK1, OK2], [BAD, GOOD])
check("QC sai → tạo lại 1 lần, lấy ảnh mới",
      g == 2 and res["image"] == "2.png" and res.get("qc_regenerated"))
res, g, q = run_checked([OK1, ERR], [BAD])
check("tạo lại hỏng → GIỮ ảnh cũ", g == 2 and res["status"] == "success" and res["image"] == "1.png")
res, g, q = run_checked([OK1, OK2], [BAD, BAD])
check("sai cả 2 lần → dừng (không lặp vô hạn)", g == 1 + pipeline.QC_REGEN)
res, g, q = run_checked([ERR], [])
check("ảnh lỗi → không soi QC", g == 1 and q == 0 and res["status"] == "error")

print(f"\n==> {len(PASS)} passed, {len(FAIL)} failed / {len(PASS) + len(FAIL)} total")
sys.exit(1 if FAIL else 0)
