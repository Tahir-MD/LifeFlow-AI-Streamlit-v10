"""Donor pages."""
from datetime import datetime

import pandas as pd
import streamlit as st

from app.models.camp import CampRSVP, DonationCamp
from app.models.hospital import Hospital
from app.models.request import BloodRequest
from app.routes import export_routes
from app.routes.camp_routes import rsvp_to_camp
from app.routes.donation_routes import donor_donation_history
from app.routes.donor_routes import my_referral, recheck_my_eligibility
from app.routes.matching_routes import accept_blood_request
from app.routes.rating_routes import rate_requester
from app.routes.request_routes import build_request_out
from app.routes.stats_routes import donor_stats
from app.routes.tracking_routes import DonorStatusIn, donor_update_status
from app.schemas.rating_schema import RatingCreate
from app.schemas.donor_schema import EligibilityAnswers
from app.schemas.request_schema import AcceptRequestInput
from app.services.matching_service import COMPATIBLE_DONOR_TYPES
from app.utils.distance import calculate_distance_kilometers
from ui import accounts, exports, health, theme, widgets
from ui.db import friendly_error, session
from ui.i18n import t


def _donor(db):
    return accounts.load(db)


def dashboard() -> None:
    with session() as db:
        donor = _donor(db)
        stats = donor_stats(db, donor)
        theme.page_header(f"{t('Welcome')}, {donor.full_name.split()[0]}", t("Thank you for being a lifesaver."), "👋")
        theme.stat_cards([
            ("⭐", stats.points, t("Points")),
            ("💉", stats.total_donations, t("donations")),
            ("❤️", stats.estimated_lives_impacted, t("lives you may have helped")),
            ("🏅", stats.badge_tier, t("Badge")),
            ("🏆", f"#{stats.leaderboard_rank}" if stats.leaderboard_rank else "-", t("Leaderboard")),
        ])
        if stats.is_eligible_now:
            st.success("✅ " + t("You are eligible to donate right now."))
        else:
            when = stats.next_eligible_date.date().isoformat() if stats.next_eligible_date else "-"
            st.info("⏳ " + t("You will be eligible again on {date}.", date=when))
        open_count = db.query(BloodRequest).filter(BloodRequest.status == "open", BloodRequest.blood_type_needed.in_(
            [bt for bt, donors in COMPATIBLE_DONOR_TYPES.items() if donor.blood_type in donors])).count()
        st.markdown(f"**{open_count}** {t('open requests')} {t('could use your blood type')}.")
        with st.expander("🤝 " + t("Invite friends")):
            ref = my_referral(db, donor)
            st.markdown(f"{t('Your invite code')}: **{ref['code']}**")
            st.caption(f"{t('Friends joined')}: {ref['friends_joined']} · {t('Friends who donated')}: {ref['friends_donated']} · "
                       f"{t('Points earned')}: {ref['points_earned']}. {t('You get')} {ref['referrer_bonus']} {t('points when a friend donates for the first time')}.")
    theme.footer()


def open_requests() -> None:
    theme.page_header(t("Open requests"), t("Compatible requests near you. Pick one to help."), "🩸")
    with session() as db:
        donor = _donor(db)
        rows = []
        for r in db.query(BloodRequest).filter(BloodRequest.status == "open").order_by(BloodRequest.id.desc()).limit(100).all():
            if (r.review_status or "ok") in ("held", "rejected"):
                continue
            if donor.blood_type not in COMPATIBLE_DONOR_TYPES.get(r.blood_type_needed, []):
                continue
            if r.requester_type == "hospital" and r.requester_id is None:
                continue
            km = calculate_distance_kilometers(r.latitude, r.longitude, donor.latitude, donor.longitude)
            if km <= (100 if r.is_sos else 50):
                rows.append((km, r))
        rows.sort(key=lambda x: (not x[1].is_sos, x[1].urgency_type != "emergency", x[0]))
        if not rows:
            theme.empty(t("No compatible request near you right now. We will alert you when one appears."), "🙌")
        for km, r in rows:
            out = build_request_out(db, r)
            remaining = out.units_remaining
            with st.container(border=True):
                st.markdown(widgets.request_summary_html(r), unsafe_allow_html=True)
                st.markdown(f"**{theme.esc(out.requester_name)}** · {km:.1f} km · 📞 {theme.esc(out.requester_phone)}")
                if r.medical_reason or r.patient_age:
                    st.caption(" · ".join(x for x in (f"{t('Patient')}: {r.patient_name}" if r.patient_name else "", f"{r.patient_age} y" if r.patient_age else "",
                                                       r.medical_reason or "") if x))
                c1, c2 = st.columns([1, 1])
                units = c1.number_input(t("Bags you will donate"), min_value=1, max_value=max(remaining, 1), value=1, key=f"don_u_{r.id}")
                c2.write("")
                if c2.button("🩸 " + t("Accept & donate"), type="primary", key=f"don_go_{r.id}"):
                    try:
                        done = accept_blood_request(r.id, AcceptRequestInput(units_donated=int(units)), db, donor)
                        st.success(f"{done['message']} {t('Contact')}: {done['requester_name']} · {done['requester_phone']}")
                        st.balloons()
                    except Exception as error:  # noqa: BLE001
                        st.error(friendly_error(error))
    theme.footer()


