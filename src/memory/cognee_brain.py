"""
PHASE 15: Cognee Brain - Graph-Based Cognitive Memory

Architecture:
- SQLite = transactional truth (ACID)
- Cognee + Neo4j = reasoning layer (graph traversal)
- Decision engine reads from both

Knowledge Model:
- Person nodes
- Experience nodes (episodic)
- Preference nodes (semantic)
- Purchase nodes (financial)
- Habit nodes (behavioral)
- Mood nodes (emotional)
- Place nodes (spatial)

Relations:
- DID_WITH (person ↔ experience)
- SPENT_AT (purchase ↔ place)
- FELT_AFTER (mood ↔ experience)
- PREFERS (person ↔ preference)
- AFFECTED_HABIT (mood ↔ habit)
- MET_AT (person ↔ place)
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# Cognee imports
try:
  import cognee
  from cognee.api.v1.search import SearchType
  COGNEE_AVAILABLE = True
except ImportError:
  COGNEE_AVAILABLE = False
  pass

# Neo4j imports
try:
  from neo4j import GraphDatabase
  NEO4J_AVAILABLE = True
except ImportError:
  NEO4J_AVAILABLE = False
  pass


@dataclass
class MemoryNode:
  """Represents a node in the knowledge graph"""
  id: str
  type: str  # Person, Experience, Preference, Purchase, Habit, Mood, Place
  text: str
  domain: str  # memory, experience, relation, habit, finance
  timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
  metadata: Dict[str, Any] = field(default_factory=dict)
  source_id: Optional[int] = None  # SQLite row ID for provenance


@dataclass
class RecallResult:
  """Result from memory recall with provenance"""
  text: str
  node_id: str
  node_type: str
  confidence: float
  source: str  # "cognee", "neo4j", "sqlite"
  timestamp: str
  related_nodes: List[str] = field(default_factory=list)


class CogneeBrain:
  """
  Cognitive memory system using Cognee + Neo4j.

  Principles:
  1. NEVER invent data - only return what's in the graph
  2. Always cite source node IDs
  3. Multi-hop reasoning for complex queries
  4. SQLite remains source of truth
  """

  # Domain datasets for Cognee
  DOMAINS = {
    "memory": "tapan_memories",
    "experience": "tapan_experiences", 
    "relation": "tapan_relations",
    "habit": "tapan_habits",
    "finance": "tapan_finance",
    "mood": "tapan_moods",
  }

  def __init__(self, data_dir: Path, neo4j_uri: str = "bolt://localhost:7687",
         neo4j_user: str = "neo4j", neo4j_password: str = "password"):
    self.data_dir = Path(data_dir)
    self.neo4j_uri = neo4j_uri
    self.neo4j_user = neo4j_user
    self.neo4j_password = neo4j_password

    # Neo4j driver (lazy init)
    self._neo4j_driver = None

    # Cognee config
    self._cognee_initialized = False

    # Local cache for offline mode
    self._cache_dir = self.data_dir / "cognee_cache"
    self._cache_dir.mkdir(parents=True, exist_ok=True)

    # Initialize
    self._init_cognee()

  def _init_cognee(self):
    """Initialize Cognee with Neo4j backend"""
    if not COGNEE_AVAILABLE:
      return

    try:
      # Configure Cognee to use Neo4j
      # Note: Cognee config varies by version
      os.environ.setdefault("COGNEE_GRAPH_DB", "neo4j")
      os.environ.setdefault("NEO4J_URI", self.neo4j_uri)
      os.environ.setdefault("NEO4J_USER", self.neo4j_user)
      os.environ.setdefault("NEO4J_PASSWORD", self.neo4j_password)

      # Use Ollama for embeddings
      os.environ.setdefault("LLM_PROVIDER", "ollama")
      os.environ.setdefault("LLM_MODEL", "llama3.2:3b")
      os.environ.setdefault("EMBEDDING_PROVIDER", "ollama")
      os.environ.setdefault("EMBEDDING_MODEL", "nomic-embed-text")

      self._cognee_initialized = True
    except Exception as e:
      _ = e

  @property
  def neo4j_driver(self):
    """Lazy Neo4j driver initialization"""
    if self._neo4j_driver is None and NEO4J_AVAILABLE:
      try:
        self._neo4j_driver = GraphDatabase.driver(
          self.neo4j_uri,
          auth=(self.neo4j_user, self.neo4j_password)
        )
        # Verify connection
        self._neo4j_driver.verify_connectivity()
      except Exception as e:
        _ = e
        self._neo4j_driver = None
    return self._neo4j_driver

  def check_health(self) -> Dict[str, bool]:
    """Check health of all components"""
    return {
      "cognee": COGNEE_AVAILABLE and self._cognee_initialized,
      "neo4j": self.neo4j_driver is not None,
      "cache": self._cache_dir.exists(),
    }

  # ==================== REMEMBER (WRITE) ====================

  async def remember(self, text: str, domain: str, metadata: Optional[Dict] = None,
             source_id: Optional[int] = None) -> MemoryNode:
    """
    Add a memory to the cognitive graph.

    Args:
      text: The memory text
      domain: One of memory, experience, relation, habit, finance, mood
      metadata: Additional structured data
      source_id: SQLite row ID for provenance

    Returns:
      MemoryNode with assigned ID
    """
    # Create node
    node = MemoryNode(
      id=f"{domain}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
      type=self._domain_to_node_type(domain),
      text=text,
      domain=domain,
      metadata=metadata or {},
      source_id=source_id
    )

    # 1. Add to Cognee (async)
    if COGNEE_AVAILABLE and self._cognee_initialized:
      try:
        dataset = self.DOMAINS.get(domain, "tapan_general")
        await cognee.add(text, datasets=[dataset])
        await cognee.cognify()
      except Exception as e:
        _ = e

    # 2. Add to Neo4j directly (for complex queries)
    if self.neo4j_driver:
      try:
        self._add_to_neo4j(node)
      except Exception as e:
        _ = e

    # 3. Cache locally (offline backup)
    self._cache_node(node)

    return node

  def _domain_to_node_type(self, domain: str) -> str:
    """Map domain to Neo4j node type"""
    mapping = {
      "memory": "Preference",
      "experience": "Experience",
      "relation": "Person",
      "habit": "Habit",
      "finance": "Purchase",
      "mood": "Mood",
    }
    return mapping.get(domain, "Memory")

  def _add_to_neo4j(self, node: MemoryNode):
    """Add node to Neo4j graph"""
    if not self.neo4j_driver:
      return

    with self.neo4j_driver.session() as session:
      # Create node with label based on type
      query = f"""
      MERGE (n:{node.type} {{id: $id}})
      SET n.text = $text,
        n.domain = $domain,
        n.timestamp = $timestamp,
        n.source_id = $source_id,
        n.metadata = $metadata
      RETURN n
      """
      session.run(query, 
        id=node.id,
        text=node.text,
        domain=node.domain,
        timestamp=node.timestamp,
        source_id=node.source_id,
        metadata=json.dumps(node.metadata)
      )

  def _cache_node(self, node: MemoryNode):
    """Cache node locally for offline access"""
    cache_file = self._cache_dir / f"{node.domain}.jsonl"
    with open(cache_file, "a", encoding="utf-8") as f:
      f.write(json.dumps({
        "id": node.id,
        "type": node.type,
        "text": node.text,
        "domain": node.domain,
        "timestamp": node.timestamp,
        "metadata": node.metadata,
        "source_id": node.source_id
      }) + "\n")

  # ==================== RECALL (READ) ====================

  async def recall(self, query: str, domain: Optional[str] = None,
           limit: int = 10) -> List[RecallResult]:
    """
    Recall memories matching query.

    CRITICAL: Never invent data. Return empty if no match.

    Args:
      query: Natural language query
      domain: Optional domain filter
      limit: Max results

    Returns:
      List of RecallResult with provenance
    """
    results = []

    # 1. Try Cognee first (semantic search)
    if COGNEE_AVAILABLE and self._cognee_initialized:
      try:
        dataset = self.DOMAINS.get(domain) if domain else None
        cognee_results = await cognee.search(
          query,
          query_type=SearchType.GRAPH_COMPLETION if domain else SearchType.INSIGHTS,
          datasets=[dataset] if dataset else None
        )
        for r in cognee_results[:limit]:
          results.append(RecallResult(
            text=str(r),
            node_id=f"cognee_{hash(str(r))}",
            node_type="CogneeResult",
            confidence=0.8,
            source="cognee",
            timestamp=datetime.now().isoformat()
          ))
      except Exception as e:
        _ = e

    # 2. Try Neo4j (graph traversal)
    if self.neo4j_driver and len(results) < limit:
      try:
        neo4j_results = self._search_neo4j(query, domain, limit - len(results))
        results.extend(neo4j_results)
      except Exception as e:
        _ = e

    # 3. Fallback to local cache
    if len(results) == 0:
      cache_results = self._search_cache(query, domain, limit)
      results.extend(cache_results)

    return results

  def _search_neo4j(self, query: str, domain: Optional[str], limit: int) -> List[RecallResult]:
    """Search Neo4j graph"""
    if not self.neo4j_driver:
      return []

    results = []
    with self.neo4j_driver.session() as session:
      # Full-text search on text property
      cypher = """
      MATCH (n)
      WHERE n.text CONTAINS $query
      """
      if domain:
        cypher += " AND n.domain = $domain"
      cypher += """
      RETURN n.id as id, n.text as text, n.type as type, 
           n.timestamp as timestamp, n.source_id as source_id
      LIMIT $limit
      """

      result = session.run(cypher, query=query.lower(), domain=domain, limit=limit)
      for record in result:
        results.append(RecallResult(
          text=record["text"],
          node_id=record["id"],
          node_type=record["type"] or "Unknown",
          confidence=0.9,
          source="neo4j",
          timestamp=record["timestamp"] or ""
        ))

    return results

  def _search_cache(self, query: str, domain: Optional[str], limit: int) -> List[RecallResult]:
    """Search local cache (offline fallback)"""
    results = []
    query_lower = query.lower()

    # Search relevant cache files
    if domain:
      cache_files = [self._cache_dir / f"{domain}.jsonl"]
    else:
      cache_files = list(self._cache_dir.glob("*.jsonl"))

    for cache_file in cache_files:
      if not cache_file.exists():
        continue

      with open(cache_file, "r", encoding="utf-8") as f:
        for line in f:
          if len(results) >= limit:
            break
          try:
            node = json.loads(line.strip())
            if query_lower in node.get("text", "").lower():
              results.append(RecallResult(
                text=node["text"],
                node_id=node["id"],
                node_type=node["type"],
                confidence=0.7,
                source="cache",
                timestamp=node["timestamp"]
              ))
          except json.JSONDecodeError:
            continue

    return results

  # ==================== MULTI-HOP QUERIES ====================

  async def multi_hop_query(self, query: str) -> List[RecallResult]:
    """
    Execute multi-hop graph query.

    Examples:
    - "When did I last meet Rahul at AlphaOne and how much did I spend?"
    - "Which habits broke after stressful days?"
    - "How do my purchases relate to mood?"
    """
    if not self.neo4j_driver:
      return [RecallResult(
        text="Multi-hop queries require Neo4j connection",
        node_id="error",
        node_type="Error",
        confidence=0.0,
        source="system",
        timestamp=datetime.now().isoformat()
      )]

    # Parse query to identify entities and relationships
    entities = self._extract_entities(query)

    results = []
    with self.neo4j_driver.session() as session:
      # Build dynamic Cypher based on entities
      if "person" in entities and "place" in entities:
        # Person + Place query
        cypher = """
        MATCH (p:Person)-[:MET_AT]->(place:Place)
        WHERE p.text CONTAINS $person AND place.text CONTAINS $place
        OPTIONAL MATCH (p)-[:DID_WITH]->(e:Experience)
        RETURN p, place, e
        LIMIT 10
        """
        result = session.run(cypher, 
          person=entities.get("person", ""),
          place=entities.get("place", "")
        )
        for record in result:
          text_parts = []
          if record["p"]:
            text_parts.append(f"Person: {record['p'].get('text', '')}")
          if record["place"]:
            text_parts.append(f"Place: {record['place'].get('text', '')}")
          if record["e"]:
            text_parts.append(f"Experience: {record['e'].get('text', '')}")

          results.append(RecallResult(
            text=" | ".join(text_parts),
            node_id=record["p"].get("id", "") if record["p"] else "unknown",
            node_type="MultiHop",
            confidence=0.85,
            source="neo4j",
            timestamp=datetime.now().isoformat(),
            related_nodes=[
              record["place"].get("id", "") if record["place"] else "",
              record["e"].get("id", "") if record["e"] else ""
            ]
          ))

      elif "habit" in entities and "mood" in entities:
        # Habit + Mood correlation
        cypher = """
        MATCH (h:Habit)-[:AFFECTED_HABIT]-(m:Mood)
        RETURN h, m
        LIMIT 10
        """
        result = session.run(cypher)
        for record in result:
          results.append(RecallResult(
            text=f"Habit: {record['h'].get('text', '')} | Mood: {record['m'].get('text', '')}",
            node_id=record["h"].get("id", ""),
            node_type="HabitMood",
            confidence=0.8,
            source="neo4j",
            timestamp=datetime.now().isoformat()
          ))

    if not results:
      results.append(RecallResult(
        text="No matching records found in knowledge graph",
        node_id="empty",
        node_type="NoResult",
        confidence=0.0,
        source="neo4j",
        timestamp=datetime.now().isoformat()
      ))

    return results

  def _extract_entities(self, query: str) -> Dict[str, str]:
    """Extract entities from natural language query"""
    import re
    entities = {}

    # Person patterns
    person_match = re.search(r'(?:with|meet|met)\s+(\w+)', query, re.I)
    if person_match:
      entities["person"] = person_match.group(1)

    # Place patterns
    place_match = re.search(r'(?:at|in)\s+(\w+)', query, re.I)
    if place_match:
      entities["place"] = place_match.group(1)

    # Habit patterns
    if re.search(r'habit', query, re.I):
      entities["habit"] = True

    # Mood patterns
    if re.search(r'mood|stress|happy|sad|feeling', query, re.I):
      entities["mood"] = True

    # Finance patterns
    if re.search(r'spend|spent|purchase|buy|cost', query, re.I):
      entities["finance"] = True

    return entities

  # ==================== RELATIONSHIP CREATION ====================

  def create_relationship(self, from_id: str, to_id: str, rel_type: str,
               properties: Optional[Dict] = None):
    """Create relationship between nodes in Neo4j"""
    if not self.neo4j_driver:
      return

    with self.neo4j_driver.session() as session:
      cypher = f"""
      MATCH (a {{id: $from_id}})
      MATCH (b {{id: $to_id}})
      MERGE (a)-[r:{rel_type}]->(b)
      SET r += $properties
      RETURN r
      """
      session.run(cypher, 
        from_id=from_id, 
        to_id=to_id, 
        properties=properties or {}
      )

  def delete_by_source_ids(self, domain: str, source_ids: List[int]) -> int:
    """Delete domain nodes by SQLite source IDs from Neo4j and local cache."""
    if not source_ids:
      return 0
    deleted = 0
    if self.neo4j_driver:
      try:
        with self.neo4j_driver.session() as session:
          result = session.run(
            """
            MATCH (n)
            WHERE n.domain = $domain AND n.source_id IN $source_ids
            WITH collect(n) AS nodes
            FOREACH (n IN nodes | DETACH DELETE n)
            RETURN size(nodes) AS deleted
            """,
            domain=domain,
            source_ids=source_ids,
          )
          row = result.single()
          deleted = int(row["deleted"]) if row and row["deleted"] is not None else 0
      except Exception:
        deleted = 0

    cache_file = self._cache_dir / f"{domain}.jsonl"
    if cache_file.exists():
      kept_lines: List[str] = []
      try:
        with open(cache_file, "r", encoding="utf-8") as fh:
          for line in fh:
            raw = line.strip()
            if not raw:
              continue
            try:
              item = json.loads(raw)
            except Exception:
              kept_lines.append(line)
              continue
            sid = item.get("source_id")
            if isinstance(sid, int) and sid in source_ids:
              continue
            kept_lines.append(line)
        with open(cache_file, "w", encoding="utf-8") as fh:
          fh.writelines(kept_lines)
      except Exception:
        pass
    return deleted

  # ==================== CLEANUP ====================

  def close(self):
    """Close connections"""
    if self._neo4j_driver:
      self._neo4j_driver.close()
      self._neo4j_driver = None


# Synchronous wrapper for non-async code
class CogneeBrainSync:
  """Synchronous wrapper for CogneeBrain"""

  def __init__(self, *args, **kwargs):
    self._brain = CogneeBrain(*args, **kwargs)
    self._loop = None

  def _get_loop(self):
    if self._loop is None or self._loop.is_closed():
      try:
        self._loop = asyncio.get_event_loop()
      except RuntimeError:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
    return self._loop

  def remember(self, text: str, domain: str, **kwargs) -> MemoryNode:
    return self._get_loop().run_until_complete(
      self._brain.remember(text, domain, **kwargs)
    )

  def recall(self, query: str, domain: Optional[str] = None, **kwargs) -> List[RecallResult]:
    return self._get_loop().run_until_complete(
      self._brain.recall(query, domain, **kwargs)
    )

  def multi_hop_query(self, query: str) -> List[RecallResult]:
    return self._get_loop().run_until_complete(
      self._brain.multi_hop_query(query)
    )

  def check_health(self) -> Dict[str, bool]:
    return self._brain.check_health()

  def delete_by_source_ids(self, domain: str, source_ids: List[int]) -> int:
    return self._brain.delete_by_source_ids(domain, source_ids)

  def close(self):
    self._brain.close()
