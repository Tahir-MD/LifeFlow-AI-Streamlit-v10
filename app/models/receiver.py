from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from datetime import datetime

from app.database import Base


class Receiver(Base):
    __tablename__ = "receivers"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    cnic_number = Column(String, nullable=False)
    address = Column(String, nullable=False)
    patient_name = Column(String, nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    # Plain-language location (so nobody needs to know latitude / longitude).
    village = Column(String, nullable=True)
    area = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    country = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    phone_verified = Column(Boolean, default=False)
    notify_sms = Column(Boolean, default=True)
    notify_whatsapp = Column(Boolean, default=False)
    email_verified = Column(Boolean, default=False)
