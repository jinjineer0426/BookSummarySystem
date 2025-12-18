#!/usr/bin/env python3
"""
Concepts Index Analyzer
Analyzes the concepts index for:
1. Hub concepts (concepts referenced from multiple sources)
2. Duplicate/similar concepts that should be merged
3. Potential broken links
"""

import re
from collections import defaultdict
from difflib import SequenceMatcher
import sys

def parse_concepts_index(filepath):
    """Parse the concepts index file and extract concept -> sources mapping."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    concepts = defaultdict(set)
    
    # First, normalize the content by joining lines and removing extra whitespace
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
    # After normalization: - [ [ concept ] ]: [ [ source ] ], [ [ source2 ] ]
    multiline_pattern = r'- \[\s*\[([^\]]+)\]\s*\]\s*:\s*((?:\[\s*\[([^\]]+)\]\s*\](?:\s*,\s*)?)+)'
    
    for match in re.finditer(multiline_pattern, normalized):
        concept = match.group(1).strip()
        sources_str = match.group(2)
        # Extract sources from [ [source] ] pattern
        sources = re.findall(r'\[\s*\[([^\]]+)\]\s*\]', sources_str)
        for src in sources:
            concepts[concept].add(src.strip())
    
    return concepts



def find_hub_concepts(concepts, threshold=3):
    """Find concepts that appear in multiple sources (hub concepts)."""
    hubs = {}
    for concept, sources in concepts.items():
        if len(sources) >= threshold:
            hubs[concept] = sources
    return dict(sorted(hubs.items(), key=lambda x: len(x[1]), reverse=True))

def find_similar_concepts(concepts, similarity_threshold=0.8):
    """Find concepts that might be duplicates based on string similarity."""
    concept_list = list(concepts.keys())
    similar_pairs = []
    
    for i, c1 in enumerate(concept_list):
        for c2 in concept_list[i+1:]:
            # Normalize for comparison
            n1 = c1.lower().replace(' ', '').replace('（', '(').replace('）', ')')
            n2 = c2.lower().replace(' ', '').replace('（', '(').replace('）', ')')
            
            # Check exact match after normalization
            if n1 == n2:
                similar_pairs.append((c1, c2, 1.0))
                continue
            
            # Check if one contains the other
            if n1 in n2 or n2 in n1:
                similar_pairs.append((c1, c2, 0.9))
                continue
            
            # Check string similarity
            ratio = SequenceMatcher(None, n1, n2).ratio()
            if ratio >= similarity_threshold:
                similar_pairs.append((c1, c2, ratio))
    
    return sorted(similar_pairs, key=lambda x: x[2], reverse=True)

def find_japanese_english_pairs(concepts):
    """Find concepts that have both Japanese and English versions."""
    # Pattern: Japanese (English) or English (Japanese)
    pairs = []
    for c in concepts.keys():
        # Check if concept has parenthetical notation
        match = re.match(r'(.+?)\s*[\(（]([^\)）]+)[\)）]', c)
        if match:
            main = match.group(1).strip()
            alt = match.group(2).strip()
            # Check if alternate exists as separate concept
            for other in concepts.keys():
                if other != c and (other == main or other == alt):
                    pairs.append((c, other))
    return pairs

def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else '/Users/takagishota/Documents/KnowledgeBase/00_Concepts_Index.md'
    threshold = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    
    print(f"=== Concepts Index Analysis (Threshold: {threshold}) ===\n")
    
    concepts = parse_concepts_index(filepath)
    print(f"Total concepts found: {len(concepts)}\n")
    
    # Hub concepts
    print(f"## Hub Concepts (>= {threshold} sources)\n")
    hubs = find_hub_concepts(concepts, threshold)
    if hubs:
        for concept, sources in hubs.items():
            print(f"- **{concept}** ({len(sources)} sources)")
            for src in sorted(sources):
                print(f"  - {src}")
    else:
        print("No hub concepts found at this threshold.\n")
    
    print(f"\n## Potential Duplicates (Similarity >= 0.8)\n")
    similar = find_similar_concepts(concepts, 0.8)
    if similar[:20]:  # Show top 20
        for c1, c2, ratio in similar[:20]:
            print(f"- [{ratio:.0%}] \"{c1}\" vs \"{c2}\"")
    else:
        print("No similar concepts found.\n")
    
    print(f"\n## Japanese/English Pairs (Separate entries)\n")
    pairs = find_japanese_english_pairs(concepts)
    if pairs:
        for p1, p2 in pairs[:20]:
            print(f"- \"{p1}\" <-> \"{p2}\"")
    else:
        print("No separate Japanese/English pairs found.\n")

if __name__ == "__main__":
    main()
