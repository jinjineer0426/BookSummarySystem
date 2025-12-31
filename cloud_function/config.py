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

# API Key
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "") 

# === GCS-based Configuration Loader ===
# Load dynamic configuration from GCS (with caching and env fallback)
_config_loader = None

def get_config_loader():
    """Get or create the global config loader instance."""
    global _config_loader
    if _config_loader is None and BUCKET_NAME:
        from services.config_loader import ConfigLoader
        _config_loader = ConfigLoader(BUCKET_NAME)
    return _config_loader

# Load configuration with GCS priority and env fallback
def get_config_value(key_path: str, env_var: str = None, default=None):
    """
    Get configuration value with priority: GCS config > ENV var > default.
    
    Args:
        key_path: Dot-notation path in GCS config (e.g., 'gemini.model_id')
        env_var: Optional environment variable name to check as fallback
        default: Default value if not found
    """
    loader = get_config_loader()
    
    # Try GCS config first
    if loader:
        value = loader.get(key_path)
        if value is not None:
            return value
    
    # Fall back to environment variable
    if env_var:
        env_value = os.environ.get(env_var)
        if env_value is not None:
            return env_value
    
    # Return default
    return default

# === TOC Extraction Configuration ===
# Model for Vision-based TOC extraction (must support image input)
TOC_EXTRACTION_MODEL = get_config_value(
    "gemini.toc_extraction_model",
    "TOC_EXTRACTION_MODEL",
    "gemini-2.5-flash"
)

# DPI for converting PDF pages to images (lower = less memory, 100 is sufficient for TOC)
TOC_IMAGE_DPI = int(get_config_value(
    "processing.toc_image_dpi",
    "TOC_IMAGE_DPI",
    "100"
))

# TOC scan range: start page (0-indexed) and max end page
TOC_SCAN_START_PAGE = int(get_config_value(
    "processing.toc_scan_start_page",
    "TOC_SCAN_START_PAGE",
    "0"
))

TOC_SCAN_END_PAGE = int(get_config_value(
    "processing.toc_scan_end_page",
    "TOC_SCAN_END_PAGE",
    "30"
))

# Similarity threshold for concept matching
SIMILARITY_THRESHOLD = float(get_config_value(
    "processing.similarity_threshold",
    "SIMILARITY_THRESHOLD",
    "0.82"
))

