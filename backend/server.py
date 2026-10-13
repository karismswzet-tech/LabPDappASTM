import os
import io
import json
import uuid
import asyncio
import base64
import logging
import re
import bcrypt
import secrets
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Annotated, Any, Dict

import requests
from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException, Request
from fastapi.responses import Response, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict, model_validator
from dotenv import load_dotenv
from PIL import Image as PILImage, ImageOps, ImageDraw, ImageFont

# Foto dari HP (terutama iPhone) umumnya berformat HEIC/HEIF. Tanpa opener ini
# Pillow gagal membuka file tersebut, sehingga foto tersimpan mentah dan tidak
# bisa ditampilkan browser maupun di-embed ke PDF.
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    _HEIF_OK = True
except Exception:  # pragma: no cover - tetap jalan walau paket belum ada
    _HEIF_OK = False

from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent, TextDelta, StreamDone

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("elastech")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")

app = FastAPI(title="Elastech Production API")
api_router = APIRouter(prefix="/api")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ===========================================================================
# Authentication — single admin (credentials from env), bcrypt + sliding session
# ===========================================================================
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
_ADMIN_HASH_B64 = os.environ.get("ADMIN_PASSWORD_HASH_B64", "")
try:
    ADMIN_PASSWORD_HASH = base64.b64decode(_ADMIN_HASH_B64) if _ADMIN_HASH_B64 else b""
except Exception:
    ADMIN_PASSWORD_HASH = b""
SESSION_TTL_MINUTES = int(os.environ.get("SESSION_TTL_MINUTES", "60"))


def _verify_password(plain: str) -> bool:
    if not ADMIN_PASSWORD_HASH:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), ADMIN_PASSWORD_HASH)
    except Exception:
        return False


def _session_expiry_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=SESSION_TTL_MINUTES)).isoformat()


SESSION_COOKIE_NAME = "elastech_session"


def _extract_token(request: Request) -> str:
    # Prefer secure HttpOnly cookie; fall back to legacy headers for older clients.
    cookie_tok = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_tok:
        return cookie_tok.strip()
    tok = request.headers.get("x-session-token")
    if tok:
        return tok.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _set_session_cookie(response: Response, token: str):
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_MINUTES * 60,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )


def _clear_session_cookie(response: Response):
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", samesite="none", secure=True)


async def _validate_session(token: str) -> Optional[dict]:
    """Return the session doc if the token is valid & not expired (by inactivity),
    refreshing its sliding expiry. Otherwise delete/ignore and return None."""
    if not token:
        return None
    doc = await db.sessions.find_one({"token": token})
    if not doc:
        return None
    exp = doc.get("expires_at")
    exp_dt = None
    try:
        exp_dt = datetime.fromisoformat(exp) if isinstance(exp, str) else exp
    except Exception:
        exp_dt = None
    if exp_dt is not None and exp_dt.tzinfo is None:
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if not exp_dt or now > exp_dt:
        await db.sessions.delete_one({"token": token})
        return None
    await db.sessions.update_one(
        {"token": token},
        {"$set": {"last_active": now.isoformat(), "expires_at": _session_expiry_iso()}},
    )
    return doc


class LoginRequest(BaseModel):
    username: str
    password: str


@api_router.post("/auth/login")
async def auth_login(req: LoginRequest, response: Response):
    if req.username.strip().lower() != ADMIN_USERNAME.strip().lower() or not _verify_password(req.password):
        raise HTTPException(status_code=401, detail="Username atau password salah")
    token = secrets.token_urlsafe(32)
    now = now_iso()
    await db.sessions.insert_one({
        "token": token,
        "username": ADMIN_USERNAME,
        "created_at": now,
        "last_active": now,
        "expires_at": _session_expiry_iso(),
    })
    _set_session_cookie(response, token)
    return {"username": ADMIN_USERNAME, "ttl_minutes": SESSION_TTL_MINUTES}


@api_router.get("/auth/me")
async def auth_me(request: Request):
    doc = await _validate_session(_extract_token(request))
    if not doc:
        raise HTTPException(status_code=401, detail="Sesi tidak valid atau telah berakhir")
    return {"username": doc.get("username"), "ttl_minutes": SESSION_TTL_MINUTES}


@api_router.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    token = _extract_token(request)
    if token:
        await db.sessions.delete_one({"token": token})
    _clear_session_cookie(response)
    return {"ok": True}


# ===========================================================================
# Object storage
# ===========================================================================
STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
APP_NAME = "elastech-kht"
_storage_key: Optional[str] = None


def init_storage(force: bool = False):
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_LLM_KEY}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def put_object(path: str, data: bytes, content_type: str) -> dict:
    import time as _time
    key = init_storage()
    resp = None
    for attempt in range(3):
        resp = requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            data=data,
            timeout=120,
        )
        if resp.status_code == 404:
            key = init_storage(force=True)
            continue
        if resp.status_code >= 500 and attempt < 2:
            # object store kadang 500/503 sesaat -> coba lagi
            _time.sleep(0.8 * (attempt + 1))
            continue
        break
    resp.raise_for_status()
    return resp.json()


def get_object(path: str):
    global _storage_key
    if not str(path or "").strip() or str(path).strip().endswith("/"):
        raise FileNotFoundError("empty image path")
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    if resp.status_code in (404, 503):
        key = init_storage(force=True)
        resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


# ===========================================================================
# K-HTT ANALYST — Komatsu Hot Tube Tester AI Vision
# ===========================================================================
NIKKO_FILE = ROOT_DIR / "reference" / "nikko_color_scale.jpg"
REF_FILE = NIKKO_FILE if NIKKO_FILE.exists() else (ROOT_DIR / "reference" / "color_scale.jpg")


def reference_b64() -> str:
    with open(REF_FILE, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


STATUS_CLEAR = "CLEAR"
STATUS_TARNISH = "TARNISH"
LEGACY_STATUS = {"PASS": STATUS_CLEAR, "FAIL": STATUS_TARNISH}


def status_for_rating(rating: float) -> str:
    return STATUS_CLEAR if rating >= 7 else STATUS_TARNISH


def normalize_status(value, rating: float) -> str:
    s = str(value or "").strip().upper()
    s = LEGACY_STATUS.get(s, s)
    return s if s in (STATUS_CLEAR, STATUS_TARNISH) else status_for_rating(rating)


_LEVEL_LABEL_SUFFIX = {
    10: "None", 9: "Very Slight", 8: "Slight", 7: "Light", 6: "Moderate",
    5: "Moderate Heavy", 4: "Heavy", 3: "Very Heavy", 2: "Extremely Heavy",
    1: "Near Black", 0: "Plugged",
}


def nikko_level_for_rating(rating: float) -> dict:
    """Map a 0-10 rating to its Nikko COLOR SCALE level: grade + deposit label."""
    try:
        r = float(rating)
    except (TypeError, ValueError):
        r = 0.0
    lvl = max(0, min(10, int(r)))
    entry = next((l for l in NIKKO_LEVELS if l["level"] == lvl), NIKKO_LEVELS[0])
    return {
        "level": lvl,
        "grade": entry["grade"],
        "deposit_level_label": f"{entry['deposit_pct']} ({_LEVEL_LABEL_SUFFIX.get(lvl, '')})",
    }


NIKKO_LEVELS = [
    {"level": 0, "color": "#0E0A06", "name": "Hitam Pekat", "condition": "Endapan karbon hitam penuh, tabung tersumbat total.", "deposit_pct": "100%", "grade": "FAILED", "status": "TARNISH"},
    {"level": 1, "color": "#241407", "name": "Cokelat Kehitaman", "condition": "Endapan sangat berat mendekati hitam.", "deposit_pct": "~100%", "grade": "FAILED", "status": "TARNISH"},
    {"level": 2, "color": "#3C2610", "name": "Cokelat Sangat Gelap", "condition": "Endapan sangat berat (extremely heavy).", "deposit_pct": "90 - 100%", "grade": "VERY POOR", "status": "TARNISH"},
    {"level": 3, "color": "#5E3C16", "name": "Cokelat Gelap", "condition": "Endapan sangat tebal (very heavy).", "deposit_pct": "75 - 90%", "grade": "POOR", "status": "TARNISH"},
    {"level": 4, "color": "#7A4A20", "name": "Cokelat", "condition": "Endapan tebal (heavy).", "deposit_pct": "60 - 75%", "grade": "POOR", "status": "TARNISH"},
    {"level": 5, "color": "#A9702E", "name": "Amber / Cokelat Muda", "condition": "Endapan menengah-berat (moderate heavy).", "deposit_pct": "45 - 60%", "grade": "FAIR", "status": "TARNISH"},
    {"level": 6, "color": "#C9992F", "name": "Kuning-Amber", "condition": "Endapan menengah (moderate).", "deposit_pct": "30 - 45%", "grade": "FAIR", "status": "TARNISH"},
    {"level": 7, "color": "#D8B24C", "name": "Kuning Jerami", "condition": "Endapan ringan (light).", "deposit_pct": "15 - 30%", "grade": "GOOD", "status": "CLEAR"},
    {"level": 8, "color": "#E4D08A", "name": "Kuning Pucat", "condition": "Endapan sedikit (slight).", "deposit_pct": "5 - 15%", "grade": "VERY GOOD", "status": "CLEAR"},
    {"level": 9, "color": "#EFE6C4", "name": "Kuning Sangat Samar", "condition": "Endapan sangat sedikit (very slight).", "deposit_pct": "< 5%", "grade": "EXCELLENT", "status": "CLEAR"},
    {"level": 10, "color": "#EAF1F0", "name": "Bening / Tak Berwarna", "condition": "Tabung bersih tanpa endapan.", "deposit_pct": "0%", "grade": "EXCELLENT", "status": "CLEAR"},
]


class Parameters(BaseModel):
    deposit_area_pct: float = 0
    deposit_length_mm: float = 0
    deposit_coverage_pct: float = 0
    avg_intensity_l: float = 0
    avg_color_a: float = 0
    avg_color_b: float = 0
    max_intensity: float = 0
    thickness_index_mm: float = 0
    deposit_start_mm: float = 0
    deposit_end_mm: float = 0


class TestMeta(BaseModel):
    sample_id: str = ""
    oil_type: str = ""
    batch: str = ""
    operator: str = ""
    temperature_c: float = 320
    duration_hours: float = 16
    air_flow: float = 10
    oil_flow: float = 0.31
    remark: str = ""


class AnalyzeRequest(TestMeta):
    image_path: str


class TestRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    image_path: str
    meta: TestMeta
    rating: float = 0
    performance: str = ""
    confidence: float = 0
    status: str = "CLEAR"
    deposit_level_label: str = ""
    parameters: Parameters = Field(default_factory=Parameters)
    ai_summary: str = ""
    recommendation: str = ""
    ai_model: str = "gemini-3.1-pro-preview"
    created_at: str = Field(default_factory=now_iso)
    edited: bool = False
    edited_at: Optional[str] = None
    deleted_at: Optional[str] = None


class TestUpdate(BaseModel):
    rating: Optional[float] = None
    performance: Optional[str] = None
    status: Optional[str] = None
    deposit_level_label: Optional[str] = None
    ai_summary: Optional[str] = None
    recommendation: Optional[str] = None


RATING_REFERENCE = """KHT (Komatsu Hot Tube Tester) standard deposit rating scale (0-10),
matching the Nikko COLOR SCALE reference board:
10 = perfectly clear / colorless glass, 0% deposit (None) -> EXCELLENT
9  = very faint pale yellow, <5% (Very Slight) -> EXCELLENT
8  = pale yellow, 5-15% (Slight) -> VERY GOOD
7  = light straw / yellow, 15-30% (Light) -> GOOD
6  = yellow-amber, 30-45% (Moderate) -> FAIR
5  = amber / light brown, 45-60% (Moderate Heavy) -> FAIR
4  = brown, 60-75% (Heavy) -> POOR
3  = dark brown, 75-90% (Very Heavy) -> POOR
2  = very dark brown, 90-100% (Extremely Heavy) -> VERY POOR
1  = near-black brown -> FAILED
0  = black, 100% (Plugged) -> FAILED
On the reference board the CLEAR tube = 10 and the BLACK tube = 0.
CLEAR if rating >= 7, otherwise TARNISH."""

ANALYSIS_PROMPT = f"""You are the KHT-AI-V2 deposit rating engine for a Komatsu Hot Tube Tester (HTT),
acting as a laboratory color-analysis expert.

You are given TWO images:
1) The FIRST image is the official Nikko COLOR SCALE reference board. It shows a row of standard
   test tubes each labelled 0 to 10. The tube that is completely CLEAR/colorless is 10 (best, no
   deposit) and the tube that is BLACK/darkest is 0 (worst, fully plugged). The tubes between them
   go clear -> pale yellow -> amber -> brown -> dark brown -> black as the number decreases.
2) The SECOND image is the operator's photo of the SAMPLE. It can be either:
   a) a single cropped sample tube, OR
   b) the sample tube SLIPPED INTO the Nikko COLOR SCALE rack, standing in a row next to
      the numbered reference tubes 0-10. In that case the SAMPLE is the tube that carries a
      HANDWRITTEN label / handwriting on a small white sticker (the reference tubes are
      unlabelled and sit under printed number caps). Rate ONLY that handwritten-labelled
      tube. Prefer comparing it against the numbered reference tubes visible in the SAME
      photo (identical lighting) before falling back to the FIRST reference image.

MANDATORY RATING PROCEDURE — always follow this exact method:
1) POSITION: identify the sample tube by its PHYSICAL LOCATION on the board (which numbered
   slots it stands between). For a single cropped tube, skip to step 2 using the FIRST
   reference image.
2) ADJACENT COMPARISON: compare the sample's deposit color ONLY against the TWO ADJACENT
   reference tubes immediately to its LEFT and RIGHT (same photo, same lighting). Internally
   note their scale values as left_ref and right_ref.
3) INTERPOLATE: assign the Nikko color scale value (0-10). Use ONE DECIMAL PLACE when the
   sample falls BETWEEN the two adjacent references (e.g., 3.5 when it is halfway between
   reference 3 and 4). Base the judgment on color DARKNESS and INTENSITY only — never on
   tube position alone. Ignore glass reflections, glare, the white paper label, any
   handwriting, and the background.
4) CONFIDENCE: rate your own certainty High / Medium / Low (sharp photo + unambiguous
   adjacent match = High; blur/glare/occlusion lowers it) and express it in the numeric
   "confidence" field: High >= 85, Medium 60-84, Low < 60.

{RATING_REFERENCE}

Also estimate the deposit geometry along the sample tube (assume usable length 300mm) and approximate
CIE L*a*b* (L* lightness 0-100, a* red-green, b* yellow-blue; darker/heavier deposit = lower L*, higher a*/b*).

Return ONLY a valid minified JSON object (no markdown, no explanation) with EXACTLY these keys:
{{
 "rating": <number 0-10, ONE decimal, interpolated between the adjacent reference tubes>,
 "performance": <one of "EXCELLENT","VERY GOOD","GOOD","FAIR","POOR","VERY POOR","FAILED">,
 "confidence": <number 0-100, from the High/Medium/Low mapping above>,
 "status": <"CLEAR" or "TARNISH">,
 "deposit_level_label": <short string like "5 - 15% (Slight)">,
 "deposit_area_pct": <number>,
 "deposit_length_mm": <number>,
 "deposit_coverage_pct": <number>,
 "avg_intensity_l": <number 0-100>,
 "avg_color_a": <number>,
 "avg_color_b": <number>,
 "max_intensity": <number 0-255>,
 "thickness_index_mm": <number>,
 "deposit_start_mm": <number 0-300>,
 "deposit_end_mm": <number 0-300>,
 "summary": <one-two sentences in BAHASA INDONESIA that MUST state: the sample tube position,
   the LEFT and RIGHT adjacent reference values, the sample color description, and the resulting
   interpolated rating, e.g. "Sampel berada di antara tube referensi 6 (kiri) dan 5 (kanan); warna
   kuning-amber sedikit lebih gelap dari referensi 6, cocok rating 6.4.">,
 "recommendation": <one short sentence in BAHASA INDONESIA with a practical recommendation>
}}"""


def _is_rate_limit_error(e: Exception) -> bool:
    m = str(e).lower().replace(" ", "").replace("_", "")
    return ("ratelimit" in m) or ("429" in m) or ("toomanyrequests" in m) or ("quota" in m)


def friendly_ai_error(e: Exception) -> str:
    """Translate raw LLM errors into a short, actionable Indonesian message."""
    if _is_rate_limit_error(e):
        return "Server AI sedang sibuk (batas permintaan tercapai). Tunggu 1-2 menit lalu coba lagi."
    s = str(e)
    return s[:300]


async def _llm_send_with_retry(chat, message, attempts: int = 4, base_delay: float = 6.0):
    """Send an LLM message, retrying transient rate-limit errors with backoff."""
    for i in range(attempts):
        try:
            return await chat.send_message(message)
        except Exception as e:
            if not _is_rate_limit_error(e) or i == attempts - 1:
                raise
            wait = base_delay * (2 ** i)
            logger.warning("LLM rate-limited, retry %d/%d in %.0fs", i + 1, attempts - 1, wait)
            await asyncio.sleep(wait)



def _parse_ai_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        m = re.search(r"(\{.*\})", text, re.DOTALL)
        if m:
            text = m.group(1)
    return json.loads(text)


async def run_ai_vision(image_b64: str) -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"kht-{uuid.uuid4()}",
        system_message="You are a precise industrial machine-vision inspection model that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    ref_b64 = reference_b64()
    resp = await _llm_send_with_retry(chat, 
        UserMessage(
            text=ANALYSIS_PROMPT,
            file_contents=[ImageContent(image_base64=ref_b64), ImageContent(image_base64=image_b64)],
        )
    )
    return _parse_ai_json(resp if isinstance(resp, str) else str(resp))


def _clamp(v, lo, hi, default=0.0):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _scale_image(content: bytes, max_side: int, quality: int = 85) -> bytes:
    """Resize (max side) + re-encode as JPEG. Raises on invalid images."""
    im = PILImage.open(io.BytesIO(content))
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        # PNG/GIF transparan -> latar putih (convert langsung bikin area transparan jadi hitam)
        rgba = im.convert("RGBA")
        bg = PILImage.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    w, h = im.size
    scale = max(w, h) / float(max_side)
    if scale > 1:
        im = im.resize((int(w / scale), int(h / scale)), PILImage.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality)
    return out.getvalue()


def _downscale_for_ai(content: bytes, max_side: int = 1600) -> bytes:
    try:
        return _scale_image(content, max_side, quality=88)
    except Exception:
        logger.warning("downscale failed; sending original image")
        return content


# ---- Uploads: compress large originals so pages stay fast ------------------
# Format yang bisa dirender langsung oleh browser & mesin PDF.
_BROWSER_SAFE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


class UnsupportedImage(Exception):
    """Bytes yang diunggah bukan gambar yang bisa dibaca Pillow."""


# Aturan kompresi upload foto (berlaku untuk SEMUA modul — semua lewat /api/kht/upload):
#  - foto utama (ditampilkan, PDF): sisi terpanjang maks 1200px, JPEG quality 85, PNG -> JPEG
#  - salinan analisa tersembunyi (hanya dipakai AI Vision & crop sampel): maks 2000px, JPEG 90,
#    supaya foto multi-sampel (DKA 4 tabung, Copper batch, Salt Spray 4 plat) tetap tajam untuk AI.
UPLOAD_MAX_SIDE = 1200
UPLOAD_JPEG_QUALITY = 85
AI_MASTER_MAX_SIDE = 2000
AI_MASTER_QUALITY = 90
UPLOAD_PREFIX = f"{APP_NAME}/uploads/"
AI_MASTER_PREFIX = f"{APP_NAME}/uploads-ai/"


def _compress_upload(content: bytes, max_side: int = UPLOAD_MAX_SIDE, quality: int = UPLOAD_JPEG_QUALITY) -> bytes:
    """Selalu simpan sebagai JPEG yang valid (PNG/HEIC/WEBP dikonversi ke JPEG).

    Kegagalan decoding ditolak eksplisit (bukan disimpan mentah) supaya foto HEIC
    yang tak terbaca tidak tersimpan sebagai .jpg rusak.
    """
    try:
        return _scale_image(content, max_side, quality)
    except Exception as e:
        logger.warning("upload compression failed (%s): %s", type(e).__name__, e)
        raise UnsupportedImage(str(e)) from e


def _ai_master_path(path: str) -> Optional[str]:
    p = str(path or "")
    return AI_MASTER_PREFIX + p[len(UPLOAD_PREFIX):] if p.startswith(UPLOAD_PREFIX) else None


def get_source_object(path: str):
    """Ambil foto untuk ANALISA AI / crop sampel: pakai salinan analisa resolusi tinggi bila ada,
    fallback ke foto utama (upload lama sebelum fitur ini tidak punya salinan analisa)."""
    master = _ai_master_path(path)
    if master:
        try:
            return get_object(master)
        except Exception:
            pass
    return get_object(path)


def _store_compressed_upload(raw: bytes) -> dict:
    """Sync (threadpool): kompres + simpan foto utama dan salinan analisa. Raise UnsupportedImage."""
    display = _compress_upload(raw)
    try:
        master = _scale_image(raw, AI_MASTER_MAX_SIDE, AI_MASTER_QUALITY)
    except Exception:
        master = None
    with PILImage.open(io.BytesIO(display)) as probe:
        width, height = probe.size
    name = f"{uuid.uuid4()}.jpg"
    path = UPLOAD_PREFIX + name
    result = put_object(path, display, "image/jpeg")
    if master:
        try:
            put_object(AI_MASTER_PREFIX + name, master, "image/jpeg")
        except Exception:
            logger.warning("AI master copy upload failed; analysis will use the 1200px photo")
    return {
        "image_path": result.get("path", path),
        "original_bytes": len(raw),
        "stored_bytes": len(display),
        "width": width,
        "height": height,
        "format": "jpeg",
        "quality": UPLOAD_JPEG_QUALITY,
    }


_UNSUPPORTED_DETAIL = (
    "Format foto tidak didukung atau file rusak. Coba ambil ulang foto, atau ubah "
    "pengaturan kamera HP ke JPEG (iPhone: Settings > Camera > Formats > Most Compatible)."
)


async def _handle_upload(raw: bytes) -> dict:
    try:
        return await run_in_threadpool(_store_compressed_upload, raw)
    except UnsupportedImage:
        raise HTTPException(status_code=400, detail=_UNSUPPORTED_DETAIL)
    except Exception as e:
        logger.exception("upload failed")
        raise HTTPException(status_code=502, detail=f"Storage upload failed: {e}")


def _ensure_browser_safe(content: bytes, content_type: str) -> tuple:
    """Transcode ke JPEG bila byte tersimpan bukan format yang bisa dirender browser.

    Ini menyembuhkan foto HEIC yang sudah tersimpan sebelum perbaikan ini.
    """
    try:
        with PILImage.open(io.BytesIO(content)) as probe:
            fmt = (probe.format or "").upper()
        if fmt in _BROWSER_SAFE_FORMATS:
            return content, content_type
        return _scale_image(content, 2200, quality=88), "image/jpeg"
    except Exception:
        return content, content_type


# ---- Served-object cache: avoids re-fetching + re-scaling on every request -
# Keyed by "<path>|w<width>"; object-store paths are immutable so caching is safe.
import threading
from collections import OrderedDict

_served_cache: "OrderedDict[str, tuple[bytes, str]]" = OrderedDict()
_served_cache_lock = threading.Lock()
_SERVED_CACHE_MAX_BYTES = 96 * 1024 * 1024


def _served_cache_get(key: str):
    with _served_cache_lock:
        item = _served_cache.get(key)
        if item is not None:
            _served_cache.move_to_end(key)
        return item


def _served_cache_put(key: str, value: tuple) -> None:
    global _SERVED_CACHE_MAX_BYTES
    with _served_cache_lock:
        _served_cache[key] = value
        _served_cache.move_to_end(key)
        total = sum(len(c) for c, _ in _served_cache.values())
        while total > _SERVED_CACHE_MAX_BYTES and len(_served_cache) > 1:
            _, (c, _) = _served_cache.popitem(last=False)
            total -= len(c)


def _get_served_object(path: str, w: int) -> tuple:
    """Fetch from object store, optionally downscale to w px; LRU-cached."""
    key = f"{path}|w{w}"
    hit = _served_cache_get(key)
    if hit is not None:
        return hit
    content, content_type = get_object(path)
    if w:
        try:
            content = _scale_image(content, w, quality=82)
            content_type = "image/jpeg"
        except Exception:
            content, content_type = _ensure_browser_safe(content, content_type)
    else:
        content, content_type = _ensure_browser_safe(content, content_type)
    _served_cache_put(key, (content, content_type))
    return content, content_type


def _build_record(req: AnalyzeRequest, ai: dict) -> TestRecord:
    rating = _clamp(ai.get("rating"), 0, 10)
    params = Parameters(
        deposit_area_pct=_clamp(ai.get("deposit_area_pct"), 0, 100),
        deposit_length_mm=_clamp(ai.get("deposit_length_mm"), 0, 300),
        deposit_coverage_pct=_clamp(ai.get("deposit_coverage_pct"), 0, 100),
        avg_intensity_l=_clamp(ai.get("avg_intensity_l"), 0, 100),
        avg_color_a=_clamp(ai.get("avg_color_a"), -128, 128),
        avg_color_b=_clamp(ai.get("avg_color_b"), -128, 128),
        max_intensity=_clamp(ai.get("max_intensity"), 0, 255),
        thickness_index_mm=_clamp(ai.get("thickness_index_mm"), 0, 50),
        deposit_start_mm=_clamp(ai.get("deposit_start_mm"), 0, 300),
        deposit_end_mm=_clamp(ai.get("deposit_end_mm"), 0, 300),
    )
    meta = TestMeta(**req.model_dump(exclude={"image_path"}))
    return TestRecord(
        image_path=req.image_path,
        meta=meta,
        rating=rating,
        performance=str(ai.get("performance", "")).upper(),
        confidence=_clamp(ai.get("confidence"), 0, 100),
        status=normalize_status(ai.get("status"), rating),
        deposit_level_label=str(ai.get("deposit_level_label", "")),
        parameters=params,
        ai_summary=str(ai.get("summary", "")),
        recommendation=str(ai.get("recommendation", "")),
    )


async def _analyze_to_record(req: AnalyzeRequest) -> TestRecord:
    try:
        content, _ = await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    small = await run_in_threadpool(_downscale_for_ai, content)
    b64 = base64.b64encode(small).decode("utf-8")
    try:
        ai = await run_ai_vision(b64)
    except Exception as e:
        logger.exception("AI vision failed")
        raise HTTPException(status_code=502, detail=f"AI Vision analysis failed: {friendly_ai_error(e)}")
    record = _build_record(req, ai)
    await db.tests.insert_one(record.model_dump())
    return record


# ---- Uploads --------------------------------------------------------------
@api_router.post("/kht/upload")
async def upload_image(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="File foto kosong. Silakan pilih foto lagi.")
    return await _handle_upload(data)


_chunk_buffers: Dict[str, dict] = {}


class ChunkIn(BaseModel):
    upload_id: str
    index: int
    total: int
    data: str


class ChunkFinish(BaseModel):
    upload_id: str
    ext: str = "jpg"


@api_router.post("/kht/upload/chunk")
async def upload_chunk(c: ChunkIn):
    if c.total < 1 or c.index < 0 or c.index >= c.total:
        raise HTTPException(status_code=400, detail="Invalid chunk index")
    buf = _chunk_buffers.setdefault(c.upload_id, {"total": c.total, "parts": {}, "ts": datetime.now(timezone.utc)})
    try:
        buf["parts"][c.index] = base64.b64decode(c.data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 chunk")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    for k in [k for k, v in _chunk_buffers.items() if v["ts"] < cutoff]:
        _chunk_buffers.pop(k, None)
    return {"received": len(buf["parts"]), "total": c.total}


@api_router.post("/kht/upload/finish")
async def upload_finish(f: ChunkFinish):
    buf = _chunk_buffers.pop(f.upload_id, None)
    if not buf:
        raise HTTPException(status_code=404, detail="Upload not found")
    if len(buf["parts"]) != buf["total"]:
        raise HTTPException(status_code=400, detail=f"Missing chunks: {len(buf['parts'])}/{buf['total']}")
    data = b"".join(buf["parts"][i] for i in range(buf["total"]))
    return await _handle_upload(data)


@api_router.get("/kht/files/{path:path}")
async def serve_file(path: str, w: Optional[int] = None):
    # w = optional max-side downscale for thumbnails (?w=320). Full image when omitted.
    width = max(32, min(int(w), 2200)) if w else 0
    try:
        content, content_type = await run_in_threadpool(_get_served_object, path, width)
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")
    # UUID-based paths are immutable -> safe to cache hard in the browser
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    return Response(content=content, media_type=content_type, headers=headers)


# ---- Async analyze job flow ----------------------------------------------
class AnalyzeJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    record_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


async def _run_job(job_id: str, req: AnalyzeRequest):
    try:
        record = await _analyze_to_record(req)
        await db.analyze_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "done", "record_id": record.id, "finished_at": now_iso()}}
        )
    except HTTPException as e:
        await db.analyze_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}}
        )
    except Exception as e:
        logger.exception("analyze job failed")
        await db.analyze_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}}
        )


@api_router.post("/kht/analyze/start", response_model=AnalyzeJob)
async def analyze_start(req: AnalyzeRequest):
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = AnalyzeJob()
    await db.analyze_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_job(job.id, req))
    return job


@api_router.get("/kht/analyze/jobs/{job_id}", response_model=AnalyzeJob)
async def analyze_job_status(job_id: str):
    doc = await db.analyze_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return AnalyzeJob(**doc)


