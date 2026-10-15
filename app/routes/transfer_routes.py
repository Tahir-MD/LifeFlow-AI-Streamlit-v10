"""
Multi-hospital blood transfers: a hospital that is short of a blood type asks another hospital
for bags from its blood bank.

  pending  -> the sender approves ("approved": the bags leave the sender's stock, oldest first)
           -> the asker confirms arrival ("received": the bags join the asker's stock)
  or       -> "rejected" by the sender / "cancelled" by the asker while still pending.
"""
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.blood_transfer import BloodTransfer
from app.models.hospital import Hospital
from app.models.inventory import BloodInventory
from app.services import batch_service
from app.utils.dependencies import get_current_hospital
from app.utils.distance import calculate_distance_kilometers
from app.utils.notify import notify

router = APIRouter(prefix="/transfers", tags=["Hospital transfers"])

BLOOD_TYPES = ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"]


class SupplierOut(BaseModel):
    hospital_id: int
    name: str
    city: Optional[str] = None
    area: Optional[str] = None
    phone_number: str
    units_available: int
    distance_kilometers: float
    is_verified: bool = False


class TransferIn(BaseModel):
    from_hospital_id: int        # the hospital that has the blood
    blood_type: str
    units: int
    note: Optional[str] = None

    @field_validator("units")
    @classmethod
    def _units(cls, v):
        if not 1 <= v <= 100:
            raise ValueError("Bags must be between 1 and 100.")
        return v

    @field_validator("note")
    @classmethod
    def _note(cls, v):
        v = " ".join((v or "").split())
        return v[:200] if v else None


class TransferOut(BaseModel):
    id: int
    direction: str            # "incoming" (someone asks me) | "outgoing" (I ask someone)
    other_hospital: str
    other_phone: str
    blood_type: str
    units: int
    note: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime


def _to_out(db: Session, transfer: BloodTransfer, me: Hospital) -> TransferOut:
    incoming = transfer.from_hospital_id == me.id
    other = db.query(Hospital).filter(Hospital.id == (transfer.to_hospital_id if incoming else transfer.from_hospital_id)).first()
    return TransferOut(
        id=transfer.id, direction="incoming" if incoming else "outgoing",
        other_hospital=other.name if other else "Unknown hospital", other_phone=other.phone_number if other else "",
        blood_type=transfer.blood_type, units=transfer.units, note=transfer.note, status=transfer.status,
        created_at=transfer.created_at, updated_at=transfer.updated_at or transfer.created_at,
    )


@router.get("/suppliers", response_model=List[SupplierOut])
def hospitals_with_stock(
    blood_type: str, db: Session = Depends(get_db), me: Hospital = Depends(get_current_hospital),
):
    """Other hospitals that have this blood type in stock, closest first."""
    if blood_type not in BLOOD_TYPES:
        raise HTTPException(status_code=400, detail="Unknown blood type")
    rows = (
        db.query(BloodInventory)
        .filter(BloodInventory.blood_type == blood_type, BloodInventory.units_available > 0,
                BloodInventory.hospital_id != me.id).all()
    )
    result = []
    for row in rows:
        hospital = db.query(Hospital).filter(Hospital.id == row.hospital_id).first()
        if not hospital:
            continue
        result.append(SupplierOut(
            hospital_id=hospital.id, name=hospital.name, city=hospital.city, area=hospital.area,
            phone_number=hospital.phone_number, units_available=row.units_available,
            distance_kilometers=round(calculate_distance_kilometers(me.latitude, me.longitude, hospital.latitude, hospital.longitude), 1),
            is_verified=bool(hospital.is_verified),
        ))
    result.sort(key=lambda item: item.distance_kilometers)
    return result[:30]


@router.post("", response_model=TransferOut, status_code=201)
def ask_for_blood(payload: TransferIn, db: Session = Depends(get_db), me: Hospital = Depends(get_current_hospital)):
    if payload.blood_type not in BLOOD_TYPES:
        raise HTTPException(status_code=400, detail="Unknown blood type")
    if payload.from_hospital_id == me.id:
        raise HTTPException(status_code=400, detail="Choose a different hospital.")
    sender = db.query(Hospital).filter(Hospital.id == payload.from_hospital_id).first()
    if not sender:
        raise HTTPException(status_code=404, detail="Hospital not found")
    day_ago = datetime.utcnow() - timedelta(hours=24)
    if db.query(BloodTransfer).filter(BloodTransfer.to_hospital_id == me.id, BloodTransfer.created_at >= day_ago).count() >= 20:
        raise HTTPException(status_code=429, detail="Too many transfer requests today. Please try again tomorrow.")

    transfer = BloodTransfer(
        from_hospital_id=sender.id, to_hospital_id=me.id, blood_type=payload.blood_type,
        units=payload.units, note=payload.note, status="pending",
    )
    db.add(transfer)
    db.flush()
    notify(db, "hospital", sender.id, "Blood transfer request",
           f"{me.name} is asking for {payload.units} bag(s) of {payload.blood_type} from your blood bank."
           + (f" Note: {payload.note}" if payload.note else ""), category="inventory")
    db.commit()
    db.refresh(transfer)
    return _to_out(db, transfer, me)


