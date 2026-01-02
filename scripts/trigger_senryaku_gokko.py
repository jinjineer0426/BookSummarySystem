import os
import json
import urllib.request
import urllib.error

# Config
FUNCTION_URL = "https://process-book-1037870388124.asia-northeast1.run.app"

TARGET_FILE_ID = "1CKLj8jztwQTc4Tmr-J_mIr-c5Oq944MS" # 戦略ごっこ マーケティング以前の問題
CATEGORY = "Humanities/Business"

def trigger_processing():
    print(f"Triggering processing for File ID: {TARGET_FILE_ID}...")
    print(f"Target URL: {FUNCTION_URL}")
    
    payload = {
        "file_id": TARGET_FILE_ID,
        "category": CATEGORY
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        FUNCTION_URL, 
        data=data, 
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            print("\nSuccess! Response:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            print(f"\nJob ID: {result.get('job_id')}")
            print("Check Cloud Tasks console or GCS logs for progress.")
            
    except urllib.error.HTTPError as e:
        print(f"\nError: HTTP {e.code}")
        print(e.read().decode('utf-8'))
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    trigger_processing()
