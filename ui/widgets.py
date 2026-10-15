"""Reusable pieces used by several pages: place and phone inputs, the request form, voice assistant, slip scanner,
request cards with timeline / ambulance & ETA / likely responders, and the conversational health check."""
import hashlib
import json
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

from app.models.request import BloodRequest
from app.models.request_event import RequestEvent
from app.routes.request_routes import create_request_for
from app.routes.sos_routes import SosIn, send_sos
from app.schemas.request_schema import BloodRequestCreate
from app.services import insight_logic as logic
from app.services import v6_service as svc
from app.services.ai_client import NOT_CONFIGURED_MESSAGE, is_ai_configured, transcribe_audio
from app.services.ai_v6_core import run_slip_scan, run_voice_assistant
from ui import accounts, health, theme
from ui.db import friendly_error
from ui.i18n import lang, t

BLOOD_TYPES = ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"]
SPEECH_CODES = {"en": "en-US", "ur": "ur-PK", "sd": "sd-PK"}


# ------------------------------------------------------------------ small helpers
def new_audio(key: str, audio):
    """Returns the bytes of a fresh recording once, so a rerun does not process the same clip twice."""
    if audio is None:
        return None
    data = audio.getvalue()
    signature = hashlib.md5(data).hexdigest()
    if st.session_state.get(key + "_sig") == signature:
        return None
    st.session_state[key + "_sig"] = signature
    return data


def listen_button(text: str, language: str) -> None:
    """A button that reads text aloud with the browser's own voice (Sindhi falls back to Urdu, then English)."""
    code = SPEECH_CODES.get(language, "en-US")
    payload = json.dumps({"text": text, "code": code, "short": code.split("-")[0]})
    components.html(
        f"""<button id="b" style="font:600 14px Inter,system-ui,sans-serif;padding:8px 16px;border-radius:12px;border:1px solid #ccc;
        background:#fff;cursor:pointer">🔊 Listen</button>
        <script>
        const cfg = {payload};
        document.getElementById('b').onclick = () => {{
          const synth = window.speechSynthesis; if (!synth) return;
          synth.cancel();
          const u = new SpeechSynthesisUtterance(cfg.text);
          const voices = synth.getVoices();
          const order = [cfg.code, cfg.short, cfg.short === 'sd' ? 'ur' : null, 'en'].filter(Boolean);
          let v = null;
          for (const c of order) {{ v = voices.find(x => x.lang && x.lang.toLowerCase().startsWith(c.toLowerCase())); if (v) break; }}
          if (v) {{ u.voice = v; u.lang = v.lang; }} else {{ u.lang = cfg.code; }}
          synth.speak(u);
        }};
        </script>""",
        height=46,
    )


def phone_input(label: str, key: str) -> str:
    cols = st.columns([1.2, 2.8])
    names = [f"{c} ({n})" for n, c in accounts.COUNTRY_CODES]
    pick = cols[0].selectbox(t("Country code"), names, key=key + "_cc")
    number = cols[1].text_input(label, key=key + "_num", placeholder="3001234567")
    code = pick.split(" ")[0]
    return accounts.full_phone(code, number)


def location_inputs(key: str, title: str = "Where do you live?") -> dict:
    """Plain-words place (village, area, city...). Coordinates are looked up automatically; nobody needs latitude/longitude."""
    st.markdown(f"**{t(title)}**")
    st.caption(t("Write your place in simple words. You do not need to know latitude or longitude."))
    c1, c2 = st.columns(2)
    village = c1.text_input(t("Village"), key=key + "_village")
    area = c2.text_input(t("Area"), key=key + "_area")
    c3, c4, c5 = st.columns(3)
    city = c3.text_input(t("City"), key=key + "_city")
    state = c4.text_input(t("State"), key=key + "_state", placeholder="Sindh")
    country = c5.text_input(t("Country"), value="Pakistan", key=key + "_country")
    place = {"village": village.strip() or None, "area": area.strip(), "city": city.strip(), "state": state.strip() or None, "country": country.strip(),
             "latitude": None, "longitude": None}
    with st.expander(t("I know my coordinates")):
        lat = st.number_input("Latitude", value=None, format="%.6f", key=key + "_lat")
        lng = st.number_input("Longitude", value=None, format="%.6f", key=key + "_lng")
        if lat is not None and lng is not None:
            place["latitude"], place["longitude"] = float(lat), float(lng)
    return place


def show_error(error: Exception) -> None:
    st.error(friendly_error(error))


