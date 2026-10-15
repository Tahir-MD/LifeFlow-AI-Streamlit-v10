"""Admin pages."""
import pandas as pd
import streamlit as st
from sqlalchemy import func

from app.models.donation import Donation
from app.models.donor import Donor
from app.models.hospital import Hospital
from app.models.receiver import Receiver
from app.models.request import BloodRequest
from app.routes.moderation_routes import DecisionIn, approve_request, reject_request, requests_to_review
from app.routes.ai_routes import platform_forecast
from app.routes import export_routes
from app.routes.admin_routes import (
    all_staff, approve_hospital, clear_donor, flag_donor, pending_donors, recent_audit_log, reject_hospital, staff_visitor_history, verify_audit_chain,
)
from app.routes.directory_routes import ContactIn, add_contact, approve_contact, delete_contact, pending_contacts
from app.services.push_service import is_push_configured
from app.services.ai_client import is_ai_configured
from app.services.delivery_service import delivery_status
from ui import accounts, exports, theme
from ui.db import friendly_error, session
from ui.i18n import t
from ui.report_view import weekly_report_view


def overview() -> None:
    theme.page_header(t("Admin overview"), t("The whole LifeFlow network at a glance."), "🛡️")
    with session() as db:
        me = accounts.load(db)
        if me is not None and getattr(me, "must_change_password", False):
            st.warning("🔐 " + t("You are using the first admin password. Open Account & security and change it before going public."))
        donors = db.query(Donor).count()
        hospitals = db.query(Hospital).count()
        patients = db.query(Receiver).count()
        requests = db.query(BloodRequest).count()
        open_req = db.query(BloodRequest).filter(BloodRequest.status == "open").count()
        held = db.query(BloodRequest).filter(BloodRequest.review_status.in_(["held", "flagged"])).count()
        units = db.query(func.coalesce(func.sum(Donation.units_donated), 0)).scalar() or 0
        pending = db.query(Hospital).filter(Hospital.is_verified == False).count()  # noqa: E712
        theme.stat_cards([
            ("🧑‍🤝‍🧑", donors, t("registered donors")), ("🏥", hospitals, t("partner hospitals")), ("🧑‍⚕️", patients, t("Patients")),
            ("🩸", requests, t("requests")), ("🟢", open_req, t("open requests")), ("💉", units, t("bags donated")),
            ("🕵️", held, t("Need review"), "warn" if held else "ok"), ("⏳", pending, t("Hospitals to verify"), "warn" if pending else "ok"),
        ])
        by_type = db.query(BloodRequest.blood_type_needed, func.count(BloodRequest.id)).group_by(BloodRequest.blood_type_needed).all()
        donors_by_type = db.query(Donor.blood_type, func.count(Donor.id)).group_by(Donor.blood_type).all()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**" + t("Requests by blood type") + "**")
            if by_type:
                st.bar_chart(pd.DataFrame(by_type, columns=["Blood type", "Requests"]).set_index("Blood type"), color="#B3202F")
            else:
                st.caption(t("No requests yet."))
        with c2:
            st.markdown("**" + t("Donors by blood type") + "**")
            if donors_by_type:
                st.bar_chart(pd.DataFrame(donors_by_type, columns=["Blood type", "Donors"]).set_index("Blood type"), color="#F26B5B")
            else:
                st.caption(t("No donors yet."))
        st.markdown("**" + t("Shortage forecast (all hospitals)") + "**")
        forecast = platform_forecast(db, None)
        frame = pd.DataFrame([e.model_dump() for e in forecast.entries])
        if not frame.empty:
            st.dataframe(frame.rename(columns={"blood_type": "Blood", "average_daily_demand": "Daily demand", "trend": "Trend", "current_stock": "Stock",
                                               "projected_demand_next_7_days": "Next 7 days", "days_until_shortage": "Days left", "risk_level": "Risk"}), hide_index=True)
    theme.footer()


