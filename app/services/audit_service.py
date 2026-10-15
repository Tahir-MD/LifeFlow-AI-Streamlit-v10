"""
A blockchain-style, tamper-evident audit trail -- without needing an
actual blockchain, a wallet, or gas fees. Each event's hash covers its
own contents and the previous event's hash (SHA-256), the same
construction a blockchain uses. Anyone can independently recompute the
chain from the raw rows and confirm nothing was altered after the
fact: see verify_chain().

This deliberately doesn't need any new infrastructure -- it's a single
extra table, which is exactly the right amount of "blockchain" for a
system that has one trusted database and wants tamper-evidence, not a
distributed trust problem to solve.
"""
import hashlib
import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

GENESIS_HASH = "0" * 64


def _compute_hash(prev_hash: str, event_type: str, actor_type: Optional[str], actor_id: Optional[int],
                   payload_json: str, created_at_iso: str) -> str:
    material = f"{prev_hash}|{event_type}|{actor_type}|{actor_id}|{payload_json}|{created_at_iso}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def record_event(db: Session, event_type: str, actor_type: Optional[str] = None,
                  actor_id: Optional[int] = None, payload: Optional[dict] = None) -> AuditLog:
    """
    Appends one tamper-evident event to the chain. Safe to call inside
    an existing request handler right before that handler's own
    db.commit() -- this function commits on its own, so the audit
    entry is durable even if something later in the same request fails.
    """
    last_entry = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    prev_hash = last_entry.hash if last_entry else GENESIS_HASH

    payload_json = json.dumps(payload or {}, sort_keys=True, default=str)
    created_at = datetime.utcnow()
    entry_hash = _compute_hash(prev_hash, event_type, actor_type, actor_id, payload_json, created_at.isoformat())

    entry = AuditLog(
        event_type=event_type, actor_type=actor_type, actor_id=actor_id,
        payload_json=payload_json, prev_hash=prev_hash, hash=entry_hash, created_at=created_at,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def verify_chain(db: Session) -> dict:
    """Walks every row in order and recomputes each hash, to prove (or disprove) the chain hasn't been tampered with."""
    entries = db.query(AuditLog).order_by(AuditLog.id.asc()).all()
    prev_hash = GENESIS_HASH
    for entry in entries:
        expected_hash = _compute_hash(
            prev_hash, entry.event_type, entry.actor_type, entry.actor_id,
            entry.payload_json, entry.created_at.isoformat(),
        )
        if expected_hash != entry.hash:
            return {"valid": False, "broken_at_id": entry.id, "checked": len(entries)}
        prev_hash = entry.hash
    return {"valid": True, "broken_at_id": None, "checked": len(entries)}
