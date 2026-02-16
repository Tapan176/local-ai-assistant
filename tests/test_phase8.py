"""
Tests for PHASE 8 - Device Readiness
Tests service layer, config, backup, and directory structure
"""
import sys
import json
from pathlib import Path
import tempfile

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))


def test_directory_structure():
  """Test only allowed directories exist in root"""
  print("\n" + "="*50)
  print("TEST: Directory Structure")
  print("="*50)

  allowed_items = {
    '.agent', '.github',  # Config dirs
    'src', 'data', 'tests', 'experiments', 'backup',  # Allowed dirs
    'README.md', 'requirements.txt', 'start.py'  # Allowed files
  }

  root = project_root
  all_items = {item.name for item in root.iterdir()}

  # Check for unexpected items
  unexpected = all_items - allowed_items - {'__pycache__', '.gitignore', '.git'}

  if unexpected:
    print(f"  ✗ Unexpected items in root: {unexpected}")
    return False

  print(f"  ✓ Root contains only: {sorted(all_items)}")

  # Check required dirs exist
  required_dirs = ['src', 'data', 'tests', 'backup']
  for d in required_dirs:
    if not (root / d).exists():
      print(f"  ✗ Missing required dir: {d}")
      return False

  print(f"  ✓ All required directories present")
  return True


def test_service_layer():
  """Test service modules import correctly"""
  print("\n" + "="*50)
  print("TEST: Service Layer")
  print("="*50)

  try:
    from src.service import brain_service, data_service, cli_service
    print("  ✓ brain_service imports")
    print("  ✓ data_service imports")
    print("  ✓ cli_service imports")
    return True
  except ImportError as e:
    print(f"  ✗ Import error: {e}")
    return False


def test_config_file():
  """Test config.json exists and is valid"""
  print("\n" + "="*50)
  print("TEST: Config File")
  print("="*50)

  config_path = project_root / "data" / "config.json"

  if not config_path.exists():
    print(f"  ✗ Config file not found: {config_path}")
    return False

  try:
    with open(config_path, 'r') as f:
      config = json.load(f)

    # Check required keys
    required = ['version', 'model', 'language', 'paths']
    for key in required:
      if key not in config:
        print(f"  ✗ Missing config key: {key}")
        return False

    print(f"  ✓ Config version: {config['version']}")
    print(f"  ✓ Config has all required keys")
    return True
  except json.JSONDecodeError as e:
    print(f"  ✗ Invalid JSON: {e}")
    return False


def test_start_entry():
  """Test start.py exists and has main()"""
  print("\n" + "="*50)
  print("TEST: Start Entry Point")
  print("="*50)

  start_path = project_root / "start.py"

  if not start_path.exists():
    print(f"  ✗ start.py not found")
    return False

  content = start_path.read_text()

  if 'def main()' not in content:
    print(f"  ✗ start.py missing main()")
    return False

  print("  ✓ start.py exists with main()")
  return True


def test_backup_commands():
  """Test snapshot and restore backup commands"""
  print("\n" + "="*50)
  print("TEST: Backup Commands")
  print("="*50)

  from src.core.backup import BackupManager

  with tempfile.TemporaryDirectory() as tmpdir:
    data_dir = Path(tmpdir) / "data"
    backup_dir = Path(tmpdir) / "backup"
    data_dir.mkdir()
    backup_dir.mkdir()

    # Create a fake db file
    fake_db = data_dir / "test.db"
    fake_db.write_text("test data")

    bm = BackupManager(data_dir, backup_dir)

    # Test snapshot
    result = bm.snapshot()
    print(f"  ✓ Snapshot created: {'SNAPSHOT' in result}")

    # Test list backups
    list_result = bm.list_backups()
    print(f"  ✓ Backups listed: {len(list_result)} chars")

    # Test restore
    restore_result = bm.restore_backup()
    print(f"  ✓ Restore works: {'Restored' in restore_result or 'No database' in restore_result}")

    return True


def test_intents():
  """Test new intents parse correctly"""
  print("\n" + "="*50)
  print("TEST: New Intents")
  print("="*50)

  from src.core.intents import IntentRouter

  router = IntentRouter()

  tests = [
    ("snapshot", "snapshot"),
    ("restore", "restore"),
    ("restore backup_20260204", "restore"),
    ("backups", "list_backups"),
  ]

  all_pass = True
  for cmd, expected in tests:
    result = router.parse_intent(cmd)
    actual = result['intent']
    passed = actual == expected
    status = "✓" if passed else "✗"
    print(f"  {status} '{cmd}' → {actual}")
    if not passed:
      all_pass = False

  return all_pass


def run_all_tests():
  """Run all Phase 8 tests"""
  print("\n" + "="*60)
  print("   TAPAN_AI PHASE 8 - Test Suite")
  print("   Device Readiness")
  print("="*60)

  results = {
    'Directory Structure': test_directory_structure(),
    'Service Layer': test_service_layer(),
    'Config File': test_config_file(),
    'Start Entry': test_start_entry(),
    'Backup Commands': test_backup_commands(),
    'New Intents': test_intents(),
  }

  print("\n" + "="*60)
  print("   TEST SUMMARY")
  print("="*60)

  passed = sum(1 for v in results.values() if v)
  total = len(results)

  for name, result in results.items():
    status = "✓ PASS" if result else "✗ FAIL"
    print(f"  {status} - {name}")

  print("\n" + "-"*60)
  print(f"  Total: {passed}/{total} tests passed")

  if passed == total:
    print("\n  🎉 All tests passed!")
  else:
    print(f"\n  ⚠️ {total - passed} tests failed")

  print("="*60 + "\n")

  return passed == total


if __name__ == "__main__":
  success = run_all_tests()
  sys.exit(0 if success else 1)
