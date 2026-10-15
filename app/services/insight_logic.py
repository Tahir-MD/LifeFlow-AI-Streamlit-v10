"""
Pure, database-free logic for the v6 AI features, so it can be unit tested on its own:

* estimate_travel         -- road distance and ETA for a donor / ambulance
* predict_response        -- how likely a donor is to accept, and how fast (explainable score)
* predict_camp            -- expected turnout and the staff / beds / bags a camp needs
* interpret_yes_no        -- understands yes / no in English, Roman Urdu, Urdu and Sindhi
* extract_number          -- pulls a number out of a spoken or typed answer (also Urdu digits)
* clean_request_fields    -- validates what a voice note or prescription photo produced

Everything here is a transparent formula (no hidden model), and everything only SUGGESTS -- a person
always confirms before anything is saved or sent.
"""
import math
import re
from typing import Dict, List, Optional

VALID_BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

# --------------------------------------------------------------------------------------------
# 1. Travel time
# --------------------------------------------------------------------------------------------
ROAD_FACTOR = 1.35            # roads are longer than the straight line between two points
SPEEDS_KMH = {"ambulance": 45.0, "car": 32.0, "bike": 24.0, "walk": 5.0}


def estimate_travel(straight_km: float, mode: str = "car") -> Dict:
    """Straight-line km -> estimated road km and minutes. Rough on purpose: a map app gives live traffic."""
    straight_km = max(float(straight_km or 0), 0.0)
    road_km = straight_km * ROAD_FACTOR
    speed = SPEEDS_KMH.get(mode, SPEEDS_KMH["car"])
    minutes = road_km / speed * 60.0
    return {"mode": mode, "road_km": round(road_km, 1), "minutes": max(1, int(round(minutes)))}


def format_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def recommend_transport(straight_km: float, is_emergency: bool) -> Dict:
    """Which way should the blood (or the patient) travel? Returns the options plus one recommendation."""
    options = [dict(estimate_travel(straight_km, m)) for m in ("ambulance", "car", "bike")]
    for option in options:
        option["label"] = {"ambulance": "Ambulance", "car": "Car / taxi", "bike": "Motorbike / rickshaw"}[option["mode"]]
    if straight_km <= 1.0:
        pick = "walk" if not is_emergency else "bike"
    elif is_emergency and straight_km >= 3:
        pick = "ambulance"
    elif straight_km >= 15:
        pick = "car"
    else:
        pick = "bike" if is_emergency else "car"
    if pick == "walk":
        options.append({**estimate_travel(straight_km, "walk"), "label": "On foot"})
    return {"options": options, "recommended_mode": pick}


# --------------------------------------------------------------------------------------------
# 2. Donor response prediction
# --------------------------------------------------------------------------------------------
def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def predict_response(
    alerts_received: int,
    donations_made: int,
    distance_km: float,
    days_since_last_donation: Optional[int],
    hour_of_day: int,
    is_emergency: bool,
    average_rating: Optional[float] = None,
    max_distance_km: float = 50.0,
) -> Dict:
    """
    Probability (0..1) that a donor accepts, and a guess of how quickly.
    Starts from the donor's own history (smoothed so new donors sit near 50%), then adjusts for
    distance, how recently they gave, time of day and urgency. Each adjustment is listed in `reasons`.
    """
    reasons: List[str] = []
    history_rate = (donations_made + 1.0) / (max(alerts_received, donations_made) + 2.0)
    score = math.log(history_rate / (1 - history_rate))
    if alerts_received or donations_made:
        reasons.append(f"answered {donations_made} of {alerts_received} past alerts")
    else:
        reasons.append("new donor, no history yet")

    distance_ratio = min(max(distance_km, 0.0) / max(max_distance_km, 1.0), 1.0)
    score += (0.5 - distance_ratio) * 1.6
    reasons.append(f"{distance_km:.1f} km away")

    if days_since_last_donation is not None:
        if days_since_last_donation < 120:
            score -= 0.2
        elif days_since_last_donation > 365:
            score -= 0.4
            reasons.append("has not donated for over a year")
        else:
            score += 0.3
            reasons.append("recently active donor")

    if 8 <= hour_of_day <= 21:
        score += 0.25
    else:
        score -= 0.5
        reasons.append("late night or very early, slower replies are likely")

    if is_emergency:
        score += 0.15
    if average_rating is not None:
        score += (average_rating - 3.5) / 1.5 * 0.3
        if average_rating >= 4.5:
            reasons.append("rated very highly by past patients")

    probability = round(_logistic(score), 2)
    if probability >= 0.7 and distance_km <= 10:
        speed = "fast"
    elif probability >= 0.45:
        speed = "normal"
    else:
        speed = "slow"
    return {"probability": probability, "speed": speed, "reasons": reasons}


