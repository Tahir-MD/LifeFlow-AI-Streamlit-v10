from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.donor import Donor
from app.schemas.donor_schema import DonorOut, EligibilityAnswers
from app.services.eligibility_service import evaluate_eligibility, min_gap_days
from app.utils.dependencies import get_current_donor
from app.services.referral_service import ensure_code, REFERRER_BONUS, FRIEND_BONUS

router = APIRouter(prefix="/donors", tags=["Donors"])


@router.get("/me", response_model=DonorOut)
def read_my_donor_profile(current_donor: Donor = Depends(get_current_donor)):
    return current_donor


@router.post("/eligibility-check")
def eligibility_check(answers: EligibilityAnswers):
    """
    Public (no login): the sign-up form calls this to tell a person, in plain words, whether they
    can donate. It only judges the answers; nothing is saved.
    """
    return evaluate_eligibility(answers.model_dump())


@router.post("/me/eligibility")
def recheck_my_eligibility(
    answers: EligibilityAnswers,
    db: Session = Depends(get_db),
    current_donor: Donor = Depends(get_current_donor),
):
    """A registered donor answers the questionnaire again (for example before donating again)."""
    data = answers.model_dump()
    verdict = evaluate_eligibility(data)
    current_donor.age = data["age"]
    current_donor.gender = data["gender"].lower()
    current_donor.weight_kg = data["weight_kg"]
    current_donor.eligibility_checked_at = datetime.utcnow()
    if verdict["eligible"]:
        current_donor.is_eligible = True
        current_donor.deferred_until = None
    elif verdict["permanent"]:
        current_donor.is_eligible = False
        current_donor.deferred_until = None
    else:
        current_donor.deferred_until = datetime.utcnow() + timedelta(days=verdict["retry_after_days"] or 0)
    db.commit()
    return verdict


@router.get("/me/next-eligible")
def my_next_eligible_date(current_donor: Donor = Depends(get_current_donor)):
    """When this donor can give blood again, for the reminder card on the dashboard."""
    now = datetime.utcnow()
    candidates = []
    if current_donor.last_donation_date:
        candidates.append(current_donor.last_donation_date + timedelta(days=min_gap_days(current_donor.gender)))
    if current_donor.deferred_until:
        candidates.append(current_donor.deferred_until)
    next_date = max(candidates) if candidates else None
    blocked_for_good = current_donor.is_eligible is False and not current_donor.deferred_until
    eligible_now = (not blocked_for_good) and (next_date is None or next_date <= now)
    return {
        "eligible_now": eligible_now,
        "permanent_block": blocked_for_good,
        "next_eligible_date": next_date.date().isoformat() if next_date and next_date > now else None,
        "days_left": max((next_date - now).days + 1, 0) if next_date and next_date > now else 0,
        "last_donation_date": current_donor.last_donation_date.date().isoformat() if current_donor.last_donation_date else None,
        "gap_days": min_gap_days(current_donor.gender),
    }


class NotificationPrefs(BaseModel):
    notify_sms: bool = True
    notify_whatsapp: bool = False


@router.put("/me/notification-channels", response_model=DonorOut)
def set_my_notification_channels(
    prefs: NotificationPrefs,
    db: Session = Depends(get_db),
    current_donor: Donor = Depends(get_current_donor),
):
    """Choose how urgent alerts reach you besides the app: SMS and/or WhatsApp."""
    current_donor.notify_sms = prefs.notify_sms
    current_donor.notify_whatsapp = prefs.notify_whatsapp
    db.commit()
    db.refresh(current_donor)
    return current_donor


@router.get("/me/referral")
def my_referral(db: Session = Depends(get_db), current_donor: Donor = Depends(get_current_donor)):
    """The donor's invite code, and how many friends joined and gave blood through it."""
    code = ensure_code(db, current_donor)
    db.commit()
    invited = db.query(Donor).filter(Donor.referred_by_id == current_donor.id).all()
    donated = [d for d in invited if d.referral_rewarded]
    return {
        "code": code,
        "friends_joined": len(invited),
        "friends_donated": len(donated),
        "points_earned": len(donated) * REFERRER_BONUS,
        "referrer_bonus": REFERRER_BONUS,
        "friend_bonus": FRIEND_BONUS,
    }


@router.get("", response_model=list[DonorOut])
def list_all_donors(db: Session = Depends(get_db)):
    return db.query(Donor).all()
