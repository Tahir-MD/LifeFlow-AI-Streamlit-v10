from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.models.request import BloodRequest
from app.schemas.request_schema import BloodRequestCreate, BloodRequestOut
from app.utils.dependencies import get_current_hospital, get_current_receiver
from app.utils.notify import notify
from app.services.matching_service import find_matching_donors, find_hospitals_with_stock
from app.services.audit_service import record_event
from app.services import batch_service
from app.services.fraud_service import score_request, decide
from app.services.tracking_service import add_event
from app.utils.distance import calculate_distance_kilometers

router = APIRouter(prefix="/requests", tags=["Blood Requests"])


def _try_fulfill_from_hospital_stock(db: Session, blood_request: BloodRequest, requester_name: str) -> None:
    """
    Before a single donor is ever contacted, every new request is checked
    against hospital blood-bank inventory. A hospital's own shelf is
    checked first, then the stock of other nearby hospitals. Whatever can
    be covered from existing stock is deducted immediately; only a
    genuine shortfall is ever broadcast to donors.
    """
    still_needed = blood_request.units_needed - blood_request.units_fulfilled
    if still_needed <= 0:
        return

    prefer_hospital_id = blood_request.requester_id if blood_request.requester_type == "hospital" else None
    candidates = find_hospitals_with_stock(db, blood_request, prefer_hospital_id=prefer_hospital_id)

    for distance, hospital, inventory_row in candidates:
        if still_needed <= 0:
            break
        take = min(inventory_row.units_available, still_needed)
        if take <= 0:
            continue

        inventory_row.units_available -= take
        batch_service.consume(db, hospital.id, blood_request.blood_type_needed, take)  # oldest bags first
        blood_request.units_fulfilled += take
        blood_request.inventory_units_used = (blood_request.inventory_units_used or 0) + take
        blood_request.fulfilled_from_inventory = True
        if blood_request.fulfilling_hospital_id is None:
            blood_request.fulfilling_hospital_id = hospital.id
        still_needed -= take

        is_own_stock = hospital.id == blood_request.requester_id and blood_request.requester_type == "hospital"
        notify(
            db, "hospital", hospital.id,
            "Blood issued from your inventory" if is_own_stock else "Your stock helped another request",
            f"{take} bag(s) of {blood_request.blood_type_needed} were allocated from your blood bank "
            f"to cover {requester_name}'s request." if not is_own_stock else
            f"{take} bag(s) of {blood_request.blood_type_needed} were used from your own stock for this request, "
            f"before any donor was contacted.",
            category="inventory",
            related_request_id=blood_request.id,
        )
        record_event(
            db, "inventory_used_for_request", actor_type="hospital", actor_id=hospital.id,
            payload={"request_id": blood_request.id, "blood_type": blood_request.blood_type_needed, "units": take},
        )

    if blood_request.units_fulfilled >= blood_request.units_needed:
        blood_request.status = "fulfilled"

    if blood_request.inventory_units_used:
        add_event(db, blood_request.id, "stock_checked",
                  f"{blood_request.inventory_units_used} bag(s) were taken from hospital blood-bank stock.")
    else:
        add_event(db, blood_request.id, "stock_checked", "Hospital blood banks were checked. No matching stock was available.")
    if blood_request.status == "fulfilled":
        add_event(db, blood_request.id, "fulfilled", "The request is fully covered.")

    if blood_request.inventory_units_used:
        remaining = blood_request.units_needed - blood_request.units_fulfilled
        summary = (
            f"Good news — {blood_request.inventory_units_used} bag(s) of {blood_request.blood_type_needed} "
            f"were available immediately from hospital blood-bank stock."
        )
        if remaining > 0:
            summary += f" We are now contacting donors for the remaining {remaining} bag(s)."
        else:
            summary += " Your request is fully covered, no donor is needed."
        notify(
            db, blood_request.requester_type, blood_request.requester_id,
            "Hospital stock checked for your request", summary,
            category="request", related_request_id=blood_request.id,
        )

    db.commit()


