from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime

from app.database import Base


class Notification(Base):
    """
    A single in-app notification for a donor, hospital, or receiver.
    user_type is one of "donor", "hospital", "receiver".
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_type = Column(String, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)
    category = Column(String, default="general")  # general, request, donation, camp, system
    related_request_id = Column(Integer, nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
