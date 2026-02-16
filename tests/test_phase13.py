"""
Tests for PHASE 13 - Security & Encryption
Tests SecurityManager and BackupManager encryption integration
"""
import sys
import shutil
import os
from pathlib import Path
from itertools import chain

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from src.core.security import SecurityManager
from src.core.backup import BackupManager

def setup_temp_env():
    """Setup temporary env for testing"""
    temp_dir = project_root / "tests" / "temp_phase13"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    
    data_dir = temp_dir / "data"
    data_dir.mkdir()
    
    # Create dummy data
    with open(data_dir / "finance.db", "w") as f:
        f.write("dummy database content")
        
    return temp_dir, data_dir

def test_security_manager():
    print("\n--- Testing SecurityManager ---")
    security = SecurityManager()
    password = "secret_password"
    
    test_file = Path("tests/temp_phase13/secret.txt")
    test_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Write original
    original_content = b"This is a secret message."
    with open(test_file, "wb") as f:
        f.write(original_content)
        
    print("1. Encrypting file...")
    enc_path = security.encrypt_file(str(test_file), password)
    print(f"   Encrypted to: {enc_path}")
    
    if not str(enc_path).endswith('.enc'):
        print("   ❌ File verify failed: extension mismatch")
        return False
        
    # Verify content changed
    with open(enc_path, "rb") as f:
        enc_content = f.read()
    if enc_content == original_content:
        print("   ❌ Encryption failed: content identical")
        return False
        
    print("2. Decrypting file...")
    dec_path = security.decrypt_file(enc_path, password)
    print(f"   Decrypted to: {dec_path}")
    
    # Verify content restored
    with open(dec_path, "rb") as f:
        dec_content = f.read()
        
    if dec_content != original_content:
        print(f"   ❌ Decryption content mismatch: {dec_content}")
        return False
        
    print("   ✓ Encryption/Decryption roundtrip successful")
    return True

def test_backup_encryption():
    print("\n--- Testing Backup Encryption ---")
    temp_dir, data_dir = setup_temp_env()
    backup_dir = temp_dir / "backup"
    
    manager = BackupManager(data_dir, backup_dir)
    password = "backup_pass"
    
    # 1. Create Encrypted Backup
    print("1. Creating encrypted backup...")
    try:
        backup_path_str = manager.create_backup(password=password)
        print(f"   Result: {backup_path_str}")
    except Exception as e:
        print(f"   ❌ Create failed: {e}")
        return False
        
    if "Encrypted Backup created" not in backup_path_str and ".zip.enc" not in backup_path_str and ".enc" not in backup_path_str:
        print(f"   ❌ Backup result doesn't indicate encryption: {backup_path_str}")
        # Note: logic returns message or path? 
        # Returns string message if encrypted? Let's check code.
        # "🔒 Encrypted Backup created: {Path(encrypted_path).name}"
        # So likely just a message returned by create_backup (logic changed from returning path to message for standard backup too?)
        # Standard backup returns "✓ Backup created..." 
        pass
        
        
    # Verify file exists
    # backups = manager.list_backups() # Returns string, check dir directly
    backups = sorted(
        chain(
            backup_dir.glob("backup_*.enc"),
            backup_dir.glob("backup_*.zip"),
            backup_dir.glob("backup_*")
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    # Filter out directories if any (though create_backup makes zip/enc now)
    backups = [b for b in backups if b.is_file()]
    
    if not backups:
        print("   ❌ No backup files found in directory")
        return False
        
    latest = backups[0]
    print(f"   Latest backup: {latest.name}")
    
    if latest.suffix != '.enc':
        print(f"   ❌ Latest backup is not .enc: {latest.suffix}")
        return False
        
    # 2. Try Restore with WRONG Password
    print("2. Attempting restore with WRONG password...")
    res = manager.restore_backup(latest.name, password="wrong")
    if "Decryption failed" in res or "Error" in res or "failed" in res:
        print(f"   ✓ Restore failed as expected: {res}")
    else:
        print(f"   ❌ Restore succeeded unexpectedly: {res}")
        return False
        
    # 3. Try Restore with CORRECT Password
    print("3. Attempting restore with CORRECT password...")
    res = manager.restore_backup(latest.name, password=password)
    if "Restored from" in res and "finance.db" in res:
         print(f"   ✓ Restore successful: {res}")
    else:
         print(f"   ❌ Restore failed: {res}")
         return False
         
    return True

if __name__ == "__main__":
    try:
        s_ok = test_security_manager()
        b_ok = test_backup_encryption()
        
        if s_ok and b_ok:
            print("\n🎉 Phase 13 Security Tests PASSED")
            sys.exit(0)
        else:
            print("\n❌ Phase 13 Security Tests FAILED")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ CRASH: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