# ---- Records CRUD ---------------------------------------------------------
@api_router.get("/kht/tests", response_model=List[TestRecord])
async def list_tests(q: Optional[str] = None):
    query: dict = {"deleted_at": None}
    if q:
        query["$or"] = [
            {"meta.sample_id": {"$regex": q, "$options": "i"}},
            {"meta.oil_type": {"$regex": q, "$options": "i"}},
            {"meta.batch": {"$regex": q, "$options": "i"}},
            {"meta.operator": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.tests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [TestRecord(**d) for d in docs]


@api_router.get("/kht/tests/{test_id}", response_model=TestRecord)
async def get_test(test_id: str):
    doc = await db.tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Test not found")
    return TestRecord(**doc)


@api_router.put("/kht/tests/{test_id}", response_model=TestRecord)
async def update_test(test_id: str, upd: TestUpdate):
    doc = await db.tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Test not found")
    changes: dict = {k: v for k, v in upd.model_dump(exclude_none=True).items()}
    if "rating" in changes:
        changes["rating"] = _clamp(changes["rating"], 0, 10)
        info = nikko_level_for_rating(changes["rating"])
        if "status" not in changes:
            changes["status"] = status_for_rating(changes["rating"])
        if "performance" not in changes:
            changes["performance"] = info["grade"]
        if "deposit_level_label" not in changes:
            changes["deposit_level_label"] = info["deposit_level_label"]
    if "status" in changes and changes["status"]:
        changes["status"] = normalize_status(changes["status"], changes.get("rating", doc.get("rating", 0)))
    if not changes:
        return TestRecord(**doc)
    changes["edited"] = True
    changes["edited_at"] = now_iso()
    await db.tests.update_one({"id": test_id}, {"$set": changes})
    doc = await db.tests.find_one({"id": test_id}, {"_id": 0})
    return TestRecord(**doc)


@api_router.delete("/kht/tests/{test_id}")
async def delete_test(test_id: str):
    res = await db.tests.update_one({"id": test_id}, {"$set": {"deleted_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Test not found")
    return {"ok": True}


@api_router.get("/kht/dashboard")
async def dashboard():
    docs = await db.tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", -1).to_list(500)
    tests = [TestRecord(**d) for d in docs]
    total = len(tests)
    passed = sum(1 for t in tests if t.status == STATUS_CLEAR)
    avg_rating = round(sum(t.rating for t in tests) / total, 1) if total else 0
    return {
        "latest": tests[0].model_dump() if tests else None,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "avg_rating": avg_rating,
    }


@api_router.get("/kht/trend")
async def trend():
    docs = await db.tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", 1).to_list(500)
    tests = [TestRecord(**d) for d in docs]
    return [
        {"id": t.id, "rating": t.rating, "status": t.status, "sample_id": t.meta.sample_id, "created_at": t.created_at}
        for t in tests
    ]


@api_router.get("/kht/color-scale")
async def color_scale():
    doc = await db.reference.find_one({"key": "nikko_color_scale"}, {"_id": 0})
    if not doc:
        await seed_reference()
        doc = await db.reference.find_one({"key": "nikko_color_scale"}, {"_id": 0})
    return {
        "title": doc.get("title", "Nikko COLOR SCALE"),
        "note": doc.get("note", ""),
        "image": f"data:{doc.get('content_type', 'image/jpeg')};base64,{doc['image_base64']}",
        "levels": doc.get("levels", NIKKO_LEVELS),
        "updated_at": doc.get("updated_at"),
    }


# ===========================================================================
# ===========================================================================
# MODULE: Rating DKA — batch (up to 4 tubes / photo) + handwritten-label OCR
# ===========================================================================
# Status categories ARE the rating (no CLEAR/TARNISH pass-fail): CLEAR, Aspect 1,
# Aspect 2, Aspect 3. `severity` (0 best .. 3 worst) is used for the trend chart.
DKA_CATEGORIES = [
    {"code": "CLEAR", "color": "#E3EAEC", "severity": 0, "description": "Tabung bening/jernih tanpa endapan."},
    {"code": "Aspect 1", "color": "#C68A3E", "severity": 1, "description": "Endapan ringan, warna amber/cokelat muda."},
    {"code": "Aspect 2", "color": "#6E3B18", "severity": 2, "description": "Endapan sedang–berat, warna cokelat gelap."},
    {"code": "Aspect 3", "color": "#161616", "severity": 3, "description": "Endapan berat, warna hitam pekat."},
]
DKA_MAP = {c["code"].lower(): c for c in DKA_CATEGORIES}


def dka_category_for(v) -> dict:
    s = str(v or "").strip().lower()
    if "clear" in s or s in ("0", "c", "bening"):
        return DKA_MAP["clear"]
    for n in ("3", "2", "1"):
        if n in s:
            return DKA_MAP["aspect " + n]
    return DKA_MAP["clear"]


DKA_REF_FILE = ROOT_DIR / "reference" / "dka_standard.jpg"
_dka_ref_bytes: Optional[bytes] = None


def dka_reference_bytes() -> bytes:
    global _dka_ref_bytes
    if _dka_ref_bytes is None:
        with open(DKA_REF_FILE, "rb") as f:
            _dka_ref_bytes = f.read()
    return _dka_ref_bytes


def dka_reference_b64() -> str:
    return base64.b64encode(dka_reference_bytes()).decode("utf-8")


DKA_PROMPT = (
    "You are the RATING DKA batch inspection engine.\n\n"
    "You are given TWO images:\n"
    "1) The FIRST image is the official DKA standard reference. It shows FOUR reference tubes labelled, "
    "from left to right: 'CLEAR' (colourless clean glass), 'Aspect 1' (light amber/brown), 'Aspect 2' "
    "(dark brown), and 'Aspect 3' (black). Deposit gets darker/heavier from CLEAR to Aspect 3.\n"
    "2) The SECOND image is the operator's SAMPLE photo which may contain UP TO 4 test tubes / beakers "
    "placed side by side.\n\n"
    "For the SECOND image, do ALL of the following:\n"
    "a) Detect each individual tube separately, ordered LEFT to RIGHT (Sample 1, 2, 3, 4).\n"
    "b) OCR the HANDWRITTEN text on the white label/sticker attached to each beaker and use it as sample_id. "
    "The handwriting may be rotated 90°/180° or mirrored through the glass — mentally rotate/flip and read "
    "it anyway. If the handwriting is unreadable or there is no label, set sample_id to an empty string.\n"
    "c) Rate each tube by visually comparing its deposit colour/darkness to the FIRST (standard) image and "
    "assign exactly one of: 'CLEAR', 'Aspect 1', 'Aspect 2', 'Aspect 3'.\n"
    "d) Give a tight normalized bounding box bbox=[x,y,w,h] (each 0.0–1.0, relative to the SECOND image) that "
    "encloses that tube TOGETHER WITH its label so it can be cropped out.\n\n"
    "Return ONLY a valid minified JSON object (no markdown) shaped exactly like:\n"
    '{"samples":[{"index":1,"sample_id":"<ocr text or empty>","rating":"Aspect 2","confidence":<0-100>,'
    '"bbox":[x,y,w,h],"summary":"<one short sentence in BAHASA INDONESIA citing the observed colour>"}]}\n'
    "Include one object per detected tube (max 4), ordered left to right."
)


async def run_dka_vision(image_b64: str) -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"dka-{uuid.uuid4()}",
        system_message="You are a precise multi-object lab-tube inspection + handwriting OCR model that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    resp = await _llm_send_with_retry(chat, 
        UserMessage(
            text=DKA_PROMPT,
            file_contents=[ImageContent(image_base64=dka_reference_b64()), ImageContent(image_base64=image_b64)],
        )
    )
    return _parse_ai_json(resp if isinstance(resp, str) else str(resp))


def _crop_bbox(content: bytes, bbox, pad: float = 0.02) -> bytes:
    im = PILImage.open(io.BytesIO(content))
    im = ImageOps.exif_transpose(im).convert("RGB")
    W, H = im.size
    x, y, w, h = [float(v) for v in bbox]
    x0 = int(max(0.0, x - pad) * W)
    y0 = int(max(0.0, y - pad) * H)
    x1 = int(min(1.0, x + w + pad) * W)
    y1 = int(min(1.0, y + h + pad) * H)
    if x1 - x0 < 8 or y1 - y0 < 8:
        raise ValueError("bbox too small")
    out = io.BytesIO()
    im.crop((x0, y0, x1, y1)).save(out, "JPEG", quality=92)
    return out.getvalue()


def _crop_column(content: bytes, i: int, n: int) -> bytes:
    im = PILImage.open(io.BytesIO(content))
    im = ImageOps.exif_transpose(im).convert("RGB")
    W, H = im.size
    n = max(1, n)
    left = int(W * i / n)
    right = int(W * (i + 1) / n)
    out = io.BytesIO()
    im.crop((left, 0, right, H)).save(out, "JPEG", quality=92)
    return out.getvalue()


def _dka_build_samples(content: bytes, raw: list) -> list:
    """Sync (runs in threadpool): crop each detected tube from the ORIGINAL
    full-res photo and upload the crop, returning sample dicts."""
    def bx(s):
        try:
            return float(s.get("bbox", [0, 0, 0, 0])[0])
        except Exception:
            return 0.0

    ordered = sorted(raw, key=bx) if raw else [{}]
    ordered = ordered[:4] if len(ordered) > 4 else ordered
    n = len(ordered)
    samples = []
    for i, s in enumerate(ordered):
        cat = dka_category_for(s.get("rating"))
        try:
            crop_bytes = _crop_bbox(content, s.get("bbox"))
        except Exception:
            try:
                crop_bytes = _crop_column(content, i, n)
            except Exception:
                crop_bytes = None
        crop_path = ""
        if crop_bytes:
            try:
                cp = f"{APP_NAME}/dka/{uuid.uuid4()}.jpg"
                put_object(cp, crop_bytes, "image/jpeg")
                crop_path = cp
            except Exception:
                crop_path = ""
        sid = str(s.get("sample_id", "")).strip() or f"Unknown {i + 1}"
        samples.append({
            "index": i + 1, "sample_id": sid, "rating": cat["code"], "severity": cat["severity"],
            "color": cat["color"], "description": cat["description"],
            "confidence": _clamp(s.get("confidence"), 0, 100), "summary": str(s.get("summary", "")),
            "crop_path": crop_path,
        })
    return samples


class DkaMeta(BaseModel):
    batch_id: str = ""
    product: str = ""
    operator: str = ""
    temperature_c: float = 320
    duration_hours: float = 16
    remark: str = ""


class DkaSample(BaseModel):
    index: int = 1
    sample_id: str = ""
    rating: str = "CLEAR"
    severity: float = 0
    color: str = "#E3EAEC"
    description: str = ""
    confidence: float = 0
    summary: str = ""
    crop_path: str = ""


class DkaAnalyzeRequest(DkaMeta):
    image_path: str


class DkaRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    image_path: str
    meta: DkaMeta
    samples: List[DkaSample] = Field(default_factory=list)
    sample_count: int = 0
    ai_model: str = "gemini-3.1-pro-preview"
    created_at: str = Field(default_factory=now_iso)
    edited: bool = False
    edited_at: Optional[str] = None
    deleted_at: Optional[str] = None


class DkaSampleUpdate(BaseModel):
    index: int
    sample_id: Optional[str] = None
    rating: Optional[str] = None


class DkaUpdate(BaseModel):
    samples: Optional[List[DkaSampleUpdate]] = None


async def _analyze_dka(req: DkaAnalyzeRequest) -> DkaRecord:
    try:
        content, _ = await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    small = await run_in_threadpool(_downscale_for_ai, content, 2200)
    b64 = base64.b64encode(small).decode("utf-8")
    try:
        ai = await run_dka_vision(b64)
    except Exception as e:
        logger.exception("DKA AI vision failed")
        raise HTTPException(status_code=502, detail=f"AI Vision analysis failed: {friendly_ai_error(e)}")
    raw = ai.get("samples") if isinstance(ai, dict) else None
    sample_dicts = await run_in_threadpool(_dka_build_samples, content, raw or [])
    record = DkaRecord(
        image_path=req.image_path,
        meta=DkaMeta(**req.model_dump(exclude={"image_path"})),
        samples=[DkaSample(**s) for s in sample_dicts],
        sample_count=len(sample_dicts),
    )
    await db.dka_tests.insert_one(record.model_dump())
    return record


class DkaJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    record_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


async def _run_dka_job(job_id: str, req: DkaAnalyzeRequest):
    try:
        record = await _analyze_dka(req)
        await db.dka_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "done", "record_id": record.id, "finished_at": now_iso()}}
        )
    except HTTPException as e:
        await db.dka_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}}
        )
    except Exception as e:
        logger.exception("dka analyze job failed")
        await db.dka_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}}
        )


@api_router.post("/dka/analyze/start", response_model=DkaJob)
async def dka_analyze_start(req: DkaAnalyzeRequest):
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = DkaJob()
    await db.dka_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_dka_job(job.id, req))
    return job


@api_router.get("/dka/analyze/jobs/{job_id}", response_model=DkaJob)
async def dka_job_status(job_id: str):
    doc = await db.dka_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return DkaJob(**doc)


@api_router.get("/dka/tests", response_model=List[DkaRecord])
async def dka_list(q: Optional[str] = None):
    query: dict = {"deleted_at": None}
    if q:
        query["$or"] = [
            {"meta.batch_id": {"$regex": q, "$options": "i"}},
            {"meta.product": {"$regex": q, "$options": "i"}},
            {"meta.operator": {"$regex": q, "$options": "i"}},
            {"samples.sample_id": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.dka_tests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [DkaRecord(**d) for d in docs]


@api_router.get("/dka/tests/{test_id}", response_model=DkaRecord)
async def dka_get(test_id: str):
    doc = await db.dka_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Test not found")
    return DkaRecord(**doc)


@api_router.put("/dka/tests/{test_id}", response_model=DkaRecord)
async def dka_update(test_id: str, upd: DkaUpdate):
    doc = await db.dka_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Test not found")
    record = DkaRecord(**doc)
    if upd.samples:
        by_index = {s.index: s for s in record.samples}
        for change in upd.samples:
            s = by_index.get(change.index)
            if not s:
                continue
            if change.sample_id is not None:
                s.sample_id = change.sample_id.strip() or s.sample_id
            if change.rating is not None:
                cat = dka_category_for(change.rating)
                s.rating = cat["code"]
                s.severity = cat["severity"]
                s.color = cat["color"]
                s.description = cat["description"]
    await db.dka_tests.update_one(
        {"id": test_id},
        {"$set": {"samples": [s.model_dump() for s in record.samples], "edited": True, "edited_at": now_iso()}},
    )
    doc = await db.dka_tests.find_one({"id": test_id}, {"_id": 0})
    return DkaRecord(**doc)


@api_router.delete("/dka/tests/{test_id}")
async def dka_delete(test_id: str):
    res = await db.dka_tests.update_one({"id": test_id}, {"$set": {"deleted_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Test not found")
    return {"ok": True}


@api_router.get("/dka/dashboard")
async def dka_dashboard():
    docs = await db.dka_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", -1).to_list(500)
    records = [DkaRecord(**d) for d in docs]
    dist = {c["code"]: 0 for c in DKA_CATEGORIES}
    total_samples = 0
    for r in records:
        for s in r.samples:
            total_samples += 1
            if s.rating in dist:
                dist[s.rating] += 1
    return {
        "latest": records[0].model_dump() if records else None,
        "total_batches": len(records),
        "total_samples": total_samples,
        "distribution": dist,
    }


@api_router.get("/dka/trend")
async def dka_trend():
    docs = await db.dka_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", 1).to_list(500)
    records = [DkaRecord(**d) for d in docs]
    out = []
    for r in records:
        sev = [s.severity for s in r.samples]
        avg = round(sum(sev) / len(sev), 2) if sev else 0
        out.append({
            "id": r.id, "batch_id": r.meta.batch_id or r.id[:8], "avg_severity": avg,
            "count": len(r.samples), "created_at": r.created_at,
        })
    return out


@api_router.get("/dka/reference-scale")
async def dka_reference_scale():
    doc = await db.reference.find_one({"key": "dka_standard"}, {"_id": 0})
    if not doc:
        await seed_dka_reference()
        doc = await db.reference.find_one({"key": "dka_standard"}, {"_id": 0})
    return {
        "title": doc.get("title", "DKA Standard"),
        "note": doc.get("note", ""),
        "image": f"data:{doc.get('content_type', 'image/jpeg')};base64,{doc['image_base64']}",
        "categories": doc.get("categories", DKA_CATEGORIES),
        "updated_at": doc.get("updated_at"),
    }


async def seed_dka_reference():
    try:
        doc = {
            "key": "dka_standard",
            "title": "DKA Standard Reference",
            "note": "Kategori (kiri→kanan): CLEAR · Aspect 1 · Aspect 2 · Aspect 3. Status hasil memakai nama kategori langsung.",
            "content_type": "image/jpeg",
            "image_base64": dka_reference_b64(),
            "categories": DKA_CATEGORIES,
            "updated_at": now_iso(),
        }
        await db.reference.replace_one({"key": "dka_standard"}, doc, upsert=True)
    except Exception as e:
        logger.warning("seed_dka_reference failed: %s", e)


async def seed_dka():
    if await db.dka_tests.count_documents({}) > 0:
        return
    logger.info("Seeding demo DKA batch...")
    try:
        content = dka_reference_bytes()
    except Exception as e:
        logger.warning("DKA seed skipped (no reference image): %s", e)
        return
    ids = ["DKA-2026-001", "DKA-2026-002", "DKA-2026-003", "DKA-2026-004"]
    summaries = [
        "Tabung bening tanpa endapan, cocok dengan kategori CLEAR.",
        "Endapan ringan warna amber muda, cocok dengan Aspect 1.",
        "Endapan cokelat gelap cukup tebal, cocok dengan Aspect 2.",
        "Endapan hitam pekat menutupi tabung, cocok dengan Aspect 3.",
    ]

    def _seed_crop(i):
        try:
            crop_bytes = _crop_column(content, i, 4)
            cp = f"{APP_NAME}/dka/{uuid.uuid4()}.jpg"
            put_object(cp, crop_bytes, "image/jpeg")
            return cp
        except Exception:
            return ""

    # Pre-crop the 4 category columns once and reuse across demo batches.
    crop_paths = []
    for i in range(len(DKA_CATEGORIES)):
        crop_paths.append(await run_in_threadpool(_seed_crop, i))

    # Upload the full reference photo once as the shared batch image.
    try:
        full_path = f"{APP_NAME}/dka/{uuid.uuid4()}.jpg"
        await run_in_threadpool(put_object, full_path, content, "image/jpeg")
    except Exception:
        full_path = ""

    # Several demo batches across different dates/products for a fuller dashboard,
    # trend and history. Each batch picks a subset of categories.
    batches = [
        {"batch_id": "DKA-DEMO-0530", "product": "Engine Oil SAE 15W-40", "operator": "Karis Setia", "days": 0,  "cats": [0, 1, 2, 3]},
        {"batch_id": "DKA-DEMO-0527", "product": "Diesel Fuel B30",       "operator": "Dwi Agus",    "days": 3,  "cats": [0, 1, 1, 2]},
        {"batch_id": "DKA-DEMO-0524", "product": "Hydraulic Oil HO-46",   "operator": "Rina Pertiwi","days": 6,  "cats": [1, 2, 2, 3]},
        {"batch_id": "DKA-DEMO-0521", "product": "Engine Oil SAE 10W-30", "operator": "Karis Setia", "days": 9,  "cats": [0, 0, 1, 2]},
        {"batch_id": "DKA-DEMO-0518", "product": "Gear Oil GL-5 85W-140", "operator": "Dwi Agus",    "days": 12, "cats": [2, 3, 3, 3]},
    ]
    base = datetime.now(timezone.utc)
    for b in batches:
        samples = []
        for slot, ci in enumerate(b["cats"]):
            cat = DKA_CATEGORIES[ci]
            samples.append(DkaSample(
                index=slot + 1, sample_id=f"{b['batch_id']}-{slot + 1:02d}",
                rating=cat["code"], severity=cat["severity"], color=cat["color"],
                description=cat["description"], confidence=96 - slot, summary=summaries[ci],
                crop_path=crop_paths[ci] if ci < len(crop_paths) else "",
            ))
        rec = DkaRecord(
            image_path=full_path,
            meta=DkaMeta(batch_id=b["batch_id"], product=b["product"], operator=b["operator"],
                         temperature_c=320, duration_hours=16),
            samples=samples, sample_count=len(samples),
        )
        rec_dict = rec.model_dump()
        rec_dict["created_at"] = (base - timedelta(days=b["days"])).isoformat()
        await db.dka_tests.insert_one(rec_dict)


# ===========================================================================
# MODULE: Copper Strip Corrosion — ASTM D130 / IP 154
# ===========================================================================
# Classification (best -> worst). CLEAR (pass) = Freshly Polished / 1a / 1b;
# everything from 2a onwards = TARNISH. `severity` (0 best .. 12 worst) is used
# for the trend chart. Colours approximate each standard descriptor.
ASTM_D130_CLASSES = [
    {"code": "0", "label": "Freshly Polished", "group": "Freshly Polished", "color": "#E8955A", "description": "Freshly polished copper strip — bright salmon/copper colour, no tarnish.", "severity": 0, "status": "CLEAR"},
    {"code": "1a", "label": "Slight Tarnish", "group": "Slight Tarnish", "color": "#EFB07A", "description": "Light orange, almost the same as a freshly polished strip.", "severity": 1, "status": "CLEAR"},
    {"code": "1b", "label": "Slight Tarnish", "group": "Slight Tarnish", "color": "#D6822F", "description": "Dark orange.", "severity": 2, "status": "CLEAR"},
    {"code": "2a", "label": "Moderate Tarnish", "group": "Moderate Tarnish", "color": "#A83B4B", "description": "Claret red.", "severity": 3, "status": "TARNISH"},
    {"code": "2b", "label": "Moderate Tarnish", "group": "Moderate Tarnish", "color": "#B98FBE", "description": "Lavender.", "severity": 4, "status": "TARNISH"},
    {"code": "2c", "label": "Moderate Tarnish", "group": "Moderate Tarnish", "color": "#9C6FA6", "description": "Multicoloured with lavender blue and/or silver overlaid on claret red.", "severity": 5, "status": "TARNISH"},
    {"code": "2d", "label": "Moderate Tarnish", "group": "Moderate Tarnish", "color": "#BFBFBF", "description": "Silvery.", "severity": 6, "status": "TARNISH"},
    {"code": "3a", "label": "Moderate Tarnish", "group": "Moderate Tarnish", "color": "#9C3A6B", "description": "Magenta overcast on a brassy/gold strip.", "severity": 7, "status": "TARNISH"},
    {"code": "3b", "label": "Dark Tarnish", "group": "Dark Tarnish", "color": "#3E7D6B", "description": "Multicoloured with red and green (peacock), but no grey.", "severity": 8, "status": "TARNISH"},
    {"code": "3c", "label": "Dark Tarnish", "group": "Dark Tarnish", "color": "#2E5A4E", "description": "Dark peacock / greenish tarnish.", "severity": 9, "status": "TARNISH"},
    {"code": "4a", "label": "Corrosion", "group": "Corrosion", "color": "#4A4A4A", "description": "Transparent black, dark grey or brown with peacock green barely showing.", "severity": 10, "status": "TARNISH"},
    {"code": "4b", "label": "Corrosion", "group": "Corrosion", "color": "#2B2B2B", "description": "Graphite or lusterless black.", "severity": 11, "status": "TARNISH"},
    {"code": "4c", "label": "Corrosion", "group": "Corrosion", "color": "#141414", "description": "Glossy or jet black.", "severity": 12, "status": "TARNISH"},
]
COPPER_CLASS_MAP = {c["code"]: c for c in ASTM_D130_CLASSES}
COPPER_CLEAR_CODES = {"0", "1a", "1b"}


def copper_class_for(code) -> dict:
    c = COPPER_CLASS_MAP.get(str(code or "").strip().lower())
    return c or COPPER_CLASS_MAP["2a"]


def _copper_hex(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def generate_copper_reference() -> bytes:
    """Render an ASTM D130 / IP 154 copper-strip standard chart (used both as
    the on-screen reference and as the AI comparison image)."""
    classes = ASTM_D130_CLASSES
    n = len(classes)
    margin, gap, strip_w, strip_h, top = 40, 12, 66, 300, 120
    width = margin * 2 + n * strip_w + (n - 1) * gap
    height = top + strip_h + 130
    img = PILImage.new("RGB", (width, height), (244, 241, 236))
    d = ImageDraw.Draw(img)

    def font(sz):
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", sz)
        except Exception:
            try:
                return ImageFont.load_default(sz)
            except Exception:
                return ImageFont.load_default()

    def ctext(cx, y, txt, fnt, fill):
        try:
            w = d.textlength(txt, font=fnt)
        except Exception:
            w = len(txt) * 12 * 0.6
        d.text((cx - w / 2, y), txt, font=fnt, fill=fill)

    d.text((margin, 28), "ASTM COPPER STRIP CORROSION STANDARDS", font=font(30), fill=(20, 20, 20))
    d.text((margin, 68), "ASTM METHOD D 130 / IP 154", font=font(20), fill=(90, 90, 90))

    x = margin
    for c in classes:
        rgb = _copper_hex(c["color"])
        for i in range(strip_h):
            f = 1.0 - (i / strip_h) * 0.22
            shade = tuple(max(0, min(255, int(v * f))) for v in rgb)
            d.line([(x, top + i), (x + strip_w, top + i)], fill=shade)
        d.rectangle([x, top, x + strip_w, top + strip_h], outline=(40, 40, 40), width=2)
        cx = x + strip_w / 2
        ctext(cx, top + strip_h + 12, c["code"].upper(), font(22), (17, 17, 17))
        ctext(cx, top + strip_h + 44, "PASS" if c["code"] in COPPER_CLEAR_CODES else "TARNISH",
              font(13), (21, 128, 61) if c["code"] in COPPER_CLEAR_CODES else (193, 34, 14))
        x += strip_w + gap

    d.text((margin, height - 34),
           "Freshly Polished  |  1a-1b Slight  |  2a-3a Moderate  |  3b-3c Dark  |  4a-4c Corrosion",
           font=font(16), fill=(70, 70, 70))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


_copper_ref_bytes: Optional[bytes] = None
COPPER_REF_FILE = ROOT_DIR / "reference" / "astm_d130.jpg"


def copper_reference_bytes() -> bytes:
    """Prefer the bundled official ASTM D130 / IP 154 chart photo; fall back to
    the generated chart only if the file is missing."""
    global _copper_ref_bytes
    if _copper_ref_bytes is None:
        if COPPER_REF_FILE.exists():
            with open(COPPER_REF_FILE, "rb") as f:
                _copper_ref_bytes = f.read()
        else:
            _copper_ref_bytes = generate_copper_reference()
    return _copper_ref_bytes


def copper_reference_b64() -> str:
    return base64.b64encode(copper_reference_bytes()).decode("utf-8")


_COPPER_CLASS_TEXT = "\n".join(
    f'  "{c["code"]}" = {c["group"]}: {c["description"]}' for c in ASTM_D130_CLASSES
)

COPPER_PROMPT = (
    "You are an ASTM D130 / IP 154 Copper Strip Corrosion rating engine.\n\n"
    "You are given TWO images:\n"
    "1) The FIRST image is the official ASTM D130 / IP 154 copper strip corrosion STANDARD chart. "
    "It shows the reference strips from Freshly Polished (brightest copper) through increasing tarnish "
    "(orange -> red -> lavender -> silvery -> magenta -> peacock green) to Corrosion (black).\n"
    "2) The SECOND image is the operator's SAMPLE copper strip that you must rate.\n\n"
    "Visually COMPARE the colour/tarnish of the SAMPLE strip against the standard strips and pick the "
    "classification whose appearance it most closely matches. Ignore glare, reflections and background.\n\n"
    "Allowed classifications (code = group: description):\n"
    + _COPPER_CLASS_TEXT +
    "\n\nStatus rule: CLEAR when classification is 0, 1a or 1b; otherwise TARNISH.\n\n"
    "Return ONLY a valid minified JSON object (no markdown) with EXACTLY these keys:\n"
    '{"classification": <one of the codes above, e.g. "1b">, '
    '"confidence": <number 0-100>, '
    '"status": <"CLEAR" or "TARNISH">, '
    '"summary": <one short sentence in BAHASA INDONESIA justifying the class by citing the observed colour, '
    'e.g. "Warna oranye gelap pada strip cocok dengan kelas 1b (slight tarnish).">, '
    '"recommendation": <one short sentence in BAHASA INDONESIA with a practical recommendation>}'
)


async def run_copper_vision(image_b64: str) -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"copper-{uuid.uuid4()}",
        system_message="You are a precise ASTM D130 copper-strip corrosion inspection model that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    ref_b64 = copper_reference_b64()
    resp = await _llm_send_with_retry(chat, 
        UserMessage(
            text=COPPER_PROMPT,
            file_contents=[ImageContent(image_base64=ref_b64), ImageContent(image_base64=image_b64)],
        )
    )
    return _parse_ai_json(resp if isinstance(resp, str) else str(resp))


_COPPER_BOX_RULE = (
    '"box_2d":[ymin,xmin,ymax,xmax] (integers 0-1000 relative to the operator photo) that encloses ONLY that ONE '
    "copper strip (plus its own label if attached). Each box must contain exactly one strip: never include any "
    "part of a neighbouring strip, and boxes of different strips must not overlap. "
)


def _copper_norm_samples(ai: dict) -> dict:
    """Convert Gemini box_2d [ymin,xmin,ymax,xmax] (0-1000) to bbox [x,y,w,h] (0-1)."""
    for smp in (ai or {}).get("samples") or []:
        b = smp.get("box_2d")
        try:
            y0, x0, y1, x1 = [max(0.0, min(1000.0, float(v))) / 1000 for v in b]
            if x1 > x0 and y1 > y0:
                smp["bbox"] = [x0, y0, x1 - x0, y1 - y0]
        except Exception:
            pass
    return ai


COPPER_BATCH_PROMPT = (
    "You are an ASTM D130 / IP 154 Copper Strip Corrosion batch inspection engine.\n\n"
    "You are given TWO images:\n"
    "1) The FIRST image is the official ASTM D130 / IP 154 reference chart with 13 allowed classes.\n"
    "2) The SECOND image is one operator photo containing up to FOUR tested copper strips.\n\n"
    "Analyze the SECOND image as a batch. Detect each tested strip separately, including its handwritten label. "
    "The strips may be arranged horizontally, vertically, or in a mixed layout. Order them top-to-bottom and "
    "left-to-right (reading order). For every detected strip: OCR the handwritten label exactly as visible, "
    "rate its tarnish appearance against the FIRST reference chart, and provide a tight bounding box "
    + _COPPER_BOX_RULE
    + "Mentally rotate or flip labels when needed. Ignore glare, reflections, and background.\n\n"
    "Allowed classifications (code = group: description):\n"
    + _COPPER_CLASS_TEXT
    + "\nStatus rule: CLEAR for 0, 1a, 1b; TARNISH for all other classes.\n\n"
    "Return ONLY valid minified JSON with exactly this shape:\n"
    '{"samples":[{"index":1,"sample_id":"<OCR label or empty>",'
    '"classification":"1b","confidence":<0-100>,"box_2d":[ymin,xmin,ymax,xmax],'
    '"summary":"<short Bahasa Indonesia sentence citing observed colour>",'
    '"recommendation":"<short practical Bahasa Indonesia recommendation>"}]}\n'
    "Include one object per detected strip, maximum four, in reading order."
)


async def run_copper_batch_vision(image_b64: str) -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"copper-batch-{uuid.uuid4()}",
        system_message="You are a precise multi-sample ASTM D130 inspection and handwriting OCR model that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    resp = await _llm_send_with_retry(
        chat,
        UserMessage(
            text=COPPER_BATCH_PROMPT,
            file_contents=[ImageContent(image_base64=copper_reference_b64()), ImageContent(image_base64=image_b64)],
        ),
    )
    return _copper_norm_samples(_parse_ai_json(resp if isinstance(resp, str) else str(resp)))



COPPER_BATCH_OCR_PROMPT = (
    "You are a handwriting OCR assistant for an ASTM D130 copper-strip test.\n"
    "The image contains up to FOUR tested copper strips arranged horizontally, vertically, or in a mixed layout. "
    "Detect each strip and read the handwritten label attached to that strip. Order samples top-to-bottom and "
    "left-to-right. Mentally rotate or flip labels when needed. Return the exact label text, an OCR confidence, "
    "and a tight bounding box " + _COPPER_BOX_RULE + "If a label cannot be read, use an empty "
    "sample_id. Return ONLY valid minified JSON: "
    '{"samples":[{"index":1,"sample_id":"<OCR text or empty>","confidence":<0-100>,"box_2d":[ymin,xmin,ymax,xmax]}]}'
)


async def run_copper_batch_ocr(image_b64: str) -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"copper-batch-ocr-{uuid.uuid4()}",
        system_message="You are a precise multi-sample handwritten-label OCR model that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    resp = await _llm_send_with_retry(
        chat,
        UserMessage(text=COPPER_BATCH_OCR_PROMPT, file_contents=[ImageContent(image_base64=image_b64)]),
    )
    return _copper_norm_samples(_parse_ai_json(resp if isinstance(resp, str) else str(resp)))

class CopperMeta(BaseModel):
    sample_id: str = ""
    product: str = ""
    batch: str = ""
    operator: str = ""
    temperature_c: float = 100
    duration_hours: float = 3
    remark: str = ""


class CopperBatchOcrRequest(BaseModel):
    image_path: str


class CopperBatchOcrJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    samples: List[dict] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


class CopperAnalyzeRequest(CopperMeta):
    image_path: str


class CopperBatchAnalyzeRequest(CopperMeta):
    image_path: str
    batch_id: str = ""
    sample_ids: List[str] = Field(default_factory=list)


class CopperRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    image_path: str
    batch_id: Optional[str] = None
    sample_index: Optional[int] = None
    crop_path: str = ""
    bbox: Optional[List[float]] = None
    meta: CopperMeta
    classification: str = "1a"
    class_label: str = ""
    group: str = ""
    color: str = "#E8955A"
    description: str = ""
    severity: float = 0
    confidence: float = 0
    status: str = "CLEAR"
    ai_summary: str = ""
    recommendation: str = ""
    ai_model: str = "gemini-3.1-pro-preview"
    created_at: str = Field(default_factory=now_iso)
    edited: bool = False
    edited_at: Optional[str] = None
    deleted_at: Optional[str] = None


class CopperUpdate(BaseModel):
    sample_id: Optional[str] = None
    classification: Optional[str] = None
    status: Optional[str] = None
    ai_summary: Optional[str] = None
    recommendation: Optional[str] = None


def _build_copper_record(req: CopperAnalyzeRequest, ai: dict) -> CopperRecord:
    cls = copper_class_for(ai.get("classification"))
    meta = CopperMeta(**req.model_dump(exclude={"image_path"}))
    return CopperRecord(
        image_path=req.image_path,
        meta=meta,
        classification=cls["code"],
        class_label=cls["label"],
        group=cls["group"],
        color=cls["color"],
        description=cls["description"],
        severity=cls["severity"],
        confidence=_clamp(ai.get("confidence"), 0, 100),
        status=cls["status"],
        ai_summary=str(ai.get("summary", "")),
        recommendation=str(ai.get("recommendation", "")),
    )


async def _analyze_copper(req: CopperAnalyzeRequest) -> CopperRecord:
    try:
        content, _ = await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    small = await run_in_threadpool(_downscale_for_ai, content)
    b64 = base64.b64encode(small).decode("utf-8")
    try:
        ai = await run_copper_vision(b64)
    except Exception as e:
        logger.exception("Copper AI vision failed")
        raise HTTPException(status_code=502, detail=f"AI Vision analysis failed: {friendly_ai_error(e)}")
    record = _build_copper_record(req, ai)
    await db.copper_tests.insert_one(record.model_dump())
    return record



def _copper_batch_sort_key(sample: dict):
    bbox = sample.get("bbox") or [0, 0, 0, 0]
    try:
        x, y = float(bbox[0]), float(bbox[1])
    except Exception:
        x, y = 0.0, 0.0
    # Reading order supports a horizontal row, a vertical column, or a 2x2 layout.
    return (round(y / 0.22), x)


def _build_copper_batch_records(content: bytes, raw: list, req: CopperBatchAnalyzeRequest, batch_id: str) -> list:
    ordered = sorted(raw or [], key=_copper_batch_sort_key)[:4]
    if not ordered:
        raise ValueError("AI tidak menemukan sample copper strip pada foto")
    meta_common = req.model_dump(exclude={"image_path", "batch_id", "sample_ids"})
    overrides = req.sample_ids or []
    records = []
    for i, sample in enumerate(ordered):
        cls = copper_class_for(sample.get("classification"))
        try:
            crop_bytes = _crop_bbox(content, sample.get("bbox"), pad=0.008)
            bx, by, bw, bh = [float(v) for v in sample["bbox"]]
            bbox = [max(0.0, bx - 0.008), max(0.0, by - 0.008), bw + 0.016, bh + 0.016]
        except Exception:
            crop_bytes = _crop_column(content, i, len(ordered))
            bbox = [i / len(ordered), 0.0, 1 / len(ordered), 1.0]
        crop_path = ""
        try:
            crop_path = f"{APP_NAME}/copper/batches/{batch_id}/{uuid.uuid4()}.jpg"
            put_object(crop_path, crop_bytes, "image/jpeg")
        except Exception:
            logger.warning("Could not store copper batch crop", exc_info=True)
            crop_path = ""
        override_id = str(overrides[i] if i < len(overrides) else "").strip()
        sample_id = override_id or str(sample.get("sample_id") or "").strip() or f"Unknown {i + 1}"
        meta = CopperMeta(**{**meta_common, "sample_id": sample_id})
        records.append(
            CopperRecord(
                image_path=req.image_path,
                batch_id=batch_id,
                sample_index=i + 1,
                crop_path=crop_path,
                bbox=bbox,
                meta=meta,
                classification=cls["code"],
                class_label=cls["label"],
                group=cls["group"],
                color=cls["color"],
                description=cls["description"],
                severity=cls["severity"],
                confidence=_clamp(sample.get("confidence"), 0, 100),
                status=cls["status"],
                ai_summary=str(sample.get("summary", "")),
                recommendation=str(sample.get("recommendation", "")),
            )
        )
    return records


async def _analyze_copper_batch(req: CopperBatchAnalyzeRequest, batch_id: str) -> list:
    try:
        content, _ = await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    small = await run_in_threadpool(_downscale_for_ai, content, 2200)
    b64 = base64.b64encode(small).decode("utf-8")
    try:
        ai = await run_copper_batch_vision(b64)
        raw = ai.get("samples") if isinstance(ai, dict) else None
        records = await run_in_threadpool(_build_copper_batch_records, content, raw or [], req, batch_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Copper batch AI vision failed")
        raise HTTPException(status_code=502, detail=f"AI Vision batch analysis failed: {friendly_ai_error(e)}")
    await db.copper_tests.insert_many([record.model_dump() for record in records])
    return records


class CopperBatchJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    batch_id: str
    status: str = "running"
    record_ids: List[str] = Field(default_factory=list)
    detected_count: int = 0
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


async def _run_copper_batch_job(job_id: str, batch_id: str, req: CopperBatchAnalyzeRequest):
    try:
        records = await _analyze_copper_batch(req, batch_id)
        await db.copper_batch_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "done", "record_ids": [r.id for r in records], "detected_count": len(records), "finished_at": now_iso()}},
        )
    except HTTPException as e:
        await db.copper_batch_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}},
        )
    except Exception as e:
        logger.exception("copper batch analyze job failed")
        await db.copper_batch_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}},
        )



