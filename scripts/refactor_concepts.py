#!/usr/bin/env python3
"""
Refactor Concepts Index
1. Converts multi-line format to single-line wikilink format.
2. Merges duplicates based on predefined rules.
3. Separates Hub Concepts (>= 3 sources).
4. Sorts concepts.
"""

import re
import sys
import shutil
from collections import defaultdict
from pathlib import Path

# Normalization map (Duplicate -> Unified)
NORMALIZATION_MAP = {
    # 俯瞰
    "俯瞰 (Overview/Bird's-eye view)": "俯瞰",
    "俯瞰 (Overview/Bird's-eye View)": "俯瞰",
    "現状把握（俯瞰）": "俯瞰",
    # 戦略的構造化
    "戦略構造化": "戦略的構造化",
    # 経営判断
    "経営判断 (Management Decision)": "経営判断",
    # 問題解決
    "問題解決 (Problem Solving)": "問題解決",
}

def parse_concepts_index(filepath):
    """Parse the concepts index file and extract concept -> sources mapping."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    concepts = defaultdict(set)
    
    # Normalize the content: join multi-line entries into single lines
    # Replace newlines with space, then collapse multiple spaces
    normalized = ' '.join(content.split())
    
    # Pattern 1: Standard format - [[concept]]: [[source1]], [[source2]]
    standard_pattern = r'- \[\[([^\]]+)\]\]\s*:\s*(\[\[[^\]]+\]\](?:\s*,\s*\[\[[^\]]+\]\])*)'
    
    for match in re.finditer(standard_pattern, normalized):
        concept = match.group(1).strip()
        sources_str = match.group(2)
        sources = re.findall(r'\[\[([^\]]+)\]\]', sources_str)
        for src in sources:
            concepts[concept].add(src.strip())
    
    # Pattern 2: Multi-line format - [ [concept ] ]: [ [source ] ], [ [source2 ] ]
    multiline_pattern = r'- \[\s*\[([^\]]+)\]\s*\]\s*:\s*((?:\[\s*\[([^\]]+)\]\s*\](?:\s*,\s*)?)+)'
    
    for match in re.finditer(multiline_pattern, normalized):
        concept = match.group(1).strip()
        sources_str = match.group(2)
        sources = re.findall(r'\[\s*\[([^\]]+)\]\s*\]', sources_str)
        for src in sources:
            concepts[concept].add(src.strip())
            
    return concepts

def normalize_concepts(concepts):
    """Merge concepts based on normalization map."""
    normalized_concepts = defaultdict(set)
    
    for concept, sources in concepts.items():
        # Apply normalization
        target_concept = NORMALIZATION_MAP.get(concept, concept)
        
        # Also clean up "clean" parentheses if not in map
        # e.g. "Concept (Detail)" -> "Concept" if strict normalization is desired? 
        # For now, sticking to the explicit map to avoid over-merging.
        
        normalized_concepts[target_concept].update(sources)
        
    return normalized_concepts

def generate_markdown(concepts, threshold=3):
    """Generate the new Markdown content."""
    lines = ["# Concepts Index", ""]
    
    # Identify Hub Concepts
    hubs = {}
    standards = {}
    
    for concept, sources in concepts.items():
        if len(sources) >= threshold:
            hubs[concept] = sources
        else:
            standards[concept] = sources
            
    # Hub Concepts Section
    lines.append(f"## Hub Concepts (>={threshold} sources)")
    lines.append("")
    lines.append("> [!TIP] 定期レビュー対象")
    lines.append("> 以下の概念は複数の書籍/クリップから参照されています。")
    lines.append("> 内容の一貫性や深掘りの必要性を定期的に確認してください。")
    lines.append("")
    
    # Sort hubs by count (desc) then name (asc)
    sorted_hubs = sorted(hubs.items(), key=lambda x: (-len(x[1]), x[0]))
    for concept, sources in sorted_hubs:
        source_links = ", ".join([f"[[{s}]]" for s in sorted(sources)])
        lines.append(f"- [[{concept}]] ({len(sources)}): {source_links}")
        
    lines.append("")
    lines.append("## Standard Concepts")
    lines.append("")
    
    # Sort standards by name (asc)
    sorted_standards = sorted(standards.items(), key=lambda x: x[0])
    for concept, sources in sorted_standards:
        source_links = ", ".join([f"[[{s}]]" for s in sorted(sources)])
        lines.append(f"- [[{concept}]]: {source_links}")
        
    return "\n".join(lines)

def main():
    filepath = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/Users/takagishota/Documents/KnowledgeBase/00_Concepts_Index.md')
    backup_path = filepath.with_suffix('.md.bak')
    
    print(f"Reading from: {filepath}")
    
    # Backup
    if filepath.exists():
        shutil.copy(filepath, backup_path)
        print(f"Backup created: {backup_path}")
    
    concepts = parse_concepts_index(filepath)
    print(f"Parsed {len(concepts)} concepts.")
    
    normalized = normalize_concepts(concepts)
    print(f"Normalized to {len(normalized)} concepts (Merged {len(concepts) - len(normalized)}).")
    
    new_content = generate_markdown(normalized, threshold=3)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
        
    print(f"Successfully wrote refactored index to {filepath}")

if __name__ == "__main__":
    main()