# ------------------------------------------------------------------ voice assistant
def voice_assistant(role: str, key: str = "va", fill_key: str = "rf", allow_fill: bool = True) -> None:
    """Speak or type in Urdu / Sindhi / English. For blood requests the details can fill the request form."""
    default = lang() if lang() in SPEECH_CODES else "ur"
    chosen = st.radio(t("Language"), ["ur", "sd", "en"], format_func=lambda c: {"ur": "اردو", "sd": "سنڌي", "en": "English"}[c],
                      horizontal=True, key=key + "_lang", index=["ur", "sd", "en"].index(default))
    st.caption(t("Speak in your own language. Example: “مجھے دو بوتل او نیگیٹو خون چاہیے، آپریشن ہے”. You always check the details before anything is sent."))
    if not is_ai_configured():
        st.info(NOT_CONFIGURED_MESSAGE)
    audio = st.audio_input(t("Tap to speak"), key=key + "_audio")
    typed = st.text_input(t("Or type here"), key=key + "_text")
    send = st.button(t("Send"), key=key + "_send")

    transcript = None
    data = new_audio(key, audio)
    if data is not None:
        with st.spinner(t("Listening and thinking...")):
            transcript = transcribe_audio(data, "voice.wav", "audio/wav", chosen) or ""
        if not transcript:
            st.session_state[key + "_result"] = {"transcript": None, "intent": "unknown", "fields": None, "language": chosen,
                                                 "reply": health_retry(chosen), "note": "Could not hear that clearly. You can type instead."}
    elif send and typed.strip():
        transcript = typed.strip()[:800]
    if transcript:
        with st.spinner(t("Listening and thinking...")):
            st.session_state[key + "_result"] = run_voice_assistant(transcript, chosen, role)

    result = st.session_state.get(key + "_result")
    if not result:
        return
    if result.get("transcript"):
        st.caption(f"{t('I heard')}: “{result['transcript']}”")
    theme.bubble(result["reply"], "bot")
    if result.get("note"):
        st.caption(result["note"])
    listen_button(result["reply"], result.get("language", chosen))
    if result.get("intent") == "request_blood" and result.get("fields"):
        fields = {k: v for k, v in result["fields"].items() if v not in (None, "") and k != "hospital_name"}
        if fields:
            st.table({t("Detail"): list(fields.keys()), t("Value"): [str(v) for v in fields.values()]})
            if allow_fill and st.button(t("Use these details in the form"), key=key + "_use", type="primary"):
                st.session_state[fill_key + "_prefill"] = fields
                st.session_state[key + "_result"] = None
                st.rerun()
    elif result.get("intent") == "emergency_numbers":
        st.caption(t("Open the “Ambulance & contacts” page for phone numbers."))


def health_retry(language: str) -> str:
    return {"ur": "میں سمجھ نہیں سکا۔ براہ کرم دوبارہ بولیں یا لکھ دیں۔", "sd": "مان سمجهي نه سگهيس. مهرباني ڪري ٻيهر ڳالهايو يا لکي ڏيو."}.get(
        language, "I could not understand that. Please try again, or type it.")


# ------------------------------------------------------------------ doctor slip scanner
def slip_scanner(key: str = "slip", fill_key: str = "rf") -> None:
    st.caption(t("Take a clear photo of the doctor's slip or blood requisition form. AI reads it and fills the form for you to check. The photo is not saved."))
    if not is_ai_configured():
        st.info(NOT_CONFIGURED_MESSAGE)
    source = st.radio(t("Photo from"), [t("Upload a photo"), t("Use the camera")], horizontal=True, key=key + "_src")
    image = st.file_uploader(t("Take or choose a photo"), type=["jpg", "jpeg", "png", "webp"], key=key + "_file") if source == t("Upload a photo") \
        else st.camera_input(t("Take or choose a photo"), key=key + "_cam")
    data = new_audio(key + "_img", image) if image is not None else None   # same once-only guard works for any upload
    if data is not None:
        if len(data) > 4 * 1024 * 1024:
            st.session_state[key + "_result"] = {"read_ok": False, "note": "Image too large (max 4 MB).", "warnings": []}
        else:
            with st.spinner(t("Reading the slip...")):
                st.session_state[key + "_result"] = run_slip_scan(data, getattr(image, "type", None) or "image/jpeg")
    result = st.session_state.get(key + "_result")
    if not result:
        return
    if not result.get("read_ok"):
        st.error(t(result.get("note", "Could not read the photo just now.")))
        return
    fields = {k: v for k, v in result["fields"].items() if v not in (None, "") and k != "hospital_name"}
    st.table({t("Detail"): list(fields.keys()), t("Value"): [str(v) for v in fields.values()]})
    for warning in result.get("warnings", []):
        st.warning(t(warning))
    st.caption(t("Please check every field. The photo was not saved."))
    if st.button(t("Use these details in the form"), key=key + "_use", type="primary"):
        st.session_state[fill_key + "_prefill"] = fields
        st.session_state[key + "_result"] = None
        st.rerun()


