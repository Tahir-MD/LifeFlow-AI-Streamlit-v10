from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime

from app.database import Base


class Admin(Base):
    """
    The LifeFlow admin account. Admins can see every donor, hospital,
    and receiver's full history (requests, donations, notifications) --
    kept separate from the individual histories those users see for
    themselves.
    """
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # True for the seeded default admin account until they set their own
    # username/password; the frontend forces a credentials-change page
    # before showing any other admin functionality while this is true.
    must_change_password = Column(Boolean, default=True)

    # Two-factor authentication (TOTP, RFC 6238) -- optional, off by default.
    totp_secret = Column(String, nullable=True)
    two_factor_enabled = Column(Boolean, default=False)
