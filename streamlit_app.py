"""
LifeFlow - blood donation network (Streamlit edition).

Run locally:   streamlit run streamlit_app.py
Deploy:        push this folder to GitHub, then create the app on https://share.streamlit.io
               (main file: streamlit_app.py) and paste your secrets (see .streamlit/secrets.toml.example).
"""
import streamlit as st

st.set_page_config(page_title="LifeFlow Blood Network", page_icon="🩸", layout="wide", initial_sidebar_state="expanded")

from ui import bootstrap  # noqa: E402  (must come after set_page_config; reads secrets before the backend loads)

bootstrap.load_secrets()


@st.cache_resource(show_spinner="Starting LifeFlow...")
def _boot() -> bool:
    bootstrap.init_database()
    return True


try:
    _boot()
except Exception as startup_error:  # noqa: BLE001
    st.error("LifeFlow could not connect to its database. Check LIFEFLOW_DATABASE_URL in your secrets.")
    st.caption(f"{type(startup_error).__name__}")
    st.stop()

from ui import (  # noqa: E402
    accounts, i18n, icons, nav, robot, theme, views_account, views_admin, views_donor, views_hospital, views_hospital_extra, views_public, views_receiver, views_staff,
)
from ui.i18n import t  # noqa: E402

theme.inject()
i18n.rtl_css()
icons.install()


def _page(func, title: str, icon: str, path: str, default: bool = False):
    if default:   # the default page always lives at the root URL, Streamlit does not allow a custom path for it
        return st.Page(func, title=t(title), icon=icon, default=True)
    return st.Page(func, title=t(title), icon=icon, url_path=path)


