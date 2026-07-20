"""Dashboard da Carchuna — Streamlit, mesmo esqueleto de abas da Calahonda.

Abas: Vendas · Margem · Cenários · Diagnóstico Legal · Relatório.
Roda 100% offline com dados sintéticos; aceita upload de CSV/JSON/XLSX.

Uso::

    streamlit run app.py
"""

from __future__ import annotations

import io
from decimal import Decimal

import pandas as pd
import streamlit as st

from carchuna import (
    AnalisadorMargem,
    ConfigTributaria,
    ParametrosDiagnostico,
    TabelaCustos,
    carregar_transacoes,
    transacoes_sinteticas,
)
from carchuna.rag.llm import gerar_resposta, resposta_extrativa
from carchuna.rag.retrieval import AVISO_LEGAL

st.set_page_config(page_title="Carchuna — raio-X da margem", layout="wide")

st.title("Carchuna — o raio-X da margem")
st.caption(
    "Você fatura 400; a Carchuna mostra, com prova, por que sobra 8 — e o que "
    "a lei permite recuperar. Projeto de portfólio; não é aconselhamento "
    "jurídico/contábil."
)


def _brl(v: Decimal) -> str:
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


# ---------------------------------------------------------------------------
# Barra lateral: dados e configuração tributária
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Dados")
    upload = st.file_uploader(
        "Vendas (CSV, JSON ou XLSX)",
        type=["csv", "json", "xlsx"],
        help=(
            "Colunas: data, canal, valor_bruto, custo_produto, frete_pago "
            "(+ devolvida, prazo_recebimento_dias, comissao_cobrada opcionais)."
        ),
    )
    if upload is not None:
        try:
            transacoes = carregar_transacoes(upload, name=upload.name)
            st.success(f"{len(transacoes)} transações importadas.")
        except (ValueError, TypeError) as erro:
            st.error(f"Falha na importação: {erro}")
            st.stop()
    else:
        meses_demo = st.slider("Meses de dados sintéticos (demo)", 2, 12, 6)
        transacoes = transacoes_sinteticas(meses=meses_demo)
        st.info(
            "Usando dados sintéticos reprodutíveis — envie um arquivo "
            "para usar os seus."
        )

    st.header("Tributação")
    regime = st.selectbox("Regime", ["simples", "mei"], format_func=str.upper)
    if regime == "simples":
        anexo = st.selectbox("Anexo do Simples", ["I", "II", "III", "IV", "V"])
        rbt12 = st.number_input(
            "RBT12 — receita bruta 12 meses (R$)",
            min_value=1_000,
            max_value=4_800_000,
            value=4_200_000,
            step=10_000,
        )
        config = ConfigTributaria(
            regime="simples", anexo_simples=anexo, rbt12=Decimal(int(rbt12))
        )
    else:
        das = st.number_input("DAS-MEI mensal vigente (R$)", 1, 500, 76)
        config = ConfigTributaria(regime="mei", das_mei_mensal=Decimal(int(das)))

    st.header("Custos (editáveis)")
    taxa_adq = st.number_input("Taxa de adquirência (%)", 0.0, 10.0, 2.0, 0.1)
    taxa_ant = st.number_input("Antecipação (% ao mês)", 0.0, 10.0, 1.99, 0.01)
    tabela = TabelaCustos(
        taxa_adquirencia=Decimal(str(taxa_adq)) / 100,
        taxa_antecipacao_mensal=Decimal(str(taxa_ant)) / 100,
    )
    atividade = st.selectbox("Atividade", ["comercio", "industria", "servicos"])

# A fachada OO reúne os quatro motores; resultados caros ficam em cache.
analise = AnalisadorMargem(
    transacoes, config, tabela, ParametrosDiagnostico(atividade=atividade)
)
decomposicao = analise.decomposicao
serie = analise.serie

abas = st.tabs(
    [
        "Vendas",
        "Margem",
        "Cenários",
        "Crescimento",
        "Diagnóstico Legal",
        "Relatório",
    ]
)
(
    aba_vendas,
    aba_margem,
    aba_cenarios,
    aba_crescimento,
    aba_diagnostico,
    aba_relatorio,
) = abas

