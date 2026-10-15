from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.models.admin import Admin
from app.models.staff import Staff
from app.models.request import BloodRequest
from app.models.donation import Donation
from app.models.inventory import BloodInventory
from app.models.visitor_log import VisitorEntry
from app.schemas.ai_schema import (
    ParseRequestIn, ParseRequestOut, AssistantMessageIn, AssistantMessageOut,
    ForecastOut, ForecastEntryOut,
)
from app.services.ai_client import ask_claude, ask_claude_for_json, is_ai_configured, NOT_CONFIGURED_MESSAGE
from app.services.forecast_service import forecast_hospital, forecast_platform
from app.utils.dependencies import get_current_donor, get_current_hospital, get_current_receiver, get_current_admin, get_current_staff

router = APIRouter(prefix="/ai", tags=["AI features"])

VALID_BLOOD_TYPES = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]

RESPONSIBLE_USE_NOTE = (
    "You are part of LifeFlow, a blood bank coordination platform. You are NOT a doctor. "
    "Never give medical advice, diagnoses, or treatment recommendations -- for any medical "
    "question, tell the person to speak to a qualified doctor or hospital staff. You may help "
    "with anything related to using the LifeFlow platform: requests, donations, inventory, "
    "history, ratings, shifts, and general guidance about blood donation eligibility rules "
    "already described to you. Keep replies short, warm, and practical -- a few sentences or a "
    "short list, not an essay. If you don't know something about this specific account, say so "
    "honestly rather than guessing."
)


@router.get("/status")
def ai_status():
    """Lets the frontend show/hide AI features depending on whether an API key is configured."""
    return {"configured": is_ai_configured()}


@router.get("/diagnostic")
def ai_diagnostic():
    """
    A quick, no-context test call straight to Groq, for debugging setup
    issues. If this fails, check the backend server's own console --
    the real status code / error from Groq is printed there.
    """
    if not is_ai_configured():
        return {"ok": False, "reason": "GROQ_API_KEY is not set."}
    reply = ask_claude("You are a test assistant.", "Reply with exactly: OK")
    success = "error" not in reply.lower() and "not set up" not in reply.lower()
    return {"ok": success, "reply": reply, "check_backend_console_for_details": not success}


# ---------------------------------------------------------------------------
# 1. Multilingual natural-language request intake
# ---------------------------------------------------------------------------

@router.post("/parse-request", response_model=ParseRequestOut)
def parse_request(payload: ParseRequestIn):
    """
    Turns a free-text message -- in any language -- describing a blood
    need into the structured fields LifeFlow's request form uses. The
    person always sees the parsed result before it's submitted, so a
    misreading never becomes a request on its own.
    """
    if not is_ai_configured():
        return ParseRequestOut(understood=False, note_to_user=NOT_CONFIGURED_MESSAGE)

    system_prompt = (
        "You read a short message -- written in any language (English, Urdu, Spanish, French, "
        "Roman Urdu, or any other) -- from someone who needs blood, possibly written in a panic "
        "with typos or mixed languages. Extract structured fields for a blood request form.\n\n"
        f"blood_type_needed must be one of exactly: {', '.join(VALID_BLOOD_TYPES)}, or null if not mentioned.\n"
        "units_needed: a whole number of blood bags, default 1 if not mentioned.\n"
        "patient_name, patient_age (number), patient_gender (Male/Female/Other): null if not mentioned.\n"
        "medical_reason: a short phrase (e.g. 'surgery', 'accident', 'thalassemia'), null if not mentioned.\n"
        "urgency_type: one of 'emergency', 'days', or 'months'. Default 'emergency' if the tone sounds urgent "
        "or no timeframe is given.\n"
        "urgency_value: a whole number of days or months, only if urgency_type is 'days' or 'months'.\n"
        "detected_language: the main language of the message, as a short English name (e.g. 'Urdu', 'English').\n"
        "note_to_user: one short, warm sentence confirming what you understood, written in the SAME language "
        "as the input message.\n\n"
        "Return JSON with exactly these keys: blood_type_needed, units_needed, patient_name, patient_age, "
        "patient_gender, medical_reason, urgency_type, urgency_value, detected_language, note_to_user."
    )

    parsed = ask_claude_for_json(system_prompt, payload.text)
    if not parsed:
        return ParseRequestOut(
            understood=False,
            note_to_user="I couldn't understand that message clearly -- please fill in the form directly.",
        )

    blood_type = parsed.get("blood_type_needed")
    if blood_type not in VALID_BLOOD_TYPES:
        blood_type = None

    return ParseRequestOut(
        understood=True,
        blood_type_needed=blood_type,
        units_needed=parsed.get("units_needed") or 1,
        patient_name=parsed.get("patient_name"),
        patient_age=parsed.get("patient_age"),
        patient_gender=parsed.get("patient_gender"),
        medical_reason=parsed.get("medical_reason"),
        urgency_type=parsed.get("urgency_type") or "emergency",
        urgency_value=parsed.get("urgency_value"),
        detected_language=parsed.get("detected_language"),
        note_to_user=parsed.get("note_to_user"),
    )


