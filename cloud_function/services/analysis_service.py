"""
Analysis Service for Weekly Concepts Index Review
"""

import re
from collections import defaultdict
from difflib import SequenceMatcher
from datetime import datetime
from typing import Dict, List, Any

from .gcs_service import GcsService


class AnalysisService:
    """Analyzes the Concepts Index and generates a report."""
    
    def __init__(self, gcs_service: GcsService):
        self.gcs = gcs_service
        self.index_path = "02_Knowledge/00_Concepts_Index.md"
    
    def analyze(self) -> Dict[str, Any]:
        """Runs the full analysis and returns a report."""
        content = self.gcs.read_obsidian_file(self.index_path)
        
        if not content:
            return {
                "status": "error",
                "message": "Could not read Concepts Index file"
            }
        
        concepts = self._parse_concepts(content)
        
        hub_concepts = self._find_hub_concepts(concepts, threshold=3)
        potential_duplicates = self._find_duplicates(concepts, similarity=0.85)
        jp_en_pairs = self._find_jp_en_pairs(concepts)
        
        return {
            "status": "success",
            "report": {
                "total_concepts": len(concepts),
                "hub_concepts": [
                    {"name": name, "count": len(sources)}
                    for name, sources in sorted(hub_concepts.items(), key=lambda x: -len(x[1]))
                ],
                "potential_duplicates": [
                    {"pair": [p[0], p[1]], "similarity": round(p[2], 2)}
                    for p in potential_duplicates[:20]  # Top 20
                ],
                "jp_en_pairs": jp_en_pairs[:10],  # Top 10
                "last_updated": datetime.utcnow().isoformat() + "Z"
            }
        }
    
    def _parse_concepts(self, content: str) -> Dict[str, set]:
        """Parses the index file and extracts concept -> sources mapping."""
        concepts = defaultdict(set)
        
        # Normalize content
        normalized = ' '.join(content.split())
        
        # Standard format: - [[Concept]]: [[Source1]], [[Source2]]
        # Hub format: - [[Concept]] (N): [[Source1]], ...
        pattern = r'- \[\[([^\]]+)\]\](?: \(\d+\))?\s*:\s*(.*?)(?=\s- \[\[|$)'
        
        for match in re.finditer(pattern, normalized):
            concept = match.group(1).strip()
            sources_str = match.group(2)
            sources = re.findall(r'\[\[([^\]]+)\]\]', sources_str)
            for src in sources:
                concepts[concept].add(src.strip())
        
        return concepts
    
    def _find_hub_concepts(self, concepts: Dict[str, set], threshold: int = 3) -> Dict[str, set]:
        """Finds concepts referenced from multiple sources."""
        return {c: s for c, s in concepts.items() if len(s) >= threshold}
    
    def _find_duplicates(self, concepts: Dict[str, set], similarity: float = 0.85) -> List[tuple]:
        """Finds potential duplicate concepts based on string similarity."""
        concept_list = list(concepts.keys())
        duplicates = []
        
        for i, c1 in enumerate(concept_list):
            for c2 in concept_list[i+1:]:
                n1 = c1.lower().replace(' ', '').replace('（', '(').replace('）', ')')
                n2 = c2.lower().replace(' ', '').replace('（', '(').replace('）', ')')
                
                if n1 == n2:
                    duplicates.append((c1, c2, 1.0))
                elif n1 in n2 or n2 in n1:
                    duplicates.append((c1, c2, 0.9))
                else:
                    ratio = SequenceMatcher(None, n1, n2).ratio()
                    if ratio >= similarity:
                        duplicates.append((c1, c2, ratio))
        
        return sorted(duplicates, key=lambda x: -x[2])
    
    def _find_jp_en_pairs(self, concepts: Dict[str, set]) -> List[Dict]:
        """Finds concepts with Japanese/English notation pairs."""
        pairs = []
        for c in concepts.keys():
            match = re.match(r'(.+?)\s*[\(（]([^\)）]+)[\)）]', c)
            if match:
                main = match.group(1).strip()
                alt = match.group(2).strip()
                for other in concepts.keys():
                    if other != c and (other == main or other == alt):
                        pairs.append({"with_notation": c, "without_notation": other})
        return pairs