async def _run_copper_batch_ocr_job(job_id: str, image_path: str):
    try:
        content, _ = await run_in_threadpool(get_source_object, image_path)
        small = await run_in_threadpool(_downscale_for_ai, content, 2200)
        b64 = base64.b64encode(small).decode("utf-8")
        ai = await run_copper_batch_ocr(b64)
        raw = ai.get("samples") if isinstance(ai, dict) else []
        samples = []
        for i, sample in enumerate(sorted(raw or [], key=_copper_batch_sort_key)[:4]):
            samples.append({
                "index": i + 1,
                "sample_id": str(sample.get("sample_id") or "").strip(),
                "confidence": _clamp(sample.get("confidence"), 0, 100),
                "bbox": sample.get("bbox") or [],
            })
        await db.copper_batch_ocr_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "done", "samples": samples, "finished_at": now_iso()}},
        )
    except HTTPException as e:
        await db.copper_batch_ocr_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}},
        )
    except Exception as e:
        logger.exception("copper batch OCR job failed")
        await db.copper_batch_ocr_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}},
        )
class CopperJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    record_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


async def _run_copper_job(job_id: str, req: CopperAnalyzeRequest):
    try:
        record = await _analyze_copper(req)
        await db.copper_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "done", "record_id": record.id, "finished_at": now_iso()}}
        )
    except HTTPException as e:
        await db.copper_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}}
        )
    except Exception as e:
        logger.exception("copper analyze job failed")
        await db.copper_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}}
        )


@api_router.post("/copper/analyze/start", response_model=CopperJob)
async def copper_analyze_start(req: CopperAnalyzeRequest):
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = CopperJob()
    await db.copper_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_copper_job(job.id, req))
    return job


@api_router.get("/copper/analyze/jobs/{job_id}", response_model=CopperJob)
async def copper_job_status(job_id: str):
    doc = await db.copper_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return CopperJob(**doc)



@api_router.post("/copper/batch/analyze/start", response_model=CopperBatchJob)
async def copper_batch_analyze_start(req: CopperBatchAnalyzeRequest):
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    batch_id = req.batch_id.strip() or f"CU-BATCH-{uuid.uuid4().hex[:8].upper()}"
    job = CopperBatchJob(batch_id=batch_id)
    await db.copper_batch_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_copper_batch_job(job.id, batch_id, req))
    return job


@api_router.get("/copper/batch/analyze/jobs/{job_id}", response_model=CopperBatchJob)
async def copper_batch_job_status(job_id: str):
    doc = await db.copper_batch_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Batch job not found")
    return CopperBatchJob(**doc)


@api_router.post("/copper/batch/ocr/start", response_model=CopperBatchOcrJob)
async def copper_batch_ocr_start(req: CopperBatchOcrRequest):
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = CopperBatchOcrJob()
    await db.copper_batch_ocr_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_copper_batch_ocr_job(job.id, req.image_path))
    return job


@api_router.get("/copper/batch/ocr/jobs/{job_id}", response_model=CopperBatchOcrJob)
async def copper_batch_ocr_status(job_id: str):
    doc = await db.copper_batch_ocr_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Batch OCR job not found")
    return CopperBatchOcrJob(**doc)


@api_router.get("/copper/batches/{batch_id}", response_model=List[CopperRecord])
async def copper_batch_get(batch_id: str):
    docs = await db.copper_tests.find({"batch_id": batch_id, "deleted_at": None}, {"_id": 0}).sort("sample_index", 1).to_list(4)
    if not docs:
        raise HTTPException(status_code=404, detail="Copper batch not found")
    return [CopperRecord(**d) for d in docs]


@api_router.delete("/copper/batches/{batch_id}")
async def copper_batch_delete(batch_id: str):
    res = await db.copper_tests.update_many({"batch_id": batch_id, "deleted_at": None}, {"$set": {"deleted_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Copper batch not found")
    return {"ok": True, "deleted": res.modified_count}

@api_router.get("/copper/tests", response_model=List[CopperRecord])
async def copper_list(q: Optional[str] = None):
    query: dict = {"deleted_at": None}
    if q:
        query["$or"] = [
            {"meta.sample_id": {"$regex": q, "$options": "i"}},
            {"meta.product": {"$regex": q, "$options": "i"}},
            {"meta.batch": {"$regex": q, "$options": "i"}},
            {"meta.operator": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.copper_tests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [CopperRecord(**d) for d in docs]


@api_router.get("/copper/tests/{test_id}", response_model=CopperRecord)
async def copper_get(test_id: str):
    doc = await db.copper_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Test not found")
    return CopperRecord(**doc)


@api_router.put("/copper/tests/{test_id}", response_model=CopperRecord)
async def copper_update(test_id: str, upd: CopperUpdate):
    doc = await db.copper_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Test not found")
    changes: dict = {k: v for k, v in upd.model_dump(exclude_none=True).items()}
    if "sample_id" in changes:
        changes["meta.sample_id"] = changes.pop("sample_id").strip()
    if "classification" in changes:
        cls = copper_class_for(changes["classification"])
        changes.update({
            "classification": cls["code"], "class_label": cls["label"], "group": cls["group"],
            "color": cls["color"], "description": cls["description"], "severity": cls["severity"],
            "status": cls["status"],
        })
    if not changes:
        return CopperRecord(**doc)
    changes["edited"] = True
    changes["edited_at"] = now_iso()
    await db.copper_tests.update_one({"id": test_id}, {"$set": changes})
    doc = await db.copper_tests.find_one({"id": test_id}, {"_id": 0})
    return CopperRecord(**doc)


class CopperCropRequest(BaseModel):
    bbox: List[float]


@api_router.put("/copper/tests/{test_id}/crop", response_model=CopperRecord)
async def copper_recrop(test_id: str, req: CopperCropRequest):
    doc = await db.copper_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Test not found")
    if len(req.bbox) != 4:
        raise HTTPException(status_code=400, detail="bbox harus [x,y,w,h]")
    x, y, w, h = [max(0.0, min(1.0, float(v))) for v in req.bbox]
    w, h = min(w, 1 - x), min(h, 1 - y)
    try:
        content, _ = await run_in_threadpool(get_source_object, doc["image_path"])
        crop_bytes = await run_in_threadpool(_crop_bbox, content, [x, y, w, h], 0.0)
    except ValueError:
        raise HTTPException(status_code=400, detail="Area crop terlalu kecil")
    path = f"{APP_NAME}/copper/crops/{test_id}/{uuid.uuid4()}.jpg"
    await run_in_threadpool(put_object, path, crop_bytes, "image/jpeg")
    changes = {"crop_path": path, "bbox": [x, y, w, h], "edited": True, "edited_at": now_iso()}
    await db.copper_tests.update_one({"id": test_id}, {"$set": changes})
    return CopperRecord(**{**doc, **changes})


@api_router.post("/copper/tests/{test_id}/rerate", response_model=CopperRecord)
async def copper_rerate(test_id: str):
    doc = await db.copper_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Test not found")
    try:
        content, _ = await run_in_threadpool(get_source_object, doc.get("crop_path") or doc["image_path"])
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    small = await run_in_threadpool(_downscale_for_ai, content)
    try:
        ai = await run_copper_vision(base64.b64encode(small).decode("utf-8"))
    except Exception as e:
        logger.exception("Copper re-rate failed")
        raise HTTPException(status_code=502, detail=f"AI Vision analysis failed: {friendly_ai_error(e)}")
    cls = copper_class_for(ai.get("classification"))
    changes = {
        "classification": cls["code"], "class_label": cls["label"], "group": cls["group"], "color": cls["color"],
        "description": cls["description"], "severity": cls["severity"], "status": cls["status"],
        "confidence": _clamp(ai.get("confidence"), 0, 100),
        "ai_summary": str(ai.get("summary", "")), "recommendation": str(ai.get("recommendation", "")),
        "edited_at": now_iso(),
    }
    await db.copper_tests.update_one({"id": test_id}, {"$set": changes})
    return CopperRecord(**{**doc, **changes})


@api_router.delete("/copper/tests/{test_id}")
async def copper_delete(test_id: str):
    res = await db.copper_tests.update_one({"id": test_id}, {"$set": {"deleted_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Test not found")
    return {"ok": True}


@api_router.get("/copper/dashboard")
async def copper_dashboard():
    docs = await db.copper_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", -1).to_list(500)
    tests = [CopperRecord(**d) for d in docs]
    total = len(tests)
    passed = sum(1 for t in tests if t.status == STATUS_CLEAR)
    return {
        "latest": tests[0].model_dump() if tests else None,
        "total": total,
        "passed": passed,
        "failed": total - passed,
    }


@api_router.get("/copper/trend")
async def copper_trend():
    docs = await db.copper_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", 1).to_list(500)
    tests = [CopperRecord(**d) for d in docs]
    return [
        {
            "id": t.id, "classification": t.classification, "severity": t.severity,
            "status": t.status, "sample_id": t.meta.sample_id, "created_at": t.created_at,
        }
        for t in tests
    ]


@api_router.get("/copper/reference-scale")
async def copper_reference_scale():
    doc = await db.reference.find_one({"key": "astm_d130_scale"}, {"_id": 0})
    if not doc:
        await seed_copper_reference()
        doc = await db.reference.find_one({"key": "astm_d130_scale"}, {"_id": 0})
    return {
        "title": doc.get("title", "ASTM Copper Strip Corrosion Standards"),
        "note": doc.get("note", ""),
        "image": f"data:{doc.get('content_type', 'image/jpeg')};base64,{doc['image_base64']}",
        "classes": doc.get("classes", ASTM_D130_CLASSES),
        "updated_at": doc.get("updated_at"),
    }


# ===========================================================================
# MODULE: Rust Preventing — ASTM D1748 / 100-box metal panel inspection
# ===========================================================================
RUST_GRADES = {
    "A": {"min": 0, "max": 0, "label": "Bersih tanpa karat", "status": "EXCELLENT PASS", "color": "#10B981"},
    "B": {"min": 1, "max": 10, "label": "Karat ringan", "status": "GOOD / MINOR", "color": "#34D399"},
    "C": {"min": 11, "max": 25, "label": "Karat sedang", "status": "FAIR / MODERATE", "color": "#FBBF24"},
    "D": {"min": 26, "max": 50, "label": "Karat luas", "status": "POOR / EXTENSIVE", "color": "#F97316"},
    "E": {"min": 51, "max": 100, "label": "Karat berat", "status": "REJECT / SEVERE", "color": "#EF4444"},
}


def rust_grade_for(count: int) -> str:
    n = max(0, min(100, int(count)))
    for grade, rule in RUST_GRADES.items():
        if rule["min"] <= n <= rule["max"]:
            return grade
    return "E"


RUST_PROMPT = """You are an expert metallurgical inspector for Rust Preventing ASTM D1748.

Analyze the SECOND image: a metal corrosion specimen placed beside or under a transparent measuring plate.
The measuring plate is 60 x 80 mm, has 0.5 mm cross-cut lines, and creates exactly 100 small boxes in a 10 x 10 grid; each box is 5 x 5 mm. Evaluate ONLY the central 50 x 50 mm measurement surface. Ignore the outer edge area outside the main measuring zone.

COUNTING RULES:
- Count a box as rusted when at least one naked-eye-visible rust spot is present in that box.
- If rust crosses a cross-cut line into an adjacent box, count every box touched by the spreading rust.
- Do not count mere glare, plate reflections, dust, scratches, or the transparent plate itself as rust.
- Read the 10 rows from top to bottom and each row left to right. If the grid is rotated, mentally normalize it.

GRADE RULES:
Grade A = 0 rusted boxes; Grade B = 1-10; Grade C = 11-25; Grade D = 26-50; Grade E = 51-100.

Return ONLY valid minified JSON with EXACTLY these keys:
{"rusted_box_count":<integer 0-100>,"grade":"A|B|C|D|E","confidence":<number 0-100>,"grid_boxes":[<exactly 100 booleans, row-major top-to-bottom>],"grid_corners":[[x,y],[x,y],[x,y],[x,y]],"rust_spread":"<localized|scattered|clustered|widespread|near-total>","summary":"<short Indonesian note describing distribution within the central 50x50 mm area and cross-cut propagation>","recommendation":"<one short Indonesian practical recommendation>"}
The grid_boxes array is mandatory and its true count MUST equal rusted_box_count. When image quality makes a box ambiguous, count only visible rust and lower confidence.
grid_corners are the 4 outer corners of the evaluated 10 x 10 box zone (central 50 x 50 mm) in the image as it is displayed, ordered top-left, top-right, bottom-right, bottom-left, each as normalized [x,y] fractions 0-1 of image width/height (x to the right, y downward). Row 1 of grid_boxes is the row between top-left and top-right."""

RUST_FULL_PROMPT = """You are an expert metallurgical inspector for Rust Preventing ASTM D1748 using the WHOLE-IMAGE method.

Analyze the SECOND image. The ACTIVE ZONE is the ENTIRE image as displayed. Mentally divide the full image into an exact 10 x 10 grid of 100 equal boxes: each box spans 10% of the image width and 10% of the image height. Box 1 is the top-left, box 10 the top-right, box 100 the bottom-right (row-major, top-to-bottom, left-to-right). Do NOT rotate or re-frame the image.

COUNTING RULES:
- Count a box as rusted when at least one naked-eye-visible rust spot (orange/brown/red-brown corrosion product) is present on the metal test specimen surface inside that box.
- If rust crosses a box boundary, count every box it touches.
- Do not count glare, reflections, water droplets, dust, scratches, shadows, or the transparent plate itself as rust.
- Rust on background equipment that is clearly not part of the test specimen(s) is NOT counted.

GRADE RULES:
Grade A = 0 rusted boxes; Grade B = 1-10; Grade C = 11-25; Grade D = 26-50; Grade E = 51-100.

Return ONLY valid minified JSON with EXACTLY these keys:
{"rusted_box_count":<integer 0-100>,"grade":"A|B|C|D|E","confidence":<number 0-100>,"grid_boxes":[<exactly 100 booleans, row-major top-to-bottom>],"specimen_box_count":<integer 0-100, boxes that contain any metal specimen surface>,"rust_spread":"<localized|scattered|clustered|widespread|near-total>","summary":"<short Indonesian note describing rust distribution across the whole image grid and which rows/columns are most affected>","recommendation":"<one short Indonesian practical recommendation>"}
The grid_boxes array is mandatory and its true count MUST equal rusted_box_count. When a box is ambiguous, count only clearly visible rust and lower confidence."""

FULL_IMAGE_CORNERS = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
RUST_METHODS = {"zone": "Active Zone 50x50 mm", "full": "Seluruh Gambar"}

RUST_LOCATE_PROMPT = """Locate the evaluated 10 x 10 box measuring zone (central 50 x 50 mm area covered by the transparent ASTM D1748 cross-cut measuring plate) on the metal panel in this image.
Return ONLY minified JSON: {"grid_corners":[[x,y],[x,y],[x,y],[x,y]]}
Corners ordered top-left, top-right, bottom-right, bottom-left as normalized fractions 0-1 of image width/height (x right, y down)."""


def _parse_grid_corners(raw) -> Optional[List[List[float]]]:
    try:
        if isinstance(raw, dict):
            raw = [raw.get(k) for k in ("top_left", "top_right", "bottom_right", "bottom_left")]
        if isinstance(raw, list) and len(raw) == 4 and all(isinstance(v, (int, float)) for v in raw):
            x0, y0, x1, y1 = [float(v) for v in raw]  # bbox form
            raw = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        vals = []
        for pt in list(raw)[:4]:
            if isinstance(pt, dict):
                pt = [pt.get("x"), pt.get("y")]
            vals.append((float(pt[0]), float(pt[1])))
        if len(vals) != 4:
            return None
        peak = max(max(abs(x), abs(y)) for x, y in vals)
        div = 1000.0 if peak > 100 else (100.0 if peak > 1.5 else 1.0)  # 0-1000 / percent / fraction
        pts = [[round(max(0.0, min(1.0, x / div)), 4), round(max(0.0, min(1.0, y / div)), 4)] for x, y in vals]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if max(xs) - min(xs) < 0.05 or max(ys) - min(ys) < 0.05:
            return None
        return pts
    except Exception:
        return None


async def run_rust_locate(image_b64: str) -> Optional[List[List[float]]]:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"rust-locate-{uuid.uuid4()}",
        system_message="You locate measuring grids in inspection photos and only output JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    parts = []
    async for event in chat.stream_message(UserMessage(text=RUST_LOCATE_PROMPT, file_contents=[ImageContent(image_base64=image_b64)])):
        if isinstance(event, TextDelta):
            parts.append(event.content)
        elif isinstance(event, StreamDone):
            break
    raw_text = "".join(parts)
    corners = _parse_grid_corners(_parse_ai_json(raw_text).get("grid_corners"))
    if not corners:
        logger.warning("Rust grid locate unparsable: %s", raw_text[:300])
    return corners


async def run_rust_vision(image_b64: str, method: str = "zone") -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"rust-d1748-{uuid.uuid4()}",
        system_message="You are a precise ASTM D1748 metal corrosion grid inspector that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    parts = []
    prompt = RUST_FULL_PROMPT if method == "full" else RUST_PROMPT
    async for event in chat.stream_message(UserMessage(text=prompt, file_contents=[ImageContent(image_base64=image_b64)])):
        if isinstance(event, TextDelta):
            parts.append(event.content)
        elif isinstance(event, StreamDone):
            break
    return _parse_ai_json("".join(parts))


class RustMeta(BaseModel):
    sample_id: str = ""
    product: str = ""
    batch: str = ""
    operator: str = ""
    exposure_hours: float = 168
    temperature_c: float = 48.9
    humidity_pct: float = 95
    substrate: str = "Cold Rolled Steel 1018"
    remark: str = ""


class RustAnalyzeRequest(RustMeta):
    image_path: str
    method: str = "zone"  # zone = Active Zone 50x50 mm, full = seluruh gambar


RUST_SNAPSHOT_KEYS = (
    "rusted_box_count", "grade", "grade_label", "grade_status", "confidence", "grid_boxes", "rust_spread",
    "ai_summary", "recommendation", "ai_model", "ai_grid_boxes", "ai_rusted_box_count", "ai_grade",
    "grid_corners", "specimen_box_count", "analyzed_at", "edited", "edited_at",
)


def _norm_method(m: Optional[str]) -> str:
    return "full" if str(m or "").lower() in {"full", "whole", "seluruh", "full_image"} else "zone"


class RustRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    image_path: str
    meta: RustMeta
    rusted_box_count: int = 0
    grade: str = "A"
    grade_label: str = "Bersih tanpa karat"
    grade_status: str = "EXCELLENT PASS"
    confidence: float = 0
    grid_boxes: List[bool] = Field(default_factory=lambda: [False] * 100)
    rust_spread: str = "localized"
    ai_summary: str = ""
    recommendation: str = ""
    ai_model: str = "gemini-3.1-pro-preview"
    # Original AI Vision verdict (never overwritten by grid corrections)
    ai_grid_boxes: Optional[List[bool]] = None
    ai_rusted_box_count: Optional[int] = None
    ai_grade: Optional[str] = None
    grid_corners: Optional[List[List[float]]] = None
    # Inspector's own manual assessment (separate from grid correction)
    inspector_count: Optional[int] = None
    inspector_grade: Optional[str] = None
    inspector_name: str = ""
    inspector_notes: str = ""
    inspector_at: Optional[str] = None
    # Assessment method: zone (Active Zone 50x50 mm) | full (seluruh gambar). Top-level fields = active method.
    method: str = "zone"
    specimen_box_count: Optional[int] = None
    analyzed_at: Optional[str] = None
    method_results: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    edited: bool = False
    edited_at: Optional[str] = None
    deleted_at: Optional[str] = None

    @model_validator(mode="after")
    def _fill_ai_original(self):
        if self.ai_grid_boxes is None:
            self.ai_grid_boxes = list(self.grid_boxes)
        if self.ai_rusted_box_count is None:
            self.ai_rusted_box_count = sum(bool(v) for v in self.ai_grid_boxes)
        if not self.ai_grade:
            self.ai_grade = rust_grade_for(self.ai_rusted_box_count)
        self.method = _norm_method(self.method)
        if self.method == "full" and not self.grid_corners:
            self.grid_corners = [list(p) for p in FULL_IMAGE_CORNERS]
        if not self.analyzed_at:
            self.analyzed_at = self.created_at
        if self.method not in self.method_results:
            self.method_results = {**self.method_results, self.method: _rust_snapshot(self.model_dump(exclude={"method_results"}))}
        return self


class RustJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    record_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


class RustUpdate(BaseModel):
    rusted_box_count: Optional[int] = None
    grid_boxes: Optional[List[bool]] = None
    ai_summary: Optional[str] = None
    recommendation: Optional[str] = None
    inspector_count: Optional[int] = None  # -1 clears the manual assessment
    inspector_name: Optional[str] = None
    inspector_notes: Optional[str] = None


def _rust_snapshot(d: dict) -> dict:
    return {k: d.get(k) for k in RUST_SNAPSHOT_KEYS}


def _rust_grid_from_ai(ai: dict) -> tuple:
    raw = ai.get("grid_boxes") if isinstance(ai, dict) else None
    boxes = []
    if isinstance(raw, list):
        for value in raw[:100]:
            if isinstance(value, bool):
                boxes.append(value)
            elif isinstance(value, (int, float)):
                boxes.append(float(value) > 0)
            else:
                boxes.append(str(value).strip().lower() in {"true", "1", "rust", "rusted", "yes"})
    boxes.extend([False] * (100 - len(boxes)))
    if len(boxes) == 100 and any(boxes):
        count = sum(boxes)
    else:
        try:
            count = int(float(ai.get("rusted_box_count", 0)))
        except (TypeError, ValueError):
            count = 0
        count = max(0, min(100, count))
        boxes = [i < count for i in range(100)]
    return boxes, sum(boxes)


def _rust_result_fields(ai: dict, method: str) -> dict:
    boxes, count = _rust_grid_from_ai(ai)
    grade = rust_grade_for(count)
    rule = RUST_GRADES[grade]
    corners = [list(p) for p in FULL_IMAGE_CORNERS] if method == "full" else _parse_grid_corners(ai.get("grid_corners"))
    spec = None
    if method == "full":
        try:
            spec = max(0, min(100, int(float(ai.get("specimen_box_count")))))
        except (TypeError, ValueError):
            spec = None
    return {
        "rusted_box_count": count, "grade": grade, "grade_label": rule["label"], "grade_status": rule["status"],
        "confidence": _clamp(ai.get("confidence"), 0, 100), "grid_boxes": boxes, "ai_grid_boxes": list(boxes),
        "ai_rusted_box_count": count, "ai_grade": grade, "grid_corners": corners, "specimen_box_count": spec,
        "rust_spread": str(ai.get("rust_spread", "localized")), "ai_summary": str(ai.get("summary", "")),
        "recommendation": str(ai.get("recommendation", "")), "ai_model": "gemini-3.1-pro-preview",
        "analyzed_at": now_iso(), "edited": False, "edited_at": None,
    }


def _build_rust_record(req: RustAnalyzeRequest, ai: dict) -> RustRecord:
    method = _norm_method(req.method)
    fields = _rust_result_fields(ai, method)
    return RustRecord(
        image_path=req.image_path,
        meta=RustMeta(**req.model_dump(exclude={"image_path", "method"})),
        method=method,
        method_results={method: dict(fields)},
        **fields,
    )


async def _analyze_rust(req: RustAnalyzeRequest) -> RustRecord:
    try:
        content, _ = await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    small = await run_in_threadpool(_downscale_for_ai, content, 2200)
    b64 = base64.b64encode(small).decode("utf-8")
    try:
        ai = await run_rust_vision(b64, _norm_method(req.method))
        record = _build_rust_record(req, ai)
    except Exception as e:
        logger.exception("Rust D1748 AI vision failed")
        raise HTTPException(status_code=502, detail=f"AI Vision analysis failed: {friendly_ai_error(e)}")
    await db.rust_tests.insert_one(record.model_dump())
    return record


async def _run_rust_job(job_id: str, req: RustAnalyzeRequest):
    try:
        record = await _analyze_rust(req)
        await db.rust_jobs.update_one({"id": job_id}, {"$set": {"status": "done", "record_id": record.id, "finished_at": now_iso()}})
    except HTTPException as e:
        await db.rust_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}})
    except Exception as e:
        logger.exception("rust analyze job failed")
        await db.rust_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}})


