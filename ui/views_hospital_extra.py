"""Hospital pages for the features that go beyond requests and stock: staff logins, transfers between hospitals,
bulk messages, camp QR check-in, own emergency numbers, nearby map and report downloads."""
import pandas as pd
import streamlit as st

from app.models.emergency_contact import CATEGORIES
from app.models.staff import ROLE_CHOICES, SHIFT_CHOICES
from app.routes import export_routes
from app.routes.bulk_routes import BulkFilter, BulkSendIn
from app.routes.bulk_routes import preview as bulk_preview
from app.routes.bulk_routes import send as bulk_send
from app.routes.camp_routes import list_my_camps
from app.routes.checkin_routes import CheckInIn, attendance, check_in
from app.routes.directory_routes import ContactIn, add_contact, delete_contact, my_contacts
from app.routes.nearby_routes import nearby_donors, nearby_hospitals
from app.routes.staff_routes import RoleChange, change_staff_role, create_staff, hospital_all_visitor_entries, list_my_staff, remove_staff
from app.routes.transfer_routes import (
    TransferIn, ask_for_blood, cancel_transfer, confirm_arrival, hospitals_with_stock, my_transfers, respond_to_transfer, RespondIn,
)
from app.schemas.staff_schema import StaffCreate
from app.services.delivery_service import is_sms_configured, is_whatsapp_configured
from app.utils.permissions import ROLE_LABELS as STAFF_ROLE_LABELS
from app.utils.permissions import permissions_for
from app.utils.security import create_access_token
from ui import accounts, exports, qr, theme, widgets
from ui.db import friendly_error, session
from ui.i18n import t


def _hospital(db):
    return accounts.acting_hospital(db)


# ------------------------------------------------------------------ staff logins
def staff_accounts() -> None:
    theme.page_header(t("Staff & shifts"), t("Create a login for each staff member. Each one sees only what their role allows."), "👥")
    with session() as db:
        me = accounts.load(db)
        with st.expander("➕ " + t("Add a staff member"), expanded=False):
            with st.form("staff_new", clear_on_submit=True):
                c1, c2 = st.columns(2)
                name = c1.text_input(t("Full name"))
                email = c2.text_input(t("Email"))
                c3, c4, c5 = st.columns(3)
                password = c3.text_input(t("Password"), type="password", help=t("At least 8 characters with upper case, lower case, a number and a special character."))
                shift = c4.selectbox(t("Shift"), SHIFT_CHOICES)
                role = c5.selectbox(t("Role"), ROLE_CHOICES, format_func=lambda r: STAFF_ROLE_LABELS[r])
                phone = st.text_input(t("Phone number, optional"))
                go = st.form_submit_button(t("Create staff login"), type="primary")
            if go:
                try:
                    create_staff(StaffCreate(full_name=name, email=email, password=password, shift=shift, role=role, phone_number=phone or None), db, me)
                    st.success("✅ " + t("Staff login created. Give the email and password to the staff member."))
                except Exception as error:  # noqa: BLE001
                    st.error(friendly_error(error))
        staff_rows = list_my_staff(db, me)
        if not staff_rows:
            theme.empty(t("No staff logins yet."), "👥")
        for s in staff_rows:
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.markdown(f'<div class="lf-title">{theme.esc(s.full_name)}</div><div class="lf-sub">{theme.esc(s.email)} · {theme.esc(s.shift)}</div>', unsafe_allow_html=True)
                new_role = c2.selectbox(t("Role"), ROLE_CHOICES, index=ROLE_CHOICES.index(s.role) if s.role in ROLE_CHOICES else 0,
                                        format_func=lambda r: STAFF_ROLE_LABELS[r], key=f"sr_{s.id}", label_visibility="collapsed")
                if new_role != s.role:
                    change_staff_role(s.id, RoleChange(role=new_role), db, me)
                    st.rerun()
                if c3.button(t("Remove"), key=f"sd_{s.id}"):
                    remove_staff(s.id, db, me)
                    st.rerun()
                st.caption(t("Can") + ": " + ", ".join(permissions_for(s.role)))
        st.subheader(t("Front-desk record of every shift"))
        entries = hospital_all_visitor_entries(db, me)
        if entries:
            frame = pd.DataFrame([{t("Time"): e.logged_at.strftime("%d %b %H:%M"), t("Type"): e.visitor_type, t("Name"): e.full_name, t("Blood type"): e.blood_type,
                                   t("Phone"): e.phone_number, t("From"): e.from_location, t("Notes"): e.notes, t("Staff"): e.staff_name, t("Shift"): e.staff_shift}
                                  for e in entries])
            st.dataframe(frame, hide_index=True)
            st.download_button("📊 " + t("Download CSV"), frame.to_csv(index=False).encode("utf-8"), file_name="front_desk_record.csv", mime="text/csv")
        else:
            st.caption(t("Nothing has been logged yet."))
    theme.footer()


