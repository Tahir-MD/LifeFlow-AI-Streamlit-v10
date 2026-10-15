from datetime import datetime, timedelta
from typing import List

from sqlalchemy.orm import Session

from app.models.donor import Donor
from app.models.request import BloodRequest
from app.utils.distance import calculate_distance_kilometers
from app.schemas.request_schema import MatchedDonorOut

# Which blood types can safely donate to which blood type.
# The key is the blood type that needs blood.
# The value is the list of blood types that can give blood to it.
COMPATIBLE_DONOR_TYPES = {
    "O-": ["O-"],
    "O+": ["O-", "O+"],
    "A-": ["O-", "A-"],
    "A+": ["O-", "O+", "A-", "A+"],
    "B-": ["O-", "B-"],
    "B+": ["O-", "O+", "B-", "B+"],
    "AB-": ["O-", "A-", "B-", "AB-"],
    "AB+": ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"],
}

MAXIMUM_SEARCH_DISTANCE_KILOMETERS = 50
MINIMUM_DAYS_BETWEEN_DONATIONS = 90


def find_hospitals_with_stock(db: Session, blood_request: BloodRequest, prefer_hospital_id: int = None):
    """
    Looks across every hospital's blood bank for units of the exact
    blood type this request needs, closest first. If the request came
    from a hospital, that hospital's own shelf is checked first, since
    a hospital should always use its own stock before pulling from
    anywhere else.
    Returns a list of (distance_km, Hospital, BloodInventory row) tuples,
    only including rows that currently have stock on hand.
    """
    from app.models.inventory import BloodInventory
    from app.models.hospital import Hospital

    rows = (
        db.query(BloodInventory)
        .filter(BloodInventory.blood_type == blood_request.blood_type_needed)
        .filter(BloodInventory.units_available > 0)
        .all()
    )

    candidates = []
    for row in rows:
        hospital = db.query(Hospital).filter(Hospital.id == row.hospital_id).first()
        if not hospital:
            continue
        distance = calculate_distance_kilometers(
            blood_request.latitude, blood_request.longitude,
            hospital.latitude, hospital.longitude,
        )
        candidates.append((round(distance, 2), hospital, row))

    # A hospital's own stock always comes first, then everything else by distance.
    candidates.sort(key=lambda item: (item[1].id != prefer_hospital_id, item[0]))
    return candidates


def _explain_match(distance: float, average_rating, donations_made: int, no_show_risk: float) -> str:
    """
    A short, deterministic "why this donor" line built straight from the
    same numbers that produced the ranking -- explainable by
    construction, rather than a separate AI call per donor (which would
    be slow, costly, and could contradict the actual math behind the score).
    """
    parts = [f"{distance:.1f} km away"]
    if donations_made > 0:
        parts.append(f"donated {donations_made} time{'s' if donations_made != 1 else ''} before")
    else:
        parts.append("first-time donor")
    if average_rating is not None:
        parts.append(f"{average_rating}★ average rating")
    reliability_percent = round((1 - no_show_risk) * 100)
    parts.append(f"~{reliability_percent}% likely to follow through")
    return ", ".join(parts)


def estimate_no_show_risk(db: Session, donor_id: int, donations_made: int, average_rating) -> float:
    """
    Explainable no-show estimate. Response rate = donations made out of
    request alerts received, smoothed (Laplace) so a brand-new donor
    starts near 50%, then nudged by rating history. Returns 0..1.
    """
    from app.models.notification import Notification
    alerts = (
        db.query(Notification)
        .filter(Notification.user_type == "donor", Notification.user_id == donor_id, Notification.category == "request")
        .count()
    )
    response_rate = (donations_made + 1) / (alerts + 2) if alerts >= donations_made else 1.0
    risk = 1 - min(response_rate, 1.0)
    if average_rating is not None:
        risk -= ((average_rating - 3.5) / 1.5) * 0.10
    return round(max(0.02, min(0.98, risk)), 2)


def find_matching_donors(
    db: Session,
    blood_request: BloodRequest,
    maximum_distance_kilometers: float = MAXIMUM_SEARCH_DISTANCE_KILOMETERS,
) -> List[MatchedDonorOut]:
    """
    Finds donors who are compatible with the requested blood type,
    are eligible to donate, and are within the search distance.

    Donors aren't ranked by distance alone: each gets a match_score that
    also weighs their track record (average rating from past donations,
    a capped bonus for donation history) so outreach goes first to
    donors who are both close by AND likely to follow through -- a
    simple, explainable stand-in for the "optimized multi-request donor
    allocation" a full assignment-problem solver would compute at scale.
    """
    from app.models.donation import Donation
    from app.models.rating import Rating

    compatible_types = COMPATIBLE_DONOR_TYPES.get(blood_request.blood_type_needed, [])
    if not compatible_types:
        return []

    candidate_donors = (
        db.query(Donor)
        .filter(Donor.blood_type.in_(compatible_types))
        .filter(Donor.is_eligible == True)  # noqa: E712
        .all()
    )

    from app.services.eligibility_service import min_gap_days

    now = datetime.utcnow()
    matches = []
    for donor in candidate_donors:
        if donor.deferred_until and donor.deferred_until > now:
            continue  # the health questionnaire said "not yet"
        earliest_allowed_last_donation = now - timedelta(days=min_gap_days(donor.gender))
        if donor.last_donation_date and donor.last_donation_date > earliest_allowed_last_donation:
            continue

        distance = calculate_distance_kilometers(
            blood_request.latitude,
            blood_request.longitude,
            donor.latitude,
            donor.longitude,
        )

        if distance <= maximum_distance_kilometers:
            donation_ids = [d.id for d in db.query(Donation.id).filter(Donation.donor_id == donor.id).all()]
            ratings = (
                db.query(Rating)
                .filter(Rating.donation_id.in_(donation_ids), Rating.direction == "requester_to_donor")
                .all()
                if donation_ids else []
            )
            average_rating = round(sum(r.stars for r in ratings) / len(ratings), 2) if ratings else None
            no_show_risk = estimate_no_show_risk(db, donor.id, len(donation_ids), average_rating)

            # Closer is better, a strong rating history is better, and a good
            # rating never fully cancels out an unreasonable distance.
            distance_penalty = min(distance, maximum_distance_kilometers) / maximum_distance_kilometers
            reliability_bonus = ((average_rating or 3.5) - 3.5) / 1.5  # roughly -1..+1
            match_score = round((1 - distance_penalty) * 70 + reliability_bonus * 20 + min(donor.points, 50) / 50 * 10, 1)
            match_reason = _explain_match(distance, average_rating, len(donation_ids), no_show_risk)

            matches.append(
                MatchedDonorOut(
                    donor_id=donor.id,
                    full_name=donor.full_name,
                    blood_type=donor.blood_type,
                    phone_number=donor.phone_number,
                    distance_kilometers=round(distance, 2),
                    points=donor.points,
                    average_rating=average_rating,
                    match_score=match_score,
                    no_show_risk=no_show_risk,
                    match_reason=match_reason,
                )
            )

    matches.sort(key=lambda item: item.match_score, reverse=True)
    return matches
