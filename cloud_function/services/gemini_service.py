import os
import time
import json
import re
import ssl
import sys
import google.generativeai as genai
from typing import Optional, Dict, Any, List
from config import GEMINI_API_KEY

print("DEBUG: Initializing GeminiService", file=sys.stderr)

class GeminiService:
    def __init__(self):
        print("DEBUG: GeminiService.__init__ started", file=sys.stderr)
        if not GEMINI_API_KEY:
            print("ERROR: GEMINI_API_KEY not found", file=sys.stderr)
            raise ValueError("GEMINI_API_KEY is not set.")
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            # Use gemini-2.5-flash for higher quota limits
            self.model_name = 'gemini-2.5-flash'
            self.embedding_model = "models/text-embedding-004"
            print(f"DEBUG: GeminiService initialized with model {self.model_name}", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: Failed to configure genai: {e}", file=sys.stderr)
            raise

    def generate_content(self, content: Any, max_retries: int = 3, model_name: Optional[str] = None) -> Optional[Dict]:
        """Call Gemini with retry logic."""
        target_model_name = model_name if model_name else self.model_name
        
        print(f"DEBUG: generate_content for model {target_model_name}", file=sys.stderr)
        
        model = genai.GenerativeModel(
            model_name=target_model_name,
            generation_config={
                "temperature": 0.2,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 8192,
                "response_mime_type": "application/json",
            },
            safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
        )
        
        for attempt in range(max_retries):
            try:
                # The legacy SDK handles list of [text, dict_image] natively
                response = model.generate_content(content)
                
                if not response.text:
                    finish_reason = "Unknown"
                    if response.candidates:
                        finish_reason = response.candidates[0].finish_reason.name
                    print(f"  Warning: Empty response text (attempt {attempt+1}). Finish reason: {finish_reason}", file=sys.stderr)
                    if attempt < max_retries - 1:
                        time.sleep(3)
                    continue

                cleaned_text = response.text.strip()
                if cleaned_text.startswith("```"):
                    cleaned_text = re.sub(r"^```json\s*", "", cleaned_text)
                    cleaned_text = re.sub(r"^```\s*", "", cleaned_text)
                    cleaned_text = re.sub(r"\s*```$", "", cleaned_text)
                
                return json.loads(cleaned_text)
                
            except Exception as e:
                error_str = str(e)
                print(f"  API error (attempt {attempt+1}): {e}", file=sys.stderr)
                
                if "429" in error_str or "quota" in error_str.lower():
                    time.sleep(60)
                elif "500" in error_str or "503" in error_str:
                    time.sleep(10)
                elif attempt < max_retries - 1:
                    time.sleep(5)
                continue
        
        return None

    def get_embedding(self, text: str) -> List[float]:
        """Get text embedding."""
        result = genai.embed_content(
            model=self.embedding_model,
            content=text,
            task_type="semantic_similarity"
        )
        return result['embedding']
