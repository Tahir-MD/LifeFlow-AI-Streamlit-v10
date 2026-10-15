from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from datetime import datetime

from app.database import Base


class Donor(Base):
    __tablename__ = "donors"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    blood_type = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    # Plain-language location (so nobody needs to know latitude / longitude).
    village = Column(String, nullable=True)
    area = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    country = Column(String, nullable=True)
    is_eligible = Column(Boolean, default=True)
    last_donation_date = Column(DateTime, nullable=True)
    points = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Set by an admin (standing in for a medical provider's sign-off) via
    # the verification panel: "pending" | "cleared" | "flagged".
    # This is separate from is_eligible, which is the donor's own
    # self-reported 90-day cooldown status.
    medical_clearance_status = Column(String, default="pending")
    medical_clearance_notes = Column(String, nullable=True)

    # Health screening answers kept from the sign-up questionnaire (only the numbers, not the
    # detailed medical answers).
    age = Column(Integer, nullable=True)
    gender = Column(String, nullable=True)        # "male" | "female" -- decides the wait between donations
    weight_kg = Column(Float, nullable=True)
    eligibility_checked_at = Column(DateTime, nullable=True)
    deferred_until = Column(DateTime, nullable=True)  # a temporary "not yet" from the questionnaire

    phone_verified = Column(Boolean, default=False)
    # How alerts reach this donor besides the app: SMS on by default, WhatsApp only if they choose it.
    notify_sms = Column(Boolean, default=True)
    notify_whatsapp = Column(Boolean, default=False)
    # The last_donation_date a "you can donate again" reminder was already sent for.
    reminder_sent_for = Column(DateTime, nullable=True)

    email_verified = Column(Boolean, default=False)
    # Invite-a-friend: every donor has a share code. A friend who signs up with it, and later gives
    # blood for the first time, earns both donors bonus points (referral_rewarded stops it paying twice).
    referral_code = Column(String, unique=True, index=True, nullable=True)
    referred_by_id = Column(Integer, nullable=True)
    referral_rewarded = Column(Boolean, default=False)
