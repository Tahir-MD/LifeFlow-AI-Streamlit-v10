"""
Live request tracking: a timeline of what has happened to a blood request, and the donor's
"on the way" / "arrived" updates.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.donation import Donation
from app.models.request import BloodRequest
from app.models.request_event import RequestEvent
from app.models.donor import Donor
from app.services.tracking_service import add_event
from app.utils.dependencies import get_current_any_account, get_current_donor
from app.utils.notify import notify

router = APIRouter(prefix="/tracking", tags=["Request tracking"])

# The order of steps shown on screen. Steps that did not happen yet are shown as "waiting".
STEPS = ["created", "stock_checked", "donors_alerted", "donor_accepted", "donor_on_the_way", "donor_arrived", "fulfilled"]


class EventOut(BaseModel):
    kind: str
    message: str
    created_at: str


class TrackingOut(BaseModel):
    request_id: int
    status: str
    review_status: str
    units_needed: int
    units_fulfilled: int
    steps: List[str]
    done_steps: List[str]
    events: List[EventOut]


def _can_view(db: Session, role: str, account_id: int, blood_request: BloodRequest) -> bool:
    if role == "admin":
        return True
    if role in ("hospital", "receiver"):
        return blood_request.requester_type == role and blood_request.requester_id == account_id
    if role == "donor":
        return db.query(Donation).filter(Donation.donor_id == account_id, Donation.request_id == blood_request.id).first() is not None
    return False


@router.get("/{request_id}", response_model=TrackingOut)
def request_timeline(request_id: int, db: Session = Depends(get_db), who=Depends(get_current_any_account)):
    role, account_id = who
    blood_request = db.query(BloodRequest).filter(BloodRequest.id == request_id).first()
    if not blood_request:
        raise HTTPException(status_code=404, detail="Request not found")
    if not _can_view(db, role, account_id, blood_request):
        raise HTTPException(status_code=403, detail="This is not your request")
    events = db.query(RequestEvent).filter(RequestEvent.request_id == request_id).order_by(RequestEvent.id.asc()).all()
    kinds = {e.kind for e in events}
    return TrackingOut(
        request_id=blood_request.id,
        status=blood_request.status,
        review_status=blood_request.review_status or "ok",
        units_needed=blood_request.units_needed,
        units_fulfilled=blood_request.units_fulfilled,
        steps=STEPS,
        done_steps=[step for step in STEPS if step in kinds],
        events=[EventOut(kind=e.kind, message=e.message, created_at=e.created_at.isoformat()) for e in events],
    )


class DonorStatusIn(BaseModel):
    status: str  # "on_the_way" | "arrived"


@router.post("/{request_id}/donor-status")
def donor_update_status(
    request_id: int,
    payload: DonorStatusIn,
    db: Session = Depends(get_db),
    current_donor: Donor = Depends(get_current_donor),
):
    """After accepting, the donor can tell the requester "I am on the way" and later "I have arrived"."""
    if payload.status not in ("on_the_way", "arrived"):
        raise HTTPException(status_code=400, detail="Unknown status")
    donation = db.query(Donation).filter(Donation.donor_id == current_donor.id, Donation.request_id == request_id).first()
    blood_request = db.query(BloodRequest).filter(BloodRequest.id == request_id).first()
    if not donation or not blood_request:
        raise HTTPException(status_code=403, detail="You have not accepted this request")

    first_name = current_donor.full_name.split()[0]
    if payload.status == "on_the_way":
        kind, message = "donor_on_the_way", f"{first_name} is on the way."
    else:
        kind, message = "donor_arrived", f"{first_name} has arrived."
    already = db.query(RequestEvent).filter(
        RequestEvent.request_id == request_id, RequestEvent.kind == kind, RequestEvent.actor_id == current_donor.id,
    ).first()
    if not already:
        add_event(db, request_id, kind, message, "donor", current_donor.id)
        notify(db, blood_request.requester_type, blood_request.requester_id, "Donor update", message,
               category="donation", related_request_id=request_id)
    db.commit()
    return {"message": message}
