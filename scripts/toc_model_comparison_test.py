#!/usr/bin/env python3
"""
TOC Extraction Model Comparison Test v3

改善点:
- 既存のGeminiServiceを参考にしたリトライロジック（SSL, Rate Limit, JSON解析エラー対応）
- 上下巻対応: PDFの総ページ数を超えるページ番号の章をフィルタリング
- LLMに「このPDFに実際に含まれる章のみ」を抽出させる

使用方法:
    export GEMINI_API_KEY="your-api-key"
    python toc_model_comparison_test.py
"""

import os
import sys
import json
import time
import re
import ssl
from datetime import datetime
from typing import Dict, List, Any, Optional

import pypdf
import google.generativeai as genai

# Configuration
PDF_PATH = "/Users/takagishota/Documents/KnowledgeBase/ナシーム・ニコラス・タレブ_反脆弱性_上.pdf"
TOC_MODEL = "gemini-2.0-flash-exp"  # 目次抽出用
SUMMARY_MODEL = "gemini-2.5-flash"  # 要約用（精度維持）

# Pages to scan for TOC (usually first 15-25 pages)
TOC_SCAN_PAGES = 25


def setup_gemini():
    """Initialize Gemini API."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY environment variable not set")
        print("   Run: export GEMINI_API_KEY='your-api-key'")
        sys.exit(1)
    genai.configure(api_key=api_key)
    print("✅ Gemini API configured")


def call_gemini_with_retry(
    model_name: str,
    prompt: str,
    max_retries: int = 3,
    max_output_tokens: int = 4096
) -> Optional[Dict]:
    """
    Call Gemini with retry logic including SSL error handling.
    Based on existing GeminiService implementation.
    """
    model = genai.GenerativeModel(model_name)
    
    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=max_output_tokens,
                    response_mime_type="application/json"
                )
            )
            
            cleaned_text = response.text.strip()
            if cleaned_text.startswith("```"):
                cleaned_text = re.sub(r"^```json\s*", "", cleaned_text)
                cleaned_text = re.sub(r"^```\s*", "", cleaned_text)
                cleaned_text = re.sub(r"\s*```$", "", cleaned_text)
            
            return json.loads(cleaned_text)
            
        except json.JSONDecodeError as e:
            print(f"  ⚠️ JSON error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"  ⏳ Retrying in 5s...")
                time.sleep(5)
            continue
            
        except (ssl.SSLError, ConnectionError, OSError) as e:
            wait_time = 10 * (attempt + 1)
            print(f"  ⚠️ Connection error (attempt {attempt+1}/{max_retries}): {e}")
            print(f"  ⏳ Waiting {wait_time}s before retry...")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            continue
            
        except Exception as e:
            error_str = str(e)
            print(f"  ⚠️ API error (attempt {attempt+1}/{max_retries}): {e}")
            
            if "ssl" in error_str.lower() or "eof" in error_str.lower() or "connection" in error_str.lower():
                wait_time = 10 * (attempt + 1)
                print(f"  ⏳ Connection issue - waiting {wait_time}s...")
                if attempt < max_retries - 1:
                    time.sleep(wait_time)
            elif "429" in error_str or "quota" in error_str.lower():
                print("  ⏳ Rate limit - waiting 60s...")
                time.sleep(60)
            elif attempt < max_retries - 1:
                time.sleep(5)
            continue
    
    return None


def extract_text_from_pages(pdf_path: str, start_page: int = 0, end_page: Optional[int] = None) -> str:
    """Extract text from specific page range."""
    reader = pypdf.PdfReader(pdf_path)
    total_pages = len(reader.pages)
    
    if end_page is None:
        end_page = total_pages
    
    end_page = min(end_page, total_pages)
    
    text_parts = []
    for i in range(start_page, end_page):
        try:
            page_text = reader.pages[i].extract_text()
            if page_text:
                text_parts.append(f"--- Page {i+1} ---\n{page_text}")
        except Exception as e:
            print(f"  Warning: Failed to extract page {i+1}: {e}")
    
    return "\n\n".join(text_parts)


def extract_toc_for_current_volume(toc_text: str, total_pages: int, pdf_filename: str) -> Dict[str, Any]:
    """
    Use gemini-2.0-flash-exp to extract table of contents.
    Key improvement: Tell the LLM the total page count so it knows which chapters are in this volume.
    """
    # Use v2-style prompt which worked better for page number extraction
    prompt = f"""あなたは書籍の目次構造を解析する専門家です。

