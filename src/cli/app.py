#!/usr/bin/env python3
"""
TAPAN_AI CLI - SQLite-First (Phase-15)
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(project_root))

from src.agent.orchestrator import Orchestrator

def main():
  print("Loading TAPAN_AI (SQLite-First)...")

  # Initialize Orchestrator with data directory
  data_dir = project_root / "data"
  data_dir.mkdir(exist_ok=True)

  try:
    orchestrator = Orchestrator(data_dir=data_dir)
    orchestrator.run_cli_loop()
  except Exception as e:
    print(f"Critical Error: {e}")
    sys.exit(1)

if __name__ == "__main__":
  main()
