import re
import os
import json
import pypdf
import fitz  # PyMuPDF
import base64
from typing import List, Dict, Any, Optional
from googleapiclient.http import MediaIoBaseDownload
from config import TOC_EXTRACTION_MODEL, TOC_IMAGE_DPI, TOC_SCAN_START_PAGE, TOC_SCAN_END_PAGE

class PdfProcessor:
    def download_file_to_temp(self, drive_service, file_id: str, file_name: str) -> str:
        """Downloads file content from Google Drive to a temporary file."""
        print(f"Starting download for {file_name} ({file_id})")
        request = drive_service.files().get_media(fileId=file_id)
        
        # Use a temp file path - simpler than NamedTemporaryFile for windows/unix compat in cloud run
        temp_path = f"/tmp/{file_id}.pdf"
        
        with open(temp_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                if status:
                    print(f"Download progress: {int(status.progress() * 100)}%")
                    
        print(f"Download complete: {temp_path}")
        return temp_path

    def extract_text_from_pdf_file(self, pdf_path: str) -> str:
        """Extracts text from PDF file path using pypdf (Pure Python)."""
        print(f"Extracting text from: {pdf_path}")
        reader = pypdf.PdfReader(pdf_path)
        text_parts = []
        
        # pypdf might be slower but safer from segfaults
        for i, page in enumerate(reader.pages):
            try:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            except Exception as e:
                print(f"Warning: Failed to extract text from page {i}: {e}")
                
        full_text = "".join(text_parts)
        
        # Clean OCR noise
        full_text = self.clean_extracted_text(full_text)
        
        print(f"Text extraction complete. Length: {len(full_text)} chars")
        return full_text

    def clean_extracted_text(self, text: str) -> str:
        """
        Removes OCR noise from extracted PDF text.
        - Repeated symbols (:::, !!!, ..., etc.)
        - Stray I/i/l characters that are OCR artifacts
        - Extra whitespace
        """
        # Remove sequences of 3+ repeated punctuation/symbols
        # Matches patterns like :::, !!!, ..., ;;;, ：：：, など
        text = re.sub(r'[：:；;！!．.…‐\-ｉｌI]{3,}', ' ', text)
        
        # Remove isolated single I/i/l surrounded by spaces or punctuation (OCR artifacts)
        text = re.sub(r'(?<=[：:；;！!．.\s])[IiｉｌＩ](?=[：:；;！!．.\s])', '', text)
        
        # Collapse multiple spaces/newlines into single space
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()

    def split_into_chapters(self, text: str) -> List[Dict[str, str]]:
        """
        Splits text into chapters/parts with improved pattern matching.
        Handles multiple formats: Chapter X, 第X章, Part X, PART X, 第X部, パートX, etc.
        Includes fallback logic when initial detection fails.
        """
        # Primary pattern - strict matching with separators
        # Matches: 第1部, 第一章, Chapter 1, Part I, etc.
        primary_pattern = r'(?:^|[\n\r]+)\s*(?:第\s*([0-9０-９一二三四五六七八九十百壱弐参]+)\s*[部章編節]|(?:Chapter|CHAPTER|Part|PART|パート)\s*([0-9０-９IVXivx]+))[　\s:：\-−—.．]*([^\n\r]{0,80})'
        
        matches = list(re.finditer(primary_pattern, text, re.IGNORECASE))
        print(f"Chapter detection (primary): Found {len(matches)} chapters/parts")
        for m in matches[:10]:  # Log first 10 matches
            print(f"  - Detected: {m.group(0).strip()[:60]}...")
        
        # Fallback: If only 0-1 chapters detected, try more lenient pattern
        if len(matches) <= 1:
            print("Warning: Only 0-1 chapters detected. Trying fallback pattern...")
            # More lenient pattern - just looks for 第X部 or 第X章 anywhere
            fallback_pattern = r'第\s*[0-9０-９一二三四五六七八九十壱弐参]+\s*[部章]'
            fallback_positions = [(m.start(), m.group()) for m in re.finditer(fallback_pattern, text)]
            print(f"  Fallback pattern found {len(fallback_positions)} matches")
            
            if len(fallback_positions) > len(matches):
                # Use fallback matches to split the text
                chapters = []
                for i, (pos, title) in enumerate(fallback_positions):
                    start = pos + len(title)
                    end = fallback_positions[i+1][0] if i + 1 < len(fallback_positions) else len(text)
                    content = text[start:end].strip()
                    # Get a better title by looking ahead a bit
                    title_extended = text[pos:min(pos+100, len(text))].split('\n')[0].strip()
                    if content:
                        chapters.append({"title": title_extended, "content": content})
                        print(f"  [Fallback] Chapter '{title_extended[:40]}...' has {len(content)} chars")
                
                if chapters:
                    return chapters
        
        # Process primary matches
        chapters = []
        if not matches:
            print("Warning: No chapters detected, treating entire text as one chapter")
            chapters.append({"title": "Full Text", "content": text})
            return chapters

        for i in range(len(matches)):
            start = matches[i].end()
            end = matches[i+1].start() if i + 1 < len(matches) else len(text)
            title = matches[i].group(0).strip()
            content = text[start:end].strip()
            if content:
                chapters.append({"title": title, "content": content})
                print(f"  Chapter '{title[:40]}...' has {len(content)} chars")
                
        return chapters

    def extract_toc_with_ai(self, pdf_path: str, gemini_service: Any, gcs_service: Any = None, job_id: str = None, override_end_page: int = None) -> Optional[Dict]:
        """
        Extracts TOC structure using Gemini Vision API.
        Converts first few pages to images and asks Gemini to parse content.
        
        Args:
            pdf_path: Path to the PDF file
            gemini_service: GeminiService instance
            gcs_service: Optional GcsService for error logging
            job_id: Optional job_id for error logging
            override_end_page: Optional override for TOC_SCAN_END_PAGE
        """
        scan_end = override_end_page if override_end_page else TOC_SCAN_END_PAGE
        print("Starting Vision-based TOC extraction...")
        print(f"  Config: Model={TOC_EXTRACTION_MODEL}, DPI={TOC_IMAGE_DPI}, Pages={TOC_SCAN_START_PAGE+1}-{scan_end}")
        
        error_details = None
        
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            filename = os.path.basename(pdf_path)
            
            # Use configurable scan range
            start_page = TOC_SCAN_START_PAGE
            end_page = min(scan_end, total_pages)
            
            images = []
            print(f"Converting pages {start_page+1}-{end_page} to images (DPI={TOC_IMAGE_DPI})...")
            
            for i in range(start_page, end_page):
                page = doc[i]
                pix = page.get_pixmap(dpi=TOC_IMAGE_DPI)
                img_bytes = pix.tobytes("png")
                
                images.append({
                    "mime_type": "image/png",
                    "data": base64.b64encode(img_bytes).decode("utf-8")
                })
            
            doc.close()
            
            prompt = f"""あなたは書籍の構造を分析する専門家です。

【PDF情報】
- 総ページ数: {total_pages}
- ファイル名: {filename}

添付画像から書籍の構成（部・章）を抽出してください。

【抽出対象】
1. まず目次ページを探す
2. 目次がない場合は、本文中の「第○部」「第○章」「Chapter X」「Part X」などの見出しを検出。さらに、その下の「第○節」「Section X」などの主要な小見出しも含めて、書籍全体の詳細な構造を抽出する
3. 「第一部」「第二部」のような部構成がある場合は必ずすべて含める（重要）
4. 各部/章/節のタイトルと開始ページ番号を正確に抽出

【抽出ルール】
- ページ番号が {total_pages} を超える章は除外（別巻の可能性）
- 「第1部」「第2部」「第3部」「第4部」のような部構成は必ずすべて検出する
- 出力は以下のJSON形式のみ

{{
  "volume_info": "上巻/下巻/全1巻",
  "has_toc_page": true,
  "chapters_in_this_volume": [
    {{
      "number": "第1部",
      "title": "部タイトル",
      "content_start_page": 25
    }}
  ]
}}
"""
            
            content = [prompt] + images
            
            # Use configurable model
            result = gemini_service.generate_content(
                content, 
                model_name=TOC_EXTRACTION_MODEL
            )
            
            if not result:
                error_details = {"stage": "api_call", "error": "Vision API returned None"}
                print("Vision TOC extraction returned None")
                self._save_toc_error(gcs_service, job_id, error_details)
                return None
                
            # Post-process: Ensure start pages are integers
            chapters = result.get("chapters_in_this_volume", [])
            for ch in chapters:
                if isinstance(ch.get("content_start_page"), str):
                    try:
                        ch["content_start_page"] = int(re.sub(r'\D', '', ch["content_start_page"]))
                    except:
                        ch["content_start_page"] = None
            
            # Sort chapters by content_start_page to ensure correct order
            chapters = [ch for ch in chapters if isinstance(ch.get("content_start_page"), int)]
            chapters.sort(key=lambda x: x.get("content_start_page", 0))
            
            # Calculate end pages based on sorted order
            for i, ch in enumerate(chapters):
                start = ch.get("content_start_page")
                chapter_end = total_pages
                if i + 1 < len(chapters):
                    next_start = chapters[i+1].get("content_start_page")
                    if isinstance(next_start, int) and next_start > start:
                        chapter_end = next_start - 1
                ch["content_end_page"] = chapter_end
            
            result["chapters_in_this_volume"] = chapters
            
            # Warning if only 0-1 chapters detected
            if len(chapters) <= 1:
                warning_msg = f"⚠️ Vision TOC extracted only {len(chapters)} chapter(s) - this may indicate extraction failure"
                print(warning_msg)
                # Save debug info even for non-error cases
                self._save_toc_error(gcs_service, job_id, {
                    "stage": "validation",
                    "warning": warning_msg,
                    "extracted_chapters": len(chapters),
                    "raw_result": result
                })
            else:
                print(f"Vision TOC extraction success: Found {len(chapters)} chapters (sorted by page)")
            
            return result
            
        except Exception as e:
            import traceback
            error_details = {
                "stage": "extraction",
                "error": str(e),
                "traceback": traceback.format_exc()
            }
            print(f"Error in extract_toc_with_ai: {e}")
            traceback.print_exc()
            self._save_toc_error(gcs_service, job_id, error_details)
            return None
    
    def _save_toc_error(self, gcs_service: Any, job_id: str, error_details: Dict):
        """Saves TOC extraction errors to GCS for debugging."""
        if not gcs_service or not job_id or not error_details:
            return
        try:
            blob = gcs_service.bucket.blob(f"jobs/{job_id}/errors.json")
            
            # Load existing errors if any
            existing = {}
            if blob.exists():
                existing = json.loads(blob.download_as_text())
            
            existing["toc_extraction"] = error_details
            
            blob.upload_from_string(
                json.dumps(existing, ensure_ascii=False, indent=2),
                content_type="application/json"
            )
            print(f"Saved TOC error details to jobs/{job_id}/errors.json")
        except Exception as e:
            print(f"Warning: Failed to save error details: {e}")

    def extract_chapters_from_toc(self, pdf_path: str, toc_data: Dict) -> List[Dict[str, str]]:
        """
        Extracts text for chapters based on TOC page ranges.
        Uses pypdf for text extraction.
        """
        print("Extracting chapters based on Vision TOC data...")
        reader = pypdf.PdfReader(pdf_path)
        total_pages = len(reader.pages)
        
        extracted_chapters = []
        chapters_list = toc_data.get("chapters_in_this_volume", [])
        
        for ch in chapters_list:
            title = ch.get("title", "Untitled")
            number = ch.get("number", "")
            full_title = f"{number} {title}".strip()
            
            start_page = ch.get("content_start_page")
            end_page = ch.get("content_end_page")
            
            if not isinstance(start_page, int) or not isinstance(end_page, int):
                print(f"Skipping {full_title}: Invalid page range {start_page}-{end_page}")
                continue
                
            # Convert 1-based page numbers to 0-based indices
            # pypdf is 0-indexed
            p_start = max(0, start_page - 1)
            p_end = min(total_pages, end_page) # end is exclusive in slicing logic usually, but here we iterate
            
            if p_start >= total_pages:
                continue
                
            chapter_text_parts = []
            for i in range(p_start, p_end):
                try:
                    text = reader.pages[i].extract_text()
                    if text:
                        chapter_text_parts.append(text)
                except Exception as e:
                    print(f"Warning extracting page {i+1}: {e}")
            
            full_text = "".join(chapter_text_parts)
            full_text = self.clean_extracted_text(full_text)
            
            if full_text:
                extracted_chapters.append({
                    "title": full_title,
                    "content": full_text
                })
                print(f"  Extracted '{full_title}' ({start_page}-{end_page}): {len(full_text)} chars")
                
        return extracted_chapters
