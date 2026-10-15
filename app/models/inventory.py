from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from datetime import datetime

from app.database import Base


class BloodInventory(Base):
    """
    One blood bank shelf: how many bags of one blood type a hospital
    currently has in stock.
    """
    __tablename__ = "blood_inventory"
    __table_args__ = (UniqueConstraint("hospital_id", "blood_type", name="uq_hospital_blood_type"),)

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    blood_type = Column(String, nullable=False)
    units_available = Column(Integer, default=0)
    low_stock_threshold = Column(Integer, default=5)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
