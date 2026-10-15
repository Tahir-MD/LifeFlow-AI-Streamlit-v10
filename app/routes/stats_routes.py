from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.models.request import BloodRequest
from app.models.donation import Donation
from app.models.inventory import BloodInventory
from app.models.rating import Rating
from app.schemas.stats_schema import DonorStatsOut, HospitalStatsOut, ReceiverStatsOut, LeaderboardEntryOut, PlatformStatsOut
from app.utils.dependencies import get_current_donor, get_current_hospital, get_current_receiver
from app.utils.badges import get_badge_tier, get_next_eligible_date, is_eligible_now

router = APIRouter(tags=["Stats & Leaderboard"])


@router.get("/donors/me/stats", response_model=DonorStatsOut)
def donor_stats(db: Session = Depends(get_db), current_donor: Donor = Depends(get_current_donor)):
    donations = db.query(Donation).filter(Donation.donor_id == current_donor.id).all()
    total_units = sum(d.units_donated for d in donations)

    donation_ids = [d.id for d in donations]
    ratings = (
        db.query(Rating)
        .filter(Rating.donation_id.in_(donation_ids), Rating.direction == "requester_to_donor")
        .all()
        if donation_ids else []
    )
    average_rating = round(sum(r.stars for r in ratings) / len(ratings), 2) if ratings else None

    all_donors_by_points = db.query(Donor).order_by(Donor.points.desc()).all()
    rank = next((i + 1 for i, d in enumerate(all_donors_by_points) if d.id == current_donor.id), None)

    return DonorStatsOut(
        total_donations=len(donations),
        total_units_donated=total_units,
        estimated_lives_impacted=total_units * 3,
        badge_tier=get_badge_tier(len(donations)),
        is_eligible_now=is_eligible_now(current_donor.is_eligible, current_donor.last_donation_date, current_donor.gender, current_donor.deferred_until),
        next_eligible_date=get_next_eligible_date(current_donor.last_donation_date, current_donor.gender, current_donor.deferred_until),
        points=current_donor.points,
        average_rating=average_rating,
        leaderboard_rank=rank,
    )


@router.get("/hospitals/me/stats", response_model=HospitalStatsOut)
def hospital_stats(db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_current_hospital)):
    requests = (
        db.query(BloodRequest)
        .filter(BloodRequest.requester_type == "hospital", BloodRequest.requester_id == current_hospital.id)
        .all()
    )
    low_stock = (
        db.query(BloodInventory)
        .filter(BloodInventory.hospital_id == current_hospital.id)
        .filter(BloodInventory.units_available <= BloodInventory.low_stock_threshold)
        .all()
    )
    return HospitalStatsOut(
        total_requests=len(requests),
        open_requests=len([r for r in requests if r.status == "open"]),
        fulfilled_requests=len([r for r in requests if r.status == "fulfilled"]),
        total_units_received=sum(r.units_fulfilled for r in requests),
        low_stock_types=[row.blood_type for row in low_stock],
    )


@router.get("/receivers/me/stats", response_model=ReceiverStatsOut)
def receiver_stats(db: Session = Depends(get_db), current_receiver: Receiver = Depends(get_current_receiver)):
    requests = (
        db.query(BloodRequest)
        .filter(BloodRequest.requester_type == "receiver", BloodRequest.requester_id == current_receiver.id)
        .all()
    )
    return ReceiverStatsOut(
        total_requests=len(requests),
        open_requests=len([r for r in requests if r.status == "open"]),
        fulfilled_requests=len([r for r in requests if r.status == "fulfilled"]),
        total_units_received=sum(r.units_fulfilled for r in requests),
    )


@router.get("/stats/platform", response_model=PlatformStatsOut)
def platform_stats(db: Session = Depends(get_db)):
    """Public, headline numbers shown on the landing page. No login needed."""
    total_donors = db.query(Donor).count()
    total_hospitals = db.query(Hospital).count()
    total_receivers = db.query(Receiver).count()
    fulfilled_requests = db.query(BloodRequest).filter(BloodRequest.status == "fulfilled").all()
    all_donations = db.query(Donation).all()
    total_units_donated = sum(d.units_donated for d in all_donations)

    all_ratings = db.query(Rating).all()
    average_rating = round(sum(r.stars for r in all_ratings) / len(all_ratings), 2) if all_ratings else None

    return PlatformStatsOut(
        total_donors=total_donors,
        total_hospitals=total_hospitals,
        total_patients_helped=total_receivers,
        total_units_donated=total_units_donated,
        total_requests_fulfilled=len(fulfilled_requests),
        average_platform_rating=average_rating,
    )


@router.get("/leaderboard/donors", response_model=List[LeaderboardEntryOut])
def donor_leaderboard(db: Session = Depends(get_db), limit: int = 20):
    """Public top-donor leaderboard, a light gamification touch used by many donation platforms."""
    donors = db.query(Donor).order_by(Donor.points.desc()).limit(limit).all()
    entries = []
    for i, donor in enumerate(donors):
        total_donations = db.query(Donation).filter(Donation.donor_id == donor.id).count()
        entries.append(LeaderboardEntryOut(
            rank=i + 1,
            donor_id=donor.id,
            full_name=donor.full_name,
            blood_type=donor.blood_type,
            points=donor.points,
            total_donations=total_donations,
            badge_tier=get_badge_tier(total_donations),
        ))
    return entries
