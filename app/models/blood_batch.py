from sqlalchemy import Column, Integer, String, DateTime, Date, Boolean, ForeignKey
from datetime import datetime

from app.database import Base


class BloodBatch(Base):
    """
    A group of blood bags received on one day, with an expiry date, so old blood is used first
    and nothing is thrown away unnoticed. state: "active" | "expired" | "discarded" | "used_up".
    """
    __tablename__ = "blood_batches"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    blood_type = Column(String, nullable=False)
    units_remaining = Column(Integer, nullable=False, default=0)
    units_received = Column(Integer, nullable=False, default=0)
    collected_on = Column(Date, nullable=False)
    expires_on = Column(Date, nullable=False)
    state = Column(String, default="active")
    alerted_soon = Column(Boolean, default=False)  # the "expires soon" warning was already sent
    source = Column(String, nullable=True)         # "manual", "transfer", ...
    created_at = Column(DateTime, default=datetime.utcnow)
