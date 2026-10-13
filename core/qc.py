"""Khâu QC ảnh qua ChatGPT web (vision).

Tốn thêm 1 message/ảnh nên mặc định TẮT (DEFAULT_QC=False) để chạy nhanh.
Khi BẬT: ảnh bị QC chấm SAI SẢN PHẨM sẽ được pipeline tạo lại (xem
`pipeline._generate_checked`). QC lỗi kỹ thuật / nghi ngờ → coi như PASS.
"""
from __future__ import annotations

from pathlib import Path

from core.aio_chatgpt import AioSession, StopRequested
from core.jsonutil import parse_json


def _parts_summary(attributes: dict, n_products: int = 1) -> str:
    # nhiều biến thể màu → bỏ màu, kẻo ảnh biến thể khác màu bị chấm "sai"
    keys = ("shape",) if (n_products or 1) > 1 else ("color", "shape")
    out = []
    for p in (attributes or {}).get("parts") or []:
        if isinstance(p, dict) and p.get("name"):
            desc = ", ".join(str(p[k]) for k in keys if p.get(k))
            out.append(f"{p['name']} ({desc})" if desc else str(p["name"]))
    return "; ".join(out)


def qc_failed(qc) -> bool:
    """Chỉ coi là HỎNG khi QC nói RÕ sai sản phẩm (product_match == False)."""
    return isinstance(qc, dict) and qc.get("product_match") is False


async def qc_image(
    session: AioSession,
    image_path: Path,
    attributes: dict,
    timeout_ms: int = 90000,
    n_products: int = 1,
) -> dict:
    """Kiểm ảnh có đúng sản phẩm / có chữ lỗi không. Nghi ngờ thì PASS."""
    try:
        await session.new_chat()
        await session.upload_images([Path(image_path)])
        parts = _parts_summary(attributes, n_products)
        prompt = (
            "Bạn là QC ảnh quảng cáo, đánh giá KHOAN DUNG (nghi ngờ thì cho PASS). "
            f"Sản phẩm mong đợi: {attributes.get('short_descriptor', '')} "
            f"(nhãn: {attributes.get('exact_label_string', '')}). "
            + (f"Bộ phận: {parts}. " if parts else "") +
            "Chỉ đặt product_match=false khi sản phẩm trong ảnh RÕ RÀNG là món "
            "khác, sai hình dạng, thiếu bộ phận chính"
            + (" (sản phẩm có NHIỀU MÀU/biến thể — khác màu KHÔNG tính là sai). "
               if (n_products or 1) > 1 else " hoặc sai hẳn màu. ") +
            "Nhìn ảnh và CHỈ trả JSON: "
            '{"product_match":true,"label_ok":true,"no_placeholder_text":true,'
            '"sharp":true,"issues":[]}'
        )
        text = await session.ask_text(prompt, timeout_ms=timeout_ms)
        data = parse_json(text)
        return data if isinstance(data, dict) else {"issues": ["qc_unparsed"]}
    except StopRequested:
        raise                # user bấm Dừng → dừng ngay, không coi là PASS
    except Exception as e:
        # QC lỗi → coi như PASS (không chặn)
        return {
            "product_match": True, "label_ok": True, "no_placeholder_text": True,
            "sharp": True, "issues": [f"qc_skipped: {e}"],
        }
