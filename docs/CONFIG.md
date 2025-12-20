# Configuration Guide

## Overview

BookSummarySystem uses a **unified configuration system** based on Google Cloud Storage (GCS). This provides a Single Source of Truth for configuration across Cloud Functions and Google Apps Script components.

## Configuration Priority

Settings are loaded with the following priority:

1. **GCS Configuration** (`config/system_config.json`)
2. **Environment Variables** (Cloud Function only)
3. **Default Values**

## Setup Instructions

### 1. Create GCS Configuration File

Upload `config/system_config.json` to your GCS bucket:

```bash
gsutil cp config/system_config.json gs://YOUR-BUCKET-NAME/config/
```

### 2. Configure System Config

Edit `config/system_config.json`:

```json
{
  "version": "1.0",
  "gemini": {
    "model_id": "gemini-2.0-flash",
    "toc_extraction_model": "gemini-2.0-flash-exp"
  },
  "folders": {
    "source_folders": {
      "Humanities/Business": "FOLDER_ID_HERE",
      "Technical": "FOLDER_ID_HERE"
    },
    "destination_folders": {
      "Manga": "FOLDER_ID_HERE",
      "Novel": "FOLDER_ID_HERE",
      "Humanities/Business": "FOLDER_ID_HERE",
      "Technical": "FOLDER_ID_HERE",
      "Other": "FOLDER_ID_HERE"
    }
  },
  "notifications": {
    "alert_email": "your-email@example.com",
    "enabled": true,
    "alert_on_failure": true,
    "alert_on_completion": false
  }
}
```

### 3. Set GAS Script Properties (Fallback)

In Google Apps Script, set these Script Properties as fallback:

```javascript
// In Apps Script Editor: Project Settings > Script Properties
GCS_BUCKET = "your-bucket-name"
ALERT_EMAIL = "your-email@example.com"
ALERTS_ENABLED = "true"
```

## Configuration Reference

### Gemini Settings

| Key | Description | Default |
|:---|:---|:---|
| `gemini.model_id` | Base Gemini model | `gemini-2.0-flash` |
| `gemini.toc_extraction_model` | Model for TOC extraction | `gemini-2.0-flash-exp` |
| `gemini.temperature` | Generation temperature | `0.2` |

### Processing Settings

| Key | Description | Default |
|:---|:---|:---|
| `processing.toc_scan_start_page` | TOC scan start (0-indexed) | `3` |
| `processing.toc_scan_end_page` | TOC scan end | `30` |
| `processing.toc_image_dpi` | DPI for PDF to image | `100` |
| `processing.similarity_threshold` | Concept matching threshold | `0.82` |
| `processing.batch_size` | Chapter batch size | `2` |

### Cloud Tasks Settings

| Key | Description | Default |
|:---|:---|:---|
| `cloud_tasks.region` | GCP region | `us-central1` |
| `cloud_tasks.queue_name` | Task queue name | `book-summary-queue` |
| `cloud_tasks.chapter_delay_seconds` | Delay between chapters | `60` |

### Notification Settings

| Key | Description | Default |
|:---|:---|:---|
| `notifications.alert_email` | Email for alerts | `""` |
| `notifications.enabled` | Enable notifications | `false` |
| `notifications.alert_on_failure` | Alert on job failure | `true` |
| `notifications.alert_on_completion` | Alert on completion | `false` |

## Accessing Configuration

### In Cloud Functions (Python)

```python
from config import get_config_loader

loader = get_config_loader()
model_id = loader.get('gemini.model_id', 'gemini-2.0-flash')
```

### In Google Apps Script

```javascript
const config = new ConfigService().getConfig();
const alertEmail = config.notifications.alert_email;
```

## Updating Configuration

To update configuration without redeploying:

1. Edit `config/system_config.json` locally
2. Upload to GCS:
   ```bash
   gsutil cp config/system_config.json gs://YOUR-BUCKET/config/
   ```
3. Configuration cache refreshes automatically after 5 minutes

To force immediate refresh in GAS:
```javascript
new ConfigService().refresh()
```

## Migration from Environment Variables

If you're migrating from environment variables:

1. Keep existing environment variables as fallback
2. Add values to `system_config.json`
3. GCS config will take priority automatically
4. Remove environment variables once verified

## Troubleshooting

### GCS Config Not Loading

Check Cloud Logging:
```
resource.type="cloud_run_revision"
jsonPayload.message="Config loaded from GCS"
```

If you see "Using defaults/cache", verify:
- GCS bucket name is correct
- Config file exists at `config/system_config.json`
- Cloud Function has Storage Object Viewer permission

### GAS Config Fallback

If GAS falls back to Script Properties, check:
- Script Properties has `GCS_BUCKET` set
- GAS has authorization to access GCS
- Config file is readable (public or authenticated)
