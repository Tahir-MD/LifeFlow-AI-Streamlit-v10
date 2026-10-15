"""
What each hospital staff role may do. One place, so the screens and the server agree.

  receptionist   front desk: logs donors and patients, checks donors in at camps
  lab_technician receptionist + manages the blood stock and expiry dates
  doctor         receptionist + screens donors (medical clearance)
  manager        everything above
"""
from typing import List

PERMISSIONS = {
    "log_visitors": "Log donors and patients",
    "camp_checkin": "Check donors in at camps",
    "view_nearby": "See nearby donors and hospitals",
    "manage_stock": "Manage blood stock and expiry dates",
    "screen_donors": "Medically screen donors",
}

ROLE_PERMISSIONS = {
    "receptionist": {"log_visitors", "camp_checkin", "view_nearby"},
    "lab_technician": {"log_visitors", "camp_checkin", "view_nearby", "manage_stock"},
    "doctor": {"log_visitors", "camp_checkin", "view_nearby", "screen_donors"},
    "manager": set(PERMISSIONS),
}

ROLE_LABELS = {
    "receptionist": "Receptionist",
    "lab_technician": "Lab technician",
    "doctor": "Doctor",
    "manager": "Manager",
}


def permissions_for(role) -> List[str]:
    """Old staff rows have no role: they keep the front-desk powers they always had."""
    return sorted(ROLE_PERMISSIONS.get(role or "receptionist", ROLE_PERMISSIONS["receptionist"]))


def can(role, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role or "receptionist", ROLE_PERMISSIONS["receptionist"])
