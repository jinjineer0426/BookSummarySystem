#!/usr/bin/env python3
"""
Integration test for Vision-based TOC extraction using the actual service classes.
"""
import os
import sys
import json
import traceback

# Add cloud_function to path
current_dir = os.path.dirname(os.path.abspath(__file__))
cloud_function_dir = os.path.abspath(os.path.join(current_dir, '../cloud_function'))
sys.path.append(cloud_function_dir)
print(f"Added {cloud_function_dir} to sys.path")

try:
    from services.pdf_processor import PdfProcessor
    from services.gemini_service import GeminiService
    import config
    print("Imports successful")
except Exception as e:
    print(f"Import Error: {e}")
    traceback.print_exc()
    sys.exit(1)

# Configuration
PDF_PATH = "/Users/takagishota/Documents/KnowledgeBase/ナシーム・ニコラス・タレブ_反脆弱性_下.pdf"

if not os.path.exists(PDF_PATH):
    print(f"PDF not found: {PDF_PATH}")
    sys.exit(1)

# Mock config if needed
if not os.environ.get("GEMINI_API_KEY"):
    print("Please set GEMINI_API_KEY")
    sys.exit(1)

def run_test():
    print("Testing PdfProcessor with Vision TOC...")
    
    try:
        # Initialize services
        gemini = GeminiService()
        processor = PdfProcessor()
        
        # 1. Test TOC Extraction
        print(f"Extracting TOC from {PDF_PATH}...")
        toc_data = processor.extract_toc_with_ai(PDF_PATH, gemini)
        
        if not toc_data:
            print("❌ TOC Extraction failed (returned None)")
            return
            
        print(f"✅ TOC Found: {len(toc_data.get('chapters_in_this_volume', []))} chapters")
        volume_info = toc_data.get('volume_info')
        print(f"ℹ️ Volume Info: {volume_info}")
        print(json.dumps(toc_data, indent=2, ensure_ascii=False))
        
        # 2. Test Chapter Extraction
        print("Extracting chapters...")
        chapters = processor.extract_chapters_from_toc(PDF_PATH, toc_data)
        
        print(f"✅ Extracted {len(chapters)} chapters text")
        
        for i, ch in enumerate(chapters[:5]):
            print(f"  - [{i+1}] {ch.get('title', 'No Title')} ({len(ch.get('content', ''))} chars)")
            print(f"    Start page: {ch.get('content_start_page')}")

    except Exception as e:
        print(f"Runtime Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        print(f"Top-level Error: {e}")
        traceback.print_exc()
