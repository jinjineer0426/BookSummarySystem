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
        Splits text into chapters/parts.
        Handles multiple formats: Chapter X, 第X章, Part X, PART X, 第X部, パートX, etc.
        """
        # Extended pattern for various chapter/part formats
        # Improved regex to prevent false positives like "第一部では..." by enforcing a separator after finding the unit
        chapter_pattern = r'(?:^|\n)\s*(?:Chapter|CHAPTER|第|Part|PART|パート|part)\s*(\d+|[一二三四五六七八九十]+|[IVXivx]+)(?:(?:章|部)(?=[\s　:：.]|$)|(?:\s*[:：.]|\s*\n|\s+))[^\n]*'
        matches = list(re.finditer(chapter_pattern, text, re.IGNORECASE))
        
        print(f"Chapter detection: Found {len(matches)} chapters/parts")
        for m in matches[:10]:  # Log first 10 matches
            print(f"  - Detected: {m.group(0).strip()[:50]}...")
        
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
                print(f"  Chapter '{title[:30]}...' has {len(content)} chars")
                
        return chapters

    def extract_toc_with_ai(self, pdf_path: str, gemini_service: Any, gcs_service: Any = None, job_id: str = None) -> Optional[Dict]:
        """
        Extracts TOC structure using Gemini Vision API.
        Converts first few pages to images and asks Gemini to parse content.
        
        Args:
            pdf_path: Path to the PDF file
            gemini_service: GeminiService instance
            gcs_service: Optional GcsService for error logging
            job_id: Optional job_id for error logging
        """
        print("Starting Vision-based TOC extraction...")
        print(f"  Config: Model={TOC_EXTRACTION_MODEL}, DPI={TOC_IMAGE_DPI}, Pages={TOC_SCAN_START_PAGE+1}-{TOC_SCAN_END_PAGE}")
        
        error_details = None
        
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            filename = os.path.basename(pdf_path)
            
            # Use configurable scan range
            start_page = TOC_SCAN_START_PAGE
            end_page = min(TOC_SCAN_END_PAGE, total_pages)
            
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
            
            prompt = f"""あなたは書籍の目次を画像から読み取る専門家です。

【PDF情報】
- 総ページ数: {total_pages}
- ファイル名: {filename}

添付画像から目次（章タイトルと開始ページ番号）を抽出してください。

【抽出ルール】
1. 「第○章」「Chapter X」などの構造を維持
2. ページ番号は行の右端にある数字（開始ページ）
3. ページ番号が {total_pages} を超える章は除外（別巻の可能性）
4. 出力は以下のJSON形式のみ

{{
  "volume_info": "上巻/下巻/全1巻",
  "chapters_in_this_volume": [
    {{
      "number": "第1章",
      "title": "章タイトル",
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
