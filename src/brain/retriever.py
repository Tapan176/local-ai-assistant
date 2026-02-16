"""
Retriever Engine - Advanced RAG capabilities
Implements hybrid search, re-ranking, and improved context building.
"""
from typing import List, Dict, Optional
from pathlib import Path
from collections import defaultdict
import math

from src.core.knowledge import KnowledgeManager

class Retriever:
    """Advanced retriever wrapping KnowledgeManager"""
    
    def __init__(self, knowledge_manager: KnowledgeManager):
        self.km = knowledge_manager
    
    def hybrid_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Hybrid search combining TF-IDF and Keyword Matching
        
        Args:
            query: User query
            top_k: Number of results
            
        Returns:
            Ranked results with citations
        """
        # 1. Get candidate results from TF-IDF (get more than needed for re-ranking)
        candidates = self.km.search(query, top_k=top_k * 3)
        
        if not candidates:
            return []
        
        # 2. Apply keyword boosting / Re-ranking
        ranked_results = self._rerank(query, candidates)
        
        # 3. Take top K
        return ranked_results[:top_k]
    
    def _rerank(self, query: str, candidates: List[Dict]) -> List[Dict]:
        """Re-rank candidates based on exact keyword matches and term proximity"""
        query_terms = self.km._tokenize(query)
        if not query_terms:
            return candidates
            
        for res in candidates:
            text = res['text'].lower()
            score = res['score']
            
            # Boost for exact phrase match
            if query.lower() in text:
                score *= 1.5
            
            # Boost for term presence (Keyword Matching)
            term_matches = sum(1 for term in query_terms if term in text)
            term_density = term_matches / len(query_terms)
            score *= (1 + term_density)
            
            # Update score
            res['final_score'] = score
            
        # Sort by new score
        return sorted(candidates, key=lambda x: x.get('final_score', 0), reverse=True)

    def deep_search(self, query: str) -> str:
        """
        Perform deep search and return comprehensive answer context
        
        Args:
            query: User query
            
        Returns:
            Formatted context string with citations
        """
        results = self.hybrid_search(query, top_k=8)
        
        if not results:
            return "No relevant information found."
            
        context_parts = []
        for i, res in enumerate(results):
            citation = f"[{i+1}] {res['source']}"
            context_parts.append(f"{citation}: {res['text']}")
            
        return "\n\n".join(context_parts)

    def ingest_pdf_text_fallback(self, file_path: Path) -> str:
        """
        Attempt to extract text from PDF (fallback text extraction)
        Matches strings of printable characters.
        """
        import re
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
                
            # Naive text extraction: find sequences of printable chars
            # This is very basic and mostly for uncompressed PDFs or simple streams
            text_content = ""
            # Filter for common textual bytes
            readable = b""
            for byte in content:
                if 32 <= byte <= 126 or byte in [9, 10, 13]: # Printable + whitespace
                    readable += bytes([byte])
                else:
                    readable += b" "
            
            # Decode and clean
            text = readable.decode('ascii', errors='ignore')
            
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Heuristic: if text length is too small compared to file size, it might be compressed
            if len(text) < len(content) * 0.05:
               return f"⚠️ PDF seems compressed or binary rich. Extracted text may be poor. ({len(text)} chars)"

            return text
        except Exception as e:
            return f"❌ Failed to extract PDF text: {e}"

