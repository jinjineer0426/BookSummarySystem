"""
Main Entry Point - Orchestrator for Book Summary System.

This module provides HTTP endpoints for:
1. process_book - Main orchestrator that downloads PDF, splits into chapters, and enqueues tasks.
2. process_chapter - Worker for individual chapter processing (from chapter_worker).
3. finalize_book - Aggregates chapter results (from finalizer).
4. process_gcs_inbox - Processes clips from Obsidian inbox.

Architecture:
- Orchestrator receives file_id, downloads PDF, splits into chapters.
- Each chapter is enqueued to Cloud Tasks with 60s delay between tasks.
- Workers process individual chapters and save results to GCS.
- Finalizer aggregates results and produces the final Markdown.
"""
import json
import os
import re
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

import functions_framework
import google.auth
import sys
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import (
    PROJECT_ID, BUCKET_NAME, OBSIDIAN_BUCKET_NAME,
    REGION, QUEUE_NAME, FUNCTION_URL, GEMINI_API_KEY
)
from services.pdf_processor import PdfProcessor
from services.gcs_service import GcsService
from services.gemini_service import GeminiService
from services.index_service import IndexService, ConceptNormalizer
from services.analysis_service import AnalysisService
from services.logging_service import JobLogger, get_logger, set_global_job_id
from services.job_tracker import JobTracker

# Import task handlers for routing
from tasks.chapter_worker import process_chapter
from tasks.finalizer import finalize_book

print("DEBUG: main.py - all modules imported successfully", file=sys.stderr)


# ... imports ...

@functions_framework.http
def main_http_entry(request):
    """
    Main HTTP entry point that routes requests based on path.
    Enables Single-Function deployment for multiple handlers.
    """
    path = request.path
    print(f"Routing request: method={request.method}, path={path}, args={request.args}")
    
    if path == "/" or path.endswith("/process_book"):
        return process_book(request)
    elif path.endswith("/prepare_book"):
        data = request.get_json(silent=True) or {}
        set_global_job_id(data.get('job_id'))
        return prepare_book(request)
    elif path.endswith("/process_chapter"):
        data = request.get_json(silent=True) or {}
        set_global_job_id(data.get('job_id'))
        return process_chapter(request)
    elif path.endswith("/finalize_book"):
        data = request.get_json(silent=True) or {}
        set_global_job_id(data.get('job_id'))
        return finalize_book(request)
    elif path.endswith("/process_gcs_inbox"):
        return process_gcs_inbox(request)
    elif path.endswith("/analyze_concepts"):
        return analyze_concepts(request)
    else:
        return json.dumps({"error": f"Path {path} not found"}), 404

def _is_valid_drive_file_id(file_id: str) -> bool:
    """
    Validates Google Drive File ID format.
    Typically ~33-44 characters, alphanumeric with underscores and hyphens.
    """
    if not file_id or len(file_id) < 20:
        return False
    if file_id.startswith("test_"):
        return False
    # Google Drive IDs usually match this pattern
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', file_id))

def _create_cloud_task(
    gcs: GcsService,
    queue_path: str,
    handler_url: str,
    payload: dict,
    delay_seconds: int = 0
):
    """Creates a Cloud Task to call the specified handler."""
    from google.cloud import tasks_v2
    from google.protobuf import timestamp_pb2
    import datetime as dt
    
    client = tasks_v2.CloudTasksClient()
    
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": handler_url,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload).encode(),
            "oidc_token": {
                "service_account_email": f"{PROJECT_ID}@appspot.gserviceaccount.com"
            }
        }
    }
    
    if delay_seconds > 0:
        d = dt.datetime.utcnow() + dt.timedelta(seconds=delay_seconds)
        timestamp = timestamp_pb2.Timestamp()
        timestamp.FromDatetime(d)
        task["schedule_time"] = timestamp
    
    response = client.create_task(parent=queue_path, task=task)
    get_logger().debug(f"Created task: {response.name}")
    return response.name


