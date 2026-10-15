from pydantic import BaseModel, field_validator

from app.utils.validators import validate_person_name, validate_optional_phone
from datetime import datetime
from typing import Optional


class VisitorEntryCreate(BaseModel):
    visitor_type: str  # "donor" | "patient"
    full_name: str
    blood_type: Optional[str] = None
    phone_number: Optional[str] = None
    from_location: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("visitor_type")
    @classmethod
    def _type(cls, v):
        if v not in ("donor", "patient"):
            raise ValueError("Choose donor or patient.")
        return v

    @field_validator("full_name")
    @classmethod
    def _name(cls, v):
        return validate_person_name(v, "Name")

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v):
        return validate_optional_phone(v)

    @field_validator("blood_type")
    @classmethod
    def _blood(cls, v):
        if v and v.strip() and v.strip() not in {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"}:
            raise ValueError("Choose a valid blood type.")
        return v.strip() if v and v.strip() else None


class VisitorEntryOut(BaseModel):
    id: int
    staff_id: int
    hospital_id: int
    visitor_type: str
    full_name: str
    blood_type: Optional[str] = None
    phone_number: Optional[str] = None
    from_location: Optional[str] = None
    notes: Optional[str] = None
    logged_at: datetime

    # Filled in by the route, not stored on the row itself, so the
    # hospital's and admin's combined views show who logged each entry.
    staff_name: Optional[str] = None
    staff_shift: Optional[str] = None

    class Config:
        from_attributes = True
