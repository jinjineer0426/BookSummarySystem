"""
Job Tracking Service - Monitors job status in GCS.

This service tracks job state through the entire processing pipeline,
making it easy to monitor progress and identify stuck or failed jobs.
"""
import json
from datetime import datetime
from typing import Optional, Dict, Any
from google.cloud import storage


class JobTracker:
    """Tracks job status in GCS for monitoring."""
    
    def __init__(self, gcs_service, job_id: str):
        """
        Initialize job tracker.
        
        Args:
            gcs_service: GcsService instance
            job_id: Job ID to track
        """
        self.gcs = gcs_service
        self.job_id = job_id
        self.status_path = f"jobs/{job_id}/status.json"
    
    def update_status(self, status: str, details: Optional[Dict[str, Any]] = None):
        """
        Updates job status in GCS.
        
        Args:
            status: Job status ('queued', 'processing', 'completed', 'failed')
            details: Optional additional details
        """
        data = {
            "job_id": self.job_id,
            "status": status,
            "updated_at": datetime.utcnow().isoformat(),
            "details": details or {}
        }
        
        try:
            self.gcs.bucket.blob(self.status_path).upload_from_string(
                json.dumps(data, ensure_ascii=False, indent=2),
                content_type="application/json"
            )
            print(f"Job {self.job_id} status updated: {status}")
        except Exception as e:
            print(f"Warning: Failed to update job status: {e}")
    
    def mark_queued(self, total_chapters: int):
        """Mark job as queued."""
        self.update_status("queued", {"total_chapters": total_chapters})
    
    def mark_processing(self, current_chapter: int, total_chapters: int):
        """Mark job as processing."""
        self.update_status("processing", {
            "current_chapter": current_chapter,
            "total_chapters": total_chapters,
            "progress": f"{current_chapter}/{total_chapters}"
        })
    
    def mark_completed(self, gcs_uri: str):
        """Mark job as completed."""
        self.update_status("completed", {"gcs_uri": gcs_uri})
    
    def mark_failed(self, error: str, stage: Optional[str] = None):
        """
        Mark job as failed and prepare for alert notification.
        
        Args:
            error: Error message
            stage: Optional stage where failure occurred
        """
        details = {"error": error}
        if stage:
            details["stage"] = stage
        
        self.update_status("failed", details)
    
    def get_status(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve current job status.
        
        Returns:
            Status dictionary or None if not found
        """
        try:
            blob = self.gcs.bucket.blob(self.status_path)
            if blob.exists():
                content = blob.download_as_text()
                return json.loads(content)
            return None
        except Exception as e:
            print(f"Warning: Failed to retrieve job status: {e}")
            return None
