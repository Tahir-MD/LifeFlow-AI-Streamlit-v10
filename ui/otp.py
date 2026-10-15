"""Phone / email verification with a 6-digit code (same service as the web app: app/services/otp_service.py)."""
import os
from typing import Optional

import streamlit as st

from ui.db import friendly_error, session
from ui.i18n import t


def channels() -> dict:
    from app.routes.otp_routes import available_channels
    return available_channels()


def required() -> bool:
    """LIFEFLOW_REQUIRE_OTP = 1 (always) / 0 (never) / auto (default: only when email, SMS or WhatsApp delivery is set up)."""
    setting = os.environ.get("LIFEFLOW_REQUIRE_OTP", "auto").strip().lower()
    if setting in ("0", "false", "no", "off"):
        return False
    if setting in ("1", "true", "yes", "on"):
        return True
    return any(channels().values())


def verify_box(key: str, phone: str, email: str) -> Optional[str]:
    """Shows 'send code' and 'check code'. Returns the proof token once the code was accepted, otherwise None."""
    from app.services.otp_service import send_code, verify_code
    from app.utils.validators import validate_phone

    if not required():
        return "streamlit"
    state = st.session_state.setdefault(key, {})
    available = [name for name, on in channels().items() if on] or ["email"]
    labels = {"email": t("Email"), "sms": "SMS", "whatsapp": "WhatsApp"}
    with st.container(border=True):
        st.markdown("##### 🔐 " + t("Verify your contact"))
        st.caption(t("We send a 6-digit code. This stops anyone from signing up with a number or email they do not own."))
        channel = st.radio(t("Send the code by"), available, format_func=lambda c: labels[c], horizontal=True, key=key + "_ch")
        try:
            contact = email.strip().lower() if channel == "email" else validate_phone(phone)
        except Exception:  # noqa: BLE001
            contact = ""
        if state.get("contact") and state.get("contact") != contact:
            state.clear()   # the number or email was changed after the code was sent
        if state.get("token"):
            st.success("✅ " + t("Verified."))
            return state["token"]
        if st.button(t("Send code"), key=key + "_send", disabled=not contact):
            try:
                with session() as db:
                    dev_code = send_code(db, contact, channel)
                state["contact"] = contact
                st.success(t("If the details are correct, a 6-digit code has been sent."))
                if dev_code:
                    st.info(f"{t('Test mode code')}: **{dev_code}**")
            except Exception as error:  # noqa: BLE001
                st.error(friendly_error(error))
        if not contact:
            st.caption(t("Fill in the phone number or email above first."))
        if state.get("contact"):
            code = st.text_input(t("6-digit code"), key=key + "_code", max_chars=6)
            if st.button(t("Check code"), key=key + "_check", type="primary"):
                try:
                    with session() as db:
                        state["token"] = verify_code(db, contact, code.strip())
                    st.rerun()
                except Exception as error:  # noqa: BLE001
                    st.error(friendly_error(error))
    return None
