from datetime import datetime, timedelta
from typing import Optional

MINIMUM_DAYS_BETWEEN_DONATIONS = 90

# Ordered from highest to lowest so the first match wins.
BADGE_TIERS = [
    (20, "Platinum Lifesaver"),
    (10, "Gold Lifesaver"),
    (5, "Silver Lifesaver"),
    (1, "Bronze Lifesaver"),
    (0, "New Donor"),
]


def get_badge_tier(total_donations: int) -> str:
    for threshold, label in BADGE_TIERS:
        if total_donations >= threshold:
            return label
    return "New Donor"


def get_next_eligible_date(last_donation_date: Optional[datetime], gender: Optional[str] = None,
                           deferred_until: Optional[datetime] = None) -> Optional[datetime]:
    """When the donor may give blood again (women wait 120 days, men 90), or None if already free."""
    from app.services.eligibility_service import min_gap_days
    candidates = []
    if last_donation_date:
        candidates.append(last_donation_date + timedelta(days=min_gap_days(gender)))
    if deferred_until:
        candidates.append(deferred_until)
    if not candidates:
        return None
    next_date = max(candidates)
    return next_date if next_date > datetime.utcnow() else None


def is_eligible_now(is_eligible_flag: bool, last_donation_date: Optional[datetime], gender: Optional[str] = None,
                    deferred_until: Optional[datetime] = None) -> bool:
    if not is_eligible_flag and not (deferred_until and deferred_until <= datetime.utcnow()):
        return False
    return get_next_eligible_date(last_donation_date, gender, deferred_until) is None
