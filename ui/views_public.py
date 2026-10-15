"""Pages anyone can open: home, log in, join, emergency contacts, leaderboard."""
import streamlit as st
from sqlalchemy import func

from app.models.donation import Donation
from app.models.donor import Donor
from app.models.emergency_contact import CATEGORIES, EmergencyContact
from app.models.hospital import Hospital
from app.models.request import BloodRequest
from app.utils.badges import get_badge_tier
from ui import accounts, bootstrap, health, nav, otp, theme, widgets
from ui.db import friendly_error, session
from ui.i18n import t


# ------------------------------------------------------------------ welcome (the first page)
def welcome() -> None:
    st.markdown("<style>section[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl'],[data-testid='collapsedControl']{display:none!important}"
                ".block-container{max-width:1100px}.st-key-w_enter button,.st-key-w_login button,.st-key-w_join button{width:100%;padding:.8rem 1rem;font-size:1.02rem}</style>", unsafe_allow_html=True)
    drops = "".join(f'<span class="drop" style="left:{x}%;animation-delay:{d}s">🩸</span>' for x, d in ((6, 0), (22, 3), (40, 1.5), (62, 4.5), (80, 2), (92, 6)))
    st.markdown(
        f'<div class="lf-welcome">{drops}<div class="logo">🩸</div><div class="hi">{theme.esc(t("Welcome to"))}</div>'
        f'<h1>LifeFlow</h1><p>{theme.esc(t("Every two seconds, someone needs blood."))} '
        f'{theme.esc(t("LifeFlow checks real hospital stock first, then reaches the nearest matching donors for whatever is still short. Fast, fair and in your own language."))}</p>'
        f'<div class="pills"><span>🩸 {theme.esc(t("Blood request"))}</span><span>🚑 {theme.esc(t("Ambulance & contacts"))}</span>'
        f'<span>🗣️ {theme.esc(t("Voice assistant (Urdu, Sindhi, English)"))}</span><span>🏥 {theme.esc(t("partner hospitals"))}</span></div></div>',
        unsafe_allow_html=True)
    st.write("")
    c1, c2, c3 = st.columns(3)
    if c1.button("🚀 " + t("Enter LifeFlow"), type="primary", key="w_enter"):
        nav.go("home")
    if c2.button("🔐 " + t("Log in"), key="w_login"):
        nav.go("login")
    if c3.button("🩸 " + t("Create account"), key="w_join"):
        nav.go("join")
    st.markdown('<div class="lf-sos-strip"><span>🚨 Emergency?</span><a href="tel:1122"><i class="fa-solid fa-phone"></i> Rescue 1122</a>'
                '<a href="tel:115"><i class="fa-solid fa-phone"></i> Edhi 115</a><a href="tel:1020"><i class="fa-solid fa-phone"></i> Chhipa 1020</a></div>', unsafe_allow_html=True)
    with session() as db:
        donors = db.query(Donor).count()
        hospitals = db.query(Hospital).count()
        units = db.query(func.coalesce(func.sum(Donation.units_donated), 0)).scalar() or 0
    theme.stat_cards([("🧑‍🤝‍🧑", donors, t("registered donors")), ("🏥", hospitals, t("partner hospitals")), ("🩸", units, t("bags donated"))])
    theme.footer()


