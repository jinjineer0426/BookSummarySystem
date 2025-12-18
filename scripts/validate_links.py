#!/usr/bin/env python3
"""
Validate Links in Concepts Index
Checks if wikilinks in 00_Concepts_Index.md point to existing files in GCS.
"""

import re
import sys
import os
from google.cloud import storage
from collections import defaultdict

# Bucket Name (from config/environment)
BUCKET_NAME = "obsidian_vault_sync_my_knowledge"

def get_gcs_files(bucket_name):
    """Get a set of all Markdown files in the bucket (basename only for wikilink matching)."""
    print(f"Connecting to GCS bucket: {bucket_name}...")
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blobs = bucket.list_blobs()
        
        files = set()
        count = 0
        for blob in blobs:
            if blob.name.endswith('.md'):
                # Extract basename without extension for wikilink matching
                # e.g. "01_Reading/Book.md" -> "Book"
                basename = os.path.splitext(os.path.basename(blob.name))[0]
                files.add(basename)
                count += 1
        
        print(f"Found {count} Markdown files in GCS.")
        return files
    except Exception as e:
        print(f"Error accessing GCS: {e}")
        return set()

def parse_concepts_index(filepath):
    """Extract all source links from the index."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    links = set()
    
    # Pattern to find [[Source]] in the values part
    # Line format: - [[Concept]]: [[Source1]], [[Source2]] ...
    for line in content.split('\n'):
        if not line.startswith('- [['):
            continue
        
        # Extract the part after the colon
        parts = line.split(':', 1)
        if len(parts) < 2:
            continue
            
        sources_str = parts[1]
        matches = re.findall(r'\[\[([^\]]+)\]\]', sources_str)
        for m in matches:
            links.add(m.strip())
            
    return links

def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else '/Users/takagishota/Documents/KnowledgeBase/00_Concepts_Index.md'
    
    print(f"Validating links in: {filepath}")
    
    # 1. Get existing files from GCS
    existing_files = get_gcs_files(BUCKET_NAME)
    
    if not existing_files:
        print("No files found in GCS or access failed. Aborting.")
        return

    # 2. Get links from Index
    linked_files = parse_concepts_index(filepath)
    print(f"Found {len(linked_files)} unique linked sources in Index.")
    
    # 3. Validation
    missing = []
    for link in linked_files:
        # Check against basic filename (case-sensitive? usually Obsidian is)
        # Note: GCS filenames might have folders, but we indexed basenames.
        # Wikilinks usually refer to the filename without path.
        if link not in existing_files:
            missing.append(link)
    
    print("\n=== Validation Results ===\n")
    if missing:
        print(f"Found {len(missing)} broken links (files not found in GCS):")
        for m in sorted(missing):
            print(f"- [[{m}]]")
    else:
        print("✅ All links are valid! All referenced files exist in GCS.")

if __name__ == "__main__":
    main()
