from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

from app.database import Base


class AuditLog(Base):
    """
    A tamper-evident record of every important event on the platform --
    a request opening, a donation completing, a rating being given, a
    hospital's inventory changing. Each row's hash is calculated from
    its own contents PLUS the previous row's hash, exactly like a
    blockchain's block-chaining: if anyone edits or deletes a past row
    directly in the database, every hash after it stops matching, and
    /admin/audit/verify will say exactly which row broke the chain.
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, nullable=False)
    actor_type = Column(String, nullable=True)   # donor | hospital | receiver | admin | staff | system
    actor_id = Column(Integer, nullable=True)
    payload_json = Column(String, nullable=False)
    prev_hash = Column(String, nullable=False)
    hash = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
