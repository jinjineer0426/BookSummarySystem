# Book Summary System Deployment Guide

This guide explains how to deploy the Book Summary System to Google Cloud Platform (GCP) and Google Apps Script (GAS).

## Prerequisites

1.  **Google Cloud Project**: You need an active GCP project.
2.  **Billing Enabled**: Cloud Functions and Gemini API require billing to be enabled.
3.  **APIs Enabled**:
    *   Search for and enable: "Cloud Functions API", "Cloud Build API", "Google Drive API", "Vertex AI API".

## Step 1: Google Cloud Storage (GCS) Setup

1.  Go to the [GCS Browser](https://console.cloud.google.com/storage/browser).
2.  **Create a Bucket**:
    *   Name: `your-unique-bucket-name` (e.g., `my-book-summary-config`).
    *   Location: `Region` (e.g., `asia-northeast1` for Tokyo).
    *   Leave other settings as default.
3.  **Upload Configuration Files**:
    *   Create a folder named `config` inside the bucket.
    *   Upload `master_concepts.json` and `master_categories.json` from the `config/` directory on your machine to this `config/` folder in the bucket.

## Step 2: Deploy Cloud Function

1.  Go to [Cloud Functions](https://console.cloud.google.com/functions).
2.  Click **CREATE FUNCTION**.
3.  **Configuration**:
    *   **Environment**: 2nd gen.
    *   **Function name**: `process_book`
    *   **Region**: `asia-northeast1` (same as bucket).
    *   **Trigger**: HTTPS (Allow unauthenticated invocations if you want to test easily, strictly speaking for GAS you might want OIDC, but for simplicity: "Allow unauthenticated" or ensure GAS sends identity token). *Recommendation: Require authentication and set up GAS to send ID token.*
4.  **Runtime Variables**:
    *   Add Environment Variables under "Runtime, build, connections and security settings":
        *   `GCP_PROJECT_ID`: Your Project ID.
        *   `GCS_BUCKET_NAME`: The bucket name you created in Step 1.
        *   `GEMINI_API_KEY`: Your Gemini API Key (if using AI Studio key) or rely on Vertex AI (if using default credentials). *Code defaults to Vertex AI if key is dummy.*
5.  **Code**:
    *   **Runtime**: Python 3.10 (or newer).
    *   **Entry point**: `main_http_entry` (Crucial: Do not use `process_book`, as we need the router)
    *   **Source code**: Upload the files from `cloud_function/` (`main.py` and `requirements.txt`).
6.  **Deploy**: Click Deploy and wait for it to finish.
7.  **Copy URL**: Once deployed, copy the **Function URL** (e.g., `https://...cloudfunctions.net/process_book`).

## Step 3: Service Account (Permissions)

The Cloud Function needs permission to access GCS and Drive.

1.  Find the "Runtime service account" of your function (usually `PROJECT_ID-compute@developer.gserviceaccount.com`).
2.  **IAM**: Go to IAM & Admin.
3.  Grant this service account:
    *   `Storage Object Admin` (to read/write config files).
    *   `Vertex AI User` (to use Gemini).
4.  **Drive Access**:
    *   The Service Account needs access to your Google Drive folders.
    *   Copy the Service Account Email address.
    *   Go to your Google Drive folder (where PDFs are).
    *   **Share** the folder with the Service Account Email (Editor role).
    *   Also share the destination folder (where MD files will go) if different.

## Step 4: Google Apps Script (GAS) Setup

1.  Open your Google Apps Script editor (or create a new project).
2.  **Required**: Update Manifest (`appsscript.json`) for Auth.
    *   Click "Project Settings" (Gear icon) -> Check "Show 'appsscript.json' manifest file in editor".
    *   Go back to Editor -> Open `appsscript.json`.
    *   Paste content from `gas/appsscript.json` (This enables `openid` scope needed for IAM auth).
3.  **Copy Code**:
    *   Create `Trigger.gs`, `PDFTool.gs`, `GcsStorage.gs` and paste the content from the `gas/` directory.

### Configuration (Crucial Step)

Instead of editing the code directly, we use **Script Properties** for security.

1.  Go to **Project Settings** (Gear icon).
2.  Scroll to **Script Properties**.
3.  Click **Edit script properties** -> **Add script properties**.
4.  Add the following key-value pairs:

| Property | Value Example | Description |
| :--- | :--- | :--- |
| `GCS_BUCKET` | `my-book-summary-config` | Your GCS bucket name |
| `CLOUD_FUNCTION_URL` | `https://...cloudfunctions.net/process_book` | Cloud Function URL from Step 2 |
| `ANALYZE_URL` | `https://...cloudfunctions.net/analyze_concepts` | (Optional) If you have a separate analysis function |
| `PROCESSED_SHEET_ID` | `18Atya...` | ID of your logging Google Sheet |
| `LOG_SHEET_NAME` | `log` | Sheet name for logs |
| `GEMINI_API_KEY` | `AIzaSy...` | Your Gemini API Key |
| `PDF_SCAN_RAW_FOLDER_ID` | `1wJuMC...` | ID of folder where you upload raw scans |
| `PDF_FALLBACK_FOLDER_ID` | `1YsZJA...` | ID of folder for failed/skipped files |

5.  **JSON Properties**: Some properties require JSON string values.
    *   **SOURCE_FOLDERS**: `{"Business": "FOLDER_ID_1", "Tech": "FOLDER_ID_2"}`
    *   **PDF_DESTINATION_FOLDERS**: `{"Manga": "ID_A", "Technical": "ID_B"}`

## Step 5: Initialize & Test

1.  **Set Trigger**:
    *   Run `setupTrigger` function in `Trigger.gs`. (Sets up daily check at 1 AM)
    *   Run `setupSyncTrigger` function in `GcsStorage.gs`. (Sets up daily sync at 2 AM)
2.  **Run Manual Test**:
    *   Select `checkNewFiles` function and click "Run".
    *   Grant permissions when asked.

## Verification

1.  Upload a PDF to the monitored folder.
2.  Wait for the daily trigger OR run `checkNewFiles` manually.
3.  Check the Google Sheet -> Should see a new row.
4.  Check the Output Folder in your Obsidian Vault -> Should see a Markdown file.
