#!/usr/bin/env python3
"""
Authentication System Test Suite
Tests single-admin login/logout/me + route guard middleware
"""
import os
import sys
import time
import json
import requests
from pathlib import Path

# Load backend URL from frontend .env
env_file = Path("/app/frontend/.env")
BACKEND_URL = "https://rating-lab.preview.emergentagent.com"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BACKEND_URL = line.split("=", 1)[1].strip()
            break

BASE_URL = f"{BACKEND_URL}/api"
print(f"Testing authentication at: {BASE_URL}")

# Admin credentials from /app/memory/test_credentials.md
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Elastech@2026"

# Test results tracking
test_results = {
    "passed": [],
    "failed": []
}

def log_pass(test_name):
    print(f"✅ PASS: {test_name}")
    test_results["passed"].append(test_name)

def log_fail(test_name, reason):
    print(f"❌ FAIL: {test_name}")
    print(f"   Reason: {reason}")
    test_results["failed"].append({"test": test_name, "reason": reason})

def test_login_wrong_password():
    """Test POST /api/auth/login with wrong password → 401"""
    try:
        payload = {"username": ADMIN_USERNAME, "password": "wrongpass"}
        resp = requests.post(f"{BASE_URL}/auth/login", json=payload, timeout=10)
        
        if resp.status_code != 401:
            log_fail("Login with wrong password → 401", 
                    f"Expected 401, got {resp.status_code}: {resp.text}")
            return False
        
        log_pass("Login with wrong password → 401")
        return True
    except Exception as e:
        log_fail("Login with wrong password → 401", str(e))
        return False

def test_login_correct_credentials():
    """Test POST /api/auth/login with correct credentials → 200 with token"""
    try:
        payload = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        resp = requests.post(f"{BASE_URL}/auth/login", json=payload, timeout=10)
        
        if resp.status_code != 200:
            log_fail("Login with correct credentials → 200", 
                    f"Expected 200, got {resp.status_code}: {resp.text}")
            return None
        
        data = resp.json()
        
        # Verify response structure
        if "token" not in data:
            log_fail("Login with correct credentials → 200", "Response missing 'token'")
            return None
        
        if not data["token"] or not isinstance(data["token"], str):
            log_fail("Login with correct credentials → 200", 
                    f"Token should be non-empty string, got: {data['token']}")
            return None
        
        if data.get("username") != ADMIN_USERNAME:
            log_fail("Login with correct credentials → 200", 
                    f"Expected username '{ADMIN_USERNAME}', got '{data.get('username')}'")
            return None
        
        if data.get("ttl_minutes") != 60:
            log_fail("Login with correct credentials → 200", 
                    f"Expected ttl_minutes 60, got {data.get('ttl_minutes')}")
            return None
        
        log_pass("Login with correct credentials → 200 {token, username:admin, ttl_minutes:60}")
        return data["token"]
    except Exception as e:
        log_fail("Login with correct credentials → 200", str(e))
        return None

def test_login_wrong_username():
    """Test POST /api/auth/login with wrong username → 401"""
    try:
        payload = {"username": "wronguser", "password": ADMIN_PASSWORD}
        resp = requests.post(f"{BASE_URL}/auth/login", json=payload, timeout=10)
        
        if resp.status_code != 401:
            log_fail("Login with wrong username → 401", 
                    f"Expected 401, got {resp.status_code}: {resp.text}")
            return False
        
        log_pass("Login with wrong username → 401")
        return True
    except Exception as e:
        log_fail("Login with wrong username → 401", str(e))
        return False

def test_protected_endpoint_without_token():
    """Test GET /api/copper/dashboard WITHOUT token → 401"""
    try:
        resp = requests.get(f"{BASE_URL}/copper/dashboard", timeout=10)
        
        if resp.status_code != 401:
            log_fail("GET /api/copper/dashboard without token → 401", 
                    f"Expected 401, got {resp.status_code}: {resp.text}")
            return False
        
        log_pass("GET /api/copper/dashboard without token → 401")
        return True
    except Exception as e:
        log_fail("GET /api/copper/dashboard without token → 401", str(e))
        return False

def test_protected_endpoint_with_token(token):
    """Test GET /api/copper/dashboard WITH X-Session-Token → 200"""
    try:
        headers = {"X-Session-Token": token}
        resp = requests.get(f"{BASE_URL}/copper/dashboard", headers=headers, timeout=10)
        
        if resp.status_code != 200:
            log_fail("GET /api/copper/dashboard with token → 200", 
                    f"Expected 200, got {resp.status_code}: {resp.text}")
            return False
        
        data = resp.json()
        
        # Verify it returns normal dashboard JSON
        required_keys = ["latest", "total", "passed", "failed"]
        missing = [k for k in required_keys if k not in data]
        if missing:
            log_fail("GET /api/copper/dashboard with token → 200", 
                    f"Dashboard JSON missing keys: {missing}")
            return False
        
        log_pass("GET /api/copper/dashboard with token → 200 (normal dashboard JSON)")
        return True
    except Exception as e:
        log_fail("GET /api/copper/dashboard with token → 200", str(e))
        return False