# ------------------------------------------------------------------ transfers between hospitals
STATUS_TONE = {"pending": "held", "approved": "open", "received": "fulfilled", "rejected": "rejected", "cancelled": "rejected"}


def transfers() -> None:
    theme.page_header(t("Hospital blood transfers"), t("Ask another hospital for bags, or answer a request from one."), "🔁")
    with session() as db:
        me = accounts.load(db)
        tab_ask, tab_list = st.tabs([t("Ask for blood"), t("My transfers")])
        with tab_ask:
            blood = st.selectbox(t("Blood type you need"), widgets.BLOOD_TYPES, key="tr_blood")
            suppliers = hospitals_with_stock(blood, db, me)
            if not suppliers:
                theme.empty(t("No other hospital has this blood type in stock right now."), "🔁")
            else:
                st.caption(t("Hospitals with this blood in stock, closest first."))
                for s in suppliers:
                    with st.container(border=True):
                        c1, c2 = st.columns([3, 2])
                        tick = " ✅" if s.is_verified else ""
                        c1.markdown(f'<div class="lf-title">{theme.esc(s.name)}{tick}</div><div class="lf-sub">{theme.esc(s.area or "")} {theme.esc(s.city or "")} · '
                                    f'{s.distance_kilometers} km · {s.units_available} {t("bags")} · 📞 {theme.esc(s.phone_number)}</div>', unsafe_allow_html=True)
                        units = c2.number_input(t("Bags"), min_value=1, max_value=min(s.units_available, 100), value=1, key=f"tr_u_{s.hospital_id}")
                        note = st.text_input(t("Note, optional"), key=f"tr_n_{s.hospital_id}")
                        if st.button(t("Send request"), key=f"tr_go_{s.hospital_id}", type="primary"):
                            try:
                                ask_for_blood(TransferIn(from_hospital_id=s.hospital_id, blood_type=blood, units=int(units), note=note or None), db, me)
                                st.success("✅ " + t("Request sent. They were notified."))
                            except Exception as error:  # noqa: BLE001
                                st.error(friendly_error(error))
        with tab_list:
            rows = my_transfers(db, me)
            if not rows:
                theme.empty(t("No transfers yet."), "🔁")
            for r in rows:
                with st.container(border=True):
                    arrow = "⬅️ " + t("they ask us") if r.direction == "incoming" else "➡️ " + t("we asked them")
                    st.markdown(f'<div class="lf-title">#{r.id} · {theme.esc(r.other_hospital)} {theme.blood_badge(r.blood_type)} × {r.units} {theme.badge(r.status, STATUS_TONE.get(r.status, "neutral"))}</div>'
                                f'<div class="lf-sub">{arrow} · 📞 {theme.esc(r.other_phone)} · {r.created_at:%d %b %H:%M}</div>', unsafe_allow_html=True)
                    if r.note:
                        st.caption(r.note)
                    c1, c2, _ = st.columns([1, 1, 3])
                    try:
                        if r.direction == "incoming" and r.status == "pending":
                            if c1.button(t("Approve"), key=f"tra_{r.id}", type="primary"):
                                respond_to_transfer(r.id, RespondIn(action="approve"), db, me)
                                st.rerun()
                            if c2.button(t("Reject"), key=f"trr_{r.id}"):
                                respond_to_transfer(r.id, RespondIn(action="reject"), db, me)
                                st.rerun()
                        elif r.direction == "outgoing" and r.status == "approved":
                            if c1.button(t("Bags arrived"), key=f"trv_{r.id}", type="primary"):
                                confirm_arrival(r.id, db, me)
                                st.rerun()
                        elif r.direction == "outgoing" and r.status == "pending":
                            if c1.button(t("Cancel"), key=f"trc_{r.id}"):
                                cancel_transfer(r.id, db, me)
                                st.rerun()
                    except Exception as error:  # noqa: BLE001
                        st.error(friendly_error(error))
    theme.footer()