# ------------------------------------------------------------------ home
def home() -> None:
    theme.hero(t("Blood bank & donor network"), t("Every two seconds, someone needs blood."),
               t("LifeFlow checks real hospital stock first, then reaches the nearest matching donors for whatever is still short. Fast, fair and in your own language."))
    st.write("")
    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button(t("Log in"), type="primary", key="home_login"):
        nav.go("login")
    if c2.button(t("Create account"), key="home_join"):
        nav.go("join")

    with session() as db:
        donors = db.query(Donor).count()
        hospitals = db.query(Hospital).count()
        units = db.query(func.coalesce(func.sum(Donation.units_donated), 0)).scalar() or 0
        fulfilled = db.query(BloodRequest).filter(BloodRequest.status == "fulfilled").count()
    theme.stat_cards([("🧑‍🤝‍🧑", donors, t("registered donors")), ("🏥", hospitals, t("partner hospitals")),
                      ("🩸", units, t("bags donated")), ("✅", fulfilled, t("Requests fulfilled"))])

    st.subheader(t("How LifeFlow works"))
    theme.steps([
        (t("Ask"), t("A patient or hospital sends a request: type it, speak it in Urdu or Sindhi, or photograph the doctor's slip.")),
        (t("Stock first"), t("We check hospital blood banks near you before anyone is disturbed.")),
        (t("Smart alerts"), t("Only compatible, eligible, nearby donors are alerted, the ones most likely to answer first.")),
        (t("Track it live"), t("Follow every step on a timeline, with ambulance numbers and travel time ready.")),
    ])

    st.subheader(t("Smart features"))
    features = [
        ("🗣️", "Voice assistant", "Speak in Urdu, Sindhi or English and the request form fills itself."),
        ("📄", "Doctor slip scanner", "Take a photo of a prescription. AI suggests the details for you to check."),
        ("🎯", "Donor response prediction", "See which donors will most likely say yes, and how fast."),
        ("🚑", "Ambulance & ETA", "Fastest source of blood, travel time, map links and ambulance numbers."),
        ("📈", "Camp predictor", "Expected turnout and the staff, beds and bags a camp needs."),
        ("🩺", "Health check chat", "Find out if you can donate, one simple question at a time."),
    ]
    cols = st.columns(3)
    for i, (icon, title, text) in enumerate(features):
        with cols[i % 3]:
            st.markdown(f'<div class="lf-feature"><div class="ic">{icon}</div><div class="lf-title">{theme.esc(t(title))}</div>'
                        f'<div class="lf-sub">{theme.esc(t(text))}</div></div>', unsafe_allow_html=True)

    if bootstrap.demo_enabled():
        with st.expander(t("Try the demo accounts")):
            st.markdown("Password for all demo accounts: **Demo@1234**")
            st.table({"Role": ["Donor", "Patient", "Hospital", "Hospital staff (manager)"], "Email": ["donor@demo.lifeflow", "patient@demo.lifeflow", "hospital@demo.lifeflow", "staff@demo.lifeflow"]})
    theme.footer()


# ------------------------------------------------------------------ log in
def login() -> None:
    theme.page_header(t("Log in"), t("Choose who you are, then sign in."), "🔐")
    roles = [("donor", "Donor"), ("receiver", "Patient"), ("hospital", "Hospital"), ("staff", "Hospital staff"), ("admin", "Admin")]
    tabs = st.tabs([f"{label}" if label == "Admin" else t(label) for _r, label in roles])
    for tab, (role_name, _label) in zip(tabs, roles):
        with tab:
            with st.form(f"login_{role_name}"):
                email = st.text_input(t("Email"), key=f"le_{role_name}")
                password = st.text_input(t("Password"), type="password", key=f"lp_{role_name}")
                code = ""
                if role_name in ("hospital", "admin"):
                    code = st.text_input(t("6-digit code"), key=f"lc_{role_name}", help=t("Only if two-step verification is turned on for this account."))
                submitted = st.form_submit_button(t("Log in"), type="primary")
            if submitted:
                with session() as db:
                    problem = accounts.sign_in(db, role_name, email, password, code)
                if problem:
                    st.error(t(problem))
                else:
                    st.rerun()
    if st.button("🔑 " + t("Forgot your password?"), key="login_forgot"):
        nav.go("forgot-password")
    if bootstrap.demo_enabled():
        st.caption(t("Demo accounts") + ": donor@demo.lifeflow · patient@demo.lifeflow · hospital@demo.lifeflow · staff@demo.lifeflow — Demo@1234")
    theme.footer()


# ------------------------------------------------------------------ join
def _password_pair(key: str):
    c1, c2 = st.columns(2)
    password = c1.text_input(t("Password"), type="password", key=key + "_pw", help=t("At least 8 characters with upper case, lower case, a number and a special character."))
    confirm = c2.text_input(t("Confirm password"), type="password", key=key + "_pw2")
    return password, confirm


def _check_passwords(password: str, confirm: str) -> bool:
    if password != confirm:
        st.error(t("The two passwords do not match."))
        return False
    return True


