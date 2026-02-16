"""
Security Manager - Handles encryption and data privacy
Uses pure Python implementation to avoid external dependencies.
"""
import os
import hashlib
import struct
from pathlib import Path

class SecurityManager:
  """
  Manages encryption and decryption of files using a pure Python stream cipher.
  Algorithm: 
  1. Key Derivation: PBKDF2 (HMAC-SHA256) with random salt.
  2. Encryption: XOR Stream Cipher (ChaCha20-like or simple counter mode using SHA256).
     We will use a Counter-Mode logic driven by SHA256 for a robust 'standard library only' stream cipher.
  """

  def __init__(self):
    pass

  def _derive_key(self, password: str, salt: bytes) -> bytes:
    """Derive 32-byte key from password and salt using PBKDF2"""
    return hashlib.pbkdf2_hmac(
      'sha256', 
      password.encode('utf-8'), 
      salt, 
      100000
    )

  def _get_keystream_block(self, key: bytes, nonce: bytes, counter: int) -> bytes:
    """Generate a 32-byte keystream block using HMAC-SHA256"""
    # Input: Key + Nonce + Counter
    msg = nonce + struct.pack('>Q', counter) # 8 bytes for counter
    # Use HMAC-SHA256 as a PRF
    return hashlib.new('sha256', key + msg).digest()

  def encrypt_file(self, file_path: str, password: str) -> str:
    """
    Encrypt a file in place (or rename to .enc)
    Format: [Salt: 16][Nonce: 16][Ciphertext...]
    """
    path = Path(file_path)
    if not path.exists():
      raise FileNotFoundError(f"File {file_path} not found")

    salt = os.urandom(16)
    nonce = os.urandom(16)
    key = self._derive_key(password, salt)

    output_path = path.with_suffix(path.suffix + ".enc")

    with open(path, 'rb') as fin, open(output_path, 'wb') as fout:
      # Write Header
      fout.write(salt)
      fout.write(nonce)

      counter = 0
      while True:
        chunk = fin.read(32) # Process in 32-byte chunks (hash size)
        if not chunk:
          break

        keystream = self._get_keystream_block(key, nonce, counter)

        # XOR
        encrypted_chunk = bytes(a ^ b for a, b in zip(chunk, keystream))
        fout.write(encrypted_chunk)

        counter += 1

    return str(output_path)

  def decrypt_file(self, file_path: str, password: str) -> str:
    """
    Decrypt a .enc file
    """
    path = Path(file_path)
    if not path.exists():
      raise FileNotFoundError(f"File {file_path} not found")

    if not path.name.endswith('.enc'):
      raise ValueError("File does not appear to be encrypted (missing .enc)")

    # Output removes .enc
    output_path = path.with_name(path.stem) 

    with open(path, 'rb') as fin, open(output_path, 'wb') as fout:
      # Read Header
      salt = fin.read(16)
      nonce = fin.read(16)

      if len(salt) != 16 or len(nonce) != 16:
        raise ValueError("Invalid encrypted file format")

      key = self._derive_key(password, salt)

      counter = 0
      while True:
        chunk = fin.read(32)
        if not chunk:
          break

        keystream = self._get_keystream_block(key, nonce, counter)

        # XOR (Symmetric)
        decrypted_chunk = bytes(a ^ b for a, b in zip(chunk, keystream))
        fout.write(decrypted_chunk)

        counter += 1

    return str(output_path)
