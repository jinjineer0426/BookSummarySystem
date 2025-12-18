#!/usr/bin/env python3
"""
TOC Extraction with Vision API v4

PDFの目次ページを画像として変換し、Gemini Vision で解析することで
OCRの問題を回避し、正確なページ番号を取得する。

使用方法:
    export GEMINI_API_KEY="your-api-key"
    python toc_vision_test.py
"""

import os
import sys
import json
import time
import re
import ssl
import base64
from typing import Dict, List, Any, Optional

import fitz  # PyMuPDF
import google.generativeai as genai

# Configuration
PDF_PATH = "/Users/takagishota/Documents/KnowledgeBase/ナシーム・ニコラス・タレブ_反脆弱性_上.pdf"
TOC_MODEL = "gemini-2.0-flash-exp"  # Vision対応モデル
SUMMARY_MODEL = "gemini-2.5-flash"

# TOC is typically in first 10-15 pages
TOC_PAGE_RANGE = (3, 12)  # 0-indexed: pages 4-12


def setup_gemini():
    """Initialize Gemini API."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY environment variable not set")
        sys.exit(1)
    genai.configure(api_key=api_key)
    print("✅ Gemini API configured")


def pdf_pages_to_images(pdf_path: str, start_page: int, end_page: int, dpi: int = 150) -> List[bytes]:
    """
    Convert PDF pages to PNG images.
    Returns list of PNG bytes.
    """
    doc = fitz.open(pdf_path)
    images = []
    
    for page_num in range(start_page, min(end_page, len(doc))):
        page = doc[page_num]
        # Convert to image with specified DPI
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        images.append(img_bytes)
        print(f"  📸 Converted page {page_num + 1} to image ({len(img_bytes)} bytes)")
    
    doc.close()
    return images


def extract_toc_with_vision(images: List[bytes], total_pages: int, pdf_filename: str) -> Dict[str, Any]:
    """
    Use Gemini Vision to extract TOC from page images.
    """
    model = genai.GenerativeModel(TOC_MODEL)
    
    prompt = f"""あなたは書籍の目次を画像から読み取る専門家です。

【重要な情報】
- このPDFの総ページ数: {total_pages} ページ
- ファイル名: {pdf_filename}

添付された画像は書籍の目次ページです。
各章のタイトルと、その章が始まるページ番号を正確に読み取ってください。

【読み取りのポイント】
1. 目次には「第○章 タイトル ... ページ番号」の形式で記載されています
2. ページ番号は通常、行の右端にある数字です（例: 62, 78, 100など）
3. 「...」や点線で章タイトルとページ番号が結ばれている場合があります
4. 「部」と「章」を区別してください
5. ページ番号が {total_pages} を超える章は、このPDFには含まれていません