@functions_framework.http
def process_book(request):
    """
    Cloud Function Entry Point - Initial Receiver.
    
    1. Receives file_id and category from GAS.
    2. Generates job_id.
    3. Enqueues a 'prepare_book' task to do the heavy lifting.
    4. Returns immediately to GAS.
    """
    from services.logging_service import StructuredLogger
    
    logger = StructuredLogger()
    
    try:
        request_json = request.get_json(silent=True)
        if not request_json or 'file_id' not in request_json:
            logger.error("Invalid request", error="file_id required")
            return json.dumps({'error': 'file_id required'}), 400
        
        file_id = request_json['file_id']
        category = request_json.get('category', 'Business')
        
        if not _is_valid_drive_file_id(file_id):
            logger.error("Invalid file_id format", file_id=file_id)
            return json.dumps({'error': f'Invalid file_id format: {file_id}'}), 400
        job_id = str(uuid.uuid4())
        
        set_global_job_id(job_id)
        logger = JobLogger(job_id)
        
        logger.info("New book processing request", 
                   file_id=file_id, category=category)
        
        # Enqueue preparation task
        gcs = GcsService()
        queue_path = f"projects/{PROJECT_ID}/locations/{REGION}/queues/{QUEUE_NAME}"
        prepare_url = f"{FUNCTION_URL}/prepare_book"
        
        _create_cloud_task(
            gcs, queue_path, prepare_url,
            {"file_id": file_id, "category": category, "job_id": job_id}
        )
        
        logger.info("Book processing accepted", job_id=job_id, status="queued")
        
        return json.dumps({
            'status': 'accepted',
            'job_id': job_id,
            'message': 'Book processing started in background'
        }), 200
        
    except Exception as e:
        logger.error("Error in process_book", error=str(e))
        return json.dumps({'error': str(e)}), 500

