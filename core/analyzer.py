"""Khâu PHÂN TÍCH + SINH PROMPT/SEO qua ChatGPT web — theo chuẩn promt.docx.

Chuẩn TikTok Shop Philippines:
- Bộ 9 ảnh theo cấu trúc: thumbnail → before/after → pain point → công dụng →
  tính năng → cách dùng → chi tiết → đối tượng → chốt sale.
- Chữ trên ảnh TIẾNG ANH, ngắn gọn, mobile-first; thêm LOGO SHOP; ĐỒNG BỘ theme;
  tránh từ vi phạm (100%, cure, guaranteed, best, number 1, permanent...).
- SEO: tên chuẩn SEO tiếng Anh + 3 tiêu đề test CTR + tiêu đề ngắn + keywords + category.

Tối ưu tốc độ: gộp còn 2 message (1 vision đọc ảnh, 1 sinh prompts + seo).
"""
from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Callable, List, Optional

from core.aio_chatgpt import AioSession, StopRequested
from core.jsonutil import parse_json
from config import (
    PROMPT_TYPE_LABELS, DEFAULT_MARKET, BANNED_CLAIMS,
    USE_PERSON_TYPES, USE_SCENE_TYPES,
)

_RETRY_MSG = (
    "Câu trả lời trước chưa đúng định dạng/chưa đủ nội dung. Hãy trả lại DUY NHẤT "
    "một JSON HỢP LỆ và ĐẦY ĐỦ theo yêu cầu ở trên, bắt đầu bằng { và kết thúc "
    "bằng }, KHÔNG kèm giải thích, KHÔNG markdown, KHÔNG dấu phẩy thừa."
)

# Số tab chạy SONG SONG khi sinh prompt (chia nhỏ để rút ngắn thời gian chờ).
PROMPT_SHARDS = 3
# Mỗi shard nên có ít nhất ngần này loại, dưới mức đó thì không chia nữa.
MIN_TYPES_PER_SHARD = 2


async def _ask_json(session: AioSession, prompt: str, timeout_ms: int,
                    retries: int = 2, validate: Optional[Callable] = None):
    """Gửi prompt, parse JSON. Hỏi lại TỐI ĐA `retries` lần. KHÔNG bao giờ raise
    vì parse lỗi → trả {} (caller tự lo dự phòng). Vẫn raise StopRequested.

    `validate(data) -> bool`: chỉ hỏi lại khi nội dung THIẾU thật sự. Trước đây
    không có bước này nên caller phải lặp thêm vòng ngoài → 3 x 4 = 12 lần hỏi,
    mỗi lần vài phút.
    """
    best = {}
    for i in range(max(1, retries)):
        try:
            text = await session.ask_text(prompt if i == 0 else _RETRY_MSG,
                                          timeout_ms=timeout_ms)
            data = parse_json(text)
            if validate is None or validate(data):
                return data
            if data and not best:
                best = data
        except StopRequested:
            raise
        except Exception:
            continue
    return best

# Phong cách/CONCEPT từng loại ảnh — bám cấu trúc listing chuẩn trong promt.docx.
TYPE_STYLE = {
    "thumbnail": "ẢNH ĐẠI DIỆN đẹp nhất: sản phẩm LỚN, nổi bật chính giữa; headline MẠNH + 3-4 lợi ích chính ngắn gọn; nền sạch theo theme, ánh sáng studio. Đây là ảnh quyết định click.",
    "before_after": "Chia đôi khung TRƯỚC/SAU (nhãn BEFORE / AFTER), thể hiện KẾT QUẢ dùng sản phẩm rõ rệt trên cùng đối tượng; sản phẩm xuất hiện; không phóng đại phi thực tế.",
    "pain_point": "Khắc hoạ NỖI ĐAU/vấn đề khách gặp khi CHƯA có sản phẩm (biểu cảm/tình huống thể hiện vấn đề); 1 câu hỏi hoặc câu ngắn về pain point; sản phẩm đặt cạnh như giải pháp.",
    "main_benefit": "Nhấn CÔNG DỤNG CHÍNH bằng 1 hình ảnh trực quan + 1 dòng benefit lớn dễ đọc; sản phẩm nổi bật, bố cục sạch.",
    "features": "Bố cục 3-4 TÍNH NĂNG nổi bật quanh sản phẩm, mỗi tính năng 1 icon + 1 cụm từ ngắn; layout gọn gàng, không rối.",
    "how_to_use": "CÁC BƯỚC sử dụng sản phẩm (vd apply → wait → rinse hoặc thao tác thật), đánh số bước, minh hoạ thao tác ĐÚNG CÁCH; chữ ngắn.",
    "detail_info": "CẬN CẢNH chi tiết/chất liệu/kết cấu/thành phần sản phẩm (macro rõ nét); có thẻ thông số kỹ thuật hoặc thành phần trình bày rõ ràng.",
    "audience": "ĐỐI TƯỢNG phù hợp / TÌNH HUỐNG sử dụng thực tế (ai dùng, dùng ở đâu); người và không gian hợp ngữ cảnh; text nêu nhóm đối tượng.",
    "closing": "Ảnh CHỐT SALE/tạo niềm tin: kết quả 'như ngoài tiệm tại nhà', CTA ngắn (vd 'Order now') + điểm tin cậy; bố cục mạnh, thúc đẩy mua.",
}


