"""Primeira página da fixture de navegação."""

import streamlit as st

st.session_state["log"].append("pagina_um")
st.header("Um")
