"""Patient / family pages."""
import streamlit as st

from app.models.request import BloodRequest
from app.routes.stats_routes import receiver_stats
from ui import accounts, theme, widgets
from ui.db import session
from ui.i18n import t


def dashboard() -> None:
    with session() as db:
        me = accounts.load(db)
        stats = receiver_stats(db, me)
        theme.page_header(f"{t('Welcome')}, {me.full_name.split()[0]}", t("Ask for blood here. We start by checking hospital stock."), "👋")
        theme.stat_cards([("🩸", stats.total_requests, t("requests")), ("🟢", stats.open_requests, t("open requests")),
                          ("✅", stats.fulfilled_requests, t("fully covered")), ("📦", stats.total_units_received, t("bags received"))])
        widgets.sos_box(db, me, "receiver")
        st.markdown("")
        recent = (db.query(BloodRequest).filter(BloodRequest.requester_type == "receiver", BloodRequest.requester_id == me.id)
                  .order_by(BloodRequest.id.desc()).limit(3).all())
        if recent:
            st.subheader(t("Latest requests"))
            widgets.request_cards(db, recent, "receiver", allow_insights=False)
    theme.footer()


def new_request() -> None:
    theme.page_header(t("Request blood"), t("Tell donors how many bags you need and how soon. Existing hospital stock is used automatically first."), "🩸")
    with st.expander("🗣️ " + t("Voice assistant (Urdu, Sindhi, English)")):
        widgets.voice_assistant("receiver", key="rva")
    with st.expander("📄 " + t("Scan a doctor's slip")):
        widgets.slip_scanner("rslip")
    with session() as db:
        me = accounts.load(db)
        with st.container(border=True):
            created = widgets.request_form(db, me, "receiver")
            if created is not None:
                if created.status == "held":
                    st.warning(t("For safety, a LifeFlow reviewer is quickly checking your request before donors are alerted. If this is a real emergency, please call the hospital directly as well."))
                else:
                    st.success(f"{t('Request sent. Number')} #{created.id}. {t('Matching donors nearby were alerted.')}")
                st.caption(t("Open “My requests” to follow it live."))
    theme.footer()


def my_requests() -> None:
    theme.page_header(t("My requests — full history"), t("Every request you have ever sent, open, closed, or still waiting for a donor."), "📋")
    with session() as db:
        me = accounts.load(db)
        rows = (db.query(BloodRequest).filter(BloodRequest.requester_type == "receiver", BloodRequest.requester_id == me.id)
                .order_by(BloodRequest.id.desc()).all())
        widgets.request_cards(db, rows, "receiver", show_responders=False)
    theme.footer()