def _rules(shop: str, language: str, market: str) -> str:
    lang_txt = "TIẾNG ANH" if language == "en" else "TIẾNG VIỆT"
    shop_line = (
        f"THÊM LOGO SHOP '{shop}' ở vị trí hợp lý (thường góc trên), nhất quán mọi ảnh."
        if shop else
        "TUYỆT ĐỐI KHÔNG thêm logo, tên shop, watermark hay chữ thương hiệu shop nào lên ảnh."
    )
    banned = ", ".join(BANNED_CLAIMS)
    return f"""QUY TẮC BẮT BUỘC cho MỌI prompt — viết CHI TIẾT, giàu hình ảnh, DÀI 70-130 từ:
1. GIỮ NGUYÊN SẢN PHẨM 100%: không đổi bao bì, màu, logo, chữ trên sản phẩm. Hiển thị ĐẦY ĐỦ mọi bộ phận (dây điện/cáp, nút, đầu phụ kiện, khe gió...), ĐÚNG CHIỀU thực tế, không lật ngược.
2. Chữ trên ảnh bằng {lang_txt}, NGẮN GỌN, dễ đọc trên điện thoại, KHÔNG nhồi nhét nhiều chữ. Đúng chính tả.
3. {shop_line}
4. ĐỒNG BỘ MỘT THEME thiết kế (tông màu, kiểu font, phong cách) xuyên suốt cả bộ 9 ảnh.
5. Bố cục SẠCH, chuyên nghiệp, tăng CTR, mobile-first, phù hợp thị trường {market}.
6. TRÁNH từ dễ vi phạm chính sách: {banned}. Không claim quá đà.
7. Ảnh phải TRÔNG NHƯ ẢNH CHỤP THẬT chuyên nghiệp bằng máy DSLR, KHÔNG giống AI/3D/CGI: bề mặt có chất liệu & phản chiếu tự nhiên; nếu có người thì da có kết cấu/lỗ chân lông, KHÔNG làm mịn/nhựa hóa, tóc có sợi bay; ánh sáng vật lý đúng, bóng mềm nhất quán, độ sâu trường ảnh và bokeh quang học thật, màu trung thực, hạt film nhẹ; tránh đối xứng máy móc, tránh over-sharpen/HDR.
8. PHẢI ĐÚNG LOGIC & GIẢI PHẪU, KHÔNG lỗi AI: sản phẩm nguyên vẹn KHÔNG méo/biến dạng/nhân đôi/thiếu bộ phận; tay ĐÚNG 5 ngón cầm nắm tự nhiên đúng cách dùng (không thừa/dính ngón); vật có ĐIỂM TỰA thật không lơ lửng, bóng+phản chiếu khớp nguồn sáng; mọi CHỮ trong ảnh CÓ NGHĨA đúng chính tả, không chữ méo/nhòe/vô nghĩa; số lượng vật thể & phối cảnh hợp lý.
9. KHUNG ẢNH VUÔNG tỉ lệ 1:1 (1080x1080), bố cục cân đối trong khung vuông.
10. KHÔNG dùng ngoặc [] {{}} hay placeholder — điền thẳng giá trị thật.
11. Mỗi ảnh bám ĐÚNG VAI TRÒ concept của nó; nội dung chữ mỗi ảnh KHÁC nhau; đa dạng bối cảnh."""


