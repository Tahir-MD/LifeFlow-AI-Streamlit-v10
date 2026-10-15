from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class DonorStatsOut(BaseModel):
    total_donations: int
    total_units_donated: int
    estimated_lives_impacted: int
    badge_tier: str
    is_eligible_now: bool
    next_eligible_date: Optional[datetime] = None
    points: int
    average_rating: Optional[float] = None
    leaderboard_rank: Optional[int] = None


class HospitalStatsOut(BaseModel):
    total_requests: int
    open_requests: int
    fulfilled_requests: int
    total_units_received: int
    low_stock_types: list[str]


class ReceiverStatsOut(BaseModel):
    total_requests: int
    open_requests: int
    fulfilled_requests: int
    total_units_received: int


class PlatformStatsOut(BaseModel):
    total_donors: int
    total_hospitals: int
    total_patients_helped: int
    total_units_donated: int
    total_requests_fulfilled: int
    average_platform_rating: Optional[float] = None


class LeaderboardEntryOut(BaseModel):
    rank: int
    donor_id: int
    full_name: str
    blood_type: str
    points: int
    total_donations: int
    badge_tier: str
