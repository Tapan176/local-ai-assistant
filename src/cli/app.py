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
    
    # Phase 18: Use BackgroundService Event Loop
    from src.service.background_service import BackgroundService
    
    def cli_input_provider():
      try:
        return input("")
      except (EOFError, KeyboardInterrupt):
        raise EOFError
        
    print("✨ Jarvis Event Loop Active (Type 'help' for commands)")
    service = BackgroundService(orchestrator, cli_input_provider)
    service.start()
  except Exception as e:
    print(f"Critical Error: {e}")
    sys.exit(1)

if __name__ == "__main__":
  main()
