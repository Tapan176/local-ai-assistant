"""
Brain Service - Exposes LLM, Router, Reasoning, Knowledge capabilities
"""
from pathlib import Path
from typing import Optional, Dict

# Lazy imports to avoid circular dependencies
_llm = None
_router = None
_reasoning = None
_retriever = None
_knowledge = None
_scheduler = None


def get_llm(data_dir: Optional[Path] = None):
    """Get the unified LLM"""
    global _llm
    if _llm is None:
        from src.brain.llm_interface import get_llm as _get_llm
        _llm = _get_llm('unified', data_dir=data_dir or Path("data"))
    return _llm


def get_reasoning(data_dir: Optional[Path] = None):
    """Get the reasoning engine"""
    global _reasoning
    if _reasoning is None:
        from src.brain.reasoning import ReasoningEngine
        _reasoning = ReasoningEngine(data_dir or Path("data"))
    return _reasoning


def get_knowledge(data_dir: Optional[Path] = None):
    """Get the knowledge manager"""
    global _knowledge
    if _knowledge is None:
        from src.core.knowledge import KnowledgeManager
        data_dir = data_dir or Path("data")
        knowledge_db = data_dir / "knowledge.db"
        _knowledge = KnowledgeManager(knowledge_db, data_dir)
    return _knowledge


def get_retriever(data_dir: Optional[Path] = None):
    """Get the advanced retriever"""
    global _retriever
    if _retriever is None:
        from src.brain.retriever import Retriever
        km = get_knowledge(data_dir)
        _retriever = Retriever(km)
    return _retriever


def ask(query: str, data_dir: Optional[Path] = None, deep: bool = False, summary: bool = False) -> str:
    """
    High-level ask function with reasoning
    
    Args:
        query: User's question
        data_dir: Path to data directory
        deep: Use deep search (slower, more context)
        summary: Generate summary report
    
    Returns:
        Formatted response with reasoning
    """
    data_dir = data_dir or Path("data")
    
    llm = get_llm(data_dir)
    reasoning = get_reasoning(data_dir)
    knowledge = get_knowledge(data_dir)
    retriever = get_retriever(data_dir)
    
    # Handle deep search vs standard
    if deep:
        context = retriever.deep_search(query)
        # Deep search often involves general knowledge, so we might skip granular memory search
        # or append it.
    else:
        # Standard context gathering (Hybrid RAG)
        # Use retriever for KB search part if we moved logic there, but gather_all_context
        # is still in KnowledgeManager for now.
        # We can enhance gather_all_context to use hybrid search if we update KnowledgeManager
        # or just use retriever here.
        # For now, let's stick to gather_all_context but maybe boost it.
        memory_db = data_dir / "memory.db"
        journal_db = data_dir / "journal.db"
        
        # If retriever has better search, we should use it.
        # Let's manually gather to use hybrid search
        kb_results = retriever.hybrid_search(query, top_k=5)
        kb_context = ""
        if kb_results:
            kb_context = "=== Knowledge Base ===\n" + "\n".join([f"[{r['source']}]: {r['text'][:200]}" for r in kb_results])
            
        # Add memories/journal
        other_context = knowledge.gather_all_context(query, memory_db, journal_db)
        # Remove the KB part from gather_all_context calculation effectively by not depending on it solely
        # But gather_all_context calls knowledge.search.
        
        # Simpler approach: Use existing gather_all_context for now to avoid duplicate logic
        # until we refactor KnowledgeManager to use Retriever.
        # Actually, let's keep it simple:
        context = knowledge.gather_all_context(query, memory_db, journal_db)

    # Get profile for reasoning
    from src.core.profile import ProfileManager
    profile_db = data_dir / "profile.db"
    profile = ProfileManager(profile_db)
    profile_data = profile.get_profile_for_reasoning()
    
    # Build reasoning context
    reasoning_context = reasoning.build_full_context(profile_data)
    reasoning_context['memories'] = context if context else []
    
    # Perform reasoning
    trace = reasoning.reason(query, reasoning_context)
    
    # Generate response
    if summary:
        response = llm.summarize(context) if context else "No information available to summarize."
    else:
        response = llm.generate(query, context)
    
    # Format with persona
    from src.core.persona import get_persona
    persona = get_persona()
    
    if trace.reasoning_type in ['finance', 'planning', 'habit'] and not summary:
        return persona.format_reasoning_response(trace, response)
    else:
        return persona.format_ask_response(query, context, response)


def reset():
    """Reset all cached services"""
    global _llm, _router, _reasoning, _knowledge, _retriever
    _llm = None
    _router = None
    _reasoning = None
    _knowledge = None
    _retriever = None
    _scheduler = None


def get_scheduler(data_dir: Optional[Path] = None):
    """Get the scheduler"""
    global _scheduler
    if _scheduler is None:
        from src.brain.scheduler import Scheduler
        _scheduler = Scheduler(data_dir or Path("data"))
    return _scheduler


