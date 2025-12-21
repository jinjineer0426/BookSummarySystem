import re
import os
import json
import pypdf
import fitz  # PyMuPDF
import base64
from typing import List, Dict, Any, Optional
from googleapiclient.http import MediaIoBaseDownload
from config import TOC_EXTRACTION_MODEL, TOC_IMAGE_DPI, TOC_SCAN_START_PAGE, TOC_SCAN_END_PAGE
from services.logging_service import get_logger

class PdfProcessor:
    def download_file_to_temp(self, drive_service, file_id: str, file_name: str) -> str:
        """Downloads file content from Google Drive to a temporary file."""
        logger = get_logger()
        logger.info(f"Starting download for {file_name} ({file_id})")
        request = drive_service.files().get_media(fileId=file_id)
        
        # Use a temp file path - simpler than NamedTemporaryFile for windows/unix compat in cloud run
        temp_path = f"/tmp/{file_id}.pdf"
        
        with open(temp_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                if status:
                    logger.debug(f"Download progress: {int(status.progress() * 100)}%")
                    
        logger.info(f"Download complete: {temp_path}")
        return temp_path

    def extract_text_from_pdf_file(self, pdf_path: str) -> str:
        """Extracts text from PDF file path using pypdf (Pure Python)."""
        logger = get_logger()
        logger.info(f"Extracting text from: {pdf_path}")
        reader = pypdf.PdfReader(pdf_path)
        text_parts = []
        
        # pypdf might be slower but safer from segfaults
        for i, page in enumerate(reader.pages):
            try:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            except Exception as e:
                logger.warning(f"Failed to extract text from page {i}: {e}")
                
        full_text = "".join(text_parts)
        
        # Clean OCR noise
        full_text = self.clean_extracted_text(full_text)
        
        logger.info(f"Text extraction complete. Length: {len(full_text)} chars")
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
        logger = get_logger()
        logger.debug(f"Chapter detection (primary): Found {len(matches)} chapters/parts")
        for m in matches[:10]:  # Log first 10 matches
            logger.debug(f"  - Detected: {m.group(0).strip()[:60]}...")
        
        # Fallback: If only 0-1 chapters detected, try more lenient pattern
        if len(matches) <= 1:
            logger.warning("Only 0-1 chapters detected. Trying fallback pattern...")
            # More lenient pattern - just looks for 第X部 or 第X章 anywhere
            fallback_pattern = r'第\s*[0-9０-９一二三四五六七八九十壱弐参]+\s*[部章]'
            fallback_positions = [(m.start(), m.group()) for m in re.finditer(fallback_pattern, text)]
            logger.debug(f"  Fallback pattern found {len(fallback_positions)} matches")
            
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
                        logger.debug(f"  [Fallback] Chapter '{title_extended[:40]}...' has {len(content)} chars")
                
                if chapters:
                    return chapters
        
        # Process primary matches
        chapters = []
        if not matches:
            logger.warning("No chapters detected, treating entire text as one chapter")
            chapters.append({"title": "Full Text", "content": text})
            return chapters

        for i in range(len(matches)):
            start = matches[i].end()
            end = matches[i+1].start() if i + 1 < len(matches) else len(text)
            title = matches[i].group(0).strip()
            content = text[start:end].strip()
            if content:
                chapters.append({"title": title, "content": content})
                logger.debug(f"  Chapter '{title[:40]}...' has {len(content)} chars")
        
        # Runaway detection and deduplication
        if len(chapters) > 30:
            logger.warning(f"Potentially too many chapters detected: {len(chapters)}")
            unique_ch_nums = set(self._normalize_chapter_number(ch['title']) for ch in chapters)
            unique_ch_nums.discard(None)
            
            duplication_rate = 1 - (len(unique_ch_nums) / len(chapters)) if chapters else 0
            logger.debug(f"Unique chapter numbers: {len(unique_ch_nums)}, Duplication rate: {duplication_rate:.2%}")
            
            if duplication_rate > 0.5:
                logger.warning(f"High duplication detected ({duplication_rate:.2%}). Applying deduplication...")
                chapters = self._deduplicate_chapters(chapters)
                logger.info(f"After deduplication: {len(chapters)} chapters")
                
        return chapters
    
    def _normalize_chapter_number(self, title: str) -> Optional[str]:
        """
        章番号部分のみを正規化して抽出。
        OCRノイズ（〃、″など）を除去し、全角→半角変換。
        """
        import unicodedata
        
        # 全角→半角、OCRノイズ除去
        title = unicodedata.normalize('NFKC', title)
        title = re.sub(r'[〃″′"｜]', '', title)
        
        # 第X章、第X部などを抽出
        m = re.search(r'第\s*(\d+)\s*[章部編節]', title)
        if m:
            return f"第{m.group(1)}章"
        
        # Chapter X, Part X などを抽出
        m = re.search(r'(?:Chapter|Part|PART|パート)\s*(\d+)', title, re.IGNORECASE)
        if m:
            return f"Chapter{m.group(1)}"
            
        return None
    
    def _deduplicate_chapters(self, chapters: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        同一章の重複を除去し、最も長いコンテンツを採用。
        章番号（第X章）のみで判定し、OCRノイズを無視。
        """
        logger = get_logger()
        seen = {}  # chapter_number -> (index, content_length, chapter_dict)
        result = []
        
        for ch in chapters:
            ch_num = self._normalize_chapter_number(ch['title'])
            if ch_num:
                if ch_num in seen:
                    # 既存より長いコンテンツなら置換
                    old_idx, old_len, old_ch = seen[ch_num]
                    if len(ch['content']) > old_len:
                        result[old_idx] = ch
                        seen[ch_num] = (old_idx, len(ch['content']), ch)
                        logger.debug(f"  Replaced duplicate {ch_num}: {old_len} -> {len(ch['content'])} chars")
                else:
                    seen[ch_num] = (len(result), len(ch['content']), ch)
                    result.append(ch)
            else:
                # 章番号が抽出できないものはそのまま追加
                result.append(ch)
                
        return result


    def extract_toc_with_ai(self, pdf_path: str, gemini_service: Any, gcs_service: Any = None, job_id: str = None, override_end_page: Optional[int] = None) -> Optional[Dict]:
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
        logger = get_logger()
        logger.info("Starting Vision-based TOC extraction...")
        logger.info(f"  Config: Model={TOC_EXTRACTION_MODEL}, DPI={TOC_IMAGE_DPI}, Pages={TOC_SCAN_START_PAGE+1}-{scan_end}")
        
        error_details = None
        
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            filename = os.path.basename(pdf_path)
            
            # Use configurable scan range
            start_page = TOC_SCAN_START_PAGE
            end_page = min(scan_end, total_pages)
            
            images = []
            logger.info(f"Converting pages {start_page+1}-{end_page} to images (DPI={TOC_IMAGE_DPI})...")
            
            for i in range(start_page, end_page):
                page = doc[i]
                pix = page.get_pixmap(dpi=TOC_IMAGE_DPI)
                img_bytes = pix.tobytes("png")
                
                images.append({
                    "mime_type": "image/png",
                    "data": base64.b64encode(img_bytes).decode("utf-8")
                })
            
            doc.close()
            
            prompt = f"""あなたは日本語書籍の目次（Table of Contents）を解析する専門家です。

【タスク】
添付画像から**目次ページを特定**し、そこに記載された章立て構造を抽出してください。

【PDF情報】
- 総ページ数: {total_pages}
- ファイル名: {filename}
- スキャン範囲: 1〜{scan_end}ページ目

【重要な区別】
⚠️ 以下は目次ではありません。無視してください：
- 各ページの**ヘッダー/フッター**に繰り返し表示される章タイトル
- 本文中に現れる「第X章で述べたように…」のような**参照テキスト**
- 奥付、著者紹介、索引のページ

✅ 目次ページの特徴：
- 複数の章/節がリスト形式で並んでいる
- 各項目に対応するページ番号が記載されている
- 通常、書籍の冒頭（3〜15ページ目あたり）に配置

【抽出ルール】
1. **目次ページが見つかった場合**:
   - 「部」「章」「節」などの階層構造をフラットなリストとして抽出
   - ページ番号が {total_pages} を超える項目は除外
   - 同じ章番号が複数回現れる場合は、最初の1つのみ採用

2. **目次ページが見つからない場合**:
   - `has_toc_page: false` を設定
   - `chapters_in_this_volume: []` を返す（空配列）

3. **出力形式**（JSON以外の説明は不要）:

{{
  "volume_info": "上巻/下巻/全1巻",
  "has_toc_page": true,
  "toc_page_numbers": [4, 5],
  "chapters_in_this_volume": [
    {{
      "number": "第1章",
      "title": "脳科学と時間管理",
      "content_start_page": 15
    }},
    {{
      "number": "第2章",
      "title": "朝のルーティン",
      "content_start_page": 45
    }}
  ]
}}

【補足】
- 辞書型書籍（例：「武器になる哲学」）の場合、50個以上のキーコンセプトが並ぶことがあります。これらも個別の「章」として抽出してください。
- 章番号のフォーマット揺れ（第1章/第一章/Chapter 1）は気にせず、見つかったまま記録してください。
"""
            
            content = [prompt] + images
            
            # Use configurable model
            result = gemini_service.generate_content(
                content, 
                model_name=TOC_EXTRACTION_MODEL
            )
            
            if not result:
                error_details = {"stage": "api_call", "error": "Vision API returned None"}
                logger.warning("Vision TOC extraction returned None")
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
            
            # ALWAYS Save debug info for analysis
            logger.info(f"Vision TOC extraction success: Found {len(chapters)} chapters. Saving debug info...")
            self._save_toc_error(gcs_service, job_id, {
                "stage": "extraction_result",
                "extracted_chapters_count": len(chapters),
                "raw_result": result
            })
            
            return result
            
        except Exception as e:
            import traceback
            error_details = {
                "stage": "extraction",
                "error": str(e),
                "traceback": traceback.format_exc()
            }
            logger.error(f"Error in extract_toc_with_ai: {e}")
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
            get_logger().debug(f"Saved TOC error details to jobs/{job_id}/errors.json")
        except Exception as e:
            get_logger().warning(f"Failed to save error details: {e}")

    def extract_chapters_from_toc(self, pdf_path: str, toc_data: Dict) -> List[Dict[str, str]]:
        """Extracts text for chapters based on TOC page ranges."""
        logger = get_logger()
        logger.info("Extracting chapters based on Vision TOC data...")
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
                logger.warning(f"Skipping {full_title}: Invalid page range {start_page}-{end_page}")
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
                    logger.warning(f"Error extracting page {i+1}: {e}")
            
            full_text = "".join(chapter_text_parts)
            full_text = self.clean_extracted_text(full_text)
            
            if full_text:
                extracted_chapters.append({
                    "title": full_title,
                    "content": full_text
                })
                logger.debug(f"  Extracted '{full_title}' ({start_page}-{end_page}): {len(full_text)} chars")
                
        return extracted_chapters
