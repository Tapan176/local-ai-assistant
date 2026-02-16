"""
CLI Service - Main application entry point
"""
import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


def main():
  """Start the TAPAN_AI CLI"""
  from src.cli.app import main as app_main
  app_main()


def run_tests():
  """Run all tests"""
  print("Running Phase 2 tests...")
  import subprocess
  result = subprocess.run(
    [sys.executable, "tests/test_phase2.py"],
    cwd=str(PROJECT_ROOT)
  )

  print("\nRunning Phase 6 tests...")
  result = subprocess.run(
    [sys.executable, "tests/test_phase6.py"],
    cwd=str(PROJECT_ROOT)
  )

  print("\nRunning Phase 7 tests...")
  result = subprocess.run(
    [sys.executable, "tests/test_phase7.py"],
    cwd=str(PROJECT_ROOT)
  )

  return result.returncode == 0


if __name__ == "__main__":
  if len(sys.argv) > 1 and sys.argv[1] == "--test":
    success = run_tests()
    sys.exit(0 if success else 1)
  else:
    main()
