"""Smoke test for freshly re-imported Elastech lab suite.
Verifies: health, login via HttpOnly cookie, auth-required endpoints 401 vs 200,
list/history endpoints for every module, logout.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://astm-rating-app.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

# Endpoints that must be auth-protected and return list/dict JSON when authed
PROTECTED_LIST_ENDPOINTS = [
    "/kht/tests", "/kht/dashboard", "/kht/trend",
    "/dka/tests", "/dka/dashboard", "/dka/trend",
    "/copper/tests", "/copper/dashboard", "/copper/trend",
    "/rust/tests", "/rust/dashboard", "/rust/trend",
    "/htcbt/runs", "/htcbt/methods", "/htcbt/active",
]


@pytest.fixture(scope="session")
def unauth_session():
    s = requests.Session()
    return s


@pytest.fixture(scope="session")
def auth_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login",
               json={"username": "admin", "password": "admin123"},
               timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("username") == "admin"
    assert "ttl_minutes" in data
    # Verify HttpOnly cookie was set
    assert "elastech_session" in s.cookies, f"cookie not set: {s.cookies}"
    return s


class TestAuth:
    def test_login_success_sets_cookie(self, auth_session):
        assert "elastech_session" in auth_session.cookies

    def test_login_bad_password(self, unauth_session):
        r = unauth_session.post(f"{API}/auth/login",
                                json={"username": "admin", "password": "wrong"},
                                timeout=10)
        assert r.status_code in (400, 401, 403)

    def test_auth_me_requires_cookie(self, unauth_session):
        r = unauth_session.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 401

    def test_auth_me_with_cookie(self, auth_session):
        r = auth_session.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 200
        assert r.json().get("username") == "admin"


class TestProtectedEndpoints:
    @pytest.mark.parametrize("path", PROTECTED_LIST_ENDPOINTS)
    def test_endpoint_requires_auth(self, unauth_session, path):
        r = unauth_session.get(f"{API}{path}", timeout=15)
        assert r.status_code == 401, f"{path} should 401 unauth, got {r.status_code}"

    @pytest.mark.parametrize("path", PROTECTED_LIST_ENDPOINTS)
    def test_endpoint_responds_authed(self, auth_session, path):
        r = auth_session.get(f"{API}{path}", timeout=20)
        assert r.status_code == 200, f"{path} authed got {r.status_code} {r.text[:200]}"
        body = r.json()
        assert isinstance(body, (list, dict))


class TestReferenceScales:
    @pytest.mark.parametrize("path", [
        "/kht/color-scale", "/dka/reference-scale",
        "/copper/reference-scale", "/rust/reference-scale",
    ])
    def test_scale_endpoint(self, auth_session, path):
        r = auth_session.get(f"{API}{path}", timeout=15)
        assert r.status_code == 200


class TestLogout:
    def test_logout_clears_cookie(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login",
                   json={"username": "admin", "password": "admin123"},
                   timeout=15)
        assert r.status_code == 200
        r2 = s.post(f"{API}/auth/logout", timeout=10)
        assert r2.status_code == 200
        # After logout, /auth/me should 401
        r3 = s.get(f"{API}/auth/me", timeout=10)
        assert r3.status_code == 401
