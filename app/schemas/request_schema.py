from pydantic import BaseModel, field_validator

from app.utils.validators import validate_person_name
from datetime import datetime
from typing import Optional


class BloodRequestCreate(BaseModel):
    blood_type_needed: str
    units_needed: int = 1
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    medical_reason: Optional[str] = None
    urgency_type: str = "emergency"
    urgency_value: Optional[int] = None
    latitude: float
    longitude: float

    @field_validator("patient_name")
    @classmethod
    def _patient(cls, v):
        return validate_person_name(v, "Patient name") if v and v.strip() else None

    @field_validator("units_needed")
    @classmethod
    def _units(cls, v):
        if not 1 <= v <= 20:
            raise ValueError("Bags needed must be between 1 and 20.")
        return v

    @field_validator("patient_age")
    @classmethod
    def _age(cls, v):
        if v is not None and not 0 <= v <= 120:
            raise ValueError("Patient age must be between 0 and 120.")
        return v


class BloodRequestOut(BaseModel):
    id: int
    requester_type: str
    requester_id: int
    requester_name: str
    requester_phone: str
    requester_cnic: Optional[str] = None
    requester_address: Optional[str] = None
    blood_type_needed: str
    units_needed: int
    units_fulfilled: int
    units_remaining: int
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    medical_reason: Optional[str] = None
    urgency_type: str
    urgency_value: Optional[int] = None
    latitude: float
    longitude: float
    status: str
    created_at: datetime
    fulfilled_from_inventory: bool = False
    inventory_units_used: int = 0
    fulfilling_hospital_name: Optional[str] = None
    review_status: str = "ok"
    is_sos: bool = False


class AcceptRequestInput(BaseModel):
    units_donated: int = 1


class MatchedDonorOut(BaseModel):
    donor_id: int
    full_name: str
    blood_type: str
    phone_number: str
    distance_kilometers: float
    points: int
    average_rating: Optional[float] = None
    match_score: Optional[float] = None
    no_show_risk: Optional[float] = None  # 0..1, higher = less likely to follow through
    match_reason: Optional[str] = None  # short, human-readable "why this donor" explanation
