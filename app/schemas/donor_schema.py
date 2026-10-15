from pydantic import BaseModel, EmailStr, Field, create_model, field_validator
from datetime import datetime
from typing import Optional

from app.schemas.location_schema import LocationIn, LocationOut
from app.utils.validators import validate_password_strength, validate_person_name, validate_phone

from app.services.eligibility_service import YES_MEANS_NO, FEMALE_ONLY

BLOOD_TYPES = {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"}

# The health questionnaire. Every yes/no question comes from eligibility_service.py, so the form,
# the rules and this schema can never get out of step.
EligibilityAnswers = create_model(
    "EligibilityAnswers",
    age=(int, Field(ge=0, le=120)),
    gender=(str, ...),
    weight_kg=(float, Field(ge=20, le=250)),
    hemoglobin=(Optional[float], Field(default=None, ge=3, le=25)),
    last_donation_date=(Optional[str], None),
    **{key: (bool, False) for key, _message, _days in YES_MEANS_NO + FEMALE_ONLY},
)


class DonorCreate(LocationIn):
    full_name: str
    email: EmailStr
    password: str
    blood_type: str
    phone_number: str
    eligibility: EligibilityAnswers   # a donor must pass the health questionnaire to register
    phone_token: str                  # proof the phone number (or email) was verified by a code
    referral_code: Optional[str] = None   # a friend's invite code, optional

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
        return validate_phone(v)

    @field_validator("blood_type")
    @classmethod
    def _blood(cls, v):
        if v not in BLOOD_TYPES:
            raise ValueError("Choose a valid blood type.")
        return v


class DonorLogin(BaseModel):
    email: EmailStr
    password: str


class DonorOut(LocationOut):
    id: int
    full_name: str
    email: EmailStr
    blood_type: str
    phone_number: str
    latitude: float
    longitude: float
    is_eligible: bool
    last_donation_date: Optional[datetime] = None
    points: int
    medical_clearance_status: str = "pending"
    age: Optional[int] = None
    gender: Optional[str] = None
    weight_kg: Optional[float] = None
    deferred_until: Optional[datetime] = None
    phone_verified: Optional[bool] = None
    email_verified: Optional[bool] = None
    referral_code: Optional[str] = None
    notify_sms: Optional[bool] = None
    notify_whatsapp: Optional[bool] = None

    class Config:
        from_attributes = True
