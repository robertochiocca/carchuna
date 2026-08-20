"""As três funções cacheadas do dashboard.

Extraído do `app.py` sem alteração de comportamento. Estão juntas de
propósito: `@st.cache_data` grudado na função errada já causou defeito
neste projeto, e o `ROADMAP.md` registra isso como motivo para não mexer
no `app.py` sem cuidado. Num arquivo só, o que é cacheado fica à vista.

Nenhuma delas desenha widget — é o que o
`test_nenhuma_funcao_que_desenha_widget_esta_cacheada` afirma, e a
separação por arquivo torna a regra visível além de testada.
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from carchuna import AnalisadorMargem, ParametrosDiagnostico
from carchuna.confianca import avaliar_confianca
from carchuna.margem import conferir_plausibilidade, reconciliar
from carchuna.rag.retrieval import Retriever


@st.cache_resource(show_spinner=False)
def _retriever_cacheado() -> Retriever:
    return Retriever()


# Cada motor da bandeja, com o nome da chave e como chamá-lo. A tabela
# existe para o `try/except` ficar num lugar só: motor novo entra aqui e
# já nasce contido, em vez de depender de alguém lembrar de embrulhá-lo.
_MOTORES: tuple[tuple[str, Callable], ...] = (
    ("decomposicao", lambda a: a.decomposicao),
    ("rbt12_mensal", lambda a: a.rbt12_mensal),
    ("resumo", lambda a: a.resumo_executivo()),
    ("mensal", lambda a: a.mensal),
    ("lucro", lambda a: a.lucro_acumulado()),
    ("por_venda", lambda a: a.margem_por_venda()),
    ("por_produto", lambda a: a.margem_por_produto()),
    ("cenarios", lambda a: a.cenarios()),
    ("achados", lambda a: a.diagnosticar()),
    ("oportunidades", lambda a: a.crescimento()),
    ("radar", lambda a: a.radar()),
    ("linhagem", lambda a: a.linhagem()),
    ("confianca", lambda a: avaliar_confianca(a.transacoes, base="calculado")),
    ("plausibilidade", lambda a: conferir_plausibilidade(a.decomposicao)),
    # A conferência que de fato valida o número: refaz o lucro lançamento
    # a lançamento, sem passar por `decompor_margem`. Ela existia desde o
    # começo e só era chamada nos testes — a tela publicava a margem sem
    # nunca perguntar se os dois caminhos fechavam.
    (
        "reconciliacao",
        lambda a: reconciliar(a.transacoes, a.config, a.decomposicao, a.tabela),
    ),
)


@st.cache_data(show_spinner=False)
def _resultados_cacheados(
    transacoes: tuple,
    config,
    tabela,
    atividade: str,
    rbt12_movel: bool = False,
    origem: str | None = None,
    confirmar_lacunas: bool = False,
) -> dict:
    """Roda os motores uma vez por (dados, config) — não por clique.

    Com bases reais (dezenas de milhares de vendas), decompor venda a
    venda a cada interação de widget ficaria lento; o cache devolve o
    conjunto pronto enquanto nada mudar.

    **Cada motor é contido no seu próprio erro.** Antes eles rodavam numa
    expressão só: o primeiro `ValueError` levava junto os outros catorze,
    e o lojista via um traceback no lugar do dashboard inteiro por causa
    de um cenário que não cabia nos dados dele. Agora a chave que falha
    recebe ``None`` e o motivo vai para ``falhas``, que a tela publica na
    aba correspondente.

    ``ValueError`` e ``TypeError`` são as duas que o motor levanta de
    propósito quando o dado não serve — teto do MEI estourado, canal sem
    venda, dinheiro em ``float``. Nada além delas é capturado aqui: erro
    que eu não previ tem de aparecer, não virar um bloco vazio com
    mensagem gentil.
    """
    analise = AnalisadorMargem(
        list(transacoes),
        config,
        tabela,
        ParametrosDiagnostico(atividade=atividade),
        retriever=_retriever_cacheado(),
        rbt12_movel=rbt12_movel,
        confirmar_lacunas=confirmar_lacunas,
        origem=origem,
    )
    bandeja: dict = {}
    falhas: dict[str, str] = {}
    for chave, motor in _MOTORES:
        try:
            bandeja[chave] = motor(analise)
        except (ValueError, TypeError) as erro:
            bandeja[chave] = None
            falhas[chave] = str(erro)
    bandeja["falhas"] = falhas
    return bandeja


@st.cache_data(show_spinner=False)
def _composicao_cacheada(transacoes: tuple, config, tabela, nome: str) -> dict:
    """Drill-down de uma dedução (por canal e por mês), cacheado por clique."""
    return AnalisadorMargem(list(transacoes), config, tabela).composicao_deducao(nome)
