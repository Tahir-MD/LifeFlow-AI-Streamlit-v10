"""
Blood-donation eligibility check.

A person answers a short health questionnaire BEFORE the donor account is created. The rules below
follow the common whole-blood donation guidelines used by blood banks (WHO / national transfusion
services): age, weight, haemoglobin, recent illness, medicines, tattoos, surgery, travel-related
infections, pregnancy, and long-term conditions.

Two kinds of "no":
  * temporary  -> "come back after <date>"  (defer_days)
  * permanent  -> "you cannot donate"       (defer_days is None)

This is a self-declared screening, NOT a medical diagnosis. A doctor at the blood bank always makes
the final decision on the donation day. This file has no database code so it is easy to test.
"""
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

MIN_AGE = 18
MAX_AGE = 60
MIN_WEIGHT_KG = 50.0
MIN_HB_MALE = 13.0
MIN_HB_FEMALE = 12.5
GAP_DAYS_MALE = 90
GAP_DAYS_FEMALE = 120


def min_gap_days(gender: Optional[str]) -> int:
    """Days a donor must wait between whole-blood donations."""
    return GAP_DAYS_FEMALE if (gender or "").lower() == "female" else GAP_DAYS_MALE


# (answer key, message shown to the person, defer_days; None = permanent)
YES_MEANS_NO: List[tuple] = [
    # ---- long-term / permanent ----
    ("hiv_aids", "HIV / AIDS means you cannot donate blood.", None),
    ("hepatitis", "Hepatitis B or C means you cannot donate blood.", None),
    ("cancer", "A history of cancer needs a doctor's approval, so you cannot register right now.", None),
    ("heart_disease", "Heart disease means you cannot donate blood.", None),
    ("bleeding_disorder", "A bleeding disorder or thalassemia major means you cannot donate blood.", None),
    ("seizures", "Seizures or epilepsy need a doctor's approval, so you cannot register right now.", None),
    ("insulin_diabetes", "Diabetes treated with insulin means you cannot donate blood.", None),
    ("kidney_liver", "Long-term kidney or liver disease means you cannot donate blood.", None),
    ("injected_drugs", "Using injected drugs that were not prescribed means you cannot donate blood.", None),
    ("blood_thinners", "Blood thinners (like warfarin) mean you cannot donate while taking them.", None),
    ("uncontrolled_bp", "High blood pressure that is not controlled means you cannot donate now. See a doctor first.", None),
    # ---- temporary ----
    ("unwell_today", "You are unwell today (fever, cold, cough, sore throat). Please come back when you are fully better.", 14),
    ("antibiotics_recent", "You took antibiotics or had an infection in the last 2 weeks.", 14),
    ("dental_week", "You had a tooth extraction or dental work in the last week.", 7),
    ("alcohol_24h", "You drank alcohol in the last 24 hours.", 1),
    ("vaccine_4w", "You had a vaccination in the last 4 weeks.", 28),
    ("malaria_3m", "You had malaria in the last 3 months.", 90),
    ("tattoo_6m", "You had a tattoo, piercing or acupuncture in the last 6 months.", 180),
    ("surgery_6m", "You had major surgery in the last 6 months.", 180),
    ("transfusion_12m", "You received a blood transfusion in the last 12 months.", 365),
    ("exposure_12m", "You had a needle-stick injury, or close contact with someone who has hepatitis or HIV, in the last 12 months.", 365),
]

FEMALE_ONLY: List[tuple] = [
    ("pregnant", "You are pregnant. Please come back after your baby is born and you have recovered.", 270),
    ("childbirth_6m", "You gave birth or are breastfeeding in the last 6 months.", 180),
]

_MESSAGES = {
    "age_low": f"You must be at least {MIN_AGE} years old to donate blood.",
    "age_high": f"You must be {MAX_AGE} years old or younger to register as a new donor.",
    "weight": f"You must weigh at least {int(MIN_WEIGHT_KG)} kg to donate blood.",
    "hb_male": f"Your haemoglobin must be at least {MIN_HB_MALE} g/dL.",
    "hb_female": f"Your haemoglobin must be at least {MIN_HB_FEMALE} g/dL.",
    "gap": "You donated blood too recently. A gap between donations is needed.",
    "gender": "Please choose male or female.",
}


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def evaluate_eligibility(answers: Dict, today: Optional[date] = None) -> Dict:
    """
    answers: {age, gender, weight_kg, hemoglobin (optional), last_donation_date (optional),
              <every key in YES_MEANS_NO / FEMALE_ONLY>: bool}
    Returns {eligible, permanent, reasons:[{code,message,defer_days}], retry_after_days, retry_after_date}
    """
    today = today or date.today()
    reasons: List[Dict] = []

    def add(code: str, message: str, defer_days: Optional[int]) -> None:
        reasons.append({"code": code, "message": message, "defer_days": defer_days})

    gender = (answers.get("gender") or "").lower()
    if gender not in ("male", "female"):
        add("gender", _MESSAGES["gender"], 0)

    try:
        age = int(answers.get("age"))
    except (TypeError, ValueError):
        age = None
    if age is None:
        add("age_low", _MESSAGES["age_low"], None)
    elif age < MIN_AGE:
        add("age_low", _MESSAGES["age_low"], (MIN_AGE - age) * 365)
    elif age > MAX_AGE:
        add("age_high", _MESSAGES["age_high"], None)

    try:
        weight = float(answers.get("weight_kg"))
    except (TypeError, ValueError):
        weight = None
    if weight is None or weight < MIN_WEIGHT_KG:
        add("weight", _MESSAGES["weight"], None if weight is None else 90)

    hb = answers.get("hemoglobin")
    if hb not in (None, ""):
        try:
            hb_value = float(hb)
            needed = MIN_HB_FEMALE if gender == "female" else MIN_HB_MALE
            if hb_value < needed:
                add("hb_female" if gender == "female" else "hb_male",
                    _MESSAGES["hb_female" if gender == "female" else "hb_male"], 60)
        except (TypeError, ValueError):
            pass

    last = _parse_date(answers.get("last_donation_date"))
    if last:
        wait = min_gap_days(gender)
        days_since = (today - last).days
        if days_since < wait:
            add("gap", _MESSAGES["gap"], wait - days_since)

    for key, message, defer in YES_MEANS_NO:
        if answers.get(key) is True:
            add(key, message, defer)
    if gender == "female":
        for key, message, defer in FEMALE_ONLY:
            if answers.get(key) is True:
                add(key, message, defer)

    permanent = any(r["defer_days"] is None for r in reasons)
    waits = [r["defer_days"] for r in reasons if r["defer_days"]]
    retry_days = None if permanent else (max(waits) if waits else None)
    return {
        "eligible": not reasons,
        "permanent": permanent,
        "reasons": reasons,
        "retry_after_days": retry_days,
        "retry_after_date": (today + timedelta(days=retry_days)).isoformat() if retry_days else None,
    }


def next_eligible_date(last_donation: Optional[datetime], gender: Optional[str]) -> Optional[date]:
    """The first day a donor may give whole blood again. None = already free to donate."""
    if not last_donation:
        return None
    return (last_donation + timedelta(days=min_gap_days(gender))).date()
