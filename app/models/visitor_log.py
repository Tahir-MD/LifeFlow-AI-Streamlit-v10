from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from datetime import datetime

from app.database import Base


class VisitorEntry(Base):
    """
    One donor or patient a staff member attended to in person during
    their shift, entered by the staff member at the front desk. This
    is what builds up each staff member's own separate shift record --
    how many donors came, how many patients, where from, and their
    details -- which they can review and print when they go off duty.
    """
    __tablename__ = "visitor_entries"

    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)

    visitor_type = Column(String, nullable=False)  # "donor" or "patient"
    full_name = Column(String, nullable=False)
    blood_type = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    from_location = Column(String, nullable=True)  # where they came from
    notes = Column(String, nullable=True)

    logged_at = Column(DateTime, default=datetime.utcnow)