def test_other_dashboards_with_token(token):
    """Smoke check GET /api/dka/dashboard and /api/kht/dashboard WITH token → 200"""
    headers = {"X-Session-Token": token}
    
    # Test DKA dashboard
    try:
        resp = requests.get(f"{BASE_URL}/dka/dashboard", headers=headers, timeout=10)
        if resp.status_code != 200:
            log_fail("GET /api/dka/dashboard with token → 200", 
                    f"Expected 200, got {resp.status_code}: {resp.text}")
        else:
            log_pass("GET /api/dka/dashboard with token → 200")
    except Exception as e:
        log_fail("GET /api/dka/dashboard with token → 200", str(e))
    
    # Test KHT dashboard
    try:
        resp = requests.get(f"{BASE_URL}/kht/dashboard", headers=headers, timeout=10)
        if resp.status_code != 200:
            log_fail("GET /api/kht/dashboard with token → 200", 
                    f"Expected 200, got {resp.status_code}: {resp.text}")
        else:
            log_pass("GET /api/kht/dashboard with token → 200")
    except Exception as e:
        log_fail("GET /api/kht/dashboard with token → 200", str(e))

def test_auth_me_without_token():
    """Test GET /api/auth/me WITHOUT token → 401"""
    try:
        resp = requests.get(f"{BASE_URL}/auth/me", timeout=10)
        
        if resp.status_code != 401:
            log_fail("GET /api/auth/me without token → 401", 
                    f"Expected 401, got {resp.status_code}: {resp.text}")
            return False
        
        log_pass("GET /api/auth/me without token → 401")
        return True
    except Exception as e:
        log_fail("GET /api/auth/me without token → 401", str(e))
        return False

def test_auth_me_with_valid_token(token):
    """Test GET /api/auth/me WITH valid token → 200 {username, ttl_minutes}"""
    try:
        headers = {"X-Session-Token": token}
        resp = requests.get(f"{BASE_URL}/auth/me", headers=headers, timeout=10)
        
        if resp.status_code != 200:
            log_fail("GET /api/auth/me with valid token → 200", 
                    f"Expected 200, got {resp.status_code}: {resp.text}")
            return False
        
        data = resp.json()
        
        if data.get("username") != ADMIN_USERNAME:
            log_fail("GET /api/auth/me with valid token → 200", 
                    f"Expected username '{ADMIN_USERNAME}', got '{data.get('username')}'")
            return False
        
        if data.get("ttl_minutes") != 60:
            log_fail("GET /api/auth/me with valid token → 200", 
                    f"Expected ttl_minutes 60, got {data.get('ttl_minutes')}")
            return False
        
        log_pass("GET /api/auth/me with valid token → 200 {username:admin, ttl_minutes:60}")
        return True
    except Exception as e:
        log_fail("GET /api/auth/me with valid token → 200", str(e))
        return False

def test_auth_me_with_garbage_token():
    """Test GET /api/auth/me WITH garbage token → 401"""
    try:
        headers = {"X-Session-Token": "abc123"}
        resp = requests.get(f"{BASE_URL}/auth/me", headers=headers, timeout=10)
        
        if resp.status_code != 401:
            log_fail("GET /api/auth/me with garbage token → 401", 
                    f"Expected 401, got {resp.status_code}: {resp.text}")
            return False
        
        log_pass("GET /api/auth/me with garbage token → 401")
        return True
    except Exception as e:
        log_fail("GET /api/auth/me with garbage token → 401", str(e))
        return False

def test_public_health_endpoint():
    """Test GET /api/ (health) → 200"""
    try:
        resp = requests.get(f"{BASE_URL}/", timeout=10)
        
        if resp.status_code != 200:
            log_fail("GET /api/ (health) → 200", 
                    f"Expected 200, got {resp.status_code}: {resp.text}")
            return False
        
        log_pass("GET /api/ (health) → 200")
        return True
    except Exception as e:
        log_fail("GET /api/ (health) → 200", str(e))
        return False

def test_public_image_serving():
    """Test GET /api/kht/files/nonexistentfile → NOT 401 (404 is acceptable)"""
    try:
        resp = requests.get(f"{BASE_URL}/kht/files/nonexistentfile", timeout=10)
        
        if resp.status_code == 401:
            log_fail("GET /api/kht/files/nonexistentfile → NOT 401", 
                    "Image serving should be public, got 401")
            return False
        
        # 404 is expected for non-existent file
        if resp.status_code == 404:
            log_pass("GET /api/kht/files/nonexistentfile → 404 (public, not 401)")
            return True
        
        # Any other status is also acceptable as long as it's not 401
        log_pass(f"GET /api/kht/files/nonexistentfile → {resp.status_code} (public, not 401)")
        return True
    except Exception as e:
        log_fail("GET /api/kht/files/nonexistentfile → NOT 401", str(e))
        return False