# ------------------------------------------------------------------ request form
URGENCY = {"emergency": "Emergency", "days": "Within some days", "months": "Within some months"}
_FIELD_KEYS = {"blood_type_needed": "blood", "units_needed": "units", "patient_name": "pname", "patient_age": "page",
               "patient_gender": "pgender", "medical_reason": "reason", "urgency_type": "urg", "urgency_value": "urgval"}


def request_form(db, account, requester_type: str, key: str = "rf"):
    """Create a blood request. Returns the new BloodRequest (after saving) or None."""
    prefill = st.session_state.pop(key + "_prefill", None)
    if prefill:
        for field, value in prefill.items():
            wkey = f"{key}_{_FIELD_KEYS.get(field, field)}"
            if field == "blood_type_needed" and value not in BLOOD_TYPES:
                continue
            if field == "patient_gender" and value not in ("Male", "Female", "Other"):
                continue
            if field == "urgency_value" and prefill.get("urgency_type") not in ("days", "months"):
                continue
            if field == "urgency_type" and value not in URGENCY:
                continue
            if field in ("units_needed", "urgency_value"):
                value = max(1, min(int(value), 20 if field == "units_needed" else 365))
            if field == "patient_age":
                value = str(int(value))
            st.session_state[wkey] = value
        st.success(t("Form filled. Please check it before sending."))

    c1, c2 = st.columns(2)
    blood = c1.selectbox(t("Blood type needed"), BLOOD_TYPES, key=key + "_blood")
    units = c2.number_input(t("Bags needed"), min_value=1, max_value=20, step=1, key=key + "_units", help=t("One bag is about 350 ml of blood"))
    c3, c4, c5 = st.columns([2, 1, 1])
    pname = c3.text_input(t("Patient name, optional"), key=key + "_pname")
    page_text = c4.text_input(t("Patient age, optional"), key=key + "_page", max_chars=3)
    pgender = c5.selectbox(t("Patient gender, optional"), ["", "Female", "Male", "Other"], format_func=lambda v: v or t("Prefer not to say"), key=key + "_pgender")
    reason = st.text_input(t("Reason, optional"), key=key + "_reason", placeholder="Surgery, accident, thalassemia...")
    urg = st.radio(t("How soon is the blood needed?"), list(URGENCY), format_func=lambda v: t(URGENCY[v]), horizontal=True, key=key + "_urg")
    urgval = None
    if urg in ("days", "months"):
        urgval = st.number_input(t("How many " + urg + "?"), min_value=1, max_value=365, step=1, key=key + "_urgval")

    where = st.radio(t("Where is the blood needed?"), [t("At my saved location"), t("At a different place")], horizontal=True, key=key + "_where")
    place = None
    if where == t("At a different place"):
        place = location_inputs(key + "_loc", "Place where blood is needed")

    if st.button(t("Send request"), type="primary", key=key + "_go"):
        try:
            if place:
                place = accounts.place_with_coordinates(place)
                lat, lng = place["latitude"], place["longitude"]
            else:
                lat, lng = account.latitude, account.longitude
            page = None
            if page_text.strip():
                if not page_text.strip().isdigit():
                    raise ValueError("Patient age must be a number.")
                page = int(page_text.strip())
            data = BloodRequestCreate(
                blood_type_needed=blood, units_needed=int(units), patient_name=pname or None,
                patient_age=page, patient_gender=pgender or None,
                medical_reason=reason.strip() or None, urgency_type=urg, urgency_value=int(urgval) if urgval else None,
                latitude=lat, longitude=lng,
            )
            created = create_request_for(db, requester_type, account, data)
            return created
        except Exception as error:  # noqa: BLE001
            show_error(error)
    return None


