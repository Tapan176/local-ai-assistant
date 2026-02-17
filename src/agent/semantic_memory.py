"""
Semantic Memory - Vector-based storage for long-term memory.
Uses Ollama embeddings and portable JSON storage for vectors.
"""
import json
import math
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.brain.ollama_backend import get_ollama

class SemanticMemory:
  """
  Manages semantic memories with vector embeddings.
  Stores data in a local JSON file for portability (vectors + metadata).
  Syncs text content with SQLite (optional, or just keeps references).
  """

  def __init__(self, data_dir: Path):
    self.data_dir = Path(data_dir)
    self.memory_file = self.data_dir / "semantic_memories.json"
    self.ollama = get_ollama()
    self.memories = self._load_memories()

  def _load_memories(self) -> List[Dict]:
    """Load memories from JSON storage."""
    if not self.memory_file.exists():
      return []
    try:
      with open(self.memory_file, 'r', encoding='utf-8') as f:
        return json.load(f)
    except Exception as e:
      print(f"[SemanticMemory] Error loading memories: {e}")
      return []

  def _save_memories(self):
    """Save memories to JSON storage."""
    try:
      # Atomic write pattern to prevent corruption
      temp_file = self.memory_file.with_suffix('.tmp')
      with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(self.memories, f, ensure_ascii=False, indent=2)
      temp_file.replace(self.memory_file)
    except Exception as e:
      print(f"[SemanticMemory] Error saving memories: {e}")

  def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
      return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = math.sqrt(sum(a * a for a in vec1))
    norm_b = math.sqrt(sum(b * b for b in vec2))
    
    if norm_a == 0 or norm_b == 0:
      return 0.0
      
    return dot_product / (norm_a * norm_b)

  def remember(self, text: str, metadata: Dict[str, Any] = None) -> bool:
    """
    Embed and store a memory.
    Returns True if successful.
    """
    if not text:
      return False

    # Get embedding
    vector = self.ollama.embeddings(text)
    if not vector:
      print(f"[SemanticMemory] Failed to get embedding for: {text[:30]}...")
      return False

    memory_item = {
      "id": int(time.time() * 1000),
      "text": text,
      "vector": vector,
      "metadata": metadata or {},
      "timestamp": time.time(),
      "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    self.memories.append(memory_item)
    self._save_memories()
    return True

  def search(self, query: str, limit: int = 5, threshold: float = 0.4) -> List[Dict]:
    """
    Search memories by semantic similarity.
    """
    if not self.memories:
      return []

    query_vector = self.ollama.embeddings(query)
    if not query_vector:
      return []

    results = []
    for mem in self.memories:
      score = self._cosine_similarity(query_vector, mem.get("vector", []))
      if score >= threshold:
        results.append({
          "text": mem["text"],
          "metadata": mem.get("metadata", {}),
          "score": score,
          "timestamp": mem.get("timestamp")
        })

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]

  def delete_by_string(self, text_substring: str) -> int:
    """Delete memories containing specific text substring."""
    initial_count = len(self.memories)
    self.memories = [m for m in self.memories if text_substring.lower() not in m["text"].lower()]
    deleted_count = initial_count - len(self.memories)
    
    if deleted_count > 0:
      self._save_memories()
      
    return deleted_count

  def clear(self):
    """Clear all semantic memories."""
    self.memories = []
    self._save_memories()
