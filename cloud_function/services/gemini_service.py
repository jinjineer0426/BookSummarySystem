import os
import time
import json
import re
import ssl
import sys
import google.generativeai as genai
from typing import Optional, Dict, Any, List
from config import GEMINI_API_KEY, get_config_value

from services.logging_service import get_logger

class GeminiService:
    def __init__(self):
        logger = get_logger()
        logger.debug("GeminiService.__init__ started")
        if not GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY is not set.")
            raise ValueError("GEMINI_API_KEY is not set.")
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            # Fetch model name from config (GCS > Env > Default)
            self.model_name = get_config_value(
                "gemini.model_id",
                "GEMINI_MODEL_ID",
                "gemini-2.5-flash"
            )
            self.embedding_model = "models/text-embedding-004"
            logger.debug(f"GeminiService initialized with model {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to configure genai: {e}")
            raise

    def generate_content(
        self, 
        content: Any, 
        max_retries: int = 3, 
        model_name: Optional[str] = None,
        response_schema: Optional[Any] = None
    ) -> Optional[Dict]:
        """Call Gemini with retry logic."""
        target_model_name = model_name if model_name else self.model_name
        logger = get_logger()
        
        logger.debug(f"generate_content for model {target_model_name}")
        
        
        gen_config_args = {
            "temperature": 0.2,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
            "response_mime_type": "application/json",
        }
        
        if response_schema:
            gen_config_args["response_schema"] = response_schema
            
        generation_config = genai.types.GenerationConfig(**gen_config_args)
        
        logger.debug(f"Generation Config: {generation_config}")
        
        model = genai.GenerativeModel(
            model_name=target_model_name,
            generation_config=generation_config,
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
                    logger.warning(f"Empty response text (attempt {attempt+1}). Finish reason: {finish_reason}")
                    if attempt < max_retries - 1:
                        time.sleep(3)
                    continue

                cleaned_text = response.text.strip()
                if cleaned_text.startswith("```"):
                    cleaned_text = re.sub(r"^```json\s*", "", cleaned_text)
                    cleaned_text = re.sub(r"^```\s*", "", cleaned_text)
                    cleaned_text = re.sub(r"\s*```$", "", cleaned_text)
                
                return json.loads(cleaned_text)
                
            except json.JSONDecodeError as e:
                finish_reason = "Unknown"
                if response.candidates:
                    finish_reason = response.candidates[0].finish_reason.name
                
                logger.error(f"JSON Parse Error (attempt {attempt+1}). Finish Reason: {finish_reason}. Error: {e}")
                
                # Log a truncated version of the raw text to avoid spamming massive logs
                raw_preview = response.text[:1000] + "..." if len(response.text) > 1000 else response.text
                logger.error(f"Raw Response Preview: {raw_preview}")
                
                if attempt < max_retries - 1:
                    time.sleep(3)
                continue
                
            except Exception as e:
                error_str = str(e)
                logger.warning(f"API error (attempt {attempt+1}): {e}")
                
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
