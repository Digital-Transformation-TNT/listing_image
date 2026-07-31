# TNT Listing Image — Bàn giao tiến độ

Repo: https://github.com/Tanashi-Titus/listing_image
Nhánh làm việc: `fix/mac-hidden-and-prompt-loop` (CHƯA merge vào `main`)
Cập nhật: phiên làm việc gần nhất.

Toàn bộ thay đổi nằm trên nhánh trên, đã push. Tổng: ~1900 dòng thêm, 16 file.

---

## BỐI CẢNH DỰ ÁN (đọc để hiểu nhanh)

App tạo bộ ảnh listing sản phẩm + SEO cho TikTok Shop bằng cách **lái ChatGPT web
qua Playwright** (KHÔNG dùng API). Có app GUI PySide6 (`python app_listing.py`)
và CLI (`python run_listing.py`).

Luồng chính:
- `extract_attributes` (đọc ảnh sản phẩm → JSON thuộc tính)
- `generate_prompts` (sinh prompt tiếng Việt cho 9–10 loại ảnh)
- `generate_one` × N (mỗi ảnh: chat mới → upload ảnh → gửi prompt → chờ ảnh → tải về)
- `generate_seo` (bài viết + tiêu đề SEO)
- Chạy song song nhiều tab; hết lượt Free thì tự xoay tài khoản.

File cốt lõi:
- `core/aio_browser.py` — mở Chrome (persistent profile), chế độ ẩn.
- `core/aio_chatgpt.py` — thao tác 1 tab ChatGPT (gõ, gửi, chờ trả lời, chờ ảnh).
- `core/analyzer.py` — trích thuộc tính + sinh prompt + SEO.
- `core/generator.py` — ghép prompt cuối + tạo/tải 1 ảnh.
- `core/pipeline.py` — điều phối toàn luồng, xoay tài khoản, sửa ảnh.
- `ui_listing/window.py` / `widgets.py` / `workers.py` — GUI.

Test logic (không cần trình duyệt), chạy tất cả:
```
python tests/test_unit.py
python tests/test_features.py
python tests/test_ask_text.py
python tests/test_send.py
python tests/test_edit_concurrent.py
```

---

## ĐÃ SỬA / ĐÃ LÀM (theo commit, mới → cũ)

### 0. Sửa NHIỀU ẢNH cùng lúc (song song) + xếp hàng theo tài khoản  (chưa commit)
- Nhu cầu: đang sửa ảnh 1, vẫn nhập prompt gửi sửa tiếp ảnh 3, 4, 7... cùng lúc.
- Ràng buộc: KHÔNG mở 2 trình duyệt trên CÙNG 1 tài khoản (Chrome khoá
  `user-data-dir` → `_cleanup_profile_lock`/`_kill_profile_chrome` sẽ giết lẫn
  nhau). Nên: ảnh KHÁC tài khoản chạy song song thật; ảnh CÙNG tài khoản xếp
  HÀNG chờ, chạy lần lượt (thẻ hiện "⏳ Đang chờ...").
- Sửa `ui_listing/window.py`: thêm bộ điều phối sửa ảnh (`_enqueue_edit`,
  `_start_edit`, `_after_edit`, khoá theo `_edit_key`). BỎ `_set_running` khỏi
  luồng sửa (trước đây edit đầu xong là bật lại nút Tạo ảnh → xoá gallery đang
  sửa → treo/lỗi). Thanh trạng thái hiện "Đang sửa N ảnh (+M chờ)". Chặn tác vụ
  chính khi đang sửa (`_block_if_editing`) và chặn sửa khi tác vụ chính chạy.
- Test: `tests/test_edit_concurrent.py` (11 case, chạy offscreen).

### 0e. Thông báo RA NGOÀI app (Windows + macOS)  (chưa commit)
- Các bước xong (prompt/ảnh/SEO/sửa ảnh/sửa hàng loạt) + lỗi + dừng → bắn thông
  báo hiện cả khi thu nhỏ tool, thay cho QMessageBox chỉ hiện trong app.
