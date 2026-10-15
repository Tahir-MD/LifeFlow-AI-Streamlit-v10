"""Page registry so one page can send the visitor to another (st.switch_page needs the Page object)."""
import streamlit as st

PAGES = {}


def go(name: str) -> None:
    if name in PAGES:
        st.switch_page(PAGES[name])
