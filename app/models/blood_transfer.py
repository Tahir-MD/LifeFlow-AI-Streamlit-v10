from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime

from app.database import Base


class BloodTransfer(Base):
    """
    One hospital asking another hospital for blood bags from its blood bank.
    status: "pending" -> "approved" (stock leaves the sender) -> "received" (stock joins the receiver)
            or "rejected" / "cancelled".
    """
    __tablename__ = "blood_transfers"

    id = Column(Integer, primary_key=True, index=True)
    from_hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)  # sender (has the blood)
    to_hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)    # asker (needs the blood)
    blood_type = Column(String, nullable=False)
    units = Column(Integer, nullable=False)
    note = Column(String, nullable=True)
    status = Column(String, default="pending")
    earliest_expiry = Column(String, nullable=True)  # ISO date of the oldest bag sent, kept for the receiving batch
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
