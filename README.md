# 🩸 LifeFlow Blood Network (Streamlit Edition, v10)

A blood-donation platform that connects donors, patients and hospitals. It includes AI tools: weekly reports, ambulance ETA, camp forecasting, donor response prediction, an Urdu/Sindhi voice assistant, a prescription scanner and a conversational health check.

Engineered by **Tahir Mahmood** · [GitHub @Tahir-MD](https://github.com/Tahir-MD)

## Features
- Roles: donor, patient, hospital, **hospital staff** (receptionist, lab technician, doctor, manager) and admin, each with its own pages
- **Welcome page** that opens first, then the rest of the app; icons on form fields, tabs, buttons and the footer links
- **Animated robot chatbot** with a "Hello" bubble in the bottom-right corner of every page (full AI with `GROQ_API_KEY`, built-in answers without it)
- **Sign-up verification codes (OTP)** by email, SMS or WhatsApp, and **forgot password** for every account type
- **Hospital transfers** (ask another hospital for bags, approve, confirm arrival), **bulk messages** to donors, **staff logins and shifts**
- **Donation certificates** (PDF with QR) and a **donor QR card**; **camp QR check-in** with camera scan, walk-ins and attendance sheet
- Donor screening by doctors, ratings, live tracking ("on the way" / "arrived"), nearby map, own emergency numbers
- Admin governance: donor clearance, staff overview, tamper-evident audit trail, emergency-number approvals, two-step login (2FA)
- Excel and PDF reports for donors, hospitals and the admin
- Blood requests with SOS, matching, accept and donate flow, and a timeline
- Hospital stock with batches and expiry, camps with RSVP, and forecasts
- Admin: approvals, request review, data tables with CSV export, weekly report (Excel/PDF)
- Languages: English, اردو, سنڌي (RTL supported)
- AI features use Groq when `GROQ_API_KEY` is set and fall back to rule-based logic otherwise

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then edit it
streamlit run streamlit_app.py
```
By default it uses a local SQLite file and seeds demo data on an empty database.

## Deploy on Streamlit Community Cloud
1. Push this repo to GitHub.
2. Go to share.streamlit.io → **New app** → pick the repo, branch `main`, main file `streamlit_app.py`.
3. **Advanced settings → Secrets**: paste the contents of `.streamlit/secrets.toml.example` and edit them.
4. Streamlit Cloud's disk is **ephemeral**, so use a free Postgres (Neon or Supabase) and set `LIFEFLOW_DATABASE_URL = "postgresql://user:pass@host/db?sslmode=require"`.
5. Deploy.

## Demo accounts (password `Demo@1234`)
`donor@demo.lifeflow`, `patient@demo.lifeflow`, `hospital@demo.lifeflow`, `staff@demo.lifeflow` (manager).
Admin comes from `LIFEFLOW_ADMIN_EMAIL` / `LIFEFLOW_ADMIN_PASSWORD`.

## Before going public
- Change the admin password and set a long random `LIFEFLOW_SECRET_KEY`.
- Set `LIFEFLOW_SEED_DEMO = "0"` to stop demo data from being seeded.
- Never commit `.streamlit/secrets.toml` (it is in `.gitignore`).

## Limitations
- Browser push notifications are not available: Streamlit cannot register the service worker they need. In-app, email, SMS and WhatsApp alerts work.
- Camera QR scanning needs `opencv-python-headless`; if it cannot read a code you can type the donor number instead.
- OTP is switched on automatically only when email, SMS or WhatsApp delivery is configured (`LIFEFLOW_REQUIRE_OTP`).
- Urdu and Sindhi translations cover the original screens; some newer labels still show in English.
- The app has been checked with static tests only; run it once and report anything odd.

## Tests
```bash
pip install -r requirements-dev.txt && pytest -q
```
