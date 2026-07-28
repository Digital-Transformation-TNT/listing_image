# TNT Listing Image

Tạo bộ ảnh listing sản phẩm + SEO cho **TikTok Shop** bằng cách lái ChatGPT web
(Playwright). Có app **PySide6** (tone màu TNT) và CLI.

> ⚠️ Tự động hoá ChatGPT là vùng xám ToS. Dùng vừa phải, xoay tài khoản khi hết
> lượt Free. Chạy `headless` bị Cloudflare chặn → dùng chế độ hiện cửa sổ hoặc
> **`hidden`** (chạy ngầm).

### Chạy ngầm (`hidden`) khác nhau theo hệ điều hành

| OS | Cách ẩn | Ghi chú |
|----|---------|---------|
| Windows | Đặt cửa sổ ở toạ độ âm (ngoài màn hình) | trong suốt với người dùng |
| macOS | macOS **kéo cửa sổ về lại màn hình** khi toạ độ âm → app tự **thu nhỏ cửa sổ xuống Dock** | đừng bấm mở lại cửa sổ đó khi đang chạy |

Kèm các cờ chống "ngủ đông" (`--disable-backgrounding-occluded-windows`,
`--disable-renderer-backgrounding`, `--disable-background-timer-throttling`) để
Chrome không bóp tốc độ tab đang ẩn — thiếu chúng thì ChatGPT đứng giữa chừng.

## Chức năng (theo promt.docx — chuẩn TikTok Shop PH)

- Bộ **9 ảnh**: thumbnail → before/after → pain point → công dụng → tính năng →
  cách dùng → chi tiết → đối tượng → chốt sale.
- Chữ trên ảnh **tiếng Anh** (mobile-first), **đồng bộ 1 theme**, tránh từ vi phạm
  (100%/cure/guaranteed/best...), tuỳ chọn **logo shop**.
- Giữ nguyên sản phẩm 100% (đủ mọi bộ phận, đúng chiều), ảnh **vuông 1080×1080**,
  ép chân thực (bớt "AI").
- **SEO**: tên chuẩn SEO EN + 3 CTR titles + tiêu đề ngắn + **bài viết mô tả** +
  keywords + category.
- **Sửa ảnh bằng prompt** (mở lại chat cũ, gửi yêu cầu sửa + ảnh tham chiếu).
- Tạo ảnh **song song nhiều tab** (nhanh).

## Cài đặt

```bash
cd TNT/listing_image
pip install -r requirements.txt
python -m playwright install chrome
```

## Chạy app (PySide6)

```bash
python app_listing.py
```

1. **Đăng nhập tài khoản** (nút) → login ChatGPT trong cửa sổ Chrome (lưu session).
2. Chọn **ảnh sản phẩm** (bắt buộc), tuỳ chọn người mẫu/bối cảnh.
3. Cấu hình (shop, số ảnh, ngôn ngữ, số luồng, tài khoản, chạy ngầm).
4. **TẠO ẢNH** → xem tiến độ → tab **Ảnh kết quả** (bấm ảnh để phóng to / **Sửa**),
   tab **SEO** để copy bài viết.

Toàn bộ việc nặng chạy trong **QThread** → app **không bao giờ đơ**.

## Chạy CLI

```bash
python run_listing.py --product data/san_pham/sp.png --shop "TNT Store" \
    --quantity 9 --concurrency 3 --hidden --profile acc2
```

Kết quả: `ket_qua/listing_YYMMDD_HHMMSS/` (ảnh + prompts.txt + listing_seo.txt +
results.json + zip).

## Nhiều tài khoản

Mỗi tài khoản = 1 profile: `--profile acc2`, `--profile acc3`... Đăng nhập:
`python cli.py login --profile acc2`.

## Build EXE

```bash
python -m PyInstaller --noconfirm TNT_Listing.spec
# ra dist/TNT_Listing/TNT_Listing.exe
```
Máy đích cần chạy `playwright install chrome` (browser không nhúng trong exe).

## Test

```bash
python tests/test_unit.py          # logic thuần (không cần trình duyệt)
python tests/test_features.py      # ép chữ EN, nhiều ảnh SP, sửa ảnh đúng tài khoản
python tests/test_ask_text.py      # chống lỗi "hỏi đi hỏi lại mãi" (trang giả)
python tests/test_send.py          # chống treo khi ảnh chưa upload xong (nút gửi)
python mac_hidden_selftest.py      # chế độ chạy ngầm có thật sự ẩn + không bị bóp tốc độ
python tests/test_integration.py   # luồng thật (cần đăng nhập)
```

`mac_hidden_selftest.py` cũng chạy tự động trên máy Mac thật của GitHub Actions:
tab **Actions → "Mac hidden-mode self-test"**.
