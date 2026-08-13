"""
auth.py
--------
Şifre hash'leme ve doğrulama.
PBKDF2-HMAC-SHA256 kullanılır (ek bağımlılık gerektirmez, Python stdlib).
"""

import hashlib
import hmac
import os

PBKDF2_ITERASYON = 260_000


def sifre_hashle(sifre: str) -> tuple[str, str]:
    """Döner: (sifre_hash_hex, salt_hex)"""
    salt = os.urandom(16)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", sifre.encode("utf-8"), salt, PBKDF2_ITERASYON)
    return hash_bytes.hex(), salt.hex()


def sifre_dogrula(sifre: str, sifre_hash_hex: str, salt_hex: str) -> bool:
    """Girilen şifre ile saklanan hash'i güvenli şekilde karşılaştırır."""
    salt = bytes.fromhex(salt_hex)
    hesaplanan = hashlib.pbkdf2_hmac("sha256", sifre.encode("utf-8"), salt, PBKDF2_ITERASYON)
    return hmac.compare_digest(hesaplanan.hex(), sifre_hash_hex)
