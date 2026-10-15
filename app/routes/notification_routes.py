from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.notification import Notification
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.schemas.notification_schema import NotificationOut
from app.utils.dependencies import get_current_donor, get_current_hospital, get_current_receiver

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _list_for(db: Session, user_type: str, user_id: int) -> List[Notification]:
    return (
        db.query(Notification)
        .filter(Notification.user_type == user_type, Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(100)
        .all()
    )


@router.get("/donor", response_model=List[NotificationOut])
def donor_notifications(db: Session = Depends(get_db), current_donor: Donor = Depends(get_current_donor)):
    return _list_for(db, "donor", current_donor.id)


@router.get("/hospital", response_model=List[NotificationOut])
def hospital_notifications(db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_current_hospital)):
    return _list_for(db, "hospital", current_hospital.id)


@router.get("/receiver", response_model=List[NotificationOut])
def receiver_notifications(db: Session = Depends(get_db), current_receiver: Receiver = Depends(get_current_receiver)):
    return _list_for(db, "receiver", current_receiver.id)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(notification_id: int, db: Session = Depends(get_db)):
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


@router.post("/donor/read-all")
def mark_all_donor_read(db: Session = Depends(get_db), current_donor: Donor = Depends(get_current_donor)):
    db.query(Notification).filter(
        Notification.user_type == "donor", Notification.user_id == current_donor.id
    ).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read."}


@router.post("/hospital/read-all")
def mark_all_hospital_read(db: Session = Depends(get_db), current_hospital: Hospital = Depends(get_current_hospital)):
    db.query(Notification).filter(
        Notification.user_type == "hospital", Notification.user_id == current_hospital.id
    ).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read."}


@router.post("/receiver/read-all")
def mark_all_receiver_read(db: Session = Depends(get_db), current_receiver: Receiver = Depends(get_current_receiver)):
    db.query(Notification).filter(
        Notification.user_type == "receiver", Notification.user_id == current_receiver.id
    ).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read."}
