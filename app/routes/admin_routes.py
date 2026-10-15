from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import Admin
from app.schemas.admin_schema import AdminOut, AdminChangeCredentials
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.models.request import BloodRequest
from app.models.donation import Donation
from app.models.notification import Notification
from app.models.staff import Staff
from app.models.visitor_log import VisitorEntry
from app.schemas.donor_schema import DonorOut
from app.schemas.hospital_schema import HospitalOut
from app.schemas.receiver_schema import ReceiverOut
from app.schemas.request_schema import BloodRequestOut
from app.schemas.donation_schema import DonationHistoryOut
from app.schemas.notification_schema import NotificationOut
from app.schemas.staff_schema import StaffOut
from app.schemas.visitor_schema import VisitorEntryOut
from app.utils.dependencies import get_current_admin
from app.utils.security import hash_password, verify_password
from app.services.history_service import build_history_entry
from app.services.audit_service import record_event, verify_chain
from app.routes.request_routes import build_request_out
from datetime import datetime

router = APIRouter(prefix="/admin", tags=["Admin"])


# --- The admin's own account ------------------------------------------------

@router.get("/me", response_model=AdminOut)
def my_admin_profile(current_admin: Admin = Depends(get_current_admin)):
    """Used right after login to decide whether to force the credentials-change page."""
    return current_admin


