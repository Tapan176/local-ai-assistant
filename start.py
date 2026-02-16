#!/usr/bin/env python3
"""
TAPAN_AI - Personal Life Assistant
Single entry point for the application

Usage:
  python start.py           # Start CLI
  python start.py --test    # Run all tests
"""
import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


def main():
  """Main entry point"""
  if len(sys.argv) > 1:
    if sys.argv[1] == "--test":
      from src.service.cli_service import run_tests
      success = run_tests()
      sys.exit(0 if success else 1)
    elif sys.argv[1] == "--help":
      print(__doc__)
      sys.exit(0)

  # Start the CLI
  from src.service.cli_service import main as cli_main
  cli_main()


if __name__ == "__main__":
  main()
