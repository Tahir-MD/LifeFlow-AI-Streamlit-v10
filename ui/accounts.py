"""Sign-in state and account creation. Mirrors the rules of the web API (backend/app/routes/auth_routes.py)."""
from datetime import datetime
from typing import Optional

import streamlit as st
from fastapi import HTTPException

from app.models.admin import Admin
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.models.staff import Staff
from app.schemas.donor_schema import DonorCreate
from app.schemas.hospital_schema import HospitalCreate
from app.schemas.receiver_schema import ReceiverCreate
from app.services.eligibility_service import evaluate_eligibility
from app.services.referral_service import new_referral_code
from app.utils.location import build_address_label, geocode_place
from app.utils.security import hash_password, verify_password
from app.utils.totp import verify_totp

MODELS = {"donor": Donor, "receiver": Receiver, "hospital": Hospital, "staff": Staff, "admin": Admin}
ROLE_LABELS = {"donor": "Donor", "receiver": "Patient / family", "hospital": "Hospital", "staff": "Hospital staff", "admin": "Admin"}


# ------------------------------------------------------------------ session
def current() -> Optional[dict]:
    return st.session_state.get("auth")


def role() -> Optional[str]:
    auth = current()
    return auth["role"] if auth else None


def sign_out() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def display_name(account) -> str:
    return getattr(account, "full_name", None) or getattr(account, "name", None) or "Account"


def acting_hospital(db):
    """The hospital the signed-in person acts for: the hospital itself, or the hospital a staff member works at."""
    auth = current()
    if not auth:
        return None
    if auth["role"] == "hospital":
        return db.query(Hospital).filter(Hospital.id == auth["id"]).first()
    if auth["role"] == "staff":
        staff = db.query(Staff).filter(Staff.id == auth["id"]).first()
        return db.query(Hospital).filter(Hospital.id == staff.hospital_id).first() if staff else None
    return None


def staff_can(db, permission: str) -> bool:
    """True for a hospital login, or for a staff member whose role allows this permission."""
    from app.utils.permissions import can
    auth = current()
    if not auth:
        return False
    if auth["role"] == "hospital":
        return True
    if auth["role"] == "staff":
        staff = db.query(Staff).filter(Staff.id == auth["id"]).first()
        return bool(staff and can(staff.role, permission))
    return False


def load(db):
    """The signed-in person's database row (fresh each page run), or None."""
    auth = current()
    if not auth:
        return None
    return db.query(MODELS[auth["role"]]).filter(MODELS[auth["role"]].id == auth["id"]).first()


# ------------------------------------------------------------------ sign in
def sign_in(db, role_name: str, email: str, password: str, code: str = "") -> str:
    """Returns "" on success, or a message to show. Hospital and admin accounts with 2FA must give the 6-digit code."""
    model = MODELS[role_name]
    account = db.query(model).filter(model.email == (email or "").strip().lower()).first()
    if not account:
        account = db.query(model).filter(model.email == (email or "").strip()).first()
    if not account or not verify_password(password or "", account.hashed_password):
        return "Incorrect email or password."
    if getattr(account, "two_factor_enabled", False):
        if not account.totp_secret or not verify_totp(account.totp_secret, (code or "").strip()):
            return "This account uses two-step verification. Enter the current 6-digit code from your authenticator app."
    st.session_state["auth"] = {"role": role_name, "id": account.id, "name": display_name(account)}
    return ""


# ------------------------------------------------------------------ places and phone
COUNTRY_CODES = [
    ("Pakistan", "+92"), ("India", "+91"), ("Afghanistan", "+93"), ("Bangladesh", "+880"), ("United Arab Emirates", "+971"),
    ("Saudi Arabia", "+966"), ("Qatar", "+974"), ("Oman", "+968"), ("Kuwait", "+965"), ("United Kingdom", "+44"),
    ("United States / Canada", "+1"), ("Turkey", "+90"), ("China", "+86"), ("Malaysia", "+60"),
]


def full_phone(code: str, number: str) -> str:
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    if digits.startswith("0"):
        digits = digits[1:]
    return f"{code} {digits}" if digits else ""


def place_with_coordinates(place: dict) -> dict:
    """Adds latitude/longitude by looking the words up on the map. Raises HTTPException if the place is not found."""
    place = dict(place)
    if place.get("latitude") is None or place.get("longitude") is None:
        found = geocode_place(place.get("village"), place.get("area"), place.get("city"), place.get("state"), place.get("country"))
        if not found:
            raise HTTPException(status_code=422, detail="We could not find this place on the map. Check the spelling, or type the coordinates under 'I know my coordinates'.")
        place["latitude"], place["longitude"] = found
    return place


