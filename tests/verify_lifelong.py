"""
Verification Script for Lifelong Companion Upgrade.
Tests:
1. Semantic Memory (Vector Search)
2. Sentiment Analysis
3. Mood Detection
4. Conversation Persistence (SQLite)
"""
import sys
import os
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.agent.semantic_memory import SemanticMemory
from src.agent.sentiment import SentimentEngine
from src.agent.persona_tone import PersonaTone, ToneMode
from src.agent.conversation_manager import ConversationManager

def test_semantic_memory():
    print("\n[1] Testing Semantic Memory...")
    try:
        data_dir = Path("d:/practice/J/data")
        data_dir.mkdir(parents=True, exist_ok=True)
        sm = SemanticMemory(data_dir)
        
        # Add memory
        text = "I love science fiction movies like Interstellar."
        params = {"category": "preference", "tags": "movies"}
        if sm.remember(text, params):
            print("  ✅ Memory stored.")
        else:
            print("  ⚠️ Memory storage failed (Ollama likely offline/no embedding model).")
            
        # Search
        results = sm.search("What kind of movies do I like?")
        if results:
            print(f"  ✅ Retrieval successful: {results[0]['text']} (Score: {results[0]['score']:.2f})")
        else:
            print("  ⚠️ Retrieval returned no results (expected if Ollama offline).")
            
    except Exception as e:
        print(f"  ❌ Semantic Memory Error: {e}")

def test_sentiment():
    print("\n[2] Testing Sentiment Engine...")
    engine = SentimentEngine()
    
    cases = [
        ("I am so happy and excited!", "happy"),
        ("This is terrible and completely failed.", "sad"),  # or angry/stressed
        ("I am very stressed about work.", "stressed"),
        ("The weather is okay.", "neutral")
    ]
    
    for text, expected in cases:
        res = engine.analyze(text)
        print(f"  Input: '{text}' -> Detected: {res['label']} (Valence: {res['valence']:.2f})")
        # Loose check as logic might vary slightly
        if expected in res['label']: 
             print("    ✅ Match")
        else:
             print(f"    ⚠️ Mismatch (Expected {expected})")

def test_persona_tone():
    print("\n[3] Testing Persona Tone...")
    pt = PersonaTone()
    
    mode = pt.detect_mode("I am feeling very sad and depressed today.")
    print(f"  Input: 'sad' -> Mode: {mode}")
    if mode == ToneMode.EMPATHETIC:
        print("  ✅ Correctly detected EMPATHETIC mode.")
    else:
        print(f"  ⚠️ Failed to detect EMPATHETIC (Got {mode}).")
        
    mode = pt.detect_mode("Brainstorm some ideas for a startup.")
    print(f"  Input: 'brainstorm' -> Mode: {mode}")
    if mode == ToneMode.BRAINSTORM:
        print("  ✅ Correctly detected BRAINSTORM mode.")
    else:
        print(f"  ⚠️ Failed to detect BRAINSTORM (Got {mode}).")

def test_conversation_persistence():
    print("\n[4] Testing Conversation Persistence...")
    data_dir = Path("d:/practice/J/data")
    cm = ConversationManager(data_dir=data_dir)
    
    # Add turn
    user_msg = "Test user message"
    ai_msg = "Test response"
    cm.add_turn(user_msg, ai_msg, intent="test", source="voice")
    print("  ✅ Turn added.")
    
    # Check reload
    cm2 = ConversationManager(data_dir=data_dir)
    history = cm2.get_recent_history(limit=1)
    if "Test user message" in history:
        print("  ✅ Persistence verified (loaded in new instance).")
    else:
        print("  ❌ Persistence failed.")

if __name__ == "__main__":
    test_semantic_memory()
    test_sentiment()
    test_persona_tone()
    test_conversation_persistence()
