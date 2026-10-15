"""
Blood expiry tracking.

Each delivery of blood bags is a "batch" with an expiry date (whole blood lasts about 35 days).
BloodInventory.units_available stays the total the rest of the app already uses; the batches say
WHICH bags are the oldest. Stock is always used oldest-first (FEFO: first-expired, first-out).
"""
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.blood_batch import BloodBatch
from app.models.inventory import BloodInventory
from app.utils.notify import notify

SHELF_LIFE_DAYS = 35
SOON_DAYS = 5


def _inventory_row(db: Session, hospital_id: int, blood_type: str) -> BloodInventory:
    row = (
        db.query(BloodInventory)
        .filter(BloodInventory.hospital_id == hospital_id, BloodInventory.blood_type == blood_type)
        .first()
    )
    if not row:
        row = BloodInventory(hospital_id=hospital_id, blood_type=blood_type, units_available=0)
        db.add(row)
        db.flush()
    return row


def add_batch(db: Session, hospital_id: int, blood_type: str, units: int, collected_on: date,
              expires_on: Optional[date] = None, source: str = "manual") -> BloodBatch:
    batch = BloodBatch(
        hospital_id=hospital_id, blood_type=blood_type, units_remaining=units, units_received=units,
        collected_on=collected_on, expires_on=expires_on or (collected_on + timedelta(days=SHELF_LIFE_DAYS)),
        state="active", source=source,
    )
    db.add(batch)
    row = _inventory_row(db, hospital_id, blood_type)
    row.units_available = (row.units_available or 0) + units
    db.flush()
    return batch


def consume(db: Session, hospital_id: int, blood_type: str, units: int) -> Optional[date]:
    """
    Takes `units` bags out of the oldest active batches (does NOT change units_available -- the
    caller already did, or does it itself). Returns the earliest expiry among the bags taken.
    """
    batches: List[BloodBatch] = (
        db.query(BloodBatch)
        .filter(BloodBatch.hospital_id == hospital_id, BloodBatch.blood_type == blood_type,
                BloodBatch.state == "active", BloodBatch.units_remaining > 0)
        .order_by(BloodBatch.expires_on.asc(), BloodBatch.id.asc())
        .all()
    )
    left = units
    earliest = None
    for batch in batches:
        if left <= 0:
            break
        take = min(batch.units_remaining, left)
        batch.units_remaining -= take
        left -= take
        earliest = earliest or batch.expires_on
        if batch.units_remaining == 0:
            batch.state = "used_up"
    return earliest


def remove_units(db: Session, hospital_id: int, blood_type: str, units: int) -> Optional[date]:
    """Lowers both the total and the oldest batches (used when stock leaves for a transfer)."""
    row = _inventory_row(db, hospital_id, blood_type)
    row.units_available = max(0, (row.units_available or 0) - units)
    return consume(db, hospital_id, blood_type, units)


def discard_batch(db: Session, batch: BloodBatch, new_state: str) -> int:
    """Marks a batch expired/discarded and removes its remaining bags from the stock total."""
    removed = batch.units_remaining
    if removed:
        row = _inventory_row(db, batch.hospital_id, batch.blood_type)
        row.units_available = max(0, (row.units_available or 0) - removed)
    batch.units_remaining = 0
    batch.state = new_state
    return removed


def sweep_expired(db: Session, hospital_id: Optional[int] = None, today: Optional[date] = None) -> dict:
    """
    Run often (every hour in the background, and whenever a hospital opens its stock page):
      * batches past their expiry date are removed from stock and the hospital is told;
      * batches expiring within SOON_DAYS get a one-time warning.
    """
    today = today or datetime.utcnow().date()
    query = db.query(BloodBatch).filter(BloodBatch.state == "active", BloodBatch.units_remaining > 0)
    if hospital_id is not None:
        query = query.filter(BloodBatch.hospital_id == hospital_id)

    expired_count = soon_count = 0
    for batch in query.all():
        if batch.expires_on < today:
            removed = discard_batch(db, batch, "expired")
            expired_count += 1
            notify(db, "hospital", batch.hospital_id, "Blood bags expired",
                   f"{removed} bag(s) of {batch.blood_type} passed their expiry date ({batch.expires_on}) "
                   f"and were removed from your stock. Please discard them safely.", category="inventory")
        elif (batch.expires_on - today).days <= SOON_DAYS and not batch.alerted_soon:
            batch.alerted_soon = True
            soon_count += 1
            notify(db, "hospital", batch.hospital_id, "Blood bags expire soon",
                   f"{batch.units_remaining} bag(s) of {batch.blood_type} expire on {batch.expires_on}. "
                   f"Use them first, or offer them to another hospital through a transfer.", category="inventory")
    db.commit()
    return {"expired_batches": expired_count, "warnings_sent": soon_count}


def batch_state_label(batch: BloodBatch, today: Optional[date] = None) -> str:
    """"expired" | "critical" (<= 3 days) | "soon" (<= 7 days) | "ok" -- drives the colour on screen."""
    today = today or datetime.utcnow().date()
    if batch.state != "active":
        return batch.state
    days = (batch.expires_on - today).days
    if days < 0:
        return "expired"
    if days <= 3:
        return "critical"
    if days <= 7:
        return "soon"
    return "ok"