def sos_box(db, account, role: str, key: str = "sos") -> None:
    with st.container(border=True):
        st.markdown("### 🚨 " + t("Emergency SOS"))
        st.caption(t("One tap. Alerts every compatible donor within 100 km and the closest hospitals."))
        c1, c2 = st.columns([1, 1])
        blood = c1.selectbox(t("Blood type needed"), BLOOD_TYPES, key=key + "_blood")
        units = c2.number_input(t("Bags needed"), min_value=1, max_value=10, step=1, key=key + "_units")
        if st.button("🚨 " + t("Send SOS now"), type="primary", key=key + "_go"):
            try:
                sent = send_sos(SosIn(blood_type_needed=blood, units_needed=int(units)), db, (role, account))
                st.success(t("SOS sent. Request number") + f" #{sent.id}.")
            except Exception as error:  # noqa: BLE001
                show_error(error)


# ------------------------------------------------------------------ request cards
def request_summary_html(r: BloodRequest) -> str:
    urgency = theme.badge("Emergency", "emergency") if r.urgency_type == "emergency" else theme.badge(f"{r.urgency_value or ''} {r.urgency_type}", "neutral")
    sos = theme.badge("SOS", "sos") if r.is_sos else ""
    patient = f" · {theme.esc(r.patient_name)}" if r.patient_name else ""
    reason = f" · {theme.esc(r.medical_reason)}" if r.medical_reason else ""
    return (
        f'<div class="lf-row"><div><span class="lf-title">{theme.blood_badge(r.blood_type_needed)} &nbsp;'
        f'{r.units_fulfilled}/{r.units_needed} bags</span> {urgency} {sos}</div>'
        f'<div>{theme.status_badge(r.status)}</div></div>'
        f'{theme.progress(r.units_fulfilled or 0, r.units_needed or 1)}'
        f'<div class="lf-sub">Request #{r.id} · {r.created_at:%d %b %Y, %H:%M}{patient}{reason}</div>'
    )


def timeline_view(db, request_id: int) -> None:
    events = db.query(RequestEvent).filter(RequestEvent.request_id == request_id).order_by(RequestEvent.id).all()
    if not events:
        st.caption(t("Nothing has happened yet."))
        return
    theme.timeline([(e.message, e.created_at.strftime("%d %b, %H:%M")) for e in events])


def eta_view(db, blood_request: BloodRequest) -> None:
    plan = svc.build_eta_plan(db, blood_request)
    st.info(plan["advice"])
    if plan["blood_sources"]:
        st.markdown("**" + t("Where blood can come from") + "**")
        for s in plan["blood_sources"]:
            stock = f"{s['units_in_stock']} " + t("bag(s) in stock") if s["has_stock"] else t("No stock reported")
            st.markdown(f"- **{s['name']}** · {s['distance_km']} km · ~{s['eta_text']} · {stock} · 📞 {s['phone_number']} · [🗺️ {t('Map')}]({s['maps_url']})")
    if plan["donors"]:
        st.markdown("**" + t("Nearest matching donors") + "**")
        for d in plan["donors"]:
            link = f" · [🗺️ {t('Map')}]({d['maps_url']})" if d.get("maps_url") else ""
            st.markdown(f"- {d['blood_type']} · **{d['name']}** · {d['distance_km']} km · ~{d['eta_text']}{link}")
    if plan["ambulances"]:
        st.markdown("**" + t("Ambulance numbers") + "**")
        for a in plan["ambulances"]:
            st.markdown(f"- {a['name']}{' · ' + a['city'] if a['city'] else ''} · 📞 **{a['phone_number']}**")
    for b in plan["blood_banks"]:
        st.markdown(f"- 🩸 {b['name']} · 📞 **{b['phone_number']}**")
    st.caption(t(plan["assumptions"]))


def response_view(db, blood_request: BloodRequest) -> None:
    plan = svc.response_plan(db, blood_request)
    st.success(f"{t('Alert the first')} {plan['alert_first_count']} {t('donor(s): about')} {plan['expected_acceptances']} "
               f"{t('are expected to say yes for')} {plan['units_still_needed']} {t('bag(s) needed.')}")
    if not plan["likely_responders"]:
        st.caption(t("No eligible donor nearby yet."))
    labels = {"fast": "fast reply", "normal": "normal reply", "slow": "slow reply"}
    for d in plan["likely_responders"]:
        pct = round(d["probability"] * 100)
        st.markdown(f"**{d['name']}** ({d['blood_type']}) · {d['distance_km']} km · {t(labels[d['speed']])}")
        st.progress(pct / 100, text=f"{pct}% · " + " · ".join(d["reasons"]))
    st.caption(t(plan["note"]))