@functions_framework.http
def prepare_book(request):
    """
    Cloud Task Handler - Heavy Lifting.
    1. Downloads PDF.
    2. TOC Extraction (Vision AI) & Regex Splitting.
    3. Saves chapters & Metadata.
    4. Enqueues individual chapter tasks.
    """
    from services.logging_service import JobLogger
    from services.job_tracker import JobTracker
    
    job_id = None
    logger = None
    
    try:
        data = request.get_json(silent=True)
        file_id = data.get('file_id')
        category = data.get('category')
        job_id = data.get('job_id')
        
        # Initialize structured logger and job tracker
        set_global_job_id(job_id)
        logger = JobLogger(job_id)
        logger.log_stage("prepare_book", "started", file_id=file_id, category=category)
        
        gcs = GcsService()
        tracker = JobTracker(gcs, job_id)
        tracker.update_status("processing", {"stage": "initialization"})
        
        pdf_processor = PdfProcessor()
        gemini = GeminiService()
        
        creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/drive.readonly'])
        drive_service = build('drive', 'v3', credentials=creds)
        
        try:
            file_metadata = drive_service.files().get(fileId=file_id).execute()
        except HttpError as e:
            if e.resp.status == 404:
                error_msg = f"File not found in Google Drive: {file_id}"
                logger.error(error_msg)
                tracker.mark_failed(error_msg, "file_not_found")
                # Return 200 to stop Cloud Tasks from retrying a permanent failure
                return json.dumps({'error': error_msg}), 200
            raise
            
        file_name = file_metadata.get('name', 'Untitled')
        if file_name.lower().endswith('.pdf'):
            file_name = file_name[:-4]
        
        logger.log_stage("download", "started", file_name=file_name)
        pdf_path = pdf_processor.download_file_to_temp(drive_service, file_id, file_name)
        logger.log_stage("download", "completed")
        
        try:
            # 1. Extraction (TOC Priority with Retry)
            logger.log_stage("toc_extraction", "attempt_1")
            tracker.update_status("processing", {"stage": "toc_extraction"})
            
            toc_data = pdf_processor.extract_toc_with_ai(pdf_path, gemini, gcs, job_id)
            toc_chapters = []
            if toc_data and toc_data.get("chapters_in_this_volume"):
                toc_chapters = pdf_processor.extract_chapters_from_toc(pdf_path, toc_data)
            
            # Retry TOC if less than 2 chapters found
            if len(toc_chapters) < 2:
                logger.log_stage("toc_extraction", "retry", chapters_found=len(toc_chapters))
                toc_data_retry = pdf_processor.extract_toc_with_ai(pdf_path, gemini, gcs, job_id, override_end_page=50)
                if toc_data_retry and toc_data_retry.get("chapters_in_this_volume"):
                    toc_chapters_retry = pdf_processor.extract_chapters_from_toc(pdf_path, toc_data_retry)
                    if len(toc_chapters_retry) >= 2:
                        logger.log_stage("toc_extraction", "retry_success", chapters_found=len(toc_chapters_retry))
                        toc_chapters = toc_chapters_retry
            
            # 2. Decision Logic
            if len(toc_chapters) >= 2:
                logger.log_stage("chapter_extraction", "using_toc", chapter_count=len(toc_chapters))
                chapters = toc_chapters
            else:
                # TOC failed or insufficient structure. Try Regex.
                logger.log_stage("chapter_extraction", "fallback_regex")
                text = pdf_processor.extract_text_from_pdf_file(pdf_path)
                regex_chapters = pdf_processor.split_into_chapters(text)
                
                if len(regex_chapters) > 100:
                    error_msg = f"Regex runaway detected: {len(regex_chapters)} potential chapters found (limit 100). Aborting."
                    logger.log_error("chapter_extraction", error_msg, chapter_count=len(regex_chapters))
                    tracker.mark_failed(error_msg, "regex_runaway")
                    pdf_processor._save_toc_error(gcs, job_id, {"stage": "regex", "error": error_msg})
                    raise Exception(error_msg)
                
                if len(regex_chapters) >= 2:
                    logger.log_stage("chapter_extraction", "using_regex", chapter_count=len(regex_chapters))
                    chapters = regex_chapters
                else:
                    # Final fallback: use whatever TOC found (even 1 chapter), or full text
                    if len(toc_chapters) > 0:
                        logger.log_stage("chapter_extraction", "fallback_single_toc")
                        chapters = toc_chapters
                    else:
                        logger.log_stage("chapter_extraction", "fallback_full_text")
                        chapters = [{"title": "Full Text", "content": text}]
            
            # 2. Setup Job in GCS
            master_concepts = list(gcs.get_concepts().get("concepts", {}).keys())
            
            job_metadata = {
                "job_id": job_id, "file_id": file_id, "book_title": file_name,
                "category": category, "total_chapters": len(chapters),
                "completed_chapters": [], "status": "processing",
                "created_at": datetime.now().isoformat()
            }
            if len(chapters) == 1:
                job_metadata["detection_warning"] = "only_1_chapter_detected"
            
            gcs.bucket.blob(f"jobs/{job_id}/metadata.json").upload_from_string(
                json.dumps(job_metadata, ensure_ascii=False, indent=2),
                content_type="application/json"
            )
            gcs.bucket.blob(f"jobs/{job_id}/input_chapters.json").upload_from_string(
                json.dumps(chapters, ensure_ascii=False),
                content_type="application/json"
            )
            
            # 3. Enqueue Workers
            queue_path = f"projects/{PROJECT_ID}/locations/{REGION}/queues/{QUEUE_NAME}"
            chapter_url = f"{FUNCTION_URL}/process_chapter"
            final_url = f"{FUNCTION_URL}/finalize_book"
            
            for i, chapter in enumerate(chapters):
                _create_cloud_task(gcs, queue_path, chapter_url, {
                    "job_id": job_id, "chapter_number": i,
                    "book_title": file_name, "existing_concepts": master_concepts[:100]
                }, delay_seconds=i * 60)
            
            _create_cloud_task(gcs, queue_path, final_url, {"job_id": job_id}, 
                               delay_seconds=len(chapters) * 60 + 120)
            
            logger.log_stage("prepare_book", "completed", chapter_count=len(chapters))
            logger.log_metric("chapters_enqueued", len(chapters))
            tracker.mark_queued(len(chapters))
            return "OK", 200
            
        finally:
            if pdf_path and os.path.exists(pdf_path):
                os.remove(pdf_path)
                logger.logger.debug("Cleaned up temp PDF file")
    except Exception as e:
        if logger:
            logger.log_error("prepare_book", str(e))
        if job_id:
            try:
                tracker = JobTracker(GcsService(), job_id)
                tracker.mark_failed(str(e), "prepare_book")
            except:
                pass
        import traceback
        traceback.print_exc()
        return f"Error: {e}", 500


