"""Puts a small icon in front of form-field labels, tab names and common buttons ("👤 Full name", "📧 Email", "🔒 Password").

It wraps the Streamlit widget functions once, so every page gets icons without each label being edited. Labels that already
start with an emoji are left alone. Translated labels (Urdu / Sindhi) are matched through their English original."""
import re

import streamlit as st

FIELD_RULES = [
    (r"confirm.*password|new password|current password", "🔐"), (r"password", "🔒"), (r"e-?mail", "📧"), (r"whatsapp", "💬"),
    (r"phone|mobile|contact|number", "📞"), (r"hospital name|hospital", "🏥"), (r"patient", "🧑‍⚕️"), (r"doctor", "🩺"),
    (r"full name|first name|name|donor", "👤"), (r"blood|bags?|units?", "🩸"), (r"hemoglobin", "🧪"), (r"weight", "⚖️"), (r"\bage\b", "🎂"),
    (r"cnic|national id", "🪪"), (r"licen[cs]e", "📄"), (r"village", "🏡"), (r"\barea\b", "📍"), (r"\bcity\b", "🏙️"), (r"\bstate\b", "🗺️"),
    (r"country", "🌍"), (r"latitude|longitude", "🧭"), (r"address|house|street|location|place", "🏠"), (r"date|collected|expires", "📅"),
    (r"\btime\b|hours", "⏰"), (r"shift", "🕒"), (r"\brole\b", "🛡️"), (r"message", "💬"), (r"note|comment|description|reason", "📝"),
    (r"code", "🔢"), (r"search", "🔍"), (r"distance|\bkm\b", "📏"), (r"stars|rating", "⭐"), (r"invite|referral", "🎁"),
    (r"language", "🌐"), (r"urgen", "⚡"), (r"title", "🏷️"), (r"camp", "⛺"), (r"\btype\b|category", "🗂️"), (r"\bwho\b", "🙋"),
]
TAB_RULES = [
    (r"^donors?$", "🩸"), (r"^patients?( / family)?$", "🧑‍⚕️"), (r"hospital staff|^staff$", "🧑‍💼"), (r"^hospitals?$", "🏥"), (r"^admin$", "🛡️"),
    (r"certificates", "🏅"), (r"donor card", "🪪"), (r"weekly report", "📈"), (r"shortage", "📉"), (r"ambulance", "🚑"), (r"^requests?$", "🩸"),
    (r"donations", "💉"), (r"ask for blood", "🩸"), (r"my transfers|transfers", "🔁"), (r"scan qr", "📷"), (r"type donor", "⌨️"),
    (r"audit", "🔎"), (r"emergency numbers", "☎️"), (r"clearance", "✅"), (r"sms", "💬"), (r"profile", "👤"), (r"stock|inventory", "📦"),
]
BUTTON_RULES = [
    (r"^log in$", "🔐"), (r"^log out$", "🚪"), (r"^create account$", "✨"), (r"^save", "💾"), (r"^send", "📤"), (r"^download", "📥"),
    (r"^add\b", "➕"), (r"^approve", "✅"), (r"^reject|^not eligible", "⛔"), (r"^remove|^discard|^delete", "🗑️"), (r"^cancel", "✖️"),
    (r"^check", "🔎"), (r"^register", "📝"), (r"^accept", "🩸"), (r"^publish", "📢"), (r"^start again", "🔄"), (r"^change", "🔑"),
    (r"^turn on|^set up", "🛡️"), (r"^mark all", "👁️"), (r"^clear", "✅"),
]


def _english(label: str) -> str:
    try:
        from ui import i18n
        code = i18n.lang()
        if code != "en":
            reverse = st.session_state.get("_lf_reverse")
            if not reverse or reverse[0] != code:
                reverse = (code, {v: k for k, v in i18n._table().get(code, {}).items()})
                st.session_state["_lf_reverse"] = reverse
            return reverse[1].get(label, label)
    except Exception:  # noqa: BLE001
        pass
    return label


def _has_symbol(label: str) -> bool:
    return bool(label) and ord(label.lstrip()[:1] or "a") > 0x2000


def decorate(label, rules):
    if not isinstance(label, str) or not label.strip() or _has_symbol(label):
        return label
    english = _english(label).lower()
    for pattern, icon in rules:
        if re.search(pattern, english):
            return f"{icon} {label}"
    return label


def _wrap_label(original, rules):
    def wrapper(*args, **kwargs):
        if args:
            args = (decorate(args[0], rules),) + args[1:]
        elif "label" in kwargs:
            kwargs["label"] = decorate(kwargs["label"], rules)
        return original(*args, **kwargs)
    wrapper._lf_wrapped = True
    return wrapper


def _wrap_method(original, rules):
    def wrapper(self, *args, **kwargs):
        if args:
            args = (decorate(args[0], rules),) + args[1:]
        elif "label" in kwargs:
            kwargs["label"] = decorate(kwargs["label"], rules)
        return original(self, *args, **kwargs)
    wrapper._lf_wrapped = True
    return wrapper


def _wrap_tabs(original, is_method):
    def decorate_all(tabs):
        return [decorate(x, TAB_RULES) for x in tabs]

    if is_method:
        def wrapper(self, tabs, *args, **kwargs):
            return original(self, decorate_all(tabs), *args, **kwargs)
    else:
        def wrapper(tabs, *args, **kwargs):
            return original(decorate_all(tabs), *args, **kwargs)
    wrapper._lf_wrapped = True
    return wrapper


def install() -> None:
    """Safe to call on every run: each function is wrapped only once."""
    try:
        from streamlit.delta_generator import DeltaGenerator
    except Exception:  # noqa: BLE001
        return
    fields = ["text_input", "text_area", "number_input", "selectbox", "multiselect", "date_input", "time_input", "select_slider", "slider"]
    buttons = ["button", "form_submit_button", "download_button"]
    for names, rules in ((fields, FIELD_RULES), (buttons, BUTTON_RULES)):
        for name in names:
            original = getattr(st, name, None)
            if original is not None and not getattr(original, "_lf_wrapped", False):
                setattr(st, name, _wrap_label(original, rules))
            method = getattr(DeltaGenerator, name, None)
            if method is not None and not getattr(method, "_lf_wrapped", False):
                setattr(DeltaGenerator, name, _wrap_method(method, rules))
    if not getattr(st.tabs, "_lf_wrapped", False):
        st.tabs = _wrap_tabs(st.tabs, False)
    if not getattr(DeltaGenerator.tabs, "_lf_wrapped", False):
        DeltaGenerator.tabs = _wrap_tabs(DeltaGenerator.tabs, True)
