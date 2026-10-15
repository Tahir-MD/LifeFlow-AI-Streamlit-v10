from pydantic import BaseModel, EmailStr, field_validator

from app.utils.validators import validate_password_strength, validate_person_name, validate_optional_phone
from datetime import datetime
from typing import List, Optional

from app.models.staff import ROLE_CHOICES


class StaffCreate(BaseModel):
    """Filled in by the hospital when it creates a login for a staff member."""
    full_name: str
    email: EmailStr
    password: str
    shift: str  # "Shift 1" | "Shift 2" | "Shift 3" | "Shift 4"
    role: str = "receptionist"  # receptionist | lab_technician | doctor | manager
    phone_number: Optional[str] = None

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in ROLE_CHOICES:
            raise ValueError("Choose a valid staff role.")
        return v

    @field_validator("full_name")
    @classmethod
    def _name(cls, v):
        return validate_person_name(v, "Name")

    @field_validator("password")
    @classmethod
    def _password(cls, v):
        return validate_password_strength(v)

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v):
        return validate_optional_phone(v)


class StaffLogin(BaseModel):
    email: EmailStr
    password: str


class StaffOut(BaseModel):
    id: int
    hospital_id: int
    full_name: str
    email: EmailStr
    shift: str
    role: str = "receptionist"
    permissions: List[str] = []
    phone_number: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