# ---------------------------------------------------------------------------
with aba_vendas:
    frame = pd.DataFrame(
        [
            {
                "data": t.data,
                "canal": t.canal,
                "valor_bruto": float(t.valor_bruto),
                "custo_produto": float(t.custo_produto),
                "frete_pago": float(t.frete_pago),
                "devolvida": t.devolvida,
                "prazo_dias": t.prazo_recebimento_dias,
            }
            for t in transacoes
        ]
    )
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Transações", len(frame))
    col2.metric("Receita bruta", _brl(decomposicao.receita_bruta))
    col3.metric("Canais", frame["canal"].nunique())
    col4.metric("Devoluções", int(frame["devolvida"].sum()))
    st.subheader("Receita por canal")
    st.bar_chart(frame.groupby("canal")["valor_bruto"].sum())
    st.subheader("Transações")
    if st.toggle(
        "Mostrar margem real por venda (decomposta pelo mesmo motor)",
        value=len(frame) <= 500,
    ):
        por_venda = analise.margem_por_venda()
        frame["margem_liquida"] = [float(v.margem_liquida) for v in por_venda]
        frame["margem_%"] = [float(v.margem_pct) for v in por_venda]
    st.dataframe(frame, use_container_width=True, height=320)

# ---------------------------------------------------------------------------
with aba_margem:
    resumo = analise.resumo_executivo()
    st.info(resumo.frase())
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Margem anunciada (receita − CMV)",
        _brl(resumo.margem_anunciada),
        f"{resumo.margem_anunciada_pct}%",
    )
    col2.metric(
        "Margem real",
        _brl(resumo.margem_real),
        f"{resumo.margem_real_pct}%",
    )
    col3.metric("Perda de margem no período", _brl(resumo.perda_total))

    col1, col2, col3 = st.columns(3)
    col1.metric("Margem líquida", _brl(decomposicao.margem_liquida))
    col2.metric("Margem %", f"{decomposicao.margem_pct}%")
    if decomposicao.aliquota_efetiva is not None:
        col3.metric(
            "Alíquota efetiva do Simples",
            f"{(decomposicao.aliquota_efetiva * 100).quantize(Decimal('0.0001'))}%",
        )

    st.subheader("Decomposição — onde a receita morre")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "dedução": d.nome,
                    "valor": _brl(d.valor),
                    "% da receita": f"{d.pct_receita}%",
                    "confiança": d.confianca,
                    "fonte": d.fonte,
                }
                for d in decomposicao.deducoes
            ]
        ),
        use_container_width=True,
    )

    if len(serie) >= 2:
        col_a, col_b = st.columns(2)
        col_a.metric("Maior queda de margem", f"{analise.maior_queda()} p.p.")
        col_b.metric("Instabilidade da margem", f"{analise.instabilidade()} p.p.")
    st.subheader("Margem % mês a mês")
    st.line_chart(
        pd.Series({mes: float(m) for mes, m in serie}, name="margem %"),
    )
    st.subheader("Lucro acumulado")
    st.area_chart(
        pd.Series(
            {mes: float(v) for mes, v in analise.lucro_acumulado()},
            name="lucro acumulado (R$)",
        )
    )

# ---------------------------------------------------------------------------
with aba_cenarios:
    st.caption(
        "Cada cenário reexecuta o mesmo motor de cálculo com o parâmetro "
        "chocado — sem fórmula paralela."
    )
    for resultado in analise.cenarios():
        with st.container(border=True):
            st.markdown(f"**{resultado.nome}**")
            c1, c2, c3 = st.columns(3)
            c1.metric("Margem no cenário", _brl(resultado.cenario.margem_liquida))
            c2.metric("Impacto (R$)", _brl(resultado.impacto_reais))
            c3.metric("Impacto (p.p.)", f"{resultado.impacto_pp:+.2f}")

