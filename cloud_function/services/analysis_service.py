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
    
    def publish_weekly_report(self) -> Dict[str, Any]:
        """Runs analysis and publishes a Markdown report to GCS."""
        analysis_result = self.analyze()
        
        if analysis_result["status"] != "success":
            return analysis_result
            
        report_data = analysis_result["report"]
        markdown_content = self._format_markdown_report(report_data)
        
        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = f"02_Knowledge/01_Weekly_Report/Weekly_Index_Report_{date_str}.md"
        
        gcs_uri = self.gcs.write_to_obsidian_vault(filename, markdown_content)
        
        return {
            "status": "success",
            "message": "Weekly report published",
            "file_path": filename,
            "gcs_uri": gcs_uri,
            "report": report_data
        }

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
        # Detect hierarchy candidates (substring matches)
        hierarchy_candidates = self._find_hierarchy_candidates(concepts)
        
        # Detect potential duplicates (similarity), excluding those already in hierarchy
        potential_duplicates = self._find_duplicates(concepts, hierarchy_candidates, similarity=0.85)
        
        jp_en_pairs = self._find_jp_en_pairs(concepts)
        
        return {
            "status": "success",
            "report": {
                "total_concepts": len(concepts),
                "hub_concepts": [
                    {"name": name, "count": len(sources)}
                    for name, sources in sorted(hub_concepts.items(), key=lambda x: -len(x[1]))
                ],
                "hierarchy_candidates": hierarchy_candidates,
                "potential_duplicates": [
                    {"pair": [p[0], p[1]], "similarity": round(p[2], 2)}
                    for p in potential_duplicates[:20]  # Top 20
                ],
                "jp_en_pairs": jp_en_pairs[:10],  # Top 10
                "last_updated": datetime.utcnow().isoformat() + "Z"
            }
        }

    def _format_markdown_report(self, data: Dict[str, Any]) -> str:
        """Formats the analysis report as Markdown."""
        today = datetime.now().strftime('%Y-%m-%d')
        
        md = f"""---
title: "Weekly Index Report {today}"
date: {today}
tags: [weekly_review, maintenance]
---

# Weekly Concepts Index Report ({today})

## 📊 Overview
- **Total Concepts**: {data.get('total_concepts', 0)}
- **Last Updated**: {data.get('last_updated')}

## 🧹 Maintenance Required

### 1. Potential Duplicates (High Similarity)
> Review these pairs. If they are synonyms, create an alias or merge them.

"""
        
        duplicates = data.get("potential_duplicates", [])
        if duplicates:
            for item in duplicates:
                c1, c2 = item["pair"]
                score = item["similarity"]
                md += f"- **{score:.2f}**: [[{c1}]] <--> [[{c2}]]\n"
        else:
            md += "- No obvious duplicates found.\n"
        md += "> These concepts have parent-child naming relationships. Consider linking them.\n"
        md += "> **How to Link**: Open the child note and add `Up: [[Parent]]` or mention `[[Parent]]` in the content.\n\n"
        
        hierarchy = data.get("hierarchy_candidates", {})
        if hierarchy:
            for parent, children in hierarchy.items():
                md += f"- **[[{parent}]]**\n"
                for child in children:
                    md += f"  - [[{child}]]\n"
        else:
            md += "- No hierarchy candidates found.\n"
            
        md += "\n### 3. Japanese/English Notation Split\n"
        md += "> These concepts exist separately but might refer to the same thing (e.g. 'Apple' vs 'Apple (Fruit)').\n\n"
        
        pairs = data.get("jp_en_pairs", [])
        if pairs:
            for item in pairs:
                c1 = item["with_notation"]
                c2 = item["without_notation"]
                md += f"- [[{c1}]] <--> [[{c2}]]\n"
        else:
            md += "- No split pairs found.\n"
            
        md += "\n## 🔗 Top Hub Concepts\n"
        md += "> Concepts with the most connections. Good candidates for MOCs (Map of Content).\n\n"
        
        hubs = data.get("hub_concepts", [])[:10]  # Top 10
        if hubs:
            for item in hubs:
                md += f"- [[{item['name']}]] ({item['count']} links)\n"
        
        return md
    
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
    
    def _find_hierarchy_candidates(self, concepts: Dict[str, set]) -> Dict[str, List[str]]:
        """Finds concepts that are substrings of others (potential parent-child)."""
        candidates = defaultdict(list)
        concept_list = sorted(list(concepts.keys()), key=len)  # Sort by length
        
        for i, parent in enumerate(concept_list):
            for child in concept_list[i+1:]:
                # Check strict substring (and strictly longer)
                if parent in child and len(child) > len(parent):
                    # Exclude if it's just a plural or minor variation (simple heuristic)
                    if child == parent + "s" or child == parent + "es":
                        continue
                    candidates[parent].append(child)
        
        return dict(candidates)

    def _find_duplicates(self, concepts: Dict[str, set], hierarchy: Dict[str, List[str]], similarity: float = 0.85) -> List[tuple]:
        """Finds potential duplicate concepts based on string similarity."""
        concept_list = list(concepts.keys())
        duplicates = []
        
        for i, c1 in enumerate(concept_list):
            for c2 in concept_list[i+1:]:
                n1 = c1.lower().replace(' ', '').replace('（', '(').replace('）', ')')
                n2 = c2.lower().replace(' ', '').replace('（', '(').replace('）', ')')
                
                if n1 == n2:
                    duplicates.append((c1, c2, 1.0))
                # Skip contains check here, handled by hierarchy detection
                # elif n1 in n2 or n2 in n1:
                #    duplicates.append((c1, c2, 0.9))
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
