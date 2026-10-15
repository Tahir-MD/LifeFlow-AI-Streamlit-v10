from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

from app.database import Base


class PushSubscription(Base):
    """
    One browser/device's push subscription, so LifeFlow can send it a
    notification even when the tab isn't open -- this is what lets a
    PWA installed on a phone's home screen receive alerts the same way
    a native app's push notifications would, without needing an app
    store build or Firebase project.
    """
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    owner_type = Column(String, nullable=False)  # donor | hospital | receiver | staff | admin
    owner_id = Column(Integer, nullable=False)
    endpoint = Column(String, unique=True, nullable=False)
    p256dh_key = Column(String, nullable=False)
    auth_key = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