# ------------------------------------------------------------------ bulk messages (hospital and admin)
def bulk_messages() -> None:
    theme.page_header(t("Message donors"), t("Send a short message to donors by blood group and area. Phone numbers are never shown to you."), "📣")
    auth = accounts.current()
    who = (auth["role"], auth["id"])
    with session() as db:
        c1, c2 = st.columns(2)
        blood = c1.multiselect(t("Blood groups"), widgets.BLOOD_TYPES, help=t("Leave empty for every blood group."), key="bm_blood")
        ready = c2.toggle(t("Only donors who can donate today"), value=True, key="bm_ready")
        c3, c4 = st.columns(2)
        city = c3.text_input(t("City"), key="bm_city")
        area = c4.text_input(t("Area, optional"), key="bm_area")
        try:
            flt = BulkFilter(blood_types=blood, city=city or None, area=area or None, only_ready_now=ready)
            info = bulk_preview(flt, db, who)
            st.markdown(f"**{info['count']}** {t('donors would receive this')} (≤ {info['limit']})")
            if info["by_blood_type"]:
                st.caption(" · ".join(f"{k}: {v}" for k, v in sorted(info["by_blood_type"].items())))
        except Exception as error:  # noqa: BLE001
            st.error(friendly_error(error))
            flt = None
        channels = ["app"] + (["sms"] if is_sms_configured() else []) + (["whatsapp"] if is_whatsapp_configured() else [])
        labels = {"app": t("App notification"), "sms": "SMS", "whatsapp": "WhatsApp"}
        channel = st.radio(t("Send by"), channels, format_func=lambda c: labels[c], horizontal=True, key="bm_ch")
        message = st.text_area(t("Message"), max_chars=300, key="bm_msg", placeholder=t("We urgently need O+ donors at our blood bank today."))
        if st.button("📣 " + t("Send message"), type="primary", key="bm_go", disabled=flt is None or len(message.strip()) < 5):
            try:
                result = bulk_send(BulkSendIn(**flt.model_dump(), message=message, channel=channel), db, who)
                st.success(f"✅ {t('Sent to')} {result['recipients']} {t('donors')}.")
            except Exception as error:  # noqa: BLE001
                st.error(friendly_error(error))
        st.caption(t("Limits: 500 donors per message and 3 bulk messages per hospital per day."))
    theme.footer()


# ------------------------------------------------------------------ camp QR check-in (hospital and staff with check-in right)
def checkin() -> None:
    theme.page_header(t("Camp check-in"), t("Scan a donor's QR card, or type the donor number."), "📷")
    auth = accounts.current()
    with session() as db:
        hospital = _hospital(db)
        if not accounts.staff_can(db, "camp_checkin"):
            st.warning(t("Your role is not allowed to check donors in."))
            return
        camps = list_my_camps(db, hospital)
        if not camps:
            theme.empty(t("No camps yet. Create one on the Donation camps page."), "⛺")
            return
        camp = st.selectbox(t("Camp"), camps, format_func=lambda c: f"{c.title} · {c.camp_date:%d %b %Y}", key="ci_camp")
        token = create_access_token({"sub": str(auth["id"]), "role": auth["role"]}, expires_minutes=5)
        tab_scan, tab_type = st.tabs([t("Scan QR"), t("Type donor number")])
        code = ""
        with tab_scan:
            photo = st.camera_input(t("Point the camera at the donor's QR card"), key="ci_cam")
            if photo is not None:
                decoded = qr.read(photo.getvalue())
                if decoded:
                    code = decoded
                else:
                    st.warning(t("No QR code was found. Try again, or type the donor number."))
        with tab_type:
            typed = st.text_input(t("Donor number"), placeholder="LF-12", key="ci_code")
            if st.button(t("Check in"), type="primary", key="ci_go") and typed.strip():
                code = typed.strip()
        if code:
            try:
                result = check_in(camp.id, CheckInIn(code=code), db, hospital, token)
                box = st.info if result.already_checked_in else st.success
                box(f"{result.message} — {result.attendee.donor_name} ({result.attendee.blood_type})")
            except Exception as error:  # noqa: BLE001
                st.error(friendly_error(error))
        people = attendance(camp.id, db, hospital)
        came = sum(1 for p in people if p.status == "attended")
        theme.stat_cards([("📝", len(people), t("registered")), ("✅", came, t("checked in")), ("🚶", sum(1 for p in people if p.walk_in), t("walk-ins"))])
        if people:
            frame = pd.DataFrame([{t("Donor"): p.donor_name, t("Blood type"): p.blood_type, t("Status"): p.status, t("Walk-in"): "✔" if p.walk_in else "",
                                   t("Checked in"): p.checked_in_at.strftime("%H:%M") if p.checked_in_at else "", t("By"): p.checked_in_by or ""} for p in people])
            st.dataframe(frame, hide_index=True)
            st.download_button("📊 " + t("Download CSV"), frame.to_csv(index=False).encode("utf-8"), file_name=f"camp_{camp.id}_attendance.csv", mime="text/csv")
        exports.export_buttons(f"ci_x_{camp.id}", lambda d, fmt: export_routes.export_camp_attendance(camp.id, fmt, d, hospital), "Attendance sheet")
    theme.footer()


