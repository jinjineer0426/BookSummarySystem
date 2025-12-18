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
from googleapiclient.discovery import build

from config import (
    PROJECT_ID, BUCKET_NAME, OBSIDIAN_BUCKET_NAME,
    REGION, QUEUE_NAME, FUNCTION_URL, GEMINI_API_KEY
)
from services.pdf_processor import PdfProcessor
from services.gcs_service import GcsService
from services.gemini_service import GeminiService
from services.index_service import IndexService, ConceptNormalizer
from services.analysis_service import AnalysisService

# Import task handlers for routing
from tasks.chapter_worker import process_chapter
from tasks.finalizer import finalize_book


# ... imports ...

@functions_framework.http
def main_http_entry(request):
    """
    Main HTTP entry point that routes requests based on path.
    Enables Single-Function deployment for multiple handlers.
    """
    path = request.path
    print(f"Routing request for: {path}")
    
    if path == "/" or path.endswith("/process_book"):
        return process_book(request)
    elif path.endswith("/process_chapter"):
        return process_chapter(request)
    elif path.endswith("/finalize_book"):
        return finalize_book(request)
    elif path.endswith("/process_gcs_inbox"):
        return process_gcs_inbox(request)
    elif path.endswith("/analyze_concepts"):
        return analyze_concepts(request)
    else:
        return json.dumps({"error": f"Path {path} not found"}), 404

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
    print(f"Created task: {response.name}")
    return response.name


@functions_framework.http
def process_book(request):
    """
    Cloud Function Entry Point - Orchestrator.
    
    Triggered by HTTP request from GAS.
    1. Downloads PDF from Google Drive.
    2. Extracts text and splits into chapters.
    3. Saves chapters to GCS.
    4. Enqueues Cloud Tasks for each chapter (60s apart).
    5. Schedules finalizer task after all chapters.
    
    Returns: JSON with job_id for tracking.
    """
    try:
        request_json = request.get_json(silent=True)
        
        if not request_json or 'file_id' not in request_json:
            return json.dumps({'error': 'file_id required'}), 400
        
        file_id = request_json['file_id']
        category = request_json.get('category', 'Business')
        use_cloud_tasks = request_json.get('use_cloud_tasks', True)
        
        print(f"Processing file: {file_id}, Category: {category}, CloudTasks: {use_cloud_tasks}")
        
        # Generate job ID
        job_id = str(uuid.uuid4())
        print(f"Job ID: {job_id}")
        
        # Initialize services
        gcs = GcsService()
        pdf_processor = PdfProcessor()
        gemini = GeminiService()
        
        # Drive API Setup (Only for Reading PDF)
        creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/drive.readonly'])
        drive_service = build('drive', 'v3', credentials=creds)
        
        # 1. Get file metadata
        file_metadata = drive_service.files().get(fileId=file_id).execute()
        file_name = file_metadata.get('name', 'Untitled')
        if file_name.lower().endswith('.pdf'):
            file_name = file_name[:-4]
        
        # 2. Download and process PDF
        pdf_path = None
        try:
            pdf_path = pdf_processor.download_file_to_temp(drive_service, file_id, file_name)
            
            # Try Vision-based TOC extraction first
            print("Attempting Vision-based TOC extraction...")
            toc_data = pdf_processor.extract_toc_with_ai(pdf_path, gemini, gcs, job_id)
            
            chapters = []
            if toc_data and toc_data.get("chapters_in_this_volume"):
                print("Using TOC-based chapter extraction...")
                chapters = pdf_processor.extract_chapters_from_toc(pdf_path, toc_data)
            
            # Fallback to Regex if TOC failed or returned no chapters
            if not chapters:
                print("Fallback to Regex-based splitting...")
                text = pdf_processor.extract_text_from_pdf_file(pdf_path)
                chapters = pdf_processor.split_into_chapters(text)
                
        finally:
            if pdf_path and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                    print(f"Cleaned up temp file: {pdf_path}")
                except Exception as e:
                    print(f"Warning: Failed to delete temp file: {e}")
        
        # 3. Get existing concepts for context
        master_concepts = list(gcs.get_concepts().get("concepts", {}).keys())
        
        # 4. Save job metadata and chapter inputs to GCS
        job_metadata = {
            "job_id": job_id,
            "file_id": file_id,
            "book_title": file_name,
            "category": category,
            "total_chapters": len(chapters),
            "completed_chapters": [],
            "status": "processing",
            "created_at": datetime.now().isoformat()
        }
        
        metadata_blob = gcs.bucket.blob(f"jobs/{job_id}/metadata.json")
        metadata_blob.upload_from_string(
            json.dumps(job_metadata, ensure_ascii=False, indent=2),
            content_type="application/json"
        )
        
        chapters_blob = gcs.bucket.blob(f"jobs/{job_id}/input_chapters.json")
        chapters_blob.upload_from_string(
            json.dumps(chapters, ensure_ascii=False),
            content_type="application/json"
        )
        
        print(f"Saved {len(chapters)} chapters to GCS for job {job_id}")
        
        if use_cloud_tasks and FUNCTION_URL:
            # 5. Enqueue Cloud Tasks for each chapter
            queue_path = f"projects/{PROJECT_ID}/locations/{REGION}/queues/{QUEUE_NAME}"
            chapter_handler_url = f"{FUNCTION_URL}/process_chapter"
            finalizer_handler_url = f"{FUNCTION_URL}/finalize_book"
            
            for i, chapter in enumerate(chapters):
                delay = i * 60  # 60 seconds between each chapter
                payload = {
                    "job_id": job_id,
                    "chapter_number": i,
                    "book_title": file_name,
                    "existing_concepts": master_concepts[:100]
                }
                _create_cloud_task(gcs, queue_path, chapter_handler_url, payload, delay)
            
            # 6. Schedule finalizer after all chapters (with extra buffer)
            finalizer_delay = len(chapters) * 60 + 120  # 2 min buffer
            _create_cloud_task(
                gcs, queue_path, finalizer_handler_url,
                {"job_id": job_id},
                finalizer_delay
            )
            
            return json.dumps({
                'status': 'queued',
                'job_id': job_id,
                'chapters': len(chapters),
                'message': f'Enqueued {len(chapters)} chapter tasks'
            }), 200
        else:
            # Fallback: Process synchronously (legacy mode)
            return _process_synchronously(
                gcs, job_id, file_id, file_name, category, chapters, master_concepts
            )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return json.dumps({'error': str(e)}), 500


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
        
        result = analyzer.analyze()
        
        return json.dumps(result, ensure_ascii=False), 200, {"Content-Type": "application/json; charset=utf-8"}
        
    except Exception as e:
        print(f"Error in analyze_concepts: {e}")
        import traceback
        traceback.print_exc()
        return json.dumps({"status": "error", "message": str(e)}), 500

