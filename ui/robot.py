"""The little robot in the bottom corner of every page: an animated button that opens the LifeFlow AI chat.

With a GROQ_API_KEY it answers with the same role-aware assistants as the web app. Without one it still answers common
questions (who can give blood to whom, how to ask for blood, emergency numbers) from built-in rules."""
import re

import streamlit as st
import streamlit.components.v1 as components

from app.routes.ai_routes import (
    assistant_admin, assistant_donor, assistant_guest, assistant_hospital, assistant_receiver, assistant_staff,
)
from app.schemas.ai_schema import AssistantMessageIn
from app.services.ai_client import is_ai_configured
from app.services.matching_service import COMPATIBLE_DONOR_TYPES
from ui import accounts, widgets
from ui.db import session
from ui.i18n import lang, t

LAUNCHER = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent;overflow:hidden;font-family:Inter,system-ui,'Segoe UI',sans-serif}
.wrap{position:absolute;right:6px;bottom:4px;display:flex;align-items:flex-end;gap:6px;cursor:pointer;-webkit-tap-highlight-color:transparent}
.bubble{position:relative;background:#fff;color:#7A1F2B;border:1.5px solid #f3c1c1;border-radius:18px 18px 4px 18px;padding:9px 14px;margin-bottom:46px;
 box-shadow:0 8px 22px rgba(122,31,43,.22);animation:pop 5s ease-in-out infinite;transform-origin:100% 100%;max-width:170px}
