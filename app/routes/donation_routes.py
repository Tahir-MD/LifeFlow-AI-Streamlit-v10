from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.donation import Donation
from app.models.request import BloodRequest
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.schemas.donation_schema import DonationHistoryOut
from app.utils.dependencies import get_current_donor, get_current_hospital, get_current_receiver
from app.services.history_service import build_history_entry, donations_for_requests

router = APIRouter(prefix="/donations", tags=["Donation History"])


def _entries_for_donations(db: Session, donations: List[Donation]) -> List[DonationHistoryOut]:
    results = []
    for donation in donations:
        blood_request = db.query(BloodRequest).filter(BloodRequest.id == donation.request_id).first()
        if not blood_request:
            continue
        entry = build_history_entry(db, donation, blood_request)
        if entry:
            results.append(entry)
    return results


@router.get("/donor/history", response_model=List[DonationHistoryOut])
def donor_donation_history(db: Session = Depends(get_db), current_donor: Donor = Depends(get_current_donor)):
    """
    Every donation this donor has ever made, with full details of who
    received it. This always reflects the donor's complete history --
    logging out and back in, even the next day, shows the same list,
    since it is read fresh from the database by this donor's id.
    """
    donations = (
        db.query(Donation)
        .filter(Donation.donor_id == current_donor.id)
        .order_by(Donation.donated_at.desc())
        .all()
    )
    return _entries_for_donations(db, donations)


@router.get("/hospital/history", response_model=List[DonationHistoryOut])
def hospital_donation_history(db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_current_hospital)):
    """Every donation received against this hospital's requests, with full donor details."""
    request_ids = [
        r.id for r in db.query(BloodRequest.id)
        .filter(BloodRequest.requester_type == "hospital", BloodRequest.requester_id == current_hospital.id)
        .all()
    ]
    donations = donations_for_requests(db, request_ids)
    return _entries_for_donations(db, donations)


@router.get("/receiver/history", response_model=List[DonationHistoryOut])
def receiver_donation_history(db: Session = Depends(get_db), current_receiver: Receiver = Depends(get_current_receiver)):
    """Every donation received against this patient's requests, with full donor details."""
    request_ids = [
        r.id for r in db.query(BloodRequest.id)
        .filter(BloodRequest.requester_type == "receiver", BloodRequest.requester_id == current_receiver.id)
        .all()
    ]
    donations = donations_for_requests(db, request_ids)
    return _entries_for_donations(db, donations)
