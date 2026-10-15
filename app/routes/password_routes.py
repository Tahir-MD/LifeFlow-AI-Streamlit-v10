"""
Forgot-password for every kind of account (donor, patient, hospital, staff, admin).

Flow:  1) POST /auth/forgot-password  {role, email}      -> a 6-digit code is emailed
       2) POST /auth/reset-password   {role, email, code, new_password}

* The reply to step 1 is always the same whether or not the email exists,
  so nobody can use this form to find out who is registered.
* Codes last 15 minutes, work once, and are locked after 5 wrong tries.
* If email delivery (SendGrid) is not set up, the code is printed in the
  backend terminal; and while LIFEFLOW_ENV is not "production" it is also
  returned in the reply so you can test the whole flow on one computer.
"""
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import Admin
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.password_reset import PasswordReset
from app.models.receiver import Receiver
from app.models.staff import Staff
from app.services.delivery_service import is_email_configured, send_email
from app.utils.security import hash_password, verify_password
from app.utils.validators import validate_password_strength

router = APIRouter(prefix="/auth", tags=["Forgot password"])

ACCOUNT_MODELS = {"donor": Donor, "receiver": Receiver, "hospital": Hospital, "staff": Staff, "admin": Admin}
CODE_MINUTES = 15
MAX_ATTEMPTS = 5
IS_PRODUCTION = os.environ.get("LIFEFLOW_ENV", "development").lower() == "production"


class ForgotIn(BaseModel):
    role: str
    email: EmailStr

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in ACCOUNT_MODELS:
            raise ValueError("Unknown account type.")
        return v


class ResetIn(ForgotIn):
    code: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v):
        return validate_password_strength(v)


@router.post("/forgot-password")
def forgot_password(data: ForgotIn, db: Session = Depends(get_db)):
    email = data.email.lower()
    model = ACCOUNT_MODELS[data.role]
    account = db.query(model).filter(model.email == data.email).first()

    reply = {"message": "If this email is registered, a 6-digit code has been sent to it."}
    if not account:
        return reply

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.query(PasswordReset).filter(
        PasswordReset.role == data.role, PasswordReset.email == email, PasswordReset.used == False  # noqa: E712
    ).update({"used": True})
    db.add(PasswordReset(
        role=data.role, email=email, code_hash=hash_password(code),
        expires_at=datetime.utcnow() + timedelta(minutes=CODE_MINUTES),
    ))
    db.commit()

    sent = send_email(
        data.email, "LifeFlow - your password reset code",
        f"Your LifeFlow code is {code}. It works for {CODE_MINUTES} minutes. "
        "If you did not ask for this, you can ignore this email.",
    )
    if not sent:
        print(f"[LifeFlow] Password reset code for {data.role} {data.email}: {code}")
        if not IS_PRODUCTION and not is_email_configured():
            reply["dev_code"] = code
            reply["dev_note"] = "Email is not set up, so the code is shown here for testing only."
    return reply


@router.post("/reset-password")
def reset_password(data: ResetIn, db: Session = Depends(get_db)):
    email = data.email.lower()
    bad = HTTPException(status_code=400, detail="This code is wrong or has expired. Please ask for a new one.")

    record = (
        db.query(PasswordReset)
        .filter(PasswordReset.role == data.role, PasswordReset.email == email, PasswordReset.used == False)  # noqa: E712
        .order_by(PasswordReset.id.desc())
        .first()
    )
    if not record or record.expires_at < datetime.utcnow() or record.attempts >= MAX_ATTEMPTS:
        raise bad
    if not verify_password(data.code.strip(), record.code_hash):
        record.attempts += 1
        db.commit()
        raise bad

    model = ACCOUNT_MODELS[data.role]
    account = db.query(model).filter(model.email == data.email).first()
    if not account:
        raise bad
    account.hashed_password = hash_password(data.new_password)
    if hasattr(account, "must_change_password"):
        account.must_change_password = False
    record.used = True
    db.commit()
    return {"message": "Your password has been changed. You can log in now."}