@api_router.post("/rust/analyze/start", response_model=RustJob)
async def rust_analyze_start(req: RustAnalyzeRequest):
    if not (req.image_path or "").strip():
        raise HTTPException(status_code=400, detail="image_path wajib diisi — unggah foto terlebih dahulu")
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = RustJob()
    await db.rust_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_rust_job(job.id, req))
    return job


@api_router.get("/rust/analyze/jobs/{job_id}", response_model=RustJob)
async def rust_job_status(job_id: str):
    doc = await db.rust_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return RustJob(**doc)


@api_router.get("/rust/tests", response_model=List[RustRecord])
async def rust_list(q: Optional[str] = None):
    query: dict = {"deleted_at": None}
    if q:
        query["$or"] = [
            {"meta.sample_id": {"$regex": q, "$options": "i"}},
            {"meta.product": {"$regex": q, "$options": "i"}},
            {"meta.batch": {"$regex": q, "$options": "i"}},
            {"meta.operator": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.rust_tests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [RustRecord(**doc) for doc in docs]


@api_router.get("/rust/tests/{test_id}", response_model=RustRecord)
async def rust_get(test_id: str):
    doc = await db.rust_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    return RustRecord(**doc)


@api_router.put("/rust/tests/{test_id}", response_model=RustRecord)
async def rust_update(test_id: str, upd: RustUpdate):
    doc = await db.rust_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    changes = upd.model_dump(exclude_none=True)
    # Freeze the original AI verdict before the first correction (legacy records)
    if doc.get("ai_grid_boxes") is None:
        orig = RustRecord(**doc)
        changes["ai_grid_boxes"] = orig.ai_grid_boxes
        changes["ai_rusted_box_count"] = orig.ai_rusted_box_count
        changes["ai_grade"] = orig.ai_grade
    inspector_touched = any(k in changes for k in ("inspector_count", "inspector_name", "inspector_notes"))
    if "inspector_count" in changes:
        ic = int(changes["inspector_count"])
        if ic < 0:
            changes["inspector_count"] = None
            changes["inspector_grade"] = None
        else:
            ic = min(100, ic)
            changes["inspector_count"] = ic
            changes["inspector_grade"] = rust_grade_for(ic)
    if inspector_touched:
        changes["inspector_at"] = now_iso()
    if "grid_boxes" in changes:
        boxes = [bool(v) for v in changes["grid_boxes"][:100]]
        boxes.extend([False] * (100 - len(boxes)))
        changes["grid_boxes"] = boxes
        changes["rusted_box_count"] = sum(boxes)
    elif "rusted_box_count" in changes:
        count = max(0, min(100, int(changes["rusted_box_count"])))
        changes["rusted_box_count"] = count
        changes["grid_boxes"] = [i < count for i in range(100)]
    if "rusted_box_count" in changes:
        grade = rust_grade_for(changes["rusted_box_count"])
        changes["grade"] = grade
        changes["grade_label"] = RUST_GRADES[grade]["label"]
        changes["grade_status"] = RUST_GRADES[grade]["status"]
    if not changes:
        return RustRecord(**doc)
    result_touched = any(k in changes for k in ("grid_boxes", "rusted_box_count", "ai_summary", "recommendation"))
    if result_touched:
        changes["edited"] = True
        changes["edited_at"] = now_iso()
    merged = RustRecord(**{**doc, **changes})
    changes["method_results"] = {**merged.method_results, merged.method: _rust_snapshot(merged.model_dump(exclude={"method_results"}))}
    await db.rust_tests.update_one({"id": test_id}, {"$set": changes})
    updated = await db.rust_tests.find_one({"id": test_id}, {"_id": 0})
    return RustRecord(**updated)


@api_router.post("/rust/tests/{test_id}/locate-grid", response_model=RustRecord)
async def rust_locate_grid(test_id: str):
    doc = await db.rust_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    if not (RustRecord(**doc).method_results.get("zone")):
        raise HTTPException(status_code=400, detail="Metode Active Zone belum dianalisa untuk inspeksi ini.")
    try:
        content, _ = await run_in_threadpool(get_source_object, doc["image_path"])
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    small = await run_in_threadpool(_downscale_for_ai, content, 2200)
    try:
        corners = await run_rust_locate(base64.b64encode(small).decode("utf-8"))
    except Exception as e:
        logger.exception("Rust grid locate failed")
        raise HTTPException(status_code=502, detail=f"AI Vision gagal mendeteksi grid: {friendly_ai_error(e)}")
    if not corners:
        raise HTTPException(status_code=422, detail="Posisi grid tidak terdeteksi pada foto.")
    rec = RustRecord(**doc)
    mr = dict(rec.method_results)
    zone = dict(mr.get("zone") or {})
    zone["grid_corners"] = corners
    mr["zone"] = zone
    sets = {"method_results": mr}
    if rec.method == "zone":
        sets["grid_corners"] = corners
    await db.rust_tests.update_one({"id": test_id}, {"$set": sets})
    updated = await db.rust_tests.find_one({"id": test_id}, {"_id": 0})
    return RustRecord(**updated)


class RustMethodRequest(BaseModel):
    method: str


async def _set_active_rust_method(test_id: str, method: str, new_result: Optional[dict] = None) -> RustRecord:
    doc = await db.rust_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    rec = RustRecord(**doc)
    mr = dict(rec.method_results)
    mr[rec.method] = _rust_snapshot(rec.model_dump(exclude={"method_results"}))  # persist current active
    if new_result is not None:
        mr[method] = new_result
    snap = mr.get(method)
    if not snap:
        raise HTTPException(status_code=400, detail=f"Metode {RUST_METHODS.get(method, method)} belum dianalisa. Jalankan analisa terlebih dahulu.")
    sets = {k: snap.get(k) for k in RUST_SNAPSHOT_KEYS}
    sets["method"] = method
    sets["method_results"] = mr
    await db.rust_tests.update_one({"id": test_id}, {"$set": sets})
    updated = await db.rust_tests.find_one({"id": test_id}, {"_id": 0})
    return RustRecord(**updated)


@api_router.put("/rust/tests/{test_id}/method", response_model=RustRecord)
async def rust_switch_method(test_id: str, req: RustMethodRequest):
    """Make an already-analyzed method the official (active) result."""
    return await _set_active_rust_method(test_id, _norm_method(req.method))


async def _run_rust_method_job(job_id: str, test_id: str, method: str):
    try:
        doc = await db.rust_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Rust inspection not found")
        try:
            content, _ = await run_in_threadpool(get_source_object, doc["image_path"])
        except Exception:
            raise HTTPException(status_code=404, detail="Image not found in storage")
        small = await run_in_threadpool(_downscale_for_ai, content, 2200)
        try:
            ai = await run_rust_vision(base64.b64encode(small).decode("utf-8"), method)
        except Exception as e:
            logger.exception("Rust D1748 method analysis failed")
            raise HTTPException(status_code=502, detail=f"AI Vision analysis failed: {friendly_ai_error(e)}")
        await _set_active_rust_method(test_id, method, _rust_result_fields(ai, method))
        await db.rust_jobs.update_one({"id": job_id}, {"$set": {"status": "done", "record_id": test_id, "finished_at": now_iso()}})
    except HTTPException as e:
        await db.rust_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}})
    except Exception as e:
        logger.exception("rust method job failed")
        await db.rust_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}})


@api_router.post("/rust/tests/{test_id}/method/analyze", response_model=RustJob)
async def rust_analyze_method(test_id: str, req: RustMethodRequest):
    """(Re)analyze the same photo with the chosen method; the result becomes the active one."""
    doc = await db.rust_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    job = RustJob()
    await db.rust_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_rust_method_job(job.id, test_id, _norm_method(req.method)))
    return job


@api_router.delete("/rust/tests/{test_id}")
async def rust_delete(test_id: str):
    res = await db.rust_tests.update_one({"id": test_id}, {"$set": {"deleted_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    return {"ok": True}


@api_router.get("/rust/dashboard")
async def rust_dashboard():
    docs = await db.rust_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", -1).to_list(500)
    records = [RustRecord(**doc) for doc in docs]
    counts = {grade: 0 for grade in RUST_GRADES}
    for record in records:
        counts[record.grade] = counts.get(record.grade, 0) + 1
    avg = round(sum(r.rusted_box_count for r in records) / len(records), 1) if records else 0
    return {"latest": records[0].model_dump() if records else None, "total": len(records), "grade_counts": counts, "average_rusted_boxes": avg}


@api_router.get("/rust/trend")
async def rust_trend():
    docs = await db.rust_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", 1).to_list(500)
    return [{"id": d["id"], "sample_id": d.get("meta", {}).get("sample_id", ""), "rusted_box_count": d.get("rusted_box_count", 0), "grade": d.get("grade", "A"), "created_at": d.get("created_at")} for d in docs]


@api_router.get("/rust/reference-scale")
async def rust_reference_scale():
    return {"title": "ASTM D1748 Rust Preventing 100-Box Scale", "measurement_area": "50 x 50 mm central surface", "plate": "60 x 80 mm; 0.5 mm cross cuts; 100 boxes of 5 x 5 mm", "grades": RUST_GRADES}


# MODULE: Humidity Cabinet Test — ASTM D1748 / WHOLE-IMAGE 100-box inspection
# ===========================================================================
# Fitur sama persis dengan Rust Preventing ASTM D1748, tetapi penilaian rating
# SELALU memakai metode Seluruh Gambar: seluruh foto = active zone, dibagi rata
# 10 x 10 = 100 kotak. Tidak ada metode plate 50 x 50 mm.
HUM_GRADES = RUST_GRADES  # skala & label Grade A-E identik dengan Rust Preventing


def hum_grade_for(count: int) -> str:
    return rust_grade_for(count)


HUM_PROMPT = """You are an expert metallurgical inspector for the Humidity Cabinet Test ASTM D1748 using the WHOLE-IMAGE method.

Analyze the SECOND image: a metal test specimen that has been exposed in a humidity cabinet (high humidity + elevated temperature) per ASTM D1748. The ACTIVE ZONE is the ENTIRE image as displayed. Mentally divide the full image into an exact 10 x 10 grid of 100 equal boxes: each box spans 10% of the image width and 10% of the image height. Box 1 is the top-left, box 10 the top-right, box 100 the bottom-right (row-major, top-to-bottom, left-to-right). Do NOT rotate or re-frame the image.

COUNTING RULES:
- Count a box as corroded when at least one naked-eye-visible rust/corrosion spot (orange/brown/red-brown corrosion product) is present on the metal test specimen surface inside that box.
- If corrosion crosses a box boundary, count every box it touches.
- Do not count glare, reflections, water droplets, condensation, dust, scratches, shadows, or any transparent cover as corrosion.
- Corrosion on background equipment that is clearly not part of the test specimen(s) is NOT counted.

GRADE RULES:
Grade A = 0 corroded boxes; Grade B = 1-10; Grade C = 11-25; Grade D = 26-50; Grade E = 51-100.

Return ONLY valid minified JSON with EXACTLY these keys:
{"rusted_box_count":<integer 0-100>,"grade":"A|B|C|D|E","confidence":<number 0-100>,"grid_boxes":[<exactly 100 booleans, row-major top-to-bottom>],"specimen_box_count":<integer 0-100, boxes that contain any metal specimen surface>,"rust_spread":"<localized|scattered|clustered|widespread|near-total>","summary":"<short Indonesian note describing corrosion distribution across the whole image grid and which rows/columns are most affected>","recommendation":"<one short Indonesian practical recommendation>"}
The grid_boxes array is mandatory and its true count MUST equal rusted_box_count. When a box is ambiguous, count only clearly visible corrosion and lower confidence."""


async def run_humidity_vision(image_b64: str) -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"humidity-d1748-{uuid.uuid4()}",
        system_message="You are a precise ASTM D1748 humidity-cabinet corrosion grid inspector that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    parts = []
    async for event in chat.stream_message(UserMessage(text=HUM_PROMPT, file_contents=[ImageContent(image_base64=image_b64)])):
        if isinstance(event, TextDelta):
            parts.append(event.content)
        elif isinstance(event, StreamDone):
            break
    return _parse_ai_json("".join(parts))


class HumidityMeta(BaseModel):
    sample_id: str = ""
    product: str = ""
    batch: str = ""
    operator: str = ""
    exposure_hours: float = 168
    temperature_c: float = 48.9
    humidity_pct: float = 95
    substrate: str = "Cold Rolled Steel 1018"
    remark: str = ""


class HumidityAnalyzeRequest(HumidityMeta):
    image_path: str


class HumidityRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    image_path: str
    meta: HumidityMeta
    rusted_box_count: int = 0
    grade: str = "A"
    grade_label: str = "Bersih tanpa karat"
    grade_status: str = "EXCELLENT PASS"
    confidence: float = 0
    grid_boxes: List[bool] = Field(default_factory=lambda: [False] * 100)
    rust_spread: str = "localized"
    ai_summary: str = ""
    recommendation: str = ""
    ai_model: str = "gemini-3.1-pro-preview"
    # Original AI Vision verdict (never overwritten by grid corrections)
    ai_grid_boxes: Optional[List[bool]] = None
    ai_rusted_box_count: Optional[int] = None
    ai_grade: Optional[str] = None
    grid_corners: Optional[List[List[float]]] = None
    specimen_box_count: Optional[int] = None
    # Inspector's own manual assessment (separate from grid correction)
    inspector_count: Optional[int] = None
    inspector_grade: Optional[str] = None
    inspector_name: str = ""
    inspector_notes: str = ""
    inspector_at: Optional[str] = None
    # Humidity Cabinet selalu metode "Seluruh Gambar" (whole image 10x10)
    method: str = "full"
    analyzed_at: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    edited: bool = False
    edited_at: Optional[str] = None
    deleted_at: Optional[str] = None

    @model_validator(mode="after")
    def _fill_ai_original(self):
        if self.ai_grid_boxes is None:
            self.ai_grid_boxes = list(self.grid_boxes)
        if self.ai_rusted_box_count is None:
            self.ai_rusted_box_count = sum(bool(v) for v in self.ai_grid_boxes)
        if not self.ai_grade:
            self.ai_grade = hum_grade_for(self.ai_rusted_box_count)
        self.method = "full"
        if not self.grid_corners:
            self.grid_corners = [list(p) for p in FULL_IMAGE_CORNERS]
        if not self.analyzed_at:
            self.analyzed_at = self.created_at
        return self


class HumidityJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    record_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


class HumidityUpdate(BaseModel):
    rusted_box_count: Optional[int] = None
    grid_boxes: Optional[List[bool]] = None
    ai_summary: Optional[str] = None
    recommendation: Optional[str] = None
    inspector_count: Optional[int] = None  # -1 clears the manual assessment
    inspector_name: Optional[str] = None
    inspector_notes: Optional[str] = None


def _humidity_result_fields(ai: dict) -> dict:
    boxes, count = _rust_grid_from_ai(ai)
    grade = hum_grade_for(count)
    rule = HUM_GRADES[grade]
    try:
        spec = max(0, min(100, int(float(ai.get("specimen_box_count")))))
    except (TypeError, ValueError):
        spec = None
    return {
        "rusted_box_count": count, "grade": grade, "grade_label": rule["label"], "grade_status": rule["status"],
        "confidence": _clamp(ai.get("confidence"), 0, 100), "grid_boxes": boxes, "ai_grid_boxes": list(boxes),
        "ai_rusted_box_count": count, "ai_grade": grade,
        "grid_corners": [list(p) for p in FULL_IMAGE_CORNERS], "specimen_box_count": spec,
        "rust_spread": str(ai.get("rust_spread", "localized")), "ai_summary": str(ai.get("summary", "")),
        "recommendation": str(ai.get("recommendation", "")), "ai_model": "gemini-3.1-pro-preview",
        "analyzed_at": now_iso(), "edited": False, "edited_at": None,
    }


def _build_humidity_record(req: HumidityAnalyzeRequest, ai: dict) -> HumidityRecord:
    fields = _humidity_result_fields(ai)
    return HumidityRecord(
        image_path=req.image_path,
        meta=HumidityMeta(**req.model_dump(exclude={"image_path"})),
        method="full",
        **fields,
    )


async def _analyze_humidity(req: HumidityAnalyzeRequest) -> HumidityRecord:
    try:
        content, _ = await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    small = await run_in_threadpool(_downscale_for_ai, content, 2200)
    b64 = base64.b64encode(small).decode("utf-8")
    try:
        ai = await run_humidity_vision(b64)
        record = _build_humidity_record(req, ai)
    except Exception as e:
        logger.exception("Humidity D1748 AI vision failed")
        raise HTTPException(status_code=502, detail=f"AI Vision analysis failed: {friendly_ai_error(e)}")
    await db.humidity_tests.insert_one(record.model_dump())
    return record


async def _run_humidity_job(job_id: str, req: HumidityAnalyzeRequest):
    try:
        record = await _analyze_humidity(req)
        await db.humidity_jobs.update_one({"id": job_id}, {"$set": {"status": "done", "record_id": record.id, "finished_at": now_iso()}})
    except HTTPException as e:
        await db.humidity_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}})
    except Exception as e:
        logger.exception("humidity analyze job failed")
        await db.humidity_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}})


@api_router.post("/humidity/analyze/start", response_model=HumidityJob)
async def humidity_analyze_start(req: HumidityAnalyzeRequest):
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = HumidityJob()
    await db.humidity_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_humidity_job(job.id, req))
    return job


@api_router.get("/humidity/analyze/jobs/{job_id}", response_model=HumidityJob)
async def humidity_job_status(job_id: str):
    doc = await db.humidity_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return HumidityJob(**doc)


@api_router.get("/humidity/tests", response_model=List[HumidityRecord])
async def humidity_list(q: Optional[str] = None):
    query: dict = {"deleted_at": None}
    if q:
        query["$or"] = [
            {"meta.sample_id": {"$regex": q, "$options": "i"}},
            {"meta.product": {"$regex": q, "$options": "i"}},
            {"meta.batch": {"$regex": q, "$options": "i"}},
            {"meta.operator": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.humidity_tests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [HumidityRecord(**doc) for doc in docs]


@api_router.get("/humidity/tests/{test_id}", response_model=HumidityRecord)
async def humidity_get(test_id: str):
    doc = await db.humidity_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Humidity inspection not found")
    return HumidityRecord(**doc)


@api_router.put("/humidity/tests/{test_id}", response_model=HumidityRecord)
async def humidity_update(test_id: str, upd: HumidityUpdate):
    doc = await db.humidity_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Humidity inspection not found")
    changes = upd.model_dump(exclude_none=True)
    # Freeze the original AI verdict before the first correction (legacy records)
    if doc.get("ai_grid_boxes") is None:
        orig = HumidityRecord(**doc)
        changes["ai_grid_boxes"] = orig.ai_grid_boxes
        changes["ai_rusted_box_count"] = orig.ai_rusted_box_count
        changes["ai_grade"] = orig.ai_grade
    inspector_touched = any(k in changes for k in ("inspector_count", "inspector_name", "inspector_notes"))
    if "inspector_count" in changes:
        ic = int(changes["inspector_count"])
        if ic < 0:
            changes["inspector_count"] = None
            changes["inspector_grade"] = None
        else:
            ic = min(100, ic)
            changes["inspector_count"] = ic
            changes["inspector_grade"] = hum_grade_for(ic)
    if inspector_touched:
        changes["inspector_at"] = now_iso()
    if "grid_boxes" in changes:
        boxes = [bool(v) for v in changes["grid_boxes"][:100]]
        boxes.extend([False] * (100 - len(boxes)))
        changes["grid_boxes"] = boxes
        changes["rusted_box_count"] = sum(boxes)
    elif "rusted_box_count" in changes:
        count = max(0, min(100, int(changes["rusted_box_count"])))
        changes["rusted_box_count"] = count
        changes["grid_boxes"] = [i < count for i in range(100)]
    if "rusted_box_count" in changes:
        grade = hum_grade_for(changes["rusted_box_count"])
        changes["grade"] = grade
        changes["grade_label"] = HUM_GRADES[grade]["label"]
        changes["grade_status"] = HUM_GRADES[grade]["status"]
    if not changes:
        return HumidityRecord(**doc)
    result_touched = any(k in changes for k in ("grid_boxes", "rusted_box_count", "ai_summary", "recommendation"))
    if result_touched:
        changes["edited"] = True
        changes["edited_at"] = now_iso()
    await db.humidity_tests.update_one({"id": test_id}, {"$set": changes})
    updated = await db.humidity_tests.find_one({"id": test_id}, {"_id": 0})
    return HumidityRecord(**updated)


@api_router.delete("/humidity/tests/{test_id}")
async def humidity_delete(test_id: str):
    res = await db.humidity_tests.update_one({"id": test_id}, {"$set": {"deleted_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Humidity inspection not found")
    return {"ok": True}


@api_router.get("/humidity/dashboard")
async def humidity_dashboard():
    docs = await db.humidity_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", -1).to_list(500)
    records = [HumidityRecord(**doc) for doc in docs]
    counts = {grade: 0 for grade in HUM_GRADES}
    for record in records:
        counts[record.grade] = counts.get(record.grade, 0) + 1
    avg = round(sum(r.rusted_box_count for r in records) / len(records), 1) if records else 0
    return {"latest": records[0].model_dump() if records else None, "total": len(records), "grade_counts": counts, "average_rusted_boxes": avg}


@api_router.get("/humidity/trend")
async def humidity_trend():
    docs = await db.humidity_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", 1).to_list(500)
    return [{"id": d["id"], "sample_id": d.get("meta", {}).get("sample_id", ""), "rusted_box_count": d.get("rusted_box_count", 0), "grade": d.get("grade", "A"), "created_at": d.get("created_at")} for d in docs]


@api_router.get("/humidity/reference-scale")
async def humidity_reference_scale():
    return {"title": "ASTM D1748 Humidity Cabinet 100-Box Scale (Seluruh Gambar)", "measurement_area": "Seluruh gambar = active zone, dibagi rata 10 x 10 = 100 kotak", "plate": "Tanpa plate; seluruh foto dibagi menjadi 100 kotak (10 x 10)", "grades": HUM_GRADES}


# MODULE: DIP TEST In House Method — WHOLE-IMAGE 100-box inspection
# ===========================================================================
# Fitur sama persis dengan Humidity Cabinet Test ASTM D1748. Penilaian rating
# SELALU memakai metode Seluruh Gambar: seluruh foto = active zone, dibagi rata
# 10 x 10 = 100 kotak. Tidak ada metode plate 50 x 50 mm.
DIP_GRADES = RUST_GRADES  # skala & label Grade A-E identik


def dip_grade_for(count: int) -> str:
    return rust_grade_for(count)


DIP_PROMPT = """You are an expert metallurgical inspector for the DIP TEST (In House Method) corrosion evaluation using the WHOLE-IMAGE method.

Analyze the SECOND image: a metal test specimen evaluated with the in-house DIP TEST method. The ACTIVE ZONE is the ENTIRE image as displayed. Mentally divide the full image into an exact 10 x 10 grid of 100 equal boxes: each box spans 10% of the image width and 10% of the image height. Box 1 is the top-left, box 10 the top-right, box 100 the bottom-right (row-major, top-to-bottom, left-to-right). Do NOT rotate or re-frame the image.

COUNTING RULES:
- Count a box as corroded when at least one naked-eye-visible rust/corrosion spot (orange/brown/red-brown corrosion product) is present on the metal test specimen surface inside that box.
- If corrosion crosses a box boundary, count every box it touches.
- Do not count glare, reflections, water droplets, condensation, dust, scratches, shadows, or any transparent cover as corrosion.
- Corrosion on background equipment that is clearly not part of the test specimen(s) is NOT counted.

GRADE RULES:
Grade A = 0 corroded boxes; Grade B = 1-10; Grade C = 11-25; Grade D = 26-50; Grade E = 51-100.

Return ONLY valid minified JSON with EXACTLY these keys:
{"rusted_box_count":<integer 0-100>,"grade":"A|B|C|D|E","confidence":<number 0-100>,"grid_boxes":[<exactly 100 booleans, row-major top-to-bottom>],"specimen_box_count":<integer 0-100, boxes that contain any metal specimen surface>,"rust_spread":"<localized|scattered|clustered|widespread|near-total>","summary":"<short Indonesian note describing corrosion distribution across the whole image grid and which rows/columns are most affected>","recommendation":"<one short Indonesian practical recommendation>"}
The grid_boxes array is mandatory and its true count MUST equal rusted_box_count. When a box is ambiguous, count only clearly visible corrosion and lower confidence."""


async def run_diptest_vision(image_b64: str) -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"diptest-{uuid.uuid4()}",
        system_message="You are a precise DIP TEST (in-house method) corrosion grid inspector that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    parts = []
    async for event in chat.stream_message(UserMessage(text=DIP_PROMPT, file_contents=[ImageContent(image_base64=image_b64)])):
        if isinstance(event, TextDelta):
            parts.append(event.content)
        elif isinstance(event, StreamDone):
            break
    return _parse_ai_json("".join(parts))


class DipMeta(BaseModel):
    sample_id: str = ""
    product: str = ""
    batch: str = ""
    operator: str = ""
    exposure_hours: float = 168
    temperature_c: float = 48.9
    humidity_pct: float = 95
    substrate: str = "Cold Rolled Steel 1018"
    remark: str = ""


class DipAnalyzeRequest(DipMeta):
    image_path: str


class DipRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    image_path: str
    meta: DipMeta
    rusted_box_count: int = 0
    grade: str = "A"
    grade_label: str = "Bersih tanpa karat"
    grade_status: str = "EXCELLENT PASS"
    confidence: float = 0
    grid_boxes: List[bool] = Field(default_factory=lambda: [False] * 100)
    rust_spread: str = "localized"
    ai_summary: str = ""
    recommendation: str = ""
    ai_model: str = "gemini-3.1-pro-preview"
    ai_grid_boxes: Optional[List[bool]] = None
    ai_rusted_box_count: Optional[int] = None
    ai_grade: Optional[str] = None
    grid_corners: Optional[List[List[float]]] = None
    specimen_box_count: Optional[int] = None
    inspector_count: Optional[int] = None
    inspector_grade: Optional[str] = None
    inspector_name: str = ""
    inspector_notes: str = ""
    inspector_at: Optional[str] = None
    method: str = "full"
    analyzed_at: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    edited: bool = False
    edited_at: Optional[str] = None
    deleted_at: Optional[str] = None

    @model_validator(mode="after")
    def _fill_ai_original(self):
        if self.ai_grid_boxes is None:
            self.ai_grid_boxes = list(self.grid_boxes)
        if self.ai_rusted_box_count is None:
            self.ai_rusted_box_count = sum(bool(v) for v in self.ai_grid_boxes)
        if not self.ai_grade:
            self.ai_grade = dip_grade_for(self.ai_rusted_box_count)
        self.method = "full"
        if not self.grid_corners:
            self.grid_corners = [list(p) for p in FULL_IMAGE_CORNERS]
        if not self.analyzed_at:
            self.analyzed_at = self.created_at
        return self


class DipJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    record_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


class DipUpdate(BaseModel):
    rusted_box_count: Optional[int] = None
    grid_boxes: Optional[List[bool]] = None
    ai_summary: Optional[str] = None
    recommendation: Optional[str] = None
    inspector_count: Optional[int] = None  # -1 clears the manual assessment
    inspector_name: Optional[str] = None
    inspector_notes: Optional[str] = None


def _dip_result_fields(ai: dict) -> dict:
    boxes, count = _rust_grid_from_ai(ai)
    grade = dip_grade_for(count)
    rule = DIP_GRADES[grade]
    try:
        spec = max(0, min(100, int(float(ai.get("specimen_box_count")))))
    except (TypeError, ValueError):
        spec = None
    return {
        "rusted_box_count": count, "grade": grade, "grade_label": rule["label"], "grade_status": rule["status"],
        "confidence": _clamp(ai.get("confidence"), 0, 100), "grid_boxes": boxes, "ai_grid_boxes": list(boxes),
        "ai_rusted_box_count": count, "ai_grade": grade,
        "grid_corners": [list(p) for p in FULL_IMAGE_CORNERS], "specimen_box_count": spec,
        "rust_spread": str(ai.get("rust_spread", "localized")), "ai_summary": str(ai.get("summary", "")),
        "recommendation": str(ai.get("recommendation", "")), "ai_model": "gemini-3.1-pro-preview",
        "analyzed_at": now_iso(), "edited": False, "edited_at": None,
    }


def _build_dip_record(req: DipAnalyzeRequest, ai: dict) -> DipRecord:
    fields = _dip_result_fields(ai)
    return DipRecord(
        image_path=req.image_path,
        meta=DipMeta(**req.model_dump(exclude={"image_path"})),
        method="full",
        **fields,
    )


async def _analyze_dip(req: DipAnalyzeRequest) -> DipRecord:
    try:
        content, _ = await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    small = await run_in_threadpool(_downscale_for_ai, content, 2200)
    b64 = base64.b64encode(small).decode("utf-8")
    try:
        ai = await run_diptest_vision(b64)
        record = _build_dip_record(req, ai)
    except Exception as e:
        logger.exception("DIP TEST AI vision failed")
        raise HTTPException(status_code=502, detail=f"AI Vision analysis failed: {friendly_ai_error(e)}")
    await db.diptest_tests.insert_one(record.model_dump())
    return record


async def _run_dip_job(job_id: str, req: DipAnalyzeRequest):
    try:
        record = await _analyze_dip(req)
        await db.diptest_jobs.update_one({"id": job_id}, {"$set": {"status": "done", "record_id": record.id, "finished_at": now_iso()}})
    except HTTPException as e:
        await db.diptest_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}})
    except Exception as e:
        logger.exception("diptest analyze job failed")
        await db.diptest_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}})


@api_router.post("/diptest/analyze/start", response_model=DipJob)
async def dip_analyze_start(req: DipAnalyzeRequest):
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = DipJob()
    await db.diptest_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_dip_job(job.id, req))
    return job


