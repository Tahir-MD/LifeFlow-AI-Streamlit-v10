from typing import Optional

from sqlalchemy.orm import Session

from app.models.donation import Donation
from app.models.request import BloodRequest
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.models.rating import Rating
from app.schemas.donation_schema import DonationHistoryOut


def average_rating(db: Session, donation_id: int, direction: str) -> Optional[float]:
    ratings = (
        db.query(Rating)
        .filter(Rating.donation_id == donation_id, Rating.direction == direction)
        .all()
    )
    if not ratings:
        return None
    return round(sum(r.stars for r in ratings) / len(ratings), 2)


def build_history_entry(db: Session, donation: Donation, blood_request: BloodRequest) -> Optional[DonationHistoryOut]:
    """
    Turns one completed donation, plus the request it answered, into a
    full history row with both sides' details. Used by every history
    view -- the donor's own history, the hospital's or patient's own
    history, and the admin view of everyone's history -- so all three
    always show exactly the same underlying record.
    """
    donor = db.query(Donor).filter(Donor.id == donation.donor_id).first()
    if not donor:
        return None

    requester_cnic = None
    requester_address = None
    if blood_request.requester_type == "hospital":
        requester = db.query(Hospital).filter(Hospital.id == blood_request.requester_id).first()
        requester_name = requester.name if requester else "Unknown hospital"
        requester_phone = requester.phone_number if requester else ""
    else:
        requester = db.query(Receiver).filter(Receiver.id == blood_request.requester_id).first()
        requester_name = requester.full_name if requester else "Unknown patient"
        requester_phone = requester.phone_number if requester else ""
        requester_cnic = requester.cnic_number if requester else None
        requester_address = requester.address if requester else None

    return DonationHistoryOut(
        donation_id=donation.id,
        request_id=blood_request.id,
        units_donated=donation.units_donated,
        donated_at=donation.donated_at,
        request_status=blood_request.status,
        blood_type_needed=blood_request.blood_type_needed,
        patient_name=blood_request.patient_name,
        donor_id=donor.id,
        donor_name=donor.full_name,
        donor_phone=donor.phone_number,
        donor_blood_type=donor.blood_type,
        requester_type=blood_request.requester_type,
        requester_id=blood_request.requester_id,
        requester_name=requester_name,
        requester_phone=requester_phone,
        requester_cnic=requester_cnic,
        requester_address=requester_address,
        average_donor_rating=average_rating(db, donation.id, "requester_to_donor"),
        average_requester_rating=average_rating(db, donation.id, "donor_to_requester"),
    )


def donations_for_requests(db: Session, request_ids: list) -> list:
    if not request_ids:
        return []
    return (
        db.query(Donation)
        .filter(Donation.request_id.in_(request_ids))
        .order_by(Donation.donated_at.desc())
        .all()
    )