def _process_synchronously(
    gcs: GcsService,
    job_id: str,
    file_id: str,
    file_name: str,
    category: str,
    chapters: list,
    master_concepts: list
) -> tuple:
    """Fallback: Process all chapters synchronously (legacy mode)."""
    import time
    from services.gemini_service import GeminiService
    from services.index_service import IndexService, ConceptNormalizer
    
    gemini = GeminiService()
    index_service = IndexService(gcs, gemini)
    concept_normalizer = ConceptNormalizer(gcs, gemini)
    
    chapter_summaries = []
    all_concepts = set()
    
    BATCH_SIZE = 2
    batches = [chapters[i:i + BATCH_SIZE] for i in range(0, len(chapters), BATCH_SIZE)]
    
    for batch_idx, batch in enumerate(batches):
        print(f"Processing batch {batch_idx+1}/{len(batches)}...")
        
        for ch in batch:
            content = ch['content'][:50000]
            prompt = f"""
            Analyze this chapter and provide a summary in Japanese.
            
            Book Title: {file_name}
            Chapter: {ch['title']}
            Existing Concepts: {", ".join(master_concepts[:100])}
            
            Content:
            {content}
            
            Output JSON:
            {{"title": "title", "summary": "- Point 1\\n- Point 2", "keyConcepts": ["C1", "C2"]}}
            """
            
            result = gemini.generate_content(prompt)
            if result:
                chapter_summaries.append(result)
                all_concepts.update(result.get('keyConcepts', []))
            else:
                chapter_summaries.append({
                    "title": ch['title'],
                    "summary": "(Failed)",
                    "keyConcepts": []
                })
        
        if batch_idx < len(batches) - 1:
            print("Waiting 30s...")
            time.sleep(30)
    
    # Book-level summary
    book_result = gemini.generate_content(f"""
    Create a book summary in Japanese from these chapter summaries.
    
    Book: {file_name}
    Chapters: {json.dumps(chapter_summaries, ensure_ascii=False)[:5000]}
    
    Output JSON:
    {{"title": "title", "author": "author", "suggestedSubfolder": "cat", "allKeyConcepts": ["c1"], "summary": "summary"}}
    """)
    
    if not book_result:
        book_result = {
            "title": file_name,
            "author": "Unknown",
            "suggestedSubfolder": "Other",
            "allKeyConcepts": list(all_concepts)[:10],
            "summary": "Generation failed."
        }
    
    # Normalize and save
    normalized_concepts = concept_normalizer.normalize(
        book_result.get("allKeyConcepts", []),
        file_name
    )
    
    final_data = {
        **book_result,
        "allKeyConcepts": [c["normalized"] for c in normalized_concepts],
        "chapters": chapter_summaries
    }
    
    # Format markdown
    md_content = _format_markdown(final_data, file_id)
    clean_title = re.sub(r'[\\/:*?"<>|]', '_', final_data["title"])
    md_path = f"01_Reading/{clean_title}.md"
    gcs_uri = gcs.write_to_obsidian_vault(md_path, md_content)
    
    # Update indexes
    index_service.update_books_index(
        final_data["title"],
        final_data["author"],
        final_data["suggestedSubfolder"]
    )
    index_service.update_concepts_index(
        final_data["allKeyConcepts"],
        final_data["title"]
    )
    
    return json.dumps({
        'status': 'success',
        'gcs_uri': gcs_uri,
        'metadata': {
            'title': final_data["title"],
            'author': final_data["author"]
        }
    }), 200


