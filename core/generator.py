"""Khâu TẠO ẢNH qua ChatGPT web (1 ảnh / 1 tab / 1 chat mới).

Web cho upload nhiều ảnh cùng lúc → KHÔNG cần ghép PIL như bản API (edits).
Ta upload thẳng: sản phẩm (+ người / + cảnh tùy loại). Model giữ sản phẩm
tốt hơn khi thấy ảnh gốc rõ ràng.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PIL import Image

from core.aio_chatgpt import AioSession, StopRequested
from config import USE_PERSON_TYPES, USE_SCENE_TYPES, TARGET_SIZE


def overlay_logo(image_path: Path, logo_path: Path,
                 ratio: float = 0.17, margin: float = 0.035) -> None:
    """Dán LOGO THẬT (ảnh) vào góc trên-phải — logo chính xác 100%, không do AI vẽ."""
    try:
        img = Image.open(image_path).convert("RGBA")
        W, H = img.size
        logo = Image.open(logo_path).convert("RGBA")
        lw = max(1, int(W * ratio))
        lh = max(1, int(logo.height * lw / logo.width))
        logo = logo.resize((lw, lh), Image.LANCZOS)
        m = int(W * margin)
        img.alpha_composite(logo, (W - lw - m, m))
        img.convert("RGB").save(image_path)
    except Exception:
        pass


def to_ratio(path: Path, rw: int, rh: int) -> None:
    """Ép ảnh về đúng tỉ lệ rw:rh bằng cách ĐỆM viền (không cắt mất nội dung).

    Chỉ đệm thêm cho đủ khung nên nếu ChatGPT đã trả gần đúng tỉ lệ thì phần
    đệm rất nhỏ. Màu đệm lấy trung bình 4 góc để hòa với nền."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if w <= 0 or h <= 0:
        return
    target = rw / rh
    cur = w / h
    if abs(cur - target) < 0.01:
        img.save(path)
        return
    if cur < target:                 # quá cao/hẹp → nới CHIỀU RỘNG
        new_w, new_h = int(round(h * target)), h
    else:                            # quá rộng → nới CHIỀU CAO
        new_w, new_h = w, int(round(w / target))
    px = img.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    avg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    canvas = Image.new("RGB", (max(new_w, w), max(new_h, h)), avg)
    canvas.paste(img, ((canvas.width - w) // 2, (canvas.height - h) // 2))
    canvas.save(path)


def to_square(path: Path, size: int = TARGET_SIZE) -> None:
    """Ép ảnh về VUÔNG size×size. Nếu chưa vuông thì đệm viền bằng màu mép ảnh."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if w != h:
        side = max(w, h)
        px = img.load()
        corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
        avg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
        canvas = Image.new("RGB", (side, side), avg)
        canvas.paste(img, ((side - w) // 2, (side - h) // 2))
        img = canvas
    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    img.save(path)


def _product_list(product) -> List[Path]:
    """Chuẩn hoá 'product' về danh sách Path (nhận 1 ảnh hoặc nhiều ảnh)."""
    if product is None:
        return []
    if isinstance(product, (str, Path)):
        return [Path(product)]
    return [Path(p) for p in product if p]


def select_refs(
    p_type: str,
    product,
    person: Optional[Path] = None,
    scene: Optional[Path] = None,
) -> List[Path]:
    """Chọn ảnh tham chiếu upload theo loại ảnh (giống USE_*_TYPES của MD).

    `product` có thể là 1 ảnh hoặc DANH SÁCH ảnh (cùng sản phẩm, khác mẫu mã).
    Ảnh sản phẩm luôn đứng ĐẦU danh sách refs (person/scene sau)."""
    refs: List[Path] = _product_list(product) or [Path(product)]
    if p_type in USE_PERSON_TYPES and person:
        refs.append(Path(person))
    if p_type in USE_SCENE_TYPES and scene:
        refs.append(Path(scene))
    return refs


# Chỉ thị CHÂN THỰC — chống vẻ AI, áp cho mọi ảnh.
REALISM = (
    "Ảnh CHỤP THẬT chuyên nghiệp bằng máy DSLR full-frame (ống kính 50mm f/4), "
    "phong cách nhiếp ảnh thương mại chân thực như ảnh studio thật, KHÔNG phải "
    "AI/3D render/CGI. Bề mặt vật có chất liệu & phản chiếu tự nhiên đúng vật lý; "
    "nếu có người thì DA có kết cấu và lỗ chân lông, KHÔNG làm mịn/nhựa hóa, tóc "
    "có sợi bay tự nhiên; ánh sáng vật lý đúng, bóng đổ mềm nhất quán một nguồn "
    "sáng; bokeh quang học và độ sâu trường ảnh thật; màu TRUNG THỰC không rực "
    "giả, cân bằng trắng tự nhiên; hạt film rất nhẹ. Tránh đối xứng máy móc, "
    "tránh bóng nhựa/CGI, tránh vẻ hoàn hảo giả tạo, tránh over-sharpen/HDR quá."
)
# Chỉ thị ĐÚNG LOGIC — chống lỗi AI (méo, thừa ngón, chữ vô nghĩa, vật lơ lửng...).
LOGIC = (
    "PHẢI ĐÚNG LOGIC & GIẢI PHẪU, KHÔNG lỗi kiểu AI: sản phẩm hiển thị NGUYÊN "
    "VẸN đúng hình dạng thật, KHÔNG méo mó/biến dạng/tan chảy, KHÔNG tự nhân đôi "
    "hay lặp sản phẩm ngoài ý muốn, KHÔNG thừa/thiếu bộ phận. Nếu có bàn tay: "
    "ĐÚNG 5 ngón, cầm nắm tự nhiên đúng cách dùng thực tế, không dính/thừa/thiếu "
    "ngón, khớp và tỉ lệ tay đúng. Vật đặt trên bề mặt phải có ĐIỂM TỰA thật, "
    "KHÔNG lơ lửng; bóng đổ và phản chiếu khớp đúng vị trí vật và nguồn sáng. "
    "Mọi CHỮ trong ảnh phải là từ CÓ NGHĨA, đúng chính tả, KHÔNG chữ méo/nhòe/vô "
    "nghĩa, không lặp chữ lỗi. Tỉ lệ, phối cảnh, số lượng vật thể hợp lý thực tế."
)
_MODEST = "Modest, fully appropriate commercial advertising photography."

# Các loại ảnh NÊN khoe nhiều màu/biến thể cùng lúc (thay vì 1 màu).
# product_info = tờ thông tin có cột biến thể → phải thấy đủ các màu/mùi.
SHOW_ALL_VARIANTS_TYPES = {"thumbnail", "features", "audience", "product_info"}

# Ảnh CHỐT SALE luôn phải có nhãn "FLASH DEAL" nổi bật (yêu cầu cố định của tool).
FLASH_DEAL_NOTE = (
    'BẮT BUỘC có nhãn/badge chữ "FLASH DEAL" nổi bật, dễ thấy (ví dụ dải/băng '
    'khuyến mãi màu tương phản ở góc hoặc phía trên), chữ to rõ. GIỮ NGUYÊN cụm '
    'từ "FLASH DEAL" bằng TIẾNG ANH viết HOA dù ngôn ngữ chữ trên ảnh là gì. '
    "Kèm lời kêu gọi chốt sale (CTA) ngắn gọn."
)


def _variant_note(p_type: str, variant_index: int, n_products: int) -> str:
    """Chỉ thị BIẾN THỂ khi có nhiều ảnh sản phẩm (nhiều màu/mẫu).

    Trước đây prompt bảo 'chọn MỘT biến thể tiêu biểu' → model mặc định lấy ảnh
    ĐẦU TIÊN → cả bộ chỉ 1 màu. Nay: ảnh khoe hàng thì show NHIỀU màu; ảnh còn
    lại XOAY vòng qua từng biến thể để cả bộ thể hiện đủ dải màu/mẫu."""
    if n_products <= 1:
        return ""
    if p_type in SHOW_ALL_VARIANTS_TYPES:
        return (
            f"NHIỀU BIẾN THỂ: có {n_products} màu/mẫu (Ảnh 1..{n_products}). Ảnh "
            "này NÊN thể hiện NHIỀU (hoặc tất cả) màu/mẫu cùng lúc, sắp xếp gọn "
            "gàng để khoe đủ dải sản phẩm; mọi biến thể giữ ĐÚNG chức năng, hình "
            "dạng và bộ phận, chỉ khác màu/kiểu."
        )
    k = ((max(1, variant_index) - 1) % n_products) + 1
    return (
        f"NHIỀU BIẾN THỂ: có {n_products} màu/mẫu (Ảnh 1..{n_products}). Ảnh này "
        f"hãy thể hiện ĐÚNG biến thể ở Ảnh số {k}. KHÔNG mặc định lấy ảnh đầu "
        f"tiên — bám đúng màu/mẫu của Ảnh số {k} (giữ nguyên chức năng/hình dạng)."
    )


def build_edit_prompt(user_edit: str, has_ref: bool = False) -> str:
    """Prompt SỬA ẢNH: tạo lại đúng ảnh đính kèm + chỉ áp dụng thay đổi user yêu cầu."""
    ref = (" Ảnh thứ 2 là ẢNH THAM CHIẾU: dùng làm mẫu cho yêu cầu "
           "(màu/bố cục/logo/phong cách...)." if has_ref else "")
    return (
        "Ảnh 1 (đính kèm) là ảnh SẢN PHẨM CẦN CHỈNH SỬA." + ref +
        " Hãy TẠO LẠI đúng ảnh đó và CHỈ áp dụng thay đổi sau, GIỮ NGUYÊN mọi "
        "phần khác (sản phẩm, bố cục, các chữ không liên quan, ánh sáng): "
        + (user_edit or "").strip() +
        " Giữ sản phẩm nguyên vẹn (đủ mọi bộ phận, đúng chiều, đúng màu trừ khi "
        "yêu cầu đổi màu), ảnh VUÔNG tỉ lệ 1:1 (1080x1080), CHỤP THẬT không giống "
        "AI, đúng logic (không méo, tay đúng 5 ngón, chữ có nghĩa đúng chính tả). "
        + _MODEST
    )


# Nhãn tỉ lệ khung cho prompt sửa hàng loạt.
RATIO_LABELS = {"1:1": "vuông 1:1", "16:9": "ngang 16:9", "9:16": "dọc 9:16"}


def build_batch_edit_prompt(translate_to: str = "", ratio: str = "",
                            custom: str = "") -> str:
    """Ghép prompt SỬA HÀNG LOẠT từ các option user chọn (áp CHUNG cho mọi ảnh).

    translate_to: '', 'vi' hoặc 'en' — dịch chữ trong ảnh.
    ratio: '', '1:1', '16:9', '9:16' — đổi tỉ lệ khung.
    custom: prompt tự nhập thêm (tùy chọn).
    Trả '' nếu không chọn option nào."""
    tasks: List[str] = []
    tl = (translate_to or "").lower()
    if tl.startswith("vi") or tl.startswith("en"):
        lang = "TIẾNG VIỆT" if tl.startswith("vi") else "TIẾNG ANH"
        tasks.append(
            f"CHUYỂN NGỮ toàn bộ chữ HIỂN THỊ/OVERLAY (tiêu đề, caption, badge, "
            f"nút, CTA...) trên ảnh sang {lang}, dịch THẬT CHUẨN và TỰ NHIÊN như "
            "người bản xứ, dùng ĐÚNG thuật ngữ ngành hàng của sản phẩm này. Dịch "
            "THEO NGỮ CẢNH của ảnh quảng cáo (hiểu ý cả cụm để dịch cho khớp, "
            "KHÔNG dịch word-by-word máy móc, KHÔNG dịch sai nghĩa), và chọn cách "
            f"diễn đạt mang GIỌNG VĂN MỜI CHÀO / QUẢNG CÁO BÁN HÀNG hấp dẫn, đúng "
            f"văn phong marketing {lang} (câu chữ ngắn gọn, thu hút, thúc đẩy mua). "
            "GIỮ ĐÚNG Ý GỐC và thông điệp của từng cụm chữ — chỉ diễn đạt lại cho "
            "hay và tự nhiên, TUYỆT ĐỐI KHÔNG bịa thêm chữ, KHÔNG thêm câu/ý/khẩu "
            "hiệu mới, KHÔNG phóng đại thêm công dụng, KHÔNG bỏ bớt ý, KHÔNG đổi "
            "số liệu. Giữ NGUYÊN vị trí, bố cục, kiểu font, màu và cỡ chữ. ĐẶC "
            "BIỆT: KHÔNG dịch và KHÔNG chỉnh sửa các CHỮ IN TRÊN BAO BÌ/NHÃN SẢN "
            "PHẨM (tên thương hiệu, nhãn, thông số in trên chính sản phẩm) — giữ "
            "NGUYÊN GỐC 100%."
        )
    r = (ratio or "").strip()
    if r in RATIO_LABELS:
        tasks.append(
            f"Đổi KHUNG ảnh sang tỉ lệ {r} ({RATIO_LABELS[r]}). Bố trí/mở rộng nền "
            "cho khớp khung mới một cách tự nhiên, KHÔNG cắt mất sản phẩm hay chữ "
            "quan trọng, KHÔNG bóp méo, KHÔNG kéo giãn sai tỉ lệ."
        )
    if custom and custom.strip():
        tasks.append(custom.strip())
    if not tasks:
        return ""
    lines = [
        "Ảnh 1 (đính kèm) là ảnh CẦN CHỈNH SỬA. Hãy TẠO LẠI đúng ảnh đó và CHỈ áp "
        "dụng các yêu cầu sau, GIỮ NGUYÊN mọi phần khác (sản phẩm, bố cục, ánh sáng, "
        "và mọi chữ KHÔNG được nhắc tới):",
    ]
    for i, t in enumerate(tasks, 1):
        lines.append(f"{i}. {t}")
    lines.append(
        "Giữ sản phẩm nguyên vẹn (đủ mọi bộ phận, đúng chiều, đúng màu). Ảnh CHỤP "
        "THẬT không giống AI, đúng logic (không méo, tay đúng 5 ngón, chữ có nghĩa "
        "đúng chính tả). " + _MODEST
    )
    return "\n".join(lines)


def _lang_note(language: str) -> str:
    """Chỉ thị NGÔN NGỮ cho chữ hiển thị trên ảnh (áp lúc TẠO ảnh).

    Prompt do ChatGPT sinh viết bằng tiếng Việt (để user dễ sửa) nên nếu không
    ép ở bước tạo ảnh, model hay in luôn chữ tiếng Việt lên ảnh. Đây là lý do
    'chọn English mà ảnh vẫn ra tiếng Việt'."""
    if (language or "").lower().startswith("en"):
        return (
            "NGÔN NGỮ CHỮ TRÊN ẢNH: TẤT CẢ chữ hiển thị trên ảnh (tiêu đề, nhãn, "
            "badge, nút, mọi caption) PHẢI bằng TIẾNG ANH. Nếu prompt mô tả chữ "
            "bằng tiếng Việt thì DỊCH sang tiếng Anh tự nhiên, ĐÚNG chính tả; "
            "TUYỆT ĐỐI KHÔNG để lại bất kỳ chữ tiếng Việt nào trên ảnh."
        )
    return (
        "NGÔN NGỮ CHỮ TRÊN ẢNH: tất cả chữ hiển thị trên ảnh bằng TIẾNG VIỆT, "
        "đúng chính tả, có dấu đầy đủ."
    )


def _build_final_prompt(prompt: str, refs: List[Path], has_person: bool,
                        has_scene: bool, notable_details=None,
                        theme: str = "", shop: str = "", logo_img: bool = False,
                        language: str = "en", n_products: int = 1,
                        p_type: str = "", variant_index: int = 1) -> str:
    """Ghép prompt cuối: nội dung + giữ nguyên sản phẩm/người + CHÂN THỰC + an toàn."""
    notes = []
    notes.append(_lang_note(language))
    if p_type == "closing":
        notes.append(FLASH_DEAL_NOTE)
    vnote = _variant_note(p_type, variant_index, n_products)
    if vnote:
        notes.append(vnote)
    if theme:
        notes.append(f"Đồng bộ theme thiết kế chung cả bộ: {theme}.")
    if logo_img:
        # có ảnh logo thật → chừa chỗ, KHÔNG để AI tự vẽ logo (dán logo thật sau)
        notes.append(
            "CHỪA GÓC TRÊN-PHẢI trống sạch (~18% chiều rộng) để dán LOGO SHOP thật "
            "vào sau; TUYỆT ĐỐI KHÔNG tự vẽ logo/chữ thương hiệu shop nào."
        )
    elif shop:
        notes.append(f"Thêm logo shop '{shop}' ở góc, nhất quán.")
    n_products = max(1, int(n_products or 1))
    if len(refs) == 1:
        notes.append(
            "Ảnh đính kèm là SẢN PHẨM: giữ NGUYÊN thiết kế, nhãn, chữ, màu sắc, "
            "tỉ lệ y hệt, không đổi bao bì. Hiển thị ĐẦY ĐỦ sản phẩm gồm MỌI bộ "
            "phận (dây điện/cáp, nút bấm, đầu phụ kiện, khe gió...), không cắt "
            "xén, không bỏ sót chi tiết."
        )
    else:
        if n_products == 1:
            parts = [
                "Ảnh 1 là SẢN PHẨM (giữ NGUYÊN thiết kế, nhãn, chữ, màu sắc; hiển "
                "thị ĐẦY ĐỦ mọi bộ phận gồm dây điện, nút, đầu phụ kiện — không bỏ sót)."
            ]
            i = 2
        else:
            # Nhiều ảnh sản phẩm = CÙNG 1 sản phẩm, khác mẫu mã/màu sắc nhưng
            # chức năng y hệt. Cho model hiểu để không ghép nhầm thành nhiều món,
            # NHƯNG được phép dùng các màu/biến thể khác nhau (không khoá 1 màu).
            parts = [
                f"Ảnh 1 đến Ảnh {n_products} là CÙNG MỘT sản phẩm nhưng khác "
                "MÀU SẮC/MẪU MÃ/phiên bản (chức năng, hình dạng, bộ phận GIỐNG "
                "hệt nhau). Đây KHÔNG phải nhiều sản phẩm khác nhau. Giữ NGUYÊN "
                "thiết kế, nhãn, chữ, tỉ lệ và ĐẦY ĐỦ mọi bộ phận (dây điện, nút, "
                "đầu phụ kiện...) đúng như các ảnh mẫu."
            ]
            i = n_products + 1
        if has_person:
            parts.append(
                f"Ảnh {i} là NGƯỜI MẪU: BẮT BUỘC đưa CHÍNH người mẫu này vào ảnh "
                "(ảnh PHẢI có người mẫu), giữ ĐÚNG gương mặt, kiểu tóc và tông da; "
                "người mẫu ĐANG CẦM/DÙNG sản phẩm đúng cách thực tế, tương tác tự "
                "nhiên (tư thế & tay cầm đúng, ánh mắt và biểu cảm phù hợp); bố cục "
                "có CẢ người mẫu VÀ sản phẩm, sản phẩm vẫn rõ nét, nổi bật, KHÔNG bị "
                "che khuất; giữ nguyên thiết kế sản phẩm."
            )
            i += 1
        if has_scene:
            parts.append(
                f"Ảnh {i} là BỐI CẢNH: dùng CHÍNH bối cảnh này làm khung cảnh nền, "
                "đặt sản phẩm/người mẫu hoà hợp tự nhiên vào không gian đó."
            )
        notes.append(" ".join(parts))
        if has_person and not has_scene:
            notes.append(
                "TỰ DỰNG bối cảnh/nền lifestyle phù hợp, sạch và đúng theme cho người "
                "mẫu (vd phòng tắm/bàn trang điểm/không gian studio sáng hợp ngữ cảnh "
                "sản phẩm), có chiều sâu thật; ánh sáng ăn khớp giữa người mẫu và sản "
                "phẩm để ảnh liền mạch, không giống ghép cắt dán."
            )

    if notable_details:
        dl = ", ".join(str(d) for d in notable_details if d)
        if dl:
            notes.append(f"Chú ý tái hiện đúng các chi tiết: {dl}.")

    notes.append(
        "HƯỚNG SẢN PHẨM PHẢI ĐÚNG THỰC TẾ: KHÔNG lật ngược, KHÔNG xoay sai hướng, "
        "KHÔNG cầm ngược. Thiết bị cầm tay: phần tay cầm/handle hướng xuống dưới, "
        "đầu hoạt động (đầu thổi gió / vòi xịt / miệng ra / đầu bàn chải / lưỡi...) "
        "hướng đúng như thiết kế gốc và đúng công năng sử dụng."
    )
    if has_person:
        notes.append(
            "NGƯỜI MẪU DÙNG SẢN PHẨM PHẢI CHÂN THỰC & ĐÚNG CÔNG NĂNG: đầu hoạt động "
            "của sản phẩm PHẢI HƯỚNG VÀO đúng bộ phận/đối tượng đang được tác động — "
            "vd MÁY SẤY thì MIỆNG THỔI GIÓ chĩa THẲNG VÀO tóc để sấy (KHÔNG chĩa ra "
            "xa, KHÔNG hướng ngược, KHÔNG cầm lộn đầu); lược/bàn chải/mỹ phẩm/dụng cụ "
            "thì áp đúng vùng đang dùng. Tay cầm đúng cách cầm thật, khoảng cách và "
            "góc thao tác hợp lý, động tác tự nhiên như đang dùng thật; luồng gió/tia "
            "xịt/hướng tác động phải NHẤT QUÁN với động tác và vị trí của người mẫu. "
            "Tuyệt đối không để sản phẩm lơ lửng sai tư thế hay dùng sai chức năng."
        )
    notes.append(
        "KHUNG ẢNH VUÔNG tỉ lệ 1:1 (1080x1080), bố cục cân đối gọn trong khung vuông."
    )
    notes.append("Chỉ dựa vào các ảnh đính kèm trong tin nhắn NÀY.")
    notes.append(REALISM)
    notes.append(LOGIC)

    body = prompt.strip()
    if _MODEST.lower() not in body.lower():
        body = f"{body} {_MODEST}"
    return f"{body}\n\n{' '.join(notes)}"


async def generate_one(
    session: AioSession,
    prompt_obj: dict,
    product,
    person: Optional[Path] = None,
    scene: Optional[Path] = None,
    dest: Optional[Path] = None,
    timeout_ms: int = 180000,
    retries: int = 2,
    notable_details=None,
    theme: str = "",
    shop: str = "",
    logo: Optional[Path] = None,
    language: str = "en",
    variant_index: int = 1,
) -> dict:
    """Tạo 1 ảnh, tải về dest. Trả result {type,label,prompt,image,status,error}.

    `product` nhận 1 ảnh hoặc DANH SÁCH ảnh (cùng sản phẩm, khác mẫu mã/màu).
    `variant_index`: số thứ tự ảnh trong bộ → xoay vòng chọn biến thể màu."""
    p_type = prompt_obj["type"]
    refs = select_refs(p_type, product, person, scene)
    n_products = len(_product_list(product)) or 1
    has_person = person is not None and p_type in USE_PERSON_TYPES
    has_scene = scene is not None and p_type in USE_SCENE_TYPES
    final_prompt = _build_final_prompt(
        prompt_obj["prompt"], refs, has_person, has_scene, notable_details,
        theme, shop, logo_img=bool(logo), language=language, n_products=n_products,
        p_type=p_type, variant_index=variant_index,
    )

    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            session._stop()
            await session.new_chat()
            await session.upload_images(refs)
            await session.type_prompt(final_prompt)
            if not await session.send():
                last_err = "send failed"   # gửi hụt → thử lại lượt mới, không chờ mòn
                continue
            # wait_for_image tự chờ 'bắt đầu sinh' (nút Dừng) nên chỉ cần nghỉ
            # ngắn cho DOM ổn định; 600→300 tiết kiệm ~0.3s/ảnh (an toàn).
            await session.page.wait_for_timeout(300)
            src = await session.wait_for_image(timeout_ms=timeout_ms)
            if not src:
                last_err = "no image"
                if session.hit_limit():
                    break        # hết lượt → retry cũng vô ích, trả lỗi ngay
                continue
            out = Path(dest)
            await session.download_image(src, out)
            try:
                to_square(out)  # ép về vuông 1080x1080
            except Exception:
                pass
            if logo:
                overlay_logo(out, logo)  # dán logo thật vào góc
            return {
                "type": p_type,
                "label": prompt_obj.get("label", p_type),
                "prompt": prompt_obj["prompt"],
                "image": str(out),
                "status": "success",
                "conversation_url": session.conversation_url(),
                "error": "",
            }
        except StopRequested:
            raise                # user bấm Dừng → không retry, đẩy lên trên
        except Exception as e:
            last_err = repr(e)
    return {
        "type": p_type,
        "label": prompt_obj.get("label", p_type),
        "prompt": prompt_obj["prompt"],
        "image": None,
        "status": "error",
        "conversation_url": "",
        "error": last_err,
    }
