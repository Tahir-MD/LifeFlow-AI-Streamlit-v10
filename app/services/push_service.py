"""
Real push notifications to a browser or an installed PWA, using the
standard Web Push protocol (VAPID) -- this is the same mechanism that
powers push notifications for installed web apps on Android and
desktop, and is what a React Native/Flutter wrapper around this same
frontend would also ultimately call under the hood.

Like ai_client.py and delivery_service.py, this degrades gracefully:
if VAPID keys aren't set, or the `pywebpush` package isn't installed,
push sends are simply skipped -- every other part of LifeFlow (in-app
notifications, SMS, email) keeps working.

To turn this on:

    pip install pywebpush
    python -c "from py_vapid import Vapid; v = Vapid(); v.generate_keys(); print(v.private_pem)"

    export VAPID_PUBLIC_KEY="..."
    export VAPID_PRIVATE_KEY="..."
    export VAPID_CLAIM_EMAIL="mailto:you@yourdomain.com"
"""
import os
import json
from typing import List

from sqlalchemy.orm import Session

from app.models.push_subscription import PushSubscription

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL", "mailto:admin@lifeflow.app")


def is_push_configured() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def get_public_key() -> str:
    return VAPID_PUBLIC_KEY


def save_subscription(db: Session, owner_type: str, owner_id: int, endpoint: str, p256dh_key: str, auth_key: str) -> PushSubscription:
    existing = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
    if existing:
        existing.owner_type = owner_type
        existing.owner_id = owner_id
        existing.p256dh_key = p256dh_key
        existing.auth_key = auth_key
        db.commit()
        db.refresh(existing)
        return existing

    subscription = PushSubscription(
        owner_type=owner_type, owner_id=owner_id, endpoint=endpoint,
        p256dh_key=p256dh_key, auth_key=auth_key,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


def remove_subscription(db: Session, endpoint: str) -> None:
    db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).delete()
    db.commit()


def _send_to_one(subscription: PushSubscription, title: str, body: str) -> bool:
    try:
        from pywebpush import webpush
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh_key, "auth": subscription.auth_key},
            },
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_CLAIM_EMAIL},
        )
        return True
    except Exception:  # noqa: BLE001 -- one dead subscription must never break the caller
        return False


def push_to_account(db: Session, owner_type: str, owner_id: int, title: str, body: str) -> int:
    """Pushes to every device this account has subscribed from. Returns how many sends succeeded."""
    if not is_push_configured():
        return 0
    subscriptions: List[PushSubscription] = (
        db.query(PushSubscription)
        .filter(PushSubscription.owner_type == owner_type, PushSubscription.owner_id == owner_id)
        .all()
    )
    return sum(1 for subscription in subscriptions if _send_to_one(subscription, title, body))
