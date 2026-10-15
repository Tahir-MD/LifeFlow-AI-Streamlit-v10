from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.models.admin import Admin
from app.models.staff import Staff
from app.schemas.donor_schema import DonorCreate, DonorOut, DonorLogin
from app.schemas.hospital_schema import HospitalCreate, HospitalOut, HospitalLogin
from app.schemas.receiver_schema import ReceiverCreate, ReceiverOut, ReceiverLogin
from app.schemas.admin_schema import AdminLogin
from app.schemas.staff_schema import StaffLogin
from app.utils.security import hash_password, verify_password, create_access_token, decode_access_token
from app.utils.totp import verify_totp
from app.utils.location import geocode_place, build_address_label
from app.services.eligibility_service import evaluate_eligibility
from app.services.otp_service import require_phone_token
from app.services.referral_service import new_referral_code
from datetime import datetime

router = APIRouter(prefix="/auth", tags=["Authentication"])

TWO_FA_PENDING_EXPIRE_MINUTES = 5
TWO_FA_MODELS = {"hospital": Hospital, "admin": Admin}


def _coordinates_for(data) -> tuple:
    """Uses the map position if the form sent one; otherwise looks the place up from the words."""
    if data.latitude is not None and data.longitude is not None:
        return data.latitude, data.longitude
    found = geocode_place(data.village, data.area, data.city, data.state, data.country)
    if not found:
        raise HTTPException(
            status_code=422,
            detail="We could not find this place on the map. Please check the spelling or tap your place on the map.",
        )
    return found


def _place_fields(data) -> dict:
    latitude, longitude = _coordinates_for(data)
    return dict(
        village=data.village, area=data.area, city=data.city, state=data.state, country=data.country,
        latitude=latitude, longitude=longitude,
    )


def _login_response(role: str, account) -> dict:
    """
    Normal path: issues a real access token straight away.
    2FA path (hospital/admin only, and only once they've turned it on):
    issues a short-lived, role-scoped "pending" token instead, which is
    only useful at /auth/login/2fa-verify and nowhere else in the API.
    """
    if role in TWO_FA_MODELS and getattr(account, "two_factor_enabled", False):
        pending_token = create_access_token(
            {"sub": str(account.id), "role": role, "stage": "2fa_pending"},
            expires_minutes=TWO_FA_PENDING_EXPIRE_MINUTES,
        )
        return {"requires_2fa": True, "temp_token": pending_token}

    token = create_access_token({"sub": str(account.id), "role": role})
    return {"access_token": token, "token_type": "bearer", "requires_2fa": False}


