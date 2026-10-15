"""
Emergency SOS button for patients and hospitals: one tap, no long form.

The blood type and number of bags are the only questions. The place is the one the account was
registered with. The alert goes to every compatible donor within 100 km, and the closest hospitals
are told too so they can check their blood banks. Fake-request checks still run, but an SOS is
never held back for review. Limit: 3 SOS alerts per account per day.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hospital import Hospital
from app.models.request import BloodRequest
from app.routes.request_routes import build_request_out, create_request_for
from app.schemas.request_schema import BloodRequestCreate, BloodRequestOut
from app.utils.dependencies import get_current_requester
from app.utils.distance import calculate_distance_kilometers
from app.utils.notify import notify
from app.utils.validators import validate_person_name

router = APIRouter(prefix="/sos", tags=["Emergency SOS"])

BLOOD_TYPES = {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"}
MAX_SOS_PER_DAY = 3
HOSPITAL_ALERT_RADIUS_KM = 50
MAX_HOSPITALS_ALERTED = 15


class SosIn(BaseModel):
    blood_type_needed: str
    units_needed: int = 1
    patient_name: Optional[str] = None
    medical_reason: Optional[str] = None

    @field_validator("blood_type_needed")
    @classmethod
    def _blood(cls, v):
        if v not in BLOOD_TYPES:
            raise ValueError("Choose a valid blood type.")
        return v

    @field_validator("patient_name")
    @classmethod
    def _patient(cls, v):
        return validate_person_name(v, "Patient name") if v and v.strip() else None

    @field_validator("medical_reason")
    @classmethod
    def _reason(cls, v):
        v = " ".join((v or "").split())
        return v[:200] if v else None

    @field_validator("units_needed")
    @classmethod
    def _units(cls, v):
        if not 1 <= v <= 10:
            raise ValueError("Bags needed must be between 1 and 10.")
        return v


@router.post("", response_model=BloodRequestOut, status_code=201)
def send_sos(
    payload: SosIn,
    db: Session = Depends(get_db),
    requester=Depends(get_current_requester),
):
    role, account = requester
    since = datetime.utcnow() - timedelta(hours=24)
    already = db.query(BloodRequest).filter(
        BloodRequest.requester_type == role, BloodRequest.requester_id == account.id,
        BloodRequest.is_sos == True, BloodRequest.created_at >= since,  # noqa: E712
    ).count()
    if already >= MAX_SOS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail=f"You already sent {MAX_SOS_PER_DAY} SOS alerts today. Please call the hospital directly.",
        )

    data = BloodRequestCreate(
        blood_type_needed=payload.blood_type_needed,
        units_needed=payload.units_needed,
        patient_name=payload.patient_name,
        medical_reason=payload.medical_reason,
        urgency_type="emergency",
        latitude=account.latitude,
        longitude=account.longitude,
    )
    new_request = create_request_for(db, role, account, data, is_sos=True)

    # Nearby hospitals are told as well, so they can check their blood banks right away.
    who = account.name if role == "hospital" else account.full_name
    nearby = []
    for hospital in db.query(Hospital).all():
        if role == "hospital" and hospital.id == account.id:
            continue
        distance = calculate_distance_kilometers(account.latitude, account.longitude, hospital.latitude, hospital.longitude)
        if distance <= HOSPITAL_ALERT_RADIUS_KM:
            nearby.append((distance, hospital))
    nearby.sort(key=lambda item: item[0])
    for distance, hospital in nearby[:MAX_HOSPITALS_ALERTED]:
        notify(db, "hospital", hospital.id, "SOS emergency blood alert",
               f"{who} needs {payload.units_needed} bag(s) of {payload.blood_type_needed} urgently, "
               f"about {round(distance, 1)} km from you. Please check your blood bank.",
               category="request", related_request_id=new_request.id)
    db.commit()
    return build_request_out(db, new_request)