def join() -> None:
    theme.page_header(t("Create account"), t("It takes about two minutes."), "🩸")
    tabs = st.tabs([t("Donor"), t("Patient"), t("Hospital")])
    with tabs[0]:
        _join_donor()
    with tabs[1]:
        _join_receiver()
    with tabs[2]:
        _join_hospital()
    theme.footer()


def _join_donor() -> None:
    st.markdown("#### " + t("Become a donor"))
    c1, c2 = st.columns(2)
    name = c1.text_input(t("Full name"), key="dr_name")
    email = c2.text_input(t("Email"), key="dr_email")
    password, confirm = _password_pair("dr")
    c3, c4 = st.columns([1, 2])
    blood = c3.selectbox(t("Blood type"), widgets.BLOOD_TYPES, index=widgets.BLOOD_TYPES.index("O+"), key="dr_blood")
    with c4:
        phone = widgets.phone_input(t("Phone number"), "dr_phone")
    referral = st.text_input(t("Invite code, optional"), value=st.query_params.get("ref", ""), key="dr_ref")
    place = widgets.location_inputs("dr_place")

    st.markdown("#### 🩺 " + t("Health check: can you give blood?"))
    st.caption(t("Answer honestly. This protects you and the patient. A doctor will check you again on the day you donate."))
    mode = st.radio(t("How do you want to answer?"), [t("Fill the form"), t("Answer by chat or voice")], horizontal=True, key="dr_mode")
    answers = None
    if mode == t("Fill the form"):
        answers = widgets.questionnaire("dr_q")
    else:
        answers = widgets.health_chat("dr_chat")
        if answers is None:
            st.info(t("Finish the chat to continue."))
        elif st.button(t("Start again"), key="dr_chat_reset"):
            del st.session_state["dr_chat"]
            st.rerun()
    result = None
    if answers is not None:
        result = health.verdict(answers)
        widgets.verdict_box(result)

    token = otp.verify_box("dr_otp", phone, email) if answers is not None and (result is None or result["eligible"]) else None
    if st.button(t("Create account"), type="primary", key="dr_go", disabled=answers is None or (result is not None and not result["eligible"]) or token is None):
        if not _check_passwords(password, confirm):
            return
        try:
            with session() as db:
                accounts.register_donor(db, {"full_name": name, "email": email, "password": password, "blood_type": blood,
                                             "phone_number": phone, "place": place, "referral_code": referral}, answers, phone_token=token)
            st.success(t("Your account is ready. Go to Log in and sign in."))
            st.balloons()
        except Exception as error:  # noqa: BLE001
            st.error(friendly_error(error))


def _join_receiver() -> None:
    st.markdown("#### " + t("Register as a patient or family member"))
    c1, c2 = st.columns(2)
    name = c1.text_input(t("Full name"), key="rr_name")
    email = c2.text_input(t("Email"), key="rr_email")
    password, confirm = _password_pair("rr")
    c3, c4 = st.columns(2)
    with c3:
        phone = widgets.phone_input(t("Phone number"), "rr_phone")
    cnic = c4.text_input(t("National ID (CNIC)"), key="rr_cnic", placeholder="4540112345671", help=t("13 digits of your national ID card"))
    patient = st.text_input(t("Patient name, optional"), key="rr_patient")
    house = st.text_input(t("House / street, optional"), key="rr_house")
    place = widgets.location_inputs("rr_place")
    token = otp.verify_box("rr_otp", phone, email)
    if st.button(t("Create account"), type="primary", key="rr_go", disabled=token is None):
        if not _check_passwords(password, confirm):
            return
        try:
            with session() as db:
                accounts.register_receiver(db, {"full_name": name, "email": email, "password": password, "phone_number": phone,
                                                "cnic_number": cnic, "address": house, "patient_name": patient, "place": place}, phone_token=token)
            st.success(t("Your account is ready. Go to Log in and sign in."))
        except Exception as error:  # noqa: BLE001
            st.error(friendly_error(error))


