from sqlalchemy import Column, Integer, DateTime, ForeignKey
from datetime import datetime

from app.database import Base


class Donation(Base):
    __tablename__ = "donations"

    id = Column(Integer, primary_key=True, index=True)
    donor_id = Column(Integer, ForeignKey("donors.id"), nullable=False)
    request_id = Column(Integer, ForeignKey("blood_requests.id"), nullable=False)
    units_donated = Column(Integer, default=1)
    donated_at = Column(DateTime, default=datetime.utcnow)
