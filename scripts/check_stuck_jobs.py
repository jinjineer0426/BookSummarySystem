
import json
import os
from google.cloud import storage
from datetime import datetime

BUCKET_NAME = "my-book-summary-config"

def check_stuck_jobs():
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    
    print(f"Checking jobs in {BUCKET_NAME}...")
    
    # List all job directories
    blobs = list(bucket.list_blobs(prefix="jobs/"))
    
    job_data = {}
    
    for blob in blobs:
        # Expected format: jobs/<job_id>/<filename>
        parts = blob.name.split('/')
        if len(parts) < 3:
            continue
            
        job_id = parts[1]
        filename = parts[2]
        
        if job_id not in job_data:
            job_data[job_id] = {"metadata": None, "has_error": False}
            
        if filename == "metadata.json":
            try:
                content = blob.download_as_text()
                job_data[job_id]["metadata"] = json.loads(content)
            except Exception as e:
                print(f"Error reading metadata for {job_id}: {e}")
        elif filename == "errors.json":
            job_data[job_id]["has_error"] = True

    print("\n--- Incomplete Jobs Report ---")
    stuck_jobs = []
    
    for job_id, data in job_data.items():
        meta = data["metadata"]
        if not meta:
            continue
            
        status = meta.get("status")
        # Filter for processing or undefined status
        if status != "complete":
            created_at = meta.get("created_at", "Unknown")
            title = meta.get("book_title", "Unknown")
            total = meta.get("total_chapters", 0)
            completed = len(meta.get("completed_chapters", []))
            
            print(f"Job ID: {job_id}")
            print(f"  Title: {title}")
            print(f"  Status: {status}")
            print(f"  Progress: {completed}/{total}")
            print(f"  Created: {created_at}")
            print(f"  Has Errors: {data['has_error']}")
            print("-" * 30)
            
            stuck_jobs.append(job_id)

    return stuck_jobs

if __name__ == "__main__":
    check_stuck_jobs()
