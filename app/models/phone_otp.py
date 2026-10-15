from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime

from app.database import Base


class PhoneOtp(Base):
    """A one-time 6-digit code sent to a phone number to prove the person owns it. Only a hash is stored."""
    __tablename__ = "phone_otps"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
