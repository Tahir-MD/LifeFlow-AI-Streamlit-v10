"""Two-factor authentication (TOTP) setup for hospital and admin accounts."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.dependencies import get_current_hospital, get_current_admin
from app.utils.security import verify_password
from app.utils.totp import generate_secret, get_otpauth_uri, verify_totp

router = APIRouter(prefix="/2fa", tags=["Two-factor authentication"])


class TwoFactorEnableIn(BaseModel):
    code: str


class TwoFactorDisableIn(BaseModel):
    password: str


def _build_router_for(role: str, get_current_account):
    """Registers /2fa/{role}/setup, /enable, /disable, /status for one account type, to avoid repeating this four times."""

    @router.get(f"/{role}/status")
    def status_(account=Depends(get_current_account)):
        return {"two_factor_enabled": bool(account.two_factor_enabled)}

    @router.post(f"/{role}/setup")
    def setup(account=Depends(get_current_account), db: Session = Depends(get_db)):
        """Generates a new secret (not yet active) and the otpauth:// URI to render as a QR code."""
        if account.two_factor_enabled:
            raise HTTPException(status_code=400, detail="Two-factor authentication is already on. Disable it first to reset.")
        account.totp_secret = generate_secret()
        db.commit()
        account_label = getattr(account, "email", f"{role}-{account.id}")
        return {"secret": account.totp_secret, "otpauth_uri": get_otpauth_uri(account.totp_secret, account_label)}

    @router.post(f"/{role}/enable")
    def enable(payload: TwoFactorEnableIn, account=Depends(get_current_account), db: Session = Depends(get_db)):
        """Confirms the person's authenticator app is actually working before turning 2FA on for real."""
        if not account.totp_secret:
            raise HTTPException(status_code=400, detail="Call /2fa/setup first")
        if not verify_totp(account.totp_secret, payload.code):
            raise HTTPException(status_code=400, detail="Incorrect code -- check your authenticator app and try again")
        account.two_factor_enabled = True
        db.commit()
        return {"two_factor_enabled": True}

    @router.post(f"/{role}/disable")
    def disable(payload: TwoFactorDisableIn, account=Depends(get_current_account), db: Session = Depends(get_db)):
        if not verify_password(payload.password, account.hashed_password):
            raise HTTPException(status_code=400, detail="Incorrect password")
        account.two_factor_enabled = False
        account.totp_secret = None
        db.commit()
        return {"two_factor_enabled": False}


_build_router_for("hospital", get_current_hospital)
_build_router_for("admin", get_current_admin)
