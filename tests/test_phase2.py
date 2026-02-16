#!/usr/bin/env python3
"""
Test PHASE 2 Features
"""
import sys
from pathlib import Path
import sqlite3

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from src.core.finance import FinanceManager
from src.core.intents import IntentRouter

def test_inr_formatting():
  """Test INR formatting without decimals for whole numbers"""
  print("\n" + "="*50)
  print("   TEST: INR Formatting")
  print("="*50)

  data_dir = project_root / "data"
  finance_db = data_dir / "test_finance.db"
  finance_schema = data_dir / "finance_schema.sql"

  # Remove test db if exists
  if finance_db.exists():
    finance_db.unlink()

  finance = FinanceManager(finance_db, finance_schema)

  tests = [
    (100, "₹100"),
    (100.00, "₹100"),
    (100.50, "₹100.50"),
    (1234, "₹1234"),
    (1234.56, "₹1234.56"),
  ]

  passed = 0
  for amount, expected in tests:
    result = finance.format_inr(amount)
    status = "✓" if result == expected else "✗"
    if result == expected:
      passed += 1
    print(f"{status} {amount} -> {result} (expected: {expected})")

  print(f"\nPassed: {passed}/{len(tests)}")

  # Cleanup
  if finance_db.exists():
    finance_db.unlink()

  return passed == len(tests)

def test_account_management():
  """Test account creation and listing"""
  print("\n" + "="*50)
  print("   TEST: Account Management")
  print("="*50)

  data_dir = project_root / "data"
  finance_db = data_dir / "test_finance.db"
  finance_schema = data_dir / "finance_schema.sql"

  # Remove test db if exists
  if finance_db.exists():
    finance_db.unlink()

  finance = FinanceManager(finance_db, finance_schema)

  # Test 1: Default Cash account should exist
  print("\n1. Check default Cash account...")
  result = finance.list_accounts()
  assert "Cash" in result, "Default Cash account not created"
  print("✓ Default Cash account exists")

  # Test 2: Add new account
  print("\n2. Add Savings account...")
  result = finance.add_account("Savings", 10000)
  assert "created" in result.lower(), f"Failed to create account: {result}"
  print(f"✓ {result}")

  # Test 3: List all accounts
  print("\n3. List all accounts...")
  result = finance.list_accounts()
  assert "Cash" in result and "Savings" in result
  print(result)

  # Test 4: Try to add duplicate account
  print("\n4. Try to add duplicate account...")
  result = finance.add_account("Cash", 500)
  assert "already exists" in result.lower(), "Should not allow duplicate accounts"
  print(f"✓ {result}")

  # Test 5: Negative opening balance
  print("\n5. Try negative opening balance...")
  result = finance.add_account("Credit", -1000)
  assert "cannot be negative" in result.lower(), "Should not allow negative balance"
  print(f"✓ {result}")

  # Cleanup
  if finance_db.exists():
    finance_db.unlink()

  print("\n✓ All account management tests passed!")
  return True

def test_validations():
  """Test amount validations"""
  print("\n" + "="*50)
  print("   TEST: Amount Validations")
  print("="*50)

  data_dir = project_root / "data"
  finance_db = data_dir / "test_finance.db"
  finance_schema = data_dir / "finance_schema.sql"

  # Remove test db if exists
  if finance_db.exists():
    finance_db.unlink()

  finance = FinanceManager(finance_db, finance_schema)

  # Test 1: Negative expense
  print("\n1. Try negative expense...")
  result = finance.add_expense(-100, "food")
  assert "must be positive" in result.lower()
  print(f"✓ {result}")

  # Test 2: Zero expense
  print("\n2. Try zero expense...")
  result = finance.add_expense(0, "food")
  assert "must be positive" in result.lower()
  print(f"✓ {result}")

  # Test 3: Negative income
  print("\n3. Try negative income...")
  result = finance.add_income(-500, "salary")
  assert "must be positive" in result.lower()
  print(f"✓ {result}")

  # Test 4: Valid expense
  print("\n4. Add valid expense...")
  result = finance.add_expense(100, "food")
  assert "✓" in result or "added" in result.lower()
  print(f"✓ {result}")

  # Test 5: Valid income
  print("\n5. Add valid income...")
  result = finance.add_income(5000, "salary")
  assert "✓" in result or "added" in result.lower()
  print(f"✓ {result}")

  # Cleanup
  if finance_db.exists():
    finance_db.unlink()

  print("\n✓ All validation tests passed!")
  return True

