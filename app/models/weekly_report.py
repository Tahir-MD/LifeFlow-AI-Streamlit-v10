from sqlalchemy import Column, Integer, String, DateTime, Text
from datetime import datetime

from app.database import Base


class WeeklyReport(Base):
    """A saved weekly summary. scope is "platform" (admin) or "hospital" (hospital_id says which one)."""
    __tablename__ = "weekly_reports"

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String, nullable=False, index=True)
    hospital_id = Column(Integer, nullable=True, index=True)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    data_json = Column(Text, nullable=False)
    narrative = Column(Text, nullable=True)
    narrative_source = Column(String, default="rules")   # "ai" | "rules"
    created_at = Column(DateTime, default=datetime.utcnow)
