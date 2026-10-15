from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime

from app.database import Base


class PasswordReset(Base):
    """A one-time 6-digit code used by "Forgot password". Only a hash of the code is stored."""
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String, nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
