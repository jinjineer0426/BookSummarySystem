# Monitoring & Alerts Guide

## Overview

BookSummarySystem includes comprehensive monitoring and alerting capabilities through:
- **Structured Logging** to Google Cloud Logging
- **Job Status Tracking** in GCS
- **Email Alerts** for failures
- **Cloud Logging Queries** for debugging

## Structured Logging

### Log Levels

| Level | Use Case |
|:---|:---|
| **INFO** | Normal operations, stage completions |
| **WARNING** | Non-critical issues, fallback usage |
| **ERROR** | Failures, exceptions |
| **DEBUG** | Detailed debugging info |

### Log Structure

All logs include structured metadata:

```json
{
  "message": "Stage: toc_extraction - completed",
  "job_id": "abc-123",
  "timestamp": "2025-12-20T10:15:30.123Z",
  "stage": "toc_extraction",
  "status": "completed",
  "chapter_count": 12
}
```

### Viewing Logs

**Cloud Console:**
```
https://console.cloud.google.com/logs
```

**Query by Job ID:**
```
resource.type="cloud_run_revision"
jsonPayload.job_id="YOUR-JOB-ID"
```

**Query by Stage:**
```
resource.type="cloud_run_revision"
jsonPayload.stage="toc_extraction"
severity="ERROR"
```

**Recent Errors:**
```
resource.type="cloud_run_revision"
severity="ERROR"
timestamp>="2025-12-20T00:00:00Z"
```

## Job Status Tracking

### Status Files

Each job creates: `jobs/{job_id}/status.json`

```json
{
  "job_id": "abc-123",
  "status": "processing",
  "updated_at": "2025-12-20T10:15:30Z",
  "details": {
    "stage": "chapter_processing",
    "current_chapter": 5,
    "total_chapters": 12
  }
}
```

### Job States

| Status | Description |
|:---|:---|
| `queued` | Job accepted, chapters enqueued |
| `processing` | Actively processing chapters |
| `completed` | Successfully finished |
| `failed` | Error occurred |

### Checking Job Status

**Via GCS Console:**
```
gs://YOUR-BUCKET/jobs/{job_id}/status.json
```

**Via Script:**
```python
from services.gcs_service import GcsService
from services.job_tracker import JobTracker

gcs = GcsService()
tracker = JobTracker(gcs, "job-id-here")
status = tracker.get_status()
print(status)
```

## Email Alerts

### Setup

1. Configure notification email in `config/system_config.json`:
```json
{
  "notifications": {
    "alert_email": "your-email@example.com",
    "enabled": true,
    "alert_on_failure": true,
    "alert_on_completion": false
  }
}
```

2. Ensure GAS has Gmail scope in `appsscript.json`:
```json
{
  "oauthScopes": [
    "https://www.googleapis.com/auth/gmail.send"
  ]
}
```

### Alert Triggers

**Failure Alert** (automatic):
- Job fails in any stage
- Regex runaway detected
- PDF download fails
- Gemini API errors

**Completion Alert** (optional):
- Job successfully completes
- Summary generated

### Alert Email Format

```
Subject: [BookSummary] エラー発生: abc-123

書籍要約システムのジョブでエラーが発生しました。

ジョブID: abc-123
発生時刻: 2025-12-20T10:15:30Z
エラー: Regex runaway detected: 150 chapters found

コンテキスト:
{
  "file_id": "1abc...",
  "stage": "chapter_extraction"
}

Cloud Logging (ジョブログ):
https://console.cloud.google.com/logs/query;query=...
```

## Monitoring Best Practices

### 1. Set Up Log-Based Alerts

Create alert policies in Cloud Monitoring:

**High Error Rate:**
```
resource.type="cloud_run_revision"
severity="ERROR"
```
Alert when: Count > 5 in 5 minutes

**Job Failures:**
```
resource.type="cloud_run_revision"
jsonPayload.status="failed"
```
Alert when: Any occurrence

### 2. Monitor Job Queue

Check for stuck jobs daily:

```javascript
// In GAS, set up daily trigger
function checkStuckJobs() {
  // Query GCS for jobs older than 2 hours in 'processing' state
  // Send alert if found
}
```

### 3. Track Success Metrics

Query successful completions:
```
resource.type="cloud_run_revision"
jsonPayload.message="Book processing accepted"
timestamp>="2025-12-20T00:00:00Z"
```

## Troubleshooting

### Job Stuck in "Processing"

1. Check Cloud Logging for errors:
   ```
   jsonPayload.job_id="JOB-ID"
   severity="ERROR"
   ```

2. Check Cloud Tasks queue:
   ```
   gcloud tasks queues describe book-summary-queue --location=asia-northeast1
   ```

3. Manually trigger finalizer:
   ```bash
   curl -X POST https://YOUR-FUNCTION-URL/finalize_book \
     -H "Content-Type: application/json" \
     -d '{"job_id": "JOB-ID"}'
   ```

### No Email Alerts

1. Verify config:
   ```javascript
   const config = new ConfigService().getConfig();
   console.log(config.notifications);
   ```

2. Check GAS execution logs for email errors

3. Verify Gmail quota (100 emails/day for free accounts)

### Missing Logs

1. Check Cloud Logging is enabled:
   ```bash
   gcloud services list | grep logging
   ```

2. Verify Cloud Function has logging permissions:
   ```bash
   gcloud projects get-iam-policy PROJECT-ID
   ```

3. Test logger locally:
   ```python
   from services.logging_service import StructuredLogger
   logger = StructuredLogger("test-job")
   logger.info("Test message", test_key="test_value")
   ```

## Dashboards

### Recommended Cloud Monitoring Dashboard

Create custom dashboard with:

1. **Error Rate Chart:**
   - Metric: Cloud Run errors
   - Filter: service_name = "book-summary-system"

2. **Job Processing Time:**
   - Metric: Custom metric from logs
   - Query: Extract duration from completion logs

3. **Success Rate:**
   - Ratio of completed to failed jobs

### Logs Explorer Saved Queries

Save these queries for quick access:

1. **All Jobs Today:**
   ```
   jsonPayload.job_id!=""
   timestamp>="TODAY"
   ```

2. **Failed Jobs:**
   ```
   jsonPayload.status="failed"
   ```

3. **TOC Extraction Issues:**
   ```
   jsonPayload.stage="toc_extraction"
   severity>="WARNING"
   ```

## Integration with External Tools

### Slack Alerts (Optional)

Use Cloud Logging Log Sinks to forward to Pub/Sub → Cloud Function → Slack:

```python
# Example Cloud Function for Slack webhook
import requests

def send_to_slack(log_entry):
    webhook_url = "YOUR-SLACK-WEBHOOK"
    message = {
        "text": f"Job {log_entry['job_id']} failed: {log_entry['error']}"
    }
    requests.post(webhook_url, json=message)
```

### PagerDuty (Optional)

Configure Cloud Monitoring to send alerts to PagerDuty for critical failures.

## Cost Optimization

Logging costs can add up. To optimize:

1. **Reduce log retention:**
   ```bash
   gcloud logging sinks update SINK-NAME --log-filter="..." --retention-days=30
   ```

2. **Filter unnecessary logs:**
   - Only log ERROR and WARNING in production
   - Use DEBUG logs sparingly

3. **Use sampling for high-volume logs:**
   ```python
   if random.random() < 0.1:  # Log 10% of requests
       logger.debug(...)
   ```

## Security Considerations

- Never log sensitive data (API keys, user emails, etc.)
- Logs are readable by project editors - use IAM to restrict access
- Email alerts contain job IDs but no sensitive content
- Consider using Secret Manager for alert email configuration