async def extract_attributes(
    session: AioSession,
    product_path: Path,
    product_info: str = "",
    timeout_ms: int = 120000,
    product_extra: Optional[List[Path]] = None,
) -> dict:
    """[Message 1 — VISION] Upload ảnh sản phẩm, trích thuộc tính JSON.

    `product_extra`: các ảnh CÙNG sản phẩm khác mẫu mã/màu — upload kèm để model
    hiểu đúng phạm vi sản phẩm (không coi là nhiều món khác nhau)."""
    imgs = [Path(product_path)] + [Path(p) for p in (product_extra or [])]
    await session.new_chat()
    await session.upload_images(imgs)
    extra = f"\n\nThông tin thêm user cung cấp: {product_info}" if product_info else ""
    variants = (
        f"\n\nLƯU Ý: có {len(imgs)} ảnh đính kèm — đây là CÙNG MỘT sản phẩm nhưng "
        "khác MẪU MÃ/MÀU SẮC/phiên bản (chức năng giống hệt). Hãy trích thuộc tính "
        "CHUNG cho sản phẩm; nếu các biến thể khác nhau ở màu/kiểu thì liệt kê vào "
        "'dominant_colors'/'notable_details'. KHÔNG coi là nhiều sản phẩm khác nhau."
        if len(imgs) > 1 else ""
    )
    prompt = (
        "Bạn là chuyên gia phân tích sản phẩm cho ảnh quảng cáo. "
        "Nhìn ẢNH sản phẩm này và trích thuộc tính THẬT KỸ. "
        "Liệt kê ĐẦY ĐỦ mọi bộ phận nhìn thấy (thân, nắp, nút bấm, DÂY ĐIỆN/CÁP, "
        "đầu phụ kiện, khe gió, màn hình...) vào 'parts', và ghi chi tiết đặc trưng "
        "dễ bị bỏ sót vào 'notable_details' (vd 'có dây điện dài ở đuôi', '2 nút đỏ'). "
        "CHỈ trả về JSON hợp lệ, KHÔNG markdown, KHÔNG giải thích. Schema:\n"
        "{"
        '"brand":"","product_type":"","product_function":"",'
        '"usage_category":"","usage_action_vi":"","usage_action_en":"",'
        '"application_area_vi":"","application_area_en":"",'
        '"form":"jar|tube|bottle_pump|bottle_spray|stick|dropper|sachet|box|other",'
        '"is_cosmetic":true,"category":"","short_descriptor":"",'
        '"dominant_colors":[],"label_lines_top_to_bottom":[],"exact_label_string":"",'
        '"parts":[{"name":"","color":"","finish":"","shape":""}],'
        '"notable_details":[],"key_benefits":[],'
        '"theme":"<tông màu + kiểu font + phong cách thiết kế dùng chung cho cả '
        'bộ ảnh listing, 1 câu tiếng Việt>"'
        "}"
        + variants
        + extra
    )
    # Lấy luôn 'theme' ở bước nhìn ảnh → các tab sinh prompt song song sau đó
    # đều bám CÙNG một theme mà không cần thêm lượt hỏi nào.
    attrs = await _ask_json(
        session, prompt, timeout_ms,
        validate=lambda d: isinstance(d, dict) and bool(d.get("product_type")),
    )
    if not isinstance(attrs, dict):
        attrs = {}
    if product_info:
        attrs["user_product_info"] = product_info
    return attrs


