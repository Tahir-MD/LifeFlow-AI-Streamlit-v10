"""
Ambulance and emergency contacts directory.

Anyone can read it (no login: in an emergency nobody should have to sign in). The admin can add,
approve and remove entries. A hospital can add its own ambulance or blood-bank number; it is shown
straight away for a verified hospital, and waits for the admin otherwise.
National numbers are added automatically the first time the server starts.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models.emergency_contact import CATEGORIES, EmergencyContact
from app.models.hospital import Hospital
from app.utils.dependencies import get_current_admin, get_current_any_account, get_current_hospital
from app.models.admin import Admin
from app.utils.validators import validate_phone_loose

router = APIRouter(prefix="/directory", tags=["Emergency directory"])

# Well-known national numbers. Coverage differs between cities, so the screen tells people to
# confirm the number works where they live. The admin can edit or remove any of them.
SEED = [
    ("Rescue 1122 (ambulance and rescue)", "ambulance", "1122", "Rescue service in many cities of Pakistan. Check that it covers your district."),
    ("Edhi Foundation ambulance", "ambulance", "115", "Edhi ambulance and emergency helpline."),
    ("Chhipa Welfare ambulance", "ambulance", "1020", "Mainly Karachi and some other cities."),
    ("Aman Foundation ambulance", "ambulance", "1021", "Mainly Karachi."),
    ("Police emergency", "police", "15", "Police emergency number."),
    ("Fire brigade", "fire", "16", "Fire brigade emergency number."),
    ("Motorway police", "police", "130", "For motorways and national highways."),
    ("Madadgar helpline (women and children)", "helpline", "1098", "National helpline for women and children in trouble."),
]


def seed_directory() -> None:
    """Adds the national numbers once, when the table is empty."""
    db = SessionLocal()
    try:
        if db.query(EmergencyContact).count() == 0:
            for name, category, phone, notes in SEED:
                db.add(EmergencyContact(
                    name=name, category=category, phone_number=phone, notes=notes,
                    is_24h=True, is_national=True, is_approved=True, added_by_type="seed",
                ))
            db.commit()
    finally:
        db.close()


class ContactIn(BaseModel):
    name: str
    category: str
    phone_number: str
    city: Optional[str] = None
    area: Optional[str] = None
    notes: Optional[str] = None
    is_24h: bool = True
    is_national: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = " ".join((v or "").split())
        if len(v) < 3 or len(v) > 80:
            raise ValueError("Name must have 3 to 80 letters.")
        return v

    @field_validator("category")
    @classmethod
    def _category(cls, v):
        if v not in CATEGORIES:
            raise ValueError("Choose a valid type.")
        return v

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v):
        return validate_phone_loose(v)

    @field_validator("city", "area", "notes")
    @classmethod
    def _text(cls, v):
        v = " ".join((v or "").split())
        return v[:200] if v else None


class ContactOut(BaseModel):
    id: int
    name: str
    category: str
    phone_number: str
    city: Optional[str] = None
    area: Optional[str] = None
    notes: Optional[str] = None
    is_24h: bool
    is_national: bool
    is_approved: bool
    added_by_type: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("", response_model=List[ContactOut])
def list_contacts(
    category: Optional[str] = None, city: Optional[str] = None, q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Approved entries. National numbers always appear; local ones are filtered by city if one is given."""
    query = db.query(EmergencyContact).filter(EmergencyContact.is_approved == True)  # noqa: E712
    if category:
        query = query.filter(EmergencyContact.category == category)
    rows = query.order_by(EmergencyContact.is_national.desc(), EmergencyContact.category, EmergencyContact.name).limit(500).all()
    if city:
        wanted = city.strip().lower()
        rows = [r for r in rows if r.is_national or not r.city or wanted in (r.city or "").lower()]
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in r.name.lower() or needle in (r.area or "").lower() or needle in (r.city or "").lower()]
    return rows


@router.post("", response_model=ContactOut, status_code=201)
def add_contact(payload: ContactIn, db: Session = Depends(get_db), who=Depends(get_current_any_account)):
    role, account_id = who
    if role not in ("admin", "hospital"):
        raise HTTPException(status_code=403, detail="Only the admin and hospitals can add contacts.")
    approved = role == "admin"
    if role == "hospital":
        hospital = db.query(Hospital).filter(Hospital.id == account_id).first()
        approved = bool(hospital and hospital.is_verified)
        if db.query(EmergencyContact).filter(EmergencyContact.added_by_type == "hospital",
                                             EmergencyContact.added_by_id == account_id).count() >= 20:
            raise HTTPException(status_code=400, detail="A hospital can add at most 20 contacts.")
    contact = EmergencyContact(**payload.model_dump(), is_approved=approved, added_by_type=role, added_by_id=account_id)
    if role == "hospital":
        contact.is_national = False   # only the admin can publish a national number
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.get("/mine", response_model=List[ContactOut])
def my_contacts(db: Session = Depends(get_db), hospital: Hospital = Depends(get_current_hospital)):
    return db.query(EmergencyContact).filter(
        EmergencyContact.added_by_type == "hospital", EmergencyContact.added_by_id == hospital.id,
    ).order_by(EmergencyContact.id.desc()).all()


@router.get("/pending", response_model=List[ContactOut])
def pending_contacts(db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    return db.query(EmergencyContact).filter(EmergencyContact.is_approved == False).order_by(EmergencyContact.id.desc()).all()  # noqa: E712


@router.post("/{contact_id}/approve", response_model=ContactOut)
def approve_contact(contact_id: int, db: Session = Depends(get_db), _admin: Admin = Depends(get_current_admin)):
    contact = db.query(EmergencyContact).filter(EmergencyContact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    contact.is_approved = True
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: int, db: Session = Depends(get_db), who=Depends(get_current_any_account)):
    role, account_id = who
    contact = db.query(EmergencyContact).filter(EmergencyContact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    owner = role == "hospital" and contact.added_by_type == "hospital" and contact.added_by_id == account_id
    if role != "admin" and not owner:
        raise HTTPException(status_code=403, detail="You can only remove your own contacts.")
    db.delete(contact)
    db.commit()
