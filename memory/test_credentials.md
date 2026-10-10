# Test Credentials — Laboratorium Product Development (Elastech)

## Admin Login (single admin, internal app)
- URL: /login (klik "Masuk" dari landing page)
- Username: admin
- Password: admin123
- Source: backend/.env (ADMIN_USERNAME, ADMIN_PASSWORD_HASH_B64)

Catatan: PRD lama menyebut admin/Elastech@2026 — sudah tidak dipakai.
Hash aktif di .env terverifikasi untuk password `admin123`.

## Re-import (2026-09-30)
- Webapp di-import ulang dari myapp.zip ke pod baru.
- EMERGENT_LLM_KEY lama sudah habis budget → diganti key baru pod ini.
- frontend/.env: REACT_APP_BACKEND_URL dikosongkan (pakai same-origin + proxy CRA ke :8001).

## Auth Migration (2026-10-01)
- Session sekarang dikelola via HttpOnly cookie `elastech_session` (Secure, SameSite=None, Max-Age=TTL).
- Login response TIDAK lagi mengembalikan field `token` — hanya `{username, ttl_minutes}`.
- Untuk testing via curl: `curl -c jar.txt -X POST .../api/auth/login -d '{"username":"admin","password":"admin123"}'` lalu `-b jar.txt` di request berikutnya.
- CORS: `allow_origin_regex=".*"` + `allow_credentials=true` (bukan `*`).

## Re-import (2026-10-07)
- Di-import dari github.com/karismswzet-tech/WebApplandingpageIn6appnew.
- .env dipulihkan via scripts/restore_env.sh; REACT_APP_BACKEND_URL di-set ke preview pod baru; EMERGENT_LLM_KEY diganti key pod ini.
- Login admin/admin123 terverifikasi.

## Re-import (2026-06) dari github.com/karismswzet-tech/WEBApp6Astm
- backend/.env: ADMIN_* dan EMERGENT_LLM_KEY dipulihkan dari .env-backup (key user, ada saldo); DB_NAME tetap test_database.
- Login admin/admin123 terverifikasi.

## Re-import (2026-10-09) dari github.com/karismswzet-tech/WEBApp6Astm2
- .env dipulihkan via scripts/restore_env.sh; REACT_APP_BACKEND_URL di-set ke preview pod ini (03506451-...preview.emergentagent.com).
- EMERGENT_LLM_KEY dari backup aktif (tes LLM OK). DB_NAME=elastech_lab.
- Login admin/admin123 terverifikasi.

## Re-import (2026-10-10) dari github.com/karismswzet-tech/WebappRatingASTmLab
- .env dipulihkan via scripts/restore_env.sh.
- frontend/.env REACT_APP_BACKEND_URL di-set ke preview pod ini (3f7e8b92-1782-4a41-8fe8-2b813cd0fd40.preview.emergentagent.com).
- Semua dependency backend & frontend terpasang; backend & frontend RUNNING.
- Login admin/admin123 terverifikasi (HTTP 200). Demo data K-HTT, DKA, Copper Strip ter-seed otomatis.