- `window._notify()`: Windows/Linux dùng `QSystemTrayIcon.showMessage` (toast +
  click mở lại app qua `_raise_app`); macOS dùng NATIVE `osascript display
  notification` (`_notify_mac_native`) vì bản .app ký ad-hoc thường KHÔNG hiện
  được toast Qt. Kèm `QApplication.alert` (nháy taskbar Win / nảy Dock Mac).
  `_setup_tray()` tạo icon khay; `closeEvent` ẩn tray. `IS_MAC` = darwin.
- LƯU Ý BUILD: bản Windows .exe đã build lại. Bản macOS .app PHẢI build LẠI
  TRÊN MÁY MAC (`bash build_mac.sh`) — PyInstaller không cross-compile.

### 0d. Tab "Sửa ảnh hàng loạt"  (chưa commit)
- Tab mới cho nhập NHIỀU ảnh + chọn chức năng sửa CHUNG, mỗi ảnh gửi riêng
  (1 ảnh + CÙNG 1 prompt) vào ChatGPT, chạy SONG SONG theo "Số luồng", tự xoay
  tài khoản khi hết lượt (giống tạo ảnh). Kết quả đổ vào gallery "Ảnh kết quả"
  cũ (xem/sửa/tải như thường).
- Option: (1) Dịch chữ trong ảnh sang Việt/Anh — cấm bịa thêm, KHÔNG đổi chữ
  in trên nhãn sản phẩm; (2) Đổi tỉ lệ 1:1/16:9/9:16; (3) Prompt tự nhập.
  Chọn 1 hoặc nhiều cùng lúc.
- Code: `generator.build_batch_edit_prompt` (ghép prompt), `generator.to_ratio`
  (ép tỉ lệ cục bộ, chỉ đệm không cắt), `pipeline.batch_edit_images` +
  `_batch_edit_account` + `_edit_one_batch` (xoay tài khoản + song song),
  `workers.BatchEditWorker`, UI `window._build_batch_tab` + `_on_batch_edit` +
  `_on_batch_done`. Các tab dùng `_show_tab(widget)` thay số thứ tự cố định.
- Test: thêm case trong `tests/test_features.py` (build_batch_edit_prompt +
  to_ratio) — 50 case. Đã smoke-test wiring tab offscreen.

### 0c. Pop-up báo xong mỗi bước + chốt sale LUÔN có "FLASH DEAL"  (chưa commit)
- Thêm QMessageBox báo khi HOÀN THÀNH bước cần user thao tác tiếp:
  `_on_prompts_done` (tạo prompt xong → sang tab Prompt sửa), `_on_gen_done`
  (tạo ảnh + SEO xong → tab Ảnh kết quả / tải về), `_on_seo_done` (SEO xong →
  copy). Sửa ảnh: báo GỘP 1 lần khi cả ĐỢT sửa xong (`_notify_edit_batch_done`,
  đếm qua `_edit_batch_ok`/`_edit_batch_fail`) — tránh mỗi ảnh 1 popup khi sửa
  nhiều ảnh song song. (Đăng nhập đã có popup sẵn.)
- Ảnh CHỐT SALE (`closing`) LUÔN có nhãn "FLASH DEAL": ép ở `generator`
  (`FLASH_DEAL_NOTE`, chỉ áp cho `p_type=="closing"`, giữ nguyên chữ tiếng Anh
  IN HOA dù ngôn ngữ ảnh là gì) + nhắc thêm trong `analyzer.TYPE_STYLE['closing']`.
- Test: thêm 5 case FLASH DEAL trong `tests/test_features.py` (38 case).

### 0b. Tinh chỉnh tốc độ (giảm độ trễ chờ) — an toàn  (chưa commit)
- Nhịp hỏi ảnh `wait_for_image` 1000→600ms (bắt tín hiệu ảnh xong sớm hơn; đường
  dự phòng `stable>=2` giảm 2s→1.2s). Nghỉ sau khi gửi 600→300ms (`generate_one`)
  và 800→400ms (sửa ảnh) vì `wait_for_image` đã tự chờ "bắt đầu sinh". Nghỉ sau
  upload 500→250ms (send() vẫn CHỜ nút gửi sẵn sàng nên không mất an toàn).
