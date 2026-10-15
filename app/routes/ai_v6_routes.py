"""
v6 AI features:
  weekly report            GET  /ai/weekly-report ... (+ /export/xlsx|pdf, POST /generate)
  ambulance and ETA        GET  /ai/eta/{request_id}
  camp predictor           GET  /ai/camp-forecast/{camp_id}
  donor response           GET  /ai/response-prediction/{request_id}
  voice assistant          POST /ai/voice-assistant       (audio or typed text; Urdu / Sindhi / English)
  prescription scanner     POST /ai/scan-slip              (photo of a doctor slip -> request form fields)
  conversational health    POST /ai/health-chat/interpret, /ai/health-chat/transcribe (public, small)
Every one of them only SUGGESTS. Photos and voice recordings are read in memory and never saved.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.camp import DonationCamp
from app.models.request import BloodRequest
from app.models.staff import Staff
from app.models.weekly_report import WeeklyReport
from app.services import insight_logic as logic
from app.services import v6_service as svc
from app.services.ai_v6_core import FALLBACK_REPLIES as _FALLBACK_REPLIES, run_slip_scan, run_voice_assistant
from app.services.ai_client import (
    NOT_CONFIGURED_MESSAGE, ask_ai_for_json, is_ai_configured, transcribe_audio,
)
from app.services.export_service import build_pdf, build_xlsx
from app.utils.dependencies import get_current_any_account

router = APIRouter(prefix="/ai", tags=["AI v6"])

LANGUAGE_NAMES = {"en": "English", "ur": "Urdu", "sd": "Sindhi"}
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_AUDIO_BYTES = 8 * 1024 * 1024
PUBLIC_AUDIO_BYTES = 2 * 1024 * 1024


def _hospital_scope(db: Session, account, requested_hospital_id: Optional[int] = None):
    """Returns ("platform", None) for admins, or ("hospital", id) for a hospital / its staff."""
    role, account_id = account
    if role == "admin":
        if requested_hospital_id:
            return "hospital", requested_hospital_id
        return "platform", None
    if role == "hospital":
        return "hospital", account_id
    if role == "staff":
        staff = db.query(Staff).filter(Staff.id == account_id).first()
        if not staff:
            raise HTTPException(status_code=404, detail="Staff account not found")
        return "hospital", staff.hospital_id
    raise HTTPException(status_code=403, detail="Your account type can't use this feature")


def _load_request_for(db: Session, request_id: int, account, owner_only_roles=("receiver",)) -> BloodRequest:
    role, account_id = account
    blood_request = db.query(BloodRequest).filter(BloodRequest.id == request_id).first()
    if not blood_request:
        raise HTTPException(status_code=404, detail="Request not found")
    if role == "donor":
        raise HTTPException(status_code=403, detail="Your account type can't use this feature")
    if role in owner_only_roles and not (blood_request.requester_type == role and blood_request.requester_id == account_id):
        raise HTTPException(status_code=403, detail="You can only look at your own requests")
    return blood_request


# ---------------------------------------------------------------- 1. weekly report -------------
@router.get("/weekly-report")
def latest_weekly_report(hospital_id: Optional[int] = None, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    scope, hid = _hospital_scope(db, account, hospital_id)
    row = (db.query(WeeklyReport).filter(WeeklyReport.scope == scope, WeeklyReport.hospital_id == hid)
           .order_by(WeeklyReport.created_at.desc()).first())
    return svc.report_to_dict(row) if row else {"empty": True}


@router.get("/weekly-report/history")
def weekly_report_history(hospital_id: Optional[int] = None, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    scope, hid = _hospital_scope(db, account, hospital_id)
    rows = (db.query(WeeklyReport).filter(WeeklyReport.scope == scope, WeeklyReport.hospital_id == hid)
            .order_by(WeeklyReport.created_at.desc()).limit(12).all())
    return [svc.report_to_dict(r) for r in rows]


@router.post("/weekly-report/generate")
def generate_report_now(hospital_id: Optional[int] = None, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    scope, hid = _hospital_scope(db, account, hospital_id)
    return svc.generate_weekly_report(db, scope, hid)


@router.get("/weekly-report/{report_id}/export/{fmt}")
def export_report(report_id: int, fmt: str, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    scope, hid = _hospital_scope(db, account)
    row = db.query(WeeklyReport).filter(WeeklyReport.id == report_id).first()
    if not row or (scope == "hospital" and (row.scope != "hospital" or row.hospital_id != hid)):
        raise HTTPException(status_code=404, detail="Report not found")
    if fmt not in ("xlsx", "pdf"):
        raise HTTPException(status_code=400, detail="Choose xlsx or pdf")
    report = svc.report_to_dict(row)
    title = f"LifeFlow weekly report {report['stats']['period_start']} to {report['stats']['period_end']}"
    sheets = svc.report_sheets(report)
    if fmt == "xlsx":
        body, media = build_xlsx(title, sheets), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        body, media = build_pdf(title, sheets), "application/pdf"
    return Response(content=body, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="lifeflow_weekly_report_{report_id}.{fmt}"'})


# ---------------------------------------------------------------- 2. ambulance and ETA ---------
@router.get("/eta/{request_id}")
def eta_suggestions(request_id: int, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    blood_request = _load_request_for(db, request_id, account)
    return svc.build_eta_plan(db, blood_request)


# ---------------------------------------------------------------- 3. camp predictor ------------
@router.get("/camp-forecast/{camp_id}")
def camp_forecast(camp_id: int, hours: float = 6.0, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    scope, hid = _hospital_scope(db, account)
    camp = db.query(DonationCamp).filter(DonationCamp.id == camp_id).first()
    if not camp:
        raise HTTPException(status_code=404, detail="Camp not found")
    if scope == "hospital" and camp.hospital_id != hid:
        raise HTTPException(status_code=403, detail="This camp belongs to another hospital")
    return svc.build_camp_forecast(db, camp, min(max(hours, 2.0), 12.0))


# ---------------------------------------------------------------- 4. donor response ------------
@router.get("/response-prediction/{request_id}")
def response_prediction(request_id: int, db: Session = Depends(get_db), account=Depends(get_current_any_account)):
    blood_request = _load_request_for(db, request_id, account)
    return svc.response_plan(db, blood_request)


# ---------------------------------------------------------------- 5. voice assistant ------------
class VoiceReplyOut(BaseModel):
    transcript: Optional[str] = None
    intent: str = "unknown"          # request_blood | emergency_numbers | find_donors | question | unknown
    fields: Optional[dict] = None
    reply: str = ""
    language: str = "en"
    note: Optional[str] = None




@router.post("/voice-assistant", response_model=VoiceReplyOut)
async def voice_assistant(
    language: str = Form("en"),
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    account=Depends(get_current_any_account),
):
    """
    Speak (or type) in Urdu, Sindhi or English. The AI works out what you want, fills in blood-request
    fields when you are asking for blood, and answers in the same language. The recording is not kept.
    """
    language = language if language in LANGUAGE_NAMES else "en"
    transcript = (text or "").strip()[:800]
    if file is not None and not transcript:
        content = await file.read()
        if len(content) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=400, detail="Recording too large (max 8 MB)")
        transcript = transcribe_audio(content, file.filename or "voice.webm", file.content_type or "audio/webm", language) or ""
        if not transcript:
            return VoiceReplyOut(reply=_FALLBACK_REPLIES[language], language=language,
                                 note="Could not hear that clearly. AI voice may be off, or the recording was too quiet. You can type instead.")
    if not transcript:
        raise HTTPException(status_code=400, detail="Please speak or type something")
    if not is_ai_configured():
        return VoiceReplyOut(transcript=transcript, reply=_FALLBACK_REPLIES[language], language=language, note=NOT_CONFIGURED_MESSAGE)

    role, _ = account
    result = run_voice_assistant(transcript, language, role)
    return VoiceReplyOut(**result)


# ---------------------------------------------------------------- 6. prescription scanner --------
@router.post("/scan-slip")
async def scan_slip(file: UploadFile = File(...), account=Depends(get_current_any_account)):
    """
    Reads a photo of a doctor's slip / prescription / blood requisition form and suggests the request fields.
    The photo is read in memory and thrown away. Nothing is saved until a person confirms the form.
    """
    role, _ = account
    if role not in ("receiver", "hospital", "staff"):
        raise HTTPException(status_code=403, detail="Your account type can't use this feature")
    content = await file.read()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image too large (max 4 MB)")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload a photo (JPG or PNG)")
    result = run_slip_scan(content, file.content_type)
    del content   # nothing about the photo is kept
    return result


# ---------------------------------------------------------------- 7. conversational health check -
class HealthAnswerIn(BaseModel):
    step: str            # age | gender | weight | hemoglobin | last_donation | yes_no
    text: str
    question: Optional[str] = None   # the question that was asked (helps the AI for yes_no)
    language: str = "en"


@router.post("/health-chat/interpret")
def health_chat_interpret(payload: HealthAnswerIn):
    """
    Turns a typed or spoken answer into a value for the eligibility form. Public, because people answer
    this BEFORE they have an account. Simple words are understood without any AI; AI only helps with
    answers the rules could not understand.
    """
    text = (payload.text or "").strip()[:300]
    step = payload.step
    if not text:
        return {"understood": False}
    if step == "age":
        n = logic.extract_number(text)
        return {"understood": n is not None and 0 < n < 121, "value": int(n) if n is not None else None}
    if step == "weight":
        n = logic.extract_number(text)
        return {"understood": n is not None and 20 <= n <= 250, "value": n}
    if step == "hemoglobin":
        if logic.interpret_yes_no(text) is False:
            return {"understood": True, "value": None}
        n = logic.extract_number(text)
        return {"understood": n is not None and 3 <= n <= 25, "value": n}
    if step == "gender":
        g = logic.interpret_gender(text)
        return {"understood": g is not None, "value": g}
    if step == "last_donation":
        kind, value = logic.interpret_last_donation(text)
        return {"understood": kind != "unknown", "value": value, "never": kind == "never"}
    if step == "yes_no":
        answer = logic.interpret_yes_no(text)
        if answer is None and is_ai_configured() and payload.question:
            parsed = ask_ai_for_json(
                "A blood donor is answering a health screening question by voice or text, in Urdu, Sindhi, English or Roman Urdu. "
                'Decide if the answer means YES or NO to the question. Reply {"answer": "yes"|"no"|"unsure"}. If unsure, say unsure.',
                f"Question: {payload.question[:200]}\nAnswer: {text}", max_tokens=40,
            )
            if parsed and parsed.get("answer") in ("yes", "no"):
                answer = parsed["answer"] == "yes"
        return {"understood": answer is not None, "value": answer}
    raise HTTPException(status_code=400, detail="Unknown step")


@router.post("/health-chat/transcribe")
async def health_chat_transcribe(language: str = Form("en"), file: UploadFile = File(...)):
    """A short voice answer for the health chat. Public (people have no account yet), so it is small and only does speech to text."""
    content = await file.read()
    if len(content) > PUBLIC_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="Recording too long. Please keep answers short.")
    transcript = transcribe_audio(content, file.filename or "voice.webm", file.content_type or "audio/webm", language)
    if not transcript:
        raise HTTPException(status_code=503, detail="Could not hear that. Please tap Yes or No, or type.")
    return {"transcript": transcript}