出力形式 (JSON):
{{
  "book_title": "書籍タイトル",
  "volume_info": "上巻/下巻/全1巻",
  "toc_found": true,
  "chapters_in_this_volume": [
    {{
      "type": "part",
      "number": "第1部",
      "title": "部タイトル",
      "content_start_page": 23
    }},
    {{
      "type": "chapter", 
      "number": "第1章",
      "title": "章タイトル",
      "parent_part": "第1部",
      "content_start_page": 62
    }}
  ],
  "chapters_not_in_this_volume": ["第17章 タイトル", "第18章 タイトル"],
  "notes": "補足情報"
}}
"""
    
    # Build content with images
    content = [prompt]
    for i, img_bytes in enumerate(images):
        content.append({
            "mime_type": "image/png",
            "data": base64.b64encode(img_bytes).decode("utf-8")
        })
    
    print(f"  📤 Sending {len(images)} images to Gemini Vision...")
    
    try:
        start_time = time.time()
        response = model.generate_content(
            content,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=8192,
                response_mime_type="application/json"
            )
        )
        elapsed = time.time() - start_time
        
        # Parse response
        cleaned_text = response.text.strip()
        if cleaned_text.startswith("```"):
            cleaned_text = re.sub(r"^```json\s*", "", cleaned_text)
            cleaned_text = re.sub(r"^```\s*", "", cleaned_text)
            cleaned_text = re.sub(r"\s*```$", "", cleaned_text)
        
        result = json.loads(cleaned_text)
        result["_meta"] = {
            "model": TOC_MODEL,
            "method": "vision",
            "elapsed_seconds": round(elapsed, 2),
            "images_sent": len(images)
        }
        
        # Post-process: Calculate end pages
        chapters = result.get("chapters_in_this_volume", [])
        for i, ch in enumerate(chapters):
            if i + 1 < len(chapters):
                next_start = chapters[i + 1].get("content_start_page")
                if next_start and ch.get("content_start_page"):
                    ch["content_end_page"] = next_start - 1
            else:
                if ch.get("content_start_page"):
                    ch["content_end_page"] = total_pages
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"  ⚠️ JSON parse error: {e}")
        return {"toc_found": False, "error": str(e)}
    except Exception as e:
        print(f"  ⚠️ Vision API error: {e}")
        return {"toc_found": False, "error": str(e)}


def extract_text_from_pages(pdf_path: str, start_page: int, end_page: int) -> str:
    """Extract text from specific page range using PyMuPDF."""
    doc = fitz.open(pdf_path)
    text_parts = []
    
    for page_num in range(start_page, min(end_page, len(doc))):
        page = doc[page_num]
        text = page.get_text()
        if text:
            text_parts.append(f"--- Page {page_num + 1} ---\n{text}")
    
    doc.close()
    return "\n\n".join(text_parts)


def call_gemini_with_retry(
    model_name: str,
    prompt: str,
    max_retries: int = 3,
    max_output_tokens: int = 4096
) -> Optional[Dict]:
    """Call Gemini with retry logic."""
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
                time.sleep(5)
            continue
        except Exception as e:
            print(f"  ⚠️ API error (attempt {attempt+1}/{max_retries}): {e}")
            if "429" in str(e) or "quota" in str(e).lower():
                time.sleep(60)
            elif attempt < max_retries - 1:
                time.sleep(5)
            continue
    
    return None


def summarize_chapter(chapter_text: str, chapter_number: str, chapter_title: str, book_title: str) -> Dict[str, Any]:
    """Summarize a chapter using gemini-2.5-flash."""
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


def run_vision_test():
    """Main test function using Vision API."""
    print("\n" + "="*60)
    print("📚 TOC Extraction with Vision API v4")
    print("="*60)
    print(f"PDF: {PDF_PATH}")
    print(f"TOC Model: {TOC_MODEL} (Vision)")
    print(f"Summary Model: {SUMMARY_MODEL}")
    print("="*60 + "\n")
    
    # Setup
    setup_gemini()
    
    # Check PDF exists
    if not os.path.exists(PDF_PATH):
        print(f"❌ Error: PDF not found at {PDF_PATH}")
        sys.exit(1)
    
    # Get PDF info
    doc = fitz.open(PDF_PATH)
    total_pages = len(doc)
    pdf_filename = os.path.basename(PDF_PATH)
    doc.close()
    
    print(f"📄 Total pages in PDF: {total_pages}")
    print(f"📁 Filename: {pdf_filename}")
    
    # Convert TOC pages to images
    print(f"\n📸 Converting pages {TOC_PAGE_RANGE[0]+1}-{TOC_PAGE_RANGE[1]} to images...")
    images = pdf_pages_to_images(PDF_PATH, TOC_PAGE_RANGE[0], TOC_PAGE_RANGE[1])
    print(f"   Total images: {len(images)}")
    
    # Extract TOC using Vision
    print("\n" + "-"*60)
    print(f"🔍 TOC Extraction using Gemini Vision")
    print("-"*60)
    
    toc_result = extract_toc_with_vision(images, total_pages, pdf_filename)
    
    meta = toc_result.get("_meta", {})
    print(f"\n⏱  Time: {meta.get('elapsed_seconds', 'N/A')}s")
    print(f"📋 TOC Found: {toc_result.get('toc_found', False)}")
    print(f"📖 Volume Info: {toc_result.get('volume_info', 'Unknown')}")
    
    chapters = toc_result.get("chapters_in_this_volume", [])
    excluded = toc_result.get("chapters_not_in_this_volume", [])
    
    print(f"✅ Chapters in this volume: {len(chapters)}")
    print(f"❌ Chapters NOT in this volume: {len(excluded)}")
    
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
    toc_output_path = os.path.join(output_dir, "toc_vision_result.json")
    with open(toc_output_path, "w", encoding="utf-8") as f:
        json.dump(toc_result, f, ensure_ascii=False, indent=2)
    print(f"\n💾 TOC result saved to: {toc_output_path}")
    
    # Filter only "chapter" type entries
    actual_chapters = [ch for ch in chapters if ch.get("type") == "chapter"]
    
    if not actual_chapters:
        print("\n❌ No chapters detected. Cannot proceed.")
        return
    
    # Summarization test: Chapters 1-3
    print("\n" + "-"*60)
    print(f"📝 Summarization Test: Chapters 1-3 (using {SUMMARY_MODEL})")
    print("-"*60)
    
    summary_results = []
    test_chapters = actual_chapters[:3]
    
    for ch in test_chapters:
        chapter_number = ch.get("number", "?")
        chapter_title = ch.get("title", "Untitled")
        start_page = ch.get("content_start_page")
        end_page = ch.get("content_end_page")
        
        if start_page is None:
            print(f"\n⚠️  Skipping {chapter_number}: no page number")
            continue
        
        if end_page is None or end_page > total_pages:
            end_page = min(start_page + 30, total_pages)
        
        print(f"\n▶ Summarizing: {chapter_number} {chapter_title}")
        print(f"  Content Pages: {start_page} - {end_page}")
        
        # Extract chapter text (0-indexed)
        chapter_text = extract_text_from_pages(PDF_PATH, start_page - 1, end_page)
        print(f"  Extracted: {len(chapter_text)} characters")
        
        # Summarize
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
        
        # Rate limit
        print("  ⏳ Waiting 5s...")
        time.sleep(5)
    
    # Save summary results
    summary_output_path = os.path.join(output_dir, "summary_vision_result.json")
    with open(summary_output_path, "w", encoding="utf-8") as f:
        json.dump({
            "toc_model": TOC_MODEL,
            "toc_method": "vision",
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
    print(f"TOC Extraction: {TOC_MODEL} (Vision)")
    print(f"  - Method: Image-based (Vision API)")
    print(f"  - Time: {meta.get('elapsed_seconds')}s")
    print(f"  - Parts: {len([c for c in chapters if c.get('type') == 'part'])}")
    print(f"  - Chapters: {len(actual_chapters)}")
    
    print(f"\nSummarization: {SUMMARY_MODEL}")
    print(f"  - Chapters summarized: {len(summary_results)}")
    
    for s in summary_results:
        status = "✅" if "error" not in s.get("_meta", {}) else "❌"
        print(f"    {status} {s.get('title', '?')}: {len(s.get('keyConcepts', []))} concepts")
    
    print("\n✅ Done!")


if __name__ == "__main__":
    run_vision_test()