以下のテキストはPDFの最初の25ページから抽出したものです。
目次（Table of Contents）ページを見つけて、各章の情報を抽出してください。

【重要】
- このPDFの総ページ数は {total_pages} ページです
- ファイル名: {pdf_filename}
- 目次に記載されている「ページ番号」は、その章の内容が実際に始まるページです
- 例: 「第1章 ダモクレスとヒュドラーの間で......25」の「25」がcontent_start_page
- ページ番号が {total_pages} を超える章は、このPDFには含まれていません（上下巻の可能性）

抽出ルール:
1. 目次ページを特定し、そこから章構造を読み取る
2. 「第○章」「Part」「Chapter」「第○部」などのパターンを探す
3. 章タイトルの横にあるページ番号を content_start_page として記録
4. ページ番号が {total_pages} を超える章は chapters_not_in_this_volume に記載

出力形式 (JSON):
{{
  "book_title": "書籍タイトル",
  "volume_info": "上巻/下巻/全1巻（わかれば）",
  "toc_found": true/false,
  "toc_page_range": "目次が何ページから何ページにあるか（例: 5-10）",
  "total_pdf_pages": {total_pages},
  "chapters_in_this_volume": [
    {{
      "type": "part",
      "number": "第1部",
      "title": "部タイトル",
      "content_start_page": 23,
      "content_end_page": null
    }},
    {{
      "type": "chapter",
      "number": "第1章",
      "title": "章タイトル",
      "parent_part": "第1部",
      "content_start_page": 25,
      "content_end_page": null
    }}
  ],
  "chapters_not_in_this_volume": ["第17章 xxxxx", "第18章 xxxxx"],
  "notes": "目次解析に関する補足情報（上下巻情報など）"
}}

===== 抽出テキスト =====
{toc_text}
"""

    result = call_gemini_with_retry(TOC_MODEL, prompt, max_retries=3, max_output_tokens=8192)
    
    if not result:
        return {
            "toc_found": False,
            "chapters_in_this_volume": [],
            "error": "TOC extraction failed after retries"
        }
    
    # Post-process: Calculate end pages
    chapters = result.get("chapters_in_this_volume", [])
    for i, ch in enumerate(chapters):
        if i + 1 < len(chapters):
            next_start = chapters[i + 1].get("content_start_page")
            if next_start and ch.get("content_start_page"):
                ch["content_end_page"] = next_start - 1
        else:
            # Last chapter ends at total_pages or earlier
            if ch.get("content_start_page"):
                ch["content_end_page"] = total_pages
    
    # Additional validation: filter out any chapters with pages exceeding total
    valid_chapters = []
    for ch in chapters:
        start = ch.get("content_start_page")
        if start and start <= total_pages:
            valid_chapters.append(ch)
        else:
            print(f"  ⚠️ Filtered out chapter with invalid page: {ch.get('number')}")
    
    result["chapters_in_this_volume"] = valid_chapters
    
    return result


def summarize_chapter(chapter_text: str, chapter_number: str, chapter_title: str, book_title: str) -> Dict[str, Any]:
    """
    Summarize a chapter using gemini-2.5-flash with retry logic.
    """
    # Truncate if too long
    max_chars = 50000
    if len(chapter_text) > max_chars:
        chapter_text = chapter_text[:max_chars] + "\n...(truncated)"
    
    full_title = f"{chapter_number} {chapter_title}"
    
    prompt = f"""あなたは書籍の要約専門家です。以下の章を詳細に要約してください。

書籍: {book_title}
章: {full_title}

要約のルール:
1. 主要な論点を箇条書きで整理（5-10ポイント）
2. 重要な概念やキーワードを抽出（5-10個）
3. 著者の主張を明確に
4. 具体例やメタファーがあれば含める
5. 日本語で出力
6. 要約は簡潔に、各ポイントは1-2文で

