"""
Report downloads as Excel (.xlsx) and PDF for the admin, hospitals and donors.
GET /exports/<admin|hospital|donor>/<xlsx|pdf>   (the person must be logged in as that role)
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import Admin
from app.models.blood_batch import BloodBatch
from app.models.blood_transfer import BloodTransfer
from app.models.donation import Donation
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest
from app.routes.admin_routes import reports_summary
from app.routes.donation_routes import _entries_for_donations
from app.services.export_service import build_pdf, build_xlsx
from app.services.history_service import donations_for_requests
from app.utils.dependencies import get_current_admin, get_current_donor, get_current_hospital, get_hospital_for_checkin
from app.models.camp import DonationCamp
from app.routes.checkin_routes import attendance

router = APIRouter(prefix="/exports", tags=["Report downloads"])

MEDIA = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
MAX_ROWS = 5000


def _send(fmt: str, title: str, sheets: list, filename: str) -> Response:
    if fmt not in MEDIA:
        raise HTTPException(status_code=400, detail="Choose xlsx or pdf")
    try:
        data = build_xlsx(title, sheets) if fmt == "xlsx" else build_pdf(title, sheets)
    except ImportError:
        raise HTTPException(status_code=503, detail="Report downloads need openpyxl and reportlab. Run: pip install -r requirements.txt")
    stamp = datetime.utcnow().strftime("%Y%m%d")
    return Response(content=data, media_type=MEDIA[fmt],
                    headers={"Content-Disposition": f"attachment; filename={filename}_{stamp}.{fmt}"})


def _request_rows(db: Session, requests: list) -> list:
    from app.routes.request_routes import build_request_out
    rows = []
    for r in requests:
        out = build_request_out(db, r)
        rows.append([out.id, out.created_at, out.requester_type, out.requester_name, out.blood_type_needed,
                     out.units_needed, out.units_fulfilled, out.status, out.urgency_type,
                     "yes" if out.is_sos else "", out.inventory_units_used])
    return rows


REQUEST_HEADERS = ["ID", "Created", "Requested by (type)", "Requested by", "Blood type", "Bags needed",
                   "Bags fulfilled", "Status", "Urgency", "SOS", "Bags from stock"]


@router.get("/admin/{fmt}")
def export_admin(fmt: str, db: Session = Depends(get_db), admin: Admin = Depends(get_current_admin)):
    summary = reports_summary(None, None, None, db, admin)
    requests = db.query(BloodRequest).order_by(BloodRequest.id.desc()).limit(MAX_ROWS).all()
    donations = db.query(Donation).order_by(Donation.id.desc()).limit(MAX_ROWS).all()
    donation_rows = []
    for entry in _entries_for_donations(db, donations):
        donation_rows.append([entry.donation_id, entry.donated_at, entry.donor_name, entry.donor_blood_type,
                              entry.units_donated, entry.requester_name, entry.blood_type_needed])
    sheets = [
        {"title": "Summary by blood type",
         "headers": ["Blood type", "Requests", "Bags needed", "Bags fulfilled", "Bags from hospital stock", "Fulfilled requests"],
         "rows": [[r["blood_type"], r["requests"], r["units_needed"], r["units_fulfilled"], r["units_from_inventory"], r["fulfilled_requests"]]
                  for r in summary["by_blood_type"]]},
        {"title": "Requests", "headers": REQUEST_HEADERS, "rows": _request_rows(db, requests)},
        {"title": "Donations",
         "headers": ["ID", "Date", "Donor", "Donor blood", "Bags", "Given to", "Blood needed"], "rows": donation_rows},
        {"title": "Donors",
         "headers": ["ID", "Name", "Blood type", "City", "Area", "Phone", "Points", "Last donation"],
         "rows": [[d.id, d.full_name, d.blood_type, d.city, d.area, d.phone_number, d.points, d.last_donation_date]
                  for d in db.query(Donor).order_by(Donor.id).limit(MAX_ROWS).all()]},
        {"title": "Hospitals",
         "headers": ["ID", "Name", "City", "Area", "Phone", "Verified"],
         "rows": [[h.id, h.name, h.city, h.area, h.phone_number, "yes" if h.is_verified else "no"]
                  for h in db.query(Hospital).order_by(Hospital.id).limit(MAX_ROWS).all()]},
    ]
    return _send(fmt, "Admin report", sheets, "lifeflow_admin_report")


@router.get("/hospital/{fmt}")
def export_hospital(fmt: str, db: Session = Depends(get_db), me: Hospital = Depends(get_current_hospital)):
    requests = (
        db.query(BloodRequest)
        .filter(BloodRequest.requester_type == "hospital", BloodRequest.requester_id == me.id)
        .order_by(BloodRequest.id.desc()).limit(MAX_ROWS).all()
    )
    request_ids = [r.id for r in requests]
    donation_rows = [
        [e.donation_id, e.donated_at, e.donor_name, e.donor_blood_type, e.units_donated, e.blood_type_needed, e.patient_name]
        for e in _entries_for_donations(db, donations_for_requests(db, request_ids))
    ]
    inventory = db.query(BloodInventory).filter(BloodInventory.hospital_id == me.id).order_by(BloodInventory.blood_type).all()
    batches = (
        db.query(BloodBatch).filter(BloodBatch.hospital_id == me.id, BloodBatch.state == "active", BloodBatch.units_remaining > 0)
        .order_by(BloodBatch.expires_on.asc()).all()
    )
    today = datetime.utcnow().date()
    transfers = (
        db.query(BloodTransfer)
        .filter((BloodTransfer.from_hospital_id == me.id) | (BloodTransfer.to_hospital_id == me.id))
        .order_by(BloodTransfer.id.desc()).limit(MAX_ROWS).all()
    )
    names = {h.id: h.name for h in db.query(Hospital).all()}
    sheets = [
        {"title": "Requests", "headers": REQUEST_HEADERS, "rows": _request_rows(db, requests)},
        {"title": "Donations received",
         "headers": ["ID", "Date", "Donor", "Donor blood", "Bags", "Blood needed", "Patient"], "rows": donation_rows},
        {"title": "Blood stock",
         "headers": ["Blood type", "Bags in stock", "Low-stock alert at"],
         "rows": [[i.blood_type, i.units_available, i.low_stock_threshold] for i in inventory]},
        {"title": "Expiry dates",
         "headers": ["Blood type", "Bags", "Collected", "Expires", "Days left"],
         "rows": [[b.blood_type, b.units_remaining, b.collected_on, b.expires_on, (b.expires_on - today).days] for b in batches]},
        {"title": "Transfers",
         "headers": ["ID", "Date", "Direction", "Other hospital", "Blood type", "Bags", "Status"],
         "rows": [[t.id, t.created_at, "we send" if t.from_hospital_id == me.id else "we asked",
                   names.get(t.to_hospital_id if t.from_hospital_id == me.id else t.from_hospital_id, ""),
                   t.blood_type, t.units, t.status] for t in transfers]},
    ]
    return _send(fmt, f"{me.name} - hospital report", sheets, "lifeflow_hospital_report")


@router.get("/donor/{fmt}")
def export_donor(fmt: str, db: Session = Depends(get_db), me: Donor = Depends(get_current_donor)):
    donations = db.query(Donation).filter(Donation.donor_id == me.id).order_by(Donation.donated_at.desc()).all()
    rows = [[e.donation_id, e.donated_at, e.units_donated, e.requester_name, e.blood_type_needed]
            for e in _entries_for_donations(db, donations)]
    sheets = [{"title": "My donations", "headers": ["ID", "Date", "Bags", "Given to", "Blood needed"], "rows": rows}]
    return _send(fmt, f"{me.full_name} - donation history", sheets, "lifeflow_my_donations")


@router.get("/camp/{camp_id}/{fmt}")
def export_camp_attendance(camp_id: int, fmt: str, db: Session = Depends(get_db), me: Hospital = Depends(get_hospital_for_checkin)):
    """Attendance sheet of one camp: who registered, who came, walk-ins, and who checked them in."""
    camp = db.query(DonationCamp).filter(DonationCamp.id == camp_id, DonationCamp.hospital_id == me.id).first()
    if not camp:
        raise HTTPException(status_code=404, detail="Camp not found")
    people = attendance(camp_id, db, me)
    rows = [[i + 1, p.donor_name, p.blood_type, p.phone_number, "attended" if p.status == "attended" else p.status,
             "yes" if p.walk_in else "", p.checked_in_at, p.checked_in_by or ""] for i, p in enumerate(people)]
    came = sum(1 for p in people if p.status == "attended")
    sheets = [
        {"title": "Summary", "headers": ["Camp", "Date", "Place", "Registered", "Came"],
         "rows": [[camp.title, camp.camp_date, camp.location_label, len(people), came]]},
        {"title": "Attendance", "headers": ["No.", "Donor", "Blood type", "Phone", "Status", "Walk-in", "Checked in at", "Checked in by"], "rows": rows},
    ]
    return _send(fmt, f"Camp attendance - {camp.title}", sheets, "lifeflow_camp_attendance")
