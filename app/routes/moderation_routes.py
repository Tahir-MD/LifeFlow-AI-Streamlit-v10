"""
Admin tools: review blood requests the fake-request check held or flagged, and run the background
jobs by hand (donation reminders, expired-blood sweep).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import Admin
from app.models.request import BloodRequest
from app.routes.request_routes import build_request_out, release_held_request
from app.schemas.request_schema import BloodRequestOut
from app.services import batch_service
from app.services.audit_service import record_event
from app.services.reminder_service import send_due_reminders
from app.services.tracking_service import add_event
from app.utils.dependencies import get_current_admin
from app.utils.notify import notify

router = APIRouter(prefix="/moderation", tags=["Request review"])


class ReviewItem(BaseModel):
    request: BloodRequestOut
    fraud_score: int
    reasons: List[str]
    review_status: str


@router.get("/requests", response_model=List[ReviewItem])
def requests_to_review(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    """Held requests first, then flagged ones, newest first. Each shows WHY it was flagged."""
    rows = (
        db.query(BloodRequest)
        .filter(BloodRequest.review_status.in_(["held", "flagged"]))
        .order_by(BloodRequest.id.desc()).limit(200).all()
    )
    rows.sort(key=lambda r: 0 if r.review_status == "held" else 1)
    return [
        ReviewItem(request=build_request_out(db, r), fraud_score=r.fraud_score or 0,
                   reasons=[x for x in (r.fraud_flags or "").split("; ") if x], review_status=r.review_status)
        for r in rows
    ]


class DecisionIn(BaseModel):
    note: Optional[str] = None


def _load(db: Session, request_id: int) -> BloodRequest:
    blood_request = db.query(BloodRequest).filter(BloodRequest.id == request_id).first()
    if not blood_request:
        raise HTTPException(status_code=404, detail="Request not found")
    return blood_request


@router.post("/requests/{request_id}/approve", response_model=BloodRequestOut)
def approve_request(request_id: int, db: Session = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    blood_request = _load(db, request_id)
    if blood_request.status == "held":
        release_held_request(db, blood_request)  # runs the stock check and alerts donors now
    else:
        blood_request.review_status = "approved"  # a flagged request that already went out: just clear the flag
        db.commit()
    record_event(db, "request_review_approved", actor_type="admin", actor_id=admin.id, payload={"request_id": request_id})
    db.refresh(blood_request)
    return build_request_out(db, blood_request)


@router.post("/requests/{request_id}/reject", response_model=BloodRequestOut)
def reject_request(request_id: int, payload: DecisionIn, db: Session = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    blood_request = _load(db, request_id)
    if blood_request.status in ("held", "open"):
        blood_request.status = "rejected"
    blood_request.review_status = "rejected"
    add_event(db, blood_request.id, "rejected", "The request was not approved by the LifeFlow reviewer.")
    notify(db, blood_request.requester_type, blood_request.requester_id, "Your request was not approved",
           "A LifeFlow reviewer could not approve this request. If it is real, please contact the hospital directly "
           "or send a new request with the patient's details." + (f" Note: {payload.note}" if payload.note else ""),
           category="request", related_request_id=blood_request.id)
    db.commit()
    record_event(db, "request_review_rejected", actor_type="admin", actor_id=admin.id, payload={"request_id": request_id})
    db.refresh(blood_request)
    return build_request_out(db, blood_request)


@router.post("/jobs/reminders")
def run_reminders(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    return {"reminders_sent": send_due_reminders(db)}


@router.post("/jobs/expiry-sweep")
def run_expiry_sweep(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    return batch_service.sweep_expired(db)
