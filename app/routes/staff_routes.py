from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.staff import Staff, SHIFT_CHOICES, ROLE_CHOICES
from app.models.hospital import Hospital
from app.models.visitor_log import VisitorEntry
from app.schemas.staff_schema import StaffCreate, StaffOut
from app.schemas.visitor_schema import VisitorEntryCreate, VisitorEntryOut
from app.utils.dependencies import get_current_hospital, get_current_staff, require_staff_permission
from app.utils.permissions import permissions_for
from app.utils.security import hash_password
from app.models.donor import Donor
from app.schemas.donor_schema import DonorOut
from app.services.audit_service import record_event
from app.utils.notify import notify

router = APIRouter(prefix="/staff", tags=["Hospital Staff & Shifts"])


def _staff_out(staff: Staff) -> StaffOut:
    return StaffOut(
        id=staff.id, hospital_id=staff.hospital_id, full_name=staff.full_name, email=staff.email, shift=staff.shift,
        role=staff.role or "receptionist", permissions=permissions_for(staff.role),
        phone_number=staff.phone_number, created_at=staff.created_at,
    )


def _entry_out(entry: VisitorEntry, staff: Staff) -> VisitorEntryOut:
    return VisitorEntryOut(
        id=entry.id,
        staff_id=entry.staff_id,
        hospital_id=entry.hospital_id,
        visitor_type=entry.visitor_type,
        full_name=entry.full_name,
        blood_type=entry.blood_type,
        phone_number=entry.phone_number,
        from_location=entry.from_location,
        notes=entry.notes,
        logged_at=entry.logged_at,
        staff_name=staff.full_name if staff else None,
        staff_shift=staff.shift if staff else None,
    )


# --- The hospital creates and manages its own staff logins -----------------

@router.post("", response_model=StaffOut, status_code=201)
def create_staff(
    staff_data: StaffCreate,
    db: Session = Depends(get_db),
    current_hospital: Hospital = Depends(get_current_hospital),
):
    if staff_data.shift not in SHIFT_CHOICES:
        raise HTTPException(status_code=400, detail=f"Shift must be one of {SHIFT_CHOICES}")

    existing = db.query(Staff).filter(Staff.email == staff_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="A staff account with this email already exists")

    new_staff = Staff(
        hospital_id=current_hospital.id,
        full_name=staff_data.full_name,
        email=staff_data.email,
        hashed_password=hash_password(staff_data.password),
        shift=staff_data.shift,
        role=staff_data.role,
        phone_number=staff_data.phone_number,
    )
    db.add(new_staff)
    db.commit()
    db.refresh(new_staff)
    return _staff_out(new_staff)


@router.get("", response_model=List[StaffOut])
def list_my_staff(db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_current_hospital)):
    """Every staff login this hospital has created, across all shifts."""
    rows = (
        db.query(Staff)
        .filter(Staff.hospital_id == current_hospital.id)
        .order_by(Staff.shift, Staff.full_name)
        .all()
    )
    return [_staff_out(row) for row in rows]


class RoleChange(BaseModel):
    role: str


@router.put("/{staff_id}/role", response_model=StaffOut)
def change_staff_role(
    staff_id: int, change: RoleChange,
    db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_current_hospital),
):
    """The hospital changes what a staff member is allowed to do."""
    if change.role not in ROLE_CHOICES:
        raise HTTPException(status_code=400, detail=f"Role must be one of {ROLE_CHOICES}")
    staff = db.query(Staff).filter(Staff.id == staff_id, Staff.hospital_id == current_hospital.id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")
    staff.role = change.role
    db.commit()
    db.refresh(staff)
    return _staff_out(staff)


@router.delete("/{staff_id}", status_code=204)
def remove_staff(staff_id: int, db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_current_hospital)):
    staff = db.query(Staff).filter(Staff.id == staff_id, Staff.hospital_id == current_hospital.id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")
    db.delete(staff)
    db.commit()


@router.get("/hospital/visitors", response_model=List[VisitorEntryOut])
def hospital_all_visitor_entries(db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_current_hospital)):
    """
    Every donor and patient logged by every staff member across every
    shift, so the hospital can see the combined front-desk record, not
    just one staff member's part of it.
    """
    entries = (
        db.query(VisitorEntry)
        .filter(VisitorEntry.hospital_id == current_hospital.id)
        .order_by(VisitorEntry.logged_at.desc())
        .all()
    )
    results = []
    for entry in entries:
        staff = db.query(Staff).filter(Staff.id == entry.staff_id).first()
        results.append(_entry_out(entry, staff))
    return results


