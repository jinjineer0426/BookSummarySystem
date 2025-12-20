"""
Configuration Loader Service - Loads config from GCS with caching.

This service provides a Single Source of Truth for system configuration
by loading settings from GCS storage, with environment variable fallback.
"""
import json
import time
from typing import Any, Optional
from google.cloud import storage


class ConfigLoader:
    """Loads configuration from GCS with local cache and fallback."""
    
    def __init__(self, bucket_name: str, config_path: str = "config/system_config.json", cache_ttl: int = 0):
        """
        Initialize the config loader.
        
        Args:
            bucket_name: GCS bucket name
            config_path: Path to config file in GCS (default: config/system_config.json)
            cache_ttl: Cache TTL in seconds. 0 = no caching (default), recommended for dev.
                       Set to 300+ for production if needed.
        """
        self.bucket_name = bucket_name
        self.config_path = config_path
        self._cache = None
        self._cache_time = None
        self.CACHE_TTL = cache_ttl  # 0 = no caching (dev mode)
        self._client = None
    
    def _get_storage_client(self):
        """Lazy initialization of storage client."""
        if self._client is None:
            self._client = storage.Client()
        return self._client
    
    def get_config(self, force_refresh: bool = False) -> dict:
        """
        Returns cached or fresh config from GCS.
        
        Args:
            force_refresh: If True, bypasses cache and reloads from GCS
            
        Returns:
            Configuration dictionary
        """
        # Check cache validity (skip if caching disabled)
        if not force_refresh and self.CACHE_TTL > 0 and self._cache is not None:
            if self._cache_time and (time.time() - self._cache_time) < self.CACHE_TTL:
                return self._cache
        
        # Load from GCS
        try:
            client = self._get_storage_client()
            bucket = client.bucket(self.bucket_name)
            blob = bucket.blob(self.config_path)
            
            if not blob.exists():
                print(f"Warning: Config file {self.config_path} not found in GCS. Using defaults.")
                return self._get_default_config()
            
            config_text = blob.download_as_text()
            config = json.loads(config_text)
            
            # Update cache
            self._cache = config
            self._cache_time = time.time()
            
            print(f"Config loaded from GCS: {self.config_path}")
            return config
            
        except Exception as e:
            print(f"Error loading config from GCS: {e}. Using defaults/cache.")
            # Return cached config if available, otherwise defaults
            return self._cache if self._cache else self._get_default_config()
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get nested config value using dot notation.
        
        Args:
            key_path: Dot-separated path to config value (e.g., 'gemini.model_id')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
            
        Example:
            >>> loader.get('gemini.model_id', 'gemini-2.0-flash')
        """
        config = self.get_config()
        keys = key_path.split('.')
        
        value = config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def _get_default_config(self) -> dict:
        """
        Returns default configuration as fallback.
        
        This is used when GCS config is unavailable.
        """
        return {
            "version": "1.0",
            "gemini": {
                "model_id": "gemini-2.0-flash",
                "toc_extraction_model": "gemini-2.0-flash-exp"
            },
            "processing": {
                "toc_scan_start_page": 3,
                "toc_scan_end_page": 30,
                "toc_image_dpi": 100,
                "similarity_threshold": 0.82
            },
            "notifications": {
                "alert_email": "",
                "enabled": False
            }
        }
