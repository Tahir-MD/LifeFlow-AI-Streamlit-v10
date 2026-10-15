from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hospital import Hospital
from app.schemas.hospital_schema import HospitalOut
from app.utils.dependencies import get_current_hospital

router = APIRouter(prefix="/hospitals", tags=["Hospitals"])


@router.get("/me", response_model=HospitalOut)
def read_my_hospital_profile(current_hospital: Hospital = Depends(get_current_hospital)):
    return current_hospital


@router.get("", response_model=list[HospitalOut])
def list_all_hospitals(db: Session = Depends(get_db)):
    return db.query(Hospital).all()
