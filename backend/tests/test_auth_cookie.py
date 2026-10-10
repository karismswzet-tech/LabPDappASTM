"""Tests for HttpOnly cookie-based auth migration."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://webapp-rating.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
COOKIE_NAME = "elastech_session"

ORIGIN = "https://example-origin.test"


@pytest.fixture
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture
def logged_in(session):
    r = session.post(f"{API}/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    assert COOKIE_NAME in session.cookies, "elastech_session cookie not set"
    return session


# --- login ---
def test_login_sets_httponly_cookie_and_no_token_in_body(session):
    r = session.post(f"{API}/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    body = r.json()
    assert "token" not in body, f"body must not include 'token', got {body}"
    assert body.get("username") == "admin"
    assert body.get("ttl_minutes") == 60

    # Set-Cookie must be present with HttpOnly, Secure, SameSite=None
    set_cookie = r.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie, set_cookie
    sc_lower = set_cookie.lower()
    assert "httponly" in sc_lower
    assert "secure" in sc_lower
    assert "samesite=none" in sc_lower


def test_login_invalid_credentials(session):
    r = session.post(f"{API}/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


# --- /auth/me ---
def test_me_with_cookie(logged_in):
    r = logged_in.get(f"{API}/auth/me")
    assert r.status_code == 200
    data = r.json()
    assert data.get("username") == "admin"
    assert data.get("ttl_minutes") == 60


def test_me_without_auth_is_401():
    r = requests.get(f"{API}/auth/me")
    assert r.status_code == 401


# --- logout ---
def test_logout_deletes_cookie_and_invalidates(logged_in):
    r = logged_in.post(f"{API}/auth/logout")
    assert r.status_code == 200
    sc = r.headers.get("set-cookie", "")
    assert COOKIE_NAME in sc
    # Deletion is indicated by empty value or expires in the past / Max-Age=0
    sc_lower = sc.lower()
    assert ("max-age=0" in sc_lower) or ("expires=" in sc_lower) or (f'{COOKIE_NAME}=""' in sc) or (f"{COOKIE_NAME}=;" in sc)
    # After logout, /auth/me must be 401 (even if the cookie wasn't cleared client-side,
    # the server deleted the session row)
    r2 = requests.get(f"{API}/auth/me", cookies={COOKIE_NAME: "doesnotexist"})
    assert r2.status_code == 401


# --- protected endpoints ---
PROTECTED = [
    "/kht/dashboard",
    "/dka/dashboard",
    "/copper/dashboard",
    "/htcbt/active",
    "/dkacec/active",
]


@pytest.mark.parametrize("path", PROTECTED)
def test_protected_requires_auth(path):
    r = requests.get(f"{API}{path}")
    assert r.status_code == 401, f"{path} should require auth, got {r.status_code}"


@pytest.mark.parametrize("path", PROTECTED)
def test_protected_with_cookie(logged_in, path):
    r = logged_in.get(f"{API}{path}")
    assert r.status_code == 200, f"{path} -> {r.status_code} body={r.text[:200]}"


# --- CORS preflight ---
def test_cors_preflight_login_credentialed():
    r = requests.options(
        f"{API}/auth/login",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code in (200, 204), r.status_code
    # Must allow credentials
    allow_creds = r.headers.get("access-control-allow-credentials", "").lower()
    assert allow_creds == "true", f"allow-credentials header missing/false: {dict(r.headers)}"
    # Must NOT be '*' when credentialed
    allow_origin = r.headers.get("access-control-allow-origin", "")
    assert allow_origin != "*", f"allow-origin must not be '*' with credentials, got {allow_origin!r}"
    # Should reflect our Origin
    assert allow_origin == ORIGIN, f"allow-origin expected to reflect {ORIGIN}, got {allow_origin!r}"
