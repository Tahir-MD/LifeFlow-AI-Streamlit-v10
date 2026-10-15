from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional


class CampCreate(BaseModel):
    title: str
    description: Optional[str] = None
    location_label: str
    latitude: float
    longitude: float
    camp_date: datetime

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        v = " ".join((v or "").split())
        if len(v) < 3:
            raise ValueError("Title must be at least 3 characters.")
        return v


class CampOut(BaseModel):
    id: int
    hospital_id: int
    hospital_name: str
    title: str
    description: Optional[str] = None
    location_label: str
    latitude: float
    longitude: float
    camp_date: datetime
    registered_count: int
    created_at: datetime


class RSVPOut(BaseModel):
    id: int
    camp_id: int
    donor_id: int
    donor_name: Optional[str] = None
    donor_phone: Optional[str] = None
    donor_blood_type: Optional[str] = None
    status: str
    created_at: datetime
