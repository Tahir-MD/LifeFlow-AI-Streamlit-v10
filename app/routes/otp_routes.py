from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.delivery_service import delivery_status
from app.services.otp_service import send_code, verify_code
from app.utils.validators import validate_phone

router = APIRouter(prefix="/otp", tags=["Phone and email verification"])


class OtpSendIn(BaseModel):
    phone_number: Optional[str] = None
    email: Optional[EmailStr] = None
    channel: str = "sms"  # "sms" | "whatsapp" | "email"

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v):
        return validate_phone(v) if v else None

    @field_validator("channel")
    @classmethod
    def _channel(cls, v):
        return v if v in ("sms", "whatsapp", "email") else "sms"


class OtpVerifyIn(BaseModel):
    phone_number: Optional[str] = None
    email: Optional[EmailStr] = None
    code: str

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v):
        return validate_phone(v) if v else None


@router.get("/channels")
def available_channels():
    """Which ways of receiving a code are really set up on this server (the sign-up page shows only these)."""
    status = delivery_status()
    return {"sms": status["sms_configured"], "whatsapp": status["whatsapp_configured"], "email": status["email_configured"]}


@router.post("/send")
def otp_send(payload: OtpSendIn, db: Session = Depends(get_db)):
    if payload.channel == "email":
        if not payload.email:
            raise HTTPException(status_code=400, detail="Please write your email address first.")
        contact = str(payload.email)
    else:
        if not payload.phone_number:
            raise HTTPException(status_code=400, detail="Please write your phone number first.")
        contact = payload.phone_number
    dev_code = send_code(db, contact, payload.channel)
    return {"message": "If the details are correct, a 6-digit code has been sent.", "dev_code": dev_code}


@router.post("/verify")
def otp_verify(payload: OtpVerifyIn, db: Session = Depends(get_db)):
    contact = str(payload.email) if payload.email and not payload.phone_number else payload.phone_number
    if not contact:
        raise HTTPException(status_code=400, detail="Missing phone number or email.")
    token = verify_code(db, contact, payload.code.strip())
    return {"phone_token": token}
