
import sys
import os
import re

# Add the cloud_function directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../cloud_function')))

try:
    from services.pdf_processor import PdfProcessor
except ImportError as e:
    print(f"Failed to import PdfProcessor: {e}")
    sys.exit(1)

def test_chapter_regex_class():
    # The problematic text pattern from "Strategy Game"
    text = """
    目次
    
    第一部では「WHO以前の問題」と題して、消費者行動の規則性を解明することを目的としている。
    個々の顧客の生活文脈や感情に即したミクロなインサイトを掘り下げる「顧客理解」が注目される中...
    
    第二部では「WHAT以前の問題」と題して、商品や価格に関する規則性を...
    
    第3章 今後の展望
    本章では...
    """
    
    processor = PdfProcessor()
    
    print("\n--- Testing PdfProcessor.split_into_chapters ---")
    chapters = processor.split_into_chapters(text)
    
    for ch in chapters:
        print(f"DETECTED CHAPTER: '{ch['title']}'")
        
    # Validation logic
    titles = [ch['title'] for ch in chapters]
    
    # We expect "第3章 今後の展望" to be found.
    # We expect "第一部では..." to NOT be found as a chapter.
    
    if any("第一部では" in t for t in titles):
        print("\nFAILURE: Incorrectly detected '第一部では...' as a chapter.")
    else:
        print("\nSUCCESS: Correctly ignored '第一部では...'.")
        
    if any("第3章" in t for t in titles):
        print("SUCCESS: Correctly detected '第3章'.")
    else:
        print("FAILURE: Failed to detect '第3章'.")

if __name__ == "__main__":
    test_chapter_regex_class()
