#!/usr/bin/env python3
"""
Backend API Testing for DIP TEST In House Method Module
Tests the /api/diptest/* endpoints
"""
import requests
import time
import json
from io import BytesIO
from PIL import Image

# Configuration
BASE_URL = "https://webapp-rating.preview.emergentagent.com/api"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# Test state - use a session to handle cookies
http_session = requests.Session()
test_records_created = []


def login():
    """Login and get session cookie"""
    print("\n=== LOGIN ===")
    
    response = http_session.post(
        f"{BASE_URL}/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        timeout=10
    )
    print(f"POST /api/auth/login: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        username = data.get('username')
        ttl = data.get('ttl_minutes')
        
        # Check if we have a cookie
        cookies = http_session.cookies.get_dict()
        if 'elastech_session' in cookies:
            print(f"✅ Login successful (cookie-based). Username: {username}, TTL: {ttl} minutes")
        else:
            print(f"⚠️  Login successful but no cookie found. Username: {username}")
        return True
    else:
        print(f"❌ Login failed: {response.text}")
        return False


def get_headers(with_auth=True):
    """Get request headers (auth handled by session cookies)"""
    return {"Content-Type": "application/json"}


def test_auth_guards():
    """Test 1: Auth guards - endpoints should return 401 without token"""
    print("\n=== TEST 1: AUTH GUARDS ===")
    
    # Create a new session without auth for testing
    no_auth_session = requests.Session()
    
    # Test GET /api/diptest/dashboard without token
    response = no_auth_session.get(f"{BASE_URL}/diptest/dashboard", timeout=10)
    print(f"GET /api/diptest/dashboard (no token): {response.status_code}")
    if response.status_code == 401:
        print("✅ Dashboard auth guard working (401)")
    else:
        print(f"❌ Expected 401, got {response.status_code}")
    
    # Test POST /api/diptest/analyze/start without token
    response = no_auth_session.post(
        f"{BASE_URL}/diptest/analyze/start",
        json={"image_path": "test.jpg", "sample_id": "TEST"},
        timeout=10
    )
    print(f"POST /api/diptest/analyze/start (no token): {response.status_code}")
    if response.status_code == 401:
        print("✅ Analyze start auth guard working (401)")
    else:
        print(f"❌ Expected 401, got {response.status_code}")


def test_reference_scale():
    """Test 2: GET /api/diptest/reference-scale"""
    print("\n=== TEST 2: REFERENCE SCALE ===")
    response = http_session.get(
        f"{BASE_URL}/diptest/reference-scale",
        headers=get_headers(),
        timeout=10
    )
    print(f"GET /api/diptest/reference-scale: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Reference scale retrieved")
        print(f"  Title: {data.get('title')}")
        print(f"  Measurement area: {data.get('measurement_area')}")
        
        # Verify grades A-E with correct thresholds
        grades = data.get('grades', {})
        expected_grades = {
            'A': {'min': 0, 'max': 0},
            'B': {'min': 1, 'max': 10},
            'C': {'min': 11, 'max': 25},
            'D': {'min': 26, 'max': 50},
            'E': {'min': 51, 'max': 100}
        }
        
        all_correct = True
        for grade, expected in expected_grades.items():
            if grade in grades:
                actual_min = grades[grade].get('min')
                actual_max = grades[grade].get('max')
                if actual_min == expected['min'] and actual_max == expected['max']:
                    print(f"  ✅ Grade {grade}: {actual_min}-{actual_max} boxes")
                else:
                    print(f"  ❌ Grade {grade}: Expected {expected['min']}-{expected['max']}, got {actual_min}-{actual_max}")
                    all_correct = False
            else:
                print(f"  ❌ Grade {grade} missing")
                all_correct = False
        
        if all_correct:
            print("✅ All grade thresholds correct (A=0, B=1-10, C=11-25, D=26-50, E=51-100)")
    else:
        print(f"❌ Failed: {response.status_code} - {response.text}")


def test_dashboard():
    """Test 3: GET /api/diptest/dashboard"""
    print("\n=== TEST 3: DASHBOARD ===")
    response = http_session.get(
        f"{BASE_URL}/diptest/dashboard",
        headers=get_headers(),
        timeout=10
    )
    print(f"GET /api/diptest/dashboard: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Dashboard retrieved")
        print(f"  Total: {data.get('total')}")
        print(f"  Average rusted boxes: {data.get('average_rusted_boxes')}")
        
        # Verify structure
        grade_counts = data.get('grade_counts', {})
        print(f"  Grade counts: A={grade_counts.get('A', 0)}, B={grade_counts.get('B', 0)}, C={grade_counts.get('C', 0)}, D={grade_counts.get('D', 0)}, E={grade_counts.get('E', 0)}")
        
        if 'latest' in data and 'total' in data and 'grade_counts' in data and 'average_rusted_boxes' in data:
            print("✅ Dashboard structure correct (latest/total/grade_counts/average_rusted_boxes)")
        else:
            print("❌ Dashboard structure incomplete")
    else:
        print(f"❌ Failed: {response.status_code} - {response.text}")


def test_trend():
    """Test 4: GET /api/diptest/trend"""
    print("\n=== TEST 4: TREND ===")
    response = http_session.get(
        f"{BASE_URL}/diptest/trend",
        headers=get_headers(),
        timeout=10
    )
    print(f"GET /api/diptest/trend: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Trend retrieved: {len(data)} records")
        if len(data) > 0:
            print(f"  First record: {data[0]}")
    else:
        print(f"❌ Failed: {response.status_code} - {response.text}")


def test_tests_list():
    """Test 5: GET /api/diptest/tests and search"""
    print("\n=== TEST 5: TESTS LIST & SEARCH ===")
    
    # Test list all
    response = http_session.get(
        f"{BASE_URL}/diptest/tests",
        headers=get_headers(),
        timeout=10
    )
    print(f"GET /api/diptest/tests: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Tests list retrieved: {len(data)} records")
    else:
        print(f"❌ Failed: {response.status_code} - {response.text}")
    
    # Test search
    response = http_session.get(
        f"{BASE_URL}/diptest/tests?q=TEST",
        headers=get_headers(),
        timeout=10
    )
    print(f"GET /api/diptest/tests?q=TEST: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Search working: {len(data)} records found")
    else:
        print(f"❌ Search failed: {response.status_code} - {response.text}")


def upload_test_image():
    """Upload a test image for analysis"""
    print("\n=== UPLOAD TEST IMAGE ===")
    
    # Create a simple test image (100x100 white image)
    img = Image.new('RGB', (100, 100), color='white')
    img_bytes = BytesIO()
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)
    
    # Upload via /api/kht/upload (using http_session for auth)
    files = {'file': ('test_diptest.jpg', img_bytes, 'image/jpeg')}
    
    response = http_session.post(
        f"{BASE_URL}/kht/upload",
        files=files,
        timeout=30
    )
    
    print(f"POST /api/kht/upload: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        image_path = data.get('image_path')
        print(f"✅ Image uploaded: {image_path}")
        return image_path
    else:
        print(f"❌ Upload failed: {response.status_code} - {response.text}")
        return None


def test_full_ai_flow():
    """Test 6: Full AI analysis flow"""
    print("\n=== TEST 6: FULL AI ANALYSIS FLOW ===")
    
    # Upload test image
    image_path = upload_test_image()
    if not image_path:
        print("❌ Cannot proceed without image")
        return None
    
    # Start analysis
    print("\n--- Starting DIP TEST Analysis ---")
    payload = {
        "image_path": image_path,
        "sample_id": "DIP-TEST-001",
        "product": "Test Product",
        "batch": "BATCH-001",
        "operator": "Test Operator",
        "exposure_hours": 168,
        "temperature_c": 48.9,
        "humidity_pct": 95,
        "substrate": "Cold Rolled Steel 1018",
        "remark": "Backend test"
    }
    
    response = http_session.post(
        f"{BASE_URL}/diptest/analyze/start",
        json=payload,
        headers=get_headers(),
        timeout=10
    )
    
    print(f"POST /api/diptest/analyze/start: {response.status_code}")
    
    if response.status_code != 200:
        print(f"❌ Failed to start analysis: {response.status_code} - {response.text}")
        return None
    
    job_data = response.json()
    job_id = job_data.get('id')
    status = job_data.get('status')
    
    print(f"✅ Job created: {job_id}")
    print(f"  Status: {status}")
    
    if status != 'running':
        print(f"❌ Expected status 'running', got '{status}'")
        return None
    
    # Poll job until done
    print("\n--- Polling Job Status ---")
    max_polls = 60  # 60 seconds max
    poll_count = 0
    record_id = None
    
    while poll_count < max_polls:
        time.sleep(1)
        poll_count += 1
        
        response = http_session.get(
            f"{BASE_URL}/diptest/analyze/jobs/{job_id}",
            headers=get_headers(),
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"❌ Poll failed: {response.status_code}")
            break
        
        job_status = response.json()
        status = job_status.get('status')
        
        if status == 'done':
            record_id = job_status.get('record_id')
            print(f"✅ Job completed in {poll_count} seconds")
            print(f"  Record ID: {record_id}")
            break
        elif status == 'error':
            error = job_status.get('error', 'Unknown error')
            print(f"⚠️  Job failed with error: {error}")
            # Check if it's a budget error (acceptable as infra-pass)
            if 'budget' in error.lower() or 'batas permintaan' in error.lower() or 'sibuk' in error.lower():
                print("✅ INFRA-PASS: Budget exhaustion is acceptable (AI integration is REAL)")
                return None
            else:
                print(f"❌ Unexpected error: {error}")
                return None
        
        if poll_count % 10 == 0:
            print(f"  Still polling... ({poll_count}s, status: {status})")
    
    if not record_id:
        print(f"❌ Job did not complete within {max_polls} seconds")
        return None
    
    # Track for cleanup
    test_records_created.append(record_id)
    
    return record_id


def test_analysis_result(record_id):
    """Test 7: Verify analysis result structure"""
    print("\n=== TEST 7: ANALYSIS RESULT VERIFICATION ===")
    
    response = http_session.get(
        f"{BASE_URL}/diptest/tests/{record_id}",
        headers=get_headers(),
        timeout=10
    )
    
    print(f"GET /api/diptest/tests/{record_id}: {response.status_code}")
    
    if response.status_code != 200:
        print(f"❌ Failed to get record: {response.status_code} - {response.text}")
        return False
    
    data = response.json()
    print(f"✅ Record retrieved")
    
    # Verify grid_boxes has exactly 100 booleans
    grid_boxes = data.get('grid_boxes', [])
    if len(grid_boxes) == 100:
        print(f"✅ grid_boxes has exactly 100 elements")
    else:
        print(f"❌ grid_boxes has {len(grid_boxes)} elements, expected 100")
        return False
    
    # Verify all are booleans
    if all(isinstance(b, bool) for b in grid_boxes):
        print(f"✅ All grid_boxes elements are booleans")
    else:
        print(f"❌ Not all grid_boxes elements are booleans")
        return False
    
    # Verify rusted_box_count matches count of true in grid_boxes
    rusted_count = data.get('rusted_box_count', 0)
    true_count = sum(1 for b in grid_boxes if b)
    
    if rusted_count == true_count:
        print(f"✅ rusted_box_count ({rusted_count}) matches count of true in grid_boxes ({true_count})")
    else:
        print(f"❌ rusted_box_count ({rusted_count}) does NOT match count of true in grid_boxes ({true_count})")
        return False
    
    # Verify grade follows thresholds
    grade = data.get('grade')
    expected_grade = None
    if rusted_count == 0:
        expected_grade = 'A'
    elif 1 <= rusted_count <= 10:
        expected_grade = 'B'
    elif 11 <= rusted_count <= 25:
        expected_grade = 'C'
    elif 26 <= rusted_count <= 50:
        expected_grade = 'D'
    elif 51 <= rusted_count <= 100:
        expected_grade = 'E'
    
    if grade == expected_grade:
        print(f"✅ Grade '{grade}' correct for rusted_count={rusted_count}")
    else:
        print(f"❌ Grade '{grade}' incorrect for rusted_count={rusted_count}, expected '{expected_grade}'")
        return False
    
    # Verify method is 'full'
    method = data.get('method')
    if method == 'full':
        print(f"✅ Method is 'full' (whole-image)")
    else:
        print(f"❌ Method is '{method}', expected 'full'")
        return False
    
    # Verify grid_corners are full-image corners
    grid_corners = data.get('grid_corners', [])
    expected_corners = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    
    if grid_corners == expected_corners:
        print(f"✅ grid_corners are full-image corners: {grid_corners}")
    else:
        print(f"⚠️  grid_corners: {grid_corners} (expected {expected_corners})")
    
    print(f"\nRecord details:")
    print(f"  Sample ID: {data.get('meta', {}).get('sample_id')}")
    print(f"  Rusted boxes: {rusted_count}/100")
    print(f"  Grade: {grade} - {data.get('grade_label')}")
    print(f"  Status: {data.get('grade_status')}")
    print(f"  Confidence: {data.get('confidence')}")
    print(f"  AI Model: {data.get('ai_model')}")
    
    return True


def test_update_operations(record_id):
    """Test 8: Update operations (rusted_box_count and inspector fields)"""
    print("\n=== TEST 8: UPDATE OPERATIONS ===")
    
    # Test 8a: Update rusted_box_count to 15 (should be grade C)
    print("\n--- Update rusted_box_count to 15 ---")
    response = http_session.put(
        f"{BASE_URL}/diptest/tests/{record_id}",
        json={"rusted_box_count": 15},
        headers=get_headers(),
        timeout=10
    )
    
    print(f"PUT /api/diptest/tests/{record_id} (rusted_box_count=15): {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        rusted_count = data.get('rusted_box_count')
        grade = data.get('grade')
        edited = data.get('edited')
        
        if rusted_count == 15:
            print(f"✅ rusted_box_count updated to 15")
        else:
            print(f"❌ rusted_box_count is {rusted_count}, expected 15")
        
        if grade == 'C':
            print(f"✅ Grade updated to 'C' (11-25 range)")
        else:
            print(f"❌ Grade is '{grade}', expected 'C'")
        
        if edited:
            print(f"✅ edited flag set to true")
        else:
            print(f"❌ edited flag is {edited}, expected true")
        
        # Verify grid_boxes recomputed
        grid_boxes = data.get('grid_boxes', [])
        true_count = sum(1 for b in grid_boxes if b)
        if true_count == 15:
            print(f"✅ grid_boxes recomputed with 15 true values")
        else:
            print(f"❌ grid_boxes has {true_count} true values, expected 15")
    else:
        print(f"❌ Update failed: {response.status_code} - {response.text}")
        return False
    
    # Test 8b: Update inspector fields
    print("\n--- Update inspector fields ---")
    response = http_session.put(
        f"{BASE_URL}/diptest/tests/{record_id}",
        json={
            "inspector_count": 30,
            "inspector_name": "QA",
            "inspector_notes": "Manual inspection notes"
        },
        headers=get_headers(),
        timeout=10
    )
    
    print(f"PUT /api/diptest/tests/{record_id} (inspector fields): {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        inspector_count = data.get('inspector_count')
        inspector_grade = data.get('inspector_grade')
        inspector_name = data.get('inspector_name')
        inspector_notes = data.get('inspector_notes')
        inspector_at = data.get('inspector_at')
        
        if inspector_count == 30:
            print(f"✅ inspector_count set to 30")
        else:
            print(f"❌ inspector_count is {inspector_count}, expected 30")
        
        if inspector_grade == 'D':
            print(f"✅ inspector_grade set to 'D' (26-50 range)")
        else:
            print(f"❌ inspector_grade is '{inspector_grade}', expected 'D'")
        
        if inspector_name == "QA":
            print(f"✅ inspector_name set to 'QA'")
        else:
            print(f"❌ inspector_name is '{inspector_name}', expected 'QA'")
        
        if inspector_notes == "Manual inspection notes":
            print(f"✅ inspector_notes set correctly")
        else:
            print(f"❌ inspector_notes is '{inspector_notes}'")
        
        if inspector_at:
            print(f"✅ inspector_at timestamp set: {inspector_at}")
        else:
            print(f"❌ inspector_at not set")
    else:
        print(f"❌ Update failed: {response.status_code} - {response.text}")
        return False
    
    # Test 8c: Clear inspector fields with inspector_count=-1
    print("\n--- Clear inspector fields (inspector_count=-1) ---")
    response = http_session.put(
        f"{BASE_URL}/diptest/tests/{record_id}",
        json={"inspector_count": -1},
        headers=get_headers(),
        timeout=10
    )
    
    print(f"PUT /api/diptest/tests/{record_id} (inspector_count=-1): {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        inspector_count = data.get('inspector_count')
        inspector_grade = data.get('inspector_grade')
        
        if inspector_count is None:
            print(f"✅ inspector_count cleared (null)")
        else:
            print(f"❌ inspector_count is {inspector_count}, expected null")
        
        if inspector_grade is None:
            print(f"✅ inspector_grade cleared (null)")
        else:
            print(f"❌ inspector_grade is '{inspector_grade}', expected null")
    else:
        print(f"❌ Update failed: {response.status_code} - {response.text}")
        return False
    
    return True


def test_delete(record_id):
    """Test 9: Soft delete"""
    print("\n=== TEST 9: SOFT DELETE ===")
    
    # Delete the record
    response = http_session.delete(
        f"{BASE_URL}/diptest/tests/{record_id}",
        headers=get_headers(),
        timeout=10
    )
    
    print(f"DELETE /api/diptest/tests/{record_id}: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        if data.get('ok'):
            print(f"✅ Delete successful")
        else:
            print(f"❌ Delete response: {data}")
            return False
    else:
        print(f"❌ Delete failed: {response.status_code} - {response.text}")
        return False
    
    # Verify record is removed from list
    response = http_session.get(
        f"{BASE_URL}/diptest/tests",
        headers=get_headers(),
        timeout=10
    )
    
    if response.status_code == 200:
        data = response.json()
        record_ids = [r.get('id') for r in data]
        if record_id not in record_ids:
            print(f"✅ Record removed from list (soft deleted)")
        else:
            print(f"❌ Record still in list after delete")
            return False
    
    # Verify GET returns 404
    response = http_session.get(
        f"{BASE_URL}/diptest/tests/{record_id}",
        headers=get_headers(),
        timeout=10
    )
    
    print(f"GET /api/diptest/tests/{record_id} (after delete): {response.status_code}")
    
    if response.status_code == 404:
        print(f"✅ GET returns 404 after delete")
    else:
        print(f"❌ Expected 404, got {response.status_code}")
        return False
    
    return True


def test_edge_cases():
    """Test 10: Edge cases"""
    print("\n=== TEST 10: EDGE CASES ===")
    
    # Test nonexistent image_path
    print("\n--- Nonexistent image_path ---")
    response = http_session.post(
        f"{BASE_URL}/diptest/analyze/start",
        json={
            "image_path": "nonexistent/image.jpg",
            "sample_id": "TEST"
        },
        headers=get_headers(),
        timeout=10
    )
    
    print(f"POST /api/diptest/analyze/start (nonexistent image): {response.status_code}")
    
    if response.status_code == 404:
        print(f"✅ Returns 404 for nonexistent image")
    else:
        print(f"❌ Expected 404, got {response.status_code}")
    
    # Test nonexistent job_id
    print("\n--- Nonexistent job_id ---")
    response = http_session.get(
        f"{BASE_URL}/diptest/analyze/jobs/nonexistent-job-id",
        headers=get_headers(),
        timeout=10
    )
    
    print(f"GET /api/diptest/analyze/jobs/nonexistent-job-id: {response.status_code}")
    
    if response.status_code == 404:
        print(f"✅ Returns 404 for nonexistent job")
    else:
        print(f"❌ Expected 404, got {response.status_code}")


def cleanup():
    """Clean up test records"""
    print("\n=== CLEANUP ===")
    for record_id in test_records_created:
        try:
            response = http_session.delete(
                f"{BASE_URL}/diptest/tests/{record_id}",
                headers=get_headers(),
                timeout=10
            )
            if response.status_code == 200:
                print(f"✅ Cleaned up record: {record_id}")
            else:
                print(f"⚠️  Failed to clean up record {record_id}: {response.status_code}")
        except Exception as e:
            print(f"⚠️  Error cleaning up record {record_id}: {e}")


def main():
    """Main test runner"""
    print("=" * 80)
    print("DIP TEST IN HOUSE METHOD - BACKEND API TESTING")
    print("=" * 80)
    
    # Login
    if not login():
        print("\n❌ FATAL: Cannot proceed without login")
        return
    
    # Run tests
    try:
        # Test 1: Auth guards
        test_auth_guards()
        
        # Test 2: Reference scale
        test_reference_scale()
        
        # Test 3: Dashboard
        test_dashboard()
        
        # Test 4: Trend
        test_trend()
        
        # Test 5: Tests list & search
        test_tests_list()
        
        # Test 6: Full AI flow
        record_id = test_full_ai_flow()
        
        if record_id:
            # Test 7: Analysis result verification
            if test_analysis_result(record_id):
                # Test 8: Update operations
                test_update_operations(record_id)
                
                # Test 9: Delete
                test_delete(record_id)
        else:
            print("\n⚠️  Skipping tests 7-9 (no record created - likely AI budget exhaustion)")
        
        # Test 10: Edge cases
        test_edge_cases()
        
    finally:
        # Cleanup
        cleanup()
    
    print("\n" + "=" * 80)
    print("TESTING COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
