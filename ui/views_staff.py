"""Pages for hospital staff (receptionist, lab technician, doctor, manager). What shows up depends on the role."""
import pandas as pd
import streamlit as st

from app.routes.staff_routes import ScreeningDecision, doctor_clear_donor, doctor_flag_donor, donors_waiting_for_screening, log_visitor, my_visitor_entries
from app.schemas.visitor_schema import VisitorEntryCreate
from app.services.export_service import build_pdf
from app.utils.permissions import ROLE_LABELS, permissions_for
from ui import accounts, theme, views_hospital, views_hospital_extra, widgets
from ui.db import friendly_error, session
from ui.i18n import t


def permissions() -> set:
    """What the signed-in staff member may do (used to decide which pages to show)."""
    with session() as db:
        staff = accounts.load(db)
        return set(permissions_for(staff.role)) if staff else set()


def dashboard() -> None:
    with session() as db:
        staff = accounts.load(db)
        hospital = accounts.acting_hospital(db)
        theme.page_header(f"{t('Welcome')}, {staff.full_name.split()[0]}", f"{hospital.name} · {staff.shift} · {t(ROLE_LABELS.get(staff.role, 'Receptionist'))}", "🧑‍⚕️")
        st.caption(t("You can") + ": " + ", ".join(permissions_for(staff.role)))
        if "log_visitors" not in permissions_for(staff.role):
            st.info(t("Your role cannot log visitors."))
        else:
            st.subheader(t("Log a donor or patient you attended to"))
            with st.form("visit_new", clear_on_submit=True):
                c1, c2 = st.columns(2)
                kind = c1.radio(t("Who"), ["donor", "patient"], format_func=lambda k: t(k.capitalize()), horizontal=True)
                name = c2.text_input(t("Full name"))
                c3, c4, c5 = st.columns(3)
                blood = c3.selectbox(t("Blood type"), [""] + widgets.BLOOD_TYPES)
                phone = c4.text_input(t("Phone number, optional"))
                origin = c5.text_input(t("Coming from, optional"))
                notes = st.text_input(t("Notes, optional"))
                go = st.form_submit_button(t("Save entry"), type="primary")
            if go:
                try:
                    log_visitor(VisitorEntryCreate(visitor_type=kind, full_name=name, blood_type=blood or None, phone_number=phone or None,
                                                   from_location=origin or None, notes=notes or None), db, staff)
                    st.success("✅ " + t("Saved."))
                except Exception as error:  # noqa: BLE001
                    st.error(friendly_error(error))
        mine = my_visitor_entries(db, staff)
        theme.stat_cards([("📝", len(mine), t("entries in your record"))])
    theme.footer()


def my_record() -> None:
    theme.page_header(t("My shift record"), t("Everyone you have logged. Download it when your shift ends."), "🧾")
    with session() as db:
        staff = accounts.load(db)
        rows = my_visitor_entries(db, staff)
        if not rows:
            theme.empty(t("Nothing logged yet."), "🧾")
            return
        frame = pd.DataFrame([{t("Time"): e.logged_at.strftime("%d %b %Y %H:%M"), t("Type"): e.visitor_type, t("Name"): e.full_name, t("Blood type"): e.blood_type,
                               t("Phone"): e.phone_number, t("From"): e.from_location, t("Notes"): e.notes} for e in rows])
        st.dataframe(frame, hide_index=True)
        c1, c2 = st.columns(2)
        c1.download_button("📊 CSV", frame.to_csv(index=False).encode("utf-8"), file_name="my_shift_record.csv", mime="text/csv")
        try:
            sheet = {"title": f"{staff.full_name} - {staff.shift}", "headers": list(frame.columns), "rows": frame.fillna("").values.tolist()}
            c2.download_button("📄 PDF", build_pdf("Shift record", [sheet]), file_name="my_shift_record.pdf", mime="application/pdf")
        except Exception:  # noqa: BLE001
            c2.caption(t("PDF needs reportlab"))
    theme.footer()


def screening() -> None:
    theme.page_header(t("Donor screening"), t("Check donors who are waiting for a medical clearance."), "🩺")
    with session() as db:
        staff = accounts.load(db)
        if "screen_donors" not in permissions_for(staff.role):
            st.warning(t("Only doctors and managers can screen donors."))
            return
        waiting = donors_waiting_for_screening(db, staff)
        if not waiting:
            theme.empty(t("Nobody is waiting for screening."), "✅")
        for d in waiting:
            with st.container(border=True):
                st.markdown(f"**{theme.esc(d.full_name)}** {theme.blood_badge(d.blood_type)} · {d.age or '-'} y · {d.weight_kg or '-'} kg · {theme.esc(d.city or '')}", unsafe_allow_html=True)
                note = st.text_input(t("Note, optional"), key=f"sn_{d.id}", max_chars=300)
                c1, c2, _ = st.columns([1, 1, 3])
                if c1.button("✅ " + t("Clear"), key=f"sc_{d.id}", type="primary"):
                    doctor_clear_donor(d.id, ScreeningDecision(notes=note or None), db, staff)
                    st.rerun()
                if c2.button("⛔ " + t("Not eligible"), key=f"sf_{d.id}"):
                    doctor_flag_donor(d.id, ScreeningDecision(notes=note or None), db, staff)
                    st.rerun()
    theme.footer()


def stock() -> None:
    with session() as db:
        if not accounts.staff_can(db, "manage_stock"):
            st.warning(t("Your role cannot manage the blood stock."))
            return
    views_hospital.stock()


def checkin() -> None:
    views_hospital_extra.checkin()


def nearby() -> None:
    views_hospital_extra.nearby()
