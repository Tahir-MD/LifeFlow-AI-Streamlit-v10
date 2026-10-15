"""
Donation reminders: tells a donor the day they can give blood again.

Runs every hour in the background (see main.py) and can also be started by an admin. A donor is
reminded once per donation: reminder_sent_for remembers which last_donation_date was reminded.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.donor import Donor
from app.services.eligibility_service import min_gap_days
from app.utils.notify import notify


def send_due_reminders(db: Session, now: Optional[datetime] = None) -> int:
    now = now or datetime.utcnow()
    sent = 0
    donors = db.query(Donor).filter(Donor.last_donation_date != None).all()  # noqa: E711
    for donor in donors:
        due = donor.last_donation_date.timestamp() + min_gap_days(donor.gender) * 86400
        if due > now.timestamp():
            continue
        if donor.reminder_sent_for == donor.last_donation_date:
            continue
        notify(db, "donor", donor.id, "You can donate blood again",
               "Thank you for your last donation. You are now able to give blood again. "
               "Someone near you may need your blood group. Open LifeFlow to see requests.",
               category="system")
        donor.reminder_sent_for = donor.last_donation_date
        sent += 1
    db.commit()
    return sent
