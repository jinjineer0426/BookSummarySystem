import os
import time
import json
import re
import ssl
from typing import Optional, Dict, Any, List
from google import genai
from google.genai import types
from config import GEMINI_API_KEY

class GeminiService:
    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set.")
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.model_name = 'gemini-2.5-flash'
        self.embedding_model = "text-embedding-004"

    def generate_content(self, content: Any, max_retries: int = 3, model_name: Optional[str] = None) -> Optional[Dict]:
        """Call Gemini with retry logic including SSL error handling. Content can be str or list (for vision)."""
        target_model = model_name if model_name else self.model_name
        
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=target_model,
                    contents=content,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=8192,
                        response_mime_type="application/json"
                    )
                )
                
                cleaned_text = response.text.strip()
                if cleaned_text.startswith("```"):
                    cleaned_text = re.sub(r"^```json\s*", "", cleaned_text)
                    cleaned_text = re.sub(r"^```\s*", "", cleaned_text)
                    cleaned_text = re.sub(r"\s*```$", "", cleaned_text)
                
                return json.loads(cleaned_text)
                
            except json.JSONDecodeError as e:
                print(f"  JSON error (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(3)
                continue
                
            except (ssl.SSLError, ConnectionError, OSError) as e:
                wait_time = 10 * (attempt + 1)
                print(f"  Connection error (attempt {attempt+1}): {e}")
                print(f"  Waiting {wait_time}s before retry...")
                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                continue
                
            except Exception as e:
                error_str = str(e)
                print(f"  API error (attempt {attempt+1}): {e}")
                
                if "ssl" in error_str.lower() or "eof" in error_str.lower() or "connection" in error_str.lower():
                    wait_time = 10 * (attempt + 1)
                    print(f"  Connection issue detected - waiting {wait_time}s...")
                    if attempt < max_retries - 1:
                        time.sleep(wait_time)
                elif "429" in error_str or "quota" in error_str.lower():
                    print("  Rate limit - waiting 60s...")
                    time.sleep(60)
                elif attempt < max_retries - 1:
                    time.sleep(5)
                continue
        
        return None

    def get_embedding(self, text: str) -> List[float]:
        """Get text embedding."""
        result = self.client.models.embed_content(
            model=self.embedding_model,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="SEMANTIC_SIMILARITY"
            )
        )
        return result.embeddings[0].values
