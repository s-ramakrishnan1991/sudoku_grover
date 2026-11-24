"""Oracle Lab: Grover's algorithm on a 3x3 Sudoku with the rule checked inside the circuit."""
import streamlit as st

st.set_page_config(page_title="Oracle Lab · in-circuit Grover", page_icon="🧪", layout="wide",
                   initial_sidebar_state="collapsed")

import state  # noqa: E402
import ui  # noqa: E402
from views import about, arena_page, hardware, lab, oracle  # noqa: E402

state.ensure()
ui.inject_css()

pages = [
    st.Page(lab.render, title="Lab", icon="🧪", url_path="lab", default=True),
    st.Page(oracle.render, title="Oracle anatomy", icon="🔬", url_path="oracle"),
    st.Page(arena_page.render, title="Noisy arena", icon="🏟️", url_path="arena"),
    st.Page(hardware.render, title="Hardware", icon="🛰️", url_path="hardware"),
    st.Page(about.render, title="About", icon="ℹ️", url_path="about"),
]
st.navigation(pages, position="top").run()
