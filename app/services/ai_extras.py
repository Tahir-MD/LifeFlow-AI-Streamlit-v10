"""
Extra AI / decision-support features:

* plan_donor_outreach   -- no-show-aware "how many donors should we alert" planner
* optimize_allocation   -- multi-request donor allocation (assignment problem, greedy with scarcity ordering)
* forecast_accuracy     -- backtest: our 7-day-average forecaster vs a naive "same as yesterday" baseline
* impact_summary        -- measured + estimated impact of the stock-check-first design
* hospital_data_context -- compact facts about one hospital, for the natural-language data assistant

All of it is transparent statistics / combinatorics, deliberately explainable.
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.request import BloodRequest
from app.models.donation import Donation
from app.models.inventory import BloodInventory
from app.models.visitor_log import VisitorEntry
from app.services.matching_service import find_matching_donors
from app.services.forecast_service import _daily_demand, BLOOD_TYPES


def plan_donor_outreach(db: Session, blood_request: BloodRequest) -> dict:
    """
    If each donor shows up with probability (1 - no_show_risk), how many
    donors must be alerted so the expected number of arrivals covers the
    units still needed with a 30% safety margin?
    """
    needed = max(blood_request.units_needed - blood_request.units_fulfilled, 0)
    matches = find_matching_donors(db, blood_request)
    target = needed * 1.3
    expected, alert = 0.0, []
    for match in matches:
        if expected >= target:
            break
        expected += 1 - (match.no_show_risk or 0.5)
        alert.append(match)
    return {
        "request_id": blood_request.id,
        "units_still_needed": needed,
        "donors_available": len(matches),
        "recommended_alert_count": len(alert),
        "expected_arrivals": round(expected, 2),
        "shortfall_risk": expected < needed,
        "donors_to_alert": [m.model_dump() for m in alert],
    }


def _urgency_rank(request: BloodRequest) -> tuple:
    order = {"emergency": 0, "days": 1, "months": 2}
    return (order.get(request.urgency_type, 3), request.urgency_value or 0, request.created_at)


def optimize_allocation(db: Session) -> dict:
    """
    Assign each donor to at most ONE open request. Emergencies first; within
    a tier, requests with the fewest candidate donors go first (scarcest
    first -- a standard heuristic for assignment problems), and each request
    takes its best-scoring donors that are still free.
    """
    open_requests = db.query(BloodRequest).filter(BloodRequest.status == "open").all()
    candidates = {r.id: find_matching_donors(db, r) for r in open_requests}
    ordered = sorted(open_requests, key=lambda r: (_urgency_rank(r)[0], len(candidates[r.id])))

    used, results = set(), []
    for request in ordered:
        needed = max(request.units_needed - request.units_fulfilled, 0)
        chosen = []
        for match in candidates[request.id]:
            if len(chosen) >= needed:
                break
            if match.donor_id not in used:
                used.add(match.donor_id)
                chosen.append(match)
        results.append({
            "request_id": request.id, "blood_type": request.blood_type_needed,
            "urgency": request.urgency_type, "units_needed": needed,
            "units_covered": len(chosen), "fully_covered": len(chosen) >= needed,
            "assigned_donors": [{"donor_id": m.donor_id, "name": m.full_name, "distance_km": m.distance_kilometers,
                                 "score": m.match_score, "no_show_risk": m.no_show_risk} for m in chosen],
        })
    total_needed = sum(r["units_needed"] for r in results)
    total_covered = sum(r["units_covered"] for r in results)
    return {
        "open_requests": len(results), "units_needed": total_needed, "units_covered": total_covered,
        "coverage_percent": round(100 * total_covered / total_needed, 1) if total_needed else 100.0,
        "method": "Greedy assignment: emergencies first, scarcest requests first, each donor used once.",
        "assignments": results,
    }


def forecast_accuracy(db: Session) -> dict:
    """Backtest one-step-ahead forecasts over the last 30 days, platform-wide, per blood type."""
    rows, model_err, naive_err, points = [], 0.0, 0.0, 0
    for blood_type in BLOOD_TYPES:
        series = _daily_demand(db, None, blood_type, 30)
        m_err = n_err = n = 0
        for t in range(7, len(series)):
            prediction = sum(series[t - 7:t]) / 7
            m_err += abs(series[t] - prediction)
            n_err += abs(series[t] - series[t - 1])
            n += 1
        if n:
            rows.append({"blood_type": blood_type, "model_mae": round(m_err / n, 3), "naive_mae": round(n_err / n, 3)})
            model_err += m_err
            naive_err += n_err
            points += n
    improvement = round(100 * (naive_err - model_err) / naive_err, 1) if naive_err else None
    return {
        "days_backtested": 23, "predictions_scored": points,
        "model": "7-day moving average", "baseline": "same as yesterday",
        "overall_model_mae": round(model_err / points, 3) if points else None,
        "overall_naive_mae": round(naive_err / points, 3) if points else None,
        "improvement_over_baseline_percent": improvement,
        "per_blood_type": rows,
        "note": "MAE = mean absolute error in bags/day. Lower is better. Scores get meaningful as real history accumulates.",
    }


CALLOUTS_PER_DONOR_FOUND = 3   # assumption: ~3 people contacted per donor who actually shows up
MINUTES_PER_CALLOUT = 15       # assumption: coordinator time per phone call


def impact_summary(db: Session) -> dict:
    requests = db.query(BloodRequest).all()
    from_stock = [r for r in requests if r.fulfilled_from_inventory]
    fully_from_stock = [r for r in from_stock if r.units_fulfilled >= r.units_needed and r.inventory_units_used >= r.units_needed]
    units_from_stock = sum(r.inventory_units_used or 0 for r in requests)
    callouts_avoided = units_from_stock * CALLOUTS_PER_DONOR_FOUND
    donations = db.query(Donation).count()
    return {
        "total_requests": len(requests),
        "requests_helped_by_stock": len(from_stock),
        "requests_fully_covered_by_stock": len(fully_from_stock),
        "units_supplied_from_stock": units_from_stock,
        "units_donated_by_donors": sum(d.units_donated for d in db.query(Donation).all()),
        "donations_completed": donations,
        "estimated_donor_callouts_avoided": callouts_avoided,
        "estimated_coordinator_hours_saved": round(callouts_avoided * MINUTES_PER_CALLOUT / 60, 1),
        "assumptions": f"Estimate: ~{CALLOUTS_PER_DONOR_FOUND} people contacted per donor found, {MINUTES_PER_CALLOUT} minutes per call. "
                       "Request and stock counts are measured; callouts/hours are estimates.",
    }


def hospital_data_context(db: Session, hospital_id: int) -> str:
    now = datetime.utcnow()
    week, month = now - timedelta(days=7), now - timedelta(days=30)
    inventory = db.query(BloodInventory).filter(BloodInventory.hospital_id == hospital_id).all()
    reqs = db.query(BloodRequest).filter(BloodRequest.requester_type == "hospital", BloodRequest.requester_id == hospital_id).all()
    request_ids = [r.id for r in reqs]
    donations = db.query(Donation).filter(Donation.request_id.in_(request_ids)).all() if request_ids else []
    visitors = db.query(VisitorEntry).filter(VisitorEntry.hospital_id == hospital_id).count()

    def by_type(items, attr, since):
        totals = {}
        for item in items:
            when = getattr(item, "created_at", None) or getattr(item, "donated_at", None)
            if when and when >= since:
                key = getattr(item, "blood_type_needed", None) or "n/a"
                totals[key] = totals.get(key, 0) + (getattr(item, attr, 1) or 1)
        return totals

    donation_units_week = sum(d.units_donated for d in donations if d.donated_at >= week)
    donation_units_month = sum(d.units_donated for d in donations if d.donated_at >= month)
    lines = [
        "Inventory (bags on hand): " + (", ".join(f"{i.blood_type}={i.units_available} (low if <{i.low_stock_threshold})" for i in inventory) or "none recorded"),
        f"Requests created last 7 days by blood type: {by_type(reqs, 'units_needed', week)}",
        f"Requests created last 30 days by blood type: {by_type(reqs, 'units_needed', month)}",
        f"Open requests now: {sum(1 for r in reqs if r.status == 'open')}; fulfilled all-time: {sum(1 for r in reqs if r.status == 'fulfilled')}",
        f"Bags donated to this hospital's requests: last 7 days={donation_units_week}, last 30 days={donation_units_month}",
        f"Donor visits/donations recorded all-time: {len(donations)}; visitor log entries all-time: {visitors}",
    ]
    return "\n".join(lines)


# --- Donor re-engagement -----------------------------------------------------

OVERDUE_DAYS = 90


def find_reengagement_candidates(db: Session, hospital_id: Optional[int] = None, limit: int = 20) -> list:
    """
    Donors who are overdue (or have never donated) for a blood type
    that's currently under strain. If hospital_id is given, "under
    strain" means that hospital's own low/high-risk stock; otherwise
    it's judged against platform-wide forecasted risk.
    """
    from app.models.donor import Donor
    from app.services.forecast_service import forecast_hospital, forecast_platform

    forecast = forecast_hospital(db, hospital_id) if hospital_id else forecast_platform(db)
    risky_types = {e["blood_type"] for e in forecast if e["risk_level"] in ("high", "medium")} or set(BLOOD_TYPES)

    cutoff = datetime.utcnow() - timedelta(days=OVERDUE_DAYS)
    donors = (
        db.query(Donor)
        .filter(Donor.is_eligible == True)  # noqa: E712
        .filter(Donor.blood_type.in_(risky_types))
        .filter((Donor.last_donation_date == None) | (Donor.last_donation_date <= cutoff))  # noqa: E711
        .order_by(Donor.last_donation_date.asc().nullsfirst())
        .limit(limit)
        .all()
    )
    out = []
    for donor in donors:
        days_overdue = (datetime.utcnow() - donor.last_donation_date).days - OVERDUE_DAYS if donor.last_donation_date else None
        out.append({
            "donor_id": donor.id, "full_name": donor.full_name, "blood_type": donor.blood_type,
            "phone_number": donor.phone_number, "days_since_last_donation": (datetime.utcnow() - donor.last_donation_date).days if donor.last_donation_date else None,
            "days_overdue": days_overdue, "never_donated": donor.last_donation_date is None,
        })
    return out


def draft_reengagement_message(donor, days_overdue: Optional[int], blood_type: str) -> str:
    """AI-drafted, personalized nudge -- falls back to a plain template if AI isn't configured."""
    from app.services.ai_client import ask_ai, is_ai_configured
    if is_ai_configured():
        context = (
            "Write a short (max 2 sentences), warm SMS/notification to a registered blood donor, encouraging "
            "them to donate again soon. Be specific, not generic. Never pressure or guilt-trip; this is a gentle nudge."
        )
        fact = (
            f"Donor first name: {donor.full_name.split()[0]}. Blood type: {blood_type}. "
            + (f"They are about {days_overdue} days overdue for their next eligible donation. " if days_overdue else "They have not donated yet. ")
            + f"{blood_type} is currently running low nearby."
        )
        return ask_ai(context, fact, max_tokens=120)
    if days_overdue:
        return f"Hi {donor.full_name.split()[0]}, it's been a while — {blood_type} is running low nearby and you're eligible again. Could you donate this week?"
    return f"Hi {donor.full_name.split()[0]}, {blood_type} is currently in short supply nearby. Your first donation could make a real difference this week."


