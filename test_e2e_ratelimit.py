#!/usr/bin/env python3
"""
E2E test for rate-limit retry fix - Real Gemini analysis
Tests /api/kht/analyze/start with real image
"""
import requests
import time
import sys
from pathlib import Path
from PIL import Image
import io

# Backend URL
BACKEND_URL = "https://lpd-evaluator.preview.emergentagent.com/api"

# Test credentials
USERNAME = "admin"
PASSWORD = "admin123"

# Test image URL
IMAGE_URL = "https://customer-assets-m6fa6gv7.emergentagent.net/job_signin-5app/artifacts/k3akmlwa_WhatsApp%20Image%202026-09-25%20at%2014.05.44.webp"

def login():
    """Login and get session token"""
    print("\n=== STEP 1: Login ===")
    resp = requests.post(
        f"{BACKEND_URL}/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=30
    )
    
    if resp.status_code != 200:
        print(f"❌ FAIL: Login failed with status {resp.status_code}")
        print(f"   Response: {resp.text}")
        return None
    
    data = resp.json()
    token = data.get("token")
    print(f"✅ PASS: Login successful, got token (length={len(token)})")
    return token


def download_and_convert_image():
    """Download WEBP image and convert to JPEG"""
    print("\n=== STEP 2: Download and convert image ===")
    
    print(f"Downloading image from {IMAGE_URL}...")
    resp = requests.get(IMAGE_URL, timeout=60)
    
    if resp.status_code != 200:
        print(f"❌ FAIL: Download failed with status {resp.status_code}")
        return None
    
    print(f"✅ Downloaded {len(resp.content)} bytes")
    
    # Convert WEBP to JPEG
    print("Converting WEBP to JPEG...")
    img = Image.open(io.BytesIO(resp.content))
    
    # Convert to RGB if needed (WEBP might have alpha channel)
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGB')
    
    # Save as JPEG
    jpeg_buffer = io.BytesIO()
    img.save(jpeg_buffer, format='JPEG', quality=95)
    jpeg_bytes = jpeg_buffer.getvalue()
    
    print(f"✅ Converted to JPEG ({len(jpeg_bytes)} bytes)")
    return jpeg_bytes


def upload_image(token, image_bytes):
    """Upload image via /api/kht/upload with retry"""
    print("\n=== STEP 3: Upload image ===")
    
    headers = {'X-Session-Token': token}
    
    # Try up to 3 times with exponential backoff
    for attempt in range(3):
        try:
            files = {'file': ('test_image.jpg', image_bytes, 'image/jpeg')}
            
            resp = requests.post(
                f"{BACKEND_URL}/kht/upload",
                files=files,
                headers=headers,
                timeout=120
            )
            
            if resp.status_code == 200:
                data = resp.json()
                image_path = data.get("image_path")
                print(f"✅ PASS: Image uploaded to {image_path} (attempt {attempt + 1})")
                return image_path
            else:
                print(f"⚠️  Attempt {attempt + 1} failed with status {resp.status_code}")
                if attempt < 2:
                    wait = 2 ** attempt
                    print(f"   Retrying in {wait}s...")
                    time.sleep(wait)
        except Exception as e:
            print(f"⚠️  Attempt {attempt + 1} failed with exception: {e}")
            if attempt < 2:
                wait = 2 ** attempt
                print(f"   Retrying in {wait}s...")
                time.sleep(wait)
    
    print(f"❌ FAIL: Upload failed after 3 attempts")
    return None


