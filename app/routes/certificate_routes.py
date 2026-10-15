"""
Digital donor certificates. Every donation gets a certificate with a code that anyone can check
at /certificates/verify/<code> (for example by scanning the QR code on the printed certificate).
The code is a signature made with the server's secret key, so it cannot be guessed or forged.
"""
import hashlib
import hmac
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import SECRET_KEY
from app.database import get_db
from app.models.donation import Donation
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.request import BloodRequest
from app.utils.badges import get_badge_tier
from app.utils.dependencies import get_current_donor

router = APIRouter(prefix="/certificates", tags=["Certificates"])


def certificate_code(donation_id: int, donor_id: int) -> str:
    signature = hmac.new(SECRET_KEY.encode(), f"cert:{donation_id}:{donor_id}".encode(), hashlib.sha256).hexdigest()[:8].upper()
    return f"LF-{donation_id:06d}-{signature}"


class CertificateOut(BaseModel):
    code: str
    donation_id: int
    donated_at: datetime
    units_donated: int
    blood_type: str
    given_to: str          # hospital name, or "a patient in need" (patients' names stay private)


class CertificatesOut(BaseModel):
    donor_name: str
    blood_type: str
    total_donations: int
    total_units: int
    lives_impacted: int
    badge_tier: str
    certificates: List[CertificateOut]


def _given_to(db: Session, blood_request: Optional[BloodRequest]) -> str:
    if blood_request and blood_request.requester_type == "hospital":
        hospital = db.query(Hospital).filter(Hospital.id == blood_request.requester_id).first()
        if hospital:
            return hospital.name
    return "a patient in need"


@router.get("/me", response_model=CertificatesOut)
def my_certificates(db: Session = Depends(get_db), donor: Donor = Depends(get_current_donor)):
    donations = db.query(Donation).filter(Donation.donor_id == donor.id).order_by(Donation.donated_at.desc()).all()
    items = []
    for donation in donations:
        blood_request = db.query(BloodRequest).filter(BloodRequest.id == donation.request_id).first()
        items.append(CertificateOut(
            code=certificate_code(donation.id, donor.id), donation_id=donation.id, donated_at=donation.donated_at,
            units_donated=donation.units_donated, blood_type=donor.blood_type, given_to=_given_to(db, blood_request),
        ))
    total_units = sum(d.units_donated for d in donations)
    return CertificatesOut(
        donor_name=donor.full_name, blood_type=donor.blood_type, total_donations=len(donations),
        total_units=total_units, lives_impacted=total_units * 3, badge_tier=get_badge_tier(len(donations)),
        certificates=items,
    )


@router.get("/verify/{code}")
def verify_certificate(code: str, db: Session = Depends(get_db)):
    """Public: confirms a certificate is real. Shows only the donor's first name and last initial."""
    invalid = {"valid": False}
    parts = code.strip().upper().split("-")
    if len(parts) != 3 or parts[0] != "LF" or not parts[1].isdigit():
        return invalid
    donation = db.query(Donation).filter(Donation.id == int(parts[1])).first()
    if not donation:
        return invalid
    donor = db.query(Donor).filter(Donor.id == donation.donor_id).first()
    if not donor or not hmac.compare_digest(certificate_code(donation.id, donor.id), "-".join(parts)):
        return invalid
    names = donor.full_name.split()
    short_name = names[0] + (f" {names[-1][0]}." if len(names) > 1 else "")
    blood_request = db.query(BloodRequest).filter(BloodRequest.id == donation.request_id).first()
    return {
        "valid": True, "donor": short_name, "blood_type": donor.blood_type, "units": donation.units_donated,
        "date": donation.donated_at.date().isoformat(), "given_to": _given_to(db, blood_request),
    }
