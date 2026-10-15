"""Hospital pages."""
from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from app.models.camp import DonationCamp
from app.models.request import BloodRequest
from app.routes.ai_routes import hospital_forecast
from app.routes.camp_routes import create_camp, list_camp_rsvps, list_my_camps
from app.routes.inventory_routes import (
    BatchIn, add_my_batch, discard_my_batch, get_my_inventory, list_my_batches, update_my_inventory,
)
from app.routes.stats_routes import hospital_stats
from app.schemas.camp_schema import CampCreate
from app.schemas.inventory_schema import InventoryUpdateInput
from app.services import v6_service as svc
from ui import accounts, theme, widgets
from ui.db import friendly_error, session
from ui.i18n import t
from ui.report_view import weekly_report_view


def _me(db):
    return accounts.acting_hospital(db)


def dashboard() -> None:
    with session() as db:
        me = _me(db)
        stats = hospital_stats(db, me)
        theme.page_header(me.name, t("Your blood bank and requests at a glance."), "🏥")
        if not me.is_verified:
            st.warning("⏳ " + t("An admin checks your licence before your hospital is shown as verified."))
        theme.stat_cards([
            ("🩸", stats.total_requests, t("requests")), ("🟢", stats.open_requests, t("open requests")),
            ("✅", stats.fulfilled_requests, t("fully covered")), ("📦", stats.total_units_received, t("bags received")),
            ("⚠️", len(stats.low_stock_types), t("Low stock"), "warn" if stats.low_stock_types else "ok"),
        ])
        if stats.low_stock_types:
            st.warning(f"{t('Low stock')}: " + ", ".join(stats.low_stock_types))
        widgets.sos_box(db, me, "hospital")
    theme.footer()


def new_request() -> None:
    theme.page_header(t("Create an emergency blood request"), t("Donors are ranked by compatibility, distance, and eligibility."), "🩸")
    with st.expander("🗣️ " + t("Voice assistant (Urdu, Sindhi, English)")):
        widgets.voice_assistant("hospital", key="hva")
    with st.expander("📄 " + t("Scan a doctor's slip")):
        widgets.slip_scanner("hslip")
    with session() as db:
        me = _me(db)
        with st.container(border=True):
            created = widgets.request_form(db, me, "hospital")
            if created is not None:
                if created.status == "held":
                    st.warning(t("For safety, a LifeFlow reviewer is quickly checking your request before donors are alerted. If this is a real emergency, please call the hospital directly as well."))
                else:
                    st.success(f"{t('Request sent. Number')} #{created.id}.")
    theme.footer()


def my_requests() -> None:
    theme.page_header(t("My requests — full history"), t("Every request you have ever sent, open, closed, or still waiting for a donor."), "📋")
    with session() as db:
        me = _me(db)
        rows = (db.query(BloodRequest).filter(BloodRequest.requester_type == "hospital", BloodRequest.requester_id == me.id)
                .order_by(BloodRequest.id.desc()).all())
        widgets.request_cards(db, rows, "hospital")
    theme.footer()


