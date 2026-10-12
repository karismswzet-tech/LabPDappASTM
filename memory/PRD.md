# Elastech Production — Product Requirements Document

## Original Problem Statement
Build a company portfolio web app "Elastech Production" with a dark-mode (black/dark), professional-tech aesthetic. Landing page shows the company name + tagline (SaaS, IoT, Web App, Mobile App). A permanent left sidebar holds the brand and 3 menus: K-HTT Analyst, Copper Strip ASTM D130, Rating DKA. Each module is a petroleum lab testing tool with sample data input, rating assessment, AI analysis, and PDF report export — shown as an input form + tidy results table in dark mode.

## User Choices
- AI analysis: Claude Sonnet 4.6 via Emergent Universal LLM Key
- Authentication: none (all modules public)
- Persistence: save test history to MongoDB
- Module technical content: based on general petroleum industry standards (ASTM D130, etc.)

## Architecture
- Frontend: React 19 + React Router + Tailwind + shadcn/ui, framer-motion, react-query, jsPDF (client-side PDF export). Dark zinc theme, amber accent, Outfit/Inter/JetBrains Mono fonts.
- Backend: FastAPI + Motor (MongoDB). All routes under /api.
- LLM: emergentintegrations LlmChat -> anthropic/claude-sonnet-4-6.

## Data Model (collection: samples)
id, module (khtt|copper-strip|rating-dka), sample_code, sample_name, product_type, operator, test_date, parameters{}, rating, notes, ai_analysis, ai_analyzed_at, created_at.

## Implemented (2026-06)
- Landing page: hero, tagline chips, 3 module cards, feature strip.
- Permanent left sidebar (desktop) + mobile top-bar menu, active-route amber indicator.
- 3 lab modules (generic ModulePage driven by config/modules.js): sample input form, rating select, per-module parameters, results table.
- Create / list / delete samples (persisted to MongoDB).
- AI analysis endpoint (Claude Sonnet 4.6) returning structured Indonesian report; stored on the sample.
- Detail dialog with parameter table + AI analysis.
- Client-side branded PDF export per sample.
- Verified end-to-end by testing agent: backend 100%, frontend 100%.

