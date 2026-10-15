from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.camp import DonationCamp, CampRSVP
from app.models.hospital import Hospital
from app.models.donor import Donor
from app.schemas.camp_schema import CampCreate, CampOut, RSVPOut
from app.utils.dependencies import get_current_hospital, get_current_donor, get_hospital_for_checkin
from app.utils.notify import notify

router = APIRouter(prefix="/camps", tags=["Donation Camps"])


def _to_camp_out(db: Session, camp: DonationCamp) -> CampOut:
    hospital = db.query(Hospital).filter(Hospital.id == camp.hospital_id).first()
    registered_count = (
        db.query(CampRSVP)
        .filter(CampRSVP.camp_id == camp.id, CampRSVP.status == "registered")
        .count()
    )
    return CampOut(
        id=camp.id,
        hospital_id=camp.hospital_id,
        hospital_name=hospital.name if hospital else "Unknown hospital",
        title=camp.title,
        description=camp.description,
        location_label=camp.location_label,
        latitude=camp.latitude,
        longitude=camp.longitude,
        camp_date=camp.camp_date,
        registered_count=registered_count,
        created_at=camp.created_at,
    )


@router.post("", response_model=CampOut, status_code=201)
def create_camp(
    camp_data: CampCreate,
    db: Session = Depends(get_db),
    current_hospital: Hospital = Depends(get_current_hospital),
):
    new_camp = DonationCamp(
        hospital_id=current_hospital.id,
        title=camp_data.title,
        description=camp_data.description,
        location_label=camp_data.location_label,
        latitude=camp_data.latitude,
        longitude=camp_data.longitude,
        camp_date=camp_data.camp_date,
    )
    db.add(new_camp)
    db.commit()
    db.refresh(new_camp)

    # Let every donor know a new drive has been organized.
    for donor in db.query(Donor).all():
        notify(
            db, "donor", donor.id,
            "New blood donation camp announced",
            f"{current_hospital.name} is holding \"{camp_data.title}\" at {camp_data.location_label} on "
            f"{camp_data.camp_date.strftime('%d %b %Y')}.",
            category="camp",
        )
    db.commit()

    return _to_camp_out(db, new_camp)


@router.get("", response_model=List[CampOut])
def list_upcoming_camps(db: Session = Depends(get_db)):
    camps = (
        db.query(DonationCamp)
        .filter(DonationCamp.camp_date >= datetime.utcnow())
        .order_by(DonationCamp.camp_date.asc())
        .all()
    )
    return [_to_camp_out(db, camp) for camp in camps]


@router.get("/mine", response_model=List[CampOut])
def list_my_camps(db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_hospital_for_checkin)):
    camps = (
        db.query(DonationCamp)
        .filter(DonationCamp.hospital_id == current_hospital.id)
        .order_by(DonationCamp.camp_date.desc())
        .all()
    )
    return [_to_camp_out(db, camp) for camp in camps]


@router.get("/mine/rsvps", response_model=List[RSVPOut])
def list_my_rsvps(db: Session = Depends(get_db), current_donor: Donor = Depends(get_current_donor)):
    """The camps this donor has signed up to attend."""
    rsvps = db.query(CampRSVP).filter(CampRSVP.donor_id == current_donor.id).order_by(CampRSVP.created_at.desc()).all()
    return [
        RSVPOut(
            id=r.id, camp_id=r.camp_id, donor_id=r.donor_id,
            donor_name=current_donor.full_name, donor_phone=current_donor.phone_number,
            donor_blood_type=current_donor.blood_type, status=r.status, created_at=r.created_at,
        )
        for r in rsvps
    ]


@router.get("/{camp_id}/rsvps", response_model=List[RSVPOut])
def list_camp_rsvps(camp_id: int, db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_current_hospital)):
    """Full list of donors who registered for one of this hospital's camps."""
    camp = db.query(DonationCamp).filter(DonationCamp.id == camp_id, DonationCamp.hospital_id == current_hospital.id).first()
    if not camp:
        raise HTTPException(status_code=404, detail="Camp not found")

    rsvps = db.query(CampRSVP).filter(CampRSVP.camp_id == camp_id).order_by(CampRSVP.created_at.asc()).all()
    results = []
    for rsvp in rsvps:
        donor = db.query(Donor).filter(Donor.id == rsvp.donor_id).first()
        results.append(RSVPOut(
            id=rsvp.id,
            camp_id=rsvp.camp_id,
            donor_id=rsvp.donor_id,
            donor_name=donor.full_name if donor else None,
            donor_phone=donor.phone_number if donor else None,
            donor_blood_type=donor.blood_type if donor else None,
            status=rsvp.status,
            created_at=rsvp.created_at,
        ))
    return results


@router.post("/{camp_id}/rsvp", response_model=RSVPOut, status_code=201)
def rsvp_to_camp(camp_id: int, db: Session = Depends(get_db), current_donor: Donor = Depends(get_current_donor)):
    camp = db.query(DonationCamp).filter(DonationCamp.id == camp_id).first()
    if not camp:
        raise HTTPException(status_code=404, detail="Camp not found")

    existing = (
        db.query(CampRSVP)
        .filter(CampRSVP.camp_id == camp_id, CampRSVP.donor_id == current_donor.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="You have already registered for this camp")

    new_rsvp = CampRSVP(camp_id=camp_id, donor_id=current_donor.id, status="registered")
    db.add(new_rsvp)

    notify(
        db, "hospital", camp.hospital_id,
        "A donor registered for your camp",
        f"{current_donor.full_name} ({current_donor.blood_type}) registered for \"{camp.title}\".",
        category="camp",
    )

    db.commit()
    db.refresh(new_rsvp)
    return RSVPOut(
        id=new_rsvp.id,
        camp_id=new_rsvp.camp_id,
        donor_id=new_rsvp.donor_id,
        donor_name=current_donor.full_name,
        donor_phone=current_donor.phone_number,
        donor_blood_type=current_donor.blood_type,
        status=new_rsvp.status,
        created_at=new_rsvp.created_at,
    )
