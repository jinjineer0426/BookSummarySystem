#!/usr/bin/env python3
"""戦略ごっこ TOC抽出問題の再現テスト"""
import os, sys, json, re

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, '../cloud_function'))

from services.pdf_processor import PdfProcessor
from services.gemini_service import GeminiService

PDF_PATH = "/Users/takagishota/Documents/KnowledgeBase/戦略ごっこ_マーケティング以前の問題.pdf"

def test_vision_toc():
    """Vision AI TOC抽出テスト"""
    print("\n" + "=" * 60)
    print("Vision AI TOC抽出")
    print("=" * 60)
    
    processor = PdfProcessor()
    gemini = GeminiService()
    # Check if API KEY is set
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY is not set.")
        return None
        
    toc_data = processor.extract_toc_with_ai(PDF_PATH, gemini)
    
    if not toc_data:
        print("❌ Vision AI: 抽出失敗")
        return None
    
    chapters = toc_data.get("chapters_in_this_volume", [])
    print(f"✅ {len(chapters)}章検出")
    
    for ch in chapters[:10]:
        title = f"{ch.get('number', '')} {ch.get('title', '')}"
        print(f"  [p.{ch.get('content_start_page') if ch.get('content_start_page') else 0:3d}] {title[:60]}")
    
    return toc_data

def test_regex_fallback():
    """正規表現フォールバックテスト"""
    print("\n" + "=" * 60)
    print("正規表現フォールバック")
    print("=" * 60)
    
    processor = PdfProcessor()
    text = processor.extract_text_from_pdf_file(PDF_PATH)
    chapters = processor.split_into_chapters(text)
    
    print(f"✅ {len(chapters)}章検出")
    
    problems = []
    for ch in chapters:
        title = ch.get("title", "")
        title_len = len(title)
        status = "⚠️" if title_len > 80 else "✅"
        # Only print first 10
        if chapters.index(ch) < 10:
            print(f"  {status} Len:{title_len:3d} | {title[:60]}...")
        
        if title_len > 80:
            problems.append(f"長すぎ({title_len}文字): {title[:40]}...")
        if "Contents" in title:
            problems.append(f"ゴミ文字(Contents): {title[:40]}...")
            
    if problems:
        print(f"\n⚠️ 問題タイトル: {len(problems)}件")
        for p in problems[:5]:
            print(f"  - {p}")
    
    return chapters

if __name__ == "__main__":
    if not os.path.exists(PDF_PATH):
        print(f"❌ PDF not found: {PDF_PATH}")
        sys.exit(1)
    
    # Run both tests
    regex_chapters = test_regex_fallback()
    vision_toc = test_vision_toc()