@router.get("/mine", response_model=List[TransferOut])
def my_transfers(db: Session = Depends(get_db), me: Hospital = Depends(get_current_hospital)):
    rows = (
        db.query(BloodTransfer)
        .filter((BloodTransfer.from_hospital_id == me.id) | (BloodTransfer.to_hospital_id == me.id))
        .order_by(BloodTransfer.id.desc()).limit(200).all()
    )
    return [_to_out(db, t, me) for t in rows]


def _load(db: Session, transfer_id: int) -> BloodTransfer:
    transfer = db.query(BloodTransfer).filter(BloodTransfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")
    return transfer


class RespondIn(BaseModel):
    action: str  # "approve" | "reject"


@router.post("/{transfer_id}/respond", response_model=TransferOut)
def respond_to_transfer(
    transfer_id: int, payload: RespondIn, db: Session = Depends(get_db), me: Hospital = Depends(get_current_hospital),
):
    """The hospital that HAS the blood approves (stock leaves now) or rejects."""
    transfer = _load(db, transfer_id)
    if transfer.from_hospital_id != me.id:
        raise HTTPException(status_code=403, detail="This transfer is not addressed to your hospital")
    if transfer.status != "pending":
        raise HTTPException(status_code=400, detail="This transfer was already answered")

    if payload.action == "reject":
        transfer.status = "rejected"
        notify(db, "hospital", transfer.to_hospital_id, "Blood transfer rejected",
               f"{me.name} could not send {transfer.units} bag(s) of {transfer.blood_type}.", category="inventory")
    elif payload.action == "approve":
        row = (
            db.query(BloodInventory)
            .filter(BloodInventory.hospital_id == me.id, BloodInventory.blood_type == transfer.blood_type).first()
        )
        if not row or (row.units_available or 0) < transfer.units:
            raise HTTPException(status_code=400, detail="You do not have enough of this blood type in stock.")
        earliest = batch_service.remove_units(db, me.id, transfer.blood_type, transfer.units)
        transfer.earliest_expiry = earliest.isoformat() if earliest else None
        transfer.status = "approved"
        notify(db, "hospital", transfer.to_hospital_id, "Blood transfer approved",
               f"{me.name} approved {transfer.units} bag(s) of {transfer.blood_type}. "
               f"Please confirm in LifeFlow when the bags arrive. Contact: {me.phone_number}.", category="inventory")
    else:
        raise HTTPException(status_code=400, detail="Unknown action")
    db.commit()
    db.refresh(transfer)
    return _to_out(db, transfer, me)


@router.post("/{transfer_id}/receive", response_model=TransferOut)
def confirm_arrival(transfer_id: int, db: Session = Depends(get_db), me: Hospital = Depends(get_current_hospital)):
    """The asking hospital confirms the bags arrived: they join its stock (keeping the oldest expiry date)."""
    transfer = _load(db, transfer_id)
    if transfer.to_hospital_id != me.id:
        raise HTTPException(status_code=403, detail="This is not your transfer")
    if transfer.status != "approved":
        raise HTTPException(status_code=400, detail="This transfer is not waiting for arrival")
    today = datetime.utcnow().date()
    expires = date.fromisoformat(transfer.earliest_expiry) if transfer.earliest_expiry else today + timedelta(days=batch_service.SHELF_LIFE_DAYS)
    if expires < today:
        expires = today  # arrived on its last day; the next sweep will list it as expired
    batch_service.add_batch(db, me.id, transfer.blood_type, transfer.units, today, expires, source="transfer")
    transfer.status = "received"
    notify(db, "hospital", transfer.from_hospital_id, "Blood transfer received",
           f"{me.name} confirmed they received {transfer.units} bag(s) of {transfer.blood_type}. Thank you.", category="inventory")
    db.commit()
    db.refresh(transfer)
    return _to_out(db, transfer, me)


@router.post("/{transfer_id}/cancel", response_model=TransferOut)
def cancel_transfer(transfer_id: int, db: Session = Depends(get_db), me: Hospital = Depends(get_current_hospital)):
    transfer = _load(db, transfer_id)
    if transfer.to_hospital_id != me.id:
        raise HTTPException(status_code=403, detail="This is not your transfer")
    if transfer.status != "pending":
        raise HTTPException(status_code=400, detail="Only a waiting transfer can be cancelled")
    transfer.status = "cancelled"
    db.commit()
    db.refresh(transfer)
    return _to_out(db, transfer, me)
