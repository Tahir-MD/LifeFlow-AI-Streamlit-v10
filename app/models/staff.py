from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from datetime import datetime

from app.database import Base


SHIFT_CHOICES = ["Shift 1", "Shift 2", "Shift 3", "Shift 4"]
ROLE_CHOICES = ["receptionist", "lab_technician", "doctor", "manager"]


class Staff(Base):
    """
    A hospital staff member. The hospital creates this account from
    its own dashboard and hands the login (email + password) to the
    staff member. Each staff member is tied to one fixed shift, so
    whoever is on duty for that shift logs in with their own account
    and every donor/patient they attend to is saved under their name,
    kept completely separate from every other staff member's record.
    """
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    shift = Column(String, nullable=False)  # one of SHIFT_CHOICES
    phone_number = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # What this person may do: see app/utils/permissions.py
    role = Column(String, default="receptionist")