出力形式 (JSON):
{{
  "chapter_number": "{chapter_number}",
  "title": "{full_title}",
  "summary": "- ポイント1\\n- ポイント2\\n- ポイント3",
  "keyConcepts": ["概念1", "概念2"],
  "keyExamples": ["具体例があれば"],
  "keyQuotes": ["重要な引用があれば"]
}}

===== 章の内容 =====
{chapter_text}
"""
    
    result = call_gemini_with_retry(SUMMARY_MODEL, prompt, max_retries=3, max_output_tokens=4096)
    
    if not result:
        return {
            "chapter_number": chapter_number,
            "title": full_title,
            "summary": "(Summary generation failed after retries)",
            "keyConcepts": [],
            "_meta": {"error": "Failed after retries"}
        }
    
    return result


def run_comparison_test():
    """Main test function."""
    print("\n" + "="*60)
    print("📚 TOC Extraction Model Comparison Test v3")
    print("="*60)
    print(f"PDF: {PDF_PATH}")
    print(f"TOC Model: {TOC_MODEL}")
    print(f"Summary Model: {SUMMARY_MODEL}")
    print("="*60 + "\n")
    
    # Setup
    setup_gemini()
    
    # Check PDF exists
    if not os.path.exists(PDF_PATH):
        print(f"❌ Error: PDF not found at {PDF_PATH}")
        sys.exit(1)
    
    # Get total pages
    reader = pypdf.PdfReader(PDF_PATH)
    total_pages = len(reader.pages)
    pdf_filename = os.path.basename(PDF_PATH)
    print(f"📄 Total pages in PDF: {total_pages}")
    print(f"📁 Filename: {pdf_filename}")
    
    # Extract TOC pages
    print(f"\n📖 Extracting first {TOC_SCAN_PAGES} pages for TOC analysis...")
    toc_text = extract_text_from_pages(PDF_PATH, 0, TOC_SCAN_PAGES)
    print(f"   Extracted {len(toc_text)} characters")
    
    # Extract TOC with volume awareness
    print("\n" + "-"*60)
    print(f"🔍 TOC Extraction using {TOC_MODEL}")
    print(f"   (Volume-aware: filtering chapters beyond {total_pages} pages)")
    print("-"*60)
    
    start_time = time.time()
    toc_result = extract_toc_for_current_volume(toc_text, total_pages, pdf_filename)
    elapsed = time.time() - start_time
    
    toc_result["_meta"] = {
        "model": TOC_MODEL,
        "elapsed_seconds": round(elapsed, 2),
        "success": toc_result.get("toc_found", False)
    }
    
    print(f"⏱  Time: {elapsed:.2f}s")
    print(f"📋 TOC Found: {toc_result.get('toc_found', False)}")
    print(f"📖 Volume Info: {toc_result.get('volume_info', 'Unknown')}")
    print(f"📄 TOC Page Range: {toc_result.get('toc_page_range', 'Unknown')}")
    
    chapters = toc_result.get("chapters_in_this_volume", [])
    excluded = toc_result.get("chapters_not_in_this_volume", [])
    
    print(f"✅ Chapters in this volume: {len(chapters)}")
    print(f"❌ Chapters NOT in this volume: {len(excluded)}")
    if excluded:
        print(f"   Excluded: {excluded[:5]}{'...' if len(excluded) > 5 else ''}")
    
    # Show extracted chapters
    print("\n📖 Extracted structure:")
    for ch in chapters[:15]:
        ch_type = ch.get("type", "?")
        number = ch.get("number", "?")
        title = ch.get("title", "Untitled")
        start_page = ch.get("content_start_page", "?")
        end_page = ch.get("content_end_page", "?")
        
        icon = "📗" if ch_type == "part" else "  📄"
        print(f"  {icon} {number}: {title}")
        print(f"      Pages: {start_page} - {end_page}")
    
    if len(chapters) > 15:
        print(f"  ... and {len(chapters) - 15} more")
    
    # Notes
    if toc_result.get("notes"):
        print(f"\n📝 Notes: {toc_result.get('notes')}")
    
    # Save TOC result
    output_dir = os.path.dirname(os.path.abspath(__file__))
    toc_output_path = os.path.join(output_dir, "toc_comparison_result_v3.json")
    with open(toc_output_path, "w", encoding="utf-8") as f:
        json.dump(toc_result, f, ensure_ascii=False, indent=2)
    print(f"\n💾 TOC result saved to: {toc_output_path}")
    
    # Filter only "chapter" type entries (not "part")
    actual_chapters = [ch for ch in chapters if ch.get("type") == "chapter"]
    
    if not actual_chapters:
        print("\n❌ No chapters detected. Cannot proceed with summarization test.")
        return
    
    # Summarization test: Chapters 1-3 only
    print("\n" + "-"*60)
    print(f"📝 Summarization Test: Chapters 1-3 (using {SUMMARY_MODEL})")
    print("   (With retry logic for JSON errors)")
    print("-"*60)
    
    summary_results = []
    test_chapters = actual_chapters[:3]  # First 3 chapters
    
    for ch in test_chapters:
        chapter_number = ch.get("number", "?")
        chapter_title = ch.get("title", "Untitled")
        start_page = ch.get("content_start_page")
        end_page = ch.get("content_end_page")
        
        if start_page is None:
            print(f"\n⚠️  Skipping {chapter_number}: no page number")
            continue
        
        # Ensure end_page is valid
        if end_page is None or end_page > total_pages:
            end_page = min(start_page + 30, total_pages)
        
        print(f"\n▶ Summarizing: {chapter_number} {chapter_title}")
        print(f"  Content Pages: {start_page} - {end_page}")
        
        # Extract chapter text (0-indexed in pypdf)
        chapter_text = extract_text_from_pages(PDF_PATH, start_page - 1, end_page)
        print(f"  Extracted: {len(chapter_text)} characters")
        
        # Summarize with retry
        start_time = time.time()
        summary = summarize_chapter(
            chapter_text, 
            chapter_number, 
            chapter_title, 
            "反脆弱性"
        )
        elapsed = time.time() - start_time
        
        summary["_meta"] = {
            "model": SUMMARY_MODEL,
            "elapsed_seconds": round(elapsed, 2),
            "pages": f"{start_page}-{end_page}",
            "chars": len(chapter_text)
        }
        summary_results.append(summary)
        
        print(f"  ⏱  Time: {elapsed:.1f}s")
        print(f"  📋 Key Concepts: {summary.get('keyConcepts', [])[:5]}")
        
        # Rate limit protection
        print("  ⏳ Waiting 5s for rate limit...")
        time.sleep(5)
    
    # Save summary results
    summary_output_path = os.path.join(output_dir, "summary_test_result_v3.json")
    with open(summary_output_path, "w", encoding="utf-8") as f:
        json.dump({
            "toc_model": TOC_MODEL,
            "summary_model": SUMMARY_MODEL,
            "volume_info": toc_result.get("volume_info"),
            "chapters_summarized": len(summary_results),
            "summaries": summary_results
        }, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Summary results saved to: {summary_output_path}")
    
    # Final summary
    print("\n" + "="*60)
    print("📊 TEST COMPLETE")
    print("="*60)
    print(f"TOC Extraction: {TOC_MODEL}")
    print(f"  - Time: {toc_result.get('_meta', {}).get('elapsed_seconds')}s")
    print(f"  - Volume: {toc_result.get('volume_info', 'Unknown')}")
    print(f"  - Parts: {len([c for c in chapters if c.get('type') == 'part'])}")
    print(f"  - Chapters in volume: {len(actual_chapters)}")
    print(f"  - Chapters excluded: {len(excluded)}")
    print(f"\nSummarization: {SUMMARY_MODEL}")
    print(f"  - Chapters summarized: {len(summary_results)}")
    
    success_count = sum(1 for s in summary_results if "error" not in s.get("_meta", {}))
    print(f"  - Successful: {success_count}/{len(summary_results)}")
    
    for s in summary_results:
        status = "✅" if "error" not in s.get("_meta", {}) else "❌"
        print(f"    {status} {s.get('title', '?')}: {len(s.get('keyConcepts', []))} concepts")
    
    print("\n✅ Done!")


if __name__ == "__main__":
    run_comparison_test()
