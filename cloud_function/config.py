import os

# === Configuration ===
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "")

# Cloud Tasks
REGION = os.environ.get("GCP_REGION", "us-central1")
QUEUE_NAME = os.environ.get("CLOUD_TASKS_QUEUE", "book-summary-queue")
FUNCTION_URL = os.environ.get("FUNCTION_URL", "")  # URL of this Cloud Function

# Obsidian Vault Bucket for output (synced via Remotely Save)
OBSIDIAN_BUCKET_NAME = os.environ.get("OBSIDIAN_BUCKET_NAME", "")

# Destination Folder ID for Obsidian (e.g. "20_Reading")
OUTPUT_FOLDER_ID = os.environ.get("OUTPUT_FOLDER_ID", "") 
# Knowledge Folder ID for MoC
KNOWLEDGE_FOLDER_ID = os.environ.get("KNOWLEDGE_FOLDER_ID", "")


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "") 
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", 0.82))

# === TOC Extraction Configuration ===
# Model for Vision-based TOC extraction (must support image input)
TOC_EXTRACTION_MODEL = os.environ.get("TOC_EXTRACTION_MODEL", "gemini-2.0-flash-exp")
# DPI for converting PDF pages to images (lower = less memory, 100 is sufficient for TOC)
TOC_IMAGE_DPI = int(os.environ.get("TOC_IMAGE_DPI", "100"))
# TOC scan range: start page (0-indexed) and max end page
TOC_SCAN_START_PAGE = int(os.environ.get("TOC_SCAN_START_PAGE", "3"))  # Page 4
TOC_SCAN_END_PAGE = int(os.environ.get("TOC_SCAN_END_PAGE", "30"))  # Up to page 30
