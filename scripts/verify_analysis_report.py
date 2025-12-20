import sys
import os
from unittest.mock import MagicMock
from datetime import datetime

# Add the cloud_function directory to the path so we can import services
sys.path.append(os.path.join(os.getcwd(), 'cloud_function'))

from services.analysis_service import AnalysisService

def test_analysis_report():
    print("Testing AnalysisService.publish_weekly_report()...")
    
    # Mock GCS Service
    mock_gcs = MagicMock()
    
    # Mock reading the index file
    mock_gcs.read_obsidian_file.return_value = """
# Concepts Index

- [[Business Strategy]]: [[Book A]], [[Book B]]
- [[Innovation]]: [[Book A]]
- [[Innovation (Concept)]]: [[Book C]]
- [[Marketing]]: [[Book B]]
- [[Strategy]]: [[Book D]]
- [[Business Strategy]]: [[Book E]] 
    """
    
    # Mock write_to_obsidian_vault to just print the content
    def mock_write(path, content):
        print(f"\n[Mock GCS Write] Path: {path}")
        print("--- Content Start ---")
        print(content)
        print("--- Content End ---")
        return f"gs://bucket/{path}"
        
    mock_gcs.write_to_obsidian_vault = mock_write
    
    # Initialize Service
    service = AnalysisService(mock_gcs)
    
    # Run
    result = service.publish_weekly_report()
    
    print("\nResult:")
    print(result)

if __name__ == "__main__":
    test_analysis_report()