def my_donations() -> None:
    theme.page_header(t("My donations"), t("Everyone you have helped."), "💉")
    with session() as db:
        donor = _donor(db)
        entries = donor_donation_history(db, donor)
        if not entries:
            theme.empty(t("You have not donated yet."), "💉")
        else:
            frame = pd.DataFrame([{t("Date"): e.donated_at.strftime("%d %b %Y"), t("Blood type"): e.blood_type_needed, t("Bags"): e.units_donated,
                                   t("Helped"): e.patient_name or e.requester_name, t("Status"): e.request_status} for e in entries])
            st.dataframe(frame, hide_index=True)
            st.download_button("📊 " + t("Download CSV"), frame.to_csv(index=False).encode("utf-8"), file_name="my_donations.csv", mime="text/csv")
            exports.export_buttons("dx", lambda d, fmt: export_routes.export_donor(fmt, d, donor), "Download my history")
            st.subheader(t("Update the person you are helping"))
            for e in entries[:20]:
                with st.container(border=True):
                    st.markdown(f"**#{e.request_id}** · {e.patient_name or e.requester_name} · {e.donated_at:%d %b} · {theme.status_badge(e.request_status)}", unsafe_allow_html=True)
                    c1, c2, c3 = st.columns([1, 1, 3])
                    if e.request_status != "fulfilled":
                        if c1.button("🚗 " + t("I am on the way"), key=f"way_{e.donation_id}"):
                            donor_update_status(e.request_id, DonorStatusIn(status="on_the_way"), db, donor)
                            st.success(t("They were told."))
                        if c2.button("📍 " + t("I have arrived"), key=f"arr_{e.donation_id}"):
                            donor_update_status(e.request_id, DonorStatusIn(status="arrived"), db, donor)
                            st.success(t("They were told."))
                    with st.expander("⭐ " + t("Rate the person you helped")):
                        stars, comment = widgets.stars_box(f"rr_{e.donation_id}")
                        if st.button(t("Send rating"), key=f"rr_go_{e.donation_id}"):
                            try:
                                rate_requester(e.donation_id, RatingCreate(stars=stars, comment=comment), db, donor)
                                st.success("✅ " + t("Thank you."))
                            except Exception as error:  # noqa: BLE001
                                st.error(friendly_error(error))
    theme.footer()


def camps() -> None:
    theme.page_header(t("Donation camps"), t("Join a camp near you."), "⛺")
    with session() as db:
        donor = _donor(db)
        mine = {x.camp_id for x in db.query(CampRSVP).filter(CampRSVP.donor_id == donor.id).all()}
        upcoming = db.query(DonationCamp).filter(DonationCamp.camp_date >= datetime.utcnow()).order_by(DonationCamp.camp_date).all()
        if not upcoming:
            theme.empty(t("No camps are planned yet."), "⛺")
        for camp in upcoming:
            hospital = db.query(Hospital).filter(Hospital.id == camp.hospital_id).first()
            km = calculate_distance_kilometers(camp.latitude, camp.longitude, donor.latitude, donor.longitude)
            with st.container(border=True):
                st.markdown(f'<div class="lf-title">{theme.esc(camp.title)}</div><div class="lf-sub">{theme.esc(hospital.name if hospital else "")} · '
                            f'{camp.camp_date:%a %d %b %Y, %H:%M} · {theme.esc(camp.location_label)} · {km:.1f} km</div>', unsafe_allow_html=True)
                if camp.description:
                    st.write(camp.description)
                if camp.id in mine:
                    st.success("✅ " + t("You are registered."))
                elif st.button(t("Register to attend"), key=f"camp_{camp.id}", type="primary"):
                    try:
                        rsvp_to_camp(camp.id, db, donor)
                        st.rerun()
                    except Exception as error:  # noqa: BLE001
                        st.error(friendly_error(error))
    theme.footer()


def health_check() -> None:
    theme.page_header(t("Health check chat"), t("Answer a few simple questions in your language, by tapping, typing or speaking. You can save the result to your profile."), "🩺")
    mode = st.radio(t("How do you want to answer?"), [t("Answer by chat or voice"), t("Fill the form")], horizontal=True, key="hc_mode")
    if mode == t("Fill the form"):
        answers = widgets.questionnaire("hq")
    else:
        answers = widgets.health_chat("hchat")
        if answers is not None and st.button(t("Start again"), key="hc_again"):
            del st.session_state["hchat"]
            st.rerun()
    if answers is not None:
        result = health.verdict(answers)
        widgets.verdict_box(result)
        if st.button(t("Save this result to my profile"), type="primary", key="hc_save"):
            try:
                with session() as db:
                    recheck_my_eligibility(EligibilityAnswers(**answers), db, _donor(db))
                st.success("✅ " + t("Saved to your profile."))
            except Exception as error:  # noqa: BLE001
                st.error(friendly_error(error))
    st.caption(t("This is a screening, not a medical diagnosis. A doctor will check you on the day you donate."))
    theme.footer()


def voice() -> None:
    theme.page_header(t("Ask LifeFlow by voice"), t("Voice assistant (Urdu, Sindhi, English)"), "🗣️")
    widgets.voice_assistant("donor", key="dva", allow_fill=False)
    theme.footer()
