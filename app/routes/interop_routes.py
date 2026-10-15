"""
Interoperability + low-connectivity access:

* /interop/fhir/...   -- hospital blood inventory exposed as HL7 FHIR R4 resources (conceptual mapping)
* /sms/inbound        -- text-message interface (Twilio-style webhook) for people with no data/app access
"""
from datetime import datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest
from app.services.matching_service import COMPATIBLE_DONOR_TYPES
from app.routes.request_routes import _try_fulfill_from_hospital_stock, _notify_matching_donors
from app.services.audit_service import record_event

router = APIRouter(tags=["Interoperability & SMS"])

BLOOD_TYPES = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]


@router.get("/interop/fhir/inventory/{hospital_id}")
def fhir_inventory(hospital_id: int, db: Session = Depends(get_db)):
    """Blood inventory as a FHIR R4 Bundle of SupplyDelivery-style Basic resources."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    rows = db.query(BloodInventory).filter(BloodInventory.hospital_id == hospital_id).all()
    return {
        "resourceType": "Bundle", "type": "collection", "timestamp": datetime.utcnow().isoformat() + "Z",
        "entry": [
            {"resource": {
                "resourceType": "Basic",
                "id": f"lifeflow-inv-{hospital_id}-{row.blood_type}",
                "code": {"coding": [{"system": "https://lifeflow.app/fhir/codes", "code": "blood-inventory",
                                     "display": "Blood bank inventory"}]},
                "subject": {"display": hospital.name},
                "extension": [
                    {"url": "https://lifeflow.app/fhir/blood-type", "valueString": row.blood_type},
                    {"url": "https://lifeflow.app/fhir/units-available", "valueInteger": row.units_available},
                    {"url": "https://lifeflow.app/fhir/low-stock-threshold", "valueInteger": row.low_stock_threshold},
                ],
            }} for row in rows
        ],
    }


def _twiml(message: str) -> Response:
    return Response(content=f"<?xml version='1.0' encoding='UTF-8'?><Response><Message>{escape(message)}</Message></Response>",
                    media_type="application/xml")


def _tail(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits[-9:]


@router.post("/sms/inbound")
def sms_inbound(From: str = Form(...), Body: str = Form(...), db: Session = Depends(get_db)):
    """
    Point a Twilio number's "incoming message" webhook here. Commands (case-insensitive):
      HELP                 -> list commands
      STOCK O+             -> nearby hospitals holding that blood type
      OPEN                 -> (registered donors) open requests you can fill, with contact numbers
      NEED O+ 2            -> (registered hospitals) raise an emergency request for 2 bags
    """
    parts = Body.strip().upper().split()
    command = parts[0] if parts else "HELP"
    sender = _tail(From)

    if command == "STOCK" and len(parts) >= 2 and parts[1] in BLOOD_TYPES:
        rows = (db.query(BloodInventory, Hospital).join(Hospital, Hospital.id == BloodInventory.hospital_id)
                .filter(BloodInventory.blood_type == parts[1], BloodInventory.units_available > 0).all())
        if not rows:
            return _twiml(f"No hospital currently reports {parts[1]} in stock.")
        return _twiml(f"{parts[1]} in stock: " + "; ".join(f"{h.name} {i.units_available} bags, tel {h.phone_number}" for i, h in rows[:5]))

    if command == "OPEN":
        donor = next((d for d in db.query(Donor).all() if _tail(d.phone_number) == sender), None)
        if not donor:
            return _twiml("This number isn't registered as a donor. Register in the LifeFlow app first.")
        wanted = [t for t, givers in COMPATIBLE_DONOR_TYPES.items() if donor.blood_type in givers]
        open_reqs = db.query(BloodRequest).filter(BloodRequest.status == "open", BloodRequest.blood_type_needed.in_(wanted)).limit(3).all()
        if not open_reqs:
            return _twiml("No open requests match your blood type right now. Thank you for being a donor!")
        from app.routes.request_routes import build_request_out
        lines = []
        for r in open_reqs:
            out = build_request_out(db, r)
            lines.append(f"#{r.id} {r.blood_type_needed} x{out.units_remaining} at {out.requester_name}, tel {out.requester_phone}")
        return _twiml("Open requests: " + " | ".join(lines))

    if command == "NEED" and len(parts) >= 3 and parts[1] in BLOOD_TYPES and parts[2].isdigit():
        hospital = next((h for h in db.query(Hospital).all() if _tail(h.phone_number) == sender), None)
        if not hospital:
            return _twiml("Only registered hospital phone numbers can raise requests by SMS.")
        new_request = BloodRequest(
            requester_type="hospital", requester_id=hospital.id, blood_type_needed=parts[1],
            units_needed=int(parts[2]), urgency_type="emergency", latitude=hospital.latitude, longitude=hospital.longitude,
        )
        db.add(new_request); db.commit(); db.refresh(new_request)
        record_event(db, "request_created_via_sms", actor_type="hospital", actor_id=hospital.id,
                     payload={"request_id": new_request.id, "blood_type": parts[1], "units_needed": int(parts[2])})
        _try_fulfill_from_hospital_stock(db, new_request, hospital.name)
        _notify_matching_donors(db, new_request, hospital.name)
        remaining = new_request.units_needed - new_request.units_fulfilled
        return _twiml(f"Request #{new_request.id} created. {new_request.inventory_units_used or 0} bag(s) covered from stock; "
                      f"{remaining} bag(s) sent to nearby donors.")

    return _twiml("LifeFlow SMS: STOCK O+ | OPEN (donors) | NEED O+ 2 (hospitals)")