async def generate_prompts(
    session: AioSession,
    attributes: dict,
    types: List[str],
    image_lang: str = "en",
    shop: str = "",
    market: str = DEFAULT_MARKET,
    has_person: bool = False,
    has_scene: bool = False,
    timeout_ms: int = 200000,
    theme: str = "",
    n_products: int = 1,
) -> dict:
    """CHỈ sinh prompt (KHÔNG SEO). Nội dung prompt bằng TIẾNG VIỆT để user dễ sửa;
    chữ HIỂN THỊ TRÊN ẢNH theo image_lang (en/vi).

    `theme`: nếu đã có sẵn (từ bước đọc ảnh) thì BẮT theo đúng theme đó — nhờ vậy
    nhiều tab sinh prompt song song vẫn cho ra một bộ ảnh đồng bộ.
    `n_products`: số ảnh sản phẩm (biến thể màu/mẫu) → nhắc prompt thể hiện đa dạng.
    """
    style_lines = []
    for t in types:
        label = PROMPT_TYPE_LABELS.get(t, t)
        style_lines.append(f"- {t} ({label}): {TYPE_STYLE.get(t, '')}")
    styles_block = "\n".join(style_lines)
    img_txt = "TIẾNG ANH" if image_lang == "en" else "TIẾNG VIỆT"

    refs_note = []
    if n_products > 1:
        refs_note.append(
            f"- CÓ {n_products} ẢNH SẢN PHẨM = CÙNG một sản phẩm, khác MÀU/MẪU MÃ "
            "(chức năng như nhau). Hãy để CÁC ẢNH KHÁC NHAU thể hiện các MÀU/BIẾN "
            "THỂ KHÁC NHAU để khoe đủ dải sản phẩm — KHÔNG bắt cả bộ chung 1 màu, "
            "KHÔNG mặc định chỉ dùng ảnh đầu tiên. Ảnh bìa (thumbnail), tính năng "
            "(features), đối tượng (audience) NÊN cho thấy NHIỀU màu cùng lúc; các "
            "ảnh còn lại mỗi ảnh chọn 1 màu/biến thể khác nhau. Nêu rõ màu/biến thể "
            "trong prompt."
        )
    if has_person:
        person_labels = ", ".join(
            f"{t} ({PROMPT_TYPE_LABELS.get(t, t)})"
            for t in types if t in USE_PERSON_TYPES
        ) or "các loại ảnh có người"
        refs_note.append(
            "- CÓ ẢNH NGƯỜI MẪU đính kèm: BẮT BUỘC đưa người mẫu VÀO ẢNH ở các loại "
            f"có người ({person_labels}) — các ảnh này PHẢI có mặt người mẫu, không "
            "được chỉ có sản phẩm trơ. Prompt phải mô tả RÕ người mẫu đang cầm/dùng "
            "sản phẩm: tư thế tay/thân, biểu cảm gương mặt, ánh mắt, góc nghiêng, cách "
            "cầm/dùng ĐÚNG THỰC TẾ & ĐÚNG CHIỀU (đầu hoạt động của sản phẩm hướng vào "
            "đúng bộ phận đang dùng — vd máy sấy chĩa gió thẳng vào tóc, không cầm "
            "ngược/chĩa ra xa); giữ ĐÚNG gương mặt, kiểu tóc và tông da của người "
            "mẫu; sản phẩm vẫn rõ nét, nổi bật cạnh người mẫu, không bị che khuất. "
            "Nếu KHÔNG có ảnh bối cảnh riêng thì tả luôn một bối cảnh/nền lifestyle "
            "phù hợp, sạch và đúng theme cho người mẫu."
        )
    if has_scene:
        scene_labels = ", ".join(
            f"{t} ({PROMPT_TYPE_LABELS.get(t, t)})"
            for t in types if t in USE_SCENE_TYPES
        ) or "các loại ảnh có bối cảnh"
        refs_note.append(
            "- CÓ ẢNH BỐI CẢNH đính kèm: dùng chính bối cảnh đó làm nền cho các loại "
            f"liên quan ({scene_labels}); tả CHI TIẾT cách đặt sản phẩm/người mẫu "
            "trong không gian (vị trí, mặt phẳng tựa, chiều sâu, ánh sáng của bối cảnh, "
            "đạo cụ xung quanh) để ảnh hoà hợp tự nhiên với cảnh thật."
        )
    refs_block = ("\nKHI CÓ ẢNH THAM CHIẾU (viết prompt DÀI & CHI TIẾT hơn cho các loại liên quan):\n"
                  + "\n".join(refs_note)) if refs_note else ""

    theme_line = (
        f"THEME BẮT BUỘC (dùng CHÍNH XÁC theme này cho mọi prompt, không tự đổi): "
        f"{theme}"
        if theme else
        "THEME: tự chọn 1 theme (tông màu/font/phong cách) rồi áp cho mọi prompt."
    )
    parts = [
        "Đóng vai chuyên gia thiết kế ảnh listing cho sàn TMĐT. Dựa vào thuộc "
        "tính sản phẩm (JSON), viết prompt tạo ảnh cho từng loại.",
        f"THUỘC TÍNH: {attributes}",
        f"SHOP: {shop or '(không có)'}",
        theme_line,
        "",
        f"Tạo prompt cho ĐÚNG các loại (giữ thứ tự): {types}",
        "Vai trò/concept từng loại:",
        styles_block,
        refs_block,
        "",
        _rules(shop, image_lang, market),
        "",
        "QUAN TRỌNG VỀ NGÔN NGỮ:",
        "- Viết TOÀN BỘ nội dung prompt bằng TIẾNG VIỆT để người dùng dễ đọc & sửa.",
        f"- Nội dung CHỮ HIỂN THỊ TRÊN ẢNH (typography overlay) phải bằng {img_txt}, "
        f"ghi rõ trong dấu ngoặc kép. Chỉ phần chữ overlay dùng {img_txt}; phần mô tả "
        "cảnh/bố cục/ánh sáng viết bằng tiếng Việt.",
        "",
        "CHỈ trả JSON hợp lệ (KHÔNG markdown, KHÔNG giải thích):",
        "{",
        '  "theme": "<mô tả ngắn theme màu/font/phong cách dùng chung cả bộ, tiếng Việt>",',
        '  "prompts": [ {"type":"<loại>","label":"<tên VN>","prompt":"<prompt tiếng Việt, chữ overlay theo ngôn ngữ ảnh>","content":""} ]',
        "}",
        f"Yêu cầu: PHẢI CÓ ĐỦ {len(types)} loại; MỖI PROMPT DÀI 70-130 từ tiếng "
        "Việt, chi tiết môi trường/chất liệu/ánh sáng; nhấn ảnh CHỤP THẬT không "
        "giống AI + ĐÚNG LOGIC (không méo, tay đúng 5 ngón, chữ có nghĩa); giữ đủ "
        "bộ phận sản phẩm đúng chiều. Không placeholder. Bỏ trường 'content' "
        "(để chuỗi rỗng) — đừng viết thêm gì ngoài JSON.",
    ]

    def _ok(d):
        return (isinstance(d, dict)
                and len(_clean_prompts(d.get("prompts"), types)) >= len(types))

    return await _ask_json(session, "\n".join(parts), timeout_ms, validate=_ok)


