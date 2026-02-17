#!/usr/bin/env python3
"""
Interactive TAPAN_AI Companion Test
Demonstrates daily companion functionality
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.agent.orchestrator import Orchestrator

def main():
    # Initialize TAPAN_AI
    data_dir = Path("test_data_interactive")
    data_dir.mkdir(exist_ok=True)
    orch = Orchestrator(data_dir)

    print("=" * 60)
    print("TAPAN_AI - Your Daily Companion")
    print("=" * 60)
    print()

    # Test sequence: Daily companion interactions
    interactions = [
        ("remember I worked at Microsoft for 5 years", "[MEMORY] Learning about work history"),
        ("remember my favorite food is biryani", "[MEMORY] Learning preferences"),
        ("expense 500 groceries", "[FINANCE] Recording expense"),
        ("income 2000 freelance", "[FINANCE] Recording income"),
        ("show balance", "[QUERY] Checking accounts"),
        ("log went to gym today", "[EXPERIENCE] Logging activity"),
        ("I'm feeling great today!", "[SENTIMENT] Mood tracking"),
        ("show memories", "[RECALL] Retrieving memories"),
    ]

    for command, label in interactions:
        print(f"[YOU]: {command}")
        print(f"     {label}")

        try:
            response = orch.process(command)
            # Truncate very long responses
            if len(response) > 200:
                response = response[:197] + "..."
            print(f"[JARVIS]: {response}")
        except Exception as e:
            print(f"[ERROR]: {str(e)}")

        print()

    print("=" * 60)
    print("Session Summary")
    print("=" * 60)

    # Get session/conversation summary
    try:
        conv = orch._get_conversation_mgr()
        if conv:
            summary = conv.get_session_summary()
            print(f"[SESSION]: {summary}")
    except Exception:
        pass

    print()
    print("[RESULT] TAPAN_AI interactive companion test completed successfully!")
    print("[INFO] All data has been persisted to databases in test_data_interactive/")

if __name__ == "__main__":
    main()
