from pydantic import BaseModel, EmailStr, field_validator

from app.schemas.location_schema import LocationIn, LocationOut
from app.utils.validators import validate_password_strength, validate_org_name, validate_phone


class HospitalCreate(LocationIn):
    name: str
    email: EmailStr
    password: str
    license_number: str
    phone_number: str
    phone_token: str  # proof the phone number was verified by a code

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return validate_org_name(v, "Hospital name")

    @field_validator("password")
    @classmethod
    def _password(cls, v):
        return validate_password_strength(v)

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v):
        return validate_phone(v)

    @field_validator("license_number")
    @classmethod
    def _license(cls, v):
        v = (v or "").strip()
        import re
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-/ ]{3,29}", v):
            raise ValueError("License number must be 4 to 30 letters or numbers.")
        return v


class HospitalLogin(BaseModel):
    email: EmailStr
    password: str


class HospitalOut(LocationOut):
    id: int
    name: str
    email: EmailStr
    license_number: str
    phone_number: str
    latitude: float
    longitude: float
    is_verified: bool = False

    class Config:
        from_attributes = True
