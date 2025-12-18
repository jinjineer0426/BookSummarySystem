#!/usr/bin/env python3
"""
Fix Concepts Index Format & Merge Significance Terms
"""

import re
import sys
import shutil
from collections import defaultdict
from pathlib import Path

# Target Concept for merges
TARGET_CONCEPT = "統計的有意性"

# Concepts to merge (substring match or exact match)
# Using a list of exact matches based on previous analysis + heuristics
MERGE_LIST = [
    "有意な連関", "有意でない連関",
    "有意な関係", "有意でない関係",
    "有意な差", "有意でない差",
    "有意な効果", "有意でない効果",
    "有意な影響", "有意でない影響",
    "有意な傾向", "有意でない傾向",
    "有意な結果", "有意でない結果",
    "有意", "有意でない",
    "有意水準", "有意確率"
]

def clean_wikilink(text):
    """Remove newlines, extra spaces, and outer brackets from a wikilink content."""
    # Matches [[ ... ]] and extracts content
    # But input might be broken like "[ [ \n content \n ] ]"
    
    # 1. Remove all newlines and multiple spaces
    cleaned = ' '.join(text.split())
    
    # 2. Extract content from [[...]]
    match = re.search(r'\[\[(.*?)\]\]', cleaned)
    if match:
        return match.group(1).strip()
    
    # Fallback: remove brackets manually
    return cleaned.replace('[', '').replace(']', '').strip()

def parse_and_clean(filepath):
    """Parses the file by reading ALL content and aggressively finding links."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    concepts = defaultdict(set)
    
    # Strategy: Split by "- [" which usually denotes start of a new entry
    # This assumes the file is vaguely a list.
    
    # Normalize the WHOLE content first to single line? No, dangerous if file is huge, but it's 50KB.
    # Replacing all newlines with space might break the distinction between entries if they don't have bullets.
    # But we know they have bullets.
    
    # Let's try splitting by the entry separator "- "
    # But standard text might have "- ".
    # The valid entries start with "- [" (or "- [ [" in broken format).
    
    # We will use the 'normalized' approach from before but STRICTER.
    normalized = ' '.join(content.split())
    
    # Pattern to find: - [[Concept]] ... : ... [[Source]]
    # Or broken: - [ [Concept] ] ... : ... [ [Source] ]
    
    # Regex to capture one entry:
    # - (bracket_stuff) : (bracket_stuff_list)
    
    # Let's iterate through the string using finditer with a very broad pattern
    # - \s* (\[.*?) \s* : \s* (.*?) (?=- \[|$)  <-- lookahead for next entry
    
    pattern = r'-\s*(\[.*?\])\s*:\s*(.*?)(?=\s-\s*\[|$)'
    
    # We need to be careful about greedy matching.
    # The key is that "Concept" part usually ends with "]:" (in broken) or "]:" (in clean)
    
    matches = re.finditer(pattern, normalized)
    
    for m in matches:
        raw_concept = m.group(1)
        raw_sources = m.group(2)
        
        concept = clean_wikilink(raw_concept)
        
        # Parse sources (comma separated wikilinks)
        # raw_sources might look like: "[[Source1]], [ [ Source 2 ] ]"
        
        # We can just extract anything that looks like a wikilink content
        # Because we flattened the string, [[...]] logic holds.
        # But broken ones might be [ [ ... ] ]
        
        # Helper to extract all "names" from a string of sources
        # We look for the innermost text wrapped in brackets
        
        # Regex for source extraction: find `[[...]]` OR `[ [ ... ] ]`
        # Simplification: Remove all `[` and `]` and split by `,`?
        # filenames usually don't contain comma.
        
        # Better: Since we know the broken format uses `[ [` and `] ]`, let's normalize raw_sources string further.
        clean_src_str = raw_sources.replace('[ [', '[[').replace('] ]', ']]')
        clean_src_str = clean_src_str.replace('[', '').replace(']', '') # remove all brackets?? No, filenames might have brackets? Unlikely in this system.
        
        # Let's split by comma
        src_items = [s.strip() for s in clean_src_str.split(',')]
        
        for src in src_items:
            if src:
                concepts[concept].add(src)
                
    return concepts

def merge_significance(concepts):
    """Merges 'significance' related concepts."""
    merged = defaultdict(set)
    
    for concept, sources in concepts.items():
        # Check merge list
        should_merge = False
        if concept in MERGE_LIST:
            should_merge = True
        
        target = TARGET_CONCEPT if should_merge else concept
        merged[target].update(sources)
        
    return merged

def generate_markdown(concepts):
    lines = ["# Concepts Index", "", "## Hub Concepts (>=3 sources)", "", "> [!TIP] 定期レビュー対象", "> 以下の概念は複数の書籍/クリップから参照されています。", "> 内容の一貫性や深掘りの必要性を定期的に確認してください。", ""]
    
    hubs = {}
    standards = {}
    
    for c, s in concepts.items():
        if len(s) >= 3:
            hubs[c] = s
        else:
            standards[c] = s
            
    # Output Hubs
    for c, s in sorted(hubs.items(), key=lambda x: (-len(x[1]), x[0])):
        link_str = ", ".join([f"[[{src}]]" for src in sorted(s)])
        lines.append(f"- [[{c}]] ({len(s)}): {link_str}")
        
    lines.append("")
    lines.append("## Standard Concepts")
    lines.append("")
    
    # Output Standards
    for c, s in sorted(standards.items(), key=lambda x: x[0]):
        link_str = ", ".join([f"[[{src}]]" for src in sorted(s)])
        lines.append(f"- [[{c}]]: {link_str}")
        
    return "\n".join(lines)

def main():
    filepath = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/Users/takagishota/Documents/KnowledgeBase/00_Concepts_Index.md')
    
    print(f"Processing {filepath}...")
    concepts = parse_and_clean(filepath)
    print(f"Parsed {len(concepts)} raw concepts.")
    
    merged = merge_significance(concepts)
    print(f"After merging: {len(merged)} concepts.")
    
    new_content = generate_markdown(merged)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
        
    print("Done.")

if __name__ == "__main__":
    main()
