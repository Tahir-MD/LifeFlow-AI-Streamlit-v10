"""
Fake / misuse detection for blood requests.

Every new request gets a score from 0 to 100 built from simple, explainable rules (no black box),
so an admin can always see WHY a request was flagged:

    score >= 60   -> HELD   (donors are not alerted until an admin approves it)
    30 .. 59      -> FLAGGED (goes out normally, but shows up in the admin review list)
    below 30      -> OK

Emergency SOS requests are never held (a real emergency must not wait), but they are still flagged.
This file has no database code: the route collects the facts, this file only judges them.
"""
import re
from typing import Dict, List, Tuple

HOLD_AT = 60
FLAG_AT = 30


def score_request(facts: Dict) -> Tuple[int, List[str]]:
    """
    facts keys (all optional):
      requests_last_24h      how many requests this account already made in 24 hours
      duplicate_open         True if the same patient + blood type already has an open request
      units_needed           int
      account_age_minutes    how old the account is
      is_emergency           bool
      distance_from_home_km  distance between the request place and the account's registered place
      medical_reason         free text
      patient_name           text
      requester_type         "hospital" | "receiver"
      hospital_verified      bool
      same_cnic_accounts     how many accounts share this CNIC (receivers)
      sos_last_24h           SOS alerts already sent today
    """
    score = 0
    reasons: List[str] = []

    def add(points: int, reason: str) -> None:
        nonlocal score
        score += points
        reasons.append(reason)

    n24 = facts.get("requests_last_24h") or 0
    if n24 >= 7:
        add(45, f"{n24} requests from one account in 24 hours")
    elif n24 >= 4:
        add(25, f"{n24} requests from one account in 24 hours")

    if facts.get("duplicate_open"):
        add(40, "Same patient and blood type already has an open request")

    units = facts.get("units_needed") or 0
    if units >= 13:
        add(35, f"Very large request ({units} bags)")
    elif units >= 8:
        add(20, f"Large request ({units} bags)")

    if facts.get("is_emergency") and (facts.get("account_age_minutes") is not None) and facts["account_age_minutes"] < 10:
        add(15, "Emergency request from an account created minutes ago")

    distance = facts.get("distance_from_home_km")
    if distance is not None and distance > 300:
        add(20, f"Request place is {round(distance)} km from the registered place")

    reason_text = (facts.get("medical_reason") or "").strip()
    if reason_text:
        if re.search(r"https?://|www\.|\.com\b", reason_text, re.I):
            add(25, "Medical reason contains a web link")
        elif re.fullmatch(r"[\d\W_]+", reason_text):
            add(25, "Medical reason is only numbers or symbols")
    elif facts.get("requester_type") == "receiver" and not (facts.get("patient_name") or "").strip():
        add(10, "No patient name and no medical reason given")

    cnic_accounts = facts.get("same_cnic_accounts") or 0
    if cnic_accounts >= 2:
        add(30, f"The same ID number is used by {cnic_accounts} accounts")

    if (facts.get("sos_last_24h") or 0) >= 2:
        add(20, "Several SOS alerts in one day")

    if facts.get("hospital_verified"):
        score -= 20
        reasons.append("Verified hospital (lower risk)")

    return max(0, min(100, score)), reasons


def decide(score: int, is_sos: bool = False) -> str:
    """Returns "held", "flagged" or "ok"."""
    if score >= HOLD_AT and not is_sos:
        return "held"
    if score >= FLAG_AT or (is_sos and score >= HOLD_AT):
        return "flagged"
    return "ok"
