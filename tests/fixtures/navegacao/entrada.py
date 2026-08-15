"""Script de entrada mínimo, no formato que o `app.py` vai adotar.

Não é cópia do `app.py`: é o esqueleto do modelo de execução que a
extração em páginas depende — barra lateral e guarda base ACIMA do
`pg.run()`, páginas abaixo. O que o teste ao lado afirma é o
comportamento do Streamlit, não o desta fixture.
"""

import streamlit as st

# O log vive em `session_state` porque ele sobrevive ao rerun dentro da
# mesma sessão do `AppTest` — é assim que se conta quantas vezes cada
# parte executou.
st.session_state.setdefault("log", [])
st.session_state["log"].append("entrada")

st.sidebar.text_input("Taxa", key="taxa_adq")

st.session_state.setdefault("parar", False)
if st.session_state["parar"]:
    st.session_state["log"].append("guarda-parou")
    st.error("motor caiu")
    st.stop()

pg = st.navigation(
    [
        st.Page("pagina_um.py", title="Um", default=True),
        st.Page("pagina_dois.py", title="Dois"),
    ]
)
pg.run()
