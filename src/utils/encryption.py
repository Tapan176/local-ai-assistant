"""Encryption utilities for data at rest."""

from __future__ import annotations

import base64
import hashlib
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class DataEncryption:
    """Encryption service for sensitive data at rest."""

    def __init__(self, key: str | None = None) -> None:
        """Initialize encryption with key or generate from environment."""
        if key:
            self.key = self._derive_key(key)
        else:
            # Try to get from environment or use default (not secure for production)
            env_key = os.getenv("TAPAN_ENCRYPTION_KEY")
            if env_key:
                self.key = self._derive_key(env_key)
            else:
                # Generate a default key (WARNING: Not secure, use env var in production)
                self.key = Fernet.generate_key()
        self.cipher = Fernet(self.key)

    @staticmethod
    def _derive_key(password: str, salt: bytes | None = None) -> bytes:
        """Derive encryption key from password."""
        password_bytes = password.encode()
        # Use provided salt or generate from environment
        if salt is None:
            salt_env = os.getenv("TAPAN_ENCRYPTION_SALT")
            if salt_env:
                salt = salt_env.encode()[:16].ljust(16, b"0")
            else:
                # Default salt (WARNING: In production, use random salt stored separately)
                salt = b"tapan_ai_salt_"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password_bytes))
        return key

    def encrypt(self, data: str) -> str:
        """Encrypt string data."""
        return self.cipher.encrypt(data.encode()).decode()

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt string data."""
        return self.cipher.decrypt(encrypted_data.encode()).decode()

    def encrypt_dict(self, data: dict) -> dict:
        """Encrypt sensitive fields in dictionary."""
        encrypted = {}
        sensitive_fields = {"password", "api_key", "secret", "token", "credit_card"}
        for key, value in data.items():
            if key.lower() in sensitive_fields and isinstance(value, str):
                encrypted[key] = self.encrypt(value)
            else:
                encrypted[key] = value
        return encrypted

    def decrypt_dict(self, data: dict) -> dict:
        """Decrypt sensitive fields in dictionary."""
        decrypted = {}
        sensitive_fields = {"password", "api_key", "secret", "token", "credit_card"}
        for key, value in data.items():
            if key.lower() in sensitive_fields and isinstance(value, str):
                try:
                    decrypted[key] = self.decrypt(value)
                except Exception:
                    decrypted[key] = value  # If decryption fails, return original
            else:
                decrypted[key] = value
        return decrypted


def hash_sensitive_data(data: str) -> str:
    """Hash sensitive data (one-way)."""
    return hashlib.sha256(data.encode()).hexdigest()
