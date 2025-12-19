"""
Finalizer - Aggregates chapter results and produces final output.

This finalizer:
1. Checks if all chapters are processed for a given job.
2. Reads all chapter results from GCS.
3. Generates a book-level summary.
4. Creates the final Markdown file.
5. Updates the Books/Concepts indexes.
"""
import json
import re
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
import functions_framework

from config import BUCKET_NAME
from services.gcs_service import GcsService
from services.gemini_service import GeminiService
from services.index_service import IndexService, ConceptNormalizer


@functions_framework.http
def finalize_book(request):
    """
    Cloud Tasks handler for finalizing a book summary.
    
    Expected payload:
    {
        "job_id": "uuid-xxx"
    }
    
    Can also be triggered by a scheduler to check for completed jobs.
    """
    try:
        print(f"Finalizing job request. method={request.method}, path={request.path}")
        print(f"Headers: {dict(request.headers)}")
        print(f"Data: {request.get_data(as_text=True)[:1000]}") # Log first 1000 chars

        request_json = request.get_json(silent=True)
        if not request_json:
            print("Error: No JSON payload found.")
            return json.dumps({"error": "No payload"}), 400
        
        job_id = request_json.get("job_id")
        if not job_id:
            print("Error: job_id missing in payload.")
            return json.dumps({"error": "job_id required"}), 400
        
        print(f"Finalizing job {job_id}")
        
        # Initialize services
        gcs = GcsService()
        gemini = GeminiService()
        index_service = IndexService(gcs, gemini)
        
        # 1. Check if all chapters are complete
        metadata = _read_job_metadata(gcs, job_id)
        if not metadata:
            return json.dumps({"error": "Job not found"}), 404
        
        total_chapters = metadata.get("total_chapters", 0)
        completed_chapters = metadata.get("completed_chapters", [])
        
        if len(completed_chapters) < total_chapters:
            return json.dumps({
                "message": f"Waiting for chapters: {len(completed_chapters)}/{total_chapters} complete"
            }), 429
        
        # 2. Read all chapter results
        chapter_summaries = _read_all_chapter_results(gcs, job_id, total_chapters)
        
        # 3. Generate book-level summary
        book_summary = _generate_book_summary(
            gemini,
            metadata.get("book_title", "Unknown"),
            metadata.get("category", "Business"),
            chapter_summaries
        )
        
        # 4. Normalize concepts
        concept_normalizer = ConceptNormalizer(gcs, gemini)
        normalized_concepts = concept_normalizer.normalize(
            book_summary.get("allKeyConcepts", []),
            metadata.get("book_title", "Unknown")
        )
        
        # 5. Prepare final data
        final_data = {
            "title": book_summary.get("title", metadata.get("book_title")),
            "author": book_summary.get("author", "Unknown"),
            "suggestedSubfolder": book_summary.get("suggestedSubfolder", "Other"),
            "allKeyConcepts": [c["normalized"] for c in normalized_concepts],
            "summary": book_summary.get("summary", ""),
            "chapters": chapter_summaries
        }
        
        # Normalize chapter concepts
        for chapter in final_data["chapters"]:
            chapter_concepts = concept_normalizer.normalize(
                chapter.get("keyConcepts", []),
                final_data["title"]
            )
            chapter["keyConcepts"] = [c["normalized"] for c in chapter_concepts]
        
        # 6. Generate markdown
        md_content = _format_as_markdown(final_data, metadata.get("file_id", ""))
        
        # 7. Write to Obsidian Vault
        clean_title = re.sub(r'[\\/:*?"<>|]', '_', final_data["title"])
        md_path = f"01_Reading/{clean_title}.md"
        gcs_uri = gcs.write_to_obsidian_vault(md_path, md_content)
        print(f"Written to GCS: {gcs_uri}")
        
        # 8. Update indexes
        index_service.update_books_index(
            final_data["title"],
            final_data["author"],
            final_data["suggestedSubfolder"]
        )
        index_service.update_concepts_index(
            final_data["allKeyConcepts"],
            final_data["title"]
        )
        
        # 9. Mark job as complete
        _mark_job_complete(gcs, job_id, gcs_uri)
        
        return json.dumps({
            "status": "success",
            "gcs_uri": gcs_uri,
            "title": final_data["title"]
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return json.dumps({"error": str(e)}), 500


def _read_job_metadata(gcs: GcsService, job_id: str) -> Optional[Dict]:
    """Reads job metadata from GCS."""
    blob = gcs.bucket.blob(f"jobs/{job_id}/metadata.json")
    if not blob.exists():
        return None
    return json.loads(blob.download_as_text())


def _read_all_chapter_results(gcs: GcsService, job_id: str, total_chapters: int) -> List[Dict]:
    """Reads all chapter result files from GCS."""
    results = []
    for i in range(total_chapters):
        blob = gcs.bucket.blob(f"jobs/{job_id}/chapter_{i}.json")
        if blob.exists():
            results.append(json.loads(blob.download_as_text()))
        else:
            results.append({
                "title": f"Chapter {i}",
                "summary": "(Result not found)",
                "keyConcepts": []
            })
    return results


def _generate_book_summary(
    gemini: GeminiService,
    book_title: str,
    category: str,
    chapter_summaries: List[Dict]
) -> Dict[str, Any]:
    """Generates the overall book summary from chapter summaries."""
    
    # Collect all concepts
    all_concepts = set()
    for cs in chapter_summaries:
        all_concepts.update(cs.get("keyConcepts", []))
    
    chapter_summaries_text = "\n".join([
        f"### {cs.get('title', 'Unknown')}\n{cs.get('summary', '')}"
        for cs in chapter_summaries
    ])
    
    prompt = f"""
    Based on these chapter summaries, create an overall book summary in Japanese.
    
    Book Title: {book_title}
    Category: {category}
    
    Chapter Summaries:
    {chapter_summaries_text}
    
    All Extracted Concepts: {", ".join(list(all_concepts)[:50])}
    
    Output JSON:
    {{
      "title": "Book title (clean, without .pdf)",
      "author": "Author name",
      "suggestedSubfolder": "Subcategory",
      "allKeyConcepts": ["Top 10 most important concepts"],
      "summary": "Comprehensive executive summary (400-600 characters)"
    }}
    """
    
    result = gemini.generate_content(prompt, max_retries=3)
    
    if not result:
        return {
            "title": book_title,
            "author": "Unknown",
            "suggestedSubfolder": "Other",
            "allKeyConcepts": list(all_concepts)[:10],
            "summary": "Book summary generation failed."
        }
    
    return result


def _format_as_markdown(data: Dict[str, Any], original_file_id: str) -> str:
    """Formats the summary data into a Markdown string."""
    today = datetime.now().strftime('%Y-%m-%d')
    pdf_url = f"https://drive.google.com/file/d/{original_file_id}/view" if original_file_id else ""
    
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

    for chapter in data.get('chapters', []):
        chapter_summary = chapter.get('summary', '')
        
        # Handle case where summary is returned as a list
        if isinstance(chapter_summary, list):
            chapter_summary = '\n'.join(str(item) for item in chapter_summary)
        
        if not chapter_summary or (isinstance(chapter_summary, str) and len(chapter_summary.strip()) < 10):
            chapter_summary = "(Summary generation failed)"
        
        chapter_concepts = " ".join([f"[[{c}]]" for c in chapter.get('keyConcepts', [])])
        md += f"""
### {chapter.get('title')}
{chapter_summary}

**Key Concepts**: {chapter_concepts}
"""

    return md


def _mark_job_complete(gcs: GcsService, job_id: str, gcs_uri: str):
    """Marks the job as complete in metadata."""
    blob = gcs.bucket.blob(f"jobs/{job_id}/metadata.json")
    if blob.exists():
        metadata = json.loads(blob.download_as_text())
    else:
        metadata = {}
    
    metadata["status"] = "complete"
    metadata["completed_at"] = datetime.now().isoformat()
    metadata["output_uri"] = gcs_uri
    
    blob.upload_from_string(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        content_type="application/json"
    )
    print(f"Job {job_id} marked as complete")
