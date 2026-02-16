"""
Massive Stress Test - 10,000 Commands
Simulates extensive usage to find race conditions, memory leaks, and edge cases.
"""
import sys
import time
import random
import string
import shutil
from pathlib import Path
from tqdm import tqdm

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.orchestrator import Orchestrator

# Test Config
ITERATIONS = 10000
TEST_DATA_DIR = PROJECT_ROOT / "data_stress_10k"

def setup():
    if TEST_DATA_DIR.exists():
        shutil.rmtree(TEST_DATA_DIR)
    TEST_DATA_DIR.mkdir()
    print(f"Set up test data dir: {TEST_DATA_DIR}")

def generate_random_string(length=10):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def generate_command():
    """Generate a random valid or invalid command."""
    types = [
        "finance_expense", "finance_income", "finance_transfer", "finance_balance",
        "memory_remember", "memory_search",
        "reminder_add", "reminder_list",
        "experience_log", "experience_stats",
        "decision", "planning",
        "system", "garbage"
    ]
    
    cmd_type = random.choice(types)
    
    if cmd_type == "finance_expense":
        return f"expense {random.randint(10, 5000)} {generate_random_string(5)}"
    elif cmd_type == "finance_income":
        return f"income {random.randint(1000, 50000)} salary"
    elif cmd_type == "finance_transfer":
        return f"transfer {random.randint(10, 500)} from {random.choice(['kotak','sbi','cash'])} to {random.choice(['axis','boi'])}"
    elif cmd_type == "finance_balance":
        return "show balance"
        
    elif cmd_type == "memory_remember":
        return f"remember I like {generate_random_string(8)}"
    elif cmd_type == "memory_search":
        return f"search memory {generate_random_string(3)}"
        
    elif cmd_type == "reminder_add":
        return f"remind me to {generate_random_string(10)}"
    elif cmd_type == "reminder_list":
        return "show reminders"
        
    elif cmd_type == "experience_log":
        return f"log went to {generate_random_string(6)}"
    elif cmd_type == "experience_stats":
        return "experience stats"
        
    elif cmd_type == "decision":
        return f"should i buy {generate_random_string(6)} for {random.randint(100, 100000)}?"
        
    elif cmd_type == "planning":
        return random.choice(["daily plan", "what should i do"])
        
    elif cmd_type == "system":
        return random.choice(["help", "profile stats", "perf report", "llm status"])
        
    elif cmd_type == "garbage":
        return generate_random_string(20)
        
    return "help"

from unittest.mock import MagicMock, patch

def run_stress_test():
    setup()
    
    print("Initializing Orchestrator with Mocks...")
    
    # Mock LLM and Decision Engine to speed up test (avoid network/heavy computation)
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "Mocked LLM Response"
    
    with patch('src.agent.orchestrator._get_llm', return_value=mock_llm), \
         patch('src.agent.orchestrator._get_decision_engine', return_value=None):
         
        orchestrator = Orchestrator(data_dir=TEST_DATA_DIR)
        
        errors = []
        
        print(f"Starting {ITERATIONS} iterations (Optimized)...")
        start_time = time.time()
        
        for i in tqdm(range(ITERATIONS)):
            cmd = generate_command()
            try:
                # Special check for reset factory every 1000 iter
                if i % 1000 == 0:
                    cmd = "reset factory"
                    
                response = orchestrator.process(cmd)
                
                # Validation
                if cmd == "reset factory":
                    if "FACTORY RESET COMPLETE" not in response:
                        errors.append(f"Iteration {i}: 'reset factory' failed to trigger reset. Got: {response[:50]}...")
                
                if not response and cmd != "clear":
                     pass
                     
            except Exception as e:
                errors.append(f"Iteration {i}: Command '{cmd}' failed: {e}")
                
        duration = time.time() - start_time
        print(f"\nCompleted in {duration:.2f}s")
        print(f"Errors: {len(errors)}")
        
        if errors:
            print("First 10 errors:")
            for e in errors[:10]:
                print(e)
                
            with open("stress_errors.log", "w") as f:
                f.write("\n".join(errors))
            print("Errors logged to stress_errors.log")
            sys.exit(1)
            
        print("✅ Stress Test Passed!")
    
    # Cleanup
    # shutil.rmtree(TEST_DATA_DIR)

if __name__ == "__main__":
    run_stress_test()
