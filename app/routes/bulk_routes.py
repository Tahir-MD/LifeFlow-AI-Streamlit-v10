"""
Bulk messages to donors by blood group and area (hospitals and the admin).

A hospital picks blood groups, a city and optionally an area, writes a short message, and sends it
as an app notification, SMS or WhatsApp. Only donors who are medically allowed to donate and who
are not paused receive it. Phone numbers are never shown to the sender. Limits: 500 donors per
message and 3 bulk messages per hospital per day, so the feature cannot be used for spam.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import Admin
from app.models.audit_log import AuditLog
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.services.audit_service import record_event
from app.services.delivery_service import is_sms_configured, is_whatsapp_configured, send_sms, send_whatsapp
from app.services.eligibility_service import min_gap_days
from app.utils.dependencies import get_current_any_account
from app.utils.notify import notify

router = APIRouter(prefix="/bulk", tags=["Bulk messages"])

BLOOD_TYPES = {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"}
MAX_RECIPIENTS = 500
MAX_PER_DAY_HOSPITAL = 3


class BulkFilter(BaseModel):
    blood_types: List[str] = []   # empty = every blood group
    city: Optional[str] = None
    area: Optional[str] = None
    only_ready_now: bool = True   # only donors who can donate today

    @field_validator("blood_types")
    @classmethod
    def _types(cls, v):
        bad = [b for b in v if b not in BLOOD_TYPES]
        if bad:
            raise ValueError("Unknown blood type.")
        return v

    @field_validator("city", "area")
    @classmethod
    def _text(cls, v):
        v = " ".join((v or "").split())
        return v[:80] if v else None


class BulkSendIn(BulkFilter):
    message: str
    channel: str = "app"   # "app" | "sms" | "whatsapp"

    @field_validator("message")
    @classmethod
    def _message(cls, v):
        v = " ".join((v or "").split())
        if len(v) < 5:
            raise ValueError("Write a message of at least 5 letters.")
        if len(v) > 300:
            raise ValueError("The message can have at most 300 letters.")
        return v

    @field_validator("channel")
    @classmethod
    def _channel(cls, v):
        if v not in ("app", "sms", "whatsapp"):
            raise ValueError("Choose app, sms or whatsapp.")
        return v


def _sender(db: Session, who):
    role, account_id = who
    if role == "hospital":
        account = db.query(Hospital).filter(Hospital.id == account_id).first()
        return role, account, account.name if account else None
    if role == "admin":
        account = db.query(Admin).filter(Admin.id == account_id).first()
        return role, account, "LifeFlow"
    raise HTTPException(status_code=403, detail="Only hospitals and the admin can send bulk messages")


def _recipients(db: Session, f: BulkFilter) -> List[Donor]:
    query = db.query(Donor)
    if f.blood_types:
        query = query.filter(Donor.blood_type.in_(f.blood_types))
    donors = query.all()
    now = datetime.utcnow()
    result = []
    for donor in donors:
        if f.city and f.city.lower() not in (donor.city or "").lower():
            continue
        if f.area and f.area.lower() not in (donor.area or "").lower():
            continue
        if donor.is_eligible is False and not donor.deferred_until:
            continue                      # cannot donate for medical reasons
        if f.only_ready_now:
            if donor.deferred_until and donor.deferred_until > now:
                continue
            if donor.last_donation_date and donor.last_donation_date + timedelta(days=min_gap_days(donor.gender)) > now:
                continue
        result.append(donor)
    return result


@router.post("/preview")
def preview(f: BulkFilter, db: Session = Depends(get_db), who=Depends(get_current_any_account)):
    """How many donors would get the message. No names or numbers are shown."""
    _sender(db, who)
    donors = _recipients(db, f)
    by_type = {}
    for donor in donors:
        by_type[donor.blood_type] = by_type.get(donor.blood_type, 0) + 1
    return {"count": len(donors), "by_blood_type": by_type, "limit": MAX_RECIPIENTS}


@router.post("/send")
def send(payload: BulkSendIn, db: Session = Depends(get_db), who=Depends(get_current_any_account)):
    role, account, sender_name = _sender(db, who)
    if role == "hospital":
        since = datetime.utcnow() - timedelta(hours=24)
        sent_today = db.query(AuditLog).filter(
            AuditLog.event_type == "bulk_message_sent", AuditLog.actor_type == "hospital",
            AuditLog.actor_id == account.id, AuditLog.created_at >= since,
        ).count()
        if sent_today >= MAX_PER_DAY_HOSPITAL:
            raise HTTPException(status_code=429, detail=f"You can send {MAX_PER_DAY_HOSPITAL} bulk messages per day.")

    donors = _recipients(db, payload)
    if not donors:
        raise HTTPException(status_code=400, detail="No donors match these choices.")
    if len(donors) > MAX_RECIPIENTS:
        raise HTTPException(status_code=400, detail=f"This would reach {len(donors)} donors. The limit is {MAX_RECIPIENTS}. Choose a smaller area.")
    if payload.channel == "sms" and not is_sms_configured():
        raise HTTPException(status_code=400, detail="SMS is not set up on this server yet. Choose app notification.")
    if payload.channel == "whatsapp" and not is_whatsapp_configured():
        raise HTTPException(status_code=400, detail="WhatsApp is not set up on this server yet. Choose app notification.")

    title = f"Message from {sender_name}"
    delivered = 0
    for donor in donors:
        # In-app notification always; the chosen channel is sent once, here, not again by notify().
        notify(db, "donor", donor.id, title, payload.message, category="system", external=False)
        text = f"LifeFlow - {title}: {payload.message}"
        if payload.channel == "sms" and send_sms(donor.phone_number, text):
            delivered += 1
        elif payload.channel == "whatsapp" and send_whatsapp(donor.phone_number, text):
            delivered += 1
    db.commit()
    record_event(db, "bulk_message_sent", actor_type=role, actor_id=account.id,
                 payload={"recipients": len(donors), "channel": payload.channel, "blood_types": payload.blood_types,
                          "city": payload.city, "area": payload.area})
    return {"recipients": len(donors), "channel": payload.channel,
            "delivered_outside_app": delivered if payload.channel != "app" else 0}