async def generate_seo(
    session: AioSession,
    attributes: dict,
    shop: str = "",
    market: str = DEFAULT_MARKET,
    language: str = "vi",
    timeout_ms: int = 180000,
) -> dict:
    """Sinh bộ listing SEO chuẩn sàn TMĐT (Từ khóa + Title + Mô tả + Bảng chi tiết).

    - language='en' → toàn bộ nội dung TIẾNG ANH; 'vi' → TIẾNG VIỆT.
    - KHÔNG dùng emoji/icon trong bài viết (chữ sạch để dán thẳng lên sàn)."""
    en = (language or "vi").lower().startswith("en")
    out_lang = "TIẾNG ANH" if en else "TIẾNG VIỆT"
    if en:
        heading = "WHAT MAKES THIS PRODUCT STAND OUT"
        tips_line = "TIPS:"
        item_hints = ("Beautiful design; Main performance/benefit; Convenient & easy "
                      "to use; Outstanding benefit; Genuine & quality assured")
        fields_hint = ("Category, Formula, Product Form, Active Ingredients, "
                       "Special Type, Packaging, Volume, Weight, Origin, Expiry, "
                       "Waterproof, Storage")
        banned_line = "không 'best', 'number 1', 'cure', 'guaranteed', '100%'..."
    else:
        heading = "ĐIỂM ĐẶC BIỆT LÀM NÊN THƯƠNG HIỆU"
        tips_line = "MẸO NHỎ:"
        item_hints = ("Thiết kế đẹp mắt; Hiệu suất/công dụng chính; Tiện lợi & dễ sử "
                      "dụng; Lợi ích nổi bật; Hàng chính hãng/chất lượng đảm bảo")
        fields_hint = ("Danh Mục, Công Thức, Dạng sản phẩm, Thành Phần Hoạt Tính, "
                       "Loại đặc biệt, Kiểu đóng gói, Thể tích, Trọng lượng, Xuất xứ, "
                       "Hạn sử dụng, Chống nước, Điều kiện bảo quản")
        banned_line = "không '100%', 'chữa khỏi', 'tốt nhất'..."

    parts = [
        "Đóng vai chuyên gia SEO sàn TMĐT (Shopee / TikTok Shop) 20 năm kinh nghiệm. "
        "Dựa vào thuộc tính sản phẩm (JSON), viết bộ nội dung listing chuẩn SEO theo "
        "ĐÚNG cấu trúc mẫu dưới đây.",
        f"THUỘC TÍNH: {attributes}",
        f"THỊ TRƯỜNG: {market}",
        "",
        f"NGÔN NGỮ: viết TOÀN BỘ nội dung (keywords, title, description, các giá trị "
        f"trong attributes) bằng {out_lang}.",
        "TUYỆT ĐỐI KHÔNG dùng emoji/icon/ký tự trang trí nào trong toàn bộ nội dung "
        "(không ✨, không 1️⃣, không 🧴, không mọi biểu tượng). Chỉ dùng chữ và số thường.",
        "",
        "QUY TẮC THÔNG TIN (RẤT QUAN TRỌNG — KHÔNG ĐƯỢC BỊA):",
        "- CHỈ dùng thông tin CÓ THẬT lấy từ THUỘC TÍNH sản phẩm ở trên và phần thông "
        "tin người dùng nhập thêm. Nếu trong thuộc tính có 'user_product_info' thì đó "
        "chính là mô tả người dùng cung cấp — ưu tiên bám theo nó.",
        "- TUYỆT ĐỐI KHÔNG bịa, KHÔNG suy đoán, KHÔNG thêm thành phần/công dụng/thông "
        "số/con số/xuất xứ không có căn cứ. Thà thiếu còn hơn bịa.",
        "- Trường/thông tin nào KHÔNG có dữ liệu thật thì BỎ HẲN, không nhắc tới. "
        "TUYỆT ĐỐI KHÔNG ghi 'Đang cập nhật', 'Updating', 'N/A', dấu '-' hay để trống.",
        "",
        "YÊU CẦU CHI TIẾT:",
        f"- keywords: 18-20 từ khóa {out_lang} khách hay tìm (mỗi phần tử 1 cụm từ "
        "khóa), bám đúng loại sản phẩm thật.",
        "- title: TÊN SẢN PHẨM viết IN HOA, nhồi lợi ích chính + từ khóa quan trọng "
        "CÓ THẬT, hấp dẫn tự nhiên như tiêu đề bán chạy thật (có thể dùng dấu phẩy/gạch nối).",
        "- description: bài MÔ TẢ theo ĐÚNG format sau (KHÔNG icon, giữ xuống dòng), "
        "chỉ nêu đặc điểm/công dụng CÓ CĂN CỨ từ thông tin thật:",
        f"    • Dòng đầu là 1 tiêu đề IN HOA: '{heading}'.",
        "    • Rồi 5 mục đánh số '1.' '2.' '3.' '4.' '5.'. Mỗi mục: tiêu đề in đậm rồi "
        f"xuống dòng 1 đoạn 2-3 câu lồng từ khóa TỰ NHIÊN (gợi ý các mục: {item_hints} "
        "— chỉnh theo đúng sản phẩm, không bịa đặc điểm không có).",
        f"    • Sau đó 1 dòng '{tips_line}' rồi 3 gạch đầu dòng (dùng dấu '-') mẹo dùng "
        "chung hợp lý cho loại sản phẩm này (không bịa thông số/hiệu quả).",
        "    • Kết bằng 1 dòng khoảng 20 hashtag (#tukhoa, viết liền không dấu cách trong 1 hashtag).",
        "- attributes: object bảng CHI TIẾT SẢN PHẨM, CHỈ gồm các trường có THÔNG TIN "
        "THẬT (biết chắc từ thuộc tính/nhãn sản phẩm hoặc thông tin user cung cấp). "
        "Trường không rõ thì BỎ HẲN khỏi object — KHÔNG thêm key rỗng, KHÔNG "
        f"'Đang cập nhật'. Các trường có thể dùng NẾU biết chắc: {fields_hint}.",
        f"- Tránh claim quá đà vô căn cứ ({banned_line}).",
        "",
        "CHỈ trả JSON hợp lệ (KHÔNG markdown, KHÔNG giải thích, KHÔNG emoji):",
        "{",
        '  "seo": {'
        '"keywords":["<từ khóa 1>","<từ khóa 2>", "... 18-20 cái"],'
        '"title":"<TÊN SẢN PHẨM IN HOA, đầy đủ lợi ích>",'
        '"description":"<toàn bộ bài mô tả theo format trên, KHÔNG icon, gồm \\n xuống dòng>",'
        '"attributes":{"<chỉ trường có thật>":"<giá trị thật>"}'
        "}",
        "}",
    ]
    def _ok(d):
        s = d.get("seo", d) if isinstance(d, dict) else {}
        return isinstance(s, dict) and bool(s.get("title") and s.get("description"))

    data = await _ask_json(session, "\n".join(parts), timeout_ms, validate=_ok)
    seo = data.get("seo", data) if isinstance(data, dict) else {}
    if isinstance(seo, dict) and "attributes" in seo:
        from core.store import clean_seo_attrs
        seo["attributes"] = clean_seo_attrs(seo.get("attributes"))
    return seo if isinstance(seo, dict) else {}


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    for ch in " /-":
        s = s.replace(ch, "_")
    return s


