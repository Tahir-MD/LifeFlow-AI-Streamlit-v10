"""Look and feel: global CSS and small HTML building blocks (hero, stat cards, badges, steps)."""
import html

import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
@import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css');

:root {
  --lf-primary: #B3202F;
  --lf-primary-dark: #7A1F2B;
  --lf-accent: #F26B5B;
  --lf-soft: rgba(179, 32, 47, 0.07);
  --lf-border: rgba(128, 128, 128, 0.22);
  --lf-radius: 16px;
  --lf-shadow: 0 8px 28px rgba(122, 31, 43, 0.10);
}

html, body, [class*="css"], .stApp { font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; }
.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1180px; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
h1, h2, h3 { letter-spacing: -0.02em; font-weight: 700; }
h1 { font-size: 2rem; }

/* ---------- sidebar ---------- */
section[data-testid="stSidebar"] { border-right: 1px solid var(--lf-border); }
section[data-testid="stSidebar"] .block-container { padding-top: 1rem; }
.lf-brand { display: flex; align-items: center; gap: 10px; padding: 4px 4px 14px; }
.lf-brand .drop { width: 38px; height: 38px; border-radius: 12px; background: linear-gradient(135deg, var(--lf-primary), var(--lf-accent));
  display: grid; place-items: center; color: #fff; font-size: 20px; box-shadow: var(--lf-shadow); }
.lf-brand b { font-size: 1.15rem; font-weight: 800; letter-spacing: -0.02em; }
.lf-brand small { display: block; opacity: .65; font-size: .72rem; margin-top: -2px; }
.lf-user { border: 1px solid var(--lf-border); border-radius: 14px; padding: 12px 14px; background: var(--lf-soft); margin: 8px 0 6px; }
.lf-user .name { font-weight: 700; }
.lf-user .role { font-size: .78rem; opacity: .7; text-transform: capitalize; }

/* ---------- hero ---------- */
.lf-hero { position: relative; overflow: hidden; border-radius: 24px; padding: 54px 44px 48px; color: #fff;
  background: radial-gradient(1200px 400px at 90% -10%, rgba(255,255,255,.18), transparent 60%),
              linear-gradient(135deg, #7A1F2B 0%, #B3202F 55%, #E04A4A 100%); box-shadow: var(--lf-shadow); }
.lf-hero::after { content: "🩸"; position: absolute; right: 36px; bottom: -18px; font-size: 190px; opacity: .13; transform: rotate(14deg); }
.lf-hero .eyebrow { display: inline-block; background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28);
  padding: 5px 14px; border-radius: 99px; font-size: .78rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; }
.lf-hero h1 { color: #fff; font-size: clamp(1.9rem, 4.2vw, 3.1rem); line-height: 1.08; margin: 16px 0 12px; font-weight: 800; max-width: 760px; }
.lf-hero p { color: rgba(255,255,255,.88); font-size: 1.08rem; max-width: 640px; line-height: 1.55; margin: 0; }

/* ---------- page header ---------- */
.lf-page-head { margin: 2px 0 18px; }
.lf-page-head h1 { margin: 0; font-size: 1.75rem; }
.lf-page-head p { margin: 4px 0 0; opacity: .72; }

/* ---------- stat cards ---------- */
.lf-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 14px; margin: 14px 0 20px; }
.lf-stat { border: 1px solid var(--lf-border); border-radius: var(--lf-radius); padding: 16px 18px; background: var(--lf-soft); }
.lf-stat .icon { font-size: 1.3rem; }
.lf-stat .num { font-size: 1.85rem; font-weight: 800; letter-spacing: -0.03em; line-height: 1.15; margin-top: 4px; }
.lf-stat .lab { font-size: .82rem; opacity: .72; font-weight: 500; }
.lf-stat.warn { background: rgba(240, 160, 30, .10); }
.lf-stat.ok { background: rgba(30, 140, 70, .09); }

/* ---------- cards & lists ---------- */
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: var(--lf-radius) !important; }
.lf-card { border: 1px solid var(--lf-border); border-radius: var(--lf-radius); padding: 18px 20px; margin-bottom: 12px; }
.lf-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.lf-title { font-weight: 700; font-size: 1.02rem; }
.lf-sub { opacity: .72; font-size: .88rem; margin-top: 2px; }
.lf-empty { text-align: center; padding: 34px 16px; border: 1.5px dashed var(--lf-border); border-radius: var(--lf-radius); opacity: .8; }
.lf-empty .big { font-size: 2rem; }

/* ---------- badges ---------- */
.lf-badge { display: inline-block; padding: 3px 11px; border-radius: 99px; font-size: .78rem; font-weight: 700; line-height: 1.5; }
.lf-badge.blood { background: var(--lf-primary); color: #fff; min-width: 38px; text-align: center; }
.lf-badge.open { background: rgba(30, 140, 70, .14); color: #18783d; }
.lf-badge.fulfilled { background: rgba(40, 90, 200, .13); color: #2a56b8; }
.lf-badge.held, .lf-badge.flagged { background: rgba(240, 160, 30, .18); color: #a86800; }
.lf-badge.rejected, .lf-badge.emergency { background: rgba(200, 40, 40, .14); color: #b32020; }
.lf-badge.days, .lf-badge.months, .lf-badge.neutral { background: rgba(128,128,128,.16); }
.lf-badge.sos { background: #b32020; color: #fff; }

/* ---------- progress ---------- */
.lf-progress { height: 8px; background: rgba(128,128,128,.2); border-radius: 99px; overflow: hidden; margin-top: 8px; }
.lf-progress > span { display: block; height: 100%; background: linear-gradient(90deg, var(--lf-primary), var(--lf-accent)); border-radius: 99px; }

/* ---------- steps ---------- */
.lf-steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin: 10px 0 22px; }
.lf-step { border: 1px solid var(--lf-border); border-radius: var(--lf-radius); padding: 20px; }
.lf-step .n { width: 32px; height: 32px; border-radius: 10px; display: grid; place-items: center; background: var(--lf-primary); color: #fff; font-weight: 800; margin-bottom: 10px; }
.lf-step b { display: block; margin-bottom: 4px; }
.lf-step span { opacity: .75; font-size: .92rem; line-height: 1.5; }

/* ---------- timeline ---------- */
.lf-timeline { border-left: 3px solid var(--lf-border); margin: 6px 0 4px 8px; padding-left: 16px; }
.lf-event { position: relative; margin-bottom: 12px; font-size: .92rem; }
.lf-event::before { content: ""; position: absolute; left: -23px; top: 5px; width: 11px; height: 11px; border-radius: 50%; background: var(--lf-primary); }
.lf-event small { display: block; opacity: .6; }

/* ---------- chat ---------- */
.lf-bubble { max-width: 86%; padding: 10px 14px; border-radius: 16px; margin: 6px 0; line-height: 1.5; }
.lf-bubble.bot { background: var(--lf-soft); border: 1px solid var(--lf-border); border-bottom-left-radius: 4px; }
.lf-bubble.me { background: var(--lf-primary); color: #fff; margin-left: auto; border-bottom-right-radius: 4px; }

/* ---------- buttons & inputs ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button, .stLinkButton > a {
  border-radius: 12px; font-weight: 600; padding: .55rem 1.15rem; transition: transform .08s ease, box-shadow .15s ease; }
.stButton > button:hover, .stFormSubmitButton > button:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(122,31,43,.18); }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"], .stFormSubmitButton > button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: linear-gradient(135deg, var(--lf-primary), #D0384A); border: 0; color: #fff; }
.stTextInput input, .stNumberInput input, .stTextArea textarea, div[data-baseweb="select"] > div { border-radius: 12px !important; }
button[data-baseweb="tab"] { font-weight: 600; }
.stAlert { border-radius: 14px; }


/* ---------- sidebar navigation ---------- */
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #FFF6F5 0%, #FBE9E7 100%); }
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavLink"] { border-radius: 12px !important; margin: 2px 4px; padding: .5rem .8rem !important; font-weight: 600; transition: background .15s, transform .12s; }
[data-testid="stSidebarNav"] a:hover, [data-testid="stSidebarNavLink"]:hover { background: rgba(179,32,47,.10) !important; transform: translateX(3px); }
[data-testid="stSidebarNav"] a[aria-current="page"], [data-testid="stSidebarNavLink"][aria-current="page"] {
  background: linear-gradient(135deg, #B3202F, #E04A4A) !important; color: #fff !important; box-shadow: 0 6px 16px rgba(179,32,47,.28); }
[data-testid="stSidebarNav"] a[aria-current="page"] *, [data-testid="stSidebarNavLink"][aria-current="page"] * { color: #fff !important; }
[data-testid="stSidebarNavSeparator"] { font-weight: 800; letter-spacing: .06em; text-transform: uppercase; font-size: .72rem; color: var(--lf-primary-dark); }

/* ---------- richer inputs, cards ---------- */
.stTextInput input, .stNumberInput input, .stTextArea textarea { border: 1.5px solid rgba(179,32,47,.18) !important; background: #fff; transition: box-shadow .15s, border-color .15s; }
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus { border-color: var(--lf-primary) !important; box-shadow: 0 0 0 3px rgba(179,32,47,.14) !important; }
div[data-baseweb="select"] > div { border: 1.5px solid rgba(179,32,47,.18) !important; }
.stTextInput label p, .stNumberInput label p, .stTextArea label p, .stSelectbox label p, .stMultiSelect label p, .stDateInput label p, .stTimeInput label p { font-weight: 600; }
div[data-testid="stVerticalBlockBorderWrapper"] { box-shadow: 0 4px 18px rgba(122,31,43,.06); transition: box-shadow .2s, transform .2s; }
div[data-testid="stVerticalBlockBorderWrapper"]:hover { box-shadow: 0 10px 28px rgba(122,31,43,.12); }
.lf-stat { transition: transform .2s, box-shadow .2s; background: linear-gradient(160deg, rgba(179,32,47,.06), rgba(242,107,91,.05)); }
.lf-stat:hover { transform: translateY(-3px); box-shadow: var(--lf-shadow); }
.lf-page-head h1 { background: linear-gradient(90deg, #7A1F2B, #D0384A); -webkit-background-clip: text; background-clip: text; color: transparent; }
button[data-baseweb="tab"] { border-radius: 12px 12px 0 0; padding: .6rem 1rem; }
button[data-baseweb="tab"][aria-selected="true"] { color: var(--lf-primary); background: rgba(179,32,47,.07); }

/* ---------- welcome page ---------- */
.lf-welcome { position: relative; overflow: hidden; border-radius: 28px; padding: 70px 40px 60px; text-align: center; color: #fff;
  background: radial-gradient(900px 420px at 15% -10%, rgba(255,255,255,.22), transparent 60%), radial-gradient(700px 400px at 100% 110%, rgba(255,209,102,.25), transparent 60%),
              linear-gradient(135deg, #5E1420 0%, #B3202F 50%, #F26B5B 100%); background-size: 200% 200%; animation: lf-shift 14s ease infinite; box-shadow: 0 24px 60px rgba(122,31,43,.35); }
.lf-welcome .logo { width: 96px; height: 96px; margin: 0 auto 18px; border-radius: 28px; background: rgba(255,255,255,.18); border: 2px solid rgba(255,255,255,.4);
  display: grid; place-items: center; font-size: 52px; animation: lf-beat 1.6s ease-in-out infinite; backdrop-filter: blur(6px); }
.lf-welcome .hi { font-weight: 700; letter-spacing: .18em; text-transform: uppercase; font-size: .85rem; opacity: .9; }
.lf-welcome h1 { color: #fff; font-size: clamp(2.2rem, 6vw, 4rem); font-weight: 800; margin: 10px 0 12px; line-height: 1.05; }
.lf-welcome p { max-width: 640px; margin: 0 auto; font-size: 1.12rem; line-height: 1.6; color: rgba(255,255,255,.92); }
.lf-welcome .drop { position: absolute; font-size: 34px; opacity: .22; animation: lf-fall 9s linear infinite; }
.lf-welcome .pills { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-top: 26px; }
.lf-welcome .pills span { background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.3); padding: 7px 16px; border-radius: 99px; font-weight: 600; font-size: .9rem; }
@keyframes lf-shift { 0%,100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
@keyframes lf-beat { 0%,100% { transform: scale(1); } 15% { transform: scale(1.12); } 30% { transform: scale(1); } 45% { transform: scale(1.08); } }
@keyframes lf-fall { 0% { transform: translateY(-60px) rotate(0); } 100% { transform: translateY(520px) rotate(25deg); } }
.lf-sos-strip { display: flex; flex-wrap: wrap; gap: 14px; justify-content: center; align-items: center; margin: 18px 0; padding: 14px 18px; border-radius: 16px;
  background: rgba(179,32,47,.08); border: 1px dashed rgba(179,32,47,.4); font-weight: 600; }
.lf-sos-strip a { color: var(--lf-primary); text-decoration: none; }
.lf-feature { border: 1px solid var(--lf-border); border-radius: 18px; padding: 20px; height: 100%; background: #fff; transition: transform .2s, box-shadow .2s; }
.lf-feature:hover { transform: translateY(-4px); box-shadow: var(--lf-shadow); }
.lf-feature .ic { width: 48px; height: 48px; border-radius: 14px; display: grid; place-items: center; font-size: 22px; color: #fff; margin-bottom: 12px;
  background: linear-gradient(135deg, #B3202F, #F26B5B); }

/* ---------- footer ---------- */
.lf-footer { margin-top: 46px; border-radius: 22px; padding: 26px 20px 18px; text-align: center; color: rgba(255,255,255,.9);
  background: linear-gradient(135deg, #5E1420, #9E1C2C 60%, #C23A47); box-shadow: var(--lf-shadow); }
.lf-footer .by { font-size: .95rem; margin-bottom: 14px; }
.lf-footer .by b { color: #fff; font-size: 1.05rem; }
.lf-footer .links { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin: 4px 0 16px; }
.lf-footer .links a { display: inline-flex; align-items: center; gap: 8px; color: #fff !important; text-decoration: none !important; font-weight: 600; font-size: .88rem;
  background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.28); padding: 8px 16px; border-radius: 99px; transition: transform .15s, background .15s; }
.lf-footer .links a:hover { background: rgba(255,255,255,.28); transform: translateY(-2px); }
.lf-footer .links i { font-size: 1rem; }
.lf-footer .copy { font-size: .8rem; opacity: .8; border-top: 1px solid rgba(255,255,255,.2); padding-top: 12px; }

@media (max-width: 720px) {
  .lf-hero { padding: 34px 22px; border-radius: 18px; }
  .lf-hero::after { font-size: 120px; }
  .block-container { padding-left: 1rem; padding-right: 1rem; }
}
@media print { section[data-testid="stSidebar"], header, .stButton { display: none !important; } }
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def page_header(title: str, subtitle: str = "", icon: str = "") -> None:
    sub = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    st.markdown(f'<div class="lf-page-head"><h1>{esc(icon)} {esc(title)}</h1>{sub}</div>', unsafe_allow_html=True)


def hero(eyebrow: str, title: str, text: str) -> None:
    st.markdown(
        f'<div class="lf-hero"><span class="eyebrow">{esc(eyebrow)}</span><h1>{esc(title)}</h1><p>{esc(text)}</p></div>',
        unsafe_allow_html=True,
    )


def stat_cards(items) -> None:
    """items: list of (icon, number, label[, tone]) where tone is '', 'warn' or 'ok'."""
    cells = []
    for item in items:
        icon, number, label = item[0], item[1], item[2]
        tone = item[3] if len(item) > 3 else ""
        cells.append(f'<div class="lf-stat {tone}"><div class="icon">{esc(icon)}</div><div class="num">{esc(number)}</div><div class="lab">{esc(label)}</div></div>')
    st.markdown(f'<div class="lf-stats">{"".join(cells)}</div>', unsafe_allow_html=True)


def badge(text: str, kind: str = "neutral") -> str:
    return f'<span class="lf-badge {esc(kind)}">{esc(text)}</span>'


def blood_badge(blood_type: str) -> str:
    return badge(blood_type, "blood")


def status_badge(status: str) -> str:
    return badge((status or "").capitalize(), status if status in ("open", "fulfilled", "held", "flagged", "rejected") else "neutral")


def progress(done: int, total: int) -> str:
    pct = 0 if not total else max(0, min(100, round(done / total * 100)))
    return f'<div class="lf-progress"><span style="width:{pct}%"></span></div>'


def empty(message: str, icon: str = "🗂️") -> None:
    st.markdown(f'<div class="lf-empty"><div class="big">{esc(icon)}</div>{esc(message)}</div>', unsafe_allow_html=True)


def steps(items) -> None:
    cells = "".join(f'<div class="lf-step"><div class="n">{i}</div><b>{esc(t)}</b><span>{esc(d)}</span></div>' for i, (t, d) in enumerate(items, 1))
    st.markdown(f'<div class="lf-steps">{cells}</div>', unsafe_allow_html=True)


def timeline(events) -> None:
    """events: list of (message, 'date text')."""
    rows = "".join(f'<div class="lf-event">{esc(m)}<small>{esc(d)}</small></div>' for m, d in events)
    st.markdown(f'<div class="lf-timeline">{rows}</div>', unsafe_allow_html=True)


def bubble(text: str, who: str = "bot") -> None:
    st.markdown(f'<div class="lf-bubble {who}">{esc(text)}</div>', unsafe_allow_html=True)


def footer() -> None:
    links = [
        ("fa-brands fa-linkedin-in", "LinkedIn", "https://www.linkedin.com/in/tahir-mahmood-781b93329/"),
        ("fa-brands fa-github", "GitHub", "https://github.com/Tahir-MD"),
        ("fa-solid fa-bolt", "Streamlit", "https://share.streamlit.io/user/tahir-md"),
        ("fa-solid fa-envelope", "Email", "mailto:tahirdool67@gmail.com"),
        ("fa-brands fa-whatsapp", "WhatsApp", "https://wa.me/923054773174"),
    ]
    pills = "".join(f'<a href="{href}" target="_blank" rel="noopener"><i class="{icon}"></i>{label}</a>' for icon, label, href in links)
    st.markdown(
        f'<div class="lf-footer"><div class="by"><i class="fa-solid fa-heart-pulse"></i> Engineered by <b>Tahir Mahmood</b></div>'
        f'<div class="links">{pills}</div>'
        '<div class="copy">© 2026 LifeFlow Blood Network. All rights reserved. · v10.0</div></div>',
        unsafe_allow_html=True,
    )