def stars_box(key: str):
    """Star picker and comment. Returns (stars, comment) or None."""
    c1, c2 = st.columns([1, 3])
    stars = c1.select_slider(t("Stars"), options=[1, 2, 3, 4, 5], value=5, format_func=lambda n: "⭐" * n, key=key + "_s")
    comment = c2.text_input(t("Comment, optional"), key=key + "_c", max_chars=200)
    return int(stars), comment.strip() or None


def rate_donors_box(db, role: str, account, blood_request: BloodRequest) -> None:
    """Hospitals and patients rate the donors who gave blood for one of their requests."""
    from app.models.donation import Donation
    from app.models.donor import Donor
    from app.models.rating import Rating
    from app.routes.rating_routes import rate_donor
    from app.schemas.rating_schema import RatingCreate

    donations = db.query(Donation).filter(Donation.request_id == blood_request.id).all()
    if not donations:
        return
    with st.expander("⭐ " + t("Donors who helped: say thank you")):
        for d in donations:
            donor = db.query(Donor).filter(Donor.id == d.donor_id).first()
            if not donor:
                continue
            st.markdown(f"**{theme.esc(donor.full_name)}** {theme.blood_badge(donor.blood_type)} · {d.units_donated} {t('bags')} · 📞 {theme.esc(donor.phone_number)}",
                        unsafe_allow_html=True)
            done = db.query(Rating).filter(Rating.donation_id == d.id, Rating.direction == "requester_to_donor").first()
            if done:
                st.caption("✅ " + t("You rated this donor") + f": {'⭐' * done.stars}")
                continue
            stars, comment = stars_box(f"rd_{d.id}")
            if st.button(t("Send rating"), key=f"rd_go_{d.id}"):
                try:
                    rate_donor(d.id, RatingCreate(stars=stars, comment=comment), db, (role, account))
                    st.rerun()
                except Exception as error:  # noqa: BLE001
                    st.error(friendly_error(error))


def request_cards(db, requests, role: str, allow_insights: bool = True, show_responders: bool = True) -> None:
    if not requests:
        theme.empty(t("You have not sent a request yet."), "🩸")
        return
    for r in requests:
        with st.container(border=True):
            st.markdown(request_summary_html(r), unsafe_allow_html=True)
            if allow_insights:
                with st.expander(t("Live tracking")):
                    timeline_view(db, r.id)
                if r.status in ("open", "held"):
                    with st.expander("🚑 " + t("Ambulance & travel time")):
                        eta_view(db, r)
                    if show_responders:
                        with st.expander("🎯 " + t("Donors most likely to respond")):
                            response_view(db, r)
            if role in ("hospital", "receiver"):
                rate_donors_box(db, role, accounts.load(db), r)


# ------------------------------------------------------------------ health questionnaire (form) and chat
def questionnaire(key: str, defaults: dict = None) -> dict:
    """The full health form. Returns the answers dict (same keys the server rules use)."""
    defaults = defaults or {}
    c1, c2, c3 = st.columns(3)
    age = c1.number_input(t("Age"), min_value=0, max_value=120, value=defaults.get("age") or 25, key=key + "_age")
    gender_options = ["male", "female"]
    gender = c2.selectbox(t("Gender"), gender_options, format_func=lambda g: t("Male") if g == "male" else t("Female"),
                          index=gender_options.index(defaults.get("gender")) if defaults.get("gender") in gender_options else 0, key=key + "_gender")
    weight = c3.number_input(t("Weight (kg)"), min_value=20.0, max_value=250.0, value=float(defaults.get("weight_kg") or 60.0), step=0.5, key=key + "_weight")
    c4, c5 = st.columns(2)
    hb = c4.number_input(t("Haemoglobin (g/dL), optional"), min_value=3.0, max_value=25.0, value=None, step=0.1, key=key + "_hb")
    last = c5.date_input(t("Date of your last blood donation, optional"), value=None, max_value=datetime.utcnow().date(), key=key + "_last")
    answers = health.empty_answers()
    answers.update({"age": int(age), "gender": gender, "weight_kg": float(weight), "hemoglobin": float(hb) if hb is not None else None,
                    "last_donation_date": last.isoformat() if last else None})
    for title, items in health.groups_for(gender):
        st.markdown(f"**{t(title)}**")
        for field, question in items:
            answers[field] = st.checkbox(t(question), key=f"{key}_q_{field}")
    return answers


