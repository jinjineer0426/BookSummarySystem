
import os
import sys
import json
import logging
import time

# Add cloud_function to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '../cloud_function'))

# Load .env manually
env_path = os.path.join(os.path.dirname(__file__), '../.env')
if os.path.exists(env_path):
    print(f"Loading .env from {env_path}")
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                os.environ[key] = value

# Setup logging to console
logging.basicConfig(level=logging.DEBUG)

# Import services
try:
    from services.pdf_processor import PdfProcessor
    from services.gemini_service import GeminiService
    from services.gcs_service import GcsService
except ImportError as e:
    print(f"Error importing services: {e}")
    sys.exit(1)

def main():
    # Default target
    target_pdf = "/Users/takagishota/Developer/book-summary-system/test/野中郁次郎, 杉之尾孝生, 鎌田伸一, 寺本義也, 戸部良一, 村井友秀_失敗の本質 日本軍の組織論的研究.pdf"
    
    # Allow override via arg
    if len(sys.argv) > 1:
        target_pdf = sys.argv[1]

    if not os.path.exists(target_pdf):
        print(f"Error: PDF not found at {target_pdf}")
        return

    print("Initializing services...")
    try:
        gemini = GeminiService()
    except Exception as e:
        print(f"Failed to init GeminiService: {e}")
        return

    processor = PdfProcessor()
    
    # Mock GCS Service
    class MockGcsUtils:
        def __init__(self):
            self.bucket = self
        def blob(self, name):
            return self
        def upload_from_string(self, *args, **kwargs):
            print(f"[MockGCS] Uploading to blob")
        def download_as_text(self):
            return "{}"
        def exists(self):
            return False

    mock_gcs = MockGcsUtils()

    print(f"Processing {target_pdf}...")
    
    # Run TOC extraction
    start_time = time.time()
    result = processor.extract_toc_with_ai(
        pdf_path=target_pdf,
        gemini_service=gemini,
        gcs_service=mock_gcs,
        job_id="DEBUG_LOCAL_RUN"
    )
    elapsed = time.time() - start_time

    print("\n" + "="*30)
    print(f"RESULT (Time: {elapsed:.2f}s):")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("="*30)

if __name__ == "__main__":
    main()
