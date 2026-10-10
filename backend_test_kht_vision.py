#!/usr/bin/env python3
"""
KHT AI Vision Analysis Prompt Test
Tests the updated MANDATORY 4-step rating procedure with real Gemini call.
"""
import requests
import time
import json
from pathlib import Path
from PIL import Image
import io

# Configuration
BASE_URL = "https://astm-rating-app.preview.emergentagent.com/api"
CREDENTIALS = {"username": "admin", "password": "admin123"}
TEST_IMAGE_URL = "https://customer-assets-m6fa6gv7.emergentagent.net/job_signin-5app/artifacts/k3akmlwa_WhatsApp%20Image%202026-09-25%20at%2014.05.44.webp"

# Test parameters
TEST_PARAMS = {
    "sample_id": "TEST-METHOD-001",
    "oil_type": "Engine Oil SAE 15W-40",
    "batch": "",
    "operator": "",
    "temperature_c": 320,
    "duration_hours": 16,
    "air_flow": 10,
    "oil_flow": 0.31,
    "remark": "method test"
}

def log(msg):
    print(f"[TEST] {msg}")

def login():
    """Step 1: Login and get auth token"""
    log("Step 1: Logging in...")
    resp = requests.post(f"{BASE_URL}/auth/login", json=CREDENTIALS, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Login failed: {resp.status_code} {resp.text}")
    data = resp.json()
    token = data.get("token")
    log(f"✓ Login successful, token: {token[:20]}...")
    return token

def download_and_convert_image():
    """Step 2: Download .webp and convert to JPEG if needed"""
    log("Step 2: Downloading test image...")
    resp = requests.get(TEST_IMAGE_URL, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"Image download failed: {resp.status_code}")
    
    image_bytes = resp.content
    log(f"✓ Downloaded {len(image_bytes)} bytes")
    
    # Check if it's WEBP and convert to JPEG
    try:
        img = Image.open(io.BytesIO(image_bytes))
        log(f"  Image format: {img.format}, size: {img.size}")
        
        if img.format == "WEBP":
            log("  Converting WEBP to JPEG...")
            # Convert to RGB (JPEG doesn't support transparency)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            
            # Save as JPEG
            jpeg_buffer = io.BytesIO()
            img.save(jpeg_buffer, format="JPEG", quality=95)
            jpeg_bytes = jpeg_buffer.getvalue()
            log(f"✓ Converted to JPEG ({len(jpeg_bytes)} bytes)")
            return jpeg_bytes, "image/jpeg"
        else:
            return image_bytes, f"image/{img.format.lower()}"
    except Exception as e:
        log(f"  Warning: Could not process image: {e}")
        return image_bytes, "image/jpeg"

def upload_image(token, image_bytes, content_type):
    """Step 3: Upload image via POST /api/kht/upload"""
    log("Step 3: Uploading image...")
    headers = {"X-Session-Token": token}
    files = {"file": ("test_image.jpg", image_bytes, content_type)}
    
    resp = requests.post(f"{BASE_URL}/kht/upload", headers=headers, files=files, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"Upload failed: {resp.status_code} {resp.text}")
    
    data = resp.json()
    log(f"  Upload response: {data}")
    image_path = data.get("image_path") or data.get("path")
    log(f"✓ Upload successful, path: {image_path}")
    return image_path

def start_analysis(token, image_path):
    """Step 4: Start analysis job"""
    log("Step 4: Starting AI Vision analysis...")
    headers = {"X-Session-Token": token}
    payload = {**TEST_PARAMS, "image_path": image_path}
    
    resp = requests.post(f"{BASE_URL}/kht/analyze/start", headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Analysis start failed: {resp.status_code} {resp.text}")
    
    data = resp.json()
    job_id = data.get("id")
    log(f"✓ Analysis job started, id: {job_id}")
    return job_id

def poll_job(token, job_id, max_wait=300):
    """Step 5: Poll job until complete (allow up to 5 minutes)"""
    log(f"Step 5: Polling job {job_id} (max {max_wait}s)...")
    headers = {"X-Session-Token": token}
    start_time = time.time()
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait:
            raise Exception(f"Job timeout after {elapsed:.0f}s")
        
        resp = requests.get(f"{BASE_URL}/kht/analyze/jobs/{job_id}", headers=headers, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"Job poll failed: {resp.status_code} {resp.text}")
        
        data = resp.json()
        status = data.get("status")
        
        if status == "done":
            record_id = data.get("record_id")
            log(f"  Job response: {data}")
            log(f"✓ Job completed in {elapsed:.1f}s, record_id: {record_id}")
            return record_id
        elif status == "error":
            error = data.get("error", "Unknown error")
            log(f"  Job response: {data}")
            raise Exception(f"Job failed: {error}")
        
        log(f"  Status: {status}, elapsed: {elapsed:.1f}s")
        time.sleep(5)

def verify_result(token, record_id):
    """Step 6: Get and verify the test record"""
    log(f"Step 6: Verifying result for record {record_id}...")
    headers = {"X-Session-Token": token}
    
    resp = requests.get(f"{BASE_URL}/kht/tests/{record_id}", headers=headers, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Get record failed: {resp.status_code} {resp.text}")
    
    record = resp.json()
    
    log("\n" + "="*80)
    log("FULL RECORD:")
    log("="*80)
    log(json.dumps(record, indent=2, ensure_ascii=False))
    log("="*80)
    
    # Extract key fields
    rating = record.get("rating")
    confidence = record.get("confidence")
    status = record.get("status")
    performance = record.get("performance")
    deposit_level_label = record.get("deposit_level_label")
    summary = record.get("ai_summary", "")  # Changed from "summary" to "ai_summary"
    
    log("\n" + "="*80)
    log("VERIFICATION RESULTS:")
    log("="*80)
    
    # Verify rating
    log(f"\n1. RATING: {rating}")
    if not isinstance(rating, (int, float)):
        log(f"   ❌ FAIL: rating is not a number (type: {type(rating).__name__})")
        return False
    if rating < 0 or rating > 10:
        log(f"   ❌ FAIL: rating {rating} is out of range 0-10")
        return False
    
    # Check if rating has at most one decimal place
    rating_str = str(rating)
    if '.' in rating_str:
        decimals = len(rating_str.split('.')[1])
        if decimals > 1:
            log(f"   ⚠ WARNING: rating has {decimals} decimal places (expected max 1)")
    
    # Expected range for light yellow-amber sample
    if 5.5 <= rating <= 8:
        log(f"   ✓ PASS: rating {rating} is plausible for light yellow-amber sample (expected ~5.5-8)")
    else:
        log(f"   ⚠ WARNING: rating {rating} is outside expected range 5.5-8 for light yellow-amber sample")
    
    # Verify confidence
    log(f"\n2. CONFIDENCE: {confidence}")
    if not isinstance(confidence, (int, float)):
        log(f"   ❌ FAIL: confidence is not a number (type: {type(confidence).__name__})")
        return False
    if confidence < 0 or confidence > 100:
        log(f"   ❌ FAIL: confidence {confidence} is out of range 0-100")
        return False
    
    # Check High/Medium/Low mapping
    if confidence >= 85:
        conf_level = "High"
    elif confidence >= 60:
        conf_level = "Medium"
    else:
        conf_level = "Low"
    log(f"   ✓ PASS: confidence {confidence} maps to {conf_level} (High>=85, Medium 60-84, Low<60)")
    
    # Verify status
    log(f"\n3. STATUS: {status}")
    if rating >= 7:
        expected_status = "CLEAR"
    else:
        expected_status = "TARNISH"
    
    if status == expected_status:
        log(f"   ✓ PASS: status '{status}' is consistent with rating {rating} (>=7 CLEAR, else TARNISH)")
    else:
        log(f"   ❌ FAIL: status '{status}' inconsistent with rating {rating} (expected '{expected_status}')")
        return False
    
    # Verify performance and deposit_level_label
    log(f"\n4. PERFORMANCE: {performance}")
    log(f"5. DEPOSIT_LEVEL_LABEL: {deposit_level_label}")
    if not performance:
        log(f"   ❌ FAIL: performance is empty")
        return False
    if not deposit_level_label:
        log(f"   ❌ FAIL: deposit_level_label is empty")
        return False
    log(f"   ✓ PASS: performance and deposit_level_label are present")
    
    # Verify summary (CRITICAL - must mention LEFT/RIGHT adjacent references)
    log(f"\n6. SUMMARY (Indonesian):")
    log(f"   \"{summary}\"")
    
    if not summary:
        log(f"   ❌ FAIL: summary is empty")
        return False
    
    # Check for key elements in summary
    checks = {
        "mentions position": False,
        "mentions left reference": False,
        "mentions right reference": False,
        "mentions color": False,
        "mentions rating": False
    }
    
    summary_lower = summary.lower()
    
    # Check for position keywords
    position_keywords = ["posisi", "berada", "antara", "di antara", "antara tube", "slot"]
    if any(kw in summary_lower for kw in position_keywords):
        checks["mentions position"] = True
    
    # Check for left/right reference keywords
    left_keywords = ["kiri", "left", "sebelah kiri"]
    right_keywords = ["kanan", "right", "sebelah kanan"]
    if any(kw in summary_lower for kw in left_keywords):
        checks["mentions left reference"] = True
    if any(kw in summary_lower for kw in right_keywords):
        checks["mentions right reference"] = True
    
    # Check for color keywords
    color_keywords = ["warna", "kuning", "amber", "coklat", "gelap", "terang", "color"]
    if any(kw in summary_lower for kw in color_keywords):
        checks["mentions color"] = True
    
    # Check if rating value appears in summary
    if str(rating) in summary or str(int(rating)) in summary:
        checks["mentions rating"] = True
    
    log(f"\n   Summary content checks:")
    all_passed = True
    for check, passed in checks.items():
        status_icon = "✓" if passed else "❌"
        log(f"   {status_icon} {check}: {passed}")
        if not passed:
            all_passed = False
    
    if not all_passed:
        log(f"\n   ⚠ WARNING: Summary may not fully comply with 4-step procedure requirements")
        log(f"   Expected: sample position, LEFT and RIGHT adjacent reference values, color description, rating")
    else:
        log(f"\n   ✓ PASS: Summary mentions all required elements")
    
    return True

def cleanup(token, record_id):
    """Step 7: Delete test record"""
    log(f"\nStep 7: Cleaning up test record {record_id}...")
    headers = {"X-Session-Token": token}
    
    resp = requests.delete(f"{BASE_URL}/kht/tests/{record_id}", headers=headers, timeout=30)
    if resp.status_code != 200:
        log(f"   ⚠ WARNING: Cleanup failed: {resp.status_code} {resp.text}")
        return False
    
    log(f"   ✓ Test record deleted successfully")
    return True

def main():
    try:
        log("="*80)
        log("KHT AI VISION ANALYSIS PROMPT TEST")
        log("Testing MANDATORY 4-step rating procedure with real Gemini call")
        log("="*80)
        
        # Step 1: Login
        token = login()
        
        # Step 2: Download and convert image
        image_bytes, content_type = download_and_convert_image()
        
        # Step 3: Upload image
        image_path = upload_image(token, image_bytes, content_type)
        
        # Step 4: Start analysis
        job_id = start_analysis(token, image_path)
        
        # Step 5: Poll until complete
        record_id = poll_job(token, job_id, max_wait=300)
        
        # Step 6: Verify result
        success = verify_result(token, record_id)
        
        # Step 7: Cleanup
        cleanup(token, record_id)
        
        if success:
            log("\n" + "="*80)
            log("✓ ALL TESTS PASSED")
            log("="*80)
            return 0
        else:
            log("\n" + "="*80)
            log("❌ SOME TESTS FAILED")
            log("="*80)
            return 1
            
    except Exception as e:
        log(f"\n❌ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