def build_pages(role: str):
    shared = [_page(views_public.directory, "Ambulance & contacts", "🚑", "contacts"),
              _page(views_public.leaderboard, "Leaderboard", "🏆", "leaderboard"),
              _page(views_account.verify_certificate_page, "Verify a certificate", "✅", "verify-certificate")]
    account = [_page(views_account.notifications, "Notifications", "🔔", "notifications"),
               _page(views_account.security, "Account & security", "🔒", "security")]
    if role is None:
        pages = {
            "LifeFlow": [_page(views_public.welcome, "Welcome", "👋", "welcome", True), _page(views_public.home, "Home", "🏠", "home"),
                         _page(views_public.login, "Log in", "🔐", "login"),
                         _page(views_public.join, "Create account", "🩸", "join"),
                         _page(views_account.forgot_password, "Forgot password", "🔑", "forgot-password")],
            t("Emergency"): shared,
        }
    elif role == "donor":
        pages = {
            t("My LifeFlow"): [_page(views_donor.dashboard, "My dashboard", "🏠", "donor-home", True),
                               _page(views_donor.open_requests, "Open requests", "🩸", "donor-requests"),
                               _page(views_donor.my_donations, "My donations", "💉", "donor-donations"),
                               _page(views_donor.camps, "Donation camps", "⛺", "donor-camps"),
                               _page(views_account.certificates, "Certificates & donor card", "🏅", "donor-certificates")],
            t("Smart help"): [_page(views_donor.health_check, "Health check chat", "🩺", "donor-health"),
                              _page(views_donor.voice, "Voice assistant", "🗣️", "donor-voice"),
                              _page(views_hospital_extra.nearby, "Near me", "🗺️", "donor-nearby")],
            t("Account"): account,
            t("Emergency"): shared,
        }
    elif role == "receiver":
        pages = {
            t("My LifeFlow"): [_page(views_receiver.dashboard, "My dashboard", "🏠", "patient-home", True),
                               _page(views_receiver.new_request, "Request blood", "🩸", "patient-request"),
                               _page(views_receiver.my_requests, "My requests", "📋", "patient-requests"),
                               _page(views_hospital_extra.nearby, "Near me", "🗺️", "patient-nearby")],
            t("Account"): account,
            t("Emergency"): shared,
        }
    elif role == "hospital":
        pages = {
            t("Hospital"): [_page(views_hospital.dashboard, "My dashboard", "🏠", "hospital-home", True),
                            _page(views_hospital.new_request, "New request", "🩸", "hospital-request"),
                            _page(views_hospital.my_requests, "My requests", "📋", "hospital-requests"),
                            _page(views_hospital.stock, "Blood inventory", "📦", "hospital-stock"),
                            _page(views_hospital_extra.transfers, "Hospital transfers", "🔁", "hospital-transfers"),
                            _page(views_hospital.camps, "Donation camps", "⛺", "hospital-camps"),
                            _page(views_hospital_extra.checkin, "Camp check-in", "📷", "hospital-checkin")],
            t("Network"): [_page(views_hospital_extra.staff_accounts, "Staff & shifts", "👥", "hospital-staff"),
                           _page(views_hospital_extra.bulk_messages, "Message donors", "📣", "hospital-bulk"),
                           _page(views_hospital_extra.nearby, "Near me", "🗺️", "hospital-nearby"),
                           _page(views_hospital_extra.my_numbers, "Our emergency numbers", "☎️", "hospital-numbers"),
                           _page(views_hospital_extra.reports, "Reports", "📥", "hospital-reports")],
            t("Smart tools"): [_page(views_hospital.ai_tools, "AI tools", "🤖", "hospital-ai"),
                               _page(views_hospital.voice, "Voice assistant", "🗣️", "hospital-voice")],
            t("Account"): account,
            t("Emergency"): shared,
        }
    elif role == "staff":
        allowed = views_staff.permissions()
        work = [_page(views_staff.dashboard, "My shift", "🧑‍⚕️", "staff-home", True), _page(views_staff.my_record, "My shift record", "🧾", "staff-record")]
        if "screen_donors" in allowed:
            work.append(_page(views_staff.screening, "Donor screening", "🩺", "staff-screening"))
        if "manage_stock" in allowed:
            work.append(_page(views_staff.stock, "Blood inventory", "📦", "staff-stock"))
        if "camp_checkin" in allowed:
            work.append(_page(views_staff.checkin, "Camp check-in", "📷", "staff-checkin"))
        if "view_nearby" in allowed:
            work.append(_page(views_staff.nearby, "Near me", "🗺️", "staff-nearby"))
        pages = {t("Staff"): work, t("Account"): [account[1]], t("Emergency"): shared}
    else:  # admin
        pages = {
            t("Admin"): [_page(views_admin.overview, "Overview", "🛡️", "admin-home", True),
                         _page(views_admin.approvals, "Hospital approvals", "✅", "admin-approvals"),
                         _page(views_admin.review, "Request review", "🕵️", "admin-review"),
                         _page(views_admin.governance, "Governance", "⚖️", "admin-governance"),
                         _page(views_hospital_extra.bulk_messages, "Message donors", "📣", "admin-bulk"),
                         _page(views_admin.weekly_report, "Weekly report", "📈", "admin-report"),
                         _page(views_admin.data_tables, "All data", "🗂️", "admin-data"),
                         _page(views_admin.system, "System status", "⚙️", "admin-system"),
                         _page(views_account.security, "Account & security", "🔒", "admin-security")],
            t("Emergency"): shared,
        }
    return pages


role = accounts.role()
pages = build_pages(role)
nav.PAGES.clear()
for group in pages.values():
    for page in group:
        nav.PAGES[page.url_path] = page

with st.sidebar:
    st.markdown('<div class="lf-brand"><div class="drop">🩸</div><div><b>LifeFlow</b><small>Blood Network</small></div></div>', unsafe_allow_html=True)

navigation = st.navigation(pages)

with st.sidebar:
    i18n.language_picker()
    auth = accounts.current()
    if auth:
        st.markdown(f'<div class="lf-user"><div class="name">{theme.esc(auth["name"])}</div><div class="role">{theme.esc(accounts.ROLE_LABELS[auth["role"]])}</div></div>',
                    unsafe_allow_html=True)
        if st.button(t("Log out"), key="logout"):
            accounts.sign_out()
            st.rerun()

navigation.run()
robot.render()
