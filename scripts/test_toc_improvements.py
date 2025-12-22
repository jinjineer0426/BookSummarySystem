#!/usr/bin/env python3
"""
Test the improved TOC extraction by triggering reprocessing for problem books.
Monitors the job progress and reports results.
"""
import os
import json
import time
import urllib.request
import urllib.error

# Production Cloud Run URL
FUNCTION_URL = "https://process-book-1037870388124.asia-northeast1.run.app"

# Problem books from the analysis
TEST_CASES = [
    {
        "name": "菅原洋平_仕事ができる人の脳にいい24時間の使い方",
        "file_id": "1ZvxFLgTwglOV8tys85tdK0Am158OzKtd",
        "category": "Humanities/Business",
        "expected_chapters": 6,  # Actually has 6 chapters, not 57
        "issue": "57 chapters detected (should be 6)"
    },
    {
        "name": "アストリッド・フェルメール, ベン・ウェンティング_自主経営組織のはじめ方",
        "file_id": "1kklEM1QJeSX3e31ZkpmeHqhg6LX2csWb",
        "category": "Humanities/Business",
        "expected_chapters": 10,  # Estimate based on book structure
        "issue": "OCR artifacts in chapter titles"
    }
]

def trigger_processing(test_case: dict) -> str:
    """Trigger processing and return job_id."""
    print(f"\n{'='*60}")
    print(f"📚 Testing: {test_case['name']}")
    print(f"   Issue: {test_case['issue']}")
    print(f"   Expected chapters: ~{test_case['expected_chapters']}")
    print(f"{'='*60}")
    
    payload = {
        "file_id": test_case["file_id"],
        "category": test_case["category"]
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        FUNCTION_URL, 
        data=data, 
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            job_id = result.get('job_id')
            print(f"✅ Job submitted: {job_id}")
            return job_id
            
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error {e.code}: {e.read().decode('utf-8')}")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def check_job_status(job_id: str) -> dict:
    """Check job status from GCS metadata (requires gsutil)."""
    import subprocess
    
    try:
        result = subprocess.run(
            ["gsutil", "cat", f"gs://my-book-summary-config/jobs/{job_id}/metadata.json"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {"status": "unknown", "error": result.stderr}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def check_toc_errors(job_id: str) -> dict:
    """Check TOC extraction errors from GCS."""
    import subprocess
    
    try:
        result = subprocess.run(
            ["gsutil", "cat", f"gs://my-book-summary-config/jobs/{job_id}/errors.json"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {}
    except:
        return {}

def run_test(test_case: dict):
    """Run test for a single book."""
    # Trigger processing
    job_id = trigger_processing(test_case)
    if not job_id:
        return {"success": False, "error": "Failed to submit job"}
    
    # Wait for processing to complete (or timeout)
    print(f"\n⏳ Waiting for processing... (checking every 30s)")
    max_wait = 600  # 10 minutes
    elapsed = 0
    
    while elapsed < max_wait:
        time.sleep(30)
        elapsed += 30
        
        status = check_job_status(job_id)
        current_status = status.get("status", "unknown")
        total_chapters = status.get("total_chapters", "?")
        completed = len(status.get("completed_chapters", []))
        
        print(f"   [{elapsed//60}m{elapsed%60}s] Status: {current_status}, "
              f"Chapters: {completed}/{total_chapters}")
        
        if current_status in ["complete", "failed"]:
            break
    
    # Report results
    final_status = check_job_status(job_id)
    errors = check_toc_errors(job_id)
    
    result = {
        "job_id": job_id,
        "book": test_case["name"],
        "expected_chapters": test_case["expected_chapters"],
        "actual_chapters": final_status.get("total_chapters"),
        "status": final_status.get("status"),
        "toc_method": "vision" if not errors.get("toc_extraction") else "regex_fallback",
        "errors": errors
    }
    
    # Evaluate success
    actual = result["actual_chapters"]
    expected = test_case["expected_chapters"]
    
    if actual and expected:
        if actual <= expected * 2 and actual >= expected * 0.5:
            print(f"\n✅ PASS: {actual} chapters detected (expected ~{expected})")
            result["success"] = True
        else:
            print(f"\n❌ FAIL: {actual} chapters detected (expected ~{expected})")
            result["success"] = False
    else:
        print(f"\n⚠️ UNABLE TO VERIFY: actual={actual}")
        result["success"] = None
    
    return result

def main():
    print("🧪 TOC Extraction Improvement Test")
    print(f"   Target: {FUNCTION_URL}")
    print(f"   Tests: {len(TEST_CASES)} books")
    
    results = []
    
    # Run the second test case (自主経営組織のはじめ方)
    for i, test_case in enumerate(TEST_CASES[1:2]):  
        result = run_test(test_case)
        results.append(result)
        
        # Save progress
        with open("/tmp/toc_test_results_v2.json", "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    
    # Summary
    print("\n" + "="*60)
    print("📊 Test Summary")
    print("="*60)
    
    for r in results:
        status_icon = "✅" if r.get("success") else "❌" if r.get("success") is False else "⚠️"
        print(f"{status_icon} {r['book'][:30]}... | "
              f"Chapters: {r.get('actual_chapters')} (expected {r.get('expected_chapters')}) | "
              f"Method: {r.get('toc_method')}")
    
    print("\nResults saved to: /tmp/toc_test_results.json")

if __name__ == "__main__":
    main()