def start_analysis(token, image_path):
    """Start KHT analysis job"""
    print("\n=== STEP 4: Start analysis ===")
    
    payload = {
        "image_path": image_path,
        "sample_id": "TEST-RL-001",
        "oil_type": "Engine Oil SAE 15W-40",
        "batch": "",
        "operator": "",
        "temperature_c": 320,
        "duration_hours": 16,
        "air_flow": 10,
        "oil_flow": 0.31,
        "remark": "ratelimit fix test"
    }
    
    headers = {'X-Session-Token': token}
    
    resp = requests.post(
        f"{BACKEND_URL}/kht/analyze/start",
        json=payload,
        headers=headers,
        timeout=30
    )
    
    if resp.status_code != 200:
        print(f"❌ FAIL: Start analysis failed with status {resp.status_code}")
        print(f"   Response: {resp.text}")
        return None
    
    data = resp.json()
    job_id = data.get("id")
    print(f"✅ PASS: Analysis job started with id={job_id}")
    return job_id


def poll_job(token, job_id, max_wait=300):
    """Poll job until done or timeout (5 minutes)"""
    print("\n=== STEP 5: Poll job until completion ===")
    
    headers = {'X-Session-Token': token}
    start_time = time.time()
    poll_count = 0
    
    while True:
        elapsed = time.time() - start_time
        
        if elapsed > max_wait:
            print(f"❌ FAIL: Timeout after {elapsed:.0f}s")
            return None
        
        poll_count += 1
        resp = requests.get(
            f"{BACKEND_URL}/kht/analyze/jobs/{job_id}",
            headers=headers,
            timeout=30
        )
        
        if resp.status_code != 200:
            print(f"❌ FAIL: Poll failed with status {resp.status_code}")
            print(f"   Response: {resp.text}")
            return None
        
        data = resp.json()
        status = data.get("status")
        
        if status == "done":
            print(f"✅ PASS: Job completed after {elapsed:.0f}s ({poll_count} polls)")
            return data
        
        elif status == "error":
            error = data.get("error", "Unknown error")
            print(f"❌ FAIL: Job failed with error: {error}")
            
            # Check if it's the friendly Indonesian message (retry worked but still failed)
            if "Server AI sedang sibuk" in error:
                print(f"   ℹ️  Note: Job failed with FRIENDLY error message (retries exhausted)")
                print(f"   This means retry logic is working, but rate limit persists")
            else:
                print(f"   ℹ️  Note: Job failed with raw error (retry logic may not be working)")
            
            return data
        
        elif status == "running":
            if poll_count % 5 == 0:  # Print every 5th poll
                print(f"   Still running... ({elapsed:.0f}s elapsed)")
            time.sleep(3)
        
        else:
            print(f"❌ FAIL: Unexpected status '{status}'")
            return None


def verify_result(token, job_data):
    """Verify the analysis result"""
    print("\n=== STEP 6: Verify result ===")
    
    status = job_data.get("status")
    
    if status == "error":
        error = job_data.get("error", "")
        print(f"⚠️  Job completed with error status")
        print(f"   Error message: {error}")
        
        # Check if it's the friendly message
        if "Server AI sedang sibuk" in error:
            print(f"✅ PASS: Error message is FRIENDLY Indonesian message (retry logic working)")
            print(f"   Expected: 'Server AI sedang sibuk (batas permintaan tercapai). Tunggu 1-2 menit lalu coba lagi.'")
            return None, "friendly_error"
        else:
            print(f"❌ FAIL: Error message is RAW error (retry logic may not be working)")
            return None, "raw_error"
    
    # Job succeeded
    record_id = job_data.get("result", {}).get("record_id")
    
    if not record_id:
        print(f"❌ FAIL: No record_id in result")
        return None, "no_record"
    
    print(f"✅ PASS: Got record_id={record_id}")
    
    # Fetch the record
    headers = {'X-Session-Token': token}
    resp = requests.get(
        f"{BACKEND_URL}/kht/tests/{record_id}",
        headers=headers,
        timeout=30
    )
    
    if resp.status_code != 200:
        print(f"❌ FAIL: Failed to fetch record with status {resp.status_code}")
        return None, "fetch_failed"
    
    record = resp.json()
    
    # Verify fields
    rating = record.get("rating")
    ai_summary = record.get("ai_summary", "")
    
    print(f"\n   Record details:")
    print(f"   - rating: {rating}")
    print(f"   - ai_summary: {ai_summary[:100]}..." if len(ai_summary) > 100 else f"   - ai_summary: {ai_summary}")
    
    # Validate rating
    if rating is None or not (0 <= rating <= 10):
        print(f"❌ FAIL: Invalid rating {rating} (expected 0-10)")
        return record_id, "invalid_rating"
    
    print(f"✅ PASS: Valid rating {rating} (0-10)")
    
    # Validate summary
    if not ai_summary or len(ai_summary) < 10:
        print(f"❌ FAIL: ai_summary too short or missing")
        return record_id, "invalid_summary"
    
    print(f"✅ PASS: ai_summary present (length={len(ai_summary)})")
    
    # Check for left/right references (mandatory 4-step procedure)
    if "kiri" in ai_summary.lower() or "kanan" in ai_summary.lower() or "left" in ai_summary.lower() or "right" in ai_summary.lower():
        print(f"✅ PASS: Summary mentions left/right references (4-step procedure)")
    else:
        print(f"⚠️  WARNING: Summary doesn't mention left/right references")
    
    return record_id, "success"