def build_request_out(db: Session, blood_request: BloodRequest) -> BloodRequestOut:
    """
    Fills in who is asking. A hospital request shows the hospital name
    and phone number. A receiver request additionally shows the CNIC
    number and address of the person asking, since they are an
    individual rather than a licensed institution.
    """
    requester_cnic = None
    requester_address = None

    if blood_request.requester_type == "hospital":
        hospital = db.query(Hospital).filter(Hospital.id == blood_request.requester_id).first()
        requester_name = hospital.name if hospital else "Unknown hospital"
        requester_phone = hospital.phone_number if hospital else ""
    else:
        receiver = db.query(Receiver).filter(Receiver.id == blood_request.requester_id).first()
        requester_name = receiver.full_name if receiver else "Unknown receiver"
        requester_phone = receiver.phone_number if receiver else ""
        requester_cnic = receiver.cnic_number if receiver else None
        requester_address = receiver.address if receiver else None  # already holds house + village + area + city

    fulfilling_hospital_name = None
    if blood_request.fulfilling_hospital_id:
        fulfilling_hospital = db.query(Hospital).filter(Hospital.id == blood_request.fulfilling_hospital_id).first()
        fulfilling_hospital_name = fulfilling_hospital.name if fulfilling_hospital else None

    return BloodRequestOut(
        id=blood_request.id,
        requester_type=blood_request.requester_type,
        requester_id=blood_request.requester_id,
        requester_name=requester_name,
        requester_phone=requester_phone,
        requester_cnic=requester_cnic,
        requester_address=requester_address,
        blood_type_needed=blood_request.blood_type_needed,
        units_needed=blood_request.units_needed,
        units_fulfilled=blood_request.units_fulfilled,
        units_remaining=max(blood_request.units_needed - blood_request.units_fulfilled, 0),
        patient_name=blood_request.patient_name,
        patient_age=blood_request.patient_age,
        patient_gender=blood_request.patient_gender,
        medical_reason=blood_request.medical_reason,
        urgency_type=blood_request.urgency_type,
        urgency_value=blood_request.urgency_value,
        latitude=blood_request.latitude,
        longitude=blood_request.longitude,
        status=blood_request.status,
        created_at=blood_request.created_at,
        fulfilled_from_inventory=blood_request.fulfilled_from_inventory,
        inventory_units_used=blood_request.inventory_units_used or 0,
        fulfilling_hospital_name=fulfilling_hospital_name,
        review_status=blood_request.review_status or "ok",
        is_sos=bool(blood_request.is_sos),
    )


def _notify_matching_donors(db, blood_request: BloodRequest, requester_name: str, max_km: float = None) -> int:
    """Tells every compatible nearby donor about the shortfall left after checking hospital stock."""
    units_remaining = blood_request.units_needed - blood_request.units_fulfilled
    if units_remaining <= 0:
        return 0
    urgency_label = "an emergency" if blood_request.urgency_type == "emergency" else "a scheduled"
    matches = find_matching_donors(db, blood_request, max_km) if max_km else find_matching_donors(db, blood_request)
    title = "SOS emergency blood alert" if blood_request.is_sos else "New compatible blood request nearby"
    try:   # donors most likely to answer quickly are alerted first
        from app.services.v6_service import rank_by_response
        order = {row["donor_id"]: i for i, row in enumerate(rank_by_response(db, blood_request, matches))}
        matches = sorted(matches, key=lambda m: order.get(m.donor_id, len(order)))
    except Exception:  # noqa: BLE001 -- ranking is a bonus; the alert must always go out
        pass
    for match in matches:
        notify(
            db, "donor", match.donor_id,
            title,
            f"{requester_name} needs {units_remaining} bag(s) of {blood_request.blood_type_needed} "
            f"({urgency_label} request), about {match.distance_kilometers} km away.",
            category="request",
            related_request_id=blood_request.id,
        )
    add_event(
        db, blood_request.id, "donors_alerted",
        f"{len(matches)} matching donor(s) nearby were alerted." if matches
        else "No matching donor was found nearby yet. We will keep the request open.",
    )
    db.commit()
    return len(matches)