def stock() -> None:
    theme.page_header(t("Blood inventory"), t("Keep your stock up to date. Requests are matched against it first."), "📦")
    with session() as db:
        me = _me(db)
        items = get_my_inventory(db, me)
        frame = pd.DataFrame([{"Blood type": i.blood_type, "Bags in stock": i.units_available, "Low-stock alert at": i.low_stock_threshold} for i in items])
        st.bar_chart(frame.set_index("Blood type")["Bags in stock"], color="#B3202F")
        edited = st.data_editor(frame, hide_index=True, disabled=["Blood type"], key="stock_editor",
                                column_config={"Bags in stock": st.column_config.NumberColumn(min_value=0, step=1),
                                               "Low-stock alert at": st.column_config.NumberColumn(min_value=0, step=1)})
        if st.button(t("Save stock"), type="primary", key="stock_save"):
            try:
                for _i, row in edited.iterrows():
                    update_my_inventory(InventoryUpdateInput(blood_type=row["Blood type"], units_available=int(row["Bags in stock"]),
                                                              low_stock_threshold=int(row["Low-stock alert at"])), db, me)
                st.success("✅ " + t("Saved."))
                st.rerun()
            except Exception as error:  # noqa: BLE001
                st.error(friendly_error(error))

        st.subheader(t("Blood expiry dates"))
        with st.form("batch_form"):
            c1, c2, c3, c4 = st.columns(4)
            blood = c1.selectbox(t("Blood type"), widgets.BLOOD_TYPES, key="b_blood")
            units = c2.number_input(t("Bags"), min_value=1, max_value=500, value=1, key="b_units")
            collected = c3.date_input(t("Collected on"), value=datetime.utcnow().date(), max_value=datetime.utcnow().date(), key="b_col")
            expires = c4.date_input(t("Expires on"), value=None, key="b_exp", help=t("Leave empty for 35 days after collection"))
            if st.form_submit_button(t("Add bags"), type="primary"):
                try:
                    add_my_batch(BatchIn(blood_type=blood, units=int(units), collected_on=collected, expires_on=expires), db, me)
                    st.success("✅ " + t("Saved."))
                except Exception as error:  # noqa: BLE001
                    st.error(friendly_error(error))
        batches = list_my_batches(False, db, me)
        if not batches:
            st.caption(t("No bags with expiry dates recorded yet."))
        for b in batches:
            tone = {"critical": "emergency", "expired": "rejected", "soon": "held"}.get(b.urgency, "open")
            c1, c2 = st.columns([5, 1])
            c1.markdown(f'{theme.blood_badge(b.blood_type)} &nbsp; {b.units_remaining} {t("bags")} · {t("expires")} {b.expires_on} '
                        f'({b.days_left} {t("days left")}) {theme.badge(b.urgency, tone)}', unsafe_allow_html=True)
            if c2.button(t("Discard"), key=f"disc_{b.id}"):
                discard_my_batch(b.id, db, me)
                st.rerun()
    theme.footer()


def _forecast_card(db, camp) -> None:
    hours = st.number_input(t("Camp hours"), min_value=2, max_value=12, value=6, key=f"ch_{camp.id}")
    if st.button("📈 " + t("Predict turnout & staff"), key=f"cf_{camp.id}"):
        st.session_state[f"cf_res_{camp.id}"] = svc.build_camp_forecast(db, db.query(DonationCamp).filter(DonationCamp.id == camp.id).first(), float(hours))
    f = st.session_state.get(f"cf_res_{camp.id}")
    if not f:
        return
    theme.stat_cards([("🧑‍🤝‍🧑", f["expected_turnout"], f"{t('expected donors')} ({f['range_low']}–{f['range_high']})"), ("🩸", f["expected_bags"], t("bags expected")),
                      ("🛏️", f["beds"], t("beds / chairs")), ("👩‍⚕️", f["staff_total"], t("staff needed"))])
    labels = {"phlebotomists": "Blood-taking nurses / phlebotomists", "screening_doctors_or_nurses": "Screening doctors or nurses",
              "registration_desk": "Registration desk", "volunteers": "Volunteers"}
    st.table({t("Role"): [t(labels.get(k, k)) for k in f["staff"]], t("People"): list(f["staff"].values())})
    st.caption(f"{f['registered']} {t('registered')} · {f['nearby_eligible_donors']} {t('eligible donors within 15 km')} · "
               f"{t('show-up rate used')} {round(f['show_rate_used'] * 100)}%")
    for note in f["notes"]:
        st.caption("💡 " + t(note))