def approvals() -> None:
    theme.page_header(t("Hospital licence verification"), t("Check each licence, then approve or reject."), "✅")
    with session() as db:
        admin = accounts.load(db)
        pending = db.query(Hospital).filter(Hospital.is_verified == False).order_by(Hospital.created_at.desc()).all()  # noqa: E712
        if not pending:
            theme.empty(t("No hospitals waiting for verification."), "✅")
        for h in pending:
            with st.container(border=True):
                st.markdown(f'<div class="lf-title">{theme.esc(h.name)}</div><div class="lf-sub">{t("licence")} {theme.esc(h.license_number)} · '
                            f'{theme.esc(h.phone_number)} · {theme.esc(h.city)}</div>', unsafe_allow_html=True)
                c1, c2, _ = st.columns([1, 1, 4])
                if c1.button(t("Approve"), key=f"ap_{h.id}", type="primary"):
                    approve_hospital(h.id, db, admin)
                    st.rerun()
                if c2.button(t("Reject"), key=f"rj_{h.id}"):
                    reject_hospital(h.id, db, admin)
                    st.rerun()
    theme.footer()


def review() -> None:
    theme.page_header(t("Request review"), t("Requests the fake-request check held or flagged."), "🕵️")
    with session() as db:
        admin = accounts.load(db)
        items = requests_to_review(db, admin)
        if not items:
            theme.empty(t("Nothing to review. All requests look fine."), "🎉")
        for item in items:
            r = item.request
            with st.container(border=True):
                st.markdown(f'<div class="lf-row"><div class="lf-title">{theme.blood_badge(r.blood_type_needed)} {r.units_needed} bags · '
                            f'{theme.esc(r.requester_name)} · #{r.id}</div><div>{theme.status_badge(item.review_status)} '
                            f'{theme.badge(f"risk {item.fraud_score}", "neutral")}</div></div>', unsafe_allow_html=True)
                for reason in item.reasons:
                    st.caption("⚠️ " + reason)
                c1, c2, _ = st.columns([1, 1, 4])
                if c1.button(t("Approve"), key=f"rv_ok_{r.id}", type="primary"):
                    try:
                        approve_request(r.id, db, admin)
                        st.rerun()
                    except Exception as error:  # noqa: BLE001
                        st.error(friendly_error(error))
                if c2.button(t("Reject"), key=f"rv_no_{r.id}"):
                    reject_request(r.id, DecisionIn(note=None), db, admin)
                    st.rerun()
    theme.footer()


def data_tables() -> None:
    theme.page_header(t("All data"), t("Browse and download everything."), "🗂️")
    with session() as db:
        tabs = st.tabs([t("Donors"), t("Hospitals"), t("Patients"), t("requests"), t("donations")])
        sets = [
            (Donor, ["id", "full_name", "email", "blood_type", "city", "points", "is_eligible", "last_donation_date", "created_at"]),
            (Hospital, ["id", "name", "email", "license_number", "city", "is_verified", "created_at"]),
            (Receiver, ["id", "full_name", "email", "phone_number", "city", "created_at"]),
            (BloodRequest, ["id", "requester_type", "blood_type_needed", "units_needed", "units_fulfilled", "status", "urgency_type", "review_status", "created_at"]),
            (Donation, ["id", "donor_id", "request_id", "units_donated", "donated_at"]),
        ]
        for tab, (model, cols) in zip(tabs, sets):
            with tab:
                rows = db.query(model).order_by(model.id.desc()).limit(2000).all()
                frame = pd.DataFrame([{c: getattr(r, c) for c in cols} for r in rows], columns=cols)
                st.dataframe(frame, hide_index=True)
                st.download_button("📊 " + t("Download CSV"), frame.to_csv(index=False).encode("utf-8"), file_name=f"{model.__tablename__}.csv",
                                   mime="text/csv", key=f"dl_{model.__tablename__}")
        admin = accounts.load(db)
        st.divider()
        exports.export_buttons("ax", lambda d, fmt: export_routes.export_admin(fmt, d, admin), "Full report for health authorities")
    theme.footer()


def weekly_report() -> None:
    theme.page_header(t("Weekly report"), t("Platform-wide summary."), "📈")
    with session() as db:
        weekly_report_view(db, "platform", None, key="awr")
    theme.footer()


def system() -> None:
    theme.page_header(t("System status"), t("What is switched on in this deployment."), "⚙️")
    st.markdown(("🟢 " if is_ai_configured() else "⚪ ") + t("AI features (voice, slip scanner, AI report text)") + (" — on" if is_ai_configured() else " — add GROQ_API_KEY in Secrets"))
    status = delivery_status()
    status["push_configured"] = is_push_configured()
    st.json(status)
    st.caption(t("Set the secrets listed in .streamlit/secrets.toml.example to turn on email, SMS and WhatsApp alerts."))
    theme.footer()