# ------------------------------------------------------------------ own emergency numbers
def my_numbers() -> None:
    theme.page_header(t("Our emergency numbers"), t("Add your ambulance or blood bank number to the public directory. An admin approves it first unless your hospital is verified."), "☎️")
    labels = {"ambulance": "🚑 Ambulance", "emergency": "🆘 Emergency", "blood_bank": "🩸 Blood bank", "hospital": "🏥 Hospital", "helpline": "☎️ Helpline"}
    auth = accounts.current()
    with session() as db:
        with st.form("num_new", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input(t("Name"), placeholder="Our hospital ambulance")
            category = c2.selectbox(t("Type"), [c for c in CATEGORIES if c in labels], format_func=lambda c: labels[c])
            c3, c4, c5 = st.columns(3)
            phone = c3.text_input(t("Phone number"))
            city = c4.text_input(t("City"))
            area = c5.text_input(t("Area"))
            notes = st.text_input(t("Notes, optional"))
            all_day = st.checkbox(t("Open 24 hours"), value=True)
            go = st.form_submit_button(t("Add number"), type="primary")
        if go:
            try:
                add_contact(ContactIn(name=name, category=category, phone_number=phone, city=city or None, area=area or None, notes=notes or None, is_24h=all_day),
                            db, ("hospital", auth["id"]))
                st.success("✅ " + t("Added."))
            except Exception as error:  # noqa: BLE001
                st.error(friendly_error(error))
        hospital = accounts.load(db)
        for c in my_contacts(db, hospital):
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"**{theme.esc(c.name)}** · {theme.esc(c.phone_number)} · {theme.badge(t('approved') if c.is_approved else t('waiting for admin'), 'fulfilled' if c.is_approved else 'held')}",
                        unsafe_allow_html=True)
            if c2.button(t("Remove"), key=f"nm_{c.id}"):
                delete_contact(c.id, db, ("hospital", auth["id"]))
                st.rerun()
    theme.footer()


# ------------------------------------------------------------------ nearby map
def nearby() -> None:
    theme.page_header(t("Near me"), t("Hospitals and donors around you. Donors show first name, blood type and area only."), "🗺️")
    auth = accounts.current()
    who = (auth["role"], auth["id"])
    with session() as db:
        c1, c2, c3 = st.columns(3)
        radius = c1.slider(t("Distance (km)"), 5, 200, 50, key="nb_r")
        options = ["hospitals", "donors"] if auth["role"] != "donor" else ["hospitals"]
        show = c2.radio(t("Show"), options, format_func=lambda s: t(s.capitalize()), horizontal=True, key="nb_show")
        blood = c3.selectbox(t("Blood type"), ["all"] + widgets.BLOOD_TYPES, format_func=lambda b: t("All") if b == "all" else b, key="nb_b") if show == "donors" else "all"
        try:
            if show == "hospitals":
                rows = nearby_hospitals(None, None, float(radius), db, who)
                frame = pd.DataFrame([{t("Hospital"): r.name, t("Area"): r.area, t("City"): r.city, "km": r.distance_kilometers, t("Phone"): r.phone_number,
                                       "lat": r.latitude, "lon": r.longitude} for r in rows])
            else:
                rows = nearby_donors(None if blood == "all" else blood, None, None, float(radius), db, who)
                frame = pd.DataFrame([{t("Donor"): r.first_name, t("Blood type"): r.blood_type, t("Area"): r.area, t("City"): r.city, "km": r.distance_kilometers,
                                       "lat": r.latitude, "lon": r.longitude} for r in rows])
        except Exception as error:  # noqa: BLE001
            st.error(friendly_error(error))
            frame = pd.DataFrame()
        if frame.empty:
            theme.empty(t("Nobody found in this distance."), "🗺️")
        else:
            st.map(frame, latitude="lat", longitude="lon", color="#B3202F")
            st.dataframe(frame.drop(columns=["lat", "lon"]), hide_index=True)
    theme.footer()


# ------------------------------------------------------------------ report downloads
def reports() -> None:
    theme.page_header(t("Reports"), t("Download your requests, donations, stock, expiry dates and transfers."), "📥")
    with session() as db:
        me = accounts.load(db)
        exports.export_buttons("hx", lambda d, fmt: export_routes.export_hospital(fmt, d, me), "Hospital report")
    theme.footer()