def camps() -> None:
    theme.page_header(t("Donation camps"), t("Every donor on LifeFlow is notified when you publish one."), "⛺")
    with session() as db:
        me = _me(db)
        with st.expander("➕ " + t("Organize a donation camp")):
            c1, c2 = st.columns(2)
            title = c1.text_input(t("Title"), key="camp_title", placeholder="Free blood donation camp")
            label = c2.text_input(t("Camp location (words)"), key="camp_label", value=f"{me.area or ''}, {me.city or ''}".strip(", "))
            desc = st.text_input(t("Description, optional"), key="camp_desc")
            c3, c4 = st.columns(2)
            day = c3.date_input(t("Date"), value=datetime.utcnow().date() + timedelta(days=7), min_value=datetime.utcnow().date(), key="camp_day")
            at = c4.time_input(t("Time"), value=time(10, 0), key="camp_time")
            if st.button(t("Publish camp"), type="primary", key="camp_go"):
                try:
                    create_camp(CampCreate(title=title, description=desc or None, location_label=label, latitude=me.latitude,
                                           longitude=me.longitude, camp_date=datetime.combine(day, at)), db, me)
                    st.success("✅ " + t("Camp published. Donors were notified."))
                except Exception as error:  # noqa: BLE001
                    st.error(friendly_error(error))
        mine = list_my_camps(db, me)
        if not mine:
            theme.empty(t("You have not organized a camp yet."), "⛺")
        for camp in mine:
            with st.container(border=True):
                st.markdown(f'<div class="lf-title">{theme.esc(camp.title)}</div><div class="lf-sub">{camp.camp_date:%a %d %b %Y, %H:%M} · '
                            f'{theme.esc(camp.location_label)} · {camp.registered_count} {t("registered")}</div>', unsafe_allow_html=True)
                _forecast_card(db, camp)
                with st.expander(t("View registered donors")):
                    rsvps = list_camp_rsvps(camp.id, db, me)
                    if rsvps:
                        st.dataframe(pd.DataFrame([{t("Donor"): r.donor_name, t("Blood type"): r.donor_blood_type, t("Phone"): r.donor_phone} for r in rsvps]), hide_index=True)
                    else:
                        st.caption(t("Nobody has registered yet."))
    theme.footer()


def ai_tools() -> None:
    theme.page_header(t("AI tools"), t("Weekly report, shortage forecast, ambulance and donor response."), "🤖")
    tabs = st.tabs([t("Weekly report"), t("Shortage forecast"), t("Ambulance, travel time & likely responders")])
    with session() as db:
        me = _me(db)
        with tabs[0]:
            weekly_report_view(db, "hospital", me.id, key="hwr")
        with tabs[1]:
            forecast = hospital_forecast(db, me)
            if forecast.summary:
                st.warning(forecast.summary)
            frame = pd.DataFrame([e.model_dump() for e in forecast.entries])
            if frame.empty:
                st.caption(t("Not enough history yet."))
            else:
                st.dataframe(frame.rename(columns={"blood_type": "Blood", "average_daily_demand": "Daily demand", "trend": "Trend", "current_stock": "Stock",
                                                   "projected_demand_next_7_days": "Next 7 days", "days_until_shortage": "Days left", "risk_level": "Risk"}), hide_index=True)
        with tabs[2]:
            rows = (db.query(BloodRequest).filter(BloodRequest.requester_type == "hospital", BloodRequest.requester_id == me.id)
                    .order_by(BloodRequest.id.desc()).limit(30).all())
            if not rows:
                st.caption(t("You have not sent a request yet."))
            else:
                pick = st.selectbox(t("Request number"), rows, format_func=lambda r: f"#{r.id} · {r.blood_type_needed} · {r.units_fulfilled}/{r.units_needed}", key="ai_req")
                st.markdown("##### 🚑 " + t("Ambulance & travel time"))
                widgets.eta_view(db, pick)
                st.markdown("##### 🎯 " + t("Donors most likely to respond"))
                widgets.response_view(db, pick)
    theme.footer()


def voice() -> None:
    theme.page_header(t("Ask LifeFlow by voice"), t("Voice assistant (Urdu, Sindhi, English)"), "🗣️")
    widgets.voice_assistant("hospital", key="hva2", allow_fill=False)
    theme.footer()
