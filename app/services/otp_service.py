"""
Phone-number check with a one-time code (OTP).

  1) POST /otp/send    {phone_number}        -> a 6-digit code is sent by SMS (or WhatsApp)
  2) POST /otp/verify  {phone_number, code}  -> returns a short-lived "phone_token"
  3) The sign-up form sends that phone_token; the server accepts the account only if the token
     was made for the SAME phone number. Nobody can register with a number they do not own.

Codes last 10 minutes, work once, and lock after 5 wrong tries. A phone can ask for at most
5 codes per hour. If no SMS provider is set, the code is printed in the backend terminal, and
while LIFEFLOW_ENV is not "production" it is also returned so the whole flow can be tested.
"""
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.phone_otp import PhoneOtp
from app.services.delivery_service import (
    is_sms_configured, is_whatsapp_configured, send_email, send_sms, send_whatsapp_otp,
)
from app.utils.security import hash_password, verify_password, create_access_token, decode_access_token

CODE_MINUTES = 10
MAX_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 5
TOKEN_MINUTES = 30
IS_PRODUCTION = os.environ.get("LIFEFLOW_ENV", "development").lower() == "production"


def send_code(db: Session, contact: str, channel: str = "sms") -> Optional[str]:
    """
    Creates and sends a code to a phone number (channel "sms" or "whatsapp") or to an email address
    (channel "email"). `contact` is the phone number or the email address. Returns the code only
    outside production (for testing).
    """
    contact = contact.strip().lower() if channel == "email" else contact
    since = datetime.utcnow() - timedelta(hours=1)
    recent = db.query(PhoneOtp).filter(PhoneOtp.phone_number == contact, PhoneOtp.created_at >= since).count()
    if recent >= MAX_CODES_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many codes were asked for this number. Please try again in an hour.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(PhoneOtp(
        phone_number=contact,   # this column holds the phone number OR the email address
        code_hash=hash_password(code),
        expires_at=datetime.utcnow() + timedelta(minutes=CODE_MINUTES),
    ))
    db.commit()

    text = f"LifeFlow: your verification code is {code}. It works for {CODE_MINUTES} minutes. Do not share it."
    sent = False
    if channel == "email":
        sent = send_email(contact, "Your LifeFlow verification code", text)
    else:
        if channel == "whatsapp" and is_whatsapp_configured():
            sent = send_whatsapp_otp(contact, code)
        if not sent and is_sms_configured():
            sent = send_sms(contact, text)
    if not sent:
        print(f"[LifeFlow OTP] code for {contact}: {code}")  # noqa: T201 -- visible in the backend terminal
    return None if IS_PRODUCTION else code


def verify_code(db: Session, contact: str, code: str) -> str:
    """Checks the code and returns a proof token (phone or email). Raises HTTP 400 if wrong or expired."""
    is_email = "@" in contact
    if is_email:
        contact = contact.strip().lower()
    row = (
        db.query(PhoneOtp)
        .filter(PhoneOtp.phone_number == contact, PhoneOtp.used == False)  # noqa: E712
        .order_by(PhoneOtp.id.desc())
        .first()
    )
    bad = HTTPException(status_code=400, detail="This code is wrong or has expired. Please ask for a new one.")
    if not row or row.expires_at < datetime.utcnow() or row.attempts >= MAX_ATTEMPTS:
        raise bad
    if not verify_password(code or "", row.code_hash):
        row.attempts += 1
        db.commit()
        raise bad
    row.used = True
    db.commit()
    purpose = "email_verified" if is_email else "phone_verified"
    return create_access_token({"sub": contact, "purpose": purpose}, expires_minutes=TOKEN_MINUTES)


def require_phone_token(phone_token: Optional[str], phone_number: str, email: Optional[str] = None) -> str:
    """
    Called by the sign-up routes. Accepts EITHER a token that proves this exact phone number OR a
    token that proves this exact email address (for people who cannot receive SMS).
    Returns "phone" or "email" so the caller can record what was proven. Raises HTTP 400 otherwise.
    """
    claims = decode_access_token(phone_token or "")
    if claims:
        if claims.get("purpose") == "phone_verified" and claims.get("sub") == phone_number:
            return "phone"
        if email and claims.get("purpose") == "email_verified" and claims.get("sub") == email.strip().lower():
            return "email"
    raise HTTPException(status_code=400, detail="Please verify your phone number with the code we send you.")