# ---------------------------------------------------------------------------
# 2. Role-aware AI assistant -- one endpoint per role, each with its own
#    context built from that account's own data, so answers are specific
#    and no one can ask about someone else's records through the assistant.
# ---------------------------------------------------------------------------

@router.post("/assistant/guest", response_model=AssistantMessageOut)
def assistant_guest(payload: AssistantMessageIn, db: Session = Depends(get_db)):
    """
    Public assistant for the home page, before anyone has logged in.
    No personal data is available here at all -- only general
    information about how LifeFlow works, blood types, and donation
    basics -- so this is safe to expose with no authentication.
    """
    platform_donors = db.query(Donor).count()
    platform_hospitals = db.query(Hospital).count()
    context = (
        f"You are talking to a visitor who has NOT logged in yet, on LifeFlow's public home page. "
        f"The platform currently has {platform_donors} registered donors and {platform_hospitals} partner hospitals. "
        "You can explain: what LifeFlow does, how the stock-check-first flow works (hospital inventory is checked "
        "before any donor is contacted), how donor matching and ratings work, blood type compatibility in general "
        "terms, and how to register as a donor, patient, or hospital. You have NO access to anyone's personal "
        "data, requests, or history -- if asked about a specific account, tell them to log in first."
    )
    reply = ask_claude(RESPONSIBLE_USE_NOTE + "\n\n" + context, payload.message)
    return AssistantMessageOut(reply=reply)


@router.post("/assistant/donor", response_model=AssistantMessageOut)
def assistant_donor(payload: AssistantMessageIn, db: Session = Depends(get_db), donor: Donor = Depends(get_current_donor)):
    donation_count = db.query(Donation).filter(Donation.donor_id == donor.id).count()
    open_requests_nearby = db.query(BloodRequest).filter(BloodRequest.status == "open").count()
    context = (
        f"This donor's account: name {donor.full_name}, blood type {donor.blood_type}, "
        f"{donor.points} points earned, eligible to donate: {donor.is_eligible}, "
        f"last donation date: {donor.last_donation_date or 'never recorded'}, "
        f"total donations made: {donation_count}. There are currently {open_requests_nearby} open "
        "blood requests on the platform (not necessarily compatible/nearby). "
        "You can explain eligibility rules (donors usually wait 90 days between donations on LifeFlow), "
        "how matching and points work, and how to read a request's details before accepting or rejecting it."
    )
    reply = ask_claude(RESPONSIBLE_USE_NOTE + "\n\n" + context, payload.message)
    return AssistantMessageOut(reply=reply)


@router.post("/assistant/receiver", response_model=AssistantMessageOut)
def assistant_receiver(payload: AssistantMessageIn, db: Session = Depends(get_db), receiver: Receiver = Depends(get_current_receiver)):
    my_requests = (
        db.query(BloodRequest)
        .filter(BloodRequest.requester_type == "receiver", BloodRequest.requester_id == receiver.id)
        .order_by(BloodRequest.created_at.desc())
        .limit(5)
        .all()
    )
    requests_summary = "; ".join(
        f"#{r.id} {r.blood_type_needed} x{r.units_needed}, status {r.status}, "
        f"{r.units_fulfilled}/{r.units_needed} fulfilled" for r in my_requests
    ) or "no requests yet"
    context = (
        f"This patient's account: name {receiver.full_name}, patient on file: {receiver.patient_name or 'not set'}. "
        f"Their 5 most recent requests: {requests_summary}. "
        "You can explain how the stock-check-first flow works (hospital inventory is always checked before "
        "donors are contacted), how to track a request, and how to rate a donor after a donation."
    )
    reply = ask_claude(RESPONSIBLE_USE_NOTE + "\n\n" + context, payload.message)
    return AssistantMessageOut(reply=reply)


