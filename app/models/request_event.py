from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

from app.database import Base


class RequestEvent(Base):
    """One step in the life of a blood request, shown to the requester as a live timeline."""
    __tablename__ = "request_events"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, nullable=False, index=True)
    # created, held, approved, stock_checked, donors_alerted, donor_accepted, donor_on_the_way,
    # donor_arrived, donated, fulfilled, rejected
    kind = Column(String, nullable=False)
    message = Column(String, nullable=False)
    actor_type = Column(String, nullable=True)
    actor_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
