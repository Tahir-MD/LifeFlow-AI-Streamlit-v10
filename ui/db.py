"""Small database helpers for the pages: one session per page run, and friendly error messages."""
from contextlib import contextmanager


@contextmanager
def session():
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def friendly_error(error: Exception) -> str:
    """Turns an API/validation exception into one short sentence a person can act on."""
    from fastapi import HTTPException
    from pydantic import ValidationError

    if isinstance(error, HTTPException):
        return str(error.detail)
    if isinstance(error, ValidationError):
        parts = []
        for item in error.errors():
            message = str(item.get("msg", "")).replace("Value error, ", "")
            loc = [str(x) for x in item.get("loc", ()) if x not in ("eligibility",)]
            parts.append(f"{loc[-1].replace('_', ' ').capitalize()}: {message}" if loc else message)
        return " ".join(parts) or "Please check the form."
    if isinstance(error, ValueError):
        return str(error)
    return "Something went wrong. Please try again."
