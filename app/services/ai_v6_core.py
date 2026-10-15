"""
The AI work behind the voice assistant and the doctor-slip scanner, as plain functions (no web framework),
so the FastAPI routes and the Streamlit app share exactly the same logic.
"""
import base64
from typing import Dict

from app.services import insight_logic as logic
from app.services.ai_client import (
    NOT_CONFIGURED_MESSAGE, ask_ai_for_json, ask_ai_vision_json, is_ai_configured,
)

LANGUAGE_NAMES = {"en": "English", "ur": "Urdu", "sd": "Sindhi"}

FALLBACK_REPLIES = {
    "en": "I could not understand that. Please try again, or type it.",
    "ur": "میں سمجھ نہیں سکا۔ براہ کرم دوبارہ بولیں یا لکھ دیں۔",
    "sd": "مان سمجهي نه سگهيس. مهرباني ڪري ٻيهر ڳالهايو يا لکي ڏيو.",
}


def run_voice_assistant(transcript: str, language: str, role: str) -> Dict:
    """transcript -> {transcript, intent, fields, reply, language, note}. Never raises."""
    language = language if language in LANGUAGE_NAMES else "en"
    if not is_ai_configured():
        return {"transcript": transcript, "intent": "unknown", "fields": None, "reply": FALLBACK_REPLIES[language],
                "language": language, "note": NOT_CONFIGURED_MESSAGE}
    prompt = (
        "You are the voice assistant of LifeFlow, a blood-donation app in Pakistan. The person may speak Urdu, Sindhi, "
        "English or Roman Urdu, possibly in a hurry. Decide what they want.\n"
        'intent is one of: "request_blood" (they need blood), "emergency_numbers" (they want an ambulance or hospital phone number), '
        '"find_donors" (they ask about donors or hospitals nearby), "question" (a general question about donating or the app), "unknown".\n'
        "For request_blood fill fields: blood_type_needed (one of A+ A- B+ B- AB+ AB- O+ O-, or null), units_needed (whole number, null if not said), "
        "patient_name, patient_age, patient_gender (Male/Female/Other), medical_reason, urgency_type (emergency/days/months), urgency_value, "
        "hospital_name. Use null for anything not said. Never guess a blood type.\n"
        f"reply: ONE or TWO short sentences in {LANGUAGE_NAMES[language]} (the person's chosen language), spoken-style, no emojis, no markdown. "
        "For request_blood say what you understood and ask them to check the form. For question give a safe, short answer; never give medical diagnoses. "
        f"The person's account type is {role}.\n"
        'Return JSON: {"intent": ..., "fields": {...} or null, "reply": "..."}'
    )
    parsed = ask_ai_for_json(prompt, transcript, max_tokens=500) or {}
    intent = parsed.get("intent") if parsed.get("intent") in ("request_blood", "emergency_numbers", "find_donors", "question") else "unknown"
    fields = logic.clean_request_fields(parsed.get("fields") or {}) if intent == "request_blood" else None
    reply = str(parsed.get("reply") or "").strip() or FALLBACK_REPLIES[language]
    return {"transcript": transcript, "intent": intent, "fields": fields, "reply": reply, "language": language, "note": None}


def run_slip_scan(image_bytes: bytes, content_type: str) -> Dict:
    """Photo of a doctor slip -> suggested request fields plus warnings. Never raises, never stores the image."""
    if not is_ai_configured():
        return {"read_ok": False, "fields": None, "warnings": [], "note": NOT_CONFIGURED_MESSAGE}
    result = ask_ai_vision_json(
        "You read photos of doctor slips, prescriptions and blood requisition forms (English or Urdu, often handwritten). "
        "Never guess something you cannot read. Do not copy phone numbers or addresses.",
        'Reply as {"is_medical_document": true/false, "legible": true/false, "blood_type_needed": "A+|A-|B+|B-|AB+|AB-|O+|O-|null", '
        '"units_needed": number or null, "patient_name": string or null, "patient_age": number or null, "patient_gender": "Male|Female|Other|null", '
        '"medical_reason": short phrase or null, "hospital_name": string or null, "urgency_type": "emergency|days|months|null", "urgency_value": number or null, '
        '"doctor_name": string or null}. Blood units may be written as "2 bags", "2 units", "2 pint".',
        base64.b64encode(image_bytes).decode(), content_type or "image/jpeg",
    )
    if not result:
        return {"read_ok": False, "fields": None, "warnings": [],
                "note": "Could not read this photo. Try a clearer, brighter picture, or fill the form by hand."}
    if result.get("is_medical_document") is False:
        return {"read_ok": False, "fields": None, "warnings": [],
                "note": "This does not look like a doctor slip or blood requisition. Please try another photo."}
    fields = logic.clean_request_fields(result)
    warnings = []
    if not result.get("legible", True):
        warnings.append("The writing was hard to read. Check every field carefully.")
    if not fields["blood_type_needed"]:
        warnings.append("No clear blood group was found. Please choose it yourself.")
    if fields["units_needed"] is None:
        warnings.append("The number of bags was not found. Please enter it.")
    if fields["blood_type_needed"] and fields["units_needed"] and fields["units_needed"] >= 6:
        warnings.append("This asks for many bags. Please double-check the number.")
    return {"read_ok": True, "fields": fields, "warnings": warnings,
            "doctor_name": str(result.get("doctor_name"))[:60] if result.get("doctor_name") else None,
            "note": "Please check every field. The photo was not saved."}