def _requester_name(account, requester_type: str) -> str:
    return account.name if requester_type == "hospital" else account.full_name


def create_request_for(db: Session, requester_type: str, account, request_data: BloodRequestCreate,
                       is_sos: bool = False) -> BloodRequest:
    """
    Shared by hospital requests, patient requests and the SOS button.
    1) score the request for fake / misuse signs  2) hold it for admin review if it looks fake
    3) otherwise check hospital stock first, then alert only the donors still needed.
    """
    now = datetime.utcnow()
    since = now - timedelta(hours=24)
    mine = db.query(BloodRequest).filter(
        BloodRequest.requester_type == requester_type, BloodRequest.requester_id == account.id,
    )
    patient_name = request_data.patient_name or (getattr(account, "patient_name", None) if requester_type == "receiver" else None)

    duplicate_open = False
    if patient_name:
        duplicate_open = db.query(BloodRequest).filter(
            func.lower(BloodRequest.patient_name) == patient_name.lower(),
            BloodRequest.blood_type_needed == request_data.blood_type_needed,
            BloodRequest.status.in_(["open", "held"]),
            BloodRequest.created_at >= now - timedelta(hours=48),
        ).first() is not None

    same_cnic = 0
    if requester_type == "receiver" and getattr(account, "cnic_number", None):
        same_cnic = db.query(Receiver).filter(Receiver.cnic_number == account.cnic_number).count()

    created_at = getattr(account, "created_at", None)
    facts = {
        "requests_last_24h": mine.filter(BloodRequest.created_at >= since).count(),
        "sos_last_24h": mine.filter(BloodRequest.created_at >= since, BloodRequest.is_sos == True).count(),  # noqa: E712
        "duplicate_open": duplicate_open,
        "units_needed": request_data.units_needed,
        "account_age_minutes": ((now - created_at).total_seconds() / 60) if created_at else None,
        "is_emergency": request_data.urgency_type == "emergency",
        "distance_from_home_km": calculate_distance_kilometers(
            request_data.latitude, request_data.longitude, account.latitude, account.longitude),
        "medical_reason": request_data.medical_reason,
        "patient_name": patient_name,
        "requester_type": requester_type,
        "hospital_verified": bool(getattr(account, "is_verified", False)) if requester_type == "hospital" else False,
        "same_cnic_accounts": same_cnic,
    }
    score, reasons = score_request(facts)
    verdict = decide(score, is_sos=is_sos)

    new_request = BloodRequest(
        requester_type=requester_type,
        requester_id=account.id,
        blood_type_needed=request_data.blood_type_needed,
        units_needed=request_data.units_needed,
        patient_name=patient_name,
        patient_age=request_data.patient_age,
        patient_gender=request_data.patient_gender,
        medical_reason=request_data.medical_reason,
        urgency_type=request_data.urgency_type,
        urgency_value=request_data.urgency_value,
        latitude=request_data.latitude,
        longitude=request_data.longitude,
        status="held" if verdict == "held" else "open",
        review_status=verdict,
        fraud_score=score,
        fraud_flags="; ".join(reasons) if reasons else None,
        is_sos=is_sos,
    )
    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    add_event(db, new_request.id, "created",
              "SOS emergency alert sent." if is_sos else "Request created.", requester_type, account.id)
    record_event(
        db, "request_created", actor_type=requester_type, actor_id=account.id,
        payload={"request_id": new_request.id, "blood_type": new_request.blood_type_needed,
                 "units_needed": new_request.units_needed, "review": verdict, "score": score, "sos": is_sos},
    )

    name = _requester_name(account, requester_type)
    if verdict == "held":
        add_event(db, new_request.id, "held", "A LifeFlow reviewer is checking this request before donors are alerted.")
        notify(db, requester_type, account.id, "Your request is being checked",
               "For safety, a LifeFlow reviewer is quickly checking your request before donors are alerted. "
               "If this is a real emergency, please call the hospital directly as well.",
               category="request", related_request_id=new_request.id)
        db.commit()
        return new_request

    # Step 1: always check hospital blood-bank stock (this hospital first, then others nearby).
    _try_fulfill_from_hospital_stock(db, new_request, name)
    # Step 2: only the remaining shortfall, if any, goes out to donors (SOS reaches further).
    _notify_matching_donors(db, new_request, name, max_km=100 if is_sos else None)
    return new_request


