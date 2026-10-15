"""
Shortage forecasting.

This deliberately avoids heavyweight ML libraries (pandas / scikit-learn /
prophet) so the feature works anywhere the rest of the backend runs, with
no extra install step. It combines two signals per hospital and blood
type:

1. Recent daily demand (units requested per day, from real request
   history), used to project how many days of current stock remain.
2. A simple trend comparison (first half vs. second half of the lookback
   window) so the dashboard can say demand is rising, falling, or steady.

The numeric part is a transparent, explainable statistical model -- exactly
the kind of thing worth naming clearly in a hackathon write-up rather than
overselling as a deep learning model it isn't.
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.request import BloodRequest
from app.models.inventory import BloodInventory

LOOKBACK_DAYS = 30
FORECAST_HORIZON_DAYS = 7
BLOOD_TYPES = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]


def _daily_demand(db: Session, hospital_id: Optional[int], blood_type: str, lookback_days: int) -> list:
    """Units requested per day for this blood type, most recent `lookback_days` days."""
    since = datetime.utcnow() - timedelta(days=lookback_days)
    query = db.query(BloodRequest).filter(
        BloodRequest.blood_type_needed == blood_type,
        BloodRequest.created_at >= since,
    )
    if hospital_id is not None:
        query = query.filter(BloodRequest.requester_type == "hospital", BloodRequest.requester_id == hospital_id)

    requests = query.all()
    daily_totals = {}
    for day_offset in range(lookback_days):
        day = (since + timedelta(days=day_offset)).date()
        daily_totals[day] = 0
    for request in requests:
        day = request.created_at.date()
        if day in daily_totals:
            daily_totals[day] += request.units_needed
    return [daily_totals[day] for day in sorted(daily_totals.keys())]


def forecast_blood_type(db: Session, hospital_id: Optional[int], blood_type: str) -> dict:
    """
    One blood type's forecast: recent average daily demand, trend
    direction, current stock, and estimated days until that stock runs
    out at the current pace.
    """
    daily_values = _daily_demand(db, hospital_id, blood_type, LOOKBACK_DAYS)
    total_days = len(daily_values)
    average_daily_demand = round(sum(daily_values) / total_days, 2) if total_days else 0.0

    midpoint = total_days // 2
    first_half = daily_values[:midpoint] or [0]
    second_half = daily_values[midpoint:] or [0]
    first_avg = sum(first_half) / len(first_half)
    second_avg = sum(second_half) / len(second_half)

    if second_avg > first_avg * 1.15:
        trend = "rising"
    elif second_avg < first_avg * 0.85:
        trend = "falling"
    else:
        trend = "steady"

    current_stock = 0
    if hospital_id is not None:
        row = (
            db.query(BloodInventory)
            .filter(BloodInventory.hospital_id == hospital_id, BloodInventory.blood_type == blood_type)
            .first()
        )
        current_stock = row.units_available if row else 0

    days_until_shortage = None
    if average_daily_demand > 0:
        days_until_shortage = round(current_stock / average_daily_demand, 1)

    projected_demand_next_week = round(average_daily_demand * FORECAST_HORIZON_DAYS, 1)

    if days_until_shortage is not None and days_until_shortage <= 3:
        risk_level = "high"
    elif days_until_shortage is not None and days_until_shortage <= 7:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "blood_type": blood_type,
        "average_daily_demand": average_daily_demand,
        "trend": trend,
        "current_stock": current_stock,
        "projected_demand_next_7_days": projected_demand_next_week,
        "days_until_shortage": days_until_shortage,
        "risk_level": risk_level,
    }


def forecast_hospital(db: Session, hospital_id: int) -> list:
    """Every blood type's forecast for one hospital, riskiest first."""
    results = [forecast_blood_type(db, hospital_id, blood_type) for blood_type in BLOOD_TYPES]
    risk_order = {"high": 0, "medium": 1, "low": 2}
    results.sort(key=lambda item: (risk_order[item["risk_level"]], -(item["average_daily_demand"])))
    return results


def forecast_platform(db: Session) -> list:
    """Same idea, but platform-wide (every hospital's requests combined) -- for the admin view."""
    results = [forecast_blood_type(db, None, blood_type) for blood_type in BLOOD_TYPES]
    risk_order = {"high": 0, "medium": 1, "low": 2}
    results.sort(key=lambda item: (risk_order[item["risk_level"]], -(item["average_daily_demand"])))
    return results
