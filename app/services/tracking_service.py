"""Live request tracking: a small timeline of what happened to a blood request."""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.request_event import RequestEvent


def add_event(db: Session, request_id: int, kind: str, message: str,
              actor_type: Optional[str] = None, actor_id: Optional[int] = None) -> None:
    """Adds one timeline step. Does not commit: the caller's own commit saves it."""
    db.add(RequestEvent(request_id=request_id, kind=kind, message=message, actor_type=actor_type, actor_id=actor_id))
