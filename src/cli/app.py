#!/usr/bin/env python3
"""
TAPAN_AI CLI - SQLite-First (Phase-15)
"""
import sys
from pathlib import Path

# Set UTF-8 encoding for proper emoji handling
if sys.platform == "win32":
    import os
    os.system("chcp 65001 > nul")

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


    # Check for Voice Mode
    voice = None
    if "--voice" in sys.argv:
        try:
            from src.io.voice_interface import VoiceInterface
            print("[INFO] Initializing Voice Interface...")
            # Wake word 'jarvis' or 'tapan'
            voice = VoiceInterface(wake_word="jarvis")
        except Exception as e:
            print(f"[WARNING] Voice Init Failed: {e}")

    # Phase 18: Use BackgroundService Event Loop
    from src.service.background_service import BackgroundService

    def cli_input_provider():
      try:
        return input("")
      except (EOFError, KeyboardInterrupt):
        raise EOFError

    print("[READY] Jarvis Event Loop Active (Type 'help' for commands)")
    service = BackgroundService(orchestrator, cli_input_provider, voice_interface=voice)
    service.start()
  except Exception as e:
    print(f"Critical Error: {e}")
    sys.exit(1)

if __name__ == "__main__":
  main()
