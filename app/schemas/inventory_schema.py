from pydantic import BaseModel
from datetime import datetime


class InventoryItemOut(BaseModel):
    blood_type: str
    units_available: int
    low_stock_threshold: int
    is_low: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class InventoryUpdateInput(BaseModel):
    blood_type: str
    units_available: int
    low_stock_threshold: int = 5


class HospitalInventoryOut(BaseModel):
    hospital_id: int
    hospital_name: str
    items: list[InventoryItemOut]
