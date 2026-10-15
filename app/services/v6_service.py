"""
Database-backed parts of the v6 AI features: weekly report, ETA suggestions, camp predictor and donor
response ranking. The formulas themselves live in insight_logic.py (no database, easy to test).
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.blood_batch import BloodBatch
from app.models.camp import CampRSVP, DonationCamp
from app.models.donation import Donation
from app.models.donor import Donor
from app.models.emergency_contact import EmergencyContact
from app.models.hospital import Hospital
from app.models.inventory import BloodInventory
from app.models.notification import Notification
from app.models.receiver import Receiver
from app.models.request import BloodRequest
from app.models.weekly_report import WeeklyReport
from app.services import insight_logic as logic
from app.services.matching_service import (
    find_hospitals_with_stock, find_matching_donors,
)
from app.utils.distance import calculate_distance_kilometers

LOCAL_UTC_OFFSET_HOURS = float(os.environ.get("LIFEFLOW_UTC_OFFSET_HOURS", "5"))   # Pakistan = UTC+5


def local_hour() -> int:
    return int((datetime.utcnow() + timedelta(hours=LOCAL_UTC_OFFSET_HOURS)).hour)


def maps_link(origin_lat, origin_lng, dest_lat, dest_lng) -> str:
    return (f"https://www.google.com/maps/dir/?api=1&origin={origin_lat},{origin_lng}"
            f"&destination={dest_lat},{dest_lng}&travelmode=driving")


# ============================================================================================
# 1. Weekly report
# ============================================================================================
def _in_period(query, column, start, end):
    return query.filter(column >= start, column < end)


def collect_weekly_stats(db: Session, scope: str, hospital_id: Optional[int], start: datetime, end: datetime) -> Dict:
    """Plain counts for the period. Hospital scope = requests it made or fulfilled, its camps, its blood bank."""
    req_q = _in_period(db.query(BloodRequest), BloodRequest.created_at, start, end)
    if scope == "hospital":
        req_q = req_q.filter(or_(
            (BloodRequest.requester_type == "hospital") & (BloodRequest.requester_id == hospital_id),
            BloodRequest.fulfilling_hospital_id == hospital_id,
        ))
    requests = req_q.all()
    prev_start = start - (end - start)
    prev_q = _in_period(db.query(BloodRequest), BloodRequest.created_at, prev_start, start)
    if scope == "hospital":
        prev_q = prev_q.filter(or_(
            (BloodRequest.requester_type == "hospital") & (BloodRequest.requester_id == hospital_id),
            BloodRequest.fulfilling_hospital_id == hospital_id,
        ))
    previous_count = prev_q.count()

    by_type: Dict[str, int] = {}
    for r in requests:
        by_type[r.blood_type_needed] = by_type.get(r.blood_type_needed, 0) + (r.units_needed or 0)
    top_types = sorted(by_type.items(), key=lambda kv: -kv[1])[:3]

    request_ids = [r.id for r in requests]
    donation_q = _in_period(db.query(Donation), Donation.donated_at, start, end)
    if scope == "hospital":
        donation_q = donation_q.filter(Donation.request_id.in_(request_ids)) if request_ids else donation_q.filter(False)
    donations = donation_q.all()

    inventory_q = db.query(BloodInventory)
    batch_q = db.query(BloodBatch).filter(BloodBatch.state == "active", BloodBatch.units_remaining > 0)
    camp_q = _in_period(db.query(DonationCamp), DonationCamp.camp_date, start, end)
    if scope == "hospital":
        inventory_q = inventory_q.filter(BloodInventory.hospital_id == hospital_id)
        batch_q = batch_q.filter(BloodBatch.hospital_id == hospital_id)
        camp_q = camp_q.filter(DonationCamp.hospital_id == hospital_id)
    low_stock = [
        {"blood_type": row.blood_type, "units": row.units_available, "hospital_id": row.hospital_id}
        for row in inventory_q.all() if (row.units_available or 0) <= (row.low_stock_threshold or 5)
    ]
    soon = (end + timedelta(days=7)).date()
    expiring = [
        {"blood_type": b.blood_type, "units": b.units_remaining, "expires_on": b.expires_on.isoformat()}
        for b in batch_q.filter(BloodBatch.expires_on <= soon).all()
    ]

    camps = camp_q.all()
    camp_rows = []
    for camp in camps:
        rsvps = db.query(CampRSVP).filter(CampRSVP.camp_id == camp.id, CampRSVP.status != "cancelled").all()
        attended = sum(1 for x in rsvps if x.checked_in_at or x.status == "attended")
        camp_rows.append({"title": camp.title, "registered": len(rsvps), "attended": attended})

    new_donors = _in_period(db.query(Donor), Donor.created_at, start, end).count() if scope == "platform" else None
    fulfilled = sum(1 for r in requests if r.status == "fulfilled")
    return {
        "period_start": start.date().isoformat(), "period_end": (end - timedelta(days=1)).date().isoformat(),
        "requests": len(requests), "requests_previous_period": previous_count,
        "fulfilled": fulfilled, "still_open": sum(1 for r in requests if r.status == "open"),
        "emergencies": sum(1 for r in requests if r.urgency_type == "emergency"),
        "sos": sum(1 for r in requests if r.is_sos),
        "flagged": sum(1 for r in requests if (r.review_status or "ok") in ("flagged", "held", "rejected")),
        "units_requested": sum(r.units_needed or 0 for r in requests),
        "units_fulfilled": sum(r.units_fulfilled or 0 for r in requests),
        "units_from_stock": sum(r.inventory_units_used or 0 for r in requests),
        "donations": len(donations), "units_donated": sum(d.units_donated or 0 for d in donations),
        "new_donors": new_donors,
        "top_blood_types": [{"blood_type": k, "units": v} for k, v in top_types],
        "low_stock": low_stock[:12], "expiring_soon": expiring[:12],
        "camps": camp_rows,
    }


def rule_based_narrative(stats: Dict, scope: str) -> str:
    """A short plain summary written from the numbers alone (used when no AI key is set)."""
    lines = []
    req, prev = stats["requests"], stats["requests_previous_period"]
    if prev:
        change = round((req - prev) / prev * 100)
        trend = f"{abs(change)}% {'more' if change > 0 else 'fewer'} than the week before" if change else "the same as the week before"
    else:
        trend = "no earlier week to compare with"
    lines.append(f"From {stats['period_start']} to {stats['period_end']} there were {req} blood request(s), {trend}.")
    if req:
        pct = round(stats["fulfilled"] / req * 100)
        lines.append(f"{stats['fulfilled']} were fully covered ({pct}%), {stats['still_open']} are still open, and {stats['emergencies']} were emergencies.")
        lines.append(f"{stats['units_fulfilled']} of {stats['units_requested']} bags needed were supplied; {stats['units_from_stock']} came straight from hospital stock.")
    if stats["top_blood_types"]:
        lines.append("Most wanted: " + ", ".join(f"{t['blood_type']} ({t['units']} bags)" for t in stats["top_blood_types"]) + ".")
    lines.append(f"{stats['donations']} donation(s) were recorded ({stats['units_donated']} bags).")
    if stats.get("new_donors") is not None:
        lines.append(f"{stats['new_donors']} new donor(s) joined.")
    if stats["low_stock"]:
        lines.append("Low stock: " + ", ".join(sorted({x["blood_type"] for x in stats["low_stock"]})) + ". Consider a camp or a donor message.")
    if stats["expiring_soon"]:
        lines.append(f"{sum(x['units'] for x in stats['expiring_soon'])} bag(s) expire within a week. Use them first or transfer them.")
    if stats["camps"]:
        lines.append("Camps: " + "; ".join(f"{c['title']} ({c['attended']} of {c['registered']} registered came)" for c in stats["camps"]) + ".")
    if stats["flagged"]:
        lines.append(f"{stats['flagged']} request(s) were flagged for review.")
    return " ".join(lines)


def ai_narrative(stats: Dict, scope: str) -> Optional[str]:
    from app.services.ai_client import ask_ai, is_ai_configured
    if not is_ai_configured():
        return None
    reply = ask_ai(
        "You write a short weekly briefing for a blood-donation network manager. Use ONLY the JSON numbers given. "
        "Do not invent figures. Plain words, 5 to 8 short sentences, then 2 bullet-point suggestions starting with '- '.",
        json.dumps(stats), max_tokens=450,
    )
    low = reply.lower()
    if "isn't set up" in low or "hit an error" in low or "couldn't generate" in low:
        return None
    return reply


def generate_weekly_report(db: Session, scope: str, hospital_id: Optional[int] = None, days: int = 7, save: bool = True) -> Dict:
    end = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start = end - timedelta(days=days)
    stats = collect_weekly_stats(db, scope, hospital_id, start, end)
    narrative = ai_narrative(stats, scope)
    source = "ai" if narrative else "rules"
    narrative = narrative or rule_based_narrative(stats, scope)
    row = None
    if save:
        row = WeeklyReport(scope=scope, hospital_id=hospital_id, period_start=start, period_end=end,
                           data_json=json.dumps(stats), narrative=narrative, narrative_source=source)
        db.add(row)
        db.commit()
        db.refresh(row)
    return {"id": row.id if row else None, "scope": scope, "hospital_id": hospital_id, "stats": stats,
            "narrative": narrative, "narrative_source": source,
            "created_at": (row.created_at if row else datetime.utcnow()).isoformat()}


def report_to_dict(row: WeeklyReport) -> Dict:
    return {"id": row.id, "scope": row.scope, "hospital_id": row.hospital_id, "stats": json.loads(row.data_json),
            "narrative": row.narrative, "narrative_source": row.narrative_source, "created_at": row.created_at.isoformat()}


def report_sheets(report: Dict) -> List[Dict]:
    s = report["stats"]
    summary = [
        ["Period", f"{s['period_start']} to {s['period_end']}"],
        ["Blood requests", s["requests"]], ["Previous week", s["requests_previous_period"]],
        ["Fully covered", s["fulfilled"]], ["Still open", s["still_open"]], ["Emergencies", s["emergencies"]],
        ["SOS requests", s["sos"]], ["Flagged for review", s["flagged"]],
        ["Bags requested", s["units_requested"]], ["Bags supplied", s["units_fulfilled"]],
        ["Bags from hospital stock", s["units_from_stock"]], ["Donations", s["donations"]], ["Bags donated", s["units_donated"]],
    ]
    if s.get("new_donors") is not None:
        summary.append(["New donors", s["new_donors"]])
    sheets = [
        {"title": "Summary", "headers": ["Item", "Value"], "rows": summary},
        {"title": "Plain-language summary", "headers": ["Text"], "rows": [[report["narrative"] or ""]]},
        {"title": "Most wanted blood", "headers": ["Blood type", "Bags"], "rows": [[x["blood_type"], x["units"]] for x in s["top_blood_types"]]},
        {"title": "Low stock", "headers": ["Blood type", "Bags"], "rows": [[x["blood_type"], x["units"]] for x in s["low_stock"]]},
        {"title": "Expiring soon", "headers": ["Blood type", "Bags", "Expires on"], "rows": [[x["blood_type"], x["units"], x["expires_on"]] for x in s["expiring_soon"]]},
        {"title": "Camps", "headers": ["Camp", "Registered", "Came"], "rows": [[c["title"], c["registered"], c["attended"]] for c in s["camps"]]},
    ]
    return sheets


def run_weekly_reports_if_due(db: Session) -> int:
    """Called by the hourly background job. Makes one report per scope each week and tells the owners."""
    from app.models.admin import Admin
    from app.utils.notify import notify
    made = 0
    cutoff = datetime.utcnow() - timedelta(days=7) + timedelta(hours=1)

    def due(scope, hospital_id):
        last = (db.query(WeeklyReport).filter(WeeklyReport.scope == scope, WeeklyReport.hospital_id == hospital_id)
                .order_by(WeeklyReport.created_at.desc()).first())
        return last is None or last.created_at < cutoff

    if due("platform", None):
        report = generate_weekly_report(db, "platform")
        for admin in db.query(Admin).all():
            notify(db, "admin", admin.id, "Your weekly LifeFlow report is ready", report["narrative"][:300], category="system")
        db.commit()
        made += 1
    for hospital in db.query(Hospital).all():
        if due("hospital", hospital.id):
            report = generate_weekly_report(db, "hospital", hospital.id)
            notify(db, "hospital", hospital.id, "Your weekly report is ready", report["narrative"][:300], category="system")
            db.commit()
            made += 1
    return made


# ============================================================================================
# 2. Ambulance and ETA suggestions
# ============================================================================================
def _directory_contacts(db: Session, city: Optional[str], category: str, limit: int = 4) -> List[Dict]:
    rows = (db.query(EmergencyContact)
            .filter(EmergencyContact.category == category, EmergencyContact.is_approved == True)  # noqa: E712
            .all())
    city_l = (city or "").strip().lower()
    local = [r for r in rows if city_l and (r.city or "").strip().lower() == city_l]
    national = [r for r in rows if r.is_national or not r.city]
    chosen = (local + [r for r in national if r not in local])[:limit]
    return [{"name": r.name, "phone_number": r.phone_number, "city": r.city, "is_24h": bool(r.is_24h), "notes": r.notes} for r in chosen]


def _requester_city(db: Session, blood_request: BloodRequest) -> Optional[str]:
    if blood_request.requester_type == "hospital":
        owner = db.query(Hospital).filter(Hospital.id == blood_request.requester_id).first()
    else:
        owner = db.query(Receiver).filter(Receiver.id == blood_request.requester_id).first()
    return getattr(owner, "city", None)


def build_eta_plan(db: Session, blood_request: BloodRequest) -> Dict:
    is_emergency = blood_request.urgency_type == "emergency"
    lat, lng = blood_request.latitude, blood_request.longitude

    sources = []
    seen = set()
    for distance, hospital, row in find_hospitals_with_stock(db, blood_request)[:4]:
        seen.add(hospital.id)
        transport = logic.recommend_transport(distance, is_emergency)
        best = next(o for o in transport["options"] if o["mode"] == transport["recommended_mode"]) if transport["recommended_mode"] != "walk" else transport["options"][-1]
        sources.append({
            "hospital_id": hospital.id, "name": hospital.name, "phone_number": hospital.phone_number,
            "has_stock": True, "units_in_stock": row.units_available, "distance_km": distance,
            "recommended_mode": transport["recommended_mode"], "eta_minutes": best["minutes"],
            "eta_text": logic.format_minutes(best["minutes"]), "options": transport["options"],
            "maps_url": maps_link(hospital.latitude, hospital.longitude, lat, lng),
        })
    if len(sources) < 3:
        others = []
        for hospital in db.query(Hospital).all():
            if hospital.id in seen:
                continue
            others.append((calculate_distance_kilometers(lat, lng, hospital.latitude, hospital.longitude), hospital))
        for distance, hospital in sorted(others, key=lambda x: x[0])[: 3 - len(sources)]:
            est = logic.estimate_travel(distance, "ambulance")
            sources.append({
                "hospital_id": hospital.id, "name": hospital.name, "phone_number": hospital.phone_number,
                "has_stock": False, "units_in_stock": 0, "distance_km": round(distance, 1),
                "recommended_mode": "ambulance", "eta_minutes": est["minutes"], "eta_text": logic.format_minutes(est["minutes"]),
                "options": [], "maps_url": maps_link(hospital.latitude, hospital.longitude, lat, lng),
            })

    donors = []
    for match in find_matching_donors(db, blood_request)[:5]:
        donor = db.query(Donor).filter(Donor.id == match.donor_id).first()
        mode = "bike" if match.distance_kilometers <= 8 else "car"
        est = logic.estimate_travel(match.distance_kilometers, mode)
        donors.append({
            "donor_id": match.donor_id, "name": match.full_name, "blood_type": match.blood_type,
            "distance_km": match.distance_kilometers, "mode": mode, "eta_minutes": est["minutes"],
            "eta_text": logic.format_minutes(est["minutes"]),
            "maps_url": maps_link(donor.latitude, donor.longitude, lat, lng) if donor else None,
        })

    stock_best = min((s for s in sources if s["has_stock"]), key=lambda s: s["eta_minutes"], default=None)
    donor_best = min(donors, key=lambda d: d["eta_minutes"], default=None)
    if stock_best and (not donor_best or stock_best["eta_minutes"] <= donor_best["eta_minutes"] + 30):
        advice = (f"Fastest: ask {stock_best['name']} to send {blood_request.blood_type_needed} blood "
                  f"({stock_best['units_in_stock']} bag(s) in stock), about {stock_best['eta_text']} by {stock_best['recommended_mode']}.")
    elif donor_best:
        advice = (f"No stock nearby. Nearest matching donor is {donor_best['name']}, about {donor_best['eta_text']} away. "
                  "Add roughly 45 minutes for screening and donation.")
    else:
        advice = "No stock or matching donor found nearby yet. Call the ambulance and blood-bank numbers below."

    city = _requester_city(db, blood_request)
    return {
        "request_id": blood_request.id, "blood_type": blood_request.blood_type_needed, "is_emergency": is_emergency,
        "advice": advice, "blood_sources": sources, "donors": donors,
        "ambulances": _directory_contacts(db, city, "ambulance"),
        "blood_banks": _directory_contacts(db, city, "blood_bank", 3),
        "assumptions": "Times are estimates from straight-line distance x 1.35 for roads and typical city speeds. "
                       "Open the map link for live traffic.",
    }


# ============================================================================================
# 3. Camp turnout and staffing predictor
# ============================================================================================
def past_show_rate(db: Session, hospital_id: Optional[int]) -> Optional[float]:
    q = db.query(DonationCamp).filter(DonationCamp.camp_date < datetime.utcnow())
    if hospital_id:
        q = q.filter(DonationCamp.hospital_id == hospital_id)
    registered = attended = 0
    for camp in q.all():
        for rsvp in db.query(CampRSVP).filter(CampRSVP.camp_id == camp.id, CampRSVP.status != "cancelled", CampRSVP.walk_in == False).all():  # noqa: E712
            registered += 1
            if rsvp.checked_in_at or rsvp.status == "attended":
                attended += 1
    return round(attended / registered, 2) if registered >= 10 else None


def build_camp_forecast(db: Session, camp: DonationCamp, camp_hours: float = 6.0) -> Dict:
    registered = db.query(CampRSVP).filter(CampRSVP.camp_id == camp.id, CampRSVP.status == "registered").count()
    now = datetime.utcnow()
    nearby = 0
    for donor in db.query(Donor).filter(Donor.is_eligible == True).all():  # noqa: E712
        if donor.deferred_until and donor.deferred_until > now:
            continue
        if calculate_distance_kilometers(camp.latitude, camp.longitude, donor.latitude, donor.longitude) <= 15:
            nearby += 1
    forecast = logic.predict_camp(registered, past_show_rate(db, camp.hospital_id), nearby, camp_hours,
                                  max((camp.camp_date - now).days, 0))
    forecast.update({"camp_id": camp.id, "title": camp.title, "camp_date": camp.camp_date.isoformat(),
                     "registered": registered, "nearby_eligible_donors": nearby})
    return forecast


# ============================================================================================
# 4. Donor response prediction
# ============================================================================================
def rank_by_response(db: Session, blood_request: BloodRequest, matches: list) -> List[Dict]:
    now, hour = datetime.utcnow(), local_hour()
    is_emergency = blood_request.urgency_type == "emergency"
    rows = []
    for m in matches:
        donor = db.query(Donor).filter(Donor.id == m.donor_id).first()
        if not donor:
            continue
        alerts = db.query(Notification).filter(Notification.user_type == "donor", Notification.user_id == donor.id,
                                               Notification.category == "request").count()
        donations = db.query(Donation).filter(Donation.donor_id == donor.id).count()
        days_since = (now - donor.last_donation_date).days if donor.last_donation_date else None
        pred = logic.predict_response(alerts, donations, m.distance_kilometers, days_since, hour, is_emergency, m.average_rating)
        eta = logic.estimate_travel(m.distance_kilometers, "bike" if m.distance_kilometers <= 8 else "car")
        rows.append({
            "donor_id": donor.id, "name": donor.full_name, "blood_type": donor.blood_type,
            "distance_km": m.distance_kilometers, "probability": pred["probability"], "speed": pred["speed"],
            "reasons": pred["reasons"], "eta_minutes": eta["minutes"], "phone_number": donor.phone_number,
        })
    rows.sort(key=lambda r: (-r["probability"], r["distance_km"]))
    return rows


def response_plan(db: Session, blood_request: BloodRequest) -> Dict:
    matches = find_matching_donors(db, blood_request)
    ranked = rank_by_response(db, blood_request, matches)
    needed = max((blood_request.units_needed or 1) - (blood_request.units_fulfilled or 0), 0) or 1
    pick = logic.pick_alert_order(ranked, needed)
    return {
        "request_id": blood_request.id, "hour_used": local_hour(), "units_still_needed": needed,
        "donors_considered": len(ranked), "likely_responders": ranked[:10],
        "alert_first_count": len(pick["alert_first"]), "expected_acceptances": pick["expected_acceptances"],
        "note": "A donor's chance is worked out from their past replies, distance, time since last donation, "
                "time of day and urgency. It only changes the order alerts go out in. Nobody is excluded.",
    }