def _clean_prompts(raw, types: List[str]) -> list:
    """Chuẩn hóa + lọc prompts theo types (khớp cả khi model viết hoa/khác dấu)."""
    norm_map = {_norm(t): t for t in types}
    out = []
    seen = set()
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        t = norm_map.get(_norm(p.get("type", "")))
        if not t or t in seen or not p.get("prompt"):
            continue
        seen.add(t)
        out.append({
            "type": t,
            "label": p.get("label", PROMPT_TYPE_LABELS.get(t, t)),
            "prompt": p.get("prompt", ""),
            "content": p.get("content", ""),
        })
    return out


def _fallback_prompts(types, attributes, image_lang):
    """Prompt mẫu (tạo LOCAL) khi ChatGPT trả JSON hỏng → user vẫn có ô để sửa."""
    a = attributes or {}
    desc = a.get("short_descriptor") or a.get("product_type") or "sản phẩm"
    overlay = ("Chữ overlay bằng tiếng Anh." if image_lang == "en"
               else "Chữ overlay bằng tiếng Việt.")
    out = []
    for t in types:
        prompt = (
            f"Ảnh listing loại '{PROMPT_TYPE_LABELS.get(t, t)}' cho {desc}. "
            f"{TYPE_STYLE.get(t, '')} Giữ NGUYÊN sản phẩm 100% (đủ mọi bộ phận, "
            "đúng chiều), ảnh VUÔNG 1080x1080, chụp thật không giống AI, đúng logic "
            "(không méo, tay đúng 5 ngón, chữ có nghĩa). " + overlay
        )
        out.append({"type": t, "label": PROMPT_TYPE_LABELS.get(t, t),
                    "prompt": prompt, "content": ""})
    return out