- Ước tính tiết kiệm ~1s/ảnh (≈10s/bộ). Nút cổ chai lớn nhất VẪN là thời gian
  ChatGPT sinh ảnh (server) — không rút được. Muốn nhanh hơn nữa: tăng "Số luồng"
  (song song) nhưng rủi ro bị Cloudflare/hết lượt cao hơn.

### 1. Chống treo khi gửi tin nhắn lúc ảnh chưa upload xong  (ac6ed57)
- Triệu chứng: đính ảnh + gõ prompt nhưng ChatGPT không trả lời, đứng mãi.
- Nguyên nhân: `send()` bấm nút gửi NGAY khi ảnh còn upload → nút gửi disabled →
  click trượt → tin không đi → chờ hết timeout.
- Sửa `core/aio_chatgpt.py::send()`: chờ nút gửi SẴN SÀNG (upload xong) rồi mới
  bấm; xác nhận ô soạn trống (đã gửi); trả về bool. `ask_text/generate_one/
  refine/edit_image` dùng bool này để retry nhanh, không chờ mòn. `ask_text`
  ném `SendError` khi không gửi được.
- Test: `tests/test_send.py`.

### 2. Loại ảnh mới "Thông tin sản phẩm" (infographic)  (09af2ef)
- Thêm loại `product_info` tạo ảnh tờ thông số: tiêu đề lớn + ảnh sản phẩm có
  đường đo kích thước (cm) + cột biến thể màu/mùi có tên + danh sách thông số
  (tên, mùi, quy cách, thành phần) + dòng lưu ý ở đáy. Cấm bịa số liệu.
- `config.py` thêm vào `PROMPT_TYPES`; `analyzer.py` thêm `TYPE_STYLE`;
  `generator.py` thêm vào `SHOW_ALL_VARIANTS_TYPES`; UI: số ảnh max tự co giãn
  (giờ 10), mặc định chọn hết.

### 3. Sửa ảnh (edit) + nhiều màu không khoá 1 màu  (a42d82f)
- SỬA ẢNH: cách cũ mở lại chat cũ theo URL hay hỏng → "không sửa được". Nay mở
  CHAT MỚI, UPLOAD chính ảnh cần sửa + ảnh tham chiếu (nếu có) + prompt sửa →
  tạo ảnh mới, thay đúng ảnh cũ trên card đó. (`pipeline.edit_image`,
  `generator.build_edit_prompt`, `workers.EditWorker`, `window._on_edit`.)
- NHIỀU MÀU: trước ép "chọn 1 biến thể tiêu biểu" → model lấy ảnh đầu → cả bộ 1
  màu. Nay: ảnh bìa/tính năng/đối tượng/thông-tin-SP khoe NHIỀU màu; các ảnh
  khác XOAY VÒNG qua từng biến thể theo vị trí (`_variant_note`, `variant_index`).

### 4. UI danh sách nhiều ảnh sản phẩm + nút xóa riêng  (0344bb6, f50b340)
- `ImagePicker` chế độ `multiple`: hiện danh sách từng ảnh (thumbnail + tên) có
  nút ✕ xóa riêng; "Xóa tất cả" giữ nguyên.
- Sửa nút ✕ không hiện (do padding nút toàn cục nuốt chữ) + thu ô preview trên
  còn 1 dòng, phóng to vùng danh sách (150–320px).

### 5. Ép chữ tiếng Anh trên ảnh + nhiều ảnh sản phẩm + sửa ảnh đúng tài khoản  (02326df)
- Chọn ngôn ngữ EN mà ảnh vẫn ra chữ Việt: luồng tạo ảnh KHÔNG truyền `language`
  xuống. Nay `generator._lang_note` ép mọi chữ overlay theo ngôn ngữ (EN thì
  bắt buộc dịch, cấm để chữ Việt). Áp cho cả chế độ tự viết prompt.
- Nhiều ảnh sản phẩm: `ImagePicker` chọn nhiều; upload hết ở bước phân tích +
  tạo ảnh; prompt hiểu là CÙNG sản phẩm khác biến thể (không ghép nhầm nhiều món).
