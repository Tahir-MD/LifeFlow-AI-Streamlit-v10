"""
Shared input checks used by every sign-up / account form.

Keeping them in one place means donor, patient, hospital, staff and
admin forms all follow exactly the same rules, and the frontend
(src/utils/validators.js) mirrors these same rules so people see the
problem while typing -- the server still re-checks everything.
"""
import re
from typing import Optional

# Letters of ANY language (English, Urdu, Arabic, Hindi...), spaces and . ' - only. No digits.
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ .'\-\u2019][^\W\d_]+)*\.?$", re.UNICODE)
# Hospital / place names may also contain digits and a few symbols (e.g. "Aga Khan Hospital No. 2").
_ORG_NAME_RE = re.compile(r"^[\w][\w &.,'\-\u2019()/]{1,119}$", re.UNICODE)
# +<country code><number>, 8 to 15 digits in total, optional single spaces.
_PHONE_RE = re.compile(r"^\+[1-9]\d{0,3}[ ]?\d{6,12}$")


def validate_password_strength(password: str) -> str:
    problems = []
    if len(password) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[A-Z]", password):
        problems.append("one capital letter (A-Z)")
    if not re.search(r"[a-z]", password):
        problems.append("one small letter (a-z)")
    if not re.search(r"\d", password):
        problems.append("one number (0-9)")
    if not re.search(r"[^A-Za-z0-9]", password):
        problems.append("one special character (like @ # $ !)")
    if problems:
        raise ValueError("Password needs " + ", ".join(problems) + ".")
    return password


def validate_person_name(value: str, field: str = "Name") -> str:
    value = " ".join((value or "").split())
    if len(value) < 2:
        raise ValueError(f"{field} must be at least 2 letters.")
    if len(value) > 80:
        raise ValueError(f"{field} is too long.")
    if not _NAME_RE.match(value):
        raise ValueError(f"{field} can only have letters and spaces - no numbers or symbols.")
    return value


def validate_org_name(value: str, field: str = "Name") -> str:
    value = " ".join((value or "").split())
    if len(value) < 3:
        raise ValueError(f"{field} must be at least 3 characters.")
    if not _ORG_NAME_RE.match(value) or not re.search(r"[^\W\d_]", value, re.UNICODE):
        raise ValueError(f"{field} has characters that are not allowed.")
    return value


def validate_phone(value: str, field: str = "Phone number") -> str:
    cleaned = re.sub(r"[\s\-()]", "", value or "")
    if not cleaned.startswith("+"):
        raise ValueError(f"{field} must start with the country code, like +92.")
    digits = cleaned[1:]
    if not digits.isdigit() or not (8 <= len(digits) <= 15):
        raise ValueError(f"{field} must have 8 to 15 digits including the country code.")
    return cleaned


def validate_phone_loose(value: str, field: str = "Phone number") -> str:
    """For emergency directories: short national numbers like 1122 or 115 are allowed, with or without +."""
    cleaned = re.sub(r"[\s\-()]", "", value or "")
    digits = cleaned[1:] if cleaned.startswith("+") else cleaned
    if not digits.isdigit() or not (3 <= len(digits) <= 15):
        raise ValueError(f"{field} must have 3 to 15 digits.")
    return cleaned


def validate_optional_phone(value: Optional[str], field: str = "Phone number") -> Optional[str]:
    if value is None or not value.strip():
        return None
    return validate_phone(value, field)


def validate_place_text(value: Optional[str], field: str, required: bool = False) -> Optional[str]:
    """Village / area / city / province: letters, digits, spaces and . , ' - / # only."""
    value = " ".join((value or "").split())
    if not value:
        if required:
            raise ValueError(f"{field} is required.")
        return None
    if len(value) > 100:
        raise ValueError(f"{field} is too long.")
    if not re.match(r"^[\w .,'\-\u2019/#()]+$", value, re.UNICODE):
        raise ValueError(f"{field} has characters that are not allowed.")
    return value


def validate_cnic(value: str) -> str:
    digits = re.sub(r"[\s\-]", "", value or "")
    if not re.fullmatch(r"\d{13}", digits):
        raise ValueError("CNIC must be 13 digits (like 42101-1234567-1).")
    return f"{digits[:5]}-{digits[5:12]}-{digits[12]}"
