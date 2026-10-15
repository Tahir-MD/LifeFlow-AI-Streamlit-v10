"""
Start-up work for the Streamlit app: read secrets into environment variables (the LifeFlow backend
code reads its settings from the environment), create the database tables, and add the first data.
Nothing here imports the backend until secrets are loaded, because the backend reads settings at import time.
"""
import os


def load_secrets() -> None:
    """Copies Streamlit secrets (Cloud: App settings > Secrets, local: .streamlit/secrets.toml) into os.environ."""
    try:
        import streamlit as st
        for key in st.secrets:
            value = st.secrets[key]
            if isinstance(value, (str, int, float, bool)) and key not in os.environ:
                os.environ[key] = str(value)
    except Exception:  # noqa: BLE001 -- no secrets file is fine: local SQLite and no AI
        pass
    # Verification codes are never shown on screen unless LIFEFLOW_ENV is set to "development".
    os.environ.setdefault("LIFEFLOW_ENV", "production")


def init_database() -> None:
    """Creates tables, adds missing columns, the admin account, the emergency numbers and (optionally) demo data."""
    from app.database import Base, engine, SessionLocal
    from app.models import (  # noqa: F401 -- importing registers every table
        admin, audit_log, blood_batch, blood_transfer, camp, donation, donor, emergency_contact, hospital,
        inventory, notification, password_reset, phone_otp, push_subscription, rating, receiver, request,
        request_event, staff, visitor_log, weekly_report,
    )
    from app.utils.migrate import add_missing_columns
    from app.utils.security import hash_password
    from app.routes.directory_routes import seed_directory

    Base.metadata.create_all(bind=engine)
    add_missing_columns(engine, Base)

    email = os.environ.get("LIFEFLOW_ADMIN_EMAIL", "admin@lifeflow.com")
    password = os.environ.get("LIFEFLOW_ADMIN_PASSWORD", "Admin@123")
    db = SessionLocal()
    try:
        if not db.query(admin.Admin).filter(admin.Admin.email == email).first():
            db.add(admin.Admin(full_name="LifeFlow Admin", email=email, hashed_password=hash_password(password)))
            db.commit()
    finally:
        db.close()

    seed_directory()
    if os.environ.get("LIFEFLOW_SEED_DEMO", "1").lower() not in ("0", "false", "off", "no"):
        from ui.demo_data import seed_demo
        seed_demo()


def demo_enabled() -> bool:
    return os.environ.get("LIFEFLOW_SEED_DEMO", "1").lower() not in ("0", "false", "off", "no")
