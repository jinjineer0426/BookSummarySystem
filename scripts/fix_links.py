#!/usr/bin/env python3
"""
Fix Links in Concepts Index
Applies specific string replacements to fix broken links identified in validation.
"""

import sys
from pathlib import Path

REPLACEMENTS = {
    # 1. Space differences
    "“超”分析の実践：業務効率を改善する –ファミレスチェーンの利益率を向上させるには- - Japan - Kearney": "“超”分析の実践：業務効率を改善する  –ファミレスチェーンの利益率を向上させるには- - Japan - Kearney",
    "「チームの役割」を統合したら13の役割になりました ーライス大学らの研究ー｜紀藤 康行 強み先生": "「チームの役割」を統合したら13の役割になりました　ーライス大学らの研究ー｜紀藤 康行  強み先生",
    "「作ってから売る」と「売ってから作る」と「売れるようにしてから作る」 ～技術の社会実装のための『開発』～": "「作ってから売る」と「売ってから作る」と「売れるようにしてから作る」　～技術の社会実装のための『開発』～",
    
    # 2. PDF / Title mismatches
    "ナシーム・ニコラス・タレブ_反脆弱性_上.pdf": "ナシーム・ニコラス・タレブ 反脆弱性 上",
    "太郎丸博_人文•社会科学のためのカテゴリカル・データ解析入門.pdf": "太郎丸博_人文•社会科学のためのカテゴリカル・データ解析入門",
    # Note: simple filename replacement - careful not to replace parts of others if shorter matches
    # Using specific target for the one lacking Author prefix
    "[[人文・社会科学のためのカテゴリカル・データ解析入門]]": "[[太郎丸博_人文•社会科学のためのカテゴリカル・データ解析入門]]"
}

def main():
    filepath = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/Users/takagishota/Documents/KnowledgeBase/00_Concepts_Index.md')
    
    print(f"Reading {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content
    count = 0
    
    # Simple string replacement for most
    for old, new in REPLACEMENTS.items():
        if old in new_content:
            new_content = new_content.replace(old, new)
            print(f"Replaced: {old[:30]}... -> {new[:30]}...")
            count += 1
        else:
            print(f"Warning: Could not find '{old[:30]}...'")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"Fixed {count} link types in {filepath}")

if __name__ == "__main__":
    main()
