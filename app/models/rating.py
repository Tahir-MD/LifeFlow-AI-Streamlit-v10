from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime

from app.database import Base


class Rating(Base):
    """
    Feedback left after a donation. direction is either
    "donor_to_requester" (the donor rates the hospital/patient) or
    "requester_to_donor" (the hospital/patient rates the donor).
    """
    __tablename__ = "ratings"

    id = Column(Integer, primary_key=True, index=True)
    donation_id = Column(Integer, nullable=False, index=True)
    direction = Column(String, nullable=False)
    stars = Column(Integer, nullable=False)
    comment = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # AI sentiment on the comment, so a hospital/donor complaint doesn't
    # sit unseen among five-star ratings until an admin happens to read it.
    sentiment = Column(String, nullable=True)  # positive | neutral | negative
    flagged_for_review = Column(Boolean, default=False)
