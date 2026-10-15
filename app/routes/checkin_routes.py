"""
Camp QR check-in. At the camp door, a hospital (or a staff member with check-in rights) scans the
QR code on a donor's digital donor card, or types the donor number. The donor is marked as
"attended", walk-ins are added automatically, and the attendance list can be printed or downloaded.
"""
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.camp import CampRSVP, DonationCamp
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.staff import Staff
from app.utils.dependencies import get_hospital_for_checkin, oauth2_scheme
from app.utils.notify import notify
from app.utils.security import decode_access_token

router = APIRouter(prefix="/camps", tags=["Camp check-in"])


class CheckInIn(BaseModel):
    code: str   # the whole text of the scanned QR code, or just the donor number


class AttendeeOut(BaseModel):
    donor_id: int
    donor_name: str
    blood_type: str
    phone_number: str
    status: str                       # registered | attended | cancelled
    walk_in: bool
    checked_in_at: Optional[datetime] = None
    checked_in_by: Optional[str] = None


class CheckInOut(BaseModel):
    attendee: AttendeeOut
    already_checked_in: bool
    message: str


def parse_donor_id(code: str) -> int:
    """Understands 'LIFEFLOW-DONOR|id:12|name:Ali|type:O+', 'id:12', 'LF-12' and plain '12'."""
    text = (code or "").strip()
    match = re.search(r"id:\s*(\d+)", text, re.I) or re.fullmatch(r"(?:LF-?)?(\d{1,9})", text, re.I)
    if not match:
        raise HTTPException(status_code=400, detail="This is not a LifeFlow donor code.")
    return int(match.group(1))


def _camp_of(db: Session, camp_id: int, hospital: Hospital) -> DonationCamp:
    camp = db.query(DonationCamp).filter(DonationCamp.id == camp_id, DonationCamp.hospital_id == hospital.id).first()
    if not camp:
        raise HTTPException(status_code=404, detail="Camp not found")
    return camp


def _attendee(donor: Donor, rsvp: CampRSVP) -> AttendeeOut:
    return AttendeeOut(
        donor_id=donor.id, donor_name=donor.full_name, blood_type=donor.blood_type, phone_number=donor.phone_number,
        status=rsvp.status, walk_in=bool(rsvp.walk_in), checked_in_at=rsvp.checked_in_at, checked_in_by=rsvp.checked_in_by,
    )


def _checker_name(token: str, db: Session, hospital: Hospital) -> str:
    payload = decode_access_token(token) or {}
    if payload.get("role") == "staff":
        staff = db.query(Staff).filter(Staff.id == int(payload.get("sub"))).first()
        if staff:
            return f"{staff.full_name} ({staff.shift})"
    return hospital.name


@router.post("/{camp_id}/checkin", response_model=CheckInOut)
def check_in(
    camp_id: int, payload: CheckInIn, db: Session = Depends(get_db),
    hospital: Hospital = Depends(get_hospital_for_checkin), token: str = Depends(oauth2_scheme),
):
    camp = _camp_of(db, camp_id, hospital)
    donor = db.query(Donor).filter(Donor.id == parse_donor_id(payload.code)).first()
    if not donor:
        raise HTTPException(status_code=404, detail="No donor was found with this code.")

    rsvp = db.query(CampRSVP).filter(CampRSVP.camp_id == camp.id, CampRSVP.donor_id == donor.id).first()
    if rsvp and rsvp.status == "attended":
        return CheckInOut(attendee=_attendee(donor, rsvp), already_checked_in=True,
                          message="This donor was already checked in.")
    if not rsvp:
        rsvp = CampRSVP(camp_id=camp.id, donor_id=donor.id, walk_in=True)
        db.add(rsvp)
    rsvp.status = "attended"
    rsvp.checked_in_at = datetime.utcnow()
    rsvp.checked_in_by = _checker_name(token, db, hospital)
    notify(db, "donor", donor.id, "You are checked in",
           f"Thank you for coming to \"{camp.title}\". Your visit was recorded.", category="camp")
    db.commit()
    db.refresh(rsvp)
    return CheckInOut(attendee=_attendee(donor, rsvp), already_checked_in=False,
                      message="Checked in." if not rsvp.walk_in else "Checked in (walk-in, not registered before).")


@router.get("/{camp_id}/attendance", response_model=List[AttendeeOut])
def attendance(camp_id: int, db: Session = Depends(get_db), hospital: Hospital = Depends(get_hospital_for_checkin)):
    """Everyone registered or checked in for this camp. Checked-in donors come first."""
    camp = _camp_of(db, camp_id, hospital)
    rows = db.query(CampRSVP).filter(CampRSVP.camp_id == camp.id).all()
    result = []
    for rsvp in rows:
        donor = db.query(Donor).filter(Donor.id == rsvp.donor_id).first()
        if donor:
            result.append(_attendee(donor, rsvp))
    result.sort(key=lambda a: (a.status != "attended", a.checked_in_at or datetime.max, a.donor_name))
    return result
