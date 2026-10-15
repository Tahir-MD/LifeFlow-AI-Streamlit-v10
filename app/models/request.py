from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from datetime import datetime

from app.database import Base


class BloodRequest(Base):
    __tablename__ = "blood_requests"

    id = Column(Integer, primary_key=True, index=True)

    # requester_type is either "hospital" or "receiver".
    # requester_id points to the id of that hospital or that receiver.
    requester_type = Column(String, nullable=False)
    requester_id = Column(Integer, nullable=False)

    blood_type_needed = Column(String, nullable=False)
    units_needed = Column(Integer, default=1)
    units_fulfilled = Column(Integer, default=0)
    patient_name = Column(String, nullable=True)

    # Extra patient details so a donor can see the full picture before
    # deciding whether to accept or reject a request.
    patient_age = Column(Integer, nullable=True)
    patient_gender = Column(String, nullable=True)
    medical_reason = Column(String, nullable=True)

    # urgency_type is one of "emergency", "days", or "months".
    # urgency_value holds the number of days or months, and is empty for emergency.
    urgency_type = Column(String, default="emergency")
    urgency_value = Column(Integer, nullable=True)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    status = Column(String, default="open")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Every request is checked against hospital blood-bank stock first.
    # These fields record how much (if any) was covered straight from
    # inventory before the shortfall, if any, was broadcast to donors.
    fulfilled_from_inventory = Column(Boolean, default=False)
    inventory_units_used = Column(Integer, default=0)
    fulfilling_hospital_id = Column(Integer, nullable=True)

    # Fake-request protection. review_status: "ok" | "flagged" (shown to admin) | "held" (waiting for
    # admin approval, donors not alerted yet) | "approved" | "rejected". None on old rows = "ok".
    review_status = Column(String, default="ok")
    fraud_score = Column(Integer, default=0)
    fraud_flags = Column(String, nullable=True)
    is_sos = Column(Boolean, default=False)
