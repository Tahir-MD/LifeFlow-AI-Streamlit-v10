import base64
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hospital import Hospital
from app.models.staff import Staff
from app.models.request import BloodRequest
from app.services.ai_client import ask_ai, ask_ai_vision_json, is_ai_configured, NOT_CONFIGURED_MESSAGE, transcribe_audio
from app.services.ai_extras import (
    plan_donor_outreach, optimize_allocation, forecast_accuracy, impact_summary, hospital_data_context,
    find_reengagement_candidates, draft_reengagement_message, suggest_camp_locations,
)
from app.utils.notify import notify
from app.models.donor import Donor
from app.utils.dependencies import get_current_any_account

router = APIRouter(prefix="/ai", tags=["AI decision support"])


def _require_role(account, allowed):
    role, account_id = account
    if role not in allowed:
        raise HTTPException(status_code=403, detail="Your account type can't use this feature")
    return role, account_id


class DataQuestionIn(BaseModel):
    message: str


@router.get("/no-show-plan/{request_id}")
def no_show_plan(request_id: int, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    """Donor no-show prediction: how many (and which) donors to alert so enough actually turn up."""
    _require_role(account, ("hospital", "receiver", "admin", "staff"))
    blood_request = db.query(BloodRequest).filter(BloodRequest.id == request_id).first()
    if not blood_request:
        raise HTTPException(status_code=404, detail="Request not found")
    return plan_donor_outreach(db, blood_request)


@router.get("/allocation")
def allocation(db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    """Multi-request donor allocation across every open request, each donor used at most once."""
    _require_role(account, ("hospital", "admin", "staff"))
    return optimize_allocation(db)


@router.get("/forecast-accuracy")
def accuracy(db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    _require_role(account, ("hospital", "admin", "staff"))
    return forecast_accuracy(db)


@router.get("/impact")
def impact(db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    _require_role(account, ("hospital", "admin", "staff"))
    return impact_summary(db)


@router.post("/data-assistant")
def data_assistant(payload: DataQuestionIn, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    """Ask questions about your own hospital's data in plain language (hospital and staff accounts)."""
    role, account_id = _require_role(account, ("hospital", "staff"))
    if role == "staff":
        staff = db.query(Staff).filter(Staff.id == account_id).first()
        if not staff:
            raise HTTPException(status_code=404, detail="Staff account not found")
        hospital_id = staff.hospital_id
    else:
        hospital_id = account_id

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    facts = hospital_data_context(db, hospital_id)
    if not is_ai_configured():
        return {"reply": NOT_CONFIGURED_MESSAGE + "\n\nHere are the raw facts for now:\n" + facts}

    system_prompt = (
        f"You answer questions about the data of {hospital.name if hospital else 'this hospital'} on LifeFlow, a blood "
        "bank coordination platform. Use ONLY the facts below; if the answer isn't in them, say you don't have that data. "
        "Be brief and give numbers. You are not a doctor and must not give medical advice.\n\nFACTS:\n" + facts
    )
    return {"reply": ask_ai(system_prompt, payload.message)}


@router.post("/verify-document")
async def verify_document(
    doc_type: str = Form(...),          # "cnic" or "licence"
    claimed_number: str = Form(...),
    file: UploadFile = File(...),
):
    """
    AI document check (vision OCR): reads the number off an uploaded photo of a CNIC or a hospital licence
    and compares it to what the person typed. It only SUGGESTS -- anything uncertain is sent for manual review.
    """
    if doc_type not in ("cnic", "licence"):
        raise HTTPException(status_code=400, detail="doc_type must be 'cnic' or 'licence'")
    content = await file.read()
    if len(content) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 4 MB)")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file")

    if not is_ai_configured():
        return {"needs_manual_review": True, "matches_claim": None, "extracted_number": None, "note": NOT_CONFIGURED_MESSAGE}

    what = "national ID (CNIC) number" if doc_type == "cnic" else "hospital licence / registration number"
    result = ask_ai_vision_json(
        "You extract identifiers from photos of documents. Never guess digits you cannot read.",
        f'Read the {what} on this document. Reply as {{"number": "<digits/letters exactly as printed or null>", '
        f'"legible": true/false, "looks_like_genuine_document": true/false}}.',
        base64.b64encode(content).decode(), file.content_type,
    )
    if not result or not result.get("number"):
        return {"needs_manual_review": True, "matches_claim": None, "extracted_number": None,
                "note": "Couldn't read a number from the image. A human reviewer will check it."}

    normalise = lambda v: "".join(ch for ch in str(v).upper() if ch.isalnum())
    matches = normalise(result["number"]) == normalise(claimed_number)
    confident = bool(result.get("legible")) and bool(result.get("looks_like_genuine_document", True))
    return {
        "extracted_number": result["number"], "matches_claim": matches,
        "needs_manual_review": not (matches and confident),
        "note": "Number matches what was typed." if matches else "Number on the document differs from what was typed -- manual review needed.",
    }


# --- Voice-based request intake (Groq Whisper) ------------------------------

@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), account=Depends(get_current_any_account)):
    """
    Transcribes a short voice recording (any language Whisper supports)
    so a panicking family member -- or anyone who'd rather speak than
    type -- can describe what's needed, then run it through
    /ai/parse-request exactly like typed text.
    """
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Recording too large (max 15 MB)")
    transcript = transcribe_audio(content, file.filename or "recording.webm", file.content_type or "audio/webm")
    if transcript is None:
        raise HTTPException(status_code=503, detail="Could not transcribe right now -- AI may not be configured, or the recording was unclear. Please type instead.")
    return {"transcript": transcript}


# --- Donor re-engagement -----------------------------------------------------

class SendReengagementIn(BaseModel):
    donor_id: int
    message: str


@router.get("/re-engagement/candidates")
def reengagement_candidates(hospital_id: int = None, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    """Overdue (or never-donated) donors whose blood type is currently running short. hospital_id optional -- omit for platform-wide."""
    _require_role(account, ("hospital", "admin", "staff"))
    return find_reengagement_candidates(db, hospital_id)


@router.get("/re-engagement/draft/{donor_id}")
def reengagement_draft(donor_id: int, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    """AI-drafted personalized nudge for one donor -- shown for review before anything is sent."""
    _require_role(account, ("hospital", "admin", "staff"))
    donor = db.query(Donor).filter(Donor.id == donor_id).first()
    if not donor:
        raise HTTPException(status_code=404, detail="Donor not found")
    days_overdue = None
    if donor.last_donation_date:
        days_overdue = max((datetime.utcnow() - donor.last_donation_date).days - 90, 0)
    message = draft_reengagement_message(donor, days_overdue, donor.blood_type)
    return {"donor_id": donor.id, "draft_message": message}


@router.post("/re-engagement/send")
def reengagement_send(payload: SendReengagementIn, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    """Sends the (possibly edited) drafted message through every channel that's configured (in-app, SMS, email, push)."""
    _require_role(account, ("hospital", "admin", "staff"))
    donor = db.query(Donor).filter(Donor.id == payload.donor_id).first()
    if not donor:
        raise HTTPException(status_code=404, detail="Donor not found")
    notify(db, "donor", donor.id, "We could use your help again", payload.message, category="general")
    db.commit()
    return {"sent": True}


# --- AI-assisted camp location suggestions -----------------------------------

@router.get("/camp-suggestions")
def camp_suggestions(days: int = 60, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    """Where recent request demand is clustering, as a starting point for planning the next donation camp."""
    _require_role(account, ("hospital", "admin"))
    return suggest_camp_locations(db, days=days)
