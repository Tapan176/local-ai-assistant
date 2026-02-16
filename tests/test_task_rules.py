"""
Tests for Task Rule Sets feature
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from src.core.task_rules import TaskRuleManager

def test_task_rules():
    print("\n" + "=" * 50)
    print("   TEST: Task Rule Sets")
    print("=" * 50)
    
    # Use temp dir for testing
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        manager = TaskRuleManager(Path(temp_dir))
        
        # Test 1: Empty rules
        print("\n1. List empty rules...")
        output = manager.list_rules()
        assert "No task rules" in output
        print("   ✓ Empty state verified")
        
        # Test 2: Add rule
        print("\n2. Add rule...")
        result = manager.add_rule("test", {
            "description": "Test rule",
            "steps": ["step1", "step2"],
            "model": "tiny"
        })
        assert "successfully" in result
        print(f"   ✓ {result}")
        
        # Test 3: Get rule
        print("\n3. Get rule...")
        rule = manager.get_rule("test")
        assert rule is not None
        assert rule['description'] == "Test rule"
        print(f"   ✓ Rule retrieved: {rule['description']}")
        
        # Test 4: Detect task type
        print("\n4. Detect task type...")
        detected = manager.detect_task_type("research best laptop")
        assert detected == "research"
        print(f"   ✓ 'research best laptop' -> {detected}")
        
        detected = manager.detect_task_type("should I buy bike")
        assert detected == "purchase_decision"
        print(f"   ✓ 'should I buy bike' -> {detected}")
        
        # Test 5: Apply rule
        print("\n5. Apply rule...")
        plan = manager.apply_rule("test")
        assert plan['rule_type'] == "test"
        assert 'steps' in plan
        print(f"   ✓ Execution plan: {plan['steps']}")
        
        # Test 6: List rules
        print("\n6. List rules...")
        output = manager.list_rules()
        assert "test" in output.lower()
        print("   ✓ Rule listed")
        
        # Test 7: Remove rule
        print("\n7. Remove rule...")
        result = manager.remove_rule("test")
        assert "removed" in result
        print(f"   ✓ {result}")
    
    print("\n  🎉 All Task Rule Tests PASSED")
    return True

if __name__ == "__main__":
    try:
        test_task_rules()
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
