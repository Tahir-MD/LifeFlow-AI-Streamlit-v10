"""
"Near me" for every kind of user. Anyone logged in can see nearby hospitals;
hospitals, patients and staff can also see nearby donors (first name, blood
type, area and distance only -- phone numbers stay private until a donor
accepts a request).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.models.staff import Staff
from app.utils.dependencies import get_current_any_account
from app.utils.distance import calculate_distance_kilometers

router = APIRouter(prefix="/nearby", tags=["Nearby"])


class NearbyHospital(BaseModel):
    id: int
    name: str
    phone_number: str
    area: Optional[str] = None
    city: Optional[str] = None
    latitude: float
    longitude: float
    distance_kilometers: float
    is_verified: bool = False


class NearbyDonor(BaseModel):
    id: int
    first_name: str
    blood_type: str
    area: Optional[str] = None
    city: Optional[str] = None
    latitude: float
    longitude: float
    distance_kilometers: float


def _my_position(db: Session, role: str, account_id: int):
    model = {"donor": Donor, "receiver": Receiver, "hospital": Hospital}.get(role)
    if role == "staff":
        staff = db.query(Staff).filter(Staff.id == account_id).first()
        account = db.query(Hospital).filter(Hospital.id == staff.hospital_id).first() if staff else None
    elif model:
        account = db.query(model).filter(model.id == account_id).first()
    else:
        account = None
    if not account:
        raise HTTPException(status_code=404, detail="Your location is not available.")
    return account.latitude, account.longitude


@router.get("/me")
def my_position(db: Session = Depends(get_db), who=Depends(get_current_any_account)):
    """Where the map should start: the logged-in account's own place (a staff member uses their hospital's)."""
    role, account_id = who
    latitude, longitude = _my_position(db, role, account_id)
    return {"latitude": latitude, "longitude": longitude}


@router.get("/hospitals", response_model=List[NearbyHospital])
def nearby_hospitals(
    latitude: Optional[float] = Query(None), longitude: Optional[float] = Query(None),
    radius_km: float = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), who=Depends(get_current_any_account),
):
    role, account_id = who
    if latitude is None or longitude is None:
        latitude, longitude = _my_position(db, role, account_id)
    rows = []
    for h in db.query(Hospital).all():
        km = calculate_distance_kilometers(latitude, longitude, h.latitude, h.longitude)
        if km <= radius_km and not (role == "hospital" and h.id == account_id):
            rows.append(NearbyHospital(
                id=h.id, name=h.name, phone_number=h.phone_number, area=h.area, city=h.city,
                latitude=h.latitude, longitude=h.longitude, distance_kilometers=round(km, 1), is_verified=bool(h.is_verified),
            ))
    return sorted(rows, key=lambda r: r.distance_kilometers)[:50]


@router.get("/donors", response_model=List[NearbyDonor])
def nearby_donors(
    blood_type: Optional[str] = Query(None),
    latitude: Optional[float] = Query(None), longitude: Optional[float] = Query(None),
    radius_km: float = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), who=Depends(get_current_any_account),
):
    role, account_id = who
    if role not in ("hospital", "receiver", "staff", "admin"):
        raise HTTPException(status_code=403, detail="Only hospitals, patients and staff can see nearby donors.")
    if latitude is None or longitude is None:
        latitude, longitude = _my_position(db, role, account_id)
    query = db.query(Donor)
    if blood_type:
        query = query.filter(Donor.blood_type == blood_type)
    rows = []
    for d in query.all():
        km = calculate_distance_kilometers(latitude, longitude, d.latitude, d.longitude)
        if km <= radius_km:
            rows.append(NearbyDonor(
                id=d.id, first_name=(d.full_name or "").split(" ")[0], blood_type=d.blood_type,
                area=d.area, city=d.city,
                # Rounded so a donor's exact home is never shown on the map.
                latitude=round(d.latitude, 2), longitude=round(d.longitude, 2),
                distance_kilometers=round(km, 1),
            ))
    return sorted(rows, key=lambda r: r.distance_kilometers)[:50]
