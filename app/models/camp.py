from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from datetime import datetime

from app.database import Base


class DonationCamp(Base):
    """A blood donation drive or camp organized by a hospital."""
    __tablename__ = "donation_camps"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    location_label = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    camp_date = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CampRSVP(Base):
    """A donor's registration to attend a donation camp."""
    __tablename__ = "camp_rsvps"

    id = Column(Integer, primary_key=True, index=True)
    camp_id = Column(Integer, ForeignKey("donation_camps.id"), nullable=False)
    donor_id = Column(Integer, ForeignKey("donors.id"), nullable=False)
    status = Column(String, default="registered")  # registered, attended, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    # QR check-in at the camp door
    checked_in_at = Column(DateTime, nullable=True)
    checked_in_by = Column(String, nullable=True)   # "hospital" or the staff member's name
    walk_in = Column(Boolean, default=False)        # came without registering first