@router.post("/register/donor", response_model=DonorOut, status_code=status.HTTP_201_CREATED)
def register_donor(donor_data: DonorCreate, db: Session = Depends(get_db)):
    existing = db.query(Donor).filter(Donor.email == donor_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    proof = require_phone_token(donor_data.phone_token, donor_data.phone_number, donor_data.email)

    # The health questionnaire is checked again here: the server never trusts the browser.
    answers = donor_data.eligibility.model_dump()
    verdict = evaluate_eligibility(answers)
    if not verdict["eligible"]:
        reasons = " ".join(r["message"] for r in verdict["reasons"])
        when = f" You can try again after {verdict['retry_after_date']}." if verdict["retry_after_date"] else ""
        raise HTTPException(status_code=422, detail=f"You cannot register as a donor right now. {reasons}{when}")

    referrer_id = None
    if donor_data.referral_code:
        referrer = db.query(Donor).filter(Donor.referral_code == donor_data.referral_code.strip().upper()).first()
        referrer_id = referrer.id if referrer else None  # a wrong code is ignored, it never blocks sign-up

    last_donation = None
    if answers.get("last_donation_date"):
        try:
            last_donation = datetime.strptime(answers["last_donation_date"][:10], "%Y-%m-%d")
        except ValueError:
            last_donation = None

    new_donor = Donor(
        full_name=donor_data.full_name,
        email=donor_data.email,
        hashed_password=hash_password(donor_data.password),
        blood_type=donor_data.blood_type,
        phone_number=donor_data.phone_number,
        age=answers["age"],
        gender=answers["gender"].lower(),
        weight_kg=answers["weight_kg"],
        eligibility_checked_at=datetime.utcnow(),
        last_donation_date=last_donation,
        phone_verified=(proof == "phone"),
        email_verified=(proof == "email"),
        referral_code=new_referral_code(db),
        referred_by_id=referrer_id,
        **_place_fields(donor_data),
    )
    db.add(new_donor)
    db.commit()
    db.refresh(new_donor)
    return new_donor


@router.post("/register/hospital", response_model=HospitalOut, status_code=status.HTTP_201_CREATED)
def register_hospital(hospital_data: HospitalCreate, db: Session = Depends(get_db)):
    existing = db.query(Hospital).filter(Hospital.email == hospital_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    if db.query(Hospital).filter(Hospital.license_number == hospital_data.license_number).first():
        raise HTTPException(status_code=400, detail="A hospital with this license number is already registered")

    proof = require_phone_token(hospital_data.phone_token, hospital_data.phone_number, hospital_data.email)

    new_hospital = Hospital(
        phone_verified=(proof == "phone"),
        email_verified=(proof == "email"),
        name=hospital_data.name,
        email=hospital_data.email,
        hashed_password=hash_password(hospital_data.password),
        license_number=hospital_data.license_number,
        phone_number=hospital_data.phone_number,
        **_place_fields(hospital_data),
    )
    db.add(new_hospital)
    db.commit()
    db.refresh(new_hospital)
    return new_hospital


@router.post("/register/receiver", response_model=ReceiverOut, status_code=status.HTTP_201_CREATED)
def register_receiver(receiver_data: ReceiverCreate, db: Session = Depends(get_db)):
    existing = db.query(Receiver).filter(Receiver.email == receiver_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    proof = require_phone_token(receiver_data.phone_token, receiver_data.phone_number, receiver_data.email)

    new_receiver = Receiver(
        phone_verified=(proof == "phone"),
        email_verified=(proof == "email"),
        full_name=receiver_data.full_name,
        email=receiver_data.email,
        hashed_password=hash_password(receiver_data.password),
        phone_number=receiver_data.phone_number,
        cnic_number=receiver_data.cnic_number,
        address=", ".join(p for p in (receiver_data.address, build_address_label(
            receiver_data.village, receiver_data.area, receiver_data.city, receiver_data.state, receiver_data.country)) if p),
        patient_name=receiver_data.patient_name,
        **_place_fields(receiver_data),
    )
    db.add(new_receiver)
    db.commit()
    db.refresh(new_receiver)
    return new_receiver


@router.post("/login/donor")
def login_donor(login_data: DonorLogin, db: Session = Depends(get_db)):
    donor = db.query(Donor).filter(Donor.email == login_data.email).first()
    if not donor or not verify_password(login_data.password, donor.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = create_access_token({"sub": str(donor.id), "role": "donor"})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/login/hospital")
def login_hospital(login_data: HospitalLogin, db: Session = Depends(get_db)):
    hospital = db.query(Hospital).filter(Hospital.email == login_data.email).first()
    if not hospital or not verify_password(login_data.password, hospital.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    return _login_response("hospital", hospital)


@router.post("/login/receiver")
def login_receiver(login_data: ReceiverLogin, db: Session = Depends(get_db)):
    receiver = db.query(Receiver).filter(Receiver.email == login_data.email).first()
    if not receiver or not verify_password(login_data.password, receiver.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = create_access_token({"sub": str(receiver.id), "role": "receiver"})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/login/admin")
def login_admin(login_data: AdminLogin, db: Session = Depends(get_db)):
    admin = db.query(Admin).filter(Admin.email == login_data.email).first()
    if not admin or not verify_password(login_data.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    return _login_response("admin", admin)


@router.post("/login/staff")
def login_staff(login_data: StaffLogin, db: Session = Depends(get_db)):
    staff = db.query(Staff).filter(Staff.email == login_data.email).first()
    if not staff or not verify_password(login_data.password, staff.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = create_access_token({"sub": str(staff.id), "role": "staff"})
    return {"access_token": token, "token_type": "bearer"}


class TwoFactorVerifyIn(BaseModel):
    temp_token: str
    code: str


@router.post("/login/2fa-verify")
def login_2fa_verify(payload: TwoFactorVerifyIn, db: Session = Depends(get_db)):
    """Step 2 of login for an account with 2FA turned on: exchange the temp token + a 6-digit code for a real access token."""
    claims = decode_access_token(payload.temp_token)
    if not claims or claims.get("stage") != "2fa_pending" or claims.get("role") not in TWO_FA_MODELS:
        raise HTTPException(status_code=401, detail="This login attempt has expired. Please log in again.")

    role = claims["role"]
    account = db.query(TWO_FA_MODELS[role]).filter(TWO_FA_MODELS[role].id == int(claims["sub"])).first()
    if not account or not account.totp_secret or not verify_totp(account.totp_secret, payload.code):
        raise HTTPException(status_code=401, detail="Incorrect or expired authentication code")

    token = create_access_token({"sub": str(account.id), "role": role})
    return {"access_token": token, "token_type": "bearer", "requires_2fa": False}
