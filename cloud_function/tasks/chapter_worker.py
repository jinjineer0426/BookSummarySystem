"""
Chapter Worker - Processes a single chapter via Cloud Tasks.

This worker:
1. Receives job_id and chapter_number from the task payload.
2. Reads chapter content from GCS (jobs/{job_id}/input_chapters.json).
3. Calls Gemini to generate a summary.
4. Saves the result to GCS (jobs/{job_id}/chapter_{n}.json).
"""
import json
import functions_framework
from typing import Dict, Any

from config import BUCKET_NAME
from services.gcs_service import GcsService
from services.gemini_service import GeminiService
from services.logging_service import JobLogger
from services.job_tracker import JobTracker


@functions_framework.http
def process_chapter(request):
    """
    Cloud Tasks handler for processing a single chapter.
    
    Expected payload:
    {
        "job_id": "uuid-xxx",
        "chapter_number": 0,
        "book_title": "Book Title",
        "existing_concepts": ["Concept1", "Concept2", ...]
    }
    """
    try:
        # Debug logging
        print(f"Chapter Process Request: method={request.method}, path={request.path}")
        # print(f"Headers: {dict(request.headers)}") 
        
        request_json = request.get_json(silent=True)
        if not request_json:
            print("Error: No JSON payload found for chapter worker.")
            print(f"Raw Data: {request.get_data(as_text=True)[:500]}")
            return json.dumps({"error": "No payload"}), 400
        
        job_id = request_json.get("job_id")
        chapter_number = request_json.get("chapter_number")
        book_title = request_json.get("book_title", "Unknown")
        existing_concepts = request_json.get("existing_concepts", [])
        
        # Initialize structured logger and job tracker
        logger = JobLogger(job_id)
        gcs = GcsService()
        tracker = JobTracker(gcs, job_id)
        
        if job_id is None or chapter_number is None:
            logger.log_error("chapter_worker", "job_id or chapter_number missing", keys=list(request_json.keys()))
            return json.dumps({"error": "job_id and chapter_number required"}), 400
        
        logger.log_stage("chapter_processing", "started", chapter_number=chapter_number, book_title=book_title)
        
        # Initialize gemini service
        gemini = GeminiService()
        
        # 1. Read chapter content from GCS
        chapter_data = _read_chapter_input(gcs, job_id, chapter_number)
        if not chapter_data:
            return json.dumps({"error": f"Chapter {chapter_number} not found"}), 404
        
        # 2. Generate summary via Gemini
        summary_result = _generate_chapter_summary(
            gemini, 
            chapter_data, 
            book_title, 
            existing_concepts
        )
        
        # 3. Save result to GCS
        _save_chapter_result(gcs, job_id, chapter_number, summary_result, logger)
        
        # Note: Progress tracking now done via chapter_N.json file existence (checked by finalizer)
        
        logger.log_stage("chapter_processing", "completed", chapter_number=chapter_number)
        
        return json.dumps({
            "status": "success",
            "job_id": job_id,
            "chapter_number": chapter_number
        }), 200
        
    except Exception as e:
        if 'logger' in locals() and logger:
            logger.log_error("chapter_worker", str(e), chapter_number=request_json.get("chapter_number"))
        import traceback
        traceback.print_exc()
        return json.dumps({"error": str(e)}), 500


def _read_chapter_input(gcs: GcsService, job_id: str, chapter_number: int) -> Dict:
    """Reads the chapter content from GCS input file."""
    blob = gcs.bucket.blob(f"jobs/{job_id}/input_chapters.json")
    if not blob.exists():
        return None
    
    all_chapters = json.loads(blob.download_as_text())
    if chapter_number >= len(all_chapters):
        return None
    
    return all_chapters[chapter_number]


def _generate_chapter_summary(
    gemini: GeminiService, 
    chapter_data: Dict, 
    book_title: str,
    existing_concepts: list
) -> Dict[str, Any]:
    """Generates summary for a single chapter using Gemini."""
    
    content = chapter_data.get("content", "")
    title = chapter_data.get("title", "Chapter")
    
    # Truncate if too long (50k chars per chapter)
    if len(content) > 50000:
        content = content[:50000] + "\n...(Truncated)..."
    
    concepts_str = ", ".join(existing_concepts[:100])
    
    prompt = f"""
    Analyze this chapter and provide a detailed summary in Japanese.
    If the chapter focuses on a specific concept or person (dictionary style), start with a clear definition.
    
    Book Title: {book_title}
    Chapter Title: {title}
    Existing Concepts (prefer these): {concepts_str}
    
    Chapter Content:
    {content}
    
    Output JSON:
    {{
      "summary": "Definition or Introduction (1-2 sentences)\\n\\n- Point 1\\n- Point 2\\n- Point 3\\n- Point 4\\n- Point 5 (Key insights and business applications)",
      "keyConcepts": ["Concept1", "Concept2", "Concept3"]
    }}
    """
    
    result = gemini.generate_content(prompt, max_retries=3)
    
    if not result:
        return {
            "title": title,
            "summary": "(Summary generation failed)",
            "keyConcepts": []
        }
    
    # Enforce the original title
    result["title"] = title
    return result


def _save_chapter_result(gcs: GcsService, job_id: str, chapter_number: int, result: Dict, logger: JobLogger):
    """Saves the chapter summary result to GCS."""
    blob = gcs.bucket.blob(f"jobs/{job_id}/chapter_{chapter_number}.json")
    blob.upload_from_string(
        json.dumps(result, ensure_ascii=False, indent=2),
        content_type="application/json"
    )
    logger.logger.debug(f"Saved chapter {chapter_number} result to GCS")



