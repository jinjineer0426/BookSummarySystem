"""
Structured Logging Service - Cloud Logging integration.

This service provides structured logging capabilities for better monitoring
and debugging in production. Logs are sent to Google Cloud Logging with
structured metadata for easy filtering and analysis.
"""
import sys
from datetime import datetime
from typing import Optional, Any, Dict
from google.cloud import logging as cloud_logging


class StructuredLogger:
    """Provides structured logging for Cloud Logging integration."""
    
    def __init__(self, job_id: Optional[str] = None, enable_console: bool = True):
        """
        Initialize the structured logger.
        
        Args:
            job_id: Optional job ID to include in all log entries
            enable_console: If True, also prints to console (default: True)
        """
        self.job_id = job_id
        self.enable_console = enable_console
        
        # Initialize Cloud Logging client
        try:
            self.client = cloud_logging.Client()
            self.logger = self.client.logger("book-summary-system")
            self.cloud_logging_enabled = True
        except Exception as e:
            print(f"Warning: Cloud Logging initialization failed: {e}. Using console only.", file=sys.stderr)
            self.cloud_logging_enabled = False
    
    def info(self, message: str, **kwargs):
        """Log info-level message."""
        self._log("INFO", message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning-level message."""
        self._log("WARNING", message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error-level message."""
        self._log("ERROR", message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        """Log debug-level message."""
        self._log("DEBUG", message, **kwargs)
    
    def _log(self, severity: str, message: str, **kwargs):
        """
        Internal logging method that sends to both Cloud Logging and console.
        
        Args:
            severity: Log severity (INFO, WARNING, ERROR, DEBUG)
            message: Log message
            **kwargs: Additional structured data to include
        """
        # Build structured log entry
        struct = {
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
            **kwargs
        }
        
        # Add job_id if available
        if self.job_id:
            struct["job_id"] = self.job_id
        
        # Send to Cloud Logging
        if self.cloud_logging_enabled:
            try:
                self.logger.log_struct(struct, severity=severity)
            except Exception as e:
                print(f"Cloud Logging error: {e}", file=sys.stderr)
        
        # Also print to console for local debugging and Cloud Run logs
        if self.enable_console:
            console_msg = f"[{severity}] {message}"
            if self.job_id:
                console_msg = f"[{self.job_id}] {console_msg}"
            
            # Add structured data to console output
            if kwargs:
                import json
                console_msg += f" | {json.dumps(kwargs)}"
            
            print(console_msg, file=sys.stderr if severity == "ERROR" else sys.stdout)


class JobLogger:
    """Convenience wrapper for job-specific logging."""
    
    def __init__(self, job_id: str):
        """
        Initialize job logger.
        
        Args:
            job_id: Job ID for all log entries
        """
        self.logger = StructuredLogger(job_id=job_id)
        self.job_id = job_id
    
    def info(self, message: str, **kwargs):
        """Log info-level message (delegated to internal StructuredLogger)."""
        self.logger.info(message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning-level message (delegated to internal StructuredLogger)."""
        self.logger.warning(message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error-level message (delegated to internal StructuredLogger)."""
        self.logger.error(message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        """Log debug-level message (delegated to internal StructuredLogger)."""
        self.logger.debug(message, **kwargs)
    
    def log_stage(self, stage: str, status: str, **kwargs):
        """
        Log a processing stage.
        
        Args:
            stage: Stage name (e.g., 'toc_extraction', 'chapter_processing')
            status: Status (e.g., 'started', 'completed', 'failed')
            **kwargs: Additional context
        """
        self.logger.info(
            f"Stage: {stage} - {status}",
            stage=stage,
            status=status,
            **kwargs
        )
    
    def log_error(self, stage: str, error: str, **kwargs):
        """
        Log an error.
        
        Args:
            stage: Stage where error occurred
            error: Error message
            **kwargs: Additional context
        """
        self.logger.error(
            f"Error in {stage}: {error}",
            stage=stage,
            error=error,
            **kwargs
        )
    
    def log_metric(self, metric_name: str, value: Any, **kwargs):
        """
        Log a metric value.
        
        Args:
            metric_name: Name of the metric
            value: Metric value
            **kwargs: Additional context
        """
        self.logger.info(
            f"Metric: {metric_name}={value}",
            metric=metric_name,
            value=value,
            **kwargs
        )
# Global logger instance for shared services
_global_logger = StructuredLogger()

def set_global_job_id(job_id: str):
    """Set the job ID for the global logger."""
    _global_logger.job_id = job_id

def get_logger() -> StructuredLogger:
    """Get the global structured logger."""
    return _global_logger