- Sửa ảnh chỉ ra "ảnh cuối": khi tạo qua nhiều tài khoản, mỗi ảnh ở chat của tài
  khoản tạo nó, nhưng edit mở bằng tài khoản trên dropdown → nhầm chat. Nay đóng
  dấu `profile` vào từng ảnh, edit mở đúng tài khoản đó.

### 6. Chạy ngầm (hidden) thật sự ẩn trên macOS + hết vòng lặp "hỏi đi hỏi lại"  (3a48d32, 4aa6b4d, 4135d3b)
- macOS kéo cửa sổ về màn hình khi đặt toạ độ âm (mẹo của Windows) → chế độ ẩn
  cũ vô tác dụng. Nay ẩn theo OS + kiểm bằng CDP: Windows toạ độ âm; macOS đẩy
  vượt mép phải mọi màn hình, không được thì THU NHỎ xuống Dock. Thêm cờ chống
  throttle để tab ẩn không bị Chrome bóp tốc độ. `kill_profile_chrome` thêm
  nhánh `pkill` cho Mac/Linux.
- Vòng lặp hỏi lại: `ask_text` cũ đọc "assistant cuối cùng" ngay sau khi gửi →
  gặp câu trả lời CŨ đứng yên → tưởng xong → JSON sai → hỏi lại vô tận. Nay bắt
  buộc thấy LƯỢT TRẢ LỜI MỚI + chốt bằng tín hiệu mạng; `_ask_json` có validate,
  chỉ hỏi lại khi thiếu thật (12 → tối đa 2 lần).
- Tốc độ: sinh prompt chia 3 tab song song; SEO chạy song song tạo ảnh; chat mới
  không tải lại trang; nhận diện hết lượt bằng HTTP 403/429 thay vì dò chữ.
- Đã CHỨNG MINH trên máy Mac thật của GitHub Actions (workflow
  `.github/workflows/mac-hidden-selftest.yml`, chạy `mac_hidden_selftest.py`):
  cửa sổ minimized, timer không bị bóp — TẤT CẢ ĐẠT.

---

## TÌNH TRẠNG KIỂM THỬ (QUAN TRỌNG — đọc kỹ)

- Đã có 58 test LOGIC (chạy không cần trình duyệt) — tất cả PASS.
- Chế độ ẩn macOS đã kiểm trên máy Mac thật của GitHub (chỉ ở trang about:blank,
  KHÔNG qua ChatGPT thật).
- CHƯA CHẠY end-to-end qua ChatGPT thật lần nào cho các thay đổi này. Tức là
  phần "nội dung prompt" và "luồng Playwright" mới chỉ kiểm ở mức mô phỏng.

### Cần 1 người chạy thật (Windows hoặc Mac có tài khoản ChatGPT đã login) xác nhận:
1. Chọn ngôn ngữ EN → chữ trên ảnh có ĐÚNG tiếng Anh không.
2. Up nhiều màu (vd 4 màu) → cả bộ 9–10 ảnh có TRẢI ĐỦ các màu không (ảnh bìa
   nhiều màu; các ảnh khác khác màu nhau).
3. Sửa 1 ảnh GIỮA (không phải ảnh cuối) → có ra đúng ảnh đó đã chỉnh và card đó
   cập nhật ảnh mới không. Thử cả khi bộ ảnh tạo qua nhiều tài khoản (xoay lượt).
4. Loại ảnh mới "Thông tin sản phẩm" → bố cục có giống mẫu (tiêu đề, ảnh + số đo,
   cột biến thể, danh sách thông số, dòng lưu ý) không. Nên nhập "Thông tin thêm
   về sản phẩm" (khối lượng/thành phần/kích thước) vì model chỉ dùng dữ liệu thật.
5. Chế độ ẩn trên máy Mac của nhân viên → tạo ảnh có chạy trơn không (kiểm thật
   qua ChatGPT, khác với test about:blank trên CI).
6. Bước phân tích ảnh không còn treo (lỗi ảnh chụp gần đây). Nếu vẫn treo, chụp
   log trong app lúc treo để biết kẹt ở khâu nào.

