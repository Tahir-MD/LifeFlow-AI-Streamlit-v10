"""
Invite a friend. Every donor has a short share code. When a friend signs up with it and later gives
blood for the FIRST time, both donors earn bonus points. The reward is paid once per friend.
"""
import secrets
from typing import Optional

from sqlalchemy.orm import Session

from app.models.donor import Donor
from app.utils.notify import notify

REFERRER_BONUS = 50    # points for the donor who invited
FRIEND_BONUS = 20      # points for the friend who gave blood
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I, so codes are easy to read aloud


def new_referral_code(db: Session) -> str:
    while True:
        code = "LF" + "".join(secrets.choice(CODE_LETTERS) for _ in range(6))
        if not db.query(Donor).filter(Donor.referral_code == code).first():
            return code


def ensure_code(db: Session, donor: Donor) -> str:
    """Donors who signed up before this feature get their code the first time they open it."""
    if not donor.referral_code:
        donor.referral_code = new_referral_code(db)
        db.flush()
    return donor.referral_code


def reward_first_donation(db: Session, donor: Donor) -> Optional[int]:
    """Called right after a donation is saved. Pays the bonus once. Returns the referrer's id if paid."""
    if not donor.referred_by_id or donor.referral_rewarded:
        return None
    referrer = db.query(Donor).filter(Donor.id == donor.referred_by_id).first()
    donor.referral_rewarded = True
    if not referrer or referrer.id == donor.id:
        return None
    referrer.points = (referrer.points or 0) + REFERRER_BONUS
    donor.points = (donor.points or 0) + FRIEND_BONUS
    first_name = donor.full_name.split()[0]
    notify(db, "donor", referrer.id, "Your friend gave blood!",
           f"{first_name} joined with your invite and just donated for the first time. You earned {REFERRER_BONUS} bonus points.",
           category="system")
    notify(db, "donor", donor.id, "Welcome bonus",
           f"Thank you for your first donation. You earned {FRIEND_BONUS} bonus points for joining through a friend.",
           category="system")
    return referrer.id
