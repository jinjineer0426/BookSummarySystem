#!/usr/bin/env python3
"""
Reproduction test for Sapiens TOC extraction issue.
Tests the current Vision AI extraction to identify missing chapters (第2〜4章).
"""
import os
import sys
import json

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Add cloud_function to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cloud_function'))

from services.pdf_processor import PdfProcessor
from services.gemini_service import GeminiService
from services.gcs_service import GcsService
from googleapiclient.discovery import build
from google.oauth2 import service_account

# Sapiens 上巻
SAPIENS_FILE_ID = "1EN2h_kgyf5o0RUA61eehX0cul6r1FDeg"
SAPIENS_EXPECTED_CHAPTERS = [
    "第1章", "第2章", "第3章", "第4章",  # 第1部
    "第5章", "第6章", "第7章", "第8章",  # 第2部  
    "第9章", "第10章", "第11章"          # 第3部
]

def main():
    print("="*60)
    print("🔍 Sapiens TOC Extraction Reproduction Test")
    print("="*60)
    
    # Initialize services
    print("\n1️⃣ Initializing services...")
    gcs = GcsService()
    gemini = GeminiService()
    processor = PdfProcessor()
    
    # Build Drive service
    drive = build('drive', 'v3')
    
    # Download PDF
    print("\n2️⃣ Downloading PDF from Google Drive...")
    pdf_path = processor.download_file_to_temp(drive, SAPIENS_FILE_ID, "sapiens_upper.pdf")
    print(f"   Downloaded to: {pdf_path}")
    
    # Extract TOC with Vision AI
    print("\n3️⃣ Extracting TOC with Vision AI...")
    print(f"   Model: gemini-2.5-flash")
    result = processor.extract_toc_with_ai(
        pdf_path, 
        gemini, 
        gcs_service=None,  # Don't save to GCS
        job_id="test-sapiens-repro"
    )
    
    if not result:
        print("❌ TOC extraction returned None")
        return
    
    # Analyze results
    print("\n4️⃣ Analysis Results:")
    chapters = result.get("chapters_in_this_volume", [])
    print(f"   Total chapters extracted: {len(chapters)}")
    print(f"   Expected chapters: {len(SAPIENS_EXPECTED_CHAPTERS)}")
    
    print("\n   Extracted chapters:")
    extracted_numbers = []
    for ch in chapters:
        number = ch.get("number", "")
        title = ch.get("title", "")
        start = ch.get("content_start_page", "?")
        end = ch.get("content_end_page", "?")
        print(f"     {number} {title} (pages {start}-{end})")
        extracted_numbers.append(number)
    
    # Check for missing chapters
    print("\n5️⃣ Missing Chapter Analysis:")
    missing = []
    for expected in SAPIENS_EXPECTED_CHAPTERS:
        if not any(expected in num for num in extracted_numbers):
            missing.append(expected)
    
    if missing:
        print(f"   ❌ Missing chapters: {', '.join(missing)}")
    else:
        print(f"   ✅ All chapters extracted!")
    
    # Check continuity
    print("\n6️⃣ Chapter Continuity Check:")
    chapter_nums = []
    for num in extracted_numbers:
        import re
        m = re.search(r'第(\d+)章', num)
        if m:
            chapter_nums.append(int(m.group(1)))
    
    if chapter_nums:
        gaps = []
        sorted_nums = sorted(chapter_nums)
        for i in range(len(sorted_nums) - 1):
            if sorted_nums[i+1] - sorted_nums[i] > 1:
                gaps.append((sorted_nums[i], sorted_nums[i+1]))
        
        if gaps:
            print(f"   ❌ Gaps detected:")
            for start, end in gaps:
                print(f"      - Gap between 第{start}章 and 第{end}章")
        else:
            print(f"   ✅ No gaps in chapter sequence")
    
    # Save result
    output_file = os.path.join(os.path.dirname(__file__), "sapiens_toc_repro_result.json")
    with open(output_file, "w") as f:
        json.dump({
            "result": result,
            "extracted_count": len(chapters),
            "expected_count": len(SAPIENS_EXPECTED_CHAPTERS),
            "missing": missing,
            "chapter_numbers": chapter_nums
        }, f, ensure_ascii=False, indent=2)
    print(f"\n📁 Result saved to: {output_file}")
    
    print("\n" + "="*60)
    if missing:
        print(f"❌ TEST FAILED: {len(missing)} chapters missing")
    else:
        print("✅ TEST PASSED: All chapters extracted")
    print("="*60)

if __name__ == "__main__":
    main()