def _join_hospital() -> None:
    st.markdown("#### " + t("Register a hospital or blood bank"))
    c1, c2 = st.columns(2)
    name = c1.text_input(t("Hospital name"), key="hr_name")
    email = c2.text_input(t("Email"), key="hr_email")
    password, confirm = _password_pair("hr")
    c3, c4 = st.columns(2)
    licence = c3.text_input(t("Licence number"), key="hr_lic")
    with c4:
        phone = widgets.phone_input(t("Phone number"), "hr_phone")
    place = widgets.location_inputs("hr_place", "Where is the hospital?")
    st.caption(t("An admin checks your licence before your hospital is shown as verified."))
    token = otp.verify_box("hr_otp", phone, email)
    if st.button(t("Create account"), type="primary", key="hr_go", disabled=token is None):
        if not _check_passwords(password, confirm):
            return
        try:
            with session() as db:
                accounts.register_hospital(db, {"name": name, "email": email, "password": password, "license_number": licence,
                                                "phone_number": phone, "place": place}, phone_token=token)
            st.success(t("Your account is ready. Go to Log in and sign in."))
        except Exception as error:  # noqa: BLE001
            st.error(friendly_error(error))


# ------------------------------------------------------------------ emergency directory
CATEGORY_LABELS = {"ambulance": "🚑 Ambulance", "emergency": "🆘 Emergency", "blood_bank": "🩸 Blood bank", "hospital": "🏥 Hospital",
                   "police": "👮 Police", "fire": "🚒 Fire", "helpline": "☎️ Helpline"}


def directory() -> None:
    theme.page_header(t("Ambulance & contacts"), t("Phone numbers for an emergency. No login needed."), "🚑")
    c1, c2 = st.columns([2, 1])
    city = c1.text_input(t("City"), key="dir_city", placeholder="Sukkur, Karachi, Lahore...")
    category = c2.selectbox(t("Type"), ["all"] + CATEGORIES, format_func=lambda c: t("All") if c == "all" else CATEGORY_LABELS.get(c, c), key="dir_cat")
    with session() as db:
        query = db.query(EmergencyContact).filter(EmergencyContact.is_approved == True)  # noqa: E712
        if category != "all":
            query = query.filter(EmergencyContact.category == category)
        rows = query.order_by(EmergencyContact.is_national.desc(), EmergencyContact.name).all()
        wanted = city.strip().lower()
        shown = [r for r in rows if not wanted or r.is_national or not r.city or wanted in (r.city or "").lower()]
        if not shown:
            theme.empty(t("No numbers found for this search."), "📞")
        for r in shown:
            where = r.city or t("All Pakistan")
            note = f"<div class='lf-sub'>{theme.esc(r.notes)}</div>" if r.notes else ""
            st.markdown(
                f'<div class="lf-card"><div class="lf-row"><div><span class="lf-title">{theme.esc(r.name)}</span> '
                f'{theme.badge(CATEGORY_LABELS.get(r.category, r.category), "neutral")}'
                f'<div class="lf-sub">{theme.esc(where)}{" · 24/7" if r.is_24h else ""}</div>{note}</div>'
                f'<a class="lf-badge blood" style="font-size:1.05rem;padding:8px 18px;text-decoration:none" href="tel:{theme.esc(r.phone_number)}">📞 {theme.esc(r.phone_number)}</a></div></div>',
                unsafe_allow_html=True)
    st.caption(t("Please confirm a number works in your district. Coverage differs between cities."))
    theme.footer()


# ------------------------------------------------------------------ leaderboard
def leaderboard() -> None:
    theme.page_header(t("Leaderboard"), t("Our top donors. Thank you."), "🏆")
    with session() as db:
        donors = db.query(Donor).order_by(Donor.points.desc()).limit(20).all()
        rows = []
        for i, d in enumerate(donors, 1):
            n = db.query(Donation).filter(Donation.donor_id == d.id).count()
            rows.append((i, d.full_name, d.blood_type, d.points, n, get_badge_tier(n)))
    if not rows:
        theme.empty(t("No donors yet."), "🏆")
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for rank, name, blood, points, n, tier in rows:
        st.markdown(
            f'<div class="lf-card"><div class="lf-row"><div><span class="lf-title">{medals.get(rank, "#" + str(rank))} {theme.esc(name)}</span> '
            f'{theme.blood_badge(blood)}<div class="lf-sub">{theme.esc(tier)} · {n} {t("donations")}</div></div>'
            f'<div class="lf-title">{points} {t("Points")}</div></div></div>', unsafe_allow_html=True)
    theme.footer()