## K-HTT Analyst — paritas dengan versi mobile (2026-06, selesai & teruji)
Sumber: github.com/Ilhamfawwaz28/RatingMeasurementKharisma (mobile Expo). Backend /api/kht/* sudah identik
(upload multipart + chunked fallback, AI Vision Gemini 3.1 Pro 2-gambar vs Nikko Color Scale, rating 0–10,
CLEAR ≥7 / TARNISH, edit rating/summary/recommendation, dashboard, trend, color-scale, soft delete, seed 4 demo).
Frontend baru (React):
- Rute: /khtt (Dashboard), /khtt/new (New Test), /khtt/history, /khtt/trend, /khtt/result/:id, /khtt/color-scale.
- New Test: Camera (getUserMedia) / Gallery + CropEditor (drag/resize, USE FULL / USE CROP), form Sample Info & Test Condition
  (default 320°C/16h/10/0.31), Run AI Vision (job polling s/d 6 menit, stage text).
- Result: TubeViewer Heatmap/Original, RatingGauge, KHT scale, edit inline rating/deskripsi/rekomendasi, export PDF, delete.
- History: search backend, chip All/Clear/Tarnish, mode pilih + Pilih Semua, export PDF gabungan (cover + halaman/sampel).
- PDF: layout HTML identik mobile, dicetak via iframe tersembunyi + window.print (Print → Save as PDF).
- Tema global diubah ke navy gelap (#0A1420/#112033) + aksen cyan (#00D2D3), font Barlow Condensed + JetBrains Mono
  (override palet zinc/amber di tailwind.config.js). Sidebar punya sub-nav K-HTT.
- File: frontend/src/lib/kht/{api,format,pdf}.js, components/kht/{ui,viz,capture}.jsx, pages/kht/*.jsx.
- Testing agent: backend 11/11 (tests/test_kht.py), frontend semua alur lolos (test_reports/iteration_2.json).

## Copper Strip ASTM D130 — paritas dengan versi mobile (2026-07, selesai; backend teruji 18/18)
Sumber: github.com/karismswzet-tech/RatingMeasurement3-App (mobile Expo). Copper Strip yang tadinya hanya
manual-entry generik kini dibangun ulang jadi modul AI Vision penuh, meniru pola modul DKA yang sudah ada.
Backend /api/copper/*: upload (pakai /api/kht/upload bersama) + analyze/start job async + polling jobs/{id},
AI Vision Gemini gemini-3.1-pro-preview membandingkan foto sampel vs chart standar ASTM D130/IP 154 (bundled
reference/astm_d130.jpg), klasifikasi 0/1a/1b/2a/2b/2c/2d/3a/3b/3c/4a/4b/4c, status CLEAR (kelas 0/1a/1b) /
TARNISH, severity 0–12, confidence, ai_summary + recommendation (Bahasa Indonesia). CRUD tests (search q,
edit klasifikasi→auto recompute label/group/color/severity/status, edit summary/recommendation, soft delete),
dashboard (total/clear/tarnish), trend, reference-scale (base64 chart + 13 kelas). 4 demo test + reference
di-seed saat startup.
Frontend (React) mirror DKA/KHT:
- Rute: /copper-strip (Dashboard), /new, /history, /trend, /copper-strip/result/:id, /copper-strip/scale.
- New Test: Camera (getUserMedia)/Gallery + form (Sample ID auto CU-YYYY-MM-DD-nnn, Product default
  "Diesel Fuel B30", Batch, Operator, Temp 100°C, Duration 3h, Remark), Run AI Vision (polling s/d 6 menit).
- Result: CopperClassGauge (swatch warna kelas + border CLEAR/TARNISH), CopperClassPicker koreksi manual 0–4c,
  edit inline deskripsi/rekomendasi, export PDF (layout identik mobile via window.print), delete.
- History: search backend + mode pilih (Pilih Semua) + export PDF gabungan (cover + 1 halaman/sampel).
- Trend: severity chart 0–12. Scale: chart standar ASTM D130 + daftar 13 kelas dengan status.
- File: frontend/src/lib/copper/{api,pdf}.js, components/copper/ui.jsx, pages/copper/*.jsx. Sidebar sub-nav Copper.
- Teruji testing agent: backend 18/18 lolos (termasuk analisa AI nyata ±27 dtk).

## Auth — login internal (single admin) (2026-07, selesai; backend teruji 16/16)
Halaman login profesional untuk aplikasi internal. Backend: kredensial dari env (ADMIN_USERNAME,
ADMIN_PASSWORD_HASH_B64 = base64 dari bcrypt hash agar `$` aman di .env; SESSION_TTL_MINUTES=60).
Endpoint /api/auth/login|me|logout; session di Mongo 'sessions' dengan expiry geser (sliding) untuk
timeout inaktivitas. Middleware auth_guard memproteksi SEMUA /api/* kecuali: OPTIONS, /api & /api/
(health), /api/auth/*, /api/kht/files/* (serving gambar untuk <img>). Frontend: AuthProvider + interceptor
(axios + global fetch inject X-Session-Token, tangani 401), RequireAuth guard (redirect ke /login bila
belum login), halaman /login (tema navy/cyan, show/hide password, error inline), tombol Logout di sidebar
& top-bar mobile (hapus session backend + token lokal). Kredensial default admin/Elastech@2026 (di
memory/test_credentials.md). Catatan: preview diakses via host REACT_APP_BACKEND_URL
(web-app-rating.preview.emergentagent.com) — mengakses via host lain memicu CORS.

## Rust Preventing ASTM D1748 — PDF dengan foto, penilaian inspector & detail perhitungan AI (2026-10, selesai; teruji 30/30)
- Backend: verdict AI asli dibekukan (ai_grid_boxes/ai_rusted_box_count/ai_grade) — koreksi grid tidak menimpanya.
  AI Vision juga mengembalikan grid_corners (4 sudut zona 50×50 mm, ternormalisasi); endpoint baru
  POST /api/rust/tests/{id}/locate-grid untuk record lama. Penilaian manual inspector terpisah: inspector_count
  (-1 = hapus) → inspector_grade otomatis, inspector_name, inspector_notes, inspector_at.
- Frontend: lib/rust/figure.js (canvas: overlay grid pada foto full+zona, matriks 1/0 + Σ baris/kolom + skala grade,
  perbandingan AI vs inspector + kesesuaian %), lib/rust/pdf.js (3 halaman/sampel: ringkasan+foto asli, detail
  perhitungan, catatan+kriteria+tanda tangan; PDF gabungan dengan cover). Result: kartu Peta Grid, Reset ke AI,
  kartu Penilaian Manual Inspector. History: mode pilih + Export PDF gabungan.

## Rust D1748 — 2 metode penilaian: Active Zone 50×50 mm / Seluruh Gambar (2026-10, selesai; teruji 16/16 + AI nyata)
- Operator memilih metode di New Inspection (method zone|full dikirim ke /api/rust/analyze/start).
- Seluruh Gambar: foto dibagi rata 10×10 (tiap kotak 10% lebar×tinggi), prompt RUST_FULL_PROMPT, grid_corners = full frame,
  specimen_box_count. Hasil tiap metode disimpan di method_results; field top-level = metode resmi (aktif).
- Endpoint: PUT /api/rust/tests/{id}/method (jadikan resmi), POST /api/rust/tests/{id}/method/analyze (job, polling
  /api/rust/analyze/jobs/{id}). Koreksi grid hanya mengubah snapshot metode aktif.
- Result: kartu Peta Grid dengan tab ZONA 50×50 / SELURUH FOTO (badge RESMI), Analisa metode ini/ulang, Jadikan hasil resmi,
  panel Detail Analisa (jumlah, luas %, grade, confidence, ringkasan, gambar perhitungan). PDF: halaman Metode Pembanding.

## Backlog
- P1: Samakan modul Rating DKA dengan versi mobile (sudah ada modul /dka AI Vision + OCR di web).
- P1: Edit existing sample; search/filter & pagination in results table.
- P1: Spec/limit-based auto pass-fail rating suggestions per parameter.
- P2: Dashboard analytics across modules (trend charts).
- P2: Real corporate portfolio sections (about, services, contact) on landing.
- P2: Streaming AI analysis; multi-language reports.
- P2: Authentication + per-operator history if needed later.

## Next Tasks
- Await user feedback on module parameters / rating scales for accuracy to their real lab SOPs.

## Re-import ke pod baru (2026-09-30)
Webapp di-import dari `myapp.zip` ke pod kosong (backend/ & frontend/ sebelumnya belum ada sehingga
supervisor backend+frontend FATAL). Yang dilakukan:
- Copy `backend/`, `frontend/`, `.emergent/`, `memory/`, `scripts/`, `test_reports/` ke /app.
- Dependency backend sudah lengkap di venv pod; `yarn install` untuk frontend.
- `frontend/package.json`: tambah script `dev` (dipakai supervisor: `yarn dev`) + `"proxy": "http://localhost:8001"`.
- `frontend/.env`: `REACT_APP_BACKEND_URL` dikosongkan → API dipanggil same-origin lewat proxy CRA,
  jadi tidak terikat host pod lama (sebelumnya lpd-auth-hub...) dan bebas masalah CORS.
- `backend/.env`: `EMERGENT_LLM_KEY` diganti key baru (key lama sudah exceeded budget → AI analysis 502).
Verifikasi: health/login/kht/copper/dka/htcbt/dkacec 200 via public URL, 401 tanpa token,
login UI → dashboard K-HTT tanpa console error, AI analysis DKA menghasilkan laporan.

## DKA-CEC — OCR Jam Running dari layar monitor (2026-09-30, selesai & teruji)
Fitur baru di modul DKA-CEC L-48-A-00: baca jam running mesin dari foto layar monitor, lalu
timer mulai dari 192:00 dikurangi jam running tersebut.
Backend:
- `DKACEC_RUNHOURS_PROMPT` + `run_dkacec_runhours_ocr()` (Gemini 3.1 Pro Vision): membaca deretan
  label waktu pada sumbu X grafik (mis. 68:27 ... 70:20, 70:27) dan mengambil yang PALING KANAN.
  Prompt eksplisit menolak salah-baca suhu (150.1C), jam/tanggal atas (12.26 07), sumbu Y (0-7),
  nilai flow (5.02 L/h) dan kode sampel.
- `POST /api/dkacec/runhours/start` (job async) + `GET /api/dkacec/runhours/jobs/{id}` (polling).
- `POST /api/dkacec/runhours/preview` — hitung 192:00 - jam running untuk koreksi manual di UI.
- Helper `_dkacec_norm_hhmm()` (validasi menit 0-59, maks 192 jam, fallback parse label string &
  fallback ke label sumbu X terbesar) dan `_dkacec_remaining_from()`.
- `submit-batch` menerima `running_hours`, `running_minutes`, `runhours_image_path`. finish_at =
  now + (192 jam - jam running); start_at digeser ke belakang sebesar jam running supaya
  progress bar mencerminkan progres nyata mesin (70:27 dari 192 jam -> 36.7%). Tolak 400 bila
  jam running >= durasi uji.
- `DkacecRun` menyimpan running_hours/running_minutes/running_label/runhours_image_path.
Frontend:
- `lib/dkacec/api.js`: `ocrRunHoursWithPolling()`, `remainingFromRunHours()` (hitung lokal supaya
  preview instan), `fmtHms()` (format jam:menit:detik tanpa pemisah hari), `DKACEC_TOTAL_HOURS=192`.
- `pages/dkacec/NewSample.jsx`: kartu "JAM RUNNING MESIN (OCR LAYAR MONITOR)" dengan pilihan
  Camera/Gallery terpisah, tombol BACA JAM RUNNING (OCR), hasil ditampilkan LEBIH DULU di field
  JAM : MENIT yang bisa dikoreksi manual (badge HASIL OCR -> DIKOREKSI MANUAL), daftar label sumbu X
  (yang terakhir di-highlight), dan preview "SISA WAKTU (START COUNTDOWN)" = 192:00 - jam running.
- `pages/dkacec/Monitor.jsx`: countdown pakai `fmtHms` (mis. 121:32:50) + keterangan
  "Mulai dari 192:00 - jam running 70:27".
Teruji: foto monitor asli user -> OCR 70:27 (13 label sumbu X, confidence 99), sisa 121 jam 33 menit,
koreksi manual 70:00 -> 122 jam 00 menit, timer jalan mundur 121:32:53 -> 121:32:50, progress 36.7%.
Negative case: menit 75 / 200 jam / jam running 192:00 / image_path kosong -> 400.

## Bugfix: foto dari HP tidak muncul di Rating DKA & export PDF (2026-09-30)
Gejala: foto yang diupload dari HP tidak tampil di halaman Rating DKA dan tidak ikut di export PDF.
Root cause: foto HP (terutama iPhone) berformat HEIC/HEIF. Pillow tanpa `pillow-heif` gagal membuka
file itu, dan `_compress_upload()` diam-diam mengembalikan byte ASLI saat decoding gagal. Akibatnya
byte HEIC mentah tersimpan dengan nama `.jpg` + content-type `image/jpeg`. Browser dan mesin PDF
tidak bisa mendecode byte tersebut -> gambar kosong di kartu maupun di PDF (PDF embed lewat
`imageToDataUri(fileUrl(path,1600))`, dan `_get_served_object` juga `pass` saat scaling gagal
sehingga menyajikan byte rusak apa adanya).
Perbaikan (backend/server.py):
- `pillow-heif` dipasang + `register_heif_opener()` saat import -> Pillow bisa decode HEIC/HEIF.
  Pin ditambahkan di requirements.txt (`pillow-heif==1.8.0`).
- `_compress_upload()` tidak lagi menyimpan byte yang gagal didecode; melempar `UnsupportedImage`.
  Kedua endpoint upload (`/kht/upload` dan `/kht/upload/finish`) mengembalikan 400 dengan pesan jelas
  berbahasa Indonesia (termasuk saran iPhone Settings > Camera > Formats > Most Compatible).
- Hasil upload SELALU disimpan sebagai JPEG (`ext="jpg"`, `image/jpeg`), tidak lagi mengikuti
  ekstensi/content-type kiriman klien yang bisa menyesatkan.
- `_ensure_browser_safe()` baru + dipakai di `_get_served_object()`: byte tersimpan yang formatnya
  bukan JPEG/PNG/WEBP/GIF ditranscode ke JPEG saat disajikan. Ini MENYEMBUHKAN foto HEIC yang sudah
  tersimpan sebelum perbaikan, baik untuk tampilan penuh (w kosong) maupun jalur PDF (w=1600).
Frontend (`lib/kht/api.js`): error 400 dari kedua jalur upload (langsung & chunked) kini menampilkan
pesan `detail` dari server, bukan hanya "Upload failed: 400".
Teruji: upload file .HEIC asli -> tersimpan JPEG, disajikan image/jpeg dan bisa didecode (full & w=400);
foto HEIC lama yang sudah tersimpan -> auto-healed jadi JPEG; alur penuh Rating DKA dengan foto HEIC
(upload -> analyze -> 4 crop tabung) semua crop tersaji valid; file rusak -> 400 pesan jelas.
Catatan: perbaikan ini berlaku untuk SEMUA modul karena semuanya memakai endpoint upload yang sama.

### Lanjutan bugfix: preview foto HEIC sebelum diunggah (2026-09-30)
Testing agent menemukan sisa masalah pada keluhan yang sama: preview SEGERA setelah foto dipilih
masih rusak untuk HEIC, karena `URL.createObjectURL(file)` menunjuk byte HEIC mentah dan browser
(Chromium/Android) tidak bisa mendecode HEIC sendiri — jadi meski server sudah benar, user masih
melihat gambar rusak di langkah pertama.
Perbaikan: helper baru `pickPreview(file)` di `frontend/src/lib/kht/api.js`:
- Coba `createImageBitmap(file)`. Bila browser BISA decode -> tetap pakai blob URL lokal (cepat,
  tanpa upload) seperti sebelumnya.
- Bila TIDAK bisa (HEIC/HEIF) -> file diunggah lebih dulu, preview memakai URL JPEG hasil konversi
  server `fileUrl(path, 1600)`, dan `imagePath` dikembalikan supaya TIDAK diunggah dua kali.
Dipakai di semua pemilih galeri: `pages/dka/NewTest.jsx` (modul yang dilaporkan),
`pages/copper/NewTest.jsx` (2), `pages/kht/NewTest.jsx` (2, termasuk cropper),
`pages/htcbt/NewSample.jsx`, `pages/dkacec/NewSample.jsx` (2). Rating DKA menampilkan placeholder
"Menyiapkan foto…" (`data-testid="dka-preparing-photo"`) selama konversi, dan handler kamera
me-reset cached path.
Fixture uji dipindah ke /app/tests/fixtures/ (dka_iphone.heic, iphone_photo.heic, plain_test.jpg,
plain_test.png) karena /tmp terhapus saat pod restart.
Hasil retest testing agent: 12/12 check lulus, 0 bug. Termasuk: preview HEIC 1280x960 via URL server,
JPEG biasa tetap preview lokal blob (tanpa upload), HEIC hanya diunggah SEKALI untuk pick+analyze,
alur analisa penuh dari HEIC + semua crop tampil, preview HEIC di K-HTT/Copper/DKA-CEC, history
thumbnail, dan URL gambar PDF export tetap decodable.



## Copper Strip — 4-sample batch AI Vision + OCR (2026-10, implemented)
- New Test now accepts one photo containing up to four copper strips arranged horizontally, vertically, or in a mixed layout, with shared Product, Batch/Lot, Operator, Temperature, Duration, and Remark metadata.
- Backend endpoints: `POST /api/copper/batch/analyze/start`, `GET /api/copper/batch/analyze/jobs/{id}`, `GET /api/copper/batches/{batch_id}`, and batch soft-delete. Gemini Vision compares each detected strip with the ASTM D130/IP 154 chart, OCRs each handwritten label, returns a valid D130 class, and stores separate records linked by `batch_id` with `sample_index` and crop path.
- Frontend batch result route `/copper-strip/batch/:batchId` mirrors Rating DKA: per-sample OCR ID correction, manual class correction, per-sample summary/recommendation, and combined PDF report.
- Backend infrastructure and frontend UI were verified. Full real AI 4-sample OCR/rating flow remains pending because the current EMERGENT_LLM_KEY has exhausted provider budget; no third-party response was mocked.


## Rust Preventing ASTM D1748 — 100-Box Metal Panel Inspection (2026-10-04, implemented & tested)
- Added protected module routes: `/rust-preventing`, `/rust-preventing/new`, `/rust-preventing/history`, `/rust-preventing/trend`, `/rust-preventing/grid-scale`, and `/rust-preventing/result/:id`.
- Backend API: `/api/rust/analyze/start`, `/api/rust/analyze/jobs/{id}`, `/api/rust/tests`, `/api/rust/tests/{id}`, `/api/rust/dashboard`, `/api/rust/trend`, and `/api/rust/reference-scale`.
- AI Vision uses the existing Emergent `EMERGENT_LLM_KEY` + Gemini 3.1 Pro Vision, strict JSON output, and async job polling. The prompt enforces the central 50×50 mm area, 60×80 mm / 0.5 mm cross-cut measuring plate, 100 5×5 mm boxes, and propagation rule.
- Deterministic classification: A=0, B=1–10, C=11–25, D=26–50, E=51–100. Backend stores `grid_boxes` (100 booleans), count, grade, confidence, spread, Indonesian summary/recommendation, metadata, and image path in MongoDB; uploaded images use existing Emergent Object Storage flow.
- Frontend includes a 10×10 audit grid with stable box test IDs, manual grid correction + save/recompute, history, trend, reference scale, and print/PDF report with metadata and inspector signature block.
- Testing agent iteration_7: 17/17 executed checks passed (16/16 pytest; 1 optional update test skipped because no AI-seeded record), 0 backend issues, 0 frontend issues, existing five modules regression-tested with 0 console errors. AI integration is LIVE but end-to-end image analysis was intentionally not exercised to preserve LLM budget; no API was mocked.



## Code Quality Refactor (2026-10-01, implemented & tested 20/20)
Resolves the critical findings from the system-injected Code Quality Report.

### Auth → HttpOnly Cookies (XSS hardening)
- `backend/server.py`: `_extract_token` now prefers `request.cookies.get("elastech_session")` and falls back to legacy headers. `POST /auth/login` sets an HttpOnly, Secure, SameSite=None cookie via `response.set_cookie(...)`; `/auth/logout` clears it. Login response body no longer contains `token`, only `{username, ttl_minutes}`.
- CORS: switched to `allow_origin_regex=".*"` with `allow_credentials=True` when `CORS_ORIGINS=*` so the browser accepts credentialed responses with reflected Origin (fixes the previous `*`+credentials conflict).
- `frontend/src/lib/api.js`: axios instance set to `withCredentials: true`.
- `frontend/src/lib/authClient.js`: removed `getToken`/`setToken`/`clearToken` and the `elastech_token` localStorage key entirely. `installAuthInterceptors` now forces `credentials: "include"` on all `/api` fetches and still bubbles 401s to the AuthProvider.
- `frontend/src/context/AuthContext.jsx`: no longer imports or calls token helpers. `check()` always hits `/auth/me`; `login()` stops persisting a token.

### React hook deps
- `pages/htcbt/Monitor.jsx` and `pages/dkacec/Monitor.jsx`: added `run.id`, `run.duration_hours`, `run.temperature_c` to the "timer finished" useEffect dependency arrays.

### Stable keys for sample lists
- `pages/dkacec/NewSample.jsx` and `pages/htcbt/NewSample.jsx`: samples state refactored from `string[]` to `{id: uuid, code: string}[]`. Add/remove/edit helpers now rotate on `id`; the list renders `key={s.id}`. Prevents React stale-DOM bugs when a middle sample row is removed.
- `pages/copper/NewTest.jsx`: fixed-length Sample ID grid keyed by `copper-sample-${index}` (array truly immutable, so index is semantically stable).

### Verification
Testing agent iteration_6.json: 20/20 pass. Confirmed: login sets HttpOnly cookie, `document.cookie` cannot see it from JS, no `elastech_token` in localStorage, protected endpoints 200 with cookie / 401 without, CORS preflight returns `Access-Control-Allow-Credentials: true` with reflected Origin (not `*`), logout clears cookie, all 5 modules load after login without console errors.

## Re-import 2026-06
- Imported from github.com/karismswzet-tech/WEBApp6Astm.git into new pod; env restored, deps installed (jspdf, pillow-heif, emergentintegrations). Smoke test 39/39 backend + all 6 module UIs pass.
- 2026-06: Rust D1748 Result — kotak pada foto overlay "PETA GRID PADA FOTO" bisa diklik manual (toggle karat), count & grade ASTM D1748 update live, tombol SIMPAN KOREKSI. Demo record RUST-DEMO-079 di-seed (AI budget habis).
- 2026-06: Export PDF Rust disederhanakan — hanya 'Penilaian Inspector' (dari grid tersimpan), tanpa AI/pembanding/manual/perbandingan; overlay & matriks mengikuti grid inspector.
- 2026-06: AI Vision/OCR fixed — EMERGENT_LLM_KEY diganti ke key milik user (dari .env-backup) karena key pod 0 budget. Semua modul AI & OCR lolos tes.
- 2026-06: Copper batch — PUT sample_id kini simpan ke meta.sample_id (input & PDF sinkron, draft disimpan sebelum export); crop AI pakai Gemini box_2d (1 strip per crop, pad 0.008).
- 2026-06: Copper batch — Atur Crop Manual (modal geser/resize kotak crop per sample, PUT /api/copper/tests/{id}/crop, bbox disimpan per record).
- 2026-06: Copper batch — Rating Ulang Otomatis (POST /api/copper/tests/{id}/rerate, checkbox di CropEditor default aktif).

## Modul Baru (2026-10)
- **Humidity Cabinet Test ASTM D1748** (`/api/humidity/*`, slug `/humidity-cabinet`): klon Rust Preventing, penilaian SELALU metode Seluruh Gambar (seluruh foto = active zone, 10×10 = 100 kotak), Grade A–E sama. Koleksi `humidity_tests`/`humidity_jobs`. Tanpa demo data.
- **DIP TEST In House Method** (`/api/diptest/*`, slug `/dip-test`): klon persis modul Humidity Cabinet (metode Seluruh Gambar, 10×10 = 100 kotak, Grade A–E sama). Koleksi `diptest_tests`/`diptest_jobs`. Tanpa demo data.
- Kedua modul memakai AI Vision Gemini gemini-3.1-pro-preview (Emergent LLM key), fitur: analisa AI, koreksi grid manual, penilaian inspector, dashboard, trend, history, export PDF.

## Fix Rust D1748 AI Vision + Label OCR baru (2026-10-10, teruji iteration_18: backend 35/35, frontend 100%)
- RCA: modul Salt Spray mendefinisikan ulang `_analyze_rust` → analisa Rust tersimpan ke salt_tests, GET /api/rust/tests/{id} 404.
  Fungsi Salt di-rename `_analyze_salt`.
- Baru: POST /api/rust/ocr/start + GET /api/rust/ocr/jobs/{id} (generic _label_ocr_start, Gemini 3.1 Pro) — baca label tulisan tangan
  (sample_id, operator, batch, suhu, exposure). New Inspection: foto di-upload sekali, OCR otomatis, kartu LABEL OCR + tombol Baca Ulang,
  isi form otomatis (Sample ID tidak ditimpa bila user sudah mengetik).
- get_object menolak path kosong; /rust/analyze/start & /rust/ocr/start → 400 bila image_path kosong.
- Fixture: tests/fixtures/rust_panel.jpg; pytest backend/tests/test_rust_fix_and_ocr.py.

## 2026-10-12 — Salt Spray Kartu Pengamatan (1 foto = 4 plat)
- Upload 1 foto 4 plat → Gemini 3.1 Pro mendeteksi box_2d tiap plat (urutan baca) → crop → tiap plat dinilai Metode Seluruh Gambar 10×10 (gambar bersih + overlay grid bernomor, prompt senior analyst).
- Fallback: bila tidak tepat 4 plat → dibagi 4 kolom sama rata; tombol Deteksi Ulang.
- Form: No. Urut, Durasi, Sample 1–4 kode manual; kotak merah bernomor bisa diklik inspector; reset ke AI.
- Endpoint: POST /api/salt-spray/observations/detect/start, GET /api/salt-spray/observations/detect/jobs/{id}; CRUD /api/salt-spray/observations (photo_path + plates[4]).
- Tipe S/D & prefix dihapus; kartu format lama di-soft-delete saat startup. Export PDF menampilkan foto + 4 overlay plat.

## 2026-10-12 — Header Data Pengujian + Tabel Report (Kartu Pengamatan)
- Header global (GET/PUT /api/salt-spray/observation-header, koleksi salt_obs_header id=default): operator, posisi specimen, pressure, water, temp chamber min-max, saturated air, pH, plat grinding (+ket). Duration otomatis (jam saat semua sample 100%).
- Kartu: field Jam Pengamatan numerik (hours); duration_label = "<h> Jam"; backfill hours dari label lama.
- Tabel report (frontend buildReport di lib/saltspray/obsReport.js): baris = kode sample (case/spasi-insensitive), kolom 0..192, berhenti di jam semua 100%, +24 jam sampai observasi terakhir bila >192; 100% merah; auto-isi 100% setelah tercapai.
- Export PDF: Data Pengujian + Tabel Report + Kartu Pengamatan dalam satu dokumen.

## 2026-10-12 — History Pengamatan (arsip seri Salt Spray)
- Kartu Pengamatan: banner "Selesaikan & Simpan ke History" saat semua sample 100%; panel progress + "Hentikan & Arsipkan Seri" (force, peringatan) bila belum.
- Backend: POST /api/salt-spray/observation-series/complete {force,note}, GET list, GET /{id} (+cards), DELETE /{id}, POST /{id}/reopen (409 jika ada kartu aktif), GET active-summary. Kartu arsip ditandai series_id (read-only, PUT 409). Header baru: kondisi chamber dibawa, operator/jam-tanggal mulai/grinding dikosongkan.
- Frontend: tab History Pengamatan (stats, search, kartu seri dgn cover) + detail (header view, tabel, kurva recharts, galeri + lightbox, export PDF, buka kembali, hapus).