@api_router.get("/diptest/analyze/jobs/{job_id}", response_model=DipJob)
async def dip_job_status(job_id: str):
    doc = await db.diptest_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return DipJob(**doc)


@api_router.get("/diptest/tests", response_model=List[DipRecord])
async def dip_list(q: Optional[str] = None):
    query: dict = {"deleted_at": None}
    if q:
        query["$or"] = [
            {"meta.sample_id": {"$regex": q, "$options": "i"}},
            {"meta.product": {"$regex": q, "$options": "i"}},
            {"meta.batch": {"$regex": q, "$options": "i"}},
            {"meta.operator": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.diptest_tests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [DipRecord(**doc) for doc in docs]


@api_router.get("/diptest/tests/{test_id}", response_model=DipRecord)
async def dip_get(test_id: str):
    doc = await db.diptest_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="DIP TEST inspection not found")
    return DipRecord(**doc)


@api_router.put("/diptest/tests/{test_id}", response_model=DipRecord)
async def dip_update(test_id: str, upd: DipUpdate):
    doc = await db.diptest_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="DIP TEST inspection not found")
    changes = upd.model_dump(exclude_none=True)
    if doc.get("ai_grid_boxes") is None:
        orig = DipRecord(**doc)
        changes["ai_grid_boxes"] = orig.ai_grid_boxes
        changes["ai_rusted_box_count"] = orig.ai_rusted_box_count
        changes["ai_grade"] = orig.ai_grade
    inspector_touched = any(k in changes for k in ("inspector_count", "inspector_name", "inspector_notes"))
    if "inspector_count" in changes:
        ic = int(changes["inspector_count"])
        if ic < 0:
            changes["inspector_count"] = None
            changes["inspector_grade"] = None
        else:
            ic = min(100, ic)
            changes["inspector_count"] = ic
            changes["inspector_grade"] = dip_grade_for(ic)
    if inspector_touched:
        changes["inspector_at"] = now_iso()
    if "grid_boxes" in changes:
        boxes = [bool(v) for v in changes["grid_boxes"][:100]]
        boxes.extend([False] * (100 - len(boxes)))
        changes["grid_boxes"] = boxes
        changes["rusted_box_count"] = sum(boxes)
    elif "rusted_box_count" in changes:
        count = max(0, min(100, int(changes["rusted_box_count"])))
        changes["rusted_box_count"] = count
        changes["grid_boxes"] = [i < count for i in range(100)]
    if "rusted_box_count" in changes:
        grade = dip_grade_for(changes["rusted_box_count"])
        changes["grade"] = grade
        changes["grade_label"] = DIP_GRADES[grade]["label"]
        changes["grade_status"] = DIP_GRADES[grade]["status"]
    if not changes:
        return DipRecord(**doc)
    result_touched = any(k in changes for k in ("grid_boxes", "rusted_box_count", "ai_summary", "recommendation"))
    if result_touched:
        changes["edited"] = True
        changes["edited_at"] = now_iso()
    await db.diptest_tests.update_one({"id": test_id}, {"$set": changes})
    updated = await db.diptest_tests.find_one({"id": test_id}, {"_id": 0})
    return DipRecord(**updated)


@api_router.delete("/diptest/tests/{test_id}")
async def dip_delete(test_id: str):
    res = await db.diptest_tests.update_one({"id": test_id}, {"$set": {"deleted_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="DIP TEST inspection not found")
    return {"ok": True}


@api_router.get("/diptest/dashboard")
async def dip_dashboard():
    docs = await db.diptest_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", -1).to_list(500)
    records = [DipRecord(**doc) for doc in docs]
    counts = {grade: 0 for grade in DIP_GRADES}
    for record in records:
        counts[record.grade] = counts.get(record.grade, 0) + 1
    avg = round(sum(r.rusted_box_count for r in records) / len(records), 1) if records else 0
    return {"latest": records[0].model_dump() if records else None, "total": len(records), "grade_counts": counts, "average_rusted_boxes": avg}


@api_router.get("/diptest/trend")
async def dip_trend():
    docs = await db.diptest_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", 1).to_list(500)
    return [{"id": d["id"], "sample_id": d.get("meta", {}).get("sample_id", ""), "rusted_box_count": d.get("rusted_box_count", 0), "grade": d.get("grade", "A"), "created_at": d.get("created_at")} for d in docs]


@api_router.get("/diptest/reference-scale")
async def dip_reference_scale():
    return {"title": "DIP TEST In House Method 100-Box Scale (Seluruh Gambar)", "measurement_area": "Seluruh gambar = active zone, dibagi rata 10 x 10 = 100 kotak", "plate": "Tanpa plate; seluruh foto dibagi menjadi 100 kotak (10 x 10)", "grades": DIP_GRADES}


# MODULE: Salt Spray — ASTM B117 / 100-box metal panel inspection
# ===========================================================================
SALT_GRADES = {
    "A": {"min": 0, "max": 0, "label": "Bersih tanpa karat", "status": "EXCELLENT PASS", "color": "#10B981"},
    "B": {"min": 1, "max": 10, "label": "Karat ringan", "status": "GOOD / MINOR", "color": "#34D399"},
    "C": {"min": 11, "max": 25, "label": "Karat sedang", "status": "FAIR / MODERATE", "color": "#FBBF24"},
    "D": {"min": 26, "max": 50, "label": "Karat luas", "status": "POOR / EXTENSIVE", "color": "#F97316"},
    "E": {"min": 51, "max": 100, "label": "Karat berat", "status": "REJECT / SEVERE", "color": "#EF4444"},
}


def salt_grade_for(count: int) -> str:
    n = max(0, min(100, int(count)))
    for grade, rule in SALT_GRADES.items():
        if rule["min"] <= n <= rule["max"]:
            return grade
    return "E"


SALT_PROMPT = """You are an expert metallurgical inspector for Salt Spray ASTM B117.

Analyze the SECOND image: a metal corrosion specimen placed beside or under a transparent measuring plate.
The measuring plate is 60 x 80 mm, has 0.5 mm cross-cut lines, and creates exactly 100 small boxes in a 10 x 10 grid; each box is 5 x 5 mm. Evaluate ONLY the central 50 x 50 mm measurement surface. Ignore the outer edge area outside the main measuring zone.

COUNTING RULES:
- Count a box as rusted when at least one naked-eye-visible rust spot is present in that box.
- If rust crosses a cross-cut line into an adjacent box, count every box touched by the spreading rust.
- Do not count mere glare, plate reflections, dust, scratches, or the transparent plate itself as rust.
- Read the 10 rows from top to bottom and each row left to right. If the grid is rotated, mentally normalize it.

GRADE RULES:
Grade A = 0 rusted boxes; Grade B = 1-10; Grade C = 11-25; Grade D = 26-50; Grade E = 51-100.

Return ONLY valid minified JSON with EXACTLY these keys:
{"rusted_box_count":<integer 0-100>,"grade":"A|B|C|D|E","confidence":<number 0-100>,"grid_boxes":[<exactly 100 booleans, row-major top-to-bottom>],"grid_corners":[[x,y],[x,y],[x,y],[x,y]],"rust_spread":"<localized|scattered|clustered|widespread|near-total>","summary":"<short Indonesian note describing distribution within the central 50x50 mm area and cross-cut propagation>","recommendation":"<one short Indonesian practical recommendation>"}
The grid_boxes array is mandatory and its true count MUST equal rusted_box_count. When image quality makes a box ambiguous, count only visible rust and lower confidence.
grid_corners are the 4 outer corners of the evaluated 10 x 10 box zone (central 50 x 50 mm) in the image as it is displayed, ordered top-left, top-right, bottom-right, bottom-left, each as normalized [x,y] fractions 0-1 of image width/height (x to the right, y downward). Row 1 of grid_boxes is the row between top-left and top-right."""

SALT_FULL_PROMPT = """You are an expert metallurgical inspector for Salt Spray ASTM B117 using the WHOLE-IMAGE method.

Analyze the SECOND image. The ACTIVE ZONE is the ENTIRE image as displayed. Mentally divide the full image into an exact 10 x 10 grid of 100 equal boxes: each box spans 10% of the image width and 10% of the image height. Box 1 is the top-left, box 10 the top-right, box 100 the bottom-right (row-major, top-to-bottom, left-to-right). Do NOT rotate or re-frame the image.

COUNTING RULES:
- Count a box as rusted when at least one naked-eye-visible rust spot (orange/brown/red-brown corrosion product) is present on the metal test specimen surface inside that box.
- If rust crosses a box boundary, count every box it touches.
- Do not count glare, reflections, water droplets, dust, scratches, shadows, or the transparent plate itself as rust.
- Rust on background equipment that is clearly not part of the test specimen(s) is NOT counted.

GRADE RULES:
Grade A = 0 rusted boxes; Grade B = 1-10; Grade C = 11-25; Grade D = 26-50; Grade E = 51-100.

Return ONLY valid minified JSON with EXACTLY these keys:
{"rusted_box_count":<integer 0-100>,"grade":"A|B|C|D|E","confidence":<number 0-100>,"grid_boxes":[<exactly 100 booleans, row-major top-to-bottom>],"specimen_box_count":<integer 0-100, boxes that contain any metal specimen surface>,"rust_spread":"<localized|scattered|clustered|widespread|near-total>","summary":"<short Indonesian note describing rust distribution across the whole image grid and which rows/columns are most affected>","recommendation":"<one short Indonesian practical recommendation>"}
The grid_boxes array is mandatory and its true count MUST equal rusted_box_count. When a box is ambiguous, count only clearly visible rust and lower confidence."""

FULL_IMAGE_CORNERS = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
SALT_METHODS = {"zone": "Active Zone 50x50 mm", "full": "Seluruh Gambar"}

SALT_LOCATE_PROMPT = """Locate the evaluated 10 x 10 box measuring zone (central 50 x 50 mm area covered by the transparent ASTM B117 cross-cut measuring plate) on the metal panel in this image.
Return ONLY minified JSON: {"grid_corners":[[x,y],[x,y],[x,y],[x,y]]}
Corners ordered top-left, top-right, bottom-right, bottom-left as normalized fractions 0-1 of image width/height (x right, y down)."""


def _parse_grid_corners(raw) -> Optional[List[List[float]]]:
    try:
        if isinstance(raw, dict):
            raw = [raw.get(k) for k in ("top_left", "top_right", "bottom_right", "bottom_left")]
        if isinstance(raw, list) and len(raw) == 4 and all(isinstance(v, (int, float)) for v in raw):
            x0, y0, x1, y1 = [float(v) for v in raw]  # bbox form
            raw = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        vals = []
        for pt in list(raw)[:4]:
            if isinstance(pt, dict):
                pt = [pt.get("x"), pt.get("y")]
            vals.append((float(pt[0]), float(pt[1])))
        if len(vals) != 4:
            return None
        peak = max(max(abs(x), abs(y)) for x, y in vals)
        div = 1000.0 if peak > 100 else (100.0 if peak > 1.5 else 1.0)  # 0-1000 / percent / fraction
        pts = [[round(max(0.0, min(1.0, x / div)), 4), round(max(0.0, min(1.0, y / div)), 4)] for x, y in vals]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if max(xs) - min(xs) < 0.05 or max(ys) - min(ys) < 0.05:
            return None
        return pts
    except Exception:
        return None


async def run_salt_locate(image_b64: str) -> Optional[List[List[float]]]:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"rust-locate-{uuid.uuid4()}",
        system_message="You locate measuring grids in inspection photos and only output JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    parts = []
    async for event in chat.stream_message(UserMessage(text=SALT_LOCATE_PROMPT, file_contents=[ImageContent(image_base64=image_b64)])):
        if isinstance(event, TextDelta):
            parts.append(event.content)
        elif isinstance(event, StreamDone):
            break
    raw_text = "".join(parts)
    corners = _parse_grid_corners(_parse_ai_json(raw_text).get("grid_corners"))
    if not corners:
        logger.warning("Rust grid locate unparsable: %s", raw_text[:300])
    return corners


async def run_salt_vision(image_b64: str, method: str = "zone") -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"rust-d1748-{uuid.uuid4()}",
        system_message="You are a precise ASTM B117 metal corrosion grid inspector that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    parts = []
    prompt = SALT_FULL_PROMPT if method == "full" else SALT_PROMPT
    async for event in chat.stream_message(UserMessage(text=prompt, file_contents=[ImageContent(image_base64=image_b64)])):
        if isinstance(event, TextDelta):
            parts.append(event.content)
        elif isinstance(event, StreamDone):
            break
    return _parse_ai_json("".join(parts))


class SaltMeta(BaseModel):
    sample_id: str = ""
    product: str = ""
    batch: str = ""
    operator: str = ""
    exposure_hours: float = 96
    temperature_c: float = 35
    humidity_pct: float = 95
    substrate: str = "Cold Rolled Steel 1018"
    remark: str = ""


class SaltAnalyzeRequest(SaltMeta):
    image_path: str
    method: str = "zone"  # zone = Active Zone 50x50 mm, full = seluruh gambar


SALT_SNAPSHOT_KEYS = (
    "rusted_box_count", "grade", "grade_label", "grade_status", "confidence", "grid_boxes", "rust_spread",
    "ai_summary", "recommendation", "ai_model", "ai_grid_boxes", "ai_rusted_box_count", "ai_grade",
    "grid_corners", "specimen_box_count", "analyzed_at", "edited", "edited_at",
)


def _salt_norm_method(m: Optional[str]) -> str:
    return "zone"


class SaltRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    image_path: str
    meta: SaltMeta
    rusted_box_count: int = 0
    grade: str = "A"
    grade_label: str = "Bersih tanpa karat"
    grade_status: str = "EXCELLENT PASS"
    confidence: float = 0
    grid_boxes: List[bool] = Field(default_factory=lambda: [False] * 100)
    rust_spread: str = "localized"
    ai_summary: str = ""
    recommendation: str = ""
    ai_model: str = "gemini-3.1-pro-preview"
    # Original AI Vision verdict (never overwritten by grid corrections)
    ai_grid_boxes: Optional[List[bool]] = None
    ai_rusted_box_count: Optional[int] = None
    ai_grade: Optional[str] = None
    grid_corners: Optional[List[List[float]]] = None
    # Inspector's own manual assessment (separate from grid correction)
    inspector_count: Optional[int] = None
    inspector_grade: Optional[str] = None
    inspector_name: str = ""
    inspector_notes: str = ""
    inspector_at: Optional[str] = None
    # Assessment method: zone (Active Zone 50x50 mm) | full (seluruh gambar). Top-level fields = active method.
    method: str = "zone"
    specimen_box_count: Optional[int] = None
    analyzed_at: Optional[str] = None
    method_results: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    edited: bool = False
    edited_at: Optional[str] = None
    deleted_at: Optional[str] = None

    @model_validator(mode="after")
    def _fill_ai_original(self):
        if self.ai_grid_boxes is None:
            self.ai_grid_boxes = list(self.grid_boxes)
        if self.ai_rusted_box_count is None:
            self.ai_rusted_box_count = sum(bool(v) for v in self.ai_grid_boxes)
        if not self.ai_grade:
            self.ai_grade = salt_grade_for(self.ai_rusted_box_count)
        self.method = _salt_norm_method(self.method)
        if self.method == "full" and not self.grid_corners:
            self.grid_corners = [list(p) for p in FULL_IMAGE_CORNERS]
        if not self.analyzed_at:
            self.analyzed_at = self.created_at
        if self.method not in self.method_results:
            self.method_results = {**self.method_results, self.method: _salt_snapshot(self.model_dump(exclude={"method_results"}))}
        return self


class SaltJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    record_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


class SaltUpdate(BaseModel):
    rusted_box_count: Optional[int] = None
    grid_boxes: Optional[List[bool]] = None
    ai_summary: Optional[str] = None
    recommendation: Optional[str] = None
    inspector_count: Optional[int] = None  # -1 clears the manual assessment
    inspector_name: Optional[str] = None
    inspector_notes: Optional[str] = None


def _salt_snapshot(d: dict) -> dict:
    return {k: d.get(k) for k in SALT_SNAPSHOT_KEYS}


def _salt_grid_from_ai(ai: dict) -> tuple:
    raw = ai.get("grid_boxes") if isinstance(ai, dict) else None
    boxes = []
    if isinstance(raw, list):
        for value in raw[:100]:
            if isinstance(value, bool):
                boxes.append(value)
            elif isinstance(value, (int, float)):
                boxes.append(float(value) > 0)
            else:
                boxes.append(str(value).strip().lower() in {"true", "1", "rust", "rusted", "yes"})
    boxes.extend([False] * (100 - len(boxes)))
    if len(boxes) == 100 and any(boxes):
        count = sum(boxes)
    else:
        try:
            count = int(float(ai.get("rusted_box_count", 0)))
        except (TypeError, ValueError):
            count = 0
        count = max(0, min(100, count))
        boxes = [i < count for i in range(100)]
    return boxes, sum(boxes)


def _salt_result_fields(ai: dict, method: str) -> dict:
    boxes, count = _salt_grid_from_ai(ai)
    grade = salt_grade_for(count)
    rule = SALT_GRADES[grade]
    corners = [list(p) for p in FULL_IMAGE_CORNERS] if method == "full" else _parse_grid_corners(ai.get("grid_corners"))
    spec = None
    if method == "full":
        try:
            spec = max(0, min(100, int(float(ai.get("specimen_box_count")))))
        except (TypeError, ValueError):
            spec = None
    return {
        "rusted_box_count": count, "grade": grade, "grade_label": rule["label"], "grade_status": rule["status"],
        "confidence": _clamp(ai.get("confidence"), 0, 100), "grid_boxes": boxes, "ai_grid_boxes": list(boxes),
        "ai_rusted_box_count": count, "ai_grade": grade, "grid_corners": corners, "specimen_box_count": spec,
        "rust_spread": str(ai.get("rust_spread", "localized")), "ai_summary": str(ai.get("summary", "")),
        "recommendation": str(ai.get("recommendation", "")), "ai_model": "gemini-3.1-pro-preview",
        "analyzed_at": now_iso(), "edited": False, "edited_at": None,
    }


def _build_salt_record(req: SaltAnalyzeRequest, ai: dict) -> SaltRecord:
    method = _salt_norm_method(req.method)
    fields = _salt_result_fields(ai, method)
    return SaltRecord(
        image_path=req.image_path,
        meta=SaltMeta(**req.model_dump(exclude={"image_path", "method"})),
        method=method,
        method_results={method: dict(fields)},
        **fields,
    )


async def _analyze_salt(req: SaltAnalyzeRequest) -> SaltRecord:
    try:
        content, _ = await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    small = await run_in_threadpool(_downscale_for_ai, content, 2200)
    b64 = base64.b64encode(small).decode("utf-8")
    try:
        ai = await run_salt_vision(b64, _salt_norm_method(req.method))
        record = _build_salt_record(req, ai)
    except Exception as e:
        logger.exception("Rust B117 AI vision failed")
        raise HTTPException(status_code=502, detail=f"AI Vision analysis failed: {friendly_ai_error(e)}")
    await db.salt_tests.insert_one(record.model_dump())
    return record


async def _run_salt_job(job_id: str, req: SaltAnalyzeRequest):
    try:
        record = await _analyze_salt(req)
        await db.salt_jobs.update_one({"id": job_id}, {"$set": {"status": "done", "record_id": record.id, "finished_at": now_iso()}})
    except HTTPException as e:
        await db.salt_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}})
    except Exception as e:
        logger.exception("rust analyze job failed")
        await db.salt_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}})


@api_router.post("/salt-spray/analyze/start", response_model=SaltJob)
async def salt_analyze_start(req: SaltAnalyzeRequest):
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = SaltJob()
    await db.salt_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_salt_job(job.id, req))
    return job


@api_router.get("/salt-spray/analyze/jobs/{job_id}", response_model=SaltJob)
async def salt_job_status(job_id: str):
    doc = await db.salt_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return SaltJob(**doc)


@api_router.get("/salt-spray/tests", response_model=List[SaltRecord])
async def salt_list(q: Optional[str] = None):
    query: dict = {"deleted_at": None}
    if q:
        query["$or"] = [
            {"meta.sample_id": {"$regex": q, "$options": "i"}},
            {"meta.product": {"$regex": q, "$options": "i"}},
            {"meta.batch": {"$regex": q, "$options": "i"}},
            {"meta.operator": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.salt_tests.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [SaltRecord(**doc) for doc in docs]


@api_router.get("/salt-spray/tests/{test_id}", response_model=SaltRecord)
async def salt_get(test_id: str):
    doc = await db.salt_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    return SaltRecord(**doc)


@api_router.put("/salt-spray/tests/{test_id}", response_model=SaltRecord)
async def salt_update(test_id: str, upd: SaltUpdate):
    doc = await db.salt_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    changes = upd.model_dump(exclude_none=True)
    # Freeze the original AI verdict before the first correction (legacy records)
    if doc.get("ai_grid_boxes") is None:
        orig = SaltRecord(**doc)
        changes["ai_grid_boxes"] = orig.ai_grid_boxes
        changes["ai_rusted_box_count"] = orig.ai_rusted_box_count
        changes["ai_grade"] = orig.ai_grade
    inspector_touched = any(k in changes for k in ("inspector_count", "inspector_name", "inspector_notes"))
    if "inspector_count" in changes:
        ic = int(changes["inspector_count"])
        if ic < 0:
            changes["inspector_count"] = None
            changes["inspector_grade"] = None
        else:
            ic = min(100, ic)
            changes["inspector_count"] = ic
            changes["inspector_grade"] = salt_grade_for(ic)
    if inspector_touched:
        changes["inspector_at"] = now_iso()
    if "grid_boxes" in changes:
        boxes = [bool(v) for v in changes["grid_boxes"][:100]]
        boxes.extend([False] * (100 - len(boxes)))
        changes["grid_boxes"] = boxes
        changes["rusted_box_count"] = sum(boxes)
    elif "rusted_box_count" in changes:
        count = max(0, min(100, int(changes["rusted_box_count"])))
        changes["rusted_box_count"] = count
        changes["grid_boxes"] = [i < count for i in range(100)]
    if "rusted_box_count" in changes:
        grade = salt_grade_for(changes["rusted_box_count"])
        changes["grade"] = grade
        changes["grade_label"] = SALT_GRADES[grade]["label"]
        changes["grade_status"] = SALT_GRADES[grade]["status"]
    if not changes:
        return SaltRecord(**doc)
    result_touched = any(k in changes for k in ("grid_boxes", "rusted_box_count", "ai_summary", "recommendation"))
    if result_touched:
        changes["edited"] = True
        changes["edited_at"] = now_iso()
    merged = SaltRecord(**{**doc, **changes})
    changes["method_results"] = {**merged.method_results, merged.method: _salt_snapshot(merged.model_dump(exclude={"method_results"}))}
    await db.salt_tests.update_one({"id": test_id}, {"$set": changes})
    updated = await db.salt_tests.find_one({"id": test_id}, {"_id": 0})
    return SaltRecord(**updated)


@api_router.post("/salt-spray/tests/{test_id}/locate-grid", response_model=SaltRecord)
async def salt_locate_grid(test_id: str):
    doc = await db.salt_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    if not (SaltRecord(**doc).method_results.get("zone")):
        raise HTTPException(status_code=400, detail="Metode Active Zone belum dianalisa untuk inspeksi ini.")
    try:
        content, _ = await run_in_threadpool(get_source_object, doc["image_path"])
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    small = await run_in_threadpool(_downscale_for_ai, content, 2200)
    try:
        corners = await run_salt_locate(base64.b64encode(small).decode("utf-8"))
    except Exception as e:
        logger.exception("Rust grid locate failed")
        raise HTTPException(status_code=502, detail=f"AI Vision gagal mendeteksi grid: {friendly_ai_error(e)}")
    if not corners:
        raise HTTPException(status_code=422, detail="Posisi grid tidak terdeteksi pada foto.")
    rec = SaltRecord(**doc)
    mr = dict(rec.method_results)
    zone = dict(mr.get("zone") or {})
    zone["grid_corners"] = corners
    mr["zone"] = zone
    sets = {"method_results": mr}
    if rec.method == "zone":
        sets["grid_corners"] = corners
    await db.salt_tests.update_one({"id": test_id}, {"$set": sets})
    updated = await db.salt_tests.find_one({"id": test_id}, {"_id": 0})
    return SaltRecord(**updated)


class SaltMethodRequest(BaseModel):
    method: str


async def _set_active_salt_method(test_id: str, method: str, new_result: Optional[dict] = None) -> SaltRecord:
    doc = await db.salt_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    rec = SaltRecord(**doc)
    mr = dict(rec.method_results)
    mr[rec.method] = _salt_snapshot(rec.model_dump(exclude={"method_results"}))  # persist current active
    if new_result is not None:
        mr[method] = new_result
    snap = mr.get(method)
    if not snap:
        raise HTTPException(status_code=400, detail=f"Metode {SALT_METHODS.get(method, method)} belum dianalisa. Jalankan analisa terlebih dahulu.")
    sets = {k: snap.get(k) for k in SALT_SNAPSHOT_KEYS}
    sets["method"] = method
    sets["method_results"] = mr
    await db.salt_tests.update_one({"id": test_id}, {"$set": sets})
    updated = await db.salt_tests.find_one({"id": test_id}, {"_id": 0})
    return SaltRecord(**updated)


@api_router.put("/salt-spray/tests/{test_id}/method", response_model=SaltRecord)
async def salt_switch_method(test_id: str, req: SaltMethodRequest):
    """Make an already-analyzed method the official (active) result."""
    return await _set_active_salt_method(test_id, _salt_norm_method(req.method))


async def _run_salt_method_job(job_id: str, test_id: str, method: str):
    try:
        doc = await db.salt_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Rust inspection not found")
        try:
            content, _ = await run_in_threadpool(get_source_object, doc["image_path"])
        except Exception:
            raise HTTPException(status_code=404, detail="Image not found in storage")
        small = await run_in_threadpool(_downscale_for_ai, content, 2200)
        try:
            ai = await run_salt_vision(base64.b64encode(small).decode("utf-8"), method)
        except Exception as e:
            logger.exception("Rust B117 method analysis failed")
            raise HTTPException(status_code=502, detail=f"AI Vision analysis failed: {friendly_ai_error(e)}")
        await _set_active_salt_method(test_id, method, _salt_result_fields(ai, method))
        await db.salt_jobs.update_one({"id": job_id}, {"$set": {"status": "done", "record_id": test_id, "finished_at": now_iso()}})
    except HTTPException as e:
        await db.salt_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}})
    except Exception as e:
        logger.exception("rust method job failed")
        await db.salt_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}})


