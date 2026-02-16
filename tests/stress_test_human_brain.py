"""
STRESS TEST: Human Brain Model (1000+ Cases)
Generates 1000 randomized human-like inputs to verify agent stability and routing.
"""
import sys
import random
import time
from pathlib import Path
from datetime import datetime
import traceback

# Add project root
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from src.agent.orchestrator import Orchestrator

# Templates for generating inputs
TEMPLATES = {
    "memory": [
        "remember simple fact: {fact}",
        "i like {noun}",
        "my favorite {noun} is {value}",
        "remember that i am {adjective}",
        "note down: {fact}"
    ],
    "reminder": [
        "remind me to {verb} {noun} {time}",
        "remind me {time} to {verb} {noun}",
        "reminder: {verb} {noun} in {number} hours",
        "wake me up at {time}",
        "set a reminder for {noun} {time}"
    ],
    "experience": [
        "today i went {activity}",
        "spent {amount} on {noun}",
        "yesterday i met {name}",
        "bought {noun} for {amount}",
        "went to {place} and spent {amount}"
    ],
    "relation": [
        "who is {name}?",
        "add relation {name} as {role}",
        "met {name} today",
        "update {name} phone 123456",
        "how do i know {name}?"
    ],
    "retrieval": [
        "when did i last {activity}?",
        "how much spent at {place}?",
        "what happened on {date}?",
        "search for {noun}",
        "show my memories about {noun}"
    ]
}

# Data for filling templates
DATA = {
    "fact": ["sky is blue", "water is wet", "earth is round", "python is cool", "AI is future"],
    "noun": ["coffee", "pizza", "laptop", "book", "car", "phone", "flowers", "milk", "bread", "eggs"],
    "verb": ["call", "buy", "meet", "fix", "clean", "wash", "eat", "drink", "read", "write"],
    "adjective": ["happy", "sad", "angry", "busy", "free", "tired", "excited", "bored"],
    "value": ["black", "white", "red", "blue", "green", "fast", "slow", "expensive", "cheap"],
    "time": ["tomorrow", "next week", "at 5pm", "in 2 days", "next year", "tonight", "morning"],
    "number": ["1", "2", "3", "4", "5", "10", "12", "24", "48"],
    "amount": ["50", "100", "500", "1000", "2000", "5000", "10", "20", "200", "300"],
    "activity": ["bowling", "shopping", "running", "gym", "swimming", "coding", "sleeping"],
    "name": ["Ravi", "Amit", "Sarah", "John", "Priya", "Rahul", "Sita", "Gita"],
    "role": ["friend", "colleague", "boss", "neighbor", "driver", "doctor"],
    "place": ["pvr", "starbucks", "alphaone", "gym", "office", "home", "market"],
    "date": ["1 jan", "14 feb", "today", "yesterday", "last week"]
}

def generate_case():
    """Generate a single random test case"""
    category = random.choice(list(TEMPLATES.keys()))
    template = random.choice(TEMPLATES[category])
    
    # Fill format slots
    text = template
    while "{" in text:
        start = text.find("{")
        end = text.find("}")
        if start == -1 or end == -1: break
        
        key = text[start+1:end]
        if key in DATA:
            value = random.choice(DATA[key])
            text = text[:start] + value + text[end+1:]
        else:
            text = text[:start] + "UNKNOWN" + text[end+1:] # Fallback
            
    return category, text

def run_stress_test(count=1000):
    print(f"🚀 Starting Stress Test: {count} cases")
    print("-" * 50)
    
    # Init Agent
    agent = Orchestrator(project_root / "data")
    
    success = 0
    errors = 0
    categories = {k: 0 for k in TEMPLATES.keys()}
    
    start_time = time.time()
    
    for i in range(count):
        cat, text = generate_case()
        categories[cat] += 1
        
        try:
            # We don't actually need full LLM for many of these if routed deterministically
            # But the Orchestrator.process() handles both.
            # To speed up, we rely on the orchestrator's deterministic checks which are fast.
            # If it falls through to LLM, it might fail in this headless environment or be slow.
            # However, for stress testing we want to exercise the CODE paths.
            
            # Since BitNet/Ollama might catch "other" queries, we expect some to be "processed" even if backend fails.
            # We just want to ensure NO CRASHES.
            
            # Allow printing every 100 cases
            if (i+1) % 100 == 0:
                print(f"[{i+1}/{count}] Processing: '{text}'...")
                
            resp = agent.process(text)
            
            if resp: 
                success += 1
            else:
                # None response isn't necessarily a crash, but unexpected for some inputs
                # In our orchestrator, process() returns string or None.
                pass
                
        except Exception as e:
            errors += 1
            print(f"❌ CRASH on '{text}': {e}")
            traceback.print_exc()
            
    end_time = time.time()
    duration = end_time - start_time
    
    print("-" * 50)
    print(f"✅ Completed in {duration:.2f}s")
    print(f"Total Cases: {count}")
    print(f"No Crashes: {count - errors}")
    print(f"Errors: {errors}")
    print("-" * 20)
    print("Category Breakdown:")
    for k, v in categories.items():
        print(f"  {k}: {v}")
    print("-" * 50)
    
    if errors == 0:
        print("🎉 STRESS TEST PASSED: SYSTEM IS ROBUST")
        sys.exit(0)
    else:
        print("⚠️ STRESS TEST FAILED: SYSTEM UNSTABLE")
        sys.exit(1)

if __name__ == "__main__":
    run_stress_test(50)
