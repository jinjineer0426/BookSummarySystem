import json
from datetime import datetime
from google.cloud import storage
from config import BUCKET_NAME, OBSIDIAN_BUCKET_NAME

class GcsService:
    def __init__(self):
        self.client = storage.Client()
        self.bucket_name = BUCKET_NAME
        self.obsidian_bucket_name = OBSIDIAN_BUCKET_NAME
        self._concepts_cache = None
        self._categories_cache = None
        # Batch buffers for rate limit prevention
        self._pending_concepts_buffer = []
        self._pending_categories_buffer = []

    @property
    def bucket(self):
        return self.client.bucket(self.bucket_name)

    @property
    def obsidian_bucket(self):
        return self.client.bucket(self.obsidian_bucket_name)

    def write_to_obsidian_vault(self, path: str, content: str) -> str:
        """Writes content to the Obsidian vault GCS bucket."""
        blob = self.obsidian_bucket.blob(path)
        blob.upload_from_string(
            content.encode('utf-8'), 
            content_type='text/markdown; charset=utf-8'
        )
        return f"gs://{self.obsidian_bucket_name}/{path}"
    
    def read_obsidian_file(self, path: str) -> str:
        """Reads content from the Obsidian vault GCS bucket."""
        blob = self.obsidian_bucket.blob(path)
        if blob.exists():
            return blob.download_as_text()
        return ""

    # === Master List Management ===
    
    def get_concepts(self) -> dict:
        if self._concepts_cache is None:
            blob = self.bucket.blob("config/master_concepts.json")
            if blob.exists():
                self._concepts_cache = json.loads(blob.download_as_text())
            else:
                self._concepts_cache = {"concepts": {}}
        return self._concepts_cache
    
    def get_categories(self) -> dict:
        if self._categories_cache is None:
            blob = self.bucket.blob("config/master_categories.json")
            if blob.exists():
                self._categories_cache = json.loads(blob.download_as_text())
            else:
                self._categories_cache = self._default_categories()
        return self._categories_cache
    
    def save_concepts(self, data: dict):
        data["last_updated"] = datetime.now().isoformat()
        blob = self.bucket.blob("config/master_concepts.json")
        blob.upload_from_string(json.dumps(data, ensure_ascii=False, indent=2))
        self._concepts_cache = data
    
    def add_pending_concept(self, concept: str, context: dict):
        """Adds a concept to the in-memory buffer (does NOT write to GCS immediately)."""
        self._pending_concepts_buffer.append({
            "name": concept,
            "context": context
        })
    
    def flush_pending_concepts(self):
        """Flushes all buffered pending concepts to GCS in a single write."""
        if not self._pending_concepts_buffer:
            return
        
        blob = self.bucket.blob("config/pending_concepts.json")
        if blob.exists():
            pending = json.loads(blob.download_as_text())
        else:
            pending = {"concepts": []}
        
        for item in self._pending_concepts_buffer:
            concept = item["name"]
            context = item["context"]
            
            existing = next((c for c in pending["concepts"] if c["name"] == concept), None)
            if existing:
                existing["count"] += 1
                if context["source"] not in existing["sources"]:
                    existing["sources"].append(context["source"])
            else:
                pending["concepts"].append({
                    "name": concept,
                    "count": 1,
                    "suggested_category": context.get("category"),
                    "sources": [context["source"]],
                    "first_seen": datetime.now().isoformat()
                })
        
        blob.upload_from_string(json.dumps(pending, ensure_ascii=False, indent=2))
        self._pending_concepts_buffer = []  # Clear buffer after flush
        print(f"Flushed {len(self._pending_concepts_buffer)} pending concepts to GCS")
        
    def add_pending_category(self, category: str, parent: str):
        """Adds a category to the in-memory buffer (does NOT write to GCS immediately)."""
        self._pending_categories_buffer.append({
            "name": category,
            "parent": parent
        })
    
    def flush_pending_categories(self):
        """Flushes all buffered pending categories to GCS in a single write."""
        if not self._pending_categories_buffer:
            return
        
        blob = self.bucket.blob("config/pending_categories.json")
        if blob.exists():
            pending = json.loads(blob.download_as_text())
        else:
            pending = {"categories": []}
        
        for item in self._pending_categories_buffer:
            category = item["name"]
            parent = item["parent"]
            
            existing = next((c for c in pending["categories"] 
                            if c["name"] == category and c["parent"] == parent), None)
            if existing:
                existing["count"] += 1
            else:
                pending["categories"].append({
                    "name": category,
                    "parent": parent,
                    "count": 1,
                    "first_seen": datetime.now().isoformat()
                })
        
        blob.upload_from_string(json.dumps(pending, ensure_ascii=False, indent=2))
        self._pending_categories_buffer = []  # Clear buffer after flush
        print(f"Flushed {len(self._pending_categories_buffer)} pending categories to GCS")
    
    def flush_all_pending(self):
        """Flushes all pending data (concepts and categories) to GCS."""
        self.flush_pending_concepts()
        self.flush_pending_categories()
    
    def _default_categories(self) -> dict:
        return {
            "分類": {
                "人文": {
                    "subcategories": ["哲学", "歴史", "心理学", "社会学"],
                    "allowNew": False
                },
                "ビジネス": {
                    "subcategories": ["戦略", "マーケティング", "組織", "リーダーシップ", "会計"],
                    "allowNew": True,
                    "pendingThreshold": 3
                },
                "技術": {
                    "subcategories": ["ソフトウエア", "データサイエンス", "品質", "インフラ"],
                    "allowNew": True,
                    "pendingThreshold": 3
                }
            }
        }