def pick_alert_order(candidates: List[Dict], units_needed: int, safety: float = 1.3) -> Dict:
    """Sort by response probability (then distance); keep alerting until expected arrivals cover the need."""
    ordered = sorted(candidates, key=lambda c: (-c["probability"], c["distance_km"]))
    target = max(units_needed, 1) * safety
    expected, chosen = 0.0, []
    for candidate in ordered:
        if expected >= target:
            break
        expected += candidate["probability"]
        chosen.append(candidate)
    return {"ranked": ordered, "alert_first": chosen, "expected_acceptances": round(expected, 2)}


# --------------------------------------------------------------------------------------------
# 3. Camp turnout and staffing
# --------------------------------------------------------------------------------------------
DEFAULT_SHOW_RATE = 0.55      # share of registered people who really come, when we have no history
WALK_IN_PER_REGISTERED = 0.2
NEARBY_CONVERSION = 0.04      # share of nearby eligible donors who drop in because of a reminder
DEFERRAL_RATE = 0.12          # share of arrivals the doctor turns away on the day


def predict_camp(
    registered: int,
    past_show_rate: Optional[float],
    nearby_eligible: int,
    camp_hours: float = 6.0,
    days_until: Optional[int] = None,
) -> Dict:
    show_rate = past_show_rate if past_show_rate is not None else DEFAULT_SHOW_RATE
    show_rate = min(max(show_rate, 0.15), 0.95)
    from_registered = registered * show_rate
    walk_ins = registered * WALK_IN_PER_REGISTERED + nearby_eligible * NEARBY_CONVERSION
    expected = from_registered + walk_ins
    low, high = expected * 0.7, expected * 1.3
    expected_i = int(round(expected))
    bags = int(math.floor(expected * (1 - DEFERRAL_RATE)))
    camp_hours = max(camp_hours, 1.0)
    peak_per_hour = max(expected / camp_hours * 1.5, 1.0)       # the first hours are busier
    beds = max(2, int(math.ceil(peak_per_hour / 3.0)))          # a donation takes ~20 minutes of bed time
    staff = {
        "phlebotomists": max(1, int(math.ceil(beds / 2.0))),
        "screening_doctors_or_nurses": max(1, int(math.ceil(peak_per_hour / 10.0))),
        "registration_desk": max(1, int(math.ceil(peak_per_hour / 25.0))),
        "volunteers": max(2, int(math.ceil(expected / 20.0))),
    }
    notes = []
    if registered < 10 and (days_until or 0) > 3:
        notes.append("Few registrations so far. Send a message to nearby donors to raise turnout.")
    if past_show_rate is None:
        notes.append(f"No past camps to learn from, so a standard {int(DEFAULT_SHOW_RATE * 100)}% show-up rate is used.")
    notes.append("Walk-ins come in waves. Keep one spare bed and a few extra bags and juice packs.")
    return {
        "expected_turnout": expected_i,
        "range_low": int(round(low)), "range_high": int(round(high)),
        "expected_bags": bags,
        "show_rate_used": round(show_rate, 2),
        "beds": beds, "staff": staff,
        "staff_total": sum(staff.values()),
        "notes": notes,
    }


