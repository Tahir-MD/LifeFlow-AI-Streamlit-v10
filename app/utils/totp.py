"""
A minimal RFC 6238 TOTP (Time-based One-Time Password) implementation
using only the Python standard library -- the same algorithm behind
Google Authenticator, Authy, etc. No extra package (e.g. pyotp) is
needed, which keeps 2FA from ever being blocked by a missing dependency.
"""
import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote

TIME_STEP_SECONDS = 30
CODE_DIGITS = 6


def generate_secret() -> str:
    """A random base32 secret, the kind an authenticator app expects."""
    return base64.b32encode(os.urandom(10)).decode("utf-8")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** CODE_DIGITS)
    return str(code).zfill(CODE_DIGITS)


def current_totp(secret: str) -> str:
    return _hotp(secret, int(time.time()) // TIME_STEP_SECONDS)


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    """Accepts a code from the current time step or one step either side, to allow for clock drift."""
    if not code or not code.isdigit():
        return False
    counter = int(time.time()) // TIME_STEP_SECONDS
    return any(_hotp(secret, counter + offset) == code for offset in range(-window, window + 1))


def get_otpauth_uri(secret: str, account_name: str, issuer: str = "LifeFlow") -> str:
    """The otpauth:// URI that an authenticator app's QR scanner expects."""
    label = quote(f"{issuer}:{account_name}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={CODE_DIGITS}&period={TIME_STEP_SECONDS}"
