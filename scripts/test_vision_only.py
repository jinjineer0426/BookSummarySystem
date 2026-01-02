#!/usr/bin/env python3
"""戦略ごっこ Vision AI TOC抽出のみのテスト"""
import os, sys, json

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, '../cloud_function'))

from services.pdf_processor import PdfProcessor
from services.gemini_service import GeminiService

PDF_PATH = "/Users/takagishota/Documents/KnowledgeBase/戦略ごっこ_マーケティング以前の問題.pdf"

def test_vision_toc():
    print("\n" + "=" * 60)
    print("Vision AI TOC抽出 (Focused Test)")
    print("=" * 60)
    
    processor = PdfProcessor()
    gemini = GeminiService()
    
    # TOC starts around page 24. Scanning 24-35.
    toc_data = processor.extract_toc_with_ai(PDF_PATH, gemini, override_end_page=35)
    
    if not toc_data:
        print("❌ Vision AI: 抽出失敗")
        return None
    
    chapters = toc_data.get("chapters_in_this_volume", [])
    print(f"✅ {len(chapters)}章検出")
    
    # 品質検証の結果も確認したいが、現在は内部でログを出すのみ
    for ch in chapters:
        title = f"{ch.get('number', '')} {ch.get('title', '')}"
        print(f"  [p.{ch.get('content_start_page', 0):3d}] {title}")
    
    return toc_data

if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY is not set.")
        sys.exit(1)
    test_vision_toc()