def test_logout_invalidates_session(token):
    """Test POST /api/auth/logout → 200, then reusing token → 401"""
    try:
        # Step 1: Logout
        headers = {"X-Session-Token": token}
        resp = requests.post(f"{BASE_URL}/auth/logout", headers=headers, timeout=10)
        
        if resp.status_code != 200:
            log_fail("POST /api/auth/logout → 200", 
                    f"Expected 200, got {resp.status_code}: {resp.text}")
            return False
        
        data = resp.json()
        if not data.get("ok"):
            log_fail("POST /api/auth/logout → 200", 
                    f"Expected {{ok:true}}, got {data}")
            return False
        
        log_pass("POST /api/auth/logout → 200 {ok:true}")
        
        # Step 2: Try to use the same token on a protected endpoint
        resp2 = requests.get(f"{BASE_URL}/copper/dashboard", headers=headers, timeout=10)
        
        if resp2.status_code != 401:
            log_fail("Reuse token after logout → 401", 
                    f"Expected 401, got {resp2.status_code}: {resp2.text}")
            return False
        
        log_pass("GET /api/copper/dashboard with logged-out token → 401")
        
        # Step 3: Try /api/auth/me with the same token
        resp3 = requests.get(f"{BASE_URL}/auth/me", headers=headers, timeout=10)
        
        if resp3.status_code != 401:
            log_fail("GET /api/auth/me with logged-out token → 401", 
                    f"Expected 401, got {resp3.status_code}: {resp3.text}")
            return False
        
        log_pass("GET /api/auth/me with logged-out token → 401")
        
        return True
    except Exception as e:
        log_fail("Logout invalidates session", str(e))
        return False

def test_sliding_expiry(token):
    """Test sliding expiry: call /api/auth/me three times, all should return 200"""
    try:
        headers = {"X-Session-Token": token}
        
        for i in range(1, 4):
            resp = requests.get(f"{BASE_URL}/auth/me", headers=headers, timeout=10)
            
            if resp.status_code != 200:
                log_fail(f"Sliding expiry check (call {i}/3) → 200", 
                        f"Expected 200, got {resp.status_code}: {resp.text}")
                return False
            
            data = resp.json()
            if data.get("username") != ADMIN_USERNAME:
                log_fail(f"Sliding expiry check (call {i}/3) → 200", 
                        f"Expected username '{ADMIN_USERNAME}', got '{data.get('username')}'")
                return False
            
            # Small delay between calls
            if i < 3:
                time.sleep(0.5)
        
        log_pass("Sliding expiry: 3 consecutive /api/auth/me calls → all 200 (expiry refreshed)")
        return True
    except Exception as e:
        log_fail("Sliding expiry check", str(e))
        return False

def main():
    print("=" * 80)
    print("AUTHENTICATION SYSTEM TEST SUITE")
    print("=" * 80)
    print()
    
    # 1. Login scenarios
    print("=== Testing Login Scenarios ===")
    test_login_wrong_password()
    valid_token = test_login_correct_credentials()
    test_login_wrong_username()
    print()
    
    if not valid_token:
        print("❌ CRITICAL: Cannot proceed without valid token")
        sys.exit(1)
    
    # 2. Route guard on existing endpoints
    print("=== Testing Route Guard ===")
    test_protected_endpoint_without_token()
    test_protected_endpoint_with_token(valid_token)
    test_other_dashboards_with_token(valid_token)
    print()
    
    # 3. /api/auth/me endpoint
    print("=== Testing /api/auth/me Endpoint ===")
    test_auth_me_without_token()
    test_auth_me_with_valid_token(valid_token)
    test_auth_me_with_garbage_token()
    print()
    
    # 4. Public paths
    print("=== Testing Public Paths ===")
    test_public_health_endpoint()
    test_public_image_serving()
    print()
    
    # 5. Logout invalidates session
    print("=== Testing Logout ===")
    test_logout_invalidates_session(valid_token)
    print()
    
    # 6. Sliding expiry (need a fresh token)
    print("=== Testing Sliding Expiry ===")
    payload = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    resp = requests.post(f"{BASE_URL}/auth/login", json=payload, timeout=10)
    if resp.status_code == 200:
        fresh_token = resp.json()["token"]
        test_sliding_expiry(fresh_token)
    else:
        log_fail("Sliding expiry test", "Could not get fresh token for sliding expiry test")
    print()
    
    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"✅ Passed: {len(test_results['passed'])}")
    print(f"❌ Failed: {len(test_results['failed'])}")
    
    if test_results["failed"]:
        print("\nFailed Tests:")
        for fail in test_results["failed"]:
            print(f"  - {fail['test']}: {fail['reason']}")
    
    print("\n" + "=" * 80)
    
    # Exit with appropriate code
    sys.exit(0 if len(test_results["failed"]) == 0 else 1)

if __name__ == "__main__":
    main()
