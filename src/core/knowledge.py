"""
Knowledge Manager - Simple RAG using TF-IDF (no external APIs)
Indexes documents and enables semantic search
"""
import sqlite3
import math
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Tuple, Optional


class KnowledgeManager:
  """Simple RAG implementation using TF-IDF for offline operation"""

  def __init__(self, db_path, data_dir):
    self.db_path = Path(db_path)
    self.data_dir = Path(data_dir)
    self.vault_dir = self.data_dir / "vault"
    self.vault_dir.mkdir(parents=True, exist_ok=True)
    self._init_db()

    # Stop words for TF-IDF
    self.stop_words = {
      'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
      'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
      'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
      'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
      'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we',
      'they', 'what', 'which', 'who', 'when', 'where', 'why', 'how', 'all',
      'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such',
      'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very'
    }

  def _init_db(self):
    """Initialize knowledge database"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    # Documents table
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        source_type TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    """)

    # Chunks table for document segments
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id INTEGER NOT NULL,
        chunk_text TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        FOREIGN KEY (doc_id) REFERENCES documents(id)
      )
    """)

    # TF-IDF vectors (simplified storage)
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS tfidf_vectors (
        chunk_id INTEGER NOT NULL,
        term TEXT NOT NULL,
        tfidf_score REAL NOT NULL,
        PRIMARY KEY (chunk_id, term),
        FOREIGN KEY (chunk_id) REFERENCES chunks(id)
      )
    """)

    # Document frequency for IDF calculation
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS doc_freq (
        term TEXT PRIMARY KEY,
        doc_count INTEGER NOT NULL
      )
    """)

    conn.commit()
    conn.close()

  def _tokenize(self, text: str) -> List[str]:
    """Tokenize and clean text"""
    # Convert to lowercase and split
    text = text.lower()
    # Remove special characters, keep alphanumeric
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    # Split and filter
    tokens = [
      word for word in text.split()
      if word not in self.stop_words and len(word) > 2
    ]
    return tokens

  def _chunk_text(self, text: str, chunk_size: int = 500) -> List[str]:
    """Split text into chunks"""
    # Split by paragraphs first
    paragraphs = text.split('\n\n')

    chunks = []
    current_chunk = ""

    for para in paragraphs:
      para = para.strip()
      if not para:
        continue

      if len(current_chunk) + len(para) < chunk_size:
        current_chunk += " " + para if current_chunk else para
      else:
        if current_chunk:
          chunks.append(current_chunk)
        current_chunk = para

    if current_chunk:
      chunks.append(current_chunk)

    return chunks if chunks else [text[:chunk_size]]

  def _calculate_tf(self, tokens: List[str]) -> Dict[str, float]:
    """Calculate term frequency"""
    tf = defaultdict(int)
    for token in tokens:
      tf[token] += 1

    # Normalize
    total = len(tokens)
    return {term: count / total for term, count in tf.items()}

  def _update_idf(self):
    """Recalculate IDF scores"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    # Get total document count
    cursor.execute("SELECT COUNT(DISTINCT doc_id) FROM chunks")
    total_docs = cursor.fetchone()[0]

    if total_docs == 0:
      conn.close()
      return

    # Recalculate document frequencies
    cursor.execute("DELETE FROM doc_freq")

    cursor.execute("""
      INSERT INTO doc_freq (term, doc_count)
      SELECT term, COUNT(DISTINCT c.doc_id)
      FROM tfidf_vectors tv
      JOIN chunks c ON tv.chunk_id = c.id
      GROUP BY term
    """)

    conn.commit()
    conn.close()

  def ingest_file(self, file_path: str) -> str:
    """Ingest a file into the knowledge base

    Supports: .txt, .md

    Args:
      file_path: Path to the file to ingest

    Returns:
      Success message
    """
    path = Path(file_path)

    if not path.exists():
      # Check in vault directory
      vault_path = self.vault_dir / path.name
      if vault_path.exists():
        path = vault_path
      else:
        return f"❌ File not found: {file_path}"

    # Read file
    try:
      with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    except Exception as e:
      return f"❌ Error reading file: {e}"

    # Determine source type
    suffix = path.suffix.lower()
    if suffix in ['.txt', '.md', '.markdown']:
      source_type = 'text'
    else:
      return f"❌ Unsupported file type: {suffix}"

    # Store document
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute(
      "INSERT INTO documents (source, source_type, content) VALUES (?, ?, ?)",
      (str(path.name), source_type, content)
    )
    doc_id = cursor.lastrowid

    # Chunk and index
    chunks = self._chunk_text(content)

    for i, chunk in enumerate(chunks):
      cursor.execute(
        "INSERT INTO chunks (doc_id, chunk_text, chunk_index) VALUES (?, ?, ?)",
        (doc_id, chunk, i)
      )
      chunk_id = cursor.lastrowid

      # Calculate TF
      tokens = self._tokenize(chunk)
      tf = self._calculate_tf(tokens)

      # Store TF scores (IDF will be applied during search)
      for term, tf_score in tf.items():
        cursor.execute(
          "INSERT INTO tfidf_vectors (chunk_id, term, tfidf_score) VALUES (?, ?, ?)",
          (chunk_id, term, tf_score)
        )

    conn.commit()
    conn.close()

    # Update IDF
    self._update_idf()

    return f"✓ Ingested: {path.name} ({len(chunks)} chunks)"

  def ingest_from_memory(self, memories: List[Tuple[str, str]]) -> int:
    """Ingest memories into knowledge base

    Args:
      memories: List of (text, timestamp) tuples

    Returns:
      Number of items ingested
    """
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    count = 0
    for text, timestamp in memories:
      cursor.execute(
        "INSERT INTO documents (source, source_type, content) VALUES (?, ?, ?)",
        (f"memory_{timestamp}", 'memory', text)
      )
      doc_id = cursor.lastrowid

      # Single chunk for memories
      cursor.execute(
        "INSERT INTO chunks (doc_id, chunk_text, chunk_index) VALUES (?, ?, ?)",
        (doc_id, text, 0)
      )
      chunk_id = cursor.lastrowid

      # Index
      tokens = self._tokenize(text)
      tf = self._calculate_tf(tokens)

      for term, tf_score in tf.items():
        cursor.execute(
          "INSERT INTO tfidf_vectors (chunk_id, term, tfidf_score) VALUES (?, ?, ?)",
          (chunk_id, term, tf_score)
        )

      count += 1

    conn.commit()
    conn.close()

    self._update_idf()
    return count

  def search(self, query: str, top_k: int = 5) -> List[Dict]:
    """Search knowledge base using TF-IDF similarity

    Args:
      query: Search query
      top_k: Number of results to return

    Returns:
      List of matching chunks with scores
    """
    query_tokens = self._tokenize(query)

    if not query_tokens:
      return []

    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    # Get total document count
    cursor.execute("SELECT COUNT(DISTINCT doc_id) FROM chunks")
    total_docs = cursor.fetchone()[0]

    if total_docs == 0:
      conn.close()
      return []

    # Calculate query TF
    query_tf = self._calculate_tf(query_tokens)

    # Score each chunk
    chunk_scores = defaultdict(float)

    for term, tf_score in query_tf.items():
      # Get IDF
      cursor.execute("SELECT doc_count FROM doc_freq WHERE term = ?", (term,))
      result = cursor.fetchone()
      if result:
        doc_count = result[0]
        idf = math.log(total_docs / (1 + doc_count))
      else:
        continue  # Term not in any document

      query_tfidf = tf_score * idf

      # Find chunks containing this term
      cursor.execute(
        """SELECT chunk_id, tfidf_score FROM tfidf_vectors WHERE term = ?""",
        (term,)
      )
      for chunk_id, chunk_tf in cursor.fetchall():
        chunk_tfidf = chunk_tf * idf
        # Cosine similarity component
        chunk_scores[chunk_id] += query_tfidf * chunk_tfidf

    # Get top results
    top_chunks = sorted(chunk_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

    results = []
    for chunk_id, score in top_chunks:
      cursor.execute(
        """SELECT c.chunk_text, d.source, d.source_type
           FROM chunks c
           JOIN documents d ON c.doc_id = d.id
           WHERE c.id = ?""",
        (chunk_id,)
      )
      row = cursor.fetchone()
      if row:
        results.append({
          'text': row[0],
          'source': row[1],
          'source_type': row[2],
          'score': score
        })

    conn.close()
    return results

  def build_context(self, query: str, max_context_length: int = 2000) -> str:
    """Build context string for LLM from relevant documents

    Args:
      query: User's question
      max_context_length: Maximum context length

    Returns:
      Context string for LLM
    """
    results = self.search(query, top_k=5)

    if not results:
      return ""

    context_parts = []
    current_length = 0

    for result in results:
      text = result['text']
      source = result['source']

      # Format chunk
      chunk_text = f"[From {source}]: {text}"

      if current_length + len(chunk_text) > max_context_length:
        break

      context_parts.append(chunk_text)
      current_length += len(chunk_text)

    return "\n\n".join(context_parts)

  def get_stats(self) -> Dict:
    """Get knowledge base statistics"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM documents")
    doc_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM chunks")
    chunk_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT term) FROM tfidf_vectors")
    term_count = cursor.fetchone()[0]

    cursor.execute("SELECT source_type, COUNT(*) FROM documents GROUP BY source_type")
    by_type = dict(cursor.fetchall())

    conn.close()

    return {
      'documents': doc_count,
      'chunks': chunk_count,
      'unique_terms': term_count,
      'by_type': by_type
    }

  def gather_all_context(self, query: str, memory_db: Optional[Path] = None, 
              journal_db: Optional[Path] = None, max_items: int = 10) -> str:
    """Gather context from all sources for RAG

    Args:
      query: User's question
      memory_db: Path to memory database
      journal_db: Path to journal database
      max_items: Maximum items per source

    Returns:
      Combined context string
    """
    context_parts = []

    # 1. Search knowledge base
    kb_results = self.search(query, top_k=max_items // 2)
    if kb_results:
      context_parts.append("=== Knowledge Base ===")
      for r in kb_results:
        context_parts.append(f"[{r['source']}]: {r['text'][:200]}")

    # 2. Search memories if available
    if memory_db and memory_db.exists():
      memories = self._search_memories(memory_db, query, max_items // 2)
      if memories:
        context_parts.append("\n=== Memories ===")
        for text, category, ts in memories:
          context_parts.append(f"[{category} - {ts[:10]}]: {text[:150]}")

    # 3. Search journal if available
    if journal_db and journal_db.exists():
      journals = self._search_journal(journal_db, query, max_items // 2)
      if journals:
        context_parts.append("\n=== Journal Entries ===")
        for text, date, tags in journals:
          tag_str = f" #{tags}" if tags else ""
          context_parts.append(f"[{date}]: {text[:150]}{tag_str}")

    return "\n".join(context_parts)

  def _search_memories(self, db_path: Path, query: str, limit: int) -> List[Tuple]:
    """Search memories database"""
    import sqlite3

    try:
      conn = sqlite3.connect(db_path)
      cursor = conn.cursor()

      # Simple keyword search
      keywords = self._tokenize(query)
      if not keywords:
        return []

      # Build search query
      conditions = " OR ".join(["text LIKE ?" for _ in keywords])
      params = [f"%{kw}%" for kw in keywords]

      cursor.execute(f"""
        SELECT text, category, timestamp 
        FROM memories 
        WHERE {conditions}
        ORDER BY timestamp DESC
        LIMIT ?
      """, params + [limit])

      results = cursor.fetchall()
      conn.close()
      return results
    except Exception:
      return []

  def _search_journal(self, db_path: Path, query: str, limit: int) -> List[Tuple]:
    """Search journal database"""
    import sqlite3

    try:
      conn = sqlite3.connect(db_path)
      cursor = conn.cursor()

      keywords = self._tokenize(query)
      if not keywords:
        return []

      conditions = " OR ".join(["entry_text LIKE ?" for _ in keywords])
      params = [f"%{kw}%" for kw in keywords]

      cursor.execute(f"""
        SELECT entry_text, entry_date, tags
        FROM journal_entries
        WHERE {conditions}
        ORDER BY entry_date DESC
        LIMIT ?
      """, params + [limit])

      results = cursor.fetchall()
      conn.close()
      return results
    except Exception:
      return []

  def ingest_all_data(self, memory_db: Optional[Path] = None, journal_db: Optional[Path] = None) -> str:
    """Ingest all memories and journal entries into knowledge base

    Args:
      memory_db: Path to memory database
      journal_db: Path to journal database

    Returns:
      Status message
    """
    count = 0

    # Ingest memories
    if memory_db and memory_db.exists():
      import sqlite3
      conn = sqlite3.connect(memory_db)
      cursor = conn.cursor()
      cursor.execute("SELECT text, timestamp FROM memories")
      memories = cursor.fetchall()
      conn.close()

      if memories:
        count += self.ingest_from_memory(memories)

    # Ingest journal entries
    if journal_db and journal_db.exists():
      import sqlite3
      conn = sqlite3.connect(journal_db)
      cursor = conn.cursor()
      cursor.execute("SELECT entry_text, entry_date FROM journal_entries")
      entries = cursor.fetchall()
      conn.close()

      for text, date in entries:
        self._ingest_single(text, f"journal_{date}", 'journal')
        count += 1

    self._update_idf()
    return f"✓ Indexed {count} documents into knowledge base"

  def _ingest_single(self, text: str, source: str, source_type: str):
    """Ingest a single document"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute(
      "INSERT INTO documents (source, source_type, content) VALUES (?, ?, ?)",
      (source, source_type, text)
    )
    doc_id = cursor.lastrowid

    # Single chunk for short documents
    cursor.execute(
      "INSERT INTO chunks (doc_id, chunk_text, chunk_index) VALUES (?, ?, ?)",
      (doc_id, text, 0)
    )
    chunk_id = cursor.lastrowid

    # Index
    tokens = self._tokenize(text)
    tf = self._calculate_tf(tokens)

    for term, tf_score in tf.items():
      cursor.execute(
        "INSERT INTO tfidf_vectors (chunk_id, term, tfidf_score) VALUES (?, ?, ?)",
        (chunk_id, term, tf_score)
      )

    conn.commit()
    conn.close()