@router.post("/change-credentials", response_model=AdminOut)
def change_admin_credentials(
    payload: AdminChangeCredentials,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    """
    Required before a freshly-seeded admin account can do anything else.
    Verifies the current password, then sets a new username (email) and
    password, and clears must_change_password so the dashboard unlocks.
    """
    if not verify_password(payload.current_password, current_admin.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if payload.new_email != current_admin.email:
        existing = db.query(Admin).filter(Admin.email == payload.new_email).first()
        if existing:
            raise HTTPException(status_code=400, detail="That email is already in use")

    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    current_admin.email = payload.new_email
    if payload.new_full_name:
        current_admin.full_name = payload.new_full_name
    current_admin.hashed_password = hash_password(payload.new_password)
    current_admin.must_change_password = False
    db.commit()
    db.refresh(current_admin)
    return current_admin


# --- Everyone on the platform ---------------------------------------------

@router.get("/donors", response_model=List[DonorOut])
def all_donors(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    return db.query(Donor).order_by(Donor.created_at.desc()).all()


@router.get("/hospitals", response_model=List[HospitalOut])
def all_hospitals(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    return db.query(Hospital).order_by(Hospital.created_at.desc()).all()


@router.get("/receivers", response_model=List[ReceiverOut])
def all_receivers(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    return db.query(Receiver).order_by(Receiver.created_at.desc()).all()


# --- Full history across every user, of every kind -------------------------

@router.get("/requests", response_model=List[BloodRequestOut])
def all_requests(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    """Every blood request ever made, by every hospital and patient, any status."""
    requests = db.query(BloodRequest).order_by(BloodRequest.created_at.desc()).all()
    return [build_request_out(db, item) for item in requests]


@router.get("/donations", response_model=List[DonationHistoryOut])
def all_donations(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    """Every completed donation on the platform, from every donor to every hospital/patient."""
    donations = db.query(Donation).order_by(Donation.donated_at.desc()).all()
    results = []
    for donation in donations:
        blood_request = db.query(BloodRequest).filter(BloodRequest.id == donation.request_id).first()
        if not blood_request:
            continue
        entry = build_history_entry(db, donation, blood_request)
        if entry:
            results.append(entry)
    return results


@router.get("/notifications", response_model=List[NotificationOut])
def all_notifications(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    """Every donor request / message notification sent to anyone, full history."""
    return db.query(Notification).order_by(Notification.created_at.desc()).limit(500).all()


# --- One specific user's own history, as seen from the admin side ---------

@router.get("/donor/{donor_id}/history", response_model=List[DonationHistoryOut])
def donor_history(donor_id: int, db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    donor = db.query(Donor).filter(Donor.id == donor_id).first()
    if not donor:
        raise HTTPException(status_code=404, detail="Donor not found")
    donations = (
        db.query(Donation)
        .filter(Donation.donor_id == donor_id)
        .order_by(Donation.donated_at.desc())
        .all()
    )
    results = []
    for donation in donations:
        blood_request = db.query(BloodRequest).filter(BloodRequest.id == donation.request_id).first()
        if not blood_request:
            continue
        entry = build_history_entry(db, donation, blood_request)
        if entry:
            results.append(entry)
    return results


@router.get("/hospital/{hospital_id}/history", response_model=List[BloodRequestOut])
def hospital_history(hospital_id: int, db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    requests = (
        db.query(BloodRequest)
        .filter(BloodRequest.requester_type == "hospital", BloodRequest.requester_id == hospital_id)
        .order_by(BloodRequest.created_at.desc())
        .all()
    )
    return [build_request_out(db, item) for item in requests]


@router.get("/receiver/{receiver_id}/history", response_model=List[BloodRequestOut])
def receiver_history(receiver_id: int, db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    receiver = db.query(Receiver).filter(Receiver.id == receiver_id).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")
    requests = (
        db.query(BloodRequest)
        .filter(BloodRequest.requester_type == "receiver", BloodRequest.requester_id == receiver_id)
        .order_by(BloodRequest.created_at.desc())
        .all()
    )
    return [build_request_out(db, item) for item in requests]


# --- Hospital staff and their shift records ---------------------------------

@router.get("/staff", response_model=List[StaffOut])
def all_staff(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    """Every staff login at every hospital, across every shift."""
    return db.query(Staff).order_by(Staff.hospital_id, Staff.shift).all()


@router.get("/staff/{staff_id}/visitors", response_model=List[VisitorEntryOut])
def staff_visitor_history(staff_id: int, db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    """One staff member's full shift record -- every donor and patient they logged."""
    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")
    entries = (
        db.query(VisitorEntry)
        .filter(VisitorEntry.staff_id == staff_id)
        .order_by(VisitorEntry.logged_at.desc())
        .all()
    )
    return [
        VisitorEntryOut(
            id=e.id, staff_id=e.staff_id, hospital_id=e.hospital_id, visitor_type=e.visitor_type,
            full_name=e.full_name, blood_type=e.blood_type, phone_number=e.phone_number,
            from_location=e.from_location, notes=e.notes, logged_at=e.logged_at,
            staff_name=staff.full_name, staff_shift=staff.shift,
        )
        for e in entries
    ]


# --- Verification panel: hospital licensing, donor medical clearance -------

@router.get("/verification/hospitals/pending", response_model=List[HospitalOut])
def pending_hospitals(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    """Hospitals that registered a license number but haven't been checked and approved yet."""
    return db.query(Hospital).filter(Hospital.is_verified == False).order_by(Hospital.created_at.desc()).all()  # noqa: E712


@router.post("/verification/hospitals/{hospital_id}/approve", response_model=HospitalOut)
def approve_hospital(hospital_id: int, db: Session = Depends(get_db), current_admin: Admin = Depends(get_current_admin)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    hospital.is_verified = True
    hospital.verified_at = datetime.utcnow()
    hospital.verified_by_admin_id = current_admin.id
    db.commit()
    db.refresh(hospital)
    record_event(
        db, "hospital_verified", actor_type="admin", actor_id=current_admin.id,
        payload={"hospital_id": hospital.id, "license_number": hospital.license_number},
    )
    return hospital


@router.post("/verification/hospitals/{hospital_id}/reject", response_model=HospitalOut)
def reject_hospital(hospital_id: int, db: Session = Depends(get_db), current_admin: Admin = Depends(get_current_admin)):
    """Marks the license as not (yet) valid; the hospital stays registered but unverified."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    hospital.is_verified = False
    hospital.verified_at = None
    hospital.verified_by_admin_id = None
    db.commit()
    db.refresh(hospital)
    record_event(
        db, "hospital_verification_rejected", actor_type="admin", actor_id=current_admin.id,
        payload={"hospital_id": hospital.id, "license_number": hospital.license_number},
    )
    return hospital


@router.get("/verification/donors/pending", response_model=List[DonorOut])
def pending_donors(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    """Donors who haven't yet been medically cleared to donate."""
    return (
        db.query(Donor)
        .filter(Donor.medical_clearance_status == "pending")
        .order_by(Donor.created_at.desc())
        .all()
    )


@router.post("/verification/donors/{donor_id}/clear", response_model=DonorOut)
def clear_donor(donor_id: int, notes: str = "", db: Session = Depends(get_db), current_admin: Admin = Depends(get_current_admin)):
    """
    Stands in for a medical provider confirming this donor's eligibility
    (screening results, no disqualifying conditions, etc.).
    """
    donor = db.query(Donor).filter(Donor.id == donor_id).first()
    if not donor:
        raise HTTPException(status_code=404, detail="Donor not found")
    donor.medical_clearance_status = "cleared"
    donor.medical_clearance_notes = notes or None
    db.commit()
    db.refresh(donor)
    record_event(
        db, "donor_medically_cleared", actor_type="admin", actor_id=current_admin.id,
        payload={"donor_id": donor.id},
    )
    return donor


@router.post("/verification/donors/{donor_id}/flag", response_model=DonorOut)
def flag_donor(donor_id: int, notes: str = "", db: Session = Depends(get_db), current_admin: Admin = Depends(get_current_admin)):
    """Marks a donor as not currently eligible to donate, with a reason for the record."""
    donor = db.query(Donor).filter(Donor.id == donor_id).first()
    if not donor:
        raise HTTPException(status_code=404, detail="Donor not found")
    donor.medical_clearance_status = "flagged"
    donor.medical_clearance_notes = notes or None
    db.commit()
    db.refresh(donor)
    record_event(
        db, "donor_flagged", actor_type="admin", actor_id=current_admin.id,
        payload={"donor_id": donor.id, "notes": notes},
    )
    return donor


# --- Tamper-evident audit trail ---------------------------------------------

@router.get("/audit/verify")
def verify_audit_chain(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    """Recomputes every hash in the audit chain and confirms nothing has been altered."""
    return verify_chain(db)


@router.get("/audit/log")
def recent_audit_log(limit: int = 200, db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    """The most recent tamper-evident events, newest first."""
    from app.models.audit_log import AuditLog
    entries = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": e.id, "event_type": e.event_type, "actor_type": e.actor_type, "actor_id": e.actor_id,
            "payload": e.payload_json, "hash": e.hash, "prev_hash": e.prev_hash, "created_at": e.created_at,
        }
        for e in entries
    ]


# --- Delivery channel status (SMS / email / push) ---------------------------

@router.get("/delivery-status")
def delivery_status(_admin: Admin = Depends(get_current_admin)):
    """Whether real SMS, email, and push notifications are configured on this server."""
    from app.services.delivery_service import delivery_status as sms_email_status
    from app.services.push_service import is_push_configured
    from app.services.ai_client import is_ai_configured
    status = sms_email_status()
    status["push_configured"] = is_push_configured()
    status["ai_configured"] = is_ai_configured()
    return status


# --- Reporting export for health authorities --------------------------------

@router.get("/reports/summary")
def reports_summary(
    blood_type: str = None, start_date: str = None, end_date: str = None,
    db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin),
):
    """Aggregated counts by blood type and status, for the printable/CSV report."""
    query = db.query(BloodRequest)
    if blood_type:
        query = query.filter(BloodRequest.blood_type_needed == blood_type)
    if start_date:
        query = query.filter(BloodRequest.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(BloodRequest.created_at <= datetime.fromisoformat(end_date))
    requests = query.all()

    by_type = {}
    for r in requests:
        row = by_type.setdefault(r.blood_type_needed, {
            "blood_type": r.blood_type_needed, "requests": 0, "units_needed": 0,
            "units_fulfilled": 0, "units_from_inventory": 0, "fulfilled_requests": 0,
        })
        row["requests"] += 1
        row["units_needed"] += r.units_needed
        row["units_fulfilled"] += r.units_fulfilled
        row["units_from_inventory"] += r.inventory_units_used or 0
        if r.status == "fulfilled":
            row["fulfilled_requests"] += 1

    donations = db.query(Donation).all()
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "filters": {"blood_type": blood_type, "start_date": start_date, "end_date": end_date},
        "total_requests": len(requests),
        "total_donations_all_time": len(donations),
        "by_blood_type": sorted(by_type.values(), key=lambda r: r["blood_type"]),
    }


@router.get("/reports/export.csv")
def reports_export_csv(
    blood_type: str = None, start_date: str = None, end_date: str = None,
    db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin),
):
    """The same report as a downloadable CSV, for handing to a health authority or importing elsewhere."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    summary = reports_summary(blood_type, start_date, end_date, db, _admin)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Blood type", "Requests", "Units needed", "Units fulfilled", "Units from hospital stock", "Fulfilled requests"])
    for row in summary["by_blood_type"]:
        writer.writerow([row["blood_type"], row["requests"], row["units_needed"], row["units_fulfilled"], row["units_from_inventory"], row["fulfilled_requests"]])
    buffer.seek(0)
    filename = f"lifeflow_report_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(buffer, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})