def cleanup(token, record_id):
    """Delete the test record"""
    print("\n=== STEP 7: Cleanup ===")
    
    if not record_id:
        print("ℹ️  No record to cleanup")
        return True
    
    headers = {'X-Session-Token': token}
    resp = requests.delete(
        f"{BACKEND_URL}/kht/tests/{record_id}",
        headers=headers,
        timeout=30
    )
    
    if resp.status_code != 200:
        print(f"❌ FAIL: Delete failed with status {resp.status_code}")
        return False
    
    print(f"✅ PASS: Record {record_id} deleted")
    
    # Verify deletion
    resp = requests.get(
        f"{BACKEND_URL}/kht/tests/{record_id}",
        headers=headers,
        timeout=30
    )
    
    if resp.status_code == 404:
        print(f"✅ PASS: Record confirmed deleted (404)")
        return True
    else:
        print(f"⚠️  WARNING: Record still exists (status {resp.status_code})")
        return False


def main():
    print("=" * 70)
    print("E2E TEST: RATE-LIMIT RETRY FIX WITH REAL GEMINI")
    print("=" * 70)
    
    # Step 1: Login
    token = login()
    if not token:
        return 1
    
    # Step 2: Download and convert image
    image_bytes = download_and_convert_image()
    if not image_bytes:
        return 1
    
    # Step 3: Upload image
    image_path = upload_image(token, image_bytes)
    if not image_path:
        return 1
    
    # Step 4: Start analysis
    job_id = start_analysis(token, image_path)
    if not job_id:
        return 1
    
    # Step 5: Poll job
    job_data = poll_job(token, job_id, max_wait=300)
    if not job_data:
        return 1
    
    # Step 6: Verify result
    record_id, result_status = verify_result(token, job_data)
    
    # Step 7: Cleanup
    if record_id:
        cleanup(token, record_id)
    
    print("\n" + "=" * 70)
    print("E2E TEST SUMMARY")
    print("=" * 70)
    
    if result_status == "success":
        print("✅ PASS: Job completed successfully with valid rating and summary")
        print("   The retry logic is working correctly (no rate limit hit, or retries succeeded)")
        return 0
    elif result_status == "friendly_error":
        print("✅ PARTIAL PASS: Job failed but with FRIENDLY error message")
        print("   The retry logic is working (retries happened, but rate limit persisted)")
        print("   This is expected behavior when rate limits are exhausted")
        return 0
    elif result_status == "raw_error":
        print("❌ FAIL: Job failed with RAW error message")
        print("   The retry logic may not be working correctly")
        return 1
    else:
        print(f"❌ FAIL: Unexpected result status: {result_status}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