# --- Camp location suggestions -----------------------------------------------

GRID_SIZE_DEGREES = 0.06  # ~6-7 km per cell


def suggest_camp_locations(db: Session, days: int = 60, top_n: int = 5) -> dict:
    """
    Bins recent requests into a lat/lng grid and surfaces the clusters
    with the most demand -- a simple, transparent stand-in for proper
    geospatial clustering (k-means/DBSCAN), good enough to point at
    "where do we need a camp" without needing a geo library.
    """
    since = datetime.utcnow() - timedelta(days=days)
    requests_recent = db.query(BloodRequest).filter(BloodRequest.created_at >= since).all()

    cells = {}
    for r in requests_recent:
        key = (round(r.latitude / GRID_SIZE_DEGREES), round(r.longitude / GRID_SIZE_DEGREES))
        cell = cells.setdefault(key, {"request_count": 0, "units_needed": 0, "lat_sum": 0.0, "lng_sum": 0.0, "blood_types": {}})
        cell["request_count"] += 1
        cell["units_needed"] += r.units_needed
        cell["lat_sum"] += r.latitude
        cell["lng_sum"] += r.longitude
        cell["blood_types"][r.blood_type_needed] = cell["blood_types"].get(r.blood_type_needed, 0) + 1

    ranked = sorted(cells.values(), key=lambda c: c["units_needed"], reverse=True)[:top_n]
    clusters = []
    for c in ranked:
        top_type = max(c["blood_types"], key=c["blood_types"].get)
        clusters.append({
            "approx_latitude": round(c["lat_sum"] / c["request_count"], 4),
            "approx_longitude": round(c["lng_sum"] / c["request_count"], 4),
            "request_count": c["request_count"], "units_needed": c["units_needed"], "most_needed_type": top_type,
        })

    from app.services.ai_client import ask_ai, is_ai_configured
    commentary = None
    if clusters and is_ai_configured():
        commentary = ask_ai(
            "You suggest where a blood bank should run its next donation camp, in 2-3 short sentences, "
            "based on clustered request data. Be concrete and reference the numbers given.",
            str(clusters), max_tokens=150,
        )
    return {"days_analyzed": days, "clusters": clusters, "ai_commentary": commentary}
