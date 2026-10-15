from sqlalchemy.orm import Session

from app.models.notification import Notification


def notify(db: Session, user_type: str, user_id: int, title: str, message: str,
           category: str = "general", related_request_id: int = None, external: bool = True) -> None:
    """
    Creates an in-app notification, and -- wherever a provider is
    configured -- also fans it out to real SMS (Twilio), real email
    (SendGrid), and real browser/PWA push (Web Push/VAPID). Every one
    of those three channels is optional and fails silently if not
    configured, so this function always at least creates the in-app
    notification.
    """
    notification = Notification(
        user_type=user_type,
        user_id=user_id,
        title=title,
        message=message,
        category=category,
        related_request_id=related_request_id,
    )
    db.add(notification)
    db.flush()

    if external:  # bulk messages choose their own channel and pass external=False
        _deliver_externally(db, user_type, user_id, title, message)


def _deliver_externally(db: Session, user_type: str, user_id: int, title: str, message: str) -> None:
    from app.services.delivery_service import (
        is_sms_configured, is_email_configured, is_whatsapp_configured, send_sms, send_email, send_whatsapp,
    )
    from app.services.push_service import is_push_configured, push_to_account

    if not (is_sms_configured() or is_email_configured() or is_push_configured() or is_whatsapp_configured()):
        return  # nothing configured -- skip the lookups below entirely

    phone_number, email, wants_sms, wants_whatsapp = _contact_details(db, user_type, user_id)

    if wants_whatsapp and is_whatsapp_configured() and phone_number:
        send_whatsapp(phone_number, f"LifeFlow - {title}: {message}")
    if wants_sms and is_sms_configured() and phone_number:
        send_sms(phone_number, f"{title}: {message}")
    if is_email_configured() and email:
        send_email(email, f"LifeFlow -- {title}", message)
    if is_push_configured():
        push_to_account(db, user_type, user_id, title, message)


def _contact_details(db: Session, user_type: str, user_id: int):
    """Looks up the phone number and email for whichever kind of account this notification is for."""
    if user_type == "donor":
        from app.models.donor import Donor
        account = db.query(Donor).filter(Donor.id == user_id).first()
    elif user_type == "hospital":
        from app.models.hospital import Hospital
        account = db.query(Hospital).filter(Hospital.id == user_id).first()
    elif user_type == "receiver":
        from app.models.receiver import Receiver
        account = db.query(Receiver).filter(Receiver.id == user_id).first()
    elif user_type == "staff":
        from app.models.staff import Staff
        account = db.query(Staff).filter(Staff.id == user_id).first()
    else:
        account = None

    if not account:
        return None, None, False, False
    phone_number = getattr(account, "phone_number", None)
    email = getattr(account, "email", None)
    wants_sms = getattr(account, "notify_sms", True) is not False        # old rows hold None = on
    wants_whatsapp = getattr(account, "notify_whatsapp", False) is True
    return phone_number, email, wants_sms, wants_whatsapp