.bubble b{display:block;font-size:17px;line-height:1.1}.bubble span{display:block;font-size:11.5px;color:#6b4a4e;margin-top:3px;line-height:1.3}
.bot{position:relative;width:112px;height:124px;animation:float 3.2s ease-in-out infinite;filter:drop-shadow(0 10px 14px rgba(122,31,43,.35))}
.bot:hover{transform:scale(1.07)}
.ring{position:absolute;left:50%;top:50%;width:104px;height:104px;margin:-52px 0 0 -52px;border-radius:50%;border:3px solid rgba(242,107,91,.6);animation:ring 2.4s ease-out infinite}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}
@keyframes pop{0%,100%{transform:scale(1)}50%{transform:scale(1.045)}}
@keyframes ring{0%{transform:scale(.8);opacity:.9}100%{transform:scale(1.35);opacity:0}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
</style></head><body>
<div class="wrap" id="go" title="__TITLE__">
 <div class="bubble"><b>__HELLO__</b><span>__SUB__</span></div>
 <div class="bot"><div class="ring"></div>
 <svg viewBox="0 0 120 130" width="112" height="124" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7A1F2B"/><stop offset=".6" stop-color="#B3202F"/><stop offset="1" stop-color="#F26B5B"/></linearGradient>
  <linearGradient id="hd" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#ffe6e3"/></linearGradient></defs>
  <circle cx="60" cy="66" r="55" fill="url(#bg)"/>
  <line x1="60" y1="16" x2="60" y2="30" stroke="#fff" stroke-width="4" stroke-linecap="round"/>
  <circle cx="60" cy="13" r="6" fill="#FFD166"><animate attributeName="r" values="5;8;5" dur="1.5s" repeatCount="indefinite"/></circle>
  <rect x="22" y="52" width="9" height="22" rx="4.5" fill="#fff"/><rect x="89" y="52" width="9" height="22" rx="4.5" fill="#fff"/>
  <rect x="28" y="28" width="64" height="56" rx="22" fill="url(#hd)" stroke="#fff" stroke-width="3"/>
  <rect x="37" y="40" width="46" height="30" rx="13" fill="#3b0f17"/>
  <ellipse cx="51" cy="54" rx="5.5" ry="7.5" fill="#7CF5FF"><animate attributeName="ry" values="7.5;7.5;1;7.5;7.5" keyTimes="0;.88;.93;.98;1" dur="4s" repeatCount="indefinite"/></ellipse>
  <ellipse cx="69" cy="54" rx="5.5" ry="7.5" fill="#7CF5FF"><animate attributeName="ry" values="7.5;7.5;1;7.5;7.5" keyTimes="0;.88;.93;.98;1" dur="4s" repeatCount="indefinite"/></ellipse>
  <path d="M53 65 Q60 70 67 65" stroke="#7CF5FF" stroke-width="2.4" fill="none" stroke-linecap="round"/>
  <circle cx="35" cy="76" r="3.4" fill="#F26B5B" opacity=".8"/><circle cx="85" cy="76" r="3.4" fill="#F26B5B" opacity=".8"/>
  <rect x="40" y="88" width="40" height="26" rx="11" fill="url(#hd)" stroke="#fff" stroke-width="3"/>
  <path d="M60 107 c-6 -4 -10 -7 -10 -11 a5 5 0 0 1 10 -1.6 a5 5 0 0 1 10 1.6 c0 4 -4 7 -10 11z" fill="#B3202F"><animateTransform attributeName="transform" type="scale" additive="sum" values="1;1.1;1" dur="1.2s" repeatCount="indefinite"/></path>
  <g><rect x="86" y="74" width="9" height="24" rx="4.5" fill="#fff" transform-origin="90 78"><animateTransform attributeName="transform" type="rotate" values="0;-28;0;-28;0" dur="2.4s" repeatCount="indefinite" additive="sum"/></rect></g>
 </svg></div></div>
<script>
document.getElementById('go').addEventListener('click',function(){
  try{var b=window.parent.document.querySelector('.st-key-lf_bot_real button'); if(b){b.click();}}catch(e){}
});
</script></body></html>"""

CSS = """
<style>
.st-key-lf_bot_robot{position:fixed!important;right:10px;bottom:58px;z-index:999990;width:330px!important;height:150px!important;pointer-events:none}
.st-key-lf_bot_robot iframe{width:330px!important;height:150px!important;border:0!important;background:transparent!important;color-scheme:normal;pointer-events:auto}
.st-key-lf_bot_real{position:fixed!important;right:18px;bottom:14px;z-index:999991;width:auto!important}
[data-testid="stPopoverBody"]{min-width:min(400px,92vw)!important;border-radius:18px!important}
@media (max-width:520px){.st-key-lf_bot_robot{right:0;width:250px!important}.st-key-lf_bot_robot iframe{width:250px!important}}
</style>
"""

FAQ = [
    (r"\b(request|need|want|ask for)\b.*\b(blood|bag)|how.*(get|find) blood|خون چاہ|رکویسٹ|ڏيو",
     {"en": "To ask for blood, log in as a patient or hospital, open “Request blood”, choose the blood group, bags and how urgent it is. We check hospital stock first, then alert the nearest matching donors. In an emergency use the red SOS button on your dashboard.",
      "ur": "خون کی درخواست کے لیے مریض یا اسپتال کے طور پر لاگ اِن کریں، “Request blood” کھولیں، بلڈ گروپ، بیگز اور ضرورت کی شدت منتخب کریں۔ ہم پہلے اسپتال کا اسٹاک دیکھتے ہیں، پھر قریبی موزوں ڈونرز کو اطلاع دیتے ہیں۔ ایمرجنسی میں ڈیش بورڈ کا سرخ SOS بٹن استعمال کریں۔"}),
    (r"\b(ambulance|emergency number|helpline|1122|edhi)\b|ایمبولینس|ایمرجنسی نمبر",
     {"en": "Open “Ambulance & contacts” in the menu for phone numbers by city (Rescue 1122, Edhi 115, Chhipa 1020 and more). Please confirm a number works in your district.",
      "ur": "مینو میں “Ambulance & contacts” کھولیں، وہاں شہر کے حساب سے نمبر ملیں گے (ریسکیو 1122، ایدھی 115، چھیپا 1020 وغیرہ)۔ براہ کرم تصدیق کر لیں کہ نمبر آپ کے ضلع میں کام کرتا ہے۔"}),
    (r"\b(who can|can i|eligible|eligibility|donate)\b.*\b(donate|give|eligible)|\bhow often\b|کون خون",
     {"en": "Most healthy adults aged 18 to 60, weighing at least 50 kg, can give blood. Men wait about 3 months between donations, women about 4 months. Use the “Health check chat” to see if you can donate today. A doctor always makes the final decision on the day.",
      "ur": "18 سے 60 سال کے صحت مند بالغ، جن کا وزن کم از کم 50 کلو ہو، خون دے سکتے ہیں۔ مرد تقریباً 3 ماہ اور خواتین تقریباً 4 ماہ بعد دوبارہ دے سکتی ہیں۔ آج دے سکتے ہیں یا نہیں، یہ “Health check chat” سے دیکھیں۔ آخری فیصلہ ہمیشہ ڈاکٹر کرتا ہے۔"}),
    (r"\b(points|badge|leaderboard|certificate)\b|پوائنٹس|سرٹیفکیٹ",
     {"en": "Donors earn points for every donation and invite. Badges grow with your donation count, and every donation gets a certificate with a QR code in “Certificates & donor card”.",
      "ur": "ہر ڈونیشن اور دعوت پر پوائنٹس ملتے ہیں۔ ڈونیشنز بڑھنے پر بیج بڑھتا ہے اور ہر ڈونیشن کا QR والا سرٹیفکیٹ “Certificates & donor card” میں ملتا ہے۔"}),
    (r"\b(hello|hi|hey|salam|assalam)\b|سلام|ہیلو",
     {"en": "Hello! 👋 I am the LifeFlow helper. Ask me about requesting blood, who can donate to whom, emergency numbers, or how to use the app.",
      "ur": "السلام علیکم! 👋 میں لائف فلو کا مددگار ہوں۔ خون کی درخواست، کون کس کو خون دے سکتا ہے، ایمرجنسی نمبرز یا ایپ کے استعمال کے بارے میں پوچھیں۔"}),
]
QUICK = ["How do I ask for blood?", "Who can I donate to?", "Emergency numbers", "Can I donate today?"]
GROUP = re.compile(r"\b(ab|a|b|o)\s*(\+|-|positive|negative|pos|neg)", re.I)


def _blood_group(text: str):
    match = GROUP.search(text)
    if not match:
        return None
    sign = "+" if match.group(2).lower() in ("+", "positive", "pos") else "-"
    return match.group(1).upper() + sign


def offline_answer(message: str) -> str:
    code = lang()
    group = _blood_group(message)
    if group:
        can_receive = COMPATIBLE_DONOR_TYPES[group]
        can_give = [r for r, donors in COMPATIBLE_DONOR_TYPES.items() if group in donors]
        if code == "ur":
            return f"{group} والے مریض کو یہ گروپ خون دے سکتے ہیں: {', '.join(can_receive)}۔ اور {group} والا ڈونر ان کو دے سکتا ہے: {', '.join(can_give)}۔"
        return f"People with {group} can receive blood from: {', '.join(can_receive)}. A {group} donor can give to: {', '.join(can_give)}."
    for pattern, answers in FAQ:
        if re.search(pattern, message, re.I):
            return answers.get(code) or answers.get("ur" if code == "sd" else "en") or answers["en"]
    return {"ur": "میں خون کی درخواست، ڈونیشن کے اصول، بلڈ گروپ کی مطابقت اور ایمرجنسی نمبرز میں مدد کر سکتا ہوں۔ مزید ذہین جوابات کے لیے ایڈمن GROQ_API_KEY شامل کرے۔",
            }.get(code, "I can help with requesting blood, who can donate to whom, donation rules and emergency numbers. For smarter answers, ask the administrator to add a GROQ_API_KEY.")


def reply_to(message: str) -> str:
    """AI answer when a key is set (role-aware, same as the web app); otherwise the built-in rules."""
    if not is_ai_configured():
        return offline_answer(message)
    names = {"ur": "Urdu", "sd": "Sindhi"}
    text = message if lang() == "en" else f"{message}\n(Please reply in {names[lang()]}.)"
    payload = AssistantMessageIn(message=text)
    auth = accounts.current()
    try:
        with session() as db:
            if not auth:
                return assistant_guest(payload, db).reply
            me = accounts.load(db)
            handlers = {"donor": assistant_donor, "receiver": assistant_receiver, "hospital": assistant_hospital,
                        "admin": assistant_admin, "staff": assistant_staff}
            return handlers[auth["role"]](payload, db, me).reply
    except Exception:  # noqa: BLE001
        return offline_answer(message)


@st.fragment
def _chat() -> None:
    history = st.session_state.setdefault("lf_bot_history", [("bot", t("Hi! I am the LifeFlow robot. How can I help you today?"))])
    st.markdown("**🤖 " + t("LifeFlow assistant") + "**")
    box = st.container(height=300, border=False)
    with box:
        for who, text in history:
            with st.chat_message("assistant" if who == "bot" else "user", avatar="🤖" if who == "bot" else None):
                st.write(text)
    if history and history[-1][0] == "bot" and len(history) > 1:
        widgets.listen_button(history[-1][1], lang())
    chips = st.columns(2)
    asked = None
    for i, question in enumerate(QUICK):
        if chips[i % 2].button(t(question), key=f"lf_q_{i}"):
            asked = t(question)
    with st.form("lf_bot_form", clear_on_submit=True, border=False):
        typed = st.text_input(t("Type your question"), label_visibility="collapsed", placeholder=t("Type your question"))
        sent = st.form_submit_button("➤ " + t("Send"), type="primary")
    question = asked or (typed.strip() if sent else "")
    if question:
        history.append(("me", question))
        history.append(("bot", reply_to(question)))
        st.rerun(scope="fragment")
    if not is_ai_configured():
        st.caption(t("Simple answers mode. An administrator can switch on full AI with a GROQ_API_KEY."))


def render() -> None:
    """Call once per page run, after the page itself: the animated robot with a Hello bubble, and the chat it opens."""
    st.markdown(CSS, unsafe_allow_html=True)
    page = (LAUNCHER.replace("__HELLO__", t("Hello! 👋")).replace("__SUB__", t("I am LifeFlow AI. Ask me anything."))
            .replace("__TITLE__", t("Chat with LifeFlow AI")))
    with st.container(key="lf_bot_robot"):
        components.html(page, height=150)
    with st.container(key="lf_bot_real"):
        with st.popover("💬 " + t("Chat with LifeFlow AI")):
            _chat()
