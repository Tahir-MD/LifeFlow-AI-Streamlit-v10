from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class RatingCreate(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: Optional[str] = None


class RatingOut(BaseModel):
    id: int
    donation_id: int
    direction: str
    stars: int
    comment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RatingSummaryOut(BaseModel):
    average_stars: Optional[float] = None
    total_ratings: int
    ratings: list[RatingOut]