def test_intent_parsing():
  """Test new command parsing"""
  print("\n" + "="*50)
  print("   TEST: Intent Parsing for New Commands")
  print("="*50)

  router = IntentRouter()

  tests = [
    ("accounts", "list_accounts", {}),
    ("account add 10000 Savings", "add_account", {"name": "savings", "opening_balance": 10000.0}),
    ("account add panch hazar Credit", "add_account", {"name": "credit", "opening_balance": 5000}),
    ("monthly", "monthly_report", {}),
    ("income do hazar salary", "add_income", {"amount": 2000, "category": "salary", "note": ""}),
  ]

  passed = 0
  for command, expected_intent, expected_params in tests:
    result = router.parse_intent(command)
    intent_match = result['intent'] == expected_intent

    params_match = True
    for key, value in expected_params.items():
      if key not in result['params'] or result['params'][key] != value:
        params_match = False
        break

    status = "✓" if intent_match and params_match else "✗"
    if intent_match and params_match:
      passed += 1

    print(f"{status} '{command}'")
    print(f"   Intent: {result['intent']} (expected: {expected_intent})")
    if expected_params:
      print(f"   Params: {result['params']}")

  print(f"\nPassed: {passed}/{len(tests)}")
  return passed == len(tests)

def test_balance_math():
  """Test that balance calculations are correct"""
  print("\n" + "="*50)
  print("   TEST: Balance Calculations")
  print("="*50)

  data_dir = project_root / "data"
  finance_db = data_dir / "test_finance.db"
  finance_schema = data_dir / "finance_schema.sql"

  # Remove test db if exists
  if finance_db.exists():
    finance_db.unlink()

  finance = FinanceManager(finance_db, finance_schema)

  # Get initial balance (should be 0)
  conn = sqlite3.connect(finance_db)
  cursor = conn.cursor()
  cursor.execute("SELECT balance FROM accounts WHERE name = 'Cash'")
  balance = cursor.fetchone()[0]
  conn.close()
  assert balance == 0, f"Initial balance should be 0, got {balance}"
  print(f"✓ Initial balance: ₹{balance}")

  # Add income
  print("\n1. Add income ₹5000...")
  finance.add_income(5000, "salary")
  conn = sqlite3.connect(finance_db)
  cursor = conn.cursor()
  cursor.execute("SELECT balance FROM accounts WHERE name = 'Cash'")
  balance = cursor.fetchone()[0]
  conn.close()
  assert balance == 5000, f"Balance should be 5000, got {balance}"
  print(f"✓ Balance after income: ₹{balance}")

  # Add expense
  print("\n2. Add expense ₹1500...")
  finance.add_expense(1500, "rent")
  conn = sqlite3.connect(finance_db)
  cursor = conn.cursor()
  cursor.execute("SELECT balance FROM accounts WHERE name = 'Cash'")
  balance = cursor.fetchone()[0]
  conn.close()
  assert balance == 3500, f"Balance should be 3500, got {balance}"
  print(f"✓ Balance after expense: ₹{balance}")

  # Add another expense
  print("\n3. Add expense ₹500...")
  finance.add_expense(500, "food")
  conn = sqlite3.connect(finance_db)
  cursor = conn.cursor()
  cursor.execute("SELECT balance FROM accounts WHERE name = 'Cash'")
  balance = cursor.fetchone()[0]
  conn.close()
  assert balance == 3000, f"Balance should be 3000, got {balance}"
  print(f"✓ Balance after expense: ₹{balance}")

  # Cleanup
  if finance_db.exists():
    finance_db.unlink()

  print("\n✓ All balance calculation tests passed!")
  return True

if __name__ == "__main__":
  print("\n" + "="*60)
  print("   PHASE 2 FEATURE TESTS")
  print("="*60)

  results = []

  # Run all tests
  results.append(("INR Formatting", test_inr_formatting()))
  results.append(("Account Management", test_account_management()))
  results.append(("Amount Validations", test_validations()))
  results.append(("Intent Parsing", test_intent_parsing()))
  results.append(("Balance Math", test_balance_math()))

  # Summary
  print("\n" + "="*60)
  print("   TEST SUMMARY")
  print("="*60)

  passed = sum(1 for _, result in results if result)
  total = len(results)

  for name, result in results:
    status = "✓ PASS" if result else "✗ FAIL"
    print(f"{status} - {name}")

  print(f"\nTotal: {passed}/{total} test suites passed")

  if passed == total:
    print("\n🎉 All PHASE 2 features working correctly!")
  else:
    print("\n❌ Some tests failed. Please review.")
    sys.exit(1)
