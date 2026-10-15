"""Excel / PDF downloads that reuse the export routes of the web app."""
import streamlit as st

from ui.db import friendly_error, session
from ui.i18n import t


def export_buttons(key: str, loader, label: str = "Download report") -> None:
    """loader(db, fmt) must return the Response of an export route. The file is built only when the person asks for it."""
    st.markdown(f"**{t(label)}**")
    c1, c2 = st.columns(2)
    for column, fmt, name in ((c1, "xlsx", "Excel"), (c2, "pdf", "PDF")):
        slot = f"{key}_{fmt}"
        with column:
            if st.button(f"📥 {name}", key=slot + "_make"):
                try:
                    with session() as db:
                        response = loader(db, fmt)
                    st.session_state[slot] = (bytes(response.body), response.headers.get("content-disposition", "").split("filename=")[-1] or f"report.{fmt}",
                                              response.media_type)
                except Exception as error:  # noqa: BLE001
                    st.error(friendly_error(error))
            ready = st.session_state.get(slot)
            if ready:
                st.download_button(f"⬇️ {name}", ready[0], file_name=ready[1], mime=ready[2], key=slot + "_dl")