def release_held_request(db: Session, blood_request: BloodRequest) -> None:
    """An admin approved a held request: now it goes through the normal stock check and donor alerts."""
    if blood_request.requester_type == "hospital":
        account = db.query(Hospital).filter(Hospital.id == blood_request.requester_id).first()
    else:
        account = db.query(Receiver).filter(Receiver.id == blood_request.requester_id).first()
    name = _requester_name(account, blood_request.requester_type) if account else "A requester"
    blood_request.status = "open"
    blood_request.review_status = "approved"
    add_event(db, blood_request.id, "approved", "The request was checked and approved.")
    db.commit()
    _try_fulfill_from_hospital_stock(db, blood_request, name)
    _notify_matching_donors(db, blood_request, name, max_km=100 if blood_request.is_sos else None)


@router.post("/hospital", response_model=BloodRequestOut, status_code=201)
def create_hospital_request(
    request_data: BloodRequestCreate,
    db: Session = Depends(get_db),
    current_hospital: Hospital = Depends(get_current_hospital),
):
    new_request = create_request_for(db, "hospital", current_hospital, request_data)
    return build_request_out(db, new_request)


@router.post("/receiver", response_model=BloodRequestOut, status_code=201)
def create_receiver_request(
    request_data: BloodRequestCreate,
    db: Session = Depends(get_db),
    current_receiver: Receiver = Depends(get_current_receiver),
):
    new_request = create_request_for(db, "receiver", current_receiver, request_data)
    return build_request_out(db, new_request)


@router.get("", response_model=list[BloodRequestOut])
def list_blood_requests(db: Session = Depends(get_db)):
    requests = (
        db.query(BloodRequest)
        .filter(BloodRequest.status.notin_(["held", "rejected"]))  # requests waiting for review stay private
        .order_by(BloodRequest.created_at.desc())
        .all()
    )
    return [build_request_out(db, item) for item in requests]


@router.get("/hospital/history", response_model=list[BloodRequestOut])
def hospital_request_history(
    db: Session = Depends(get_db),
    current_hospital: Hospital = Depends(get_current_hospital),
):
    """
    Every request this hospital has ever sent -- open, closed, or
    still waiting for a donor -- not just the ones a donor has
    fulfilled. This is the hospital's full request history, and it
    stays the same across logins because it is read straight from the
    database by this hospital's id.
    """
    requests = (
        db.query(BloodRequest)
        .filter(BloodRequest.requester_type == "hospital", BloodRequest.requester_id == current_hospital.id)
        .order_by(BloodRequest.created_at.desc())
        .all()
    )
    return [build_request_out(db, item) for item in requests]


@router.get("/receiver/history", response_model=list[BloodRequestOut])
def receiver_request_history(
    db: Session = Depends(get_db),
    current_receiver: Receiver = Depends(get_current_receiver),
):
    """Every request this patient has ever sent -- open, closed, or still waiting."""
    requests = (
        db.query(BloodRequest)
        .filter(BloodRequest.requester_type == "receiver", BloodRequest.requester_id == current_receiver.id)
        .order_by(BloodRequest.created_at.desc())
        .all()
    )
    return [build_request_out(db, item) for item in requests]


@router.get("/{request_id}", response_model=BloodRequestOut)
def get_blood_request(request_id: int, db: Session = Depends(get_db)):
    blood_request = db.query(BloodRequest).filter(BloodRequest.id == request_id).first()
    if not blood_request:
        raise HTTPException(status_code=404, detail="Request not found")
    return build_request_out(db, blood_request)
