from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class DonationHistoryOut(BaseModel):
    """
    A single completed donation, shown with full details of both
    sides so a donor sees exactly who they helped, and a hospital or
    patient sees exactly who helped them.
    """
    donation_id: int
    request_id: int
    units_donated: int
    donated_at: datetime
    request_status: str
    blood_type_needed: str
    patient_name: Optional[str] = None

    donor_id: int
    donor_name: str
    donor_phone: str
    donor_blood_type: str

    requester_type: str
    requester_id: int
    requester_name: str
    requester_phone: str
    requester_cnic: Optional[str] = None
    requester_address: Optional[str] = None

    average_donor_rating: Optional[float] = None
    average_requester_rating: Optional[float] = None
