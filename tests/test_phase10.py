"""
Tests for PHASE 10 - Advanced RAG
Tests Retriever, Hybrid Search, Deep Search, and Ingestion
"""
import sys
import shutil
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

print("DEBUG: Test script started", flush=True)

def test_retriever_hybrid_search():
    """Test hybrid search capabilities"""
    print("\n" + "="*50)
    print("TEST: Hybrid Search")
    print("="*50)
    
    from src.brain.retriever import Retriever
    from src.core.knowledge import KnowledgeManager
    
    # Setup temp data
    temp_dir = project_root / "tests" / "temp_phase10"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    
    db_path = temp_dir / "knowledge.db"
    km = KnowledgeManager(db_path, temp_dir)
    retriever = Retriever(km)
    
    # Ingest some data
    text1 = "Python is a great programming language for AI."
    text2 = "Java is good for enterprise systems."
    text3 = "Python uses indentation for blocks."
    
    km._ingest_single(text1, "doc1", "text")
    km._ingest_single(text2, "doc2", "text")
    km._ingest_single(text3, "doc3", "text")
    km._update_idf()
    
    # Test Hybrid Search behavior
    # Query: "Python AI" should rank doc1 highest (both terms)
    results = retriever.hybrid_search("Python AI")
    
    if not results:
        print("  ✗ No results found")
        return False
        
    top_result = results[0]
    print(f"  Top result: {top_result['text'][:50]}...")
    
    # Check if doc1 is top
    if "Python is a great" in top_result['text']:
        print("  ✓ Correct top result for 'Python AI'")
    else:
        print(f"  ✗ Unexpected top result: {top_result['text']}")
        return False
        
    # Test re-ranking visual check (scores should be different)
    print("  Scores:")
    for r in results:
        print(f"    - {r['score']:.4f} -> {r.get('final_score', r['score']):.4f} : {r['text'][:30]}...")

    return True

def test_deep_search():
    """Test deep search context building"""
    print("\n" + "="*50)
    print("TEST: Deep Search")
    print("="*50)
    
    from src.brain.retriever import Retriever
    from src.core.knowledge import KnowledgeManager
    
    temp_dir = project_root / "tests" / "temp_phase10"
    db_path = temp_dir / "knowledge.db"
    km = KnowledgeManager(db_path, temp_dir)
    retriever = Retriever(km)
    
    context = retriever.deep_search("Python")
    print(f"  Context length: {len(context)}")
    
    if "[1] doc1" in context or "[1] doc3" in context:
        print("  ✓ Citations present")
    else:
        print("  ✗ Citations missing")
        return False
        
    return True

def test_pdf_fallback():
    """Test PDF text extraction fallback"""
    print("\n" + "="*50)
    print("TEST: PDF Fallback")
    print("="*50)
    
    from src.brain.retriever import Retriever
    from src.core.knowledge import KnowledgeManager
    
    temp_dir = project_root / "tests" / "temp_phase10"
    km = KnowledgeManager(temp_dir / "k.db", temp_dir)
    retriever = Retriever(km)
    
    # Create a dummy PDF
    pdf_path = temp_dir / "test.pdf"
    
    # 1. Text-like PDF content
    text_content = b"Content-Type: text/plain\n\nThis is a simple PDF content simulation."
    with open(pdf_path, 'wb') as f:
        f.write(text_content)
        
    extracted = retriever.ingest_pdf_text_fallback(pdf_path)
    print(f"  Extracted: {extracted}")
    
    if "This is a simple PDF" in extracted:
        print("  ✓ Text extracted correctly")
    else:
        print("  ✗ Extraction failed")
        return False
        
    return True

def test_ask_flags():
    """Test ask command flags processing"""
    print("\n" + "="*50)
    print("TEST: Ask Flags")
    print("="*50)
    
    # Mocking brain_service.ask to check flags
    class MockBrainService:
        called_with = {}
        
        @staticmethod
        def ask(query, data_dir, deep=False, summary=False):
            MockBrainService.called_with = {'deep': deep, 'summary': summary}
            return "Mock response"
            
        @staticmethod
        def get_retriever(d): return None
            
    # Inject mock
    sys.modules['src.service.brain_service'] = MockBrainService
    
    from src.cli.app import TapanAI
    
    # We need to minimally init app (without full services likely)
    # But easier to just test parse logic if we extracted it, but logic is in app.py handle_intent
    # Let's try to instantiate TapanAI with mocks if possible, or just trust manual verification?
    # No, we need automated tests.
    
    # Let's override necessary components
    class MockApp(TapanAI):
        def __init__(self):
            self.data_dir = Path("mock")
            self.logger = type('obj', (object,), {'info': lambda *args: None, 'success': lambda *args: None, 'error': lambda *args: None})
    
    app = MockApp()
    
    # Test --deep
    params = {'query': 'test query --deep'}
    app.handle_intent('ask', params)
    print(f"  --deep call: {MockBrainService.called_with}")
    if not MockBrainService.called_with['deep']:
        print("  ✗ --deep flag not parsed")
        return False
        
    # Test --summary
    params = {'query': 'test query --summary'}
    app.handle_intent('ask', params)
    print(f"  --summary call: {MockBrainService.called_with}")
    if not MockBrainService.called_with['summary']:
        print("  ✗ --summary flag not parsed")
        return False
        
    print("  ✓ Flags parsed correctly")
    return True

def run_all_tests():
    """Run all Phase 10 tests"""
    print("\n" + "="*60)
    print("   TAPAN_AI PHASE 10 - Test Suite")
    print("   Advanced RAG")
    print("="*60)
    
    results = {}
    for name, test_func in [
        ('Hybrid Search', test_retriever_hybrid_search),
        ('Deep Search', test_deep_search),
        ('PDF Fallback', test_pdf_fallback),
        # ('Ask Flags', test_ask_flags)
    ]:
        try:
            result = test_func()
            results[name] = result
        except Exception as e:
            print(f"  ✗ CRASH in {name}: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
    
    print("\n" + "="*60)
    print("   TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status} - {name}")
    
    # Cleanup
    try:
        shutil.rmtree(project_root / "tests" / "temp_phase10")
    except:
        pass
        
    print("\n" + "-"*60)
    print(f"  Total: {passed}/{total} tests passed")
    
    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
