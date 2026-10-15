from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class NotificationOut(BaseModel):
    id: int
    title: str
    message: str
    category: str
    related_request_id: Optional[int] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True