def verdict_box(result: dict) -> None:
    if result["eligible"]:
        st.success("✅ " + t("Good news: you can register as a blood donor."))
        return
    lines = "\n".join(f"- {t(r['message'])}" for r in result["reasons"])
    extra = ""
    if result.get("retry_after_date"):
        extra += f"\n\n{t('You can try again after')} **{result['retry_after_date']}**."
    if result.get("permanent"):
        extra += f"\n\n{t('Please speak to a doctor. You can still help by sharing LifeFlow with others.')}"
    st.error(f"**{t('You cannot register as a donor right now.')}**\n\n{lines}{extra}")


def health_chat(key: str = "hc") -> dict:
    """One question at a time. Returns the answers dict when finished, otherwise None."""
    language = lang() if lang() in SPEECH_CODES else "en"
    state = st.session_state.setdefault(key, {"i": 0, "answers": health.empty_answers(), "log": [], "done": False})
    texts = health.CHAT_TEXT.get(language, {})
    from ui.i18n import _table  # translated yes/no questions come from the same table as the web app

    def ask_text(step_type: str, english: str) -> str:
        return texts.get(step_type) or _table().get(language, {}).get(english, english)

    steps = health.chat_steps(state["answers"].get("gender"))
    if not state["log"]:
        state["log"].append(("bot", texts.get("hello", "Hello! I will ask a few simple questions to see if you can give blood.")))
        state["log"].append(("bot", ask_text(steps[0][1], steps[0][2])))
    for who, text in state["log"]:
        theme.bubble(text, who)

    if state["done"]:
        return state["answers"]
    field, step_type, english = steps[state["i"]]
    st.progress(state["i"] / len(steps))

    def accept(value_text: str, new_answers: dict) -> None:
        state["answers"].update(new_answers)
        state["log"].append(("me", value_text))
        state["i"] += 1
        upcoming = health.chat_steps(state["answers"].get("gender"))
        if state["i"] >= len(upcoming):
            state["done"] = True
        else:
            state["log"].append(("bot", ask_text(upcoming[state["i"]][1], upcoming[state["i"]][2])))
        st.rerun()

    def misunderstood(text: str) -> None:
        state["log"].append(("me", text))
        state["log"].append(("bot", texts.get("retry", "Sorry, I did not understand. Please try again.")))
        st.rerun()

    def apply_text(text: str) -> None:
        reply = health.interpret(step_type, text, english)
        if not reply.get("understood"):
            misunderstood(text)
        value = reply.get("value")
        if step_type == "yes_no":
            accept(t("Yes") if value else t("No"), {field: bool(value)})
        elif step_type == "gender":
            accept(t("Male") if value == "male" else t("Female"), {"gender": value})
        elif step_type == "last_donation":
            accept(text, {"last_donation_date": None if reply.get("never") else value})
        elif step_type == "hemoglobin":
            accept(text, {"hemoglobin": value})
        elif step_type == "weight":
            accept(text, {"weight_kg": float(value)})
        else:
            accept(text, {"age": int(value)})

    if step_type == "yes_no":
        c1, c2 = st.columns(2)
        if c1.button("✅ " + t("Yes"), key=f"{key}_y{state['i']}"):
            accept(t("Yes"), {field: True})
        if c2.button("❌ " + t("No"), key=f"{key}_n{state['i']}"):
            accept(t("No"), {field: False})
    elif step_type == "gender":
        c1, c2 = st.columns(2)
        if c1.button(t("Male"), key=f"{key}_m{state['i']}"):
            accept(t("Male"), {"gender": "male"})
        if c2.button(t("Female"), key=f"{key}_f{state['i']}"):
            accept(t("Female"), {"gender": "female"})
    else:
        typed = st.text_input(t("Type your answer"), key=f"{key}_t{state['i']}")
        if st.button(t("Send"), key=f"{key}_s{state['i']}") and typed.strip():
            apply_text(typed.strip())

    with st.expander("🎤 " + t("or speak your answer")):
        audio = st.audio_input(t("Tap to speak"), key=f"{key}_a{state['i']}")
        data = new_audio(f"{key}_a{state['i']}", audio)
        if data is not None:
            spoken = transcribe_audio(data, "voice.wav", "audio/wav", language)
            if spoken:
                if step_type == "yes_no":
                    answer = logic.interpret_yes_no(spoken)
                    if answer is None:
                        reply = health.interpret("yes_no", spoken, english)
                        answer = reply.get("value") if reply.get("understood") else None
                    if answer is None:
                        misunderstood(spoken)
                    accept(t("Yes") if answer else t("No"), {field: bool(answer)})
                else:
                    apply_text(spoken)
            else:
                st.warning(t("Could not hear that. Please tap Yes or No, or type."))
    return None
