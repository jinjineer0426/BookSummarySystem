import re
import math
import json
from datetime import datetime
from typing import List, Optional, Dict

from config import SIMILARITY_THRESHOLD
from .gcs_service import GcsService
from .gemini_service import GeminiService

class ConceptNormalizer:
    def __init__(self, gcs_service: GcsService, gemini_service: GeminiService):
        self.gcs = gcs_service
        self.gemini = gemini_service
    
    def normalize(self, raw_concepts: List[str], book_title: str) -> List[Dict]:
        master_data = self.gcs.get_concepts()
        master_concepts = master_data.get("concepts", {})
        
        results = []
        for concept in raw_concepts:
            normalized = self._find_match(concept, master_concepts)
            
            if normalized:
                results.append({
                    "original": concept,
                    "normalized": normalized,
                    "is_new": False
                })
                target_concept = master_concepts[normalized]
                target_concept["count"] = target_concept.get("count", 0) + 1
                
                # Backfill embedding if missing (Self-healing)
                if "embedding" not in target_concept:
                    try:
                        print(f"Backfilling embedding for: {normalized}")
                        target_concept["embedding"] = self.gemini.get_embedding(normalized)
                    except Exception as e:
                        print(f"Failed to backfill embedding: {e}")

            else:
                similar = self._find_similar_by_embedding(concept, master_concepts)
                
                if similar:
                    results.append({
                        "original": concept,
                        "normalized": similar,
                        "is_new": False
                    })
                    target_concept = master_concepts[similar]
                    if concept not in target_concept.get("aliases", []):
                        target_concept.setdefault("aliases", []).append(concept)
                    target_concept["count"] = target_concept.get("count", 0) + 1
                    
                    # Backfill embedding if missing
                    if "embedding" not in target_concept:
                        try:
                             target_concept["embedding"] = self.gemini.get_embedding(similar)
                        except: pass

                else:
                    results.append({
                        "original": concept,
                        "normalized": concept,
                        "is_new": True
                    })
                    self.gcs.add_pending_concept(concept, {"source": book_title, "category": "Unknown"})
        
        master_data["concepts"] = master_concepts
        self.gcs.save_concepts(master_data)
        
        return results
    
    def _find_match(self, concept: str, master_concepts: dict) -> Optional[str]:
        concept_lower = concept.lower().replace(" ", "").replace("-", "")
        
        for name, data in master_concepts.items():
            if name.lower().replace(" ", "").replace("-", "") == concept_lower:
                return name
            
            for alias in data.get("aliases", []):
                if alias.lower().replace(" ", "").replace("-", "") == concept_lower:
                    return name
        
        return None
    
    def _find_similar_by_embedding(self, concept: str, master_concepts: dict) -> Optional[str]:
        if not master_concepts:
            return None
        
        # 1. Get embedding for the new concept
        try:
            concept_embedding = self.gemini.get_embedding(concept)
        except Exception as e:
            print(f"Embedding failed for {concept}: {e}")
            return None
            
        best_match = None
        best_score = 0
        
        # 2. Compare with existing concepts
        for name, data in master_concepts.items():
            master_embedding = data.get("embedding")
            
            if master_embedding and len(master_embedding) > 0:
                score = self._cosine_similarity(concept_embedding, master_embedding)
                if score > best_score:
                    best_score = score
                    best_match = name
        
        # 3. Validation against threshold
        if best_score >= SIMILARITY_THRESHOLD:
            print(f"Similarity match: '{concept}' -> '{best_match}' (Score: {best_score:.4f})")
            return best_match
            
        return None
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot_product = sum(i * j for i, j in zip(a, b))
        magnitude_a = math.sqrt(sum(i * i for i in a))
        magnitude_b = math.sqrt(sum(i * i for i in b))
        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0
        return dot_product / (magnitude_a * magnitude_b)


class CategoryNormalizer:
    def __init__(self, gcs_service: GcsService):
        self.gcs = gcs_service
    
    def normalize(self, suggested_category: str, parent_category: str) -> str:
        categories = self.gcs.get_categories()
        taxonomy = categories.get("taxonomy", {})
        
        if parent_category not in taxonomy:
            parent_category = "Business" 
        
        parent_data = taxonomy.get(parent_category, {})
        subcategories = parent_data.get("subcategories", [])
        
        if suggested_category in subcategories:
            return suggested_category
        
        if parent_data.get("allowNew", False):
            self.gcs.add_pending_category(suggested_category, parent_category)
            return "Other"
        else:
            return subcategories[0] if subcategories else "Other"


class IndexService:
    def __init__(self, gcs_service: GcsService, gemini_service: GeminiService):
        self.gcs = gcs_service
        self.concept_normalizer = ConceptNormalizer(gcs_service, gemini_service)
        self.category_normalizer = CategoryNormalizer(gcs_service)

    def update_books_index(self, title: str, author: str, category: str) -> None:
        """Updates the Books Index file in GCS."""
        index_path = "01_Reading/00_Books_Index.md"
        content = self.gcs.read_obsidian_file(index_path)
        
        if not content:
            content = "# Books Index\n\n"
        
        entry = f"- [[{title}]] ({author}) - {category}"
        
        if entry not in content:
            content = content.rstrip() + "\n" + entry + "\n"
            self.gcs.write_to_obsidian_vault(index_path, content)
            print(f"Updated Books Index: added {title}")

    def update_concepts_index(self, concepts: List[str], book_title: str) -> None:
        """Updates the Concepts Index file in GCS."""
        if not concepts:
            return
        
        index_path = "02_Knowledge/00_Concepts_Index.md"
        content = self.gcs.read_obsidian_file(index_path)
        
        if not content:
            content = "# Concepts Index\n\n"
        
        lines = content.split('\n')
        concept_line_map = {}
        
        # Parse existing concept lines
        for idx, line in enumerate(lines):
            if line.strip().startswith('- [['):
                match = re.match(r'^- \[\[(.*?)\]\](?: \(\d+\))?:', line)
                if match:
                    concept_line_map[match.group(1)] = idx
        
        updated = False
        book_link = f"[[{book_title}]]"
        
        for concept in concepts:
            if concept in concept_line_map:
                idx = concept_line_map[concept]
                if book_link not in lines[idx]:
                    lines[idx] += f", {book_link}"
                    updated = True
            else:
                lines.append(f"- [[{concept}]]: {book_link}")
                updated = True
        
        if updated:
            new_content = '\n'.join(lines)
            self.gcs.write_to_obsidian_vault(index_path, new_content)
            print(f"Updated Concepts Index: added links for {book_title}")
