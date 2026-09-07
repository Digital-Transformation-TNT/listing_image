"""CLI chạy pipeline listing đầy đủ (web + song song).

Ví dụ:
    python run_listing.py --product data/san_pham/sp1.png \
        --person data/nguoi_mau/nm2.png --quantity 5 --concurrency 3 \
        --info "Kem dưỡng trắng body 4in1 SPF50"

Kết quả (ảnh + prompts.txt + listing_text.txt + results.json + zip) nằm trong
ket_qua/listing_YYMMDD_HHMMSS/.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import tnt_track
from tnt_license import check_license

# Khoá tool trong nhật ký sử dụng — ĐỂ RIÊNG với "listing_image" của bản web,
# gộp chung thì bảng "Chi tiết theo tool" cộng số của hai bản làm một.
FEATURE = "listing_image_app"
from core.pipeline import run_pipeline
from config import DEFAULT_TYPES, DEFAULT_CONCURRENCY, PROMPT_TYPE_KEYS, profile_path


def progress(event: str, data: dict) -> None:
    if event == "analyze_start":
        print(">> [1/3] Đang phân tích ảnh + sinh prompt...", flush=True)
    elif event == "analyze_done":
        print(f">> [1/3] Xong: {data['n_prompts']} prompt.", flush=True)
    elif event == "generate_start":
        print(f">> [2/3] Tạo {data['total']} ảnh, song song {data['concurrency']} tab...",
              flush=True)
    elif event == "image_done":
        mark = "✓" if data["status"] == "success" else "✗"
        print(f">>   {mark} [{data['done']}/{data['total']}] {data['type']}",
              flush=True)
    elif event == "done":
        print(f">> [3/3] HOÀN TẤT: {data['ok']}/{data['total']} ảnh. Zip: {data['zip']}",
              flush=True)


async def _main(args) -> None:
    types = ([t.strip() for t in args.types.split(",") if t.strip()]
             if args.types else list(DEFAULT_TYPES))
    out = await run_pipeline(
        product=Path(args.product),
        person=Path(args.person) if args.person else None,
        scene=Path(args.scene) if args.scene else None,
        types=types,
        quantity=args.quantity,
        language=args.language,
        product_info=args.info,
        shop=args.shop,
        market=args.market,
        concurrency=args.concurrency,
        qc=args.qc,
        want_seo=not args.no_seo,
        headless=args.headless,
        hidden=args.hidden,
        profile_dir=profile_path(args.profile),
        progress=progress,
    )
    print(f"\n>> Thư mục kết quả: {out['dir']}", flush=True)
    print(f">> {out['ok_count']}/{out['total']} ảnh thành công.", flush=True)


def main() -> None:
    info = check_license("TNT_Listing")
    # Chỉ ĐỌC tên nhân viên đã ký sẵn trong license.
    tnt_track.init(FEATURE, license_info=info, tool="TNT_Listing")   # BẢO MẬT LICENSE
    ap = argparse.ArgumentParser(description="TNT Listing Image — pipeline web (song song)")
    ap.add_argument("--product", required=True, help="Ảnh sản phẩm (bắt buộc)")
    ap.add_argument("--person", help="Ảnh người mẫu (tùy chọn)")
    ap.add_argument("--scene", help="Ảnh bối cảnh (tùy chọn)")
    ap.add_argument("--types", help=f"Loại ảnh, phẩy. Có: {','.join(PROMPT_TYPE_KEYS)}")
    ap.add_argument("--quantity", type=int, default=9, help="Số ảnh (1-9)")
    ap.add_argument("--language", default="en", choices=["vi", "en"],
                    help="Ngôn ngữ chữ trên ảnh (mặc định en cho PH)")
    ap.add_argument("--info", default="", help="Thông tin thêm về sản phẩm")
    ap.add_argument("--shop", default="", help="Tên shop (thêm logo shop vào ảnh)")
    ap.add_argument("--market", default="Philippines", help="Thị trường mục tiêu")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                    help="Số tab tạo ảnh song song")
    ap.add_argument("--qc", action="store_true", help="Bật QC ảnh (chậm hơn)")
    ap.add_argument("--no-seo", action="store_true", help="Bỏ phần SEO/bài viết")
    ap.add_argument("--headless", action="store_true",
                    help="Ẩn hẳn (KHÔNG khuyến nghị — ChatGPT/Cloudflare chặn)")
    ap.add_argument("--hidden", action="store_true",
                    help="Chạy NGẦM: trình duyệt thật nhưng cửa sổ ra ngoài màn hình")
    ap.add_argument("--profile", default=None,
                    help="Tài khoản/profile ChatGPT (vd: acc2). Bỏ trống = mặc định")
    args = ap.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
