"""Pipeline listing đầy đủ, TẠO ẢNH SONG SONG nhiều tab.

Luồng (giống listing-image-gpt-logic.md, khác: web thay API + song song):
  analyze (attributes + prompts + copy + shopee)  → 2 message text
  → lọc prompt theo loại & cắt còn quantity
  → tạo ảnh SONG SONG qua pool tab (asyncio)      → nút cổ chai, song song hoá
  → (tùy chọn) QC mỗi ảnh
  → lưu prompts.txt / listing_text.txt / results.json → zip
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, List, Optional

from core.aio_browser import AioBrowser
from core.aio_chatgpt import AioSession, StopRequested
from core.analyzer import (
    analyze, make_prompts, make_seo, generate_seo, PROMPT_SHARDS,
)
from core.generator import generate_one, to_square
from core.qc import qc_image
from core import store
from config import (
    OUTPUT_DIR, DEFAULT_TYPES, DEFAULT_CONCURRENCY, DEFAULT_QC,
    DEFAULT_LANGUAGE, DEFAULT_MARKET, PROMPT_TYPE_KEYS,
)

ProgressCB = Optional[Callable[[str, dict], None]]


def _emit(cb: ProgressCB, event: str, data: dict) -> None:
    if cb:
        try:
            cb(event, data)
        except Exception:
            pass


def _filter_prompts(prompts: List[dict], types: List[str], quantity: int) -> List[dict]:
    """Lọc theo loại đã chọn (giữ thứ tự PROMPT_TYPE_KEYS) rồi cắt còn quantity."""
    by_type = {p["type"]: p for p in prompts if p.get("type") in types}
    ordered = [by_type[t] for t in PROMPT_TYPE_KEYS if t in by_type]
    return ordered[:quantity]


async def run_pipeline(
    product: Path,
    person: Optional[Path] = None,
    scene: Optional[Path] = None,
    types: Optional[List[str]] = None,
    quantity: int = 9,
    language: str = DEFAULT_LANGUAGE,
    product_info: str = "",
    shop: str = "",
    market: str = DEFAULT_MARKET,
    concurrency: int = DEFAULT_CONCURRENCY,
    qc: bool = DEFAULT_QC,
    want_seo: bool = True,
    output_base: Path = OUTPUT_DIR,
    headless: bool = False,
    hidden: bool = False,
    profile_dir: Optional[Path] = None,
    product_extra: Optional[List[Path]] = None,
    progress: ProgressCB = None,
) -> dict:
    """Chạy trọn pipeline (analyze + tạo ảnh), trả về dict tổng hợp + zip."""
    types = types or list(DEFAULT_TYPES)
    types = [t for t in types if t in PROMPT_TYPE_KEYS][:quantity]
    products = [product] + [p for p in (product_extra or [])]

    br = AioBrowser(headless=headless, hidden=hidden,
                    **({"profile_dir": profile_dir} if profile_dir else {}))
    await br.start()
    try:
        page0 = await br.first_page()
        await br.open_chatgpt(page0)
        if not await br.is_logged_in(page0, timeout_ms=20000):
            raise RuntimeError("Chưa đăng nhập ChatGPT — chạy: python cli.py login")
        s0 = AioSession(page0)

        _emit(progress, "analyze_start", {})
        analysis = await analyze(
            s0, product, types, language, product_info, shop, market, want_seo,
            product_extra=product_extra,
        )
        prompts = _filter_prompts(analysis["prompts"], types, quantity)
        theme = analysis.get("theme", "")
        _emit(progress, "analyze_done", {"n_prompts": len(prompts)})
        if not prompts:
            raise RuntimeError("Không sinh được prompt nào.")

        return await _finish_generate(
            br, s0, prompts, products, person, scene,
            analysis.get("attributes", {}), theme, shop,
            analysis.get("seo", {}), concurrency, qc, output_base, progress,
            language=language,
        )
    finally:
        await br.close()


async def _finish_generate(br, first_session, prompts, product, person, scene,
                           attributes, theme, shop, seo, concurrency, qc,
                           output_base, progress, logo=None, language="vi"):
    """Tạo ảnh SONG SONG + lưu (dùng chung cho run_pipeline & generate_from_prompts)."""
    sid, sdir = store.new_session_dir(output_base)
    store.write_prompts(sdir, prompts)

    n = len(prompts)
    conc = max(1, min(concurrency, n))
    pool: asyncio.Queue = asyncio.Queue()
    pool.put_nowait(first_session)
    for _ in range(conc - 1):
        pool.put_nowait(AioSession(await br.new_page()))

    done_count = 0
    lock = asyncio.Lock()

    async def worker(idx: int, prompt_obj: dict) -> dict:
        nonlocal done_count
        sess = await pool.get()
        try:
            tag = f"{idx:02d}_{prompt_obj['type']}"
            dest = sdir / f"{tag}.png"
            res = await generate_one(
                sess, prompt_obj, product, person, scene, dest=dest,
                notable_details=(attributes or {}).get("notable_details"),
                theme=theme, shop=shop, logo=logo, language=language,
            )
            if qc and res["status"] == "success":
                res["qc"] = await qc_image(sess, res["image"], attributes or {})
        finally:
            pool.put_nowait(sess)
        async with lock:
            done_count += 1
            _emit(progress, "image_done", {
                "idx": idx, "done": done_count, "total": n,
                "type": prompt_obj["type"], "status": res["status"],
                "image": res.get("image"),
            })
        return res

    _emit(progress, "generate_start", {"total": n, "concurrency": conc})
    results = await asyncio.gather(*[worker(i + 1, p) for i, p in enumerate(prompts)])

    store.write_seo(sdir, seo or {}, theme, shop, language)
    out = {
        "session_id": sid, "dir": str(sdir), "attributes": attributes or {},
        "theme": theme, "prompts": prompts, "seo": seo or {}, "results": results,
        "ok_count": sum(1 for r in results if r["status"] == "success"), "total": n,
    }
    store.write_results(sdir, out)
    out["zip"] = str(store.zip_session(sdir, sid))
    _emit(progress, "done", {"ok": out["ok_count"], "total": n, "zip": out["zip"]})
    return out


async def make_prompts_pipeline(product: Path, types=None,
                                language: str = DEFAULT_LANGUAGE,
                                product_info: str = "", shop: str = "",
                                market: str = DEFAULT_MARKET, quantity: int = 9,
                                hidden: bool = False,
                                profile_dir: Optional[Path] = None,
                                cancel=None, has_person: bool = False,
                                has_scene: bool = False,
                                product_extra: Optional[List[Path]] = None,
                                progress: ProgressCB = None) -> dict:
    """Nút '① Tạo prompt' — CHỉ sinh prompt (tiếng Việt), KHÔNG SEO."""
    types = types or list(DEFAULT_TYPES)
    types = [t for t in types if t in PROMPT_TYPE_KEYS][:quantity]
    br = AioBrowser(hidden=hidden,
                    **({"profile_dir": profile_dir} if profile_dir else {}))
    await br.start()
    try:
        page0 = await br.first_page()
        await br.open_chatgpt(page0)
        if not await br.is_logged_in(page0, timeout_ms=20000):
            raise RuntimeError("Chưa đăng nhập ChatGPT.")
        s0 = AioSession(page0)
        s0.cancel = cancel
        # Mở sẵn vài tab phụ để CHIA NHỎ việc sinh prompt chạy song song.
        extra = []
        n_extra = min(PROMPT_SHARDS, max(1, len(types) // 2)) - 1
        for _ in range(max(0, n_extra)):
            try:
                s = AioSession(await br.new_page())
                s.cancel = cancel
                extra.append(s)
            except Exception:
                break
        _emit(progress, "analyze_start", {})
        res = await make_prompts(s0, product, types, language, product_info,
                                 shop, market, has_person=has_person,
                                 has_scene=has_scene, extra_sessions=extra,
                                 product_extra=product_extra)
        res["prompts"] = _filter_prompts(res["prompts"], types, quantity)
        _emit(progress, "analyze_done", {"n_prompts": len(res["prompts"])})
        return res
    finally:
        await br.close()


async def make_seo_pipeline(product: Path, product_info: str = "", shop: str = "",
                            market: str = DEFAULT_MARKET, language: str = "vi",
                            hidden: bool = False,
                            profile_dir: Optional[Path] = None, cancel=None,
                            progress: ProgressCB = None) -> dict:
    """Nút 'Tạo bài viết & tiêu đề SEO' — CHỈ sinh SEO theo ngôn ngữ đã chọn."""
    br = AioBrowser(hidden=hidden,
                    **({"profile_dir": profile_dir} if profile_dir else {}))
    await br.start()
    try:
        page0 = await br.first_page()
        await br.open_chatgpt(page0)
        if not await br.is_logged_in(page0, timeout_ms=20000):
            raise RuntimeError("Chưa đăng nhập ChatGPT.")
        s0 = AioSession(page0)
        s0.cancel = cancel
        _emit(progress, "seo_start", {})
        res = await make_seo(s0, product, product_info, shop, market, language)
        _emit(progress, "seo_done", {})
        return res
    finally:
        await br.close()


# --- Nhận diện "hết lượt Free" -------------------------------------------- #
# Cụm từ ĐẶC TRƯNG. Bản cũ dùng các từ quá chung ("limit", "maximum",
# "image generation", "come back") nên chữ trong chính câu trả lời của ChatGPT
# cũng khớp → tưởng hết lượt → đổi tài khoản oan, mỗi lần mất ~30s khởi động.
_LIMIT_HINTS = [
    "you've hit the limit", "you've reached", "reached your limit",
    "hit your limit", "usage limit", "rate limit", "limit reached",
    "try again later", "try again in", "come back later",
    "upgrade to chatgpt", "image generation limit",
    "hết lượt", "đã đạt giới hạn", "giới hạn sử dụng", "hạn mức",
    "vui lòng thử lại sau", "quá nhiều yêu cầu",
]
# Số ảnh LỖI LIÊN TIẾP để tự coi là hết lượt/hỏng (dù không nhận ra câu báo).
_FAIL_STREAK = 3


async def _session_hit_limit(sess) -> bool:
    """Hết lượt? Ưu tiên mã HTTP 403/429 (chắc chắn), sau đó mới dò chữ."""
    try:
        if sess.hit_limit():
            return True
    except Exception:
        pass
    try:
        txt = (await sess.page.inner_text("main")).lower()
        return any(h in txt for h in _LIMIT_HINTS)
    except Exception:
        return False


async def _batch_account(br, page0, items, product, person, scene, attributes,
                         theme, shop, concurrency, qc, sdir, total, base_done,
                         progress, cancel=None, logo=None, language="vi",
                         profile_name=""):
    """Chạy các job bằng 1 tài khoản; dừng khi HẾT LƯỢT hoặc user HỦY.
    Trả (done, remaining, limit). Raise StopRequested nếu user hủy."""
    conc = max(1, min(concurrency, len(items)))
    pool: asyncio.Queue = asyncio.Queue()
    sess0 = AioSession(page0)
    sess0.cancel = cancel
    pool.put_nowait(sess0)
    for _ in range(conc - 1):
        s = AioSession(await br.new_page())
        s.cancel = cancel
        pool.put_nowait(s)
    q: asyncio.Queue = asyncio.Queue()
    for it in items:
        q.put_nowait(it)
    done = {}
    limit_event = asyncio.Event()
    lock = asyncio.Lock()
    consec = {"n": 0}
    stopped = {"v": False}

    def _emit_img(idx, prompt_obj, res):
        _emit(progress, "image_done", {
            "idx": idx, "done": base_done + len(done), "total": total,
            "type": prompt_obj["type"], "status": res["status"],
            "image": res.get("image"),
        })

    async def worker():
        while not limit_event.is_set():
            if cancel is not None and cancel.is_set():
                stopped["v"] = True
                limit_event.set()
                return
            try:
                idx, prompt_obj = q.get_nowait()
            except asyncio.QueueEmpty:
                break
            sess = await pool.get()
            try:
                tag = f"{idx:02d}_{prompt_obj['type']}"
                dest = sdir / f"{tag}.png"
                res = await generate_one(
                    sess, prompt_obj, product, person, scene, dest=dest,
                    notable_details=(attributes or {}).get("notable_details"),
                    theme=theme, shop=shop, logo=logo, language=language,
                )
                # đóng dấu TÀI KHOẢN đã tạo ảnh này → lúc sửa mở đúng tài khoản
                res["profile"] = profile_name
                if res["status"] == "success":
                    if qc:
                        res["qc"] = await qc_image(sess, res["image"], attributes or {})
                    async with lock:
                        consec["n"] = 0
                        done[idx] = res
                        _emit_img(idx, prompt_obj, res)
                else:
                    is_limit = await _session_hit_limit(sess)
                    async with lock:
                        consec["n"] += 1
                        streak = consec["n"]
                    if is_limit or streak >= _FAIL_STREAK:
                        q.put_nowait((idx, prompt_obj))
                        limit_event.set()
                        return
                    async with lock:
                        done[idx] = res
                        _emit_img(idx, prompt_obj, res)
            except StopRequested:
                stopped["v"] = True
                q.put_nowait((idx, prompt_obj))
                limit_event.set()
                return
            finally:
                pool.put_nowait(sess)

    await asyncio.gather(*[worker() for _ in range(conc)])
    if stopped["v"]:
        raise StopRequested()
    remaining = [(idx, p) for (idx, p) in items if idx not in done]
    return done, remaining, limit_event.is_set()


async def generate_from_prompts(prompts, product: Path, person=None, scene=None,
                                attributes=None, theme: str = "", shop: str = "",
                                seo=None, market: str = DEFAULT_MARKET,
                                concurrency: int = DEFAULT_CONCURRENCY,
                                qc: bool = False, output_base: Path = OUTPUT_DIR,
                                hidden: bool = False, profiles=None, cancel=None,
                                logo: Optional[Path] = None,
                                want_seo: bool = False, product_info: str = "",
                                language: str = "vi",
                                product_extra: Optional[List[Path]] = None,
                                progress: ProgressCB = None) -> dict:
    """Tạo ảnh từ prompt cho sẵn, TỰ XOAY qua các tài khoản khi hết lượt.

    profiles: danh sách (profile_dir, tên) để xoay. Hết sạch → dừng + báo.
    cancel: threading.Event — set khi user bấm Dừng.
    want_seo: nếu True và chưa có seo → sinh luôn bài viết SEO trên tài khoản
              đăng nhập đầu tiên (tạo ảnh + SEO trong 1 lần chạy).
    """
    prompts = [p for p in (prompts or []) if (p.get("prompt") or "").strip()]
    if not prompts:
        raise RuntimeError("Không có prompt để tạo ảnh.")
    items = [(i + 1, p) for i, p in enumerate(prompts)]
    n = len(items)
    profiles = profiles or [(None, "default")]
    # gộp ảnh sản phẩm chính + các mẫu mã phụ → 1 danh sách để upload khi tạo ảnh
    products = [product] + [p for p in (product_extra or [])]

    sid, sdir = store.new_session_dir(output_base)
    store.write_prompts(sdir, prompts)

    results_by_idx = {}
    remaining = list(items)
    user_stopped = False
    seo_result = dict(seo or {})
    seo_needed = want_seo and not seo_result
    _emit(progress, "generate_start", {"total": n, "concurrency": concurrency})

    for profile_dir, prof_name in profiles:
        if not remaining or user_stopped:
            break
        if cancel is not None and cancel.is_set():
            user_stopped = True
            break
        _emit(progress, "account", {"profile": prof_name, "remaining": len(remaining)})
        br = AioBrowser(hidden=hidden,
                        **({"profile_dir": profile_dir} if profile_dir else {}))
        try:
            await br.start()
            page0 = await br.first_page()
            await br.open_chatgpt(page0)
            if not await br.is_logged_in(page0, timeout_ms=15000):
                _emit(progress, "account_skip",
                      {"profile": prof_name, "reason": "chưa đăng nhập"})
                continue
            seo_task = None
            if seo_needed:
                _emit(progress, "seo_start", {})
                if attributes:
                    # Đã có thuộc tính → viết SEO ở tab riêng CHẠY SONG SONG với
                    # việc tạo ảnh (trước đây phải chờ xong SEO mới tạo ảnh,
                    # mất thêm 1-2 phút chết).
                    if product_info and not attributes.get("user_product_info"):
                        attributes = {**attributes,
                                      "user_product_info": product_info}

                    async def _seo_job(attrs=attributes):
                        seo_page = await br.new_page()
                        ss = AioSession(seo_page)
                        ss.cancel = cancel
                        try:
                            await ss.new_chat()
                            return await generate_seo(ss, attrs, shop, market,
                                                      language)
                        finally:
                            try:
                                await seo_page.close()
                            except Exception:
                                pass

                    seo_task = asyncio.ensure_future(_seo_job())
                else:
                    # Chưa có thuộc tính → phải phân tích ảnh trước, và khâu tạo
                    # ảnh cũng cần thuộc tính đó → giữ tuần tự.
                    try:
                        seo_page = await br.new_page()
                        ss = AioSession(seo_page)
                        ss.cancel = cancel
                        r = await make_seo(ss, product, product_info, shop,
                                           market, language)
                        if isinstance(r, dict):
                            seo_result = r.get("seo", {}) or {}
                            attributes = attributes or r.get("attributes", {})
                        seo_needed = False
                        _emit(progress, "seo_done", {})
                        try:
                            await seo_page.close()
                        except Exception:
                            pass
                    except StopRequested:
                        user_stopped = True
                        break
                    except Exception as e:
                        _emit(progress, "account_error",
                              {"profile": prof_name, "error": repr(e)})
            try:
                done, remaining, limit_hit = await _batch_account(
                    br, page0, remaining, products, person, scene, attributes, theme,
                    shop, concurrency, qc, sdir, n, len(results_by_idx), progress,
                    cancel, logo, language=language, profile_name=prof_name,
                )
            finally:
                if seo_task is not None:
                    try:
                        seo_result = await seo_task or seo_result
                        seo_needed = False
                        _emit(progress, "seo_done", {})
                    except StopRequested:
                        user_stopped = True
                    except Exception as e:
                        _emit(progress, "account_error",
                              {"profile": prof_name, "error": repr(e)})
            results_by_idx.update(done)
            if limit_hit:
                _emit(progress, "account_limit",
                      {"profile": prof_name, "remaining": len(remaining)})
        except StopRequested:
            user_stopped = True
        except Exception as e:
            _emit(progress, "account_error",
                  {"profile": prof_name, "error": repr(e)})
        finally:
            await br.close()

    if user_stopped:
        _emit(progress, "stopped", {"remaining": len(remaining)})
    elif remaining:
        _emit(progress, "exhausted", {"remaining": len(remaining)})

    results = []
    for idx, p in items:
        if idx in results_by_idx:
            results.append(results_by_idx[idx])
        else:
            results.append({
                "type": p["type"], "label": p.get("label", p["type"]),
                "prompt": p["prompt"], "image": None, "status": "skipped",
                "conversation_url": "", "error": "hết tài khoản",
            })

    store.write_seo(sdir, seo_result or {}, theme, shop, language)
    out = {
        "session_id": sid, "dir": str(sdir), "attributes": attributes or {},
        "theme": theme, "prompts": prompts, "seo": seo_result or {}, "results": results,
        "ok_count": sum(1 for r in results if r["status"] == "success"), "total": n,
    }
    store.write_results(sdir, out)
    out["zip"] = str(store.zip_session(sdir, sid))
    _emit(progress, "done", {"ok": out["ok_count"], "total": n, "zip": out["zip"]})
    return out


async def edit_image(
    conversation_url: str,
    edit_prompt: str,
    dest: Path,
    extra_images: Optional[List[Path]] = None,
    profile_dir: Optional[Path] = None,
    hidden: bool = False,
    headless: bool = False,
) -> Optional[str]:
    """Mở lại đúng cuộc chat, gửi prompt sửa → tải ảnh MỚI (vuông) về dest."""
    br = AioBrowser(headless=headless, hidden=hidden,
                    **({"profile_dir": profile_dir} if profile_dir else {}))
    await br.start()
    try:
        page = await br.first_page()
        await br.open_chatgpt(page)
        if not await br.is_logged_in(page, timeout_ms=20000):
            raise RuntimeError("Chưa đăng nhập ChatGPT.")
        s = AioSession(page)
        await s.open_conversation(conversation_url)
        src = await s.refine(edit_prompt, extra_images)
        if not src:
            return None
        out = Path(dest)
        await s.download_image(src, out)
        try:
            to_square(out)
        except Exception:
            pass
        return str(out)
    finally:
        await br.close()


async def _read_session_email(page) -> str:
    """Lấy email/tên tài khoản ChatGPT đang đăng nhập (qua /api/auth/session)."""
    try:
        return await page.evaluate(
            """async () => {
                try {
                    const r = await fetch('/api/auth/session', {credentials:'include'});
                    const j = await r.json();
                    return (j && j.user && (j.user.email || j.user.name)) || '';
                } catch(e) { return ''; }
            }"""
        )
    except Exception:
        return ""


async def do_login(profile_dir: Optional[Path] = None,
                   max_wait_s: int = 600) -> bool:
    """Mở trình duyệt HIỆN cho user đăng nhập, lưu session + tên tài khoản."""
    br = AioBrowser(headless=False, hidden=False,
                    **({"profile_dir": profile_dir} if profile_dir else {}))
    await br.start()
    try:
        page = await br.first_page()
        await br.open_chatgpt(page)
        import time as _t
        end = _t.time() + max_wait_s
        while _t.time() < end:
            if await br.is_logged_in(page, timeout_ms=3000):
                await page.wait_for_timeout(3500)  # đảm bảo cookie ghi xong
                email = await _read_session_email(page)
                if email and profile_dir is not None:
                    from config import save_account_name
                    save_account_name(Path(profile_dir).name, email)
                return True
            await page.wait_for_timeout(2500)
        return False
    finally:
        await br.close()


async def refresh_account_names(profiles, hidden: bool = True,
                                progress: ProgressCB = None) -> dict:
    """Lấy email cho các profile đã login (mở nhanh, lưu vào accounts.json)."""
    from config import save_account_name
    out = {}
    for profile_dir, name in profiles:
        _emit(progress, "name_start", {"profile": name})
        try:
            br = AioBrowser(hidden=hidden,
                            **({"profile_dir": profile_dir} if profile_dir else {}))
            await br.start()
            try:
                page = await br.first_page()
                await br.open_chatgpt(page)
                email = ""
                if await br.is_logged_in(page, timeout_ms=12000):
                    email = await _read_session_email(page)
                    if email:
                        save_account_name(name, email)
                out[name] = email
                _emit(progress, "name_done", {"profile": name, "email": email})
            finally:
                await br.close()
        except Exception:
            out[name] = ""
    return out
