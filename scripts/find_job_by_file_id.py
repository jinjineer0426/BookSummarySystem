
import os
import json
from google.cloud import storage

def find_job(bucket_name, target_file_id):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    
    print(f"Searching in bucket: {bucket_name}")
    
    # List all blobs in jobs/ directory
    blobs = bucket.list_blobs(prefix="jobs/")
    
    for blob in blobs:
        if blob.name.endswith("metadata.json"):
            try:
                content = blob.download_as_text()
                metadata = json.loads(content)
                
                if metadata.get("file_id") == target_file_id:
                    print(f"FOUND MATCH!")
                    print(f"Job ID: {metadata.get('job_id')}")
                    print(f"Created At: {metadata.get('created_at')}")
                    print(f"Status: {metadata.get('status')}")
                    return metadata.get('job_id')
            except Exception as e:
                print(f"Error reading {blob.name}: {e}")
                
    print("No matching job found.")
    return None

if __name__ == "__main__":
    bucket_name = "my-book-summary-config"
    target_file_id = "1CKLj8jztwQTc4Tmr-J_mIr-c5Oq944MS"
    find_job(bucket_name, target_file_id)
