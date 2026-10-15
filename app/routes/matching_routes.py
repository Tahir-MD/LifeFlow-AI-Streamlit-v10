from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.models.request import BloodRequest
from app.models.donation import Donation
from app.schemas.request_schema import MatchedDonorOut, AcceptRequestInput
from app.services.matching_service import find_matching_donors
from app.utils.dependencies import get_current_donor
from app.utils.notify import notify
from app.services.audit_service import record_event
from app.services.eligibility_service import min_gap_days
from app.services.tracking_service import add_event
from app.services.referral_service import reward_first_donation

POINTS_PER_UNIT = 10

router = APIRouter(prefix="/matching", tags=["Matching"])


@router.get("/{request_id}", response_model=list[MatchedDonorOut])
def get_matches_for_request(request_id: int, db: Session = Depends(get_db)):
    blood_request = db.query(BloodRequest).filter(BloodRequest.id == request_id).first()
    if not blood_request:
        raise HTTPException(status_code=404, detail="Request not found")

    return find_matching_donors(db, blood_request)


@router.post("/{request_id}/accept")
def accept_blood_request(
    request_id: int,
    accept_data: AcceptRequestInput,
    db: Session = Depends(get_db),
    current_donor: Donor = Depends(get_current_donor),
):
    blood_request = db.query(BloodRequest).filter(BloodRequest.id == request_id).first()
    if not blood_request:
        raise HTTPException(status_code=404, detail="Request not found")

    if blood_request.status != "open":
        raise HTTPException(status_code=400, detail="This request is no longer open")

    units_remaining = blood_request.units_needed - blood_request.units_fulfilled
    if units_remaining <= 0:
        raise HTTPException(status_code=400, detail="This request has already been fully covered")

    # A donor who is not medically able to give blood right now cannot accept.
    now = datetime.utcnow()
    if current_donor.is_eligible is False and not current_donor.deferred_until:
        raise HTTPException(status_code=400, detail="Your health check says you cannot donate blood. Please speak to a doctor.")
    if current_donor.deferred_until and current_donor.deferred_until > now:
        raise HTTPException(status_code=400, detail=f"You can donate again after {current_donor.deferred_until.date().isoformat()}.")
    if current_donor.last_donation_date:
        next_ok = current_donor.last_donation_date + timedelta(days=min_gap_days(current_donor.gender))
        if next_ok > now:
            raise HTTPException(status_code=400, detail=f"You can donate again after {next_ok.date().isoformat()}.")

    units_donated = accept_data.units_donated
    if units_donated < 1:
        raise HTTPException(status_code=400, detail="You must donate at least one bag")
    if units_donated > units_remaining:
        units_donated = units_remaining

    new_donation = Donation(
        donor_id=current_donor.id,
        request_id=blood_request.id,
        units_donated=units_donated,
    )
    db.add(new_donation)

    current_donor.last_donation_date = datetime.utcnow()
    current_donor.points = current_donor.points + (POINTS_PER_UNIT * units_donated)
    reward_first_donation(db, current_donor)   # invite-a-friend bonus (paid once)

    blood_request.units_fulfilled = blood_request.units_fulfilled + units_donated
    remaining_after = blood_request.units_needed - blood_request.units_fulfilled
    if remaining_after <= 0:
        blood_request.status = "fulfilled"

    first_name = current_donor.full_name.split()[0]
    add_event(db, blood_request.id, "donor_accepted",
              f"{first_name} ({current_donor.blood_type}) accepted and will donate {units_donated} bag(s).",
              "donor", current_donor.id)
    if remaining_after <= 0:
        add_event(db, blood_request.id, "fulfilled", "The request is fully covered.")
    db.commit()

    record_event(
        db, "donation_completed", actor_type="donor", actor_id=current_donor.id,
        payload={
            "donation_id": new_donation.id, "request_id": blood_request.id,
            "units_donated": units_donated, "blood_type": current_donor.blood_type,
            "requester_type": blood_request.requester_type, "requester_id": blood_request.requester_id,
        },
    )

    if blood_request.requester_type == "hospital":
        requester = db.query(Hospital).filter(Hospital.id == blood_request.requester_id).first()
        requester_name = requester.name if requester else "Unknown hospital"
        requester_phone = requester.phone_number if requester else ""
    else:
        requester = db.query(Receiver).filter(Receiver.id == blood_request.requester_id).first()
        requester_name = requester.full_name if requester else "Unknown receiver"
        requester_phone = requester.phone_number if requester else ""

    notify(
        db, blood_request.requester_type, blood_request.requester_id,
        "A donor accepted your request",
        f"{current_donor.full_name} ({current_donor.blood_type}) is donating {units_donated} bag(s). "
        f"Their contact number is {current_donor.phone_number}.",
        category="donation",
        related_request_id=blood_request.id,
    )
    db.commit()

    return {
        "message": f"Thank you. You are donating {units_donated} bag{'s' if units_donated != 1 else ''}.",
        "donor_points": current_donor.points,
        "units_donated": units_donated,
        "units_remaining": max(remaining_after, 0),
        "request_status": blood_request.status,
        "requester_type": blood_request.requester_type,
        "requester_name": requester_name,
        "requester_phone": requester_phone,
        "patient_name": blood_request.patient_name,
    }