@api_router.post("/salt-spray/tests/{test_id}/method/analyze", response_model=SaltJob)
async def salt_analyze_method(test_id: str, req: SaltMethodRequest):
    """(Re)analyze the same photo with the chosen method; the result becomes the active one."""
    doc = await db.salt_tests.find_one({"id": test_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    job = SaltJob()
    await db.salt_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_salt_method_job(job.id, test_id, _salt_norm_method(req.method)))
    return job


@api_router.delete("/salt-spray/tests/{test_id}")
async def salt_delete(test_id: str):
    res = await db.salt_tests.update_one({"id": test_id}, {"$set": {"deleted_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Rust inspection not found")
    return {"ok": True}


@api_router.get("/salt-spray/dashboard")
async def salt_dashboard():
    docs = await db.salt_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", -1).to_list(500)
    records = [SaltRecord(**doc) for doc in docs]
    counts = {grade: 0 for grade in SALT_GRADES}
    for record in records:
        counts[record.grade] = counts.get(record.grade, 0) + 1
    avg = round(sum(r.rusted_box_count for r in records) / len(records), 1) if records else 0
    return {"latest": records[0].model_dump() if records else None, "total": len(records), "grade_counts": counts, "average_rusted_boxes": avg}


@api_router.get("/salt-spray/trend")
async def salt_trend():
    docs = await db.salt_tests.find({"deleted_at": None}, {"_id": 0}).sort("created_at", 1).to_list(500)
    return [{"id": d["id"], "sample_id": d.get("meta", {}).get("sample_id", ""), "rusted_box_count": d.get("rusted_box_count", 0), "grade": d.get("grade", "A"), "created_at": d.get("created_at")} for d in docs]


@api_router.get("/salt-spray/reference-scale")
async def salt_reference_scale():
    return {"title": "ASTM B117 Salt Spray 100-Box Scale", "measurement_area": "50 x 50 mm central surface", "plate": "60 x 80 mm; 0.5 mm cross cuts; 100 boxes of 5 x 5 mm", "grades": SALT_GRADES}


# ---------------------------------------------------------------------------
# Salt Spray — Kartu Pengamatan (Observation Cards)
# 1 foto berisi 4 plat uji -> AI Vision mendeteksi & memotong 4 plat -> tiap plat
# dinilai dengan Metode Seluruh Gambar (potongan plat = active zone, 10x10 rata).
# Kotak berkarat ditandai (merah bernomor) dan dapat dikoreksi inspector.
# 1 record = 1 foto + 4 kode sample (Sample 1..4) + No. Urut + Durasi.
# ---------------------------------------------------------------------------
OBS_PLATE_COUNT = 4

SALT_OBS_DETECT_PROMPT = """You are a senior corrosion-laboratory analyst (ASTM B117 salt spray) preparing panels for rating.

The image is ONE operator photo that should contain FOUR flat metal test panels (plates) photographed together after salt-spray exposure. They are usually placed side by side in one row, but may also be in a column or a 2 x 2 layout.

TASK: locate every test panel precisely.
- For each panel return box_2d = [ymin, xmin, ymax, xmax] as integers 0-1000 relative to the full image (y down, x right).
- The box must hug the panel's own metal edges tightly: include the full panel surface (all four edges and corners), exclude table/background, shadows, rulers, holders and neighbouring panels.
- Boxes of different panels must NOT overlap. One object per physical panel. Never split one panel into two, never merge two panels.
- Ignore labels/tape/handwriting as separate objects (they belong to the panel they are on).
- Order the panels in reading order: top-to-bottom rows, then left-to-right inside a row.

Return ONLY valid minified JSON:
{"panel_count":<integer>,"layout":"row|column|grid|other","panels":[{"index":1,"box_2d":[ymin,xmin,ymax,xmax],"label":"<visible handwritten/printed code on the panel, or empty>"}]}"""

SALT_OBS_GRADE_PROMPT = """You are a SENIOR, highly experienced metallurgical corrosion analyst rating ONE ASTM B117 salt-spray test panel. Rate like a meticulous professional inspector: careful, consistent, conservative, and never guessing.

You receive TWO images of the SAME single panel:
1) IMAGE 1 = clean photo of the panel (use it to judge true colour/texture of corrosion).
2) IMAGE 2 = the same photo with a reference 10 x 10 grid drawn on top; every box carries its number 1-100.

METHOD — WHOLE IMAGE (Seluruh Gambar):
- The ACTIVE ZONE is the ENTIRE image. It is divided evenly into 10 x 10 = 100 boxes, each box = 10% of image width x 10% of image height.
- Box 1 = top-left, box 10 = top-right, box 91 = bottom-left, box 100 = bottom-right (row-major). Box number = row*10 + column + 1 (row, column starting at 0). Do NOT rotate or re-frame.

PROFESSIONAL RATING PROCEDURE (do it internally, row by row):
1. Scan row 1 (boxes 1-10) left to right, then row 2 (11-20) ... until row 10 (91-100). Inspect each box in IMAGE 1, use IMAGE 2 only to know the box boundaries/numbers.
2. A box is RUSTED when it contains at least one naked-eye-visible corrosion product ON THE METAL PANEL: red rust, orange/brown rust spots, rust bloom, rust streaks/run-off, creep from scribe or edges, pitting with rust, or blistering with rust staining. Even one small genuine rust spot makes the box rusted.
3. If one rust area crosses a box boundary, every box it touches is rusted.
4. NOT rust: glare, specular reflections, water droplets, salt deposits (white), white/grey zinc corrosion without red-brown colour, shadows, dust, fingerprints, scratches without rust, handwritten marks, label tape, holes, the grid lines/numbers drawn in IMAGE 2, and any background outside the panel.
5. Boxes that show only background (not panel) are never rusted.
6. Double-check your list against IMAGE 1 before answering; remove anything you are not confident is real corrosion, and add any spot you missed.

GRADE RULES: A = 0 rusted boxes; B = 1-10; C = 11-25; D = 26-50; E = 51-100.

Return ONLY valid minified JSON with EXACTLY these keys:
{"rusted_boxes":[<sorted unique box numbers 1-100 that are rusted>],"rusted_box_count":<integer = length of rusted_boxes>,"grade":"A|B|C|D|E","confidence":<number 0-100>,"specimen_box_count":<boxes containing any panel surface>,"rust_spread":"<none|localized|scattered|clustered|widespread|near-total>","summary":"<short professional Indonesian note: where the rust is (rows/columns/edges), type and severity>"}"""


def _obs_font(sz: int):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", sz)
    except Exception:
        try:
            return ImageFont.load_default(sz)
        except Exception:
            return ImageFont.load_default()


def _obs_grid_overlay(content: bytes) -> bytes:
    """Draw the numbered 10x10 reference grid over a plate crop (helps the AI localise boxes)."""
    im = PILImage.open(io.BytesIO(content)).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    lw = max(1, round(min(W, H) / 400))
    for i in range(1, 10):
        x = round(W * i / 10)
        y = round(H * i / 10)
        d.line([(x, 0), (x, H)], fill=(0, 230, 255), width=lw)
        d.line([(0, y), (W, y)], fill=(0, 230, 255), width=lw)
    d.rectangle([0, 0, W - 1, H - 1], outline=(0, 230, 255), width=lw)
    fnt = _obs_font(max(9, round(min(W, H) / 10 * 0.22)))
    for n in range(100):
        r, c = divmod(n, 10)
        d.text((W * c / 10 + 3, H * r / 10 + 2), str(n + 1), font=fnt, fill=(255, 255, 0), stroke_width=2, stroke_fill=(0, 0, 0))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=90)
    return out.getvalue()


def _obs_norm_panels(ai: dict) -> list:
    panels = []
    for p in (ai or {}).get("panels") or []:
        try:
            y0, x0, y1, x1 = [max(0.0, min(1000.0, float(v))) / 1000 for v in p.get("box_2d")]
        except Exception:
            continue
        if x1 - x0 < 0.03 or y1 - y0 < 0.03:
            continue
        panels.append({"bbox": [x0, y0, x1 - x0, y1 - y0], "label": str(p.get("label") or "").strip()})
    return panels


def _obs_sort_key(p: dict):
    x, y, w, h = p["bbox"]
    return (round((y + h / 2) / 0.25), x)


def _obs_boxes_from_ai(ai: dict) -> List[bool]:
    boxes = [False] * 100
    nums = ai.get("rusted_boxes") if isinstance(ai, dict) else None
    if isinstance(nums, list) and nums and not isinstance(nums[0], bool):
        for v in nums:
            try:
                n = int(float(v))
            except (TypeError, ValueError):
                continue
            if 1 <= n <= 100:
                boxes[n - 1] = True
        return boxes
    b, _ = _salt_grid_from_ai({"grid_boxes": ai.get("grid_boxes") or nums or [], "rusted_box_count": ai.get("rusted_box_count", 0)})
    return b


async def run_obs_detect(image_b64: str) -> list:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"salt-obs-detect-{uuid.uuid4()}",
        system_message="You are a precise object-localisation model for laboratory test panels. Output JSON only.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    resp = await _llm_send_with_retry(chat, UserMessage(text=SALT_OBS_DETECT_PROMPT, file_contents=[ImageContent(image_base64=image_b64)]))
    return _obs_norm_panels(_parse_ai_json(resp if isinstance(resp, str) else str(resp)))


async def run_obs_grade(clean_b64: str, grid_b64: str) -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"salt-obs-grade-{uuid.uuid4()}",
        system_message="You are a senior ASTM B117 corrosion analyst. You rate meticulously and output JSON only.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    resp = await _llm_send_with_retry(chat, UserMessage(
        text=SALT_OBS_GRADE_PROMPT,
        file_contents=[ImageContent(image_base64=clean_b64), ImageContent(image_base64=grid_b64)],
    ))
    return _parse_ai_json(resp if isinstance(resp, str) else str(resp))


class SaltObsPlate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index: int = 1
    code: str = ""
    bbox: Optional[List[float]] = None  # [x, y, w, h] normalized in the original photo
    crop_path: Optional[str] = None
    label: str = ""  # label read by AI on the panel (hint only)
    grid_boxes: List[bool] = Field(default_factory=lambda: [False] * 100)
    ai_grid_boxes: Optional[List[bool]] = None
    rusted_box_count: int = 0
    grade: str = "A"
    ai_rusted_box_count: Optional[int] = None
    ai_grade: Optional[str] = None
    confidence: float = 0
    rust_spread: str = ""
    summary: str = ""
    edited: bool = False


class SaltObsCard(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    seq: int = 1
    duration_label: str = ""
    hours: Optional[float] = None  # jam pengamatan (kolom Hours di tabel report)
    photo_path: Optional[str] = None
    detection: str = ""  # ai | fallback
    plates: List[SaltObsPlate] = Field(default_factory=list)
    ai_model: str = "gemini-3.1-pro-preview"
    series_id: Optional[str] = None  # set when the series is archived to History Pengamatan
    created_at: str = Field(default_factory=now_iso)
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


class SaltObsCardUpsert(BaseModel):
    seq: int = 1
    duration_label: str = ""
    hours: Optional[float] = None
    photo_path: Optional[str] = None
    detection: str = ""
    plates: List[SaltObsPlate] = Field(default_factory=list)


class SaltObsDetectRequest(BaseModel):
    photo_path: str


class SaltObsJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    stage: str = "Mendeteksi plat…"
    photo_path: str = ""
    detection: str = ""
    plates: List[SaltObsPlate] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


def _norm_plate(p: SaltObsPlate, i: int) -> dict:
    boxes = [bool(v) for v in (p.grid_boxes or [])[:100]]
    boxes.extend([False] * (100 - len(boxes)))
    ai_boxes = p.ai_grid_boxes
    if ai_boxes is not None:
        ai_boxes = [bool(v) for v in ai_boxes[:100]] + [False] * max(0, 100 - len(ai_boxes))
    count = sum(boxes)
    ai_count = sum(ai_boxes) if ai_boxes is not None else count
    return {
        **p.model_dump(),
        "index": i + 1,
        "code": str(p.code or "").strip(),
        "grid_boxes": boxes,
        "ai_grid_boxes": ai_boxes if ai_boxes is not None else list(boxes),
        "rusted_box_count": count,
        "grade": salt_grade_for(count),
        "ai_rusted_box_count": ai_count,
        "ai_grade": salt_grade_for(ai_count),
        "edited": ai_boxes is not None and boxes != ai_boxes,
    }


def _clean_obs_plates(plates: List[SaltObsPlate]) -> List[dict]:
    return [_norm_plate(p, i) for i, p in enumerate((plates or [])[:OBS_PLATE_COUNT])]


def _obs_prepare_crops(content: bytes, panels: list) -> tuple:
    """Return (detection_mode, [(bbox, crop_bytes, label)]) for exactly 4 plates."""
    detection = "ai"
    items = []
    if len(panels) == OBS_PLATE_COUNT:
        for p in sorted(panels, key=_obs_sort_key):
            try:
                items.append((p["bbox"], _crop_bbox(content, p["bbox"], pad=0.0), p["label"]))
            except Exception:
                items = []
                break
    if len(items) != OBS_PLATE_COUNT:
        detection = "fallback"
        items = [([i / OBS_PLATE_COUNT, 0.0, 1 / OBS_PLATE_COUNT, 1.0], _crop_column(content, i, OBS_PLATE_COUNT), "") for i in range(OBS_PLATE_COUNT)]
    return detection, items


async def _obs_grade_one(crop: bytes) -> dict:
    small = await run_in_threadpool(_downscale_for_ai, crop, 1600)
    grid = await run_in_threadpool(_obs_grid_overlay, small)
    return await run_obs_grade(base64.b64encode(small).decode("utf-8"), base64.b64encode(grid).decode("utf-8"))


async def _run_obs_detect_job(job_id: str, photo_path: str):
    async def stage(text):
        await db.salt_obs_jobs.update_one({"id": job_id}, {"$set": {"stage": text}})
    try:
        try:
            content, _ = await run_in_threadpool(get_source_object, photo_path)
        except Exception:
            raise HTTPException(status_code=404, detail="Foto tidak ditemukan di storage")
        small = await run_in_threadpool(_downscale_for_ai, content, 2200)
        try:
            panels = await run_obs_detect(base64.b64encode(small).decode("utf-8"))
        except Exception as e:
            if _is_rate_limit_error(e):
                raise HTTPException(status_code=502, detail=friendly_ai_error(e))
            logger.warning("Salt obs plate detection failed; using column fallback", exc_info=True)
            panels = []
        detection, items = await run_in_threadpool(_obs_prepare_crops, content, panels)
        await stage(f"{'4 plat terdeteksi' if detection == 'ai' else 'Plat dibagi 4 kolom'} — menilai kotak berkarat…")
        try:
            results = await asyncio.gather(*[_obs_grade_one(crop) for _, crop, _ in items])
        except Exception as e:
            logger.exception("Salt obs plate grading failed")
            raise HTTPException(status_code=502, detail=f"AI Vision gagal menilai plat: {friendly_ai_error(e)}")
        plates = []
        for i, ((bbox, crop, label), ai) in enumerate(zip(items, results)):
            crop_path = f"{APP_NAME}/salt/observations/{job_id}/plate_{i + 1}.jpg"
            try:
                await run_in_threadpool(put_object, crop_path, crop, "image/jpeg")
            except Exception:
                logger.warning("Could not store salt obs crop", exc_info=True)
                crop_path = None
            boxes = _obs_boxes_from_ai(ai)
            plates.append(_norm_plate(SaltObsPlate(
                bbox=[round(float(v), 4) for v in bbox], crop_path=crop_path, label=label,
                grid_boxes=boxes, ai_grid_boxes=list(boxes), confidence=_clamp(ai.get("confidence"), 0, 100),
                rust_spread=str(ai.get("rust_spread", "")), summary=str(ai.get("summary", "")),
            ), i))
        await db.salt_obs_jobs.update_one({"id": job_id}, {"$set": {
            "status": "done", "stage": "Selesai", "detection": detection, "plates": plates, "finished_at": now_iso()}})
    except HTTPException as e:
        await db.salt_obs_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": str(e.detail), "finished_at": now_iso()}})
    except Exception as e:
        logger.exception("salt obs detect job failed")
        await db.salt_obs_jobs.update_one({"id": job_id}, {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}})


@api_router.post("/salt-spray/observations/detect/start", response_model=SaltObsJob)
async def salt_obs_detect_start(req: SaltObsDetectRequest):
    try:
        await run_in_threadpool(get_source_object, req.photo_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Foto tidak ditemukan di storage")
    job = SaltObsJob(photo_path=req.photo_path)
    await db.salt_obs_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_obs_detect_job(job.id, req.photo_path))
    return job


@api_router.get("/salt-spray/observations/detect/jobs/{job_id}", response_model=SaltObsJob)
async def salt_obs_detect_status(job_id: str):
    doc = await db.salt_obs_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    return SaltObsJob(**doc)


def _obs_parse_hours(label) -> Optional[float]:
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(label or ""))
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    if re.search(r"hari|day", str(label), re.I):
        v *= 24
    return v


def _fmt_hours(h: float) -> str:
    return str(int(h)) if float(h).is_integer() else str(round(h, 2))


def _obs_hours_fields(req: "SaltObsCardUpsert") -> dict:
    hours = req.hours if req.hours is not None else _obs_parse_hours(req.duration_label)
    if hours is not None:
        hours = max(0.0, float(hours))
        return {"hours": hours, "duration_label": f"{_fmt_hours(hours)} Jam"}
    return {"hours": None, "duration_label": str(req.duration_label or "").strip()}


class SaltObsHeader(BaseModel):
    model_config = ConfigDict(extra="ignore")
    operator: str = ""
    start_time: str = ""  # HH:MM
    start_date: str = ""  # YYYY-MM-DD
    specimen_position: str = "15°-30°"
    pressure: str = "13 psi"
    water: str = "10 L Aquadest + 530 gr NaCl 5%"
    chamber_temp_min: str = "35.1"
    chamber_temp_max: str = "36.7"
    saturated_air_temp: str = "46°C"
    ph: str = "6.5 - 7.2 di suhu 35°C"
    plate_grinding: bool = False
    plate_grinding_note: str = ""
    updated_at: Optional[str] = None


@api_router.get("/salt-spray/observation-header", response_model=SaltObsHeader)
async def salt_obs_header_get():
    doc = await db.salt_obs_header.find_one({"id": "default"}, {"_id": 0, "id": 0})
    return SaltObsHeader(**(doc or {}))


@api_router.put("/salt-spray/observation-header", response_model=SaltObsHeader)
async def salt_obs_header_put(req: SaltObsHeader):
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in req.model_dump().items()}
    data["updated_at"] = now_iso()
    await db.salt_obs_header.update_one({"id": "default"}, {"$set": data}, upsert=True)
    return SaltObsHeader(**data)


async def cleanup_legacy_obs_cards():
    """Old manual-format cards (per-sample photos, S/D types) are retired."""
    res = await db.salt_observations.update_many(
        {"plates": {"$exists": False}, "deleted_at": None}, {"$set": {"deleted_at": now_iso()}})
    if res.modified_count:
        logger.info("Retired %d legacy salt observation cards", res.modified_count)
    async for d in db.salt_observations.find({"plates": {"$exists": True}, "hours": {"$exists": False}}, {"_id": 0, "id": 1, "duration_label": 1}):
        h = _obs_parse_hours(d.get("duration_label"))
        await db.salt_observations.update_one({"id": d["id"]}, {"$set": {"hours": h}})


ACTIVE_OBS_QUERY = {"deleted_at": None, "plates": {"$exists": True}, "series_id": None}


@api_router.get("/salt-spray/observations", response_model=List[SaltObsCard])
async def salt_obs_list():
    docs = await db.salt_observations.find(ACTIVE_OBS_QUERY, {"_id": 0}).sort([("hours", 1), ("seq", 1)]).to_list(500)
    return [SaltObsCard(**doc) for doc in docs]


