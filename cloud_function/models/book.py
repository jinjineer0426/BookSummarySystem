from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class Chapter:
    number: int
    title: str
    content: str
    token_count: int = 0
    summary: Optional[str] = None
    concepts: List[str] = field(default_factory=list)

@dataclass
class Book:
    title: str
    author: str
    chapters: List[Chapter] = field(default_factory=list)
    total_chapters: int = 0
    file_id: Optional[str] = None
    job_id: Optional[str] = None

@dataclass
class SummaryResult:
    chapter_number: int
    summary_text: str
    concepts: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
