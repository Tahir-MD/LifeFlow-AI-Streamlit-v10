"""English / Urdu / Sindhi. Uses the same translation table as the React app (ui/i18n_data.json). Missing text stays English."""
import json
import os

import streamlit as st

LANGS = {"en": "English", "ur": "اردو", "sd": "سنڌي"}
_PATH = os.path.join(os.path.dirname(__file__), "i18n_data.json")


@st.cache_resource(show_spinner=False)
def _table() -> dict:
    try:
        with open(_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:  # noqa: BLE001
        return {"ur": {}, "sd": {}}


def lang() -> str:
    code = st.session_state.get("lang", "en")
    return code if code in LANGS else "en"


def t(text: str, **values) -> str:
    """Translate an English sentence. {placeholders} are filled from values."""
    code = lang()
    out = _table().get(code, {}).get(text, text) if code != "en" else text
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def language_picker() -> None:
    st.radio("Language", list(LANGS), format_func=lambda c: LANGS[c], key="lang", horizontal=True, label_visibility="collapsed")


def rtl_css() -> None:
    if lang() in ("ur", "sd"):
        st.markdown(
            "<style>.main .block-container, section[data-testid='stSidebar'] .block-container {direction: rtl; text-align: right;}"
            ".lf-hero, .lf-stat, .lf-card, .lf-step {text-align: right;} input, textarea {direction: rtl;}</style>",
            unsafe_allow_html=True,
        )