@api_router.get("/salt-spray/observations/{card_id}", response_model=SaltObsCard)
async def salt_obs_get(card_id: str):
    doc = await db.salt_observations.find_one({"id": card_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Kartu pengamatan tidak ditemukan")
    return SaltObsCard(**doc)


def _validate_obs(req: SaltObsCardUpsert):
    if not req.photo_path:
        raise HTTPException(status_code=400, detail="Foto 4 plat wajib diunggah.")
    if len(req.plates or []) != OBS_PLATE_COUNT:
        raise HTTPException(status_code=400, detail="Hasil deteksi harus berisi 4 plat.")
    if any(not str(p.code or "").strip() for p in req.plates):
        raise HTTPException(status_code=400, detail="Kode Sample 1-4 wajib diisi.")


@api_router.post("/salt-spray/observations", response_model=SaltObsCard)
async def salt_obs_create(req: SaltObsCardUpsert):
    _validate_obs(req)
    card = SaltObsCard(
        seq=int(req.seq or 1),
        **_obs_hours_fields(req),
        photo_path=req.photo_path,
        detection=req.detection or "",
        plates=[SaltObsPlate(**p) for p in _clean_obs_plates(req.plates)],
    )
    await db.salt_observations.insert_one(card.model_dump())
    return card


@api_router.put("/salt-spray/observations/{card_id}", response_model=SaltObsCard)
async def salt_obs_update(card_id: str, req: SaltObsCardUpsert):
    doc = await db.salt_observations.find_one({"id": card_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Kartu pengamatan tidak ditemukan")
    if doc.get("series_id"):
        raise HTTPException(status_code=409, detail="Kartu sudah diarsipkan di History Pengamatan (read-only).")
    _validate_obs(req)
    changes = {
        "seq": int(req.seq or 1),
        **_obs_hours_fields(req),
        "photo_path": req.photo_path,
        "detection": req.detection or doc.get("detection", ""),
        "plates": _clean_obs_plates(req.plates),
        "updated_at": now_iso(),
    }
    await db.salt_observations.update_one({"id": card_id}, {"$set": changes})
    updated = await db.salt_observations.find_one({"id": card_id}, {"_id": 0})
    return SaltObsCard(**updated)


@api_router.delete("/salt-spray/observations/{card_id}")
async def salt_obs_delete(card_id: str):
    res = await db.salt_observations.update_one({"id": card_id}, {"$set": {"deleted_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Kartu pengamatan tidak ditemukan")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Salt Spray — History Pengamatan (archived observation series)
# 1 seri = snapshot header Data Pengujian + semua kartu pengamatan aktif.
# ---------------------------------------------------------------------------
HEADER_CARRY_FIELDS = ("specimen_position", "pressure", "water", "chamber_temp_min", "chamber_temp_max", "saturated_air_temp", "ph")


def _obs_series_summary(cards: list) -> dict:
    """Python twin of frontend buildReport(): per-sample reach-100% hour, latest %, duration."""
    data, order, alias = {}, [], {}
    for c in sorted(cards, key=lambda c: ((c.get("hours") if c.get("hours") is not None else -1), c.get("seq") or 0)):
        h = c.get("hours")
        if h is None:
            continue
        for p in c.get("plates") or []:
            raw = re.sub(r"\s+", " ", str(p.get("code") or "").strip())
            if not raw:
                continue
            key = raw.upper()
            if key not in alias:
                alias[key] = raw
                data[raw] = {}
                order.append(raw)
            data[alias[key]][float(h)] = min(100, sum(1 for b in (p.get("grid_boxes") or []) if b))
    samples = []
    for code in order:
        hs = sorted(data[code])
        reach = next((h for h in hs if data[code][h] >= 100), None)
        samples.append({"code": code, "reach_hour": reach, "last_pct": 100 if reach is not None else (data[code][hs[-1]] if hs else 0)})
    all_reached = bool(samples) and all(s["reach_hour"] is not None for s in samples)
    hours = [float(c["hours"]) for c in cards if c.get("hours") is not None]
    return {
        "samples": samples,
        "all_reached": all_reached,
        "duration_hours": max(s["reach_hour"] for s in samples) if all_reached else None,
        "max_hours": max(hours) if hours else None,
    }


class SaltObsSeriesSample(BaseModel):
    code: str
    reach_hour: Optional[float] = None
    last_pct: float = 0


class SaltObsSeries(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    number: int = 1
    header: SaltObsHeader = Field(default_factory=SaltObsHeader)
    samples: List[SaltObsSeriesSample] = Field(default_factory=list)
    all_reached: bool = False
    stopped_early: bool = False
    duration_hours: Optional[float] = None
    max_hours: Optional[float] = None
    card_count: int = 0
    cover_photo_path: Optional[str] = None
    note: str = ""
    completed_at: str = Field(default_factory=now_iso)
    deleted_at: Optional[str] = None


class SaltObsSeriesDetail(SaltObsSeries):
    cards: List[SaltObsCard] = Field(default_factory=list)


class SaltObsCompleteRequest(BaseModel):
    force: bool = False
    note: str = ""


@api_router.get("/salt-spray/observation-series/active-summary")
async def salt_series_active_summary():
    cards = await db.salt_observations.find(ACTIVE_OBS_QUERY, {"_id": 0}).to_list(500)
    return {**_obs_series_summary(cards), "card_count": len(cards)}


@api_router.post("/salt-spray/observation-series/complete", response_model=SaltObsSeries)
async def salt_series_complete(req: SaltObsCompleteRequest):
    cards = await db.salt_observations.find(ACTIVE_OBS_QUERY, {"_id": 0}).sort([("hours", 1), ("seq", 1)]).to_list(500)
    if not cards:
        raise HTTPException(status_code=400, detail="Belum ada kartu pengamatan untuk diselesaikan.")
    summary = _obs_series_summary(cards)
    if not summary["all_reached"] and not req.force:
        pending = [s["code"] for s in summary["samples"] if s["reach_hour"] is None]
        raise HTTPException(status_code=409, detail=f"Belum semua sample 100%: {', '.join(pending) or '-'}")
    hdr_doc = await db.salt_obs_header.find_one({"id": "default"}, {"_id": 0, "id": 0}) or {}
    header = SaltObsHeader(**hdr_doc)
    last = await db.salt_obs_series.find_one({"deleted_at": None}, {"_id": 0, "number": 1}, sort=[("number", -1)])
    cover = next((c.get("photo_path") for c in reversed(cards) if c.get("photo_path")), None)
    series = SaltObsSeries(
        number=(last or {}).get("number", 0) + 1,
        header=header,
        samples=[SaltObsSeriesSample(**s) for s in summary["samples"]],
        all_reached=summary["all_reached"],
        stopped_early=not summary["all_reached"],
        duration_hours=summary["duration_hours"],
        max_hours=summary["max_hours"],
        card_count=len(cards),
        cover_photo_path=cover,
        note=req.note.strip(),
    )
    await db.salt_obs_series.insert_one(series.model_dump())
    await db.salt_observations.update_many({"id": {"$in": [c["id"] for c in cards]}}, {"$set": {"series_id": series.id}})
    # Fresh header for the next series: keep chamber conditions, clear per-run fields.
    fresh = SaltObsHeader().model_dump()
    for k in HEADER_CARRY_FIELDS:
        fresh[k] = getattr(header, k)
    fresh["updated_at"] = now_iso()
    await db.salt_obs_header.update_one({"id": "default"}, {"$set": fresh}, upsert=True)
    return series


@api_router.get("/salt-spray/observation-series", response_model=List[SaltObsSeries])
async def salt_series_list():
    docs = await db.salt_obs_series.find({"deleted_at": None}, {"_id": 0}).sort("completed_at", -1).to_list(500)
    return [SaltObsSeries(**d) for d in docs]


@api_router.get("/salt-spray/observation-series/{series_id}", response_model=SaltObsSeriesDetail)
async def salt_series_get(series_id: str):
    doc = await db.salt_obs_series.find_one({"id": series_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Seri pengujian tidak ditemukan")
    cards = await db.salt_observations.find({"series_id": series_id, "deleted_at": None}, {"_id": 0}).sort([("hours", 1), ("seq", 1)]).to_list(500)
    return SaltObsSeriesDetail(**doc, cards=[SaltObsCard(**c) for c in cards])


@api_router.delete("/salt-spray/observation-series/{series_id}")
async def salt_series_delete(series_id: str):
    ts = now_iso()
    res = await db.salt_obs_series.update_one({"id": series_id, "deleted_at": None}, {"$set": {"deleted_at": ts}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Seri pengujian tidak ditemukan")
    await db.salt_observations.update_many({"series_id": series_id, "deleted_at": None}, {"$set": {"deleted_at": ts}})
    return {"ok": True}


@api_router.post("/salt-spray/observation-series/{series_id}/reopen")
async def salt_series_reopen(series_id: str):
    doc = await db.salt_obs_series.find_one({"id": series_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Seri pengujian tidak ditemukan")
    if await db.salt_observations.count_documents(ACTIVE_OBS_QUERY) > 0:
        raise HTTPException(status_code=409, detail="Kartu Pengamatan masih berisi seri aktif. Selesaikan atau kosongkan dulu sebelum membuka kembali.")
    await db.salt_observations.update_many({"series_id": series_id, "deleted_at": None}, {"$set": {"series_id": None}})
    hdr = {**SaltObsHeader(**(doc.get("header") or {})).model_dump(), "updated_at": now_iso()}
    await db.salt_obs_header.update_one({"id": "default"}, {"$set": hdr}, upsert=True)
    await db.salt_obs_series.update_one({"id": series_id}, {"$set": {"deleted_at": now_iso(), "reopened": True}})
    return {"ok": True}


COPPER_SEED = [
    {"sample_id": "CU-2026-05-30-001", "product": "Diesel Fuel B30", "batch": "LOT-CU-0530-A", "operator": "Karis Setia",
     "classification": "1a", "confidence": 97.4,
     "img": "https://images.unsplash.com/photo-1605152276897-4f618f831968?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Warna oranye muda hampir sama dengan strip terpoles, cocok dengan kelas 1a (slight tarnish).",
     "recommendation": "Bahan bakar dalam kondisi baik, tidak korosif terhadap tembaga."},
    {"sample_id": "CU-2026-05-28-004", "product": "Gasoline RON 92", "batch": "LOT-CU-0528-C", "operator": "Karis Setia",
     "classification": "1b", "confidence": 95.0,
     "img": "https://images.unsplash.com/photo-1567427017947-545c5f8d16ad?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Warna oranye gelap merata pada strip cocok dengan kelas 1b (slight tarnish).",
     "recommendation": "Masih memenuhi batas umum spesifikasi (<= 1b). Lanjutkan pemantauan rutin."},
    {"sample_id": "CU-2026-05-25-002", "product": "Aviation Turbine Fuel", "batch": "LOT-CU-0525-B", "operator": "Dwi Agus",
     "classification": "2c", "confidence": 92.6,
     "img": "https://images.unsplash.com/photo-1614308457932-e16d85c5d053?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Muncul warna multiwarna lavender di atas merah claret, cocok dengan kelas 2c (moderate tarnish).",
     "recommendation": "Melebihi batas 1b — periksa kandungan sulfur aktif pada bahan bakar."},
    {"sample_id": "CU-2026-05-22-007", "product": "Marine Gas Oil", "batch": "LOT-CU-0522-D", "operator": "Dwi Agus",
     "classification": "4b", "confidence": 90.1,
     "img": "https://images.unsplash.com/photo-1581093458791-9d09a5c0a5b9?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Strip menghitam pekat tanpa kilau (graphite black), cocok dengan kelas 4b (corrosion).",
     "recommendation": "Sangat korosif — jangan gunakan, lakukan treatment/penyaringan sebelum dipakai."},
    {"sample_id": "CU-2026-05-20-011", "product": "Diesel Fuel B35", "batch": "LOT-CU-0520-E", "operator": "Karis Setia",
     "classification": "1a", "confidence": 96.8,
     "img": "https://images.unsplash.com/photo-1605152276897-4f618f831968?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Warna oranye muda seragam nyaris identik dengan strip terpoles, sesuai kelas 1a.",
     "recommendation": "Bahan bakar tidak korosif — lulus, lanjutkan penggunaan normal."},
    {"sample_id": "CU-2026-05-18-013", "product": "Kerosene", "batch": "LOT-CU-0518-F", "operator": "Rina Pertiwi",
     "classification": "2a", "confidence": 93.7,
     "img": "https://images.unsplash.com/photo-1567427017947-545c5f8d16ad?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Muncul warna merah claret pada permukaan strip, sesuai kelas 2a (moderate tarnish).",
     "recommendation": "Sedikit di atas 1b — pantau kandungan sulfur, ulangi uji pada batch berikutnya."},
    {"sample_id": "CU-2026-05-15-016", "product": "Gasoline RON 95", "batch": "LOT-CU-0515-G", "operator": "Rina Pertiwi",
     "classification": "1b", "confidence": 95.9,
     "img": "https://images.unsplash.com/photo-1614308457932-e16d85c5d053?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Oranye gelap merata tanpa perubahan warna lain, sesuai kelas 1b.",
     "recommendation": "Masih memenuhi spesifikasi umum (<= 1b), aman digunakan."},
    {"sample_id": "CU-2026-05-12-019", "product": "Biodiesel B100", "batch": "LOT-CU-0512-H", "operator": "Dwi Agus",
     "classification": "3b", "confidence": 91.4,
     "img": "https://images.unsplash.com/photo-1581093458791-9d09a5c0a5b9?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Warna magenta di atas dasar kecokelatan, sesuai kelas 3b (dark tarnish).",
     "recommendation": "Melebihi batas — evaluasi stabilitas oksidasi dan kandungan sulfur aktif."},
    {"sample_id": "CU-2026-05-10-022", "product": "Aviation Turbine Fuel", "batch": "LOT-CU-0510-I", "operator": "Karis Setia",
     "classification": "2d", "confidence": 92.0,
     "img": "https://images.unsplash.com/photo-1567427017947-545c5f8d16ad?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Warna keperakan-keunguan multiwarna, sesuai kelas 2d (moderate tarnish).",
     "recommendation": "Di atas 1b — konfirmasi hasil dengan uji ulang sebelum rilis batch."},
]


async def seed_copper():
    if await db.copper_tests.count_documents({}) > 0:
        return
    logger.info("Seeding demo Copper Strip tests...")
    base = datetime.now(timezone.utc)
    for i, s in enumerate(COPPER_SEED):
        cls = copper_class_for(s["classification"])
        rec = CopperRecord(
            image_path=s["img"],
            meta=CopperMeta(
                sample_id=s["sample_id"], product=s["product"], batch=s["batch"], operator=s["operator"],
                temperature_c=100, duration_hours=3,
            ),
            classification=cls["code"], class_label=cls["label"], group=cls["group"], color=cls["color"],
            description=cls["description"], severity=cls["severity"], status=cls["status"],
            confidence=s["confidence"], ai_summary=s["summary"], recommendation=s["recommendation"],
        )
        rec_dict = rec.model_dump()
        rec_dict["created_at"] = (base - timedelta(days=i * 3)).isoformat()
        await db.copper_tests.insert_one(rec_dict)


async def seed_copper_reference():
    """Store the ASTM D130 / IP 154 copper-strip standard chart (base64) + class
    metadata in MongoDB. Idempotent."""
    try:
        doc = {
            "key": "astm_d130_scale",
            "title": "ASTM Copper Strip Corrosion Standards (D130 / IP 154)",
            "note": "Freshly Polished · 1a–1b Slight Tarnish · 2a–3a Moderate Tarnish · 3b–3c Dark Tarnish · 4a–4c Corrosion. CLEAR (lulus) bila kelas 0/1a/1b.",
            "content_type": "image/jpeg",
            "image_base64": copper_reference_b64(),
            "classes": ASTM_D130_CLASSES,
            "updated_at": now_iso(),
        }
        await db.reference.replace_one({"key": "astm_d130_scale"}, doc, upsert=True)
    except Exception as e:
        logger.warning("seed_copper_reference failed: %s", e)



# ===========================================================================
# Generic modules — Copper Strip ASTM D130 & Rating DKA (manual entry)
# ===========================================================================
MODULES: Dict[str, Dict[str, Any]] = {
    "copper-strip": {
        "title": "Copper Strip ASTM D130",
        "description": "Uji korosi bilah tembaga (copper strip corrosion) sesuai standar ASTM D130.",
        "rating_options": ["1a", "1b", "2a", "2b", "2c", "2d", "2e", "3a", "3b", "4a", "4b", "4c"],
        "parameters": [
            {"key": "test_temperature", "label": "Test Temperature", "unit": "°C"},
            {"key": "test_duration", "label": "Test Duration", "unit": "hours"},
            {"key": "strip_appearance", "label": "Strip Appearance", "unit": ""},
            {"key": "tarnish_level", "label": "Tarnish Level", "unit": ""},
            {"key": "bath_medium", "label": "Bath Medium", "unit": ""},
        ],
    },
    "rating-dka": {
        "title": "Rating DKA",
        "description": "Penilaian Deposit / Karbon / Aging (DKA) pada minyak pelumas & bahan bakar.",
        "rating_options": ["A - Sangat Baik", "B - Baik", "C - Cukup", "D - Kurang", "E - Buruk"],
        "parameters": [
            {"key": "deposit_level", "label": "Deposit Level", "unit": "merit"},
            {"key": "carbon_residue", "label": "Carbon Residue", "unit": "% wt"},
            {"key": "oxidation_stability", "label": "Oxidation Stability", "unit": "min"},
            {"key": "sludge_content", "label": "Sludge Content", "unit": "mg/100ml"},
            {"key": "varnish_rating", "label": "Varnish Rating", "unit": "merit"},
            {"key": "color_change", "label": "Color Change", "unit": ""},
        ],
    },
}


def require_module(module: str) -> Dict[str, Any]:
    meta = MODULES.get(module)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown module '{module}'")
    return meta


class SampleCreate(BaseModel):
    sample_code: str
    sample_name: str
    product_type: str = ""
    operator: str = ""
    test_date: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    rating: str = ""
    notes: str = ""


class Sample(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    module: str
    sample_code: str
    sample_name: str
    product_type: str = ""
    operator: str = ""
    test_date: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    rating: str = ""
    notes: str = ""
    ai_analysis: Optional[str] = None
    ai_analyzed_at: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


@api_router.get("/")
async def root():
    return {"message": "Elastech Production API"}


@api_router.get("/modules/{module}")
async def get_module(module: str):
    return require_module(module)


@api_router.post("/{module}/samples", response_model=Sample)
async def create_sample(module: str, payload: SampleCreate):
    require_module(module)
    sample = Sample(module=module, **payload.model_dump())
    await db.samples.insert_one(sample.model_dump())
    return sample


@api_router.get("/{module}/samples", response_model=List[Sample])
async def list_samples(module: str):
    require_module(module)
    docs = await db.samples.find({"module": module}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return [Sample(**d) for d in docs]


@api_router.delete("/{module}/samples/{sample_id}")
async def delete_sample(module: str, sample_id: str):
    require_module(module)
    res = await db.samples.delete_one({"module": module, "id": sample_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Sample not found")
    return {"success": True}


def _build_prompt(meta: Dict[str, Any], sample: Sample) -> str:
    lines = [
        f"Modul Pengujian: {meta['title']}", f"Deskripsi: {meta['description']}", "",
        f"Kode Sampel: {sample.sample_code}", f"Nama Sampel: {sample.sample_name}",
        f"Jenis Produk: {sample.product_type or '-'}", f"Operator: {sample.operator or '-'}",
        f"Tanggal Uji: {sample.test_date or '-'}", f"Rating: {sample.rating or '-'}", "", "Parameter Hasil Uji:",
    ]
    param_labels = {p["key"]: p for p in meta["parameters"]}
    for key, value in sample.parameters.items():
        p = param_labels.get(key, {"label": key, "unit": ""})
        unit = f" {p['unit']}" if p.get("unit") else ""
        lines.append(f"- {p['label']}: {value}{unit}")
    if sample.notes:
        lines.append("")
        lines.append(f"Catatan Operator: {sample.notes}")
    return "\n".join(lines)


@api_router.post("/{module}/samples/{sample_id}/analyze", response_model=Sample)
async def analyze_sample(module: str, sample_id: str):
    meta = require_module(module)
    doc = await db.samples.find_one({"module": module, "id": sample_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Sample not found")
    sample = Sample(**doc)
    system_message = (
        "Anda adalah ahli laboratorium pengujian minyak bumi senior di Elastech Production. "
        "Analisa hasil pengujian dan berikan laporan profesional dalam Bahasa Indonesia dengan bagian: "
        "1. RINGKASAN HASIL 2. INTERPRETASI PARAMETER 3. PENILAIAN KUALITAS 4. REKOMENDASI. Maks 350 kata."
    )
    try:
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"analyze-{module}-{sample_id}",
                       system_message=system_message).with_model("anthropic", "claude-sonnet-4-6")
        analysis = await _llm_send_with_retry(chat, UserMessage(text=_build_prompt(meta, sample)))
    except Exception as e:
        logger.exception("AI analysis failed")
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {e}")
    analyzed_at = now_iso()
    await db.samples.update_one({"module": module, "id": sample_id},
                                {"$set": {"ai_analysis": analysis, "ai_analyzed_at": analyzed_at}})
    sample.ai_analysis = analysis
    sample.ai_analyzed_at = analyzed_at
    return sample


# ===========================================================================
# Seed
# ===========================================================================
async def seed_reference():
    try:
        doc = {
            "key": "nikko_color_scale", "title": "Nikko COLOR SCALE",
            "note": "0 = paling gelap/pekat (terburuk) · 10 = bening/tak berwarna (terbaik). CLEAR bila rating >= 7.",
            "content_type": "image/jpeg", "image_base64": reference_b64(),
            "levels": NIKKO_LEVELS, "updated_at": now_iso(),
        }
        await db.reference.replace_one({"key": "nikko_color_scale"}, doc, upsert=True)
    except Exception as e:
        logger.warning("seed_reference failed: %s", e)


KHT_SEED = [
    {"sample_id": "KHT-2026-05-30-001", "oil_type": "Engine Oil SAE 15W-40", "batch": "LOT-20260530-A",
     "operator": "Karis Setia", "rating": 8.7, "performance": "VERY GOOD", "confidence": 98.2, "status": "CLEAR",
     "deposit_level_label": "5 - 15% (Slight)", "p": [8.9, 125, 44.6, 54.2, 9.6, 19.8, 132, 0.42, 90, 215],
     "img": "https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Endapan cokelat muda tipis merata di area tengah tabung, cocok dengan skala 8-9 pada COLOR SCALE.",
     "recommendation": "Oli dalam kondisi baik, lanjutkan interval penggantian normal."},
    {"sample_id": "KHT-2026-05-28-004", "oil_type": "Hydraulic Oil HO-46", "batch": "LOT-20260528-C",
     "operator": "Karis Setia", "rating": 6.2, "performance": "FAIR", "confidence": 95.1, "status": "TARNISH",
     "deposit_level_label": "30 - 45% (Moderate)", "p": [32.4, 190, 61.3, 41.0, 14.2, 26.4, 178, 0.71, 55, 245],
     "img": "https://images.unsplash.com/photo-1581093458791-9d09a5c0a5b9?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Endapan gelap sedang menyebar hampir sepanjang tabung, cocok dengan skala 6 pada COLOR SCALE.",
     "recommendation": "Perpendek interval penggantian dan periksa stabilitas oksidasi oli."},
    {"sample_id": "KHT-2026-05-25-002", "oil_type": "Engine Oil SAE 10W-30", "batch": "LOT-20260525-B",
     "operator": "Dwi Agus", "rating": 9.4, "performance": "EXCELLENT", "confidence": 97.6, "status": "CLEAR",
     "deposit_level_label": "< 5% (Very Slight)", "p": [3.1, 60, 18.2, 68.5, 4.1, 11.2, 96, 0.18, 120, 180],
     "img": "https://images.unsplash.com/photo-1567427017947-545c5f8d16ad?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Tabung sangat bersih hanya jejak samar endapan, cocok dengan skala 9-10 pada COLOR SCALE.",
     "recommendation": "Stabilitas termal sangat baik, tidak diperlukan tindakan."},
    {"sample_id": "KHT-2026-05-22-007", "oil_type": "Gear Oil GL-5 85W-140", "batch": "LOT-20260522-D",
     "operator": "Dwi Agus", "rating": 4.1, "performance": "POOR", "confidence": 92.8, "status": "TARNISH",
     "deposit_level_label": "60 - 75% (Heavy)", "p": [63.7, 250, 82.5, 28.3, 19.8, 31.6, 212, 1.12, 30, 285],
     "img": "https://images.unsplash.com/photo-1614308457932-e16d85c5d053?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Endapan karbon gelap tebal menutupi hampir seluruh tabung, cocok dengan skala 4 pada COLOR SCALE.",
     "recommendation": "Stabilitas termal buruk — evaluasi ulang formulasi/aplikasi oli."},
    {"sample_id": "KHT-2026-05-20-010", "oil_type": "Engine Oil SAE 5W-30", "batch": "LOT-20260520-E",
     "operator": "Rina Pertiwi", "rating": 9.1, "performance": "EXCELLENT", "confidence": 98.0, "status": "CLEAR",
     "deposit_level_label": "< 5% (Very Slight)", "p": [4.2, 72, 21.0, 66.1, 5.0, 12.4, 101, 0.21, 115, 188],
     "img": "https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Tabung sangat bersih dengan jejak endapan minimal, cocok skala 9 pada COLOR SCALE.",
     "recommendation": "Performa sangat baik, tidak perlu tindakan tambahan."},
    {"sample_id": "KHT-2026-05-18-012", "oil_type": "Turbine Oil ISO VG-46", "batch": "LOT-20260518-F",
     "operator": "Rina Pertiwi", "rating": 7.6, "performance": "GOOD", "confidence": 96.3, "status": "CLEAR",
     "deposit_level_label": "15 - 30% (Light)", "p": [18.5, 150, 38.2, 49.0, 11.0, 22.1, 150, 0.55, 70, 225],
     "img": "https://images.unsplash.com/photo-1567427017947-545c5f8d16ad?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Endapan cokelat muda tipis di sepertiga tabung, cocok skala 7-8 pada COLOR SCALE.",
     "recommendation": "Kondisi baik, pertahankan interval penggantian normal."},
    {"sample_id": "KHT-2026-05-15-015", "oil_type": "Compressor Oil ISO VG-68", "batch": "LOT-20260515-G",
     "operator": "Dwi Agus", "rating": 5.4, "performance": "FAIR", "confidence": 94.2, "status": "TARNISH",
     "deposit_level_label": "30 - 45% (Moderate)", "p": [38.0, 205, 58.7, 39.5, 15.1, 27.0, 182, 0.78, 50, 250],
     "img": "https://images.unsplash.com/photo-1581093458791-9d09a5c0a5b9?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Endapan gelap sedang menyebar di area tengah tabung, cocok skala 5-6 pada COLOR SCALE.",
     "recommendation": "Perpendek interval penggantian dan cek kontaminasi oli."},
    {"sample_id": "KHT-2026-05-12-018", "oil_type": "Engine Oil SAE 15W-40", "batch": "LOT-20260512-H",
     "operator": "Karis Setia", "rating": 8.9, "performance": "VERY GOOD", "confidence": 97.9, "status": "CLEAR",
     "deposit_level_label": "5 - 15% (Slight)", "p": [9.5, 118, 42.0, 55.0, 9.0, 19.0, 128, 0.40, 92, 210],
     "img": "https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Endapan cokelat muda tipis merata, cocok skala 8-9 pada COLOR SCALE.",
     "recommendation": "Oli dalam kondisi baik, lanjutkan pemakaian normal."},
    {"sample_id": "KHT-2026-05-10-021", "oil_type": "Gear Oil GL-4 80W-90", "batch": "LOT-20260510-I",
     "operator": "Rina Pertiwi", "rating": 3.3, "performance": "POOR", "confidence": 91.0, "status": "TARNISH",
     "deposit_level_label": "75 - 90% (Very Heavy)", "p": [78.0, 268, 88.0, 24.0, 21.5, 33.0, 221, 1.28, 22, 292],
     "img": "https://images.unsplash.com/photo-1614308457932-e16d85c5d053?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
     "summary": "Endapan karbon hitam tebal menutupi hampir seluruh tabung, cocok skala 3 pada COLOR SCALE.",
     "recommendation": "Stabilitas termal sangat buruk — hentikan penggunaan dan reformulasi."},
]


async def seed_kht():
    if await db.tests.count_documents({}) > 0:
        return
    logger.info("Seeding demo KHT tests...")
    base = datetime.now(timezone.utc)
    for i, s in enumerate(KHT_SEED):
        p = s["p"]
        rec = TestRecord(
            image_path=s["img"],
            meta=TestMeta(sample_id=s["sample_id"], oil_type=s["oil_type"], batch=s["batch"], operator=s["operator"],
                          temperature_c=320, duration_hours=16, air_flow=10, oil_flow=0.31),
            rating=s["rating"], performance=s["performance"], confidence=s["confidence"], status=s["status"],
            deposit_level_label=s["deposit_level_label"], ai_summary=s["summary"], recommendation=s["recommendation"],
            parameters=Parameters(deposit_area_pct=p[0], deposit_length_mm=p[1], deposit_coverage_pct=p[2],
                                  avg_intensity_l=p[3], avg_color_a=p[4], avg_color_b=p[5], max_intensity=p[6],
                                  thickness_index_mm=p[7], deposit_start_mm=p[8], deposit_end_mm=p[9]),
        )
        rec_dict = rec.model_dump()
        rec_dict["created_at"] = (base - timedelta(days=i * 3)).isoformat()
        await db.tests.insert_one(rec_dict)


# ===========================================================================
# HTCBT — ASTM D6594 (High Temperature Corrosion Bench Test)
# Monitoring module: handwritten-label OCR (AI Vision) + persistent countdown timer.
# One active run at a time; a run batches up to 4 samples sharing one countdown.
# ===========================================================================

HTCBT_METHODS = [
    {"code": "A", "label": "Metode A · 168 jam @ 135°C", "duration_hours": 168, "temperature_c": 135},
    {"code": "B", "label": "Metode B · 312 jam @ 121°C", "duration_hours": 312, "temperature_c": 121},
]
HTCBT_MAX_SAMPLES = 4


def _htcbt_method_for(temperature_c, duration_hours):
    """Best-effort match of OCR values to one of the two standard methods."""
    try:
        dur = float(duration_hours) if duration_hours is not None else None
    except (TypeError, ValueError):
        dur = None
    try:
        temp = float(temperature_c) if temperature_c is not None else None
    except (TypeError, ValueError):
        temp = None
    # duration is the strongest signal
    if dur is not None:
        for m in HTCBT_METHODS:
            if abs(dur - m["duration_hours"]) <= 24:
                return m
    if temp is not None:
        for m in HTCBT_METHODS:
            if abs(temp - m["temperature_c"]) <= 5:
                return m
    return None


HTCBT_OCR_PROMPT = (
    "You are an OCR and data-extraction engine reading a HANDWRITTEN laboratory sample "
    "label / note for an HTCBT test (High Temperature Corrosion Bench Test, ASTM D6594).\n"
    "A single label/note may list MULTIPLE sample codes that all belong to the SAME batch "
    "(they share one temperature and one duration).\n"
    "IMPORTANT READING RULES: the handwriting may be rotated 90°/270°, upside-down (180°) or mirrored "
    "through the glass — mentally rotate/flip the image and read it anyway; scan the WHOLE image for "
    "codes written directly on the tube or on a small white label.\n"
    "Carefully read ALL the handwriting in the image and extract:\n"
    "- sample_codes: an ARRAY of ALL sample identifiers / codes exactly as written, in the order "
    "they appear (list of strings). Each line that looks like a sample code is a separate entry. "
    "Keep letters, digits and separators (e.g. 'WZ 275215', 'BL 275314', 'NT 265142', 'WZ 265336'). "
    "Do NOT include the temperature or duration lines as sample codes. If only one code exists, "
    "return an array with one element.\n"
    "- temperature_c: the test temperature in degrees Celsius as a NUMBER only (e.g. 135 or 121). "
    "This applies to the whole batch. null if not present.\n"
    "- duration_hours: the test duration in HOURS as a NUMBER only. If written as '168 jam' or "
    "'168 h' return 168; if '312 jam' return 312. Applies to the whole batch. null if not present.\n\n"
    "Common valid combinations are 168 hours at 135C, and 312 hours at 121C.\n\n"
    "Return ONLY a valid minified JSON object (no markdown) with EXACTLY these keys:\n"
    '{"sample_codes": [<string>, ...], "temperature_c": <number or null>, '
    '"duration_hours": <number or null>, "raw_text": <all text you can read from the label>}'
)


async def run_htcbt_ocr(image_b64: str) -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"htcbt-{uuid.uuid4()}",
        system_message="You are a precise handwriting OCR model that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    resp = await _llm_send_with_retry(chat, 
        UserMessage(text=HTCBT_OCR_PROMPT, file_contents=[ImageContent(image_base64=image_b64)])
    )
    return _parse_ai_json(resp if isinstance(resp, str) else str(resp))


class HtcbtSample(BaseModel):
    sample_code: str
    added_at: str = Field(default_factory=now_iso)


class HtcbtRun(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method_code: str = ""
    method_label: str = ""
    temperature_c: float = 0
    duration_hours: float = 0
    samples: List[HtcbtSample] = Field(default_factory=list)
    operator: str = ""
    notes: str = ""
    image_path: Optional[str] = None
    ocr_raw: str = ""
    start_at: str = Field(default_factory=now_iso)
    finish_at: str = ""
    status: str = "running"  # running | done | stopped
    acknowledged: bool = False
    created_at: str = Field(default_factory=now_iso)
    deleted_at: Optional[str] = None


class HtcbtOcrRequest(BaseModel):
    image_path: str


class HtcbtSubmitRequest(BaseModel):
    sample_code: str
    temperature_c: Optional[float] = None
    duration_hours: Optional[float] = None
    method_code: Optional[str] = None
    operator: str = ""
    notes: str = ""
    image_path: Optional[str] = None
    ocr_raw: str = ""


def _parse_iso(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


def _htcbt_public(doc: dict) -> dict:
    """Enrich a run document with live countdown fields."""
    doc = {k: v for k, v in doc.items() if k != "_id"}
    now = datetime.now(timezone.utc)
    finish = _parse_iso(doc.get("finish_at") or now.isoformat())
    start = _parse_iso(doc.get("start_at") or now.isoformat())
    remaining = int((finish - now).total_seconds())
    total = int((finish - start).total_seconds()) or 1
    time_up = now >= finish
    doc["remaining_seconds"] = max(0, remaining)
    doc["elapsed_seconds"] = max(0, int((now - start).total_seconds()))
    doc["total_seconds"] = total
    doc["progress_pct"] = min(100, max(0, round((total - max(0, remaining)) / total * 100, 1)))
    # A run whose time has elapsed but is still "running" is reported as time_up
    doc["time_up"] = bool(time_up and doc.get("status") == "running")
    doc["is_active"] = doc.get("status") == "running"
    return doc


async def _htcbt_active_doc() -> Optional[dict]:
    return await db.htcbt_runs.find_one(
        {"status": "running", "deleted_at": None}, sort=[("created_at", -1)]
    )


class HtcbtOcrJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"  # running | done | error
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


async def _run_htcbt_ocr_job(job_id: str, image_path: str):
    try:
        content, _ = await run_in_threadpool(get_source_object, image_path)
        small = await run_in_threadpool(_downscale_for_ai, content)
        b64 = base64.b64encode(small).decode("utf-8")
        ai = await run_htcbt_ocr(b64)
        method = _htcbt_method_for(ai.get("temperature_c"), ai.get("duration_hours"))
        # Normalize sample codes into a de-duplicated, order-preserving list.
        raw_codes = ai.get("sample_codes")
        if not isinstance(raw_codes, list):
            raw_codes = [ai.get("sample_code")] if ai.get("sample_code") else []
        codes = []
        seen = set()
        for c in raw_codes:
            s = str(c or "").strip()
            key = s.upper()
            if s and key not in seen:
                seen.add(key)
                codes.append(s)
        over_limit = len(codes) > HTCBT_MAX_SAMPLES
        codes = codes[:HTCBT_MAX_SAMPLES]
        result = {
            "sample_codes": codes,
            "sample_code": codes[0] if codes else "",
            "detected_count": len(codes),
            "over_limit": over_limit,
            "max_samples": HTCBT_MAX_SAMPLES,
            "temperature_c": ai.get("temperature_c"),
            "duration_hours": ai.get("duration_hours"),
            "raw_text": str(ai.get("raw_text") or ""),
            "method_code": method["code"] if method else "",
            "method_label": method["label"] if method else "",
        }
        await db.htcbt_ocr_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "done", "result": result, "finished_at": now_iso()}},
        )
    except Exception as e:
        logger.exception("HTCBT OCR job failed")
        await db.htcbt_ocr_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}},
        )


@api_router.post("/htcbt/ocr/start", response_model=HtcbtOcrJob)
async def htcbt_ocr_start(req: HtcbtOcrRequest):
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = HtcbtOcrJob()
    await db.htcbt_ocr_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_htcbt_ocr_job(job.id, req.image_path))
    return job


@api_router.get("/htcbt/ocr/jobs/{job_id}", response_model=HtcbtOcrJob)
async def htcbt_ocr_job_status(job_id: str):
    doc = await db.htcbt_ocr_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return HtcbtOcrJob(**doc)


# ===========================================================================
# Generic handwritten LABEL OCR — shared by K-HTT & Copper Strip "New Test".
# Reads ONE label/note and extracts: sample id, operator name, temperature,
# duration and batch/lot so the form can be auto-filled.
# ===========================================================================

LABEL_OCR_PROMPT = (
    "You are an OCR and data-extraction engine reading a HANDWRITTEN laboratory sample "
    "label / note for a {context}.\n"
    "IMPORTANT READING RULES:\n"
    "- The handwriting may be written at ANY angle: rotated 90°/270° (along the tube), upside-down "
    "(180°) or mirrored (photo taken from the back of the glass). Mentally rotate/flip the image and "
    "read it anyway — never give up because the text is not upright.\n"
    "- The code may be written DIRECTLY ON THE GLASS TUBE with a marker, or on a small white paper "
    "label/sticker taped to the tube, or on a note in the frame. Scan the WHOLE image.\n"
    "- If the first read fails, try reading the text flipped 180° (many photos are upside-down).\n"
    "Carefully read ALL the handwriting in the image and extract these fields:\n"
    "- sample_id: the single sample identifier / code exactly as written (e.g. 'WZ 275215', "
    "'KHT-001'). If several codes appear, take the FIRST/main one. Empty string if none.\n"
    "- operator: the person/operator name written on the label (may follow 'op', 'operator', "
    "'oleh', 'by', or a name alone). Empty string if not present.\n"
    "- temperature_c: the test temperature in degrees Celsius as a NUMBER only (e.g. text "
    "'320C', '320 °C', '100C' -> 320 / 100). null if not present.\n"
    "- duration_hours: the test duration in HOURS as a NUMBER only. '16 jam' -> 16, '3 h' -> 3, "
    "'168 jam' -> 168. null if not present.\n"
    "- batch: a batch / lot number if written (e.g. 'LOT-123', 'B-45'). Empty string if none.\n\n"
    "Typical values for this test: around {hint_temp}°C for {hint_dur} hours — but only report "
    "what is actually written; use null when absent.\n\n"
    "Return ONLY a valid minified JSON object (no markdown) with EXACTLY these keys:\n"
    '{{"sample_id": <string>, "operator": <string>, "temperature_c": <number or null>, '
    '"duration_hours": <number or null>, "batch": <string>, "raw_text": <all text you can read>}}'
)


async def run_label_ocr(image_b64: str, context: str, hint_temp: str, hint_dur: str) -> dict:
    prompt = LABEL_OCR_PROMPT.format(context=context, hint_temp=hint_temp, hint_dur=hint_dur)
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"labelocr-{uuid.uuid4()}",
        system_message="You are a precise handwriting OCR model that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    resp = await _llm_send_with_retry(chat, 
        UserMessage(text=prompt, file_contents=[ImageContent(image_base64=image_b64)])
    )
    return _parse_ai_json(resp if isinstance(resp, str) else str(resp))


class LabelOcrRequest(BaseModel):
    image_path: str


class LabelOcrJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"  # running | done | error
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


def _num_or_none(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


async def _run_label_ocr_job(job_id: str, image_path: str, collection, context: str, hint_temp: str, hint_dur: str):
    try:
        content, _ = await run_in_threadpool(get_source_object, image_path)
        small = await run_in_threadpool(_downscale_for_ai, content)
        b64 = base64.b64encode(small).decode("utf-8")
        ai = await run_label_ocr(b64, context, hint_temp, hint_dur)
        result = {
            "sample_id": str(ai.get("sample_id") or "").strip(),
            "operator": str(ai.get("operator") or "").strip(),
            "temperature_c": _num_or_none(ai.get("temperature_c")),
            "duration_hours": _num_or_none(ai.get("duration_hours")),
            "batch": str(ai.get("batch") or "").strip(),
            "raw_text": str(ai.get("raw_text") or ""),
        }
        await collection.update_one(
            {"id": job_id},
            {"$set": {"status": "done", "result": result, "finished_at": now_iso()}},
        )
    except Exception as e:
        logger.exception("Label OCR job failed (%s)", context)
        await collection.update_one(
            {"id": job_id},
            {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}},
        )


async def _label_ocr_start(req: LabelOcrRequest, collection, context: str, hint_temp: str, hint_dur: str) -> LabelOcrJob:
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = LabelOcrJob()
    await collection.insert_one(job.model_dump())
    asyncio.create_task(_run_label_ocr_job(job.id, req.image_path, collection, context, hint_temp, hint_dur))
    return job


async def _label_ocr_status(job_id: str, collection) -> LabelOcrJob:
    doc = await collection.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return LabelOcrJob(**doc)


@api_router.post("/kht/ocr/start", response_model=LabelOcrJob)
async def kht_label_ocr_start(req: LabelOcrRequest):
    return await _label_ocr_start(
        req,
        db.kht_ocr_jobs,
        "K-HTT hot tube deposit test. IMPORTANT: the photo usually shows a glass test "
        "tube; the sample code is HANDWRITTEN on a small WHITE PAPER LABEL taped to the "
        "tube. Find that white label first and read the code from it",
        "320",
        "16",
    )


@api_router.get("/kht/ocr/jobs/{job_id}", response_model=LabelOcrJob)
async def kht_label_ocr_status(job_id: str):
    return await _label_ocr_status(job_id, db.kht_ocr_jobs)


@api_router.post("/dka/ocr/start", response_model=LabelOcrJob)
async def dka_label_ocr_start(req: LabelOcrRequest):
    return await _label_ocr_start(
        req,
        db.dka_ocr_jobs,
        "Rating DKA batch test. Read the handwritten temperature written on the sample photo or lab note; keep the value exactly as written.",
        "320",
        "192",
    )


@api_router.get("/dka/ocr/jobs/{job_id}", response_model=LabelOcrJob)
async def dka_label_ocr_status(job_id: str):
    return await _label_ocr_status(job_id, db.dka_ocr_jobs)


@api_router.post("/copper/ocr/start", response_model=LabelOcrJob)
async def copper_label_ocr_start(req: LabelOcrRequest):
    return await _label_ocr_start(req, db.copper_ocr_jobs, "Copper Strip corrosion test (ASTM D130)", "100", "3")


@api_router.get("/copper/ocr/jobs/{job_id}", response_model=LabelOcrJob)
async def copper_label_ocr_status(job_id: str):
    return await _label_ocr_status(job_id, db.copper_ocr_jobs)


@api_router.post("/rust/ocr/start", response_model=LabelOcrJob)
async def rust_label_ocr_start(req: LabelOcrRequest):
    if not (req.image_path or "").strip():
        raise HTTPException(status_code=400, detail="image_path wajib diisi")
    return await _label_ocr_start(
        req,
        db.rust_ocr_jobs,
        "Rust Preventing ASTM D1748 humidity-cabinet metal panel test. The photo shows a steel test "
        "panel with a transparent 10x10 measuring grid; the sample code is HANDWRITTEN on a small WHITE "
        "PAPER LABEL / sticker on or next to the panel, or written with marker directly on the panel. "
        "Ignore the printed grid row letters (A-J) and column numbers (1-10). duration_hours = exposure time",
        "48.9",
        "168",
    )


@api_router.get("/rust/ocr/jobs/{job_id}", response_model=LabelOcrJob)
async def rust_label_ocr_status(job_id: str):
    return await _label_ocr_status(job_id, db.rust_ocr_jobs)



@api_router.get("/htcbt/methods")
async def htcbt_methods():
    return {"methods": HTCBT_METHODS, "max_samples": HTCBT_MAX_SAMPLES}


@api_router.get("/htcbt/active")
async def htcbt_active():
    doc = await _htcbt_active_doc()
    return {"active": _htcbt_public(doc) if doc else None}


@api_router.get("/htcbt/runs")
async def htcbt_runs():
    docs = await db.htcbt_runs.find({"deleted_at": None}, {"_id": 0}).sort("created_at", -1).to_list(300)
    return [_htcbt_public(d) for d in docs]


@api_router.post("/htcbt/submit")
async def htcbt_submit(req: HtcbtSubmitRequest):
    code = (req.sample_code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Kode sampel tidak boleh kosong.")

    active = await _htcbt_active_doc()
    if active:
        finish = _parse_iso(active.get("finish_at"))
        if datetime.now(timezone.utc) >= finish:
            raise HTTPException(
                status_code=409,
                detail="Run sebelumnya sudah SELESAI. Konfirmasi/arsipkan dulu sebelum memulai run baru.",
            )
        samples = active.get("samples", [])
        if len(samples) >= HTCBT_MAX_SAMPLES:
            raise HTTPException(
                status_code=409,
                detail=f"Batch penuh (maks {HTCBT_MAX_SAMPLES} sampel). Hentikan run untuk memulai batch baru.",
            )
        if any(s.get("sample_code") == code for s in samples):
            raise HTTPException(status_code=409, detail=f"Sampel '{code}' sudah ada di run aktif.")
        new_sample = HtcbtSample(sample_code=code).model_dump()
        await db.htcbt_runs.update_one(
            {"id": active["id"]}, {"$push": {"samples": new_sample}}
        )
        doc = await db.htcbt_runs.find_one({"id": active["id"]}, {"_id": 0})
        return {"run": _htcbt_public(doc), "created": False}

    # No active run — start a new one (auto-start countdown)
    method = None
    if req.method_code:
        method = next((m for m in HTCBT_METHODS if m["code"] == req.method_code), None)
    if method is None:
        method = _htcbt_method_for(req.temperature_c, req.duration_hours)

    duration = req.duration_hours or (method["duration_hours"] if method else None)
    temperature = req.temperature_c or (method["temperature_c"] if method else 0)
    if not duration or float(duration) <= 0:
        raise HTTPException(
            status_code=400,
            detail="Durasi uji tidak terdeteksi. Pilih metode atau masukkan durasi (jam) manual.",
        )

    start = datetime.now(timezone.utc)
    finish = start + timedelta(hours=float(duration))
    run = HtcbtRun(
        method_code=method["code"] if method else "",
        method_label=method["label"] if method else f"Custom · {int(float(duration))} jam @ {int(float(temperature or 0))}°C",
        temperature_c=float(temperature or 0),
        duration_hours=float(duration),
        samples=[HtcbtSample(sample_code=code)],
        operator=req.operator or "",
        notes=req.notes or "",
        image_path=req.image_path,
        ocr_raw=req.ocr_raw or "",
        start_at=start.isoformat(),
        finish_at=finish.isoformat(),
    )
    await db.htcbt_runs.insert_one(run.model_dump())
    return {"run": _htcbt_public(run.model_dump()), "created": True}


class HtcbtBatchSubmitRequest(BaseModel):
    sample_codes: List[str] = Field(default_factory=list)
    temperature_c: Optional[float] = None
    duration_hours: Optional[float] = None
    method_code: Optional[str] = None
    operator: str = ""
    notes: str = ""
    image_path: Optional[str] = None
    ocr_raw: str = ""


@api_router.post("/htcbt/submit-batch")
async def htcbt_submit_batch(req: HtcbtBatchSubmitRequest):
    # Clean + de-duplicate the incoming codes, preserving order.
    codes = []
    seen = set()
    for c in (req.sample_codes or []):
        s = (c or "").strip()
        key = s.upper()
        if s and key not in seen:
            seen.add(key)
            codes.append(s)
    if not codes:
        raise HTTPException(status_code=400, detail="Minimal satu kode sampel harus diisi.")

    truncated = len(codes) > HTCBT_MAX_SAMPLES
    codes = codes[:HTCBT_MAX_SAMPLES]

    added, skipped = [], []
    active = await _htcbt_active_doc()
    if active:
        finish = _parse_iso(active.get("finish_at"))
        if datetime.now(timezone.utc) >= finish:
            raise HTTPException(
                status_code=409,
                detail="Run sebelumnya sudah SELESAI. Konfirmasi/arsipkan dulu sebelum memulai run baru.",
            )
        existing = active.get("samples", [])
        existing_codes = {s.get("sample_code", "").upper() for s in existing}
        slots = HTCBT_MAX_SAMPLES - len(existing)
        to_push = []
        for code in codes:
            if code.upper() in existing_codes:
                skipped.append({"code": code, "reason": "duplikat"})
                continue
            if len(to_push) >= slots:
                skipped.append({"code": code, "reason": "batch penuh"})
                continue
            to_push.append(HtcbtSample(sample_code=code).model_dump())
            existing_codes.add(code.upper())
            added.append(code)
        if to_push:
            await db.htcbt_runs.update_one(
                {"id": active["id"]}, {"$push": {"samples": {"$each": to_push}}}
            )
        doc = await db.htcbt_runs.find_one({"id": active["id"]}, {"_id": 0})
        return {
            "run": _htcbt_public(doc), "created": False,
            "added": added, "skipped": skipped, "truncated": truncated,
            "max_samples": HTCBT_MAX_SAMPLES,
        }

    # No active run — start a new batch with all codes.
    method = None
    if req.method_code:
        method = next((m for m in HTCBT_METHODS if m["code"] == req.method_code), None)
    if method is None:
        method = _htcbt_method_for(req.temperature_c, req.duration_hours)

    duration = req.duration_hours or (method["duration_hours"] if method else None)
    temperature = req.temperature_c or (method["temperature_c"] if method else 0)
    if not duration or float(duration) <= 0:
        raise HTTPException(
            status_code=400,
            detail="Durasi uji tidak terdeteksi. Pilih metode atau masukkan durasi (jam) manual.",
        )

    start = datetime.now(timezone.utc)
    finish = start + timedelta(hours=float(duration))
    run = HtcbtRun(
        method_code=method["code"] if method else "",
        method_label=method["label"] if method else f"Custom · {int(float(duration))} jam @ {int(float(temperature or 0))}°C",
        temperature_c=float(temperature or 0),
        duration_hours=float(duration),
        samples=[HtcbtSample(sample_code=c) for c in codes],
        operator=req.operator or "",
        notes=req.notes or "",
        image_path=req.image_path,
        ocr_raw=req.ocr_raw or "",
        start_at=start.isoformat(),
        finish_at=finish.isoformat(),
    )
    await db.htcbt_runs.insert_one(run.model_dump())
    added = list(codes)
    return {
        "run": _htcbt_public(run.model_dump()), "created": True,
        "added": added, "skipped": skipped, "truncated": truncated,
        "max_samples": HTCBT_MAX_SAMPLES,
    }


@api_router.delete("/htcbt/runs/{run_id}/samples/{sample_code}")
async def htcbt_remove_sample(run_id: str, sample_code: str):
    doc = await db.htcbt_runs.find_one({"id": run_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Run tidak ditemukan")
    await db.htcbt_runs.update_one(
        {"id": run_id}, {"$pull": {"samples": {"sample_code": sample_code}}}
    )
    doc = await db.htcbt_runs.find_one({"id": run_id}, {"_id": 0})
    return {"run": _htcbt_public(doc)}


@api_router.post("/htcbt/runs/{run_id}/complete")
async def htcbt_complete(run_id: str):
    res = await db.htcbt_runs.update_one(
        {"id": run_id}, {"$set": {"status": "done", "acknowledged": True}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Run tidak ditemukan")
    doc = await db.htcbt_runs.find_one({"id": run_id}, {"_id": 0})
    return {"run": _htcbt_public(doc)}


@api_router.post("/htcbt/runs/{run_id}/stop")
async def htcbt_stop(run_id: str):
    res = await db.htcbt_runs.update_one(
        {"id": run_id}, {"$set": {"status": "stopped", "acknowledged": True}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Run tidak ditemukan")
    doc = await db.htcbt_runs.find_one({"id": run_id}, {"_id": 0})
    return {"run": _htcbt_public(doc)}


@api_router.delete("/htcbt/runs/{run_id}")
async def htcbt_delete(run_id: str):
    res = await db.htcbt_runs.update_one(
        {"id": run_id}, {"$set": {"deleted_at": now_iso()}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Run tidak ditemukan")
    return {"ok": True}


# ===========================================================================
# DKA-CEC L-48-A-00 — CEC L-48-A-00 oxidation/thermal test
# Monitoring module mirroring HTCBT: handwritten-label OCR (AI Vision) reads
# Sample ID(s), temperature and operator; persistent 192-hour countdown timer.
# One active run at a time; a run batches up to 4 samples sharing one countdown.
# ===========================================================================

DKACEC_METHODS = [
    {"code": "1", "label": "Metode 1 · 192 jam @ 150°C", "duration_hours": 192, "temperature_c": 150},
    {"code": "2", "label": "Metode 2 · 192 jam @ 160°C", "duration_hours": 192, "temperature_c": 160},
    {"code": "3", "label": "Metode 3 · 192 jam @ 180°C", "duration_hours": 192, "temperature_c": 180},
]
DKACEC_MAX_SAMPLES = 4
DKACEC_DURATION_HOURS = 192


def _dkacec_method_for(temperature_c, duration_hours=None):
    """Match OCR values to one of the three methods. All methods share 192h,
    so temperature is the discriminator (150 / 160 / 180)."""
    try:
        temp = float(temperature_c) if temperature_c is not None else None
    except (TypeError, ValueError):
        temp = None
    if temp is not None:
        best, best_diff = None, None
        for m in DKACEC_METHODS:
            diff = abs(temp - m["temperature_c"])
            if best is None or diff < best_diff:
                best, best_diff = m, diff
        if best is not None and best_diff <= 5:
            return best
    return None


DKACEC_OCR_PROMPT = (
    "You are an OCR and data-extraction engine reading a HANDWRITTEN laboratory sample "
    "label / note for a DKA-CEC L-48-A-00 oxidation test.\n"
    "A single label/note may list MULTIPLE sample codes that all belong to the SAME batch "
    "(they share one temperature and one operator).\n"
    "Carefully read ALL the handwriting in the image and extract:\n"
    "- sample_codes: an ARRAY of ALL sample identifiers / codes exactly as written, in the order "
    "they appear (list of strings). Each line that looks like a sample code is a separate entry. "
    "Keep letters, digits and separators (e.g. 'WZ 275215', 'BL 275314'). Do NOT include the "
    "temperature or operator lines as sample codes. If only one code exists, return an array with one element.\n"
    "- temperature_c: the test temperature in degrees Celsius as a NUMBER only (e.g. 150, 160 or 180). "
    "This applies to the whole batch. null if not present.\n"
    "- operator: the operator / analyst name if written on the note (string). null if not present. "
    "Look for a name, or a label like 'Operator', 'Analis', 'By', 'PIC'.\n\n"
    "Common valid temperatures are 150C, 160C and 180C (all run for 192 hours).\n\n"
    "Return ONLY a valid minified JSON object (no markdown) with EXACTLY these keys:\n"
    '{"sample_codes": [<string>, ...], "temperature_c": <number or null>, '
    '"operator": <string or null>, "raw_text": <all text you can read from the label>}'
)


async def run_dkacec_ocr(image_b64: str) -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"dkacec-{uuid.uuid4()}",
        system_message="You are a precise handwriting OCR model that only outputs JSON.",
    ).with_model("gemini", "gemini-3.1-pro-preview")
    resp = await _llm_send_with_retry(chat, 
        UserMessage(text=DKACEC_OCR_PROMPT, file_contents=[ImageContent(image_base64=image_b64)])
    )
    return _parse_ai_json(resp if isinstance(resp, str) else str(resp))


class DkacecSample(BaseModel):
    sample_code: str
    added_at: str = Field(default_factory=now_iso)


class DkacecRun(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method_code: str = ""
    method_label: str = ""
    temperature_c: float = 0
    duration_hours: float = DKACEC_DURATION_HOURS
    samples: List[DkacecSample] = Field(default_factory=list)
    operator: str = ""
    notes: str = ""
    image_path: Optional[str] = None
    ocr_raw: str = ""
    # Jam running mesin saat timer dimulai (hasil OCR layar monitor / koreksi manual).
    running_hours: int = 0
    running_minutes: int = 0
    running_label: str = ""
    runhours_image_path: Optional[str] = None
    start_at: str = Field(default_factory=now_iso)
    finish_at: str = ""
    status: str = "running"  # running | done | stopped
    acknowledged: bool = False
    created_at: str = Field(default_factory=now_iso)
    deleted_at: Optional[str] = None


class DkacecOcrRequest(BaseModel):
    image_path: str


class DkacecOcrJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"  # running | done | error
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None


def _dkacec_public(doc: dict) -> dict:
    doc = {k: v for k, v in doc.items() if k != "_id"}
    now = datetime.now(timezone.utc)
    finish = _parse_iso(doc.get("finish_at") or now.isoformat())
    start = _parse_iso(doc.get("start_at") or now.isoformat())
    remaining = int((finish - now).total_seconds())
    total = int((finish - start).total_seconds()) or 1
    time_up = now >= finish
    doc["remaining_seconds"] = max(0, remaining)
    doc["elapsed_seconds"] = max(0, int((now - start).total_seconds()))
    doc["total_seconds"] = total
    doc["progress_pct"] = min(100, max(0, round((total - max(0, remaining)) / total * 100, 1)))
    doc["time_up"] = bool(time_up and doc.get("status") == "running")
    doc["is_active"] = doc.get("status") == "running"
    return doc


async def _dkacec_active_doc() -> Optional[dict]:
    return await db.dkacec_runs.find_one(
        {"status": "running", "deleted_at": None}, sort=[("created_at", -1)]
    )


async def _run_dkacec_ocr_job(job_id: str, image_path: str):
    try:
        content, _ = await run_in_threadpool(get_source_object, image_path)
        small = await run_in_threadpool(_downscale_for_ai, content)
        b64 = base64.b64encode(small).decode("utf-8")
        ai = await run_dkacec_ocr(b64)
        method = _dkacec_method_for(ai.get("temperature_c"))
        raw_codes = ai.get("sample_codes")
        if not isinstance(raw_codes, list):
            raw_codes = [ai.get("sample_code")] if ai.get("sample_code") else []
        codes, seen = [], set()
        for c in raw_codes:
            s = str(c or "").strip()
            key = s.upper()
            if s and key not in seen:
                seen.add(key)
                codes.append(s)
        over_limit = len(codes) > DKACEC_MAX_SAMPLES
        codes = codes[:DKACEC_MAX_SAMPLES]
        result = {
            "sample_codes": codes,
            "sample_code": codes[0] if codes else "",
            "detected_count": len(codes),
            "over_limit": over_limit,
            "max_samples": DKACEC_MAX_SAMPLES,
            "temperature_c": ai.get("temperature_c"),
            "duration_hours": DKACEC_DURATION_HOURS,
            "operator": str(ai.get("operator") or "").strip(),
            "raw_text": str(ai.get("raw_text") or ""),
            "method_code": method["code"] if method else "",
            "method_label": method["label"] if method else "",
        }
        await db.dkacec_ocr_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "done", "result": result, "finished_at": now_iso()}},
        )
    except Exception as e:
        logger.exception("DKA-CEC OCR job failed")
        await db.dkacec_ocr_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}},
        )


@api_router.post("/dkacec/ocr/start", response_model=DkacecOcrJob)
async def dkacec_ocr_start(req: DkacecOcrRequest):
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = DkacecOcrJob()
    await db.dkacec_ocr_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_dkacec_ocr_job(job.id, req.image_path))
    return job


@api_router.get("/dkacec/ocr/jobs/{job_id}", response_model=DkacecOcrJob)
async def dkacec_ocr_job_status(job_id: str):
    doc = await db.dkacec_ocr_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return DkacecOcrJob(**doc)


# ---------------------------------------------------------------------------
# DKA-CEC — OCR jam running dari foto layar monitor mesin
# Membaca label waktu pada sumbu X grafik (mis. 68:27 ... 70:20, 70:27) dan
# mengambil yang PALING KANAN (terakhir) sebagai jam running mesin.
# ---------------------------------------------------------------------------
DKACEC_RUNHOURS_PROMPT = (
    "This photo shows the control-panel screen of a laboratory oxidation-test machine (DKA-CEC L-48-A-00). "
    "The screen contains a chart (Flow or Temperature vs time). Along the BOTTOM horizontal axis (X axis) "
    "there is a row of elapsed-running-time tick labels written as HOURS:MINUTES, for example: "
    "'68:27  68:40  68:50  69:00  69:10  69:20  69:30  69:40  69:50  70:00  70:10  70:20  70:27'.\n\n"
    "YOUR TASK: read that row of X-axis time labels from LEFT to RIGHT and report them, then report the "
    "LAST one (the RIGHT-MOST label, i.e. the largest / most recent elapsed time). That right-most value is "
    "the machine's current running time.\n\n"
    "CRITICAL RULES:\n"
    "1. These are ELAPSED RUNNING HOURS, not clock time. Hours can be any number from 0 to 192 "
    "(e.g. 70:27 means 70 hours 27 minutes). Minutes are always 00-59.\n"
    "2. Take ONLY the right-most/last label on the X axis for 'last_label'. In the example above that is '70:27'.\n"
    "3. Do NOT confuse it with: the temperature readout (e.g. '150.1\u00b0C'), the clock/date field at the top "
    "(e.g. '12.26 07'), the Y-axis numbers (0-7 flow scale), flow values like '5.02 L/h', or sample codes.\n"
    "4. The right-most label often sits very close to the second-to-last one (e.g. '70:20 70:27') - read both "
    "carefully and return the larger/last one.\n"
    "5. If labels use a dot or space separator (70.27 or 70 27), still report it as HH:MM.\n\n"
    "Return ONLY a valid minified JSON object (no markdown) with EXACTLY these keys:\n"
    '{"axis_labels": [<string>, ...], "last_label": "<HH:MM>", "hours": <integer>, '
    '"minutes": <integer>, "confidence": <number 0-100>, "raw_text": "<any other text you can read>"}'
)


def _dkacec_norm_hhmm(hours, minutes, label: str = "") -> Optional[Dict[str, Any]]:
    """Normalise an OCR'd running-time reading into {hours, minutes, total_minutes, label}.
    Falls back to parsing the raw label string when the numeric fields are unusable."""
    h = m = None
    try:
        if hours is not None:
            h = int(float(hours))
        if minutes is not None:
            m = int(float(minutes))
    except (TypeError, ValueError):
        h = m = None

    if h is None or m is None or m < 0 or m > 59:
        match = re.search(r"(\d{1,3})\s*[:.\s]\s*(\d{1,2})", str(label or ""))
        if not match:
            return None
        h, m = int(match.group(1)), int(match.group(2))

    if h < 0 or m < 0 or m > 59:
        return None
    total = h * 60 + m
    if total > int(DKACEC_DURATION_HOURS) * 60:
        return None
    return {"hours": h, "minutes": m, "total_minutes": total, "label": f"{h:02d}:{m:02d}"}


def _dkacec_remaining_from(total_minutes: int) -> Dict[str, Any]:
    """192:00 minus the machine's running time -> countdown start value."""
    rem = max(0, int(DKACEC_DURATION_HOURS) * 60 - int(total_minutes))
    return {
        "remaining_minutes": rem,
        "remaining_seconds": rem * 60,
        "remaining_hours": rem // 60,
        "remaining_mins": rem % 60,
        "remaining_label": f"{rem // 60:02d}:{rem % 60:02d}",
    }


async def run_dkacec_runhours_ocr(image_b64: str) -> dict:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"dkacec-runhours-{uuid.uuid4()}",
        system_message=(
            "You are a precise OCR model for industrial machine screens. You read chart axis labels "
            "exactly as printed and only output JSON."
        ),
    ).with_model("gemini", "gemini-3.1-pro-preview")
    resp = await _llm_send_with_retry(
        chat,
        UserMessage(text=DKACEC_RUNHOURS_PROMPT, file_contents=[ImageContent(image_base64=image_b64)]),
    )
    return _parse_ai_json(resp if isinstance(resp, str) else str(resp))


async def _run_dkacec_runhours_job(job_id: str, image_path: str):
    try:
        content, _ = await run_in_threadpool(get_source_object, image_path)
        small = await run_in_threadpool(_downscale_for_ai, content)
        b64 = base64.b64encode(small).decode("utf-8")
        ai = await run_dkacec_runhours_ocr(b64)

        labels = ai.get("axis_labels")
        labels = [str(x).strip() for x in labels if str(x).strip()] if isinstance(labels, list) else []
        last_label = str(ai.get("last_label") or "").strip() or (labels[-1] if labels else "")

        reading = _dkacec_norm_hhmm(ai.get("hours"), ai.get("minutes"), last_label)
        # Fall back to the largest axis label if the reported "last" one is unusable.
        if reading is None:
            parsed = [p for p in (_dkacec_norm_hhmm(None, None, l) for l in labels) if p]
            reading = max(parsed, key=lambda p: p["total_minutes"]) if parsed else None
        if reading is None:
            raise ValueError(
                "Angka jam running tidak terbaca pada foto. Pastikan sumbu X grafik (deretan angka "
                "seperti 70:27) terlihat jelas, lalu ulangi."
            )

        result = {
            **reading,
            "axis_labels": labels,
            "duration_hours": DKACEC_DURATION_HOURS,
            **_dkacec_remaining_from(reading["total_minutes"]),
            "confidence": ai.get("confidence"),
            "raw_text": str(ai.get("raw_text") or ""),
        }
        await db.dkacec_runhours_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "done", "result": result, "finished_at": now_iso()}},
        )
    except Exception as e:
        logger.exception("DKA-CEC run-hours OCR job failed")
        await db.dkacec_runhours_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "error", "error": friendly_ai_error(e), "finished_at": now_iso()}},
        )


@api_router.post("/dkacec/runhours/start", response_model=DkacecOcrJob)
async def dkacec_runhours_start(req: DkacecOcrRequest):
    if not (req.image_path or "").strip():
        raise HTTPException(status_code=400, detail="image_path wajib diisi.")
    try:
        await run_in_threadpool(get_source_object, req.image_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found in storage")
    job = DkacecOcrJob()
    await db.dkacec_runhours_jobs.insert_one(job.model_dump())
    asyncio.create_task(_run_dkacec_runhours_job(job.id, req.image_path))
    return job


@api_router.get("/dkacec/runhours/jobs/{job_id}", response_model=DkacecOcrJob)
async def dkacec_runhours_job_status(job_id: str):
    doc = await db.dkacec_runhours_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return DkacecOcrJob(**doc)


class DkacecRunHoursPreview(BaseModel):
    hours: int = 0
    minutes: int = 0


@api_router.post("/dkacec/runhours/preview")
async def dkacec_runhours_preview(req: DkacecRunHoursPreview):
    """Hitung sisa waktu (192:00 - jam running) untuk koreksi manual di UI."""
    reading = _dkacec_norm_hhmm(req.hours, req.minutes)
    if reading is None:
        raise HTTPException(
            status_code=400,
            detail=f"Jam running tidak valid. Menit 0-59 dan maksimal {int(DKACEC_DURATION_HOURS)} jam.",
        )
    return {**reading, "duration_hours": DKACEC_DURATION_HOURS, **_dkacec_remaining_from(reading["total_minutes"])}


@api_router.get("/dkacec/methods")
async def dkacec_methods():
    return {"methods": DKACEC_METHODS, "max_samples": DKACEC_MAX_SAMPLES, "duration_hours": DKACEC_DURATION_HOURS}


@api_router.get("/dkacec/active")
async def dkacec_active():
    doc = await _dkacec_active_doc()
    return {"active": _dkacec_public(doc) if doc else None}


@api_router.get("/dkacec/runs")
async def dkacec_runs():
    docs = await db.dkacec_runs.find({"deleted_at": None}, {"_id": 0}).sort("created_at", -1).to_list(300)
    return [_dkacec_public(d) for d in docs]


class DkacecBatchSubmitRequest(BaseModel):
    sample_codes: List[str] = Field(default_factory=list)
    temperature_c: Optional[float] = None
    duration_hours: Optional[float] = None
    method_code: Optional[str] = None
    operator: str = ""
    notes: str = ""
    image_path: Optional[str] = None
    ocr_raw: str = ""
    # Jam running terbaca dari layar monitor (OCR / koreksi manual).
    # Timer mulai dari 192:00 - running_hours:running_minutes.
    running_hours: Optional[int] = None
    running_minutes: Optional[int] = None
    runhours_image_path: Optional[str] = None


@api_router.post("/dkacec/submit-batch")
async def dkacec_submit_batch(req: DkacecBatchSubmitRequest):
    codes, seen = [], set()
    for c in (req.sample_codes or []):
        s = (c or "").strip()
        key = s.upper()
        if s and key not in seen:
            seen.add(key)
            codes.append(s)
    if not codes:
        raise HTTPException(status_code=400, detail="Minimal satu kode sampel harus diisi.")

    truncated = len(codes) > DKACEC_MAX_SAMPLES
    codes = codes[:DKACEC_MAX_SAMPLES]

    added, skipped = [], []
    active = await _dkacec_active_doc()
    if active:
        finish = _parse_iso(active.get("finish_at"))
        if datetime.now(timezone.utc) >= finish:
            raise HTTPException(
                status_code=409,
                detail="Run sebelumnya sudah SELESAI. Konfirmasi/arsipkan dulu sebelum memulai run baru.",
            )
        existing = active.get("samples", [])
        existing_codes = {s.get("sample_code", "").upper() for s in existing}
        slots = DKACEC_MAX_SAMPLES - len(existing)
        to_push = []
        for code in codes:
            if code.upper() in existing_codes:
                skipped.append({"code": code, "reason": "duplikat"})
                continue
            if len(to_push) >= slots:
                skipped.append({"code": code, "reason": "batch penuh"})
                continue
            to_push.append(DkacecSample(sample_code=code).model_dump())
            existing_codes.add(code.upper())
            added.append(code)
        if to_push:
            await db.dkacec_runs.update_one(
                {"id": active["id"]}, {"$push": {"samples": {"$each": to_push}}}
            )
        doc = await db.dkacec_runs.find_one({"id": active["id"]}, {"_id": 0})
        return {
            "run": _dkacec_public(doc), "created": False,
            "added": added, "skipped": skipped, "truncated": truncated,
            "max_samples": DKACEC_MAX_SAMPLES,
        }

    # No active run — start a new batch.
    method = None
    if req.method_code:
        method = next((m for m in DKACEC_METHODS if m["code"] == req.method_code), None)
    if method is None:
        method = _dkacec_method_for(req.temperature_c)

    temperature = req.temperature_c or (method["temperature_c"] if method else 0)
    duration = req.duration_hours or (method["duration_hours"] if method else DKACEC_DURATION_HOURS)
    if (not temperature or float(temperature) <= 0) and method is None:
        raise HTTPException(
            status_code=400,
            detail="Suhu uji tidak terdeteksi. Pilih metode (150/160/180°C) atau masukkan suhu manual.",
        )

    start = datetime.now(timezone.utc)

    # Jam running mesin (OCR layar monitor / koreksi manual): timer mulai dari
    # 192:00 - jam running. start_at digeser ke belakang sebesar jam running
    # supaya progress bar mencerminkan progres nyata mesin.
    reading = None
    if req.running_hours is not None or req.running_minutes is not None:
        reading = _dkacec_norm_hhmm(req.running_hours or 0, req.running_minutes or 0)
        if reading is None:
            raise HTTPException(
                status_code=400,
                detail=f"Jam running tidak valid. Menit 0-59 dan maksimal {int(DKACEC_DURATION_HOURS)} jam.",
            )
        if reading["total_minutes"] >= float(duration) * 60:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Jam running terbaca ({reading['label']}) sudah mencapai/melebihi durasi uji "
                    f"{int(float(duration))} jam. Tidak ada sisa waktu untuk timer."
                ),
            )

    elapsed_min = reading["total_minutes"] if reading else 0
    finish = start + timedelta(minutes=float(duration) * 60 - elapsed_min)
    run = DkacecRun(
        method_code=method["code"] if method else "",
        method_label=method["label"] if method else f"Custom · {int(float(duration))} jam @ {int(float(temperature or 0))}°C",
        temperature_c=float(temperature or 0),
        duration_hours=float(duration),
        samples=[DkacecSample(sample_code=c) for c in codes],
        operator=req.operator or "",
        notes=req.notes or "",
        image_path=req.image_path,
        ocr_raw=req.ocr_raw or "",
        running_hours=reading["hours"] if reading else 0,
        running_minutes=reading["minutes"] if reading else 0,
        running_label=reading["label"] if reading else "",
        runhours_image_path=req.runhours_image_path,
        start_at=(start - timedelta(minutes=elapsed_min)).isoformat(),
        finish_at=finish.isoformat(),
    )
    await db.dkacec_runs.insert_one(run.model_dump())
    return {
        "run": _dkacec_public(run.model_dump()), "created": True,
        "added": list(codes), "skipped": skipped, "truncated": truncated,
        "max_samples": DKACEC_MAX_SAMPLES,
    }


@api_router.delete("/dkacec/runs/{run_id}/samples/{sample_code}")
async def dkacec_remove_sample(run_id: str, sample_code: str):
    doc = await db.dkacec_runs.find_one({"id": run_id, "deleted_at": None}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Run tidak ditemukan")
    await db.dkacec_runs.update_one(
        {"id": run_id}, {"$pull": {"samples": {"sample_code": sample_code}}}
    )
    doc = await db.dkacec_runs.find_one({"id": run_id}, {"_id": 0})
    return {"run": _dkacec_public(doc)}


@api_router.post("/dkacec/runs/{run_id}/complete")
async def dkacec_complete(run_id: str):
    res = await db.dkacec_runs.update_one(
        {"id": run_id}, {"$set": {"status": "done", "acknowledged": True}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Run tidak ditemukan")
    doc = await db.dkacec_runs.find_one({"id": run_id}, {"_id": 0})
    return {"run": _dkacec_public(doc)}


@api_router.post("/dkacec/runs/{run_id}/stop")
async def dkacec_stop(run_id: str):
    res = await db.dkacec_runs.update_one(
        {"id": run_id}, {"$set": {"status": "stopped", "acknowledged": True}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Run tidak ditemukan")
    doc = await db.dkacec_runs.find_one({"id": run_id}, {"_id": 0})
    return {"run": _dkacec_public(doc)}


@api_router.delete("/dkacec/runs/{run_id}")
async def dkacec_delete(run_id: str):
    res = await db.dkacec_runs.update_one(
        {"id": run_id}, {"$set": {"deleted_at": now_iso()}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Run tidak ditemukan")
    return {"ok": True}




app.include_router(api_router)


# --- Auth guard: protect all /api/* routes except login/me/logout, health,
#     image serving (used in <img> tags) and CORS preflight. Added BEFORE the
#     CORS middleware so CORS remains the outermost layer (401s keep CORS headers).
_AUTH_PUBLIC_EXACT = {"/api", "/api/"}


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api"):
        return await call_next(request)
    if (
        path in _AUTH_PUBLIC_EXACT
        or path.startswith("/api/auth/")
        or path.startswith("/api/kht/files/")
    ):
        return await call_next(request)
    doc = await _validate_session(_extract_token(request))
    if not doc:
        return JSONResponse(status_code=401, content={"detail": "Tidak terautentikasi. Silakan login."})
    return await call_next(request)


_cors_origins = os.environ.get('CORS_ORIGINS', '*').split(',')
# HttpOnly cookie-based sessions require credentialed CORS. The browser rejects
# `Access-Control-Allow-Origin: *` with credentials, so when CORS_ORIGINS is "*"
# we reflect the request origin via regex (Starlette echoes the matched origin).
if "*" in _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_origin_regex=".*",
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
async def startup():
    try:
        await run_in_threadpool(init_storage)
        logger.info("Storage initialized")
    except Exception as e:
        logger.error("Storage init failed: %s", e)
    await seed_reference()
    await seed_kht()
    await seed_dka_reference()
    await seed_dka()
    await seed_copper_reference()
    await seed_copper()
    try:
        await cleanup_legacy_obs_cards()
    except Exception:
        logger.warning("legacy obs cleanup failed", exc_info=True)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
