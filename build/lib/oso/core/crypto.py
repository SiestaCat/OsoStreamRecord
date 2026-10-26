"""Encrypted cloud passwords and portable encrypted exports.

Note: an obfuscation key embedded in an application binary is NOT a secure
credential vault; an attacker who can read the app and its data can recover it.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Project-requested obfuscation layer. Not claimed to be strong secret storage.
_MASK_FRAGMENTS = ("osr", "-browser", "-portable", "-local", "-mask-v1")
_MAGIC = b"OSOEXPORT1\0"


def deriveKey(passphrase, salt):
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, 600_000, dklen=32)


def encodeSecret(value, passphrase):
    salt, nonce = os.urandom(16), os.urandom(12)
    raw = salt + nonce + AESGCM(deriveKey(passphrase, salt)).encrypt(nonce, value.encode(), None)
    return base64.urlsafe_b64encode(raw).decode()


def decodeSecret(value, passphrase):
    raw = base64.urlsafe_b64decode(value)
    salt, nonce, cipher = raw[:16], raw[16:28], raw[28:]
    return AESGCM(deriveKey(passphrase, salt)).decrypt(nonce, cipher, None).decode()


def _mask(salt):
    return hashlib.pbkdf2_hmac("sha256", "".join(_MASK_FRAGMENTS).encode(), salt, 100_000, 32)


class PassphraseStore:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.exists():
            self.save(secrets.token_urlsafe(24))

    def save(self, value):
        if not value:
            raise ValueError("Passphrase must not be empty")
        salt = os.urandom(16)
        key = _mask(salt)
        payload = value.encode()
        stream = hashlib.shake_256(key).digest(len(payload))
        encoded = base64.urlsafe_b64encode(salt + bytes(a ^ b for a, b in zip(payload, stream)))
        self.path.write_bytes(encoded)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def load(self):
        raw = base64.urlsafe_b64decode(self.path.read_bytes())
        salt, payload = raw[:16], raw[16:]
        stream = hashlib.shake_256(_mask(salt)).digest(len(payload))
        return bytes(a ^ b for a, b in zip(payload, stream)).decode()


def sealArchive(zipBytes, passphrase):
    salt, nonce = os.urandom(16), os.urandom(12)
    return _MAGIC + salt + nonce + AESGCM(deriveKey(passphrase, salt)).encrypt(nonce, zipBytes, _MAGIC)


def openArchive(raw, passphrase):
    if not raw.startswith(_MAGIC):
        raise ValueError("Invalid encrypted archive")
    raw = raw[len(_MAGIC):]
    return AESGCM(deriveKey(passphrase, raw[:16])).decrypt(raw[16:28], raw[28:], _MAGIC)