---

## VIỆC CÒN LẠI / CẦN LÀM TIẾP

### A. Bắt buộc trước khi phát rộng
- [ ] Chạy end-to-end thật 1 lần đủ luồng (phân tích → prompt → 9–10 ảnh → SEO →
      sửa 1 ảnh) trên Windows, xác nhận 6 mục ở trên.
- [ ] Chạy thật trên máy Mac của nhân viên (chế độ ẩn + tạo ảnh qua ChatGPT).
- [ ] Quyết định merge nhánh `fix/mac-hidden-and-prompt-loop` vào `main`.

### B. Rủi ro đã biết (cần theo dõi khi chạy thật)
- [ ] Selector ChatGPT có thể đổi bất cứ lúc nào: nút "chat mới"
      (`SEL_NEW_CHAT`), nút gửi (`SEL_SEND_BTN`), nút Dừng (`SEL_STOP_BTN`),
      ô soạn (`#prompt-textarea`) trong `core/aio_chatgpt.py`. Nếu ChatGPT đổi
      giao diện, sửa selector ở đây.
- [ ] Chế độ ẩn macOS dùng minimize xuống Dock: dặn người dùng ĐỪNG bấm mở lại
      cửa sổ đó khi đang chạy (đã ghi tooltip, nhưng nên nhắc trong hướng dẫn).
- [ ] Phân bổ màu theo biến thể đang là XOAY VÒNG cứng theo vị trí ảnh. Nếu muốn
      cố định "ảnh loại X luôn màu Y" thì phải làm cơ chế map riêng.
- [ ] Ảnh sản phẩm quá lớn/nhiều: upload có thể lâu; `send()` chờ nút sẵn sàng
      tối đa ~45s. Nếu mạng chậm hơn, cân nhắc tăng ngưỡng.

### C. Cải thiện nên có (không gấp)
- [ ] Bước sinh SEO (`make_seo_pipeline`) chưa nhận nhiều ảnh sản phẩm
      (`product_extra`) — hiện chỉ dùng ảnh chính. Có thể thêm cho đầy đủ.
- [ ] CLI `run_listing.py` chưa hỗ trợ nhiều ảnh sản phẩm (chỉ 1 `--product`).
      Tính năng nhiều ảnh hiện chỉ có trên GUI.
- [ ] `core/browser.py` + `core/chatgpt.py` (bản SYNC cũ) vẫn còn, chỉ CLI login
      dùng. Có thể dọn nếu không cần.
- [ ] Build lại bản phát hành: Windows (`TNT_Listing.spec`) và macOS
      (`build_mac.sh` / `TNT_Listing_mac.spec`) sau khi chốt code.

---

## GHI CHÚ KỸ THUẬT CHO AI CODE TIẾP

- Các hằng số/loại ảnh: `config.py` (`PROMPT_TYPES`, `USE_PERSON_TYPES`,
  `USE_SCENE_TYPES`, `DEFAULT_CONCURRENCY`).
- Prompt cuối gửi cho model tạo ảnh: `generator._build_final_prompt` (gồm
  `_lang_note` ép ngôn ngữ, `_variant_note` phân bổ màu). Prompt SỬA ảnh:
  `generator.build_edit_prompt`.
- Loại ảnh khoe nhiều biến thể: `generator.SHOW_ALL_VARIANTS_TYPES`.
- Đọc/parse JSON từ ChatGPT: `core/jsonutil.py`. Hỏi + retry: `analyzer._ask_json`
  (có tham số `validate` để chỉ hỏi lại khi nội dung thiếu).
- Chờ trả lời text: `aio_chatgpt.ask_text`. Chờ ảnh: `aio_chatgpt.wait_for_image`.
  Cả hai bám tín hiệu mạng (`stream_finished`) + DOM. Hết lượt: `hit_limit`
  (HTTP 403/429).
- Đừng bỏ `viewport` cố định và các cờ `ANTI_THROTTLE_ARGS` trong
  `aio_browser.py` — cần cho chế độ ẩn/thu nhỏ chạy đúng tốc độ.