# --- A staff member's own account, logged in for their shift ---------------

@router.get("/me", response_model=StaffOut)
def read_my_staff_profile(current_staff: Staff = Depends(get_current_staff)):
    return _staff_out(current_staff)


@router.post("/visitors", response_model=VisitorEntryOut, status_code=201)
def log_visitor(
    entry_data: VisitorEntryCreate,
    db: Session = Depends(get_db),
    current_staff: Staff = Depends(require_staff_permission("log_visitors")),
):
    """A staff member records one donor or patient they attended to, right now, during their shift."""
    if entry_data.visitor_type not in ("donor", "patient"):
        raise HTTPException(status_code=400, detail="visitor_type must be 'donor' or 'patient'")

    entry = VisitorEntry(
        staff_id=current_staff.id,
        hospital_id=current_staff.hospital_id,
        visitor_type=entry_data.visitor_type,
        full_name=entry_data.full_name,
        blood_type=entry_data.blood_type,
        phone_number=entry_data.phone_number,
        from_location=entry_data.from_location,
        notes=entry_data.notes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _entry_out(entry, current_staff)


@router.get("/visitors/mine", response_model=List[VisitorEntryOut])
def my_visitor_entries(db: Session = Depends(get_db), current_staff: Staff = Depends(get_current_staff)):
    """
    This staff member's own complete shift record -- every donor and
    patient they have ever logged, kept fully separate from every
    other staff member's record, so it is always there to review and
    print when they go off duty.
    """
    entries = (
        db.query(VisitorEntry)
        .filter(VisitorEntry.staff_id == current_staff.id)
        .order_by(VisitorEntry.logged_at.desc())
        .all()
    )
    return [_entry_out(entry, current_staff) for entry in entries]


# --- Doctor: medical screening of donors ------------------------------------
@router.get("/screening/donors", response_model=List[DonorOut])
def donors_waiting_for_screening(
    db: Session = Depends(get_db), _doctor: Staff = Depends(require_staff_permission("screen_donors")),
):
    """Donors who have not yet been medically cleared. Only doctors and managers can open this."""
    return (
        db.query(Donor).filter(Donor.medical_clearance_status == "pending")
        .order_by(Donor.created_at.desc()).limit(200).all()
    )


class ScreeningDecision(BaseModel):
    notes: Optional[str] = None


def _screen(db: Session, donor_id: int, doctor: Staff, status_value: str, notes: Optional[str]) -> Donor:
    donor = db.query(Donor).filter(Donor.id == donor_id).first()
    if not donor:
        raise HTTPException(status_code=404, detail="Donor not found")
    donor.medical_clearance_status = status_value
    donor.medical_clearance_notes = (" ".join((notes or "").split())[:300] or None)
    notify(db, "donor", donor.id,
           "You are medically cleared" if status_value == "cleared" else "Medical check: not eligible now",
           "A doctor checked your details and cleared you to donate blood." if status_value == "cleared"
           else "A doctor says you cannot donate right now. Please speak to the doctor at the blood bank.",
           category="system")
    db.commit()
    db.refresh(donor)
    record_event(db, "donor_medically_cleared" if status_value == "cleared" else "donor_flagged",
                 actor_type="staff", actor_id=doctor.id, payload={"donor_id": donor.id, "role": doctor.role})
    return donor


@router.post("/screening/donors/{donor_id}/clear", response_model=DonorOut)
def doctor_clear_donor(
    donor_id: int, decision: ScreeningDecision, db: Session = Depends(get_db),
    doctor: Staff = Depends(require_staff_permission("screen_donors")),
):
    return _screen(db, donor_id, doctor, "cleared", decision.notes)


@router.post("/screening/donors/{donor_id}/flag", response_model=DonorOut)
def doctor_flag_donor(
    donor_id: int, decision: ScreeningDecision, db: Session = Depends(get_db),
    doctor: Staff = Depends(require_staff_permission("screen_donors")),
):
    return _screen(db, donor_id, doctor, "flagged", decision.notes)
