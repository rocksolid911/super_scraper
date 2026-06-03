"""
At-rest field encryption for stored secrets (destination DSNs, API tokens, creds).

Values are encrypted with Fernet (AES-128-CBC + HMAC) using a key derived from
``settings.FIELD_ENCRYPTION_KEY`` (or ``settings.SECRET_KEY`` if unset). Encrypted
values carry an ``enc:`` prefix so:

* decryption is idempotent and backward-compatible — rows written as plaintext before
  encryption was added still read correctly (passed through unchanged);
* re-saving an already-encrypted value doesn't double-encrypt.

If the ``cryptography`` library is unavailable, encryption degrades to a no-op so the
app never breaks; a warning is logged once. Encryption then activates automatically
once the dependency is present.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any, Dict

from django.conf import settings

logger = logging.getLogger(__name__)

_PREFIX = 'enc:'
_fernet = None
_unavailable = False

# Config keys that hold secrets and should be encrypted at rest.
SECRET_KEYS = {
    'dsn', 'secret', 'password', 'token', 'api_key',
    'credentials', 'credentials_json', 'url',
}


def _get_fernet():
    global _fernet, _unavailable
    if _fernet is not None or _unavailable:
        return _fernet
    try:
        from cryptography.fernet import Fernet
    except Exception:  # noqa: BLE001 - missing dep -> graceful no-op
        _unavailable = True
        logger.warning("cryptography not installed; secret fields stored UNENCRYPTED")
        return None
    raw = getattr(settings, 'FIELD_ENCRYPTION_KEY', '') or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    _fernet = Fernet(key)
    return _fernet


def encrypt_str(value: str) -> str:
    if not isinstance(value, str) or not value or value.startswith(_PREFIX):
        return value
    f = _get_fernet()
    if f is None:
        return value
    return _PREFIX + f.encrypt(value.encode()).decode()


def decrypt_str(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(_PREFIX):
        return value
    f = _get_fernet()
    if f is None:
        return value
    try:
        return f.decrypt(value[len(_PREFIX):].encode()).decode()
    except Exception:  # noqa: BLE001 - tampered/rotated key -> return as-is
        logger.warning("failed to decrypt a secret field; returning stored value")
        return value


def encrypt_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``config`` with known secret values encrypted."""
    if not isinstance(config, dict):
        return config
    out: Dict[str, Any] = {}
    for k, v in config.items():
        if k in SECRET_KEYS and v:
            if isinstance(v, (dict, list)):
                out[k] = encrypt_str(json.dumps(v))
            elif isinstance(v, str):
                out[k] = encrypt_str(v)
            else:
                out[k] = v
        else:
            out[k] = v
    return out


def decrypt_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """Inverse of :func:`encrypt_secrets`; restores JSON-encoded dict/list values."""
    if not isinstance(config, dict):
        return config
    out: Dict[str, Any] = {}
    for k, v in config.items():
        if k in SECRET_KEYS and isinstance(v, str) and v.startswith(_PREFIX):
            dec = decrypt_str(v)
            if k in ('credentials', 'credentials_json'):
                try:
                    out[k] = json.loads(dec)
                    continue
                except Exception:  # noqa: BLE001
                    pass
            out[k] = dec
        else:
            out[k] = v
    return out