def _place_columns(place: dict) -> dict:
    return {k: place.get(k) for k in ("village", "area", "city", "state", "country", "latitude", "longitude")}


# ------------------------------------------------------------------ registration
def check_proof(phone_token: str, phone_number: str, email: str) -> None:
    """When code verification is switched on, the sign-up needs a proof token made for this phone number or email."""
    from ui import otp
    if phone_token and phone_token != "streamlit":
        from app.services.otp_service import require_phone_token
        require_phone_token(phone_token, phone_number, email)
    elif otp.required():
        raise HTTPException(status_code=400, detail="Please verify your phone number or email with the code we send you.")


def register_donor(db, data: dict, answers: dict, phone_token: str = "streamlit") -> Donor:
    """data: full_name, email, password, blood_type, phone_number + place fields. answers: the health questionnaire."""
    place = place_with_coordinates(data["place"])
    payload = DonorCreate(
        full_name=data["full_name"], email=data["email"], password=data["password"], blood_type=data["blood_type"],
        phone_number=data["phone_number"], eligibility=answers, phone_token=phone_token or "streamlit", referral_code=data.get("referral_code") or None,
        **_place_columns(place),
    )
    check_proof(phone_token, payload.phone_number, str(payload.email))
    if db.query(Donor).filter(Donor.email == payload.email).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    clean = payload.eligibility.model_dump()
    verdict = evaluate_eligibility(clean)
    if not verdict["eligible"]:
        reasons = " ".join(r["message"] for r in verdict["reasons"])
        when = f" You can try again after {verdict['retry_after_date']}." if verdict["retry_after_date"] else ""
        raise HTTPException(status_code=422, detail=f"You cannot register as a donor right now. {reasons}{when}")
    referrer_id = None
    if payload.referral_code:
        referrer = db.query(Donor).filter(Donor.referral_code == payload.referral_code.strip().upper()).first()
        referrer_id = referrer.id if referrer else None
    last = None
    if clean.get("last_donation_date"):
        try:
            last = datetime.strptime(clean["last_donation_date"][:10], "%Y-%m-%d")
        except ValueError:
            last = None
    donor = Donor(
        full_name=payload.full_name, email=payload.email, hashed_password=hash_password(payload.password),
        blood_type=payload.blood_type, phone_number=payload.phone_number, age=clean["age"], gender=clean["gender"].lower(),
        weight_kg=clean["weight_kg"], eligibility_checked_at=datetime.utcnow(), last_donation_date=last,
        referral_code=new_referral_code(db), referred_by_id=referrer_id, **_place_columns(place),
    )
    db.add(donor)
    db.commit()
    db.refresh(donor)
    return donor


def register_hospital(db, data: dict, phone_token: str = "streamlit") -> Hospital:
    place = place_with_coordinates(data["place"])
    payload = HospitalCreate(
        name=data["name"], email=data["email"], password=data["password"], license_number=data["license_number"],
        phone_number=data["phone_number"], phone_token=phone_token or "streamlit", **_place_columns(place),
    )
    check_proof(phone_token, payload.phone_number, str(payload.email))
    if db.query(Hospital).filter(Hospital.email == payload.email).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    if db.query(Hospital).filter(Hospital.license_number == payload.license_number).first():
        raise HTTPException(status_code=400, detail="A hospital with this license number is already registered")
    hospital = Hospital(
        name=payload.name, email=payload.email, hashed_password=hash_password(payload.password),
        license_number=payload.license_number, phone_number=payload.phone_number, **_place_columns(place),
    )
    db.add(hospital)
    db.commit()
    db.refresh(hospital)
    return hospital


def register_receiver(db, data: dict, phone_token: str = "streamlit") -> Receiver:
    place = place_with_coordinates(data["place"])
    payload = ReceiverCreate(
        full_name=data["full_name"], email=data["email"], password=data["password"], phone_number=data["phone_number"],
        cnic_number=data["cnic_number"], address=data.get("address") or None, patient_name=data.get("patient_name") or None,
        phone_token=phone_token or "streamlit", **_place_columns(place),
    )
    check_proof(phone_token, payload.phone_number, str(payload.email))
    if db.query(Receiver).filter(Receiver.email == payload.email).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    label = build_address_label(payload.village, payload.area, payload.city, payload.state, payload.country)
    receiver = Receiver(
        full_name=payload.full_name, email=payload.email, hashed_password=hash_password(payload.password),
        phone_number=payload.phone_number, cnic_number=payload.cnic_number,
        address=", ".join(p for p in (payload.address, label) if p), patient_name=payload.patient_name, **_place_columns(place),
    )
    db.add(receiver)
    db.commit()
    db.refresh(receiver)
    return receiver