# --------------------------------------------------------------------------------------------
# 4. Understanding spoken / typed answers (English, Roman Urdu, Urdu, Sindhi)
# --------------------------------------------------------------------------------------------
_YES = {
    "yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "true", "correct", "haan", "han", "ha", "haa", "ji", "jee",
    "ji haan", "ji han", "bilkul", "hanji", "ہاں", "ہاں جی", "جی", "جی ہاں", "بالکل", "ہا", "ها", "هاڻي", "ها ادا",
    "ها سائين", "ها ڙي", "هائو", "جي", "جي ها", "بلڪل",
}
_NO = {
    "no", "n", "nope", "nah", "never", "false", "nahi", "nahin", "nai", "nahi ji", "na", "nahee", "نہیں", "نہی", "نا", "نہیں جی",
    "کبھی نہیں", "نه", "نہ", "ناهي", "نه ادا", "نه سائين", "ناھي", "نه ڙي", "ڪڏهن به نه", "نا ادا",
}
_URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def interpret_yes_no(text: str) -> Optional[bool]:
    """True = yes, False = no, None = not sure (ask again or let the AI help)."""
    if not text:
        return None
    cleaned = re.sub(r"[^\w\s؀-ۿ]", " ", str(text).lower()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned in _YES:
        return True
    if cleaned in _NO:
        return False
    words = cleaned.split()
    if not words:
        return None
    has_no = any(w in _NO for w in words) or "not" in words or "don't" in words
    has_yes = any(w in _YES for w in words)
    if has_no and not has_yes:
        return False
    if has_yes and not has_no:
        return True
    return None


def extract_number(text: str) -> Optional[float]:
    if text is None:
        return None
    normalised = str(text).translate(_URDU_DIGITS).replace("٫", ".").replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", normalised)
    return float(match.group()) if match else None


def interpret_gender(text: str) -> Optional[str]:
    cleaned = (text or "").strip().lower()
    if any(w in cleaned for w in ("female", "woman", "girl", "aurat", "larki", "خاتون", "عورت", "لڑکی", "زال", "ڇوڪري", "مائي")):
        return "female"
    if any(w in cleaned for w in ("male", "man", "boy", "mard", "larka", "مرد", "لڑکا", "ڇوڪرو", "پيو")):
        return "male"
    return None


# --------------------------------------------------------------------------------------------
# 5. Cleaning what the AI read from a voice note or a prescription photo
# --------------------------------------------------------------------------------------------
_BLOOD_WORDS = [
    (r"\bab\s*(\+|pos|positive)", "AB+"), (r"\bab\s*(-|−|neg|negative)", "AB-"),
    (r"\bo\s*(\+|pos|positive)", "O+"), (r"\bo\s*(-|−|neg|negative)", "O-"),
    (r"\ba\s*(\+|pos|positive)", "A+"), (r"\ba\s*(-|−|neg|negative)", "A-"),
    (r"\bb\s*(\+|pos|positive)", "B+"), (r"\bb\s*(-|−|neg|negative)", "B-"),
]


def normalise_blood_type(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().upper().replace("−", "-").replace(" ", "")
    if text in VALID_BLOOD_TYPES:
        return text
    lowered = str(value).strip().lower()
    for pattern, result in _BLOOD_WORDS:
        if re.search(pattern, lowered):
            return result
    return None


def clean_request_fields(raw: Dict) -> Dict:
    """Make AI output safe to drop into the request form. Anything doubtful becomes None."""
    raw = raw or {}
    units = raw.get("units_needed")
    try:
        units = int(float(units))
    except (TypeError, ValueError):
        units = None
    if units is not None and not (1 <= units <= 20):
        units = None
    age = raw.get("patient_age")
    try:
        age = int(float(age))
    except (TypeError, ValueError):
        age = None
    if age is not None and not (0 <= age <= 120):
        age = None
    gender = str(raw.get("patient_gender") or "").strip().capitalize()
    if gender not in ("Male", "Female", "Other"):
        gender = None
    urgency = raw.get("urgency_type")
    if urgency not in ("emergency", "days", "months"):
        urgency = None
    value = raw.get("urgency_value")
    try:
        value = int(float(value)) if urgency in ("days", "months") else None
    except (TypeError, ValueError):
        value = None
    name = re.sub(r"[^A-Za-z؀-ۿ\s.'-]", "", str(raw.get("patient_name") or "")).strip()[:60] or None
    return {
        "blood_type_needed": normalise_blood_type(raw.get("blood_type_needed")),
        "units_needed": units,
        "patient_name": name,
        "patient_age": age,
        "patient_gender": gender,
        "medical_reason": (str(raw.get("medical_reason")).strip()[:120] if raw.get("medical_reason") else None),
        "urgency_type": urgency,
        "urgency_value": value,
        "hospital_name": (str(raw.get("hospital_name")).strip()[:120] if raw.get("hospital_name") else None),
    }


# --------------------------------------------------------------------------------------------
# 6. "When did you last donate?" in plain words
# --------------------------------------------------------------------------------------------
_NEVER_WORDS = ("never", "kabhi nahi", "kabhi nahin", "nahi kiya", "first time", "pehli", "کبھی نہیں", "پہلی", "ڪڏهن به نه", "پهريون")
_UNIT_DAYS = [
    (("year", "saal", "sal", "سال", "ورهه", "ورھہ"), 365),
    (("month", "mahin", "mah", "مہینے", "مہینہ", "ماہ", "مهينا", "مهينو", "مھينا"), 30),
    (("week", "hafta", "hafte", "ہفتے", "ہفتہ", "هفتا", "هفتو"), 7),
    (("day", "din", "دن", "ڏينهن", "ڏهاڙا"), 1),
]


def interpret_last_donation(text: str, today=None):
    """
    Returns ("never", None), ("date", "YYYY-MM-DD") or ("unknown", None).
    Understands "3 months ago", "2 mahine pehle", "6 ہفتے پہلے", an ISO date, or "never".
    """
    from datetime import date, timedelta
    today = today or date.today()
    raw = (text or "").strip().lower()
    if not raw:
        return "unknown", None
    if any(w in raw for w in _NEVER_WORDS):
        return "never", None
    iso = re.search(r"(20\d\d)-(\d\d)-(\d\d)", raw)
    if iso:
        try:
            parsed = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            if parsed <= today:
                return "date", parsed.isoformat()
        except ValueError:
            pass
    amount = extract_number(raw)
    if amount is None:
        if any(w in raw for w in ("yesterday", "kal", "کل")):
            return "date", (today - timedelta(days=1)).isoformat()
        return "unknown", None
    for words, days in _UNIT_DAYS:
        if any(w in raw for w in words):
            return "date", (today - timedelta(days=int(amount * days))).isoformat()
    return "unknown", None
