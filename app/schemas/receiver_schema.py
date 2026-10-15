from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional

from app.schemas.location_schema import LocationIn, LocationOut
from app.utils.validators import (
    validate_password_strength, validate_person_name, validate_phone, validate_cnic,
)


class ReceiverCreate(LocationIn):
    full_name: str
    email: EmailStr
    password: str
    phone_number: str
    cnic_number: str
    address: Optional[str] = None  # house / street details, optional now that area + city are asked separately
    patient_name: Optional[str] = None
    phone_token: str  # proof the phone number was verified by a code

    @field_validator("full_name")
    @classmethod
    def _name(cls, v):
        return validate_person_name(v, "Name")

    @field_validator("patient_name")
    @classmethod
    def _patient(cls, v):
        return validate_person_name(v, "Patient name") if v and v.strip() else None

    @field_validator("password")
    @classmethod
    def _password(cls, v):
        return validate_password_strength(v)

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v):
        return validate_phone(v)

    @field_validator("cnic_number")
    @classmethod
    def _cnic(cls, v):
        return validate_cnic(v)

    @field_validator("address")
    @classmethod
    def _address(cls, v):
        v = " ".join((v or "").split())
        return v[:200] if v else None


class ReceiverLogin(BaseModel):
    email: EmailStr
    password: str


class ReceiverOut(LocationOut):
    id: int
    full_name: str
    email: EmailStr
    phone_number: str
    cnic_number: str
    address: Optional[str] = None
    patient_name: Optional[str] = None
    latitude: float
    longitude: float

    class Config:
        from_attributes = True