def _split_types(types: List[str], shards: int) -> List[List[str]]:
    """Chia đều danh sách loại ảnh cho các tab (giữ nguyên thứ tự)."""
    if shards <= 1 or len(types) < MIN_TYPES_PER_SHARD * 2:
        return [list(types)]
    shards = min(shards, len(types) // MIN_TYPES_PER_SHARD)
    size = math.ceil(len(types) / shards)
    return [types[i:i + size] for i in range(0, len(types), size)]


async def make_prompts(
    session: AioSession,
    product_path: Path,
    types: List[str],
    image_lang: str = "en",
    product_info: str = "",
    shop: str = "",
    market: str = DEFAULT_MARKET,
    attributes: Optional[dict] = None,
    has_person: bool = False,
    has_scene: bool = False,
    extra_sessions: Optional[List[AioSession]] = None,
    product_extra: Optional[List[Path]] = None,
) -> dict:
    """Trích thuộc tính + sinh PROMPT (tiếng Việt). Không SEO. KHÔNG bao giờ rỗng.

    `extra_sessions`: các tab phụ. Có tab phụ thì 9 loại ảnh được CHIA ĐỀU cho
    các tab và sinh SONG SONG → thời gian chờ giảm gần bằng 1/số tab (câu trả
    lời dài ~1000 từ là nút cổ chai lớn nhất của bước này).
    `product_extra`: ảnh sản phẩm phụ (khác mẫu mã) — upload kèm ở mọi tab.
    """
    prod_imgs = [Path(product_path)] + [Path(p) for p in (product_extra or [])]
    attrs = attributes or await extract_attributes(
        session, product_path, product_info, product_extra=product_extra)
    theme = ""
    if isinstance(attrs, dict):
        theme = str(attrs.pop("theme", "") or "")

    sessions = [session] + [s for s in (extra_sessions or []) if s is not None]
    shards = _split_types(list(types), min(PROMPT_SHARDS, len(sessions)))
    sessions = sessions[:len(shards)]

    async def _shard(sess: AioSession, sub: List[str], first: bool) -> list:
        if not first:
            # tab phụ: mở chat mới + đưa ảnh sản phẩm vào cho model "nhìn" thấy
            await sess.new_chat()
            try:
                await sess.upload_images(prod_imgs)
            except Exception:
                pass
        data = await generate_prompts(sess, attrs, sub, image_lang, shop, market,
                                      has_person, has_scene, theme=theme,
                                      n_products=len(prod_imgs))
        return _clean_prompts((data or {}).get("prompts"), sub)

    if len(shards) == 1:
        got = [await _shard(sessions[0], shards[0], True)]
    else:
        got = await asyncio.gather(
            *[_shard(s, sub, i == 0) for i, (s, sub) in enumerate(zip(sessions, shards))],
            return_exceptions=True,
        )

    by_type = {}
    for res in got:
        if isinstance(res, BaseException):
            if isinstance(res, StopRequested):
                raise res
            continue
        for p in res:
            by_type.setdefault(p["type"], p)

    # loại nào vẫn thiếu → điền prompt mẫu để user tự sửa (không văng lỗi)
    missing = [t for t in types if t not in by_type]
    for p in _fallback_prompts(missing, attrs, image_lang):
        by_type[p["type"]] = p

    clean = [by_type[t] for t in types if t in by_type]
    return {"attributes": attrs, "theme": theme, "prompts": clean}


async def make_seo(
    session: AioSession,
    product_path: Path,
    product_info: str = "",
    shop: str = "",
    market: str = DEFAULT_MARKET,
    language: str = "vi",
    attributes: Optional[dict] = None,
) -> dict:
    """Trích thuộc tính (nếu chưa có) + sinh bộ SEO theo ngôn ngữ đã chọn."""
    attrs = attributes or await extract_attributes(session, product_path, product_info)
    seo = await generate_seo(session, attrs, shop, market, language)
    return {"attributes": attrs, "seo": seo}


async def analyze(
    session: AioSession,
    product_path: Path,
    types: List[str],
    language: str = "en",
    product_info: str = "",
    shop: str = "",
    market: str = DEFAULT_MARKET,
    want_seo: bool = True,
    product_extra: Optional[List[Path]] = None,
) -> dict:
    """CLI: attributes + prompts (+ seo nếu want_seo). Dùng chung extract 1 lần."""
    attrs = await extract_attributes(session, product_path, product_info,
                                     product_extra=product_extra)
    p = await make_prompts(session, product_path, types, language, product_info,
                           shop, market, attributes=attrs,
                           product_extra=product_extra)
    seo = {}
    if want_seo:
        try:
            seo = await generate_seo(session, attrs, shop, market, language)
        except Exception:
            seo = {}
    return {
        "attributes": attrs,
        "theme": p.get("theme", ""),
        "prompts": p.get("prompts", []),
        "seo": seo,
    }