def _format_markdown(data: Dict[str, Any], file_id: str) -> str:
    """Format summary data as Markdown."""
    today = datetime.now().strftime('%Y-%m-%d')
    pdf_url = f"https://drive.google.com/file/d/{file_id}/view"
    concepts_links = " ".join([f"[[{c}]]" for c in data.get('allKeyConcepts', [])])
    
    md = f"""---
title: "{data.get('title')}"
author: "{data.get('author')}"
category: ["{data.get('suggestedSubfolder')}", "Business"]
processed_date: {today}
concepts: {json.dumps(data.get('allKeyConcepts', []), ensure_ascii=False)}
source_url: "{pdf_url}"
---

# {data.get('title')}

## Metadata
- **Author**: {data.get('author')}
- **Source**: [Original PDF]({pdf_url})
- **Topics**: {concepts_links}

## Summary
{data.get('summary')}

## Chapter Summaries
"""
    for ch in data.get('chapters', []):
        concepts = " ".join([f"[[{c}]]" for c in ch.get('keyConcepts', [])])
        md += f"\n### {ch.get('title')}\n{ch.get('summary', '(No summary)')}\n\n**Key Concepts**: {concepts}\n"
    
    return md


# === Clip Processing (unchanged from original) ===

@functions_framework.http
def process_gcs_inbox(request):
    """
    Scans 00_Inbox in GCS and processes new clips.
    """
    try:
        gcs = GcsService()
        gemini = GeminiService()
        concept_normalizer = ConceptNormalizer(gcs, gemini)
        
        blobs = list(gcs.obsidian_bucket.list_blobs(prefix="00_Inbox/"))
        
        processed_count = 0
        
        for blob in blobs:
            if not blob.name.endswith(".md"):
                continue
                
            content = blob.download_as_text()
            filename = os.path.basename(blob.name)
            
            # Check if already processed
            if "## Auto-Generated Links" in content:
                continue
            
            # Process clip
            enhanced, concepts = _process_clip(gemini, concept_normalizer, content, filename)
            
            if enhanced:
                blob.upload_from_string(enhanced.encode('utf-8'), content_type='text/markdown')
                print(f"Processed: {blob.name}")
                
                # Update index
                index_service = IndexService(gcs, gemini)
                index_service.update_concepts_index(concepts, filename.replace(".md", ""))
                
                processed_count += 1
                
        return json.dumps({"status": "success", "processed": processed_count}), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return json.dumps({"error": str(e)}), 500


def _process_clip(gemini: GeminiService, normalizer: ConceptNormalizer, content: str, filename: str):
    """Process a single clip content."""
    title = filename.replace(".md", "")
    
    prompt = f"""
    Analyze this web article clip and extract key concepts.
    
    Title: {title}
    Content: {content[:10000]}
    
    Output JSON:
    {{"summary": "3-line summary in Japanese", "concepts": ["C1", "C2"], "category": "Business"}}
    """
    
    try:
        data = gemini.generate_content(prompt)
        if not data:
            return None, []
        
        normalized = normalizer.normalize(data.get("concepts", []), title)
        concept_names = [c["normalized"] for c in normalized]
        
        links = f"""

---

## Auto-Generated Links

### Summary
{data.get("summary", "")}

### Key Concepts
"""
        for c in concept_names:
            links += f"- [[{c}]]\n"
        
        return content + links, concept_names
        
    except Exception as e:
        print(f"Error processing clip {filename}: {e}")
        return None, []


@functions_framework.http
def analyze_concepts(request):
    """
    Analyzes the Concepts Index and returns a report.
    
    Triggered by GAS weekly job.
    Returns: JSON report with hub concepts, duplicates, etc.
    """
    try:
        gcs = GcsService()
        analyzer = AnalysisService(gcs)
        
        result = analyzer.publish_weekly_report()
        
        return json.dumps(result, ensure_ascii=False), 200, {"Content-Type": "application/json; charset=utf-8"}
        
    except Exception as e:
        print(f"Error in analyze_concepts: {e}")
        import traceback
        traceback.print_exc()
        return json.dumps({"status": "error", "message": str(e)}), 500


# Entry point alias for Cloud Functions
router = main_http_entry
