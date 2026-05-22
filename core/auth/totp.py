"""TOTP (Time-based One-Time Password) helpers. Uses pyotp."""
from __future__ import annotations

import io

import pyotp
import qrcode

ISSUER = "Sudo Canary"


def generate_secret() -> str:
    return pyotp.random_base32()


def verify_code(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code. valid_window=1 allows ±30s clock drift."""
    totp = pyotp.TOTP(secret, issuer=ISSUER)
    return totp.verify(code, valid_window=1)


def get_provisioning_uri(secret: str, username: str) -> str:
    totp = pyotp.TOTP(secret, issuer=ISSUER)
    return totp.provisioning_uri(name=username, issuer_name=ISSUER)


def generate_qr_bytes(secret: str, username: str) -> bytes:
    """Return QR code as PNG bytes, ready for QPixmap.loadFromData()."""
    uri = get_provisioning_uri(secret, username)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()