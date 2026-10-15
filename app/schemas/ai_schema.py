from typing import Optional, List
from pydantic import BaseModel


class ParseRequestIn(BaseModel):
    text: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class ParseRequestOut(BaseModel):
    understood: bool
    blood_type_needed: Optional[str] = None
    units_needed: Optional[int] = None
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    medical_reason: Optional[str] = None
    urgency_type: Optional[str] = None
    urgency_value: Optional[int] = None
    detected_language: Optional[str] = None
    note_to_user: Optional[str] = None


class AssistantMessageIn(BaseModel):
    message: str


class AssistantMessageOut(BaseModel):
    reply: str


class ForecastEntryOut(BaseModel):
    blood_type: str
    average_daily_demand: float
    trend: str
    current_stock: int
    projected_demand_next_7_days: float
    days_until_shortage: Optional[float] = None
    risk_level: str


class ForecastOut(BaseModel):
    entries: List[ForecastEntryOut]
    summary: Optional[str] = None