# ---------------------------------------------------------------------------
with aba_crescimento:
    from carchuna import CenarioCrescimentoCanal
    from carchuna.crescimento import AVISO_CRESCIMENTO

    st.caption(
        "Como faturar mais — com números dos seus próprios dados, não com "
        "promessa: onde cada real vendido rende mais, o preço certo por canal "
        "e quanto cabe crescer dentro do Simples."
    )
    for oportunidade in analise.crescimento():
        with st.container(border=True):
            ganho = _brl(oportunidade.ganho_estimado_mensal)
            st.markdown(
                f"**{oportunidade.titulo}** — ~{ganho}/mês "
                f"[{oportunidade.confianca} · {oportunidade.tipo}]"
            )
            st.write(oportunidade.explicacao)
            for disp in oportunidade.base_legal:
                st.markdown(
                    f"- **{disp.lei}, {disp.artigo}** — {disp.resumo} "
                    f"[[fonte oficial]({disp.fonte})]"
                )
            st.markdown(f"**Caminho prático:** {oportunidade.caminho_pratico}")

    st.subheader("Simule vender mais em um canal")
    col_c1, col_c2 = st.columns(2)
    canal_cresc = col_c1.selectbox(
        "Canal", sorted({t.canal for t in transacoes}), key="canal_cresc"
    )
    pct_cresc = col_c2.slider("Crescimento das vendas (%)", 5, 100, 20, 5)
    try:
        simulacao = analise.simular(
            CenarioCrescimentoCanal(canal_cresc, Decimal(pct_cresc) / 100)
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Margem hoje", _brl(simulacao.base.margem_liquida))
        c2.metric("Margem no cenário", _brl(simulacao.cenario.margem_liquida))
        c3.metric("Ganho (R$)", _brl(simulacao.impacto_reais))
    except ValueError as erro:
        st.warning(str(erro))

    st.subheader("Calculadora de preço (motor de margem invertido)")
    col_p1, col_p2, col_p3, col_p4 = st.columns(4)
    calc_custo = col_p1.number_input("Custo do produto (R$)", 0.01, 100000.0, 40.0)
    calc_frete = col_p2.number_input("Frete (R$)", 0.0, 10000.0, 10.0)
    calc_canal = col_p3.selectbox(
        "Canal de venda",
        ["mercado_livre", "shopee", "amazon", "loja_propria", "fisico"],
        key="calc_canal",
    )
    calc_margem = col_p4.number_input("Margem alvo (%)", 0.0, 60.0, 10.0, 1.0)
    try:
        equilibrio = analise.preco_sugerido(
            Decimal(str(calc_custo)),
            Decimal(str(calc_frete)),
            calc_canal,
            Decimal("0"),
        )
        alvo = analise.preco_sugerido(
            Decimal(str(calc_custo)),
            Decimal(str(calc_frete)),
            calc_canal,
            Decimal(str(calc_margem)) / 100,
        )
        col_r1, col_r2 = st.columns(2)
        col_r1.metric("Preço de equilíbrio (margem zero)", _brl(equilibrio))
        col_r2.metric(f"Preço para {calc_margem:.0f}% de margem", _brl(alvo))
    except ValueError as erro:
        st.error(str(erro))
    st.caption(AVISO_CRESCIMENTO)

# ---------------------------------------------------------------------------
with aba_diagnostico:
    retriever = analise.retriever
    st.warning(retriever.aviso_corpus)

    st.subheader("Vazamentos detectados (heurísticas transparentes)")
    achados = analise.diagnosticar()
    if not achados:
        st.success("Nenhum vazamento detectado pelas 4 regras da v1.")
    for achado in achados:
        with st.expander(
            f"{achado.titulo} — ~{_brl(achado.impacto_mensal)}/mês "
            f"[{achado.confianca}]"
        ):
            st.write(achado.explicacao)
            st.markdown("**Base legal (recuperada do corpus):**")
            for disp in achado.base_legal:
                pendente = "" if disp.revisado else " · _revisão humana pendente_"
                st.markdown(
                    f"- **{disp.lei}, {disp.artigo}**{pendente} — {disp.resumo} "
                    f"[[fonte oficial]({disp.fonte})]"
                )
            st.markdown(f"**Caminho prático:** {achado.caminho_pratico}")
            st.caption(achado.aviso)

    st.subheader("Pergunte na sua língua")
    pergunta = st.text_input(
        "Ex.: 'a taxa da maquininha tá alta demais, posso trocar?'"
    )
    if pergunta:
        dispositivos = retriever.buscar(pergunta)
        resposta = gerar_resposta(pergunta, dispositivos)
        if resposta is None:
            resposta = resposta_extrativa(pergunta, dispositivos)
            st.caption(
                "Modo extrativo (sem chave de API) — configure ANTHROPIC_API_KEY "
                "para respostas em linguagem natural."
            )
        st.write(resposta)

# ---------------------------------------------------------------------------
with aba_relatorio:
    st.caption(
        "PDF de 3 páginas: raio-X da margem, cenários e achados legais. "
        "Números 100% calculados por código testado."
    )
    if st.button("Gerar relatório PDF"):
        buffer = io.BytesIO()
        analise.gerar_pdf(buffer)
        st.download_button(
            "Baixar relatorio_carchuna.pdf",
            data=buffer.getvalue(),
            file_name="relatorio_carchuna.pdf",
            mime="application/pdf",
        )
    st.caption(AVISO_LEGAL)