def governance() -> None:
    theme.page_header(t("Governance"), t("Medical clearance, staff, the audit trail and public emergency numbers."), "⚖️")
    tabs = st.tabs([t("Donor clearance"), t("Hospital staff"), t("Audit trail"), t("Emergency numbers")])
    with session() as db:
        admin = accounts.load(db)
        with tabs[0]:
            waiting = pending_donors(db, admin)
            if not waiting:
                theme.empty(t("Nobody is waiting for medical clearance."), "✅")
            for d in waiting[:100]:
                with st.container(border=True):
                    st.markdown(f"**{theme.esc(d.full_name)}** {theme.blood_badge(d.blood_type)} · {d.age or '-'} y · {theme.esc(d.city or '')}", unsafe_allow_html=True)
                    note = st.text_input(t("Note, optional"), key=f"gn_{d.id}", max_chars=300)
                    c1, c2, _ = st.columns([1, 1, 3])
                    if c1.button("✅ " + t("Clear"), key=f"gc_{d.id}", type="primary"):
                        clear_donor(d.id, note, db, admin)
                        st.rerun()
                    if c2.button("⛔ " + t("Not eligible"), key=f"gf_{d.id}"):
                        flag_donor(d.id, note, db, admin)
                        st.rerun()
        with tabs[1]:
            staff_rows = all_staff(db, admin)
            if not staff_rows:
                theme.empty(t("No staff logins yet."), "👥")
            else:
                frame = pd.DataFrame([{"ID": s.id, t("Name"): s.full_name, t("Email"): s.email, t("Hospital"): s.hospital_id, t("Shift"): s.shift, t("Role"): s.role} for s in staff_rows])
                st.dataframe(frame, hide_index=True)
                pick = st.selectbox(t("See one person's record"), staff_rows, format_func=lambda s: f"{s.full_name} ({s.shift})", key="gs_pick")
                entries = staff_visitor_history(pick.id, db, admin)
                if entries:
                    st.dataframe(pd.DataFrame([{t("Time"): e.logged_at.strftime("%d %b %H:%M"), t("Type"): e.visitor_type, t("Name"): e.full_name,
                                                t("Blood type"): e.blood_type, t("Notes"): e.notes} for e in entries]), hide_index=True)
                else:
                    st.caption(t("Nothing logged yet."))
        with tabs[2]:
            check = verify_audit_chain(db, admin)
            ok = check.get("valid", check.get("ok", False))
            (st.success if ok else st.error)(("✅ " if ok else "⚠️ ") + t("Audit chain") + f": {check}")
            log = recent_audit_log(200, db, admin)
            st.dataframe(pd.DataFrame([{"#": e["id"], t("Time"): e["created_at"], t("Event"): e["event_type"], t("Who"): f"{e['actor_type']} {e['actor_id'] or ''}",
                                        t("Details"): e["payload"]} for e in log]), hide_index=True)
        with tabs[3]:
            for c in pending_contacts(db, admin):
                c1, c2, c3 = st.columns([4, 1, 1])
                c1.markdown(f"**{theme.esc(c.name)}** · {theme.esc(c.phone_number)} · {theme.esc(c.city or '')} ({c.category})")
                if c2.button(t("Approve"), key=f"ca_{c.id}", type="primary"):
                    approve_contact(c.id, db, admin)
                    st.rerun()
                if c3.button(t("Remove"), key=f"cd_{c.id}"):
                    delete_contact(c.id, db, ("admin", admin.id))
                    st.rerun()
            with st.expander("➕ " + t("Add a public number")):
                with st.form("gc_new", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    name = c1.text_input(t("Name"))
                    category = c2.selectbox(t("Type"), ["ambulance", "emergency", "blood_bank", "hospital", "police", "fire", "helpline"])
                    c3, c4 = st.columns(2)
                    phone = c3.text_input(t("Phone number"))
                    city = c4.text_input(t("City"), help=t("Leave empty for a national number"))
                    go = st.form_submit_button(t("Add number"), type="primary")
                if go:
                    try:
                        add_contact(ContactIn(name=name, category=category, phone_number=phone, city=city or None, is_national=not city.strip()), db, ("admin", admin.id))
                        st.success("✅ " + t("Added."))
                    except Exception as error:  # noqa: BLE001
                        st.error(friendly_error(error))
    theme.footer()


