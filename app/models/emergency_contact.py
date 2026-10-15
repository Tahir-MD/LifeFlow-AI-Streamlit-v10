from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime

from app.database import Base

CATEGORIES = ["ambulance", "emergency", "blood_bank", "hospital", "police", "fire", "helpline"]


class EmergencyContact(Base):
    """A phone number people can call in an emergency: an ambulance service, a blood bank, a helpline."""
    __tablename__ = "emergency_contacts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False, index=True)
    phone_number = Column(String, nullable=False)
    city = Column(String, nullable=True, index=True)       # empty = works everywhere / national number
    area = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    is_24h = Column(Boolean, default=True)
    is_national = Column(Boolean, default=False)
    is_approved = Column(Boolean, default=True)            # entries added by hospitals wait for the admin
    added_by_type = Column(String, nullable=True)          # "seed" | "admin" | "hospital"
    added_by_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
