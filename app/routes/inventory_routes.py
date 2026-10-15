from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.inventory import BloodInventory
from app.models.hospital import Hospital
from app.schemas.inventory_schema import InventoryItemOut, InventoryUpdateInput, HospitalInventoryOut
from app.models.blood_batch import BloodBatch
from app.services import batch_service
from app.utils.dependencies import get_current_hospital, get_hospital_for_stock

router = APIRouter(prefix="/inventory", tags=["Blood Inventory"])

BLOOD_TYPES = ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"]


def _ensure_rows_exist(db: Session, hospital_id: int) -> None:
    existing_types = {
        row.blood_type
        for row in db.query(BloodInventory).filter(BloodInventory.hospital_id == hospital_id).all()
    }
    for blood_type in BLOOD_TYPES:
        if blood_type not in existing_types:
            db.add(BloodInventory(hospital_id=hospital_id, blood_type=blood_type, units_available=0))
    db.commit()


def _to_item_out(row: BloodInventory) -> InventoryItemOut:
    return InventoryItemOut(
        blood_type=row.blood_type,
        units_available=row.units_available,
        low_stock_threshold=row.low_stock_threshold,
        is_low=row.units_available <= row.low_stock_threshold,
        updated_at=row.updated_at,
    )


@router.get("/me", response_model=List[InventoryItemOut])
def get_my_inventory(db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_hospital_for_stock)):
    batch_service.sweep_expired(db, current_hospital.id)
    _ensure_rows_exist(db, current_hospital.id)
    rows = db.query(BloodInventory).filter(BloodInventory.hospital_id == current_hospital.id).all()
    return [_to_item_out(r) for r in sorted(rows, key=lambda r: BLOOD_TYPES.index(r.blood_type))]


@router.put("/me", response_model=InventoryItemOut)
def update_my_inventory(
    update: InventoryUpdateInput,
    db: Session = Depends(get_db),
    current_hospital: Hospital = Depends(get_current_hospital),
):
    if update.blood_type not in BLOOD_TYPES:
        raise HTTPException(status_code=400, detail="Unknown blood type")
    if update.units_available < 0:
        raise HTTPException(status_code=400, detail="Units available cannot be negative")

    row = (
        db.query(BloodInventory)
        .filter(BloodInventory.hospital_id == current_hospital.id, BloodInventory.blood_type == update.blood_type)
        .first()
    )
    if not row:
        row = BloodInventory(hospital_id=current_hospital.id, blood_type=update.blood_type)
        db.add(row)

    removed = (row.units_available or 0) - update.units_available
    if removed > 0:
        batch_service.consume(db, current_hospital.id, update.blood_type, removed)  # oldest bags leave first
    row.units_available = update.units_available
    row.low_stock_threshold = update.low_stock_threshold
    db.commit()
    db.refresh(row)
    return _to_item_out(row)


@router.get("", response_model=List[HospitalInventoryOut])
def list_all_hospital_inventories(db: Session = Depends(get_db)):
    """Public view so donors and patients can see which nearby hospitals already have stock."""
    hospitals = db.query(Hospital).all()
    results = []
    for hospital in hospitals:
        rows = db.query(BloodInventory).filter(BloodInventory.hospital_id == hospital.id).all()
        if not rows:
            continue
        results.append(HospitalInventoryOut(
            hospital_id=hospital.id,
            hospital_name=hospital.name,
            items=[_to_item_out(r) for r in sorted(rows, key=lambda r: BLOOD_TYPES.index(r.blood_type))],
        ))
    return results


# ---------------------------------------------------------------------------
# Expiry tracking (batches of bags with an expiry date)
# ---------------------------------------------------------------------------
class BatchIn(BaseModel):
    blood_type: str
    units: int
    collected_on: Optional[date] = None
    expires_on: Optional[date] = None   # empty = 35 days after collection

    @field_validator("units")
    @classmethod
    def _units(cls, v):
        if not 1 <= v <= 500:
            raise ValueError("Bags must be between 1 and 500.")
        return v


class BatchOut(BaseModel):
    id: int
    blood_type: str
    units_remaining: int
    units_received: int
    collected_on: date
    expires_on: date
    days_left: int
    state: str       # active | expired | discarded | used_up
    urgency: str     # ok | soon | critical | expired | ...
    source: Optional[str] = None


def _batch_out(batch: BloodBatch) -> BatchOut:
    today = datetime.utcnow().date()
    return BatchOut(
        id=batch.id, blood_type=batch.blood_type, units_remaining=batch.units_remaining,
        units_received=batch.units_received, collected_on=batch.collected_on, expires_on=batch.expires_on,
        days_left=(batch.expires_on - today).days, state=batch.state,
        urgency=batch_service.batch_state_label(batch, today), source=batch.source,
    )


@router.get("/batches", response_model=List[BatchOut])
def list_my_batches(
    include_closed: bool = False,
    db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_hospital_for_stock),
):
    """Every batch of bags, oldest expiry first. Active only, unless include_closed is set."""
    batch_service.sweep_expired(db, current_hospital.id)
    query = db.query(BloodBatch).filter(BloodBatch.hospital_id == current_hospital.id)
    if not include_closed:
        query = query.filter(BloodBatch.state == "active", BloodBatch.units_remaining > 0)
    return [_batch_out(b) for b in query.order_by(BloodBatch.expires_on.asc(), BloodBatch.id.asc()).limit(300).all()]


@router.post("/batches", response_model=BatchOut, status_code=201)
def add_my_batch(
    payload: BatchIn,
    db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_hospital_for_stock),
):
    """Records new bags (received, collected at a camp...) with their expiry date. Adds to the stock total."""
    if payload.blood_type not in BLOOD_TYPES:
        raise HTTPException(status_code=400, detail="Unknown blood type")
    today = datetime.utcnow().date()
    collected = payload.collected_on or today
    if collected > today:
        raise HTTPException(status_code=400, detail="The collection date cannot be in the future.")
    expires = payload.expires_on or (collected + timedelta(days=batch_service.SHELF_LIFE_DAYS))
    if expires < today:
        raise HTTPException(status_code=400, detail="These bags have already expired.")
    if expires <= collected:
        raise HTTPException(status_code=400, detail="The expiry date must be after the collection date.")
    batch = batch_service.add_batch(db, current_hospital.id, payload.blood_type, payload.units, collected, expires)
    db.commit()
    db.refresh(batch)
    return _batch_out(batch)


@router.post("/batches/{batch_id}/discard", response_model=BatchOut)
def discard_my_batch(
    batch_id: int,
    db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_hospital_for_stock),
):
    """Throws away a batch (damaged, expired...). Its remaining bags leave the stock total."""
    batch = db.query(BloodBatch).filter(BloodBatch.id == batch_id, BloodBatch.hospital_id == current_hospital.id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.state == "active":
        batch_service.discard_batch(db, batch, "discarded")
        db.commit()
        db.refresh(batch)
    return _batch_out(batch)


@router.get("/expiring", response_model=List[BatchOut])
def my_expiring_batches(
    days: int = 7,
    db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_hospital_for_stock),
):
    """Batches that expire within the next `days` days."""
    batch_service.sweep_expired(db, current_hospital.id)
    limit = datetime.utcnow().date() + timedelta(days=max(1, min(days, 60)))
    rows = (
        db.query(BloodBatch)
        .filter(BloodBatch.hospital_id == current_hospital.id, BloodBatch.state == "active",
                BloodBatch.units_remaining > 0, BloodBatch.expires_on <= limit)
        .order_by(BloodBatch.expires_on.asc()).all()
    )
    return [_batch_out(b) for b in rows]
