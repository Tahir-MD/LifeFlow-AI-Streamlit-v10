from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator

from app.utils.validators import validate_password_strength, validate_person_name
from datetime import datetime


class AdminLogin(BaseModel):
    email: EmailStr
    password: str


class AdminOut(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    created_at: datetime
    must_change_password: bool = True

    class Config:
        from_attributes = True


class AdminChangeCredentials(BaseModel):
    current_password: str
    new_email: EmailStr
    new_full_name: Optional[str] = None
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, v):
        return validate_password_strength(v)

    @field_validator("new_full_name")
    @classmethod
    def _name(cls, v):
        return validate_person_name(v, "Name") if v and v.strip() else None