@router.post("/assistant/hospital", response_model=AssistantMessageOut)
def assistant_hospital(payload: AssistantMessageIn, db: Session = Depends(get_db), hospital: Hospital = Depends(get_current_hospital)):
    inventory_rows = db.query(BloodInventory).filter(BloodInventory.hospital_id == hospital.id).all()
    inventory_summary = ", ".join(f"{row.blood_type}: {row.units_available}" for row in inventory_rows) or "no inventory recorded yet"
    open_requests = (
        db.query(BloodRequest)
        .filter(BloodRequest.requester_type == "hospital", BloodRequest.requester_id == hospital.id, BloodRequest.status == "open")
        .count()
    )
    context = (
        f"This hospital's account: {hospital.name}. Current blood bank inventory: {inventory_summary}. "
        f"Open requests right now: {open_requests}. "
        "You can explain the shortage forecast, how stock-check-first works, how staff shifts and "
        "visitor logs work, and how to read donor match scores (distance + reliability)."
    )
    reply = ask_claude(RESPONSIBLE_USE_NOTE + "\n\n" + context, payload.message)
    return AssistantMessageOut(reply=reply)


@router.post("/assistant/admin", response_model=AssistantMessageOut)
def assistant_admin(payload: AssistantMessageIn, db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    total_donors = db.query(Donor).count()
    total_hospitals = db.query(Hospital).count()
    total_receivers = db.query(Receiver).count()
    total_requests = db.query(BloodRequest).count()
    open_requests = db.query(BloodRequest).filter(BloodRequest.status == "open").count()
    context = (
        f"Platform-wide numbers: {total_donors} donors, {total_hospitals} hospitals, {total_receivers} patients, "
        f"{total_requests} requests total ({open_requests} currently open). "
        "You can explain platform-wide shortage forecasts, help interpret trends, and describe how any "
        "part of LifeFlow (matching, stock-check-first, staff shifts, ratings) works end to end."
    )
    reply = ask_claude(RESPONSIBLE_USE_NOTE + "\n\n" + context, payload.message)
    return AssistantMessageOut(reply=reply)


@router.post("/assistant/staff", response_model=AssistantMessageOut)
def assistant_staff(payload: AssistantMessageIn, db: Session = Depends(get_db), staff: Staff = Depends(get_current_staff)):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    entries_today = (
        db.query(VisitorEntry)
        .filter(VisitorEntry.staff_id == staff.id, VisitorEntry.logged_at >= today_start)
        .count()
    )
    context = (
        f"This staff member: {staff.full_name}, shift {staff.shift}, at hospital ID {staff.hospital_id}. "
        f"Visitor entries logged today: {entries_today}. "
        "You can explain how to log a donor or patient visit, how to print/save their shift record as a "
        "PDF at the end of duty, and general front-desk questions about using LifeFlow."
    )
    reply = ask_claude(RESPONSIBLE_USE_NOTE + "\n\n" + context, payload.message)
    return AssistantMessageOut(reply=reply)


# ---------------------------------------------------------------------------
# 3. Shortage forecasting
# ---------------------------------------------------------------------------

@router.get("/forecast/hospital", response_model=ForecastOut)
def hospital_forecast(db: Session = Depends(get_db), hospital: Hospital = Depends(get_current_hospital)):
    entries = forecast_hospital(db, hospital.id)
    summary = None
    if is_ai_configured():
        high_risk = [e for e in entries if e["risk_level"] == "high"]
        if high_risk:
            prompt_text = ", ".join(f"{e['blood_type']} ({e['days_until_shortage']} days left)" for e in high_risk)
            summary = ask_claude(
                "You write a single, short (1-2 sentence), plain-language warning for a hospital dashboard "
                "based on a shortage forecast. Be direct and actionable, no fluff.",
                f"These blood types are at high risk of running out soon: {prompt_text}. Write the warning.",
                max_tokens=150,
            )
    return ForecastOut(entries=[ForecastEntryOut(**e) for e in entries], summary=summary)


@router.get("/forecast/platform", response_model=ForecastOut)
def platform_forecast(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    entries = forecast_platform(db)
    return ForecastOut(entries=[ForecastEntryOut(**e) for e in entries], summary=None)
