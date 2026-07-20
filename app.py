"""Dashboard da Carchuna — Streamlit, mesmo esqueleto de abas da Calahonda.

Abas: Vendas · Margem · Cenários · Crescimento · Diagnóstico Legal ·
Relatório. Interface bilíngue (PT/EN); roda 100% offline com dados
sintéticos e aceita upload de CSV/JSON/XLSX.

As narrativas geradas pelos motores (achados, oportunidades, nomes de
cenário) são em português — a língua do público-alvo; a interface é que
alterna. Isso está sinalizado no modo EN.

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
    CenarioCrescimentoCanal,
    ConfigTributaria,
    ParametrosDiagnostico,
    TabelaCustos,
    carregar_transacoes,
    transacoes_sinteticas,
)
from carchuna.crescimento import AVISO_CRESCIMENTO
from carchuna.rag.llm import gerar_resposta, resposta_extrativa
from carchuna.rag.retrieval import AVISO_LEGAL

st.set_page_config(page_title="Carchuna", layout="wide")

# ---------------------------------------------------------------------------
# Textos da interface (PT/EN). Saídas dos motores permanecem em PT.
# ---------------------------------------------------------------------------

T = {
    "pt": {
        "titulo": "Carchuna — o raio-X da margem",
        "subtitulo": (
            "Você fatura 400; a Carchuna mostra, com prova, por que sobra 8 — "
            "e o que a lei permite recuperar. Projeto de portfólio; não é "
            "aconselhamento jurídico/contábil."
        ),
        "dados": "Dados",
        "upload": "Vendas (CSV, JSON ou XLSX)",
        "upload_ajuda": (
            "Colunas: data, canal, valor_bruto, custo_produto, frete_pago "
            "(+ devolvida, prazo_recebimento_dias, comissao_cobrada opcionais)."
        ),
        "importadas": "transações importadas.",
        "falha_importacao": "Falha na importação:",
        "meses_demo": "Meses de dados sintéticos (demo)",
        "aviso_demo": (
            "Usando dados sintéticos reprodutíveis — envie um arquivo para "
            "usar os seus."
        ),
        "tributacao": "Tributação",
        "regime": "Regime",
        "anexo": "Anexo do Simples",
        "rbt12": "RBT12 — receita bruta 12 meses (R$)",
        "das": "DAS-MEI mensal vigente (R$)",
        "custos": "Custos (editáveis)",
        "taxa_adq": "Taxa de adquirência (%)",
        "taxa_ant": "Antecipação (% ao mês)",
        "atividade": "Atividade",
        "abas": [
            "Vendas",
            "Margem",
            "Cenários",
            "Crescimento",
            "Diagnóstico Legal",
            "Relatório",
        ],
        "transacoes": "Transações",
        "receita_bruta": "Receita bruta",
        "canais": "Canais",
        "devolucoes": "Devoluções",
        "receita_por_canal": "Receita por canal",
        "margem_por_venda": (
            "Mostrar margem real por venda (decomposta pelo mesmo motor)"
        ),
        "margem_anunciada": "Margem anunciada (receita − CMV)",
        "margem_real": "Margem real",
        "perda_periodo": "Perda de margem no período",
        "margem_liquida": "Margem líquida",
        "margem_pct": "Margem %",
        "aliquota_efetiva": "Alíquota efetiva do Simples",
        "decomposicao": "Decomposição — onde a receita morre",
        "maior_queda": "Maior queda de margem",
        "instabilidade": "Instabilidade da margem",
        "margem_mensal": "Margem % mês a mês",
        "lucro_acumulado": "Lucro acumulado",
        "cenarios_caption": (
            "Cada cenário reexecuta o mesmo motor de cálculo com o parâmetro "
            "chocado — sem fórmula paralela."
        ),
        "margem_cenario": "Margem no cenário",
        "impacto_reais": "Impacto (R$)",
        "impacto_pp": "Impacto (p.p.)",
        "crescimento_caption": (
            "Como faturar mais — com números dos seus próprios dados, não com "
            "promessa: onde cada real vendido rende mais, o preço certo por "
            "canal e quanto cabe crescer dentro do Simples."
        ),
        "caminho": "Caminho prático:",
        "simular_canal": "Simule vender mais em um canal",
        "canal": "Canal",
        "crescimento_vendas": "Crescimento das vendas (%)",
        "margem_hoje": "Margem hoje",
        "ganho": "Ganho (R$)",
        "calculadora": "Calculadora de preço (motor de margem invertido)",
        "custo_produto": "Custo do produto (R$)",
        "frete": "Frete (R$)",
        "canal_venda": "Canal de venda",
        "margem_alvo": "Margem alvo (%)",
        "preco_equilibrio": "Preço de equilíbrio (margem zero)",
        "preco_para": "Preço para {pct}% de margem",
        "vazamentos": "Vazamentos detectados (heurísticas transparentes)",
        "sem_achados": "Nenhum vazamento detectado pelas 4 regras da v1.",
        "base_legal": "Base legal (recuperada do corpus):",
        "pendente": " · _revisão humana pendente_",
        "fonte_oficial": "fonte oficial",
        "pergunte": "Pergunte na sua língua",
        "pergunta_exemplo": "Ex.: 'a taxa da maquininha tá alta demais, posso trocar?'",
        "modo_extrativo": (
            "Modo extrativo (sem chave de API) — configure ANTHROPIC_API_KEY "
            "para respostas em linguagem natural."
        ),
        "relatorio_caption": (
            "PDF de 3 páginas: raio-X da margem, cenários e achados legais. "
            "Números 100% calculados por código testado."
        ),
        "gerar_pdf": "Gerar relatório PDF",
        "baixar_pdf": "Baixar relatorio_carchuna.pdf",
        "nota_motor": "",
    },
    "en": {
        "titulo": "Carchuna — the margin X-ray",
        "subtitulo": (
            "You bill 400; Carchuna shows, with proof, why only 8 is left — "
            "and what the law allows you to recover. Portfolio project; not "
            "legal or accounting advice."
        ),
        "dados": "Data",
        "upload": "Sales (CSV, JSON or XLSX)",
        "upload_ajuda": (
            "Columns: data, canal, valor_bruto, custo_produto, frete_pago "
            "(+ optional devolvida, prazo_recebimento_dias, comissao_cobrada)."
        ),
        "importadas": "transactions imported.",
        "falha_importacao": "Import failed:",
        "meses_demo": "Months of synthetic data (demo)",
        "aviso_demo": (
            "Using reproducible synthetic data — upload a file to use your own."
        ),
        "tributacao": "Taxation",
        "regime": "Tax regime",
        "anexo": "Simples Nacional annex",
        "rbt12": "RBT12 — gross revenue, last 12 months (R$)",
        "das": "Current monthly MEI flat tax (R$)",
        "custos": "Costs (editable)",
        "taxa_adq": "Card acquiring fee (%)",
        "taxa_ant": "Receivables prepayment (%/month)",
        "atividade": "Activity",
        "abas": [
            "Sales",
            "Margin",
            "Scenarios",
            "Growth",
            "Legal Diagnosis",
            "Report",
        ],
        "transacoes": "Transactions",
        "receita_bruta": "Gross revenue",
        "canais": "Channels",
        "devolucoes": "Returns",
        "receita_por_canal": "Revenue by channel",
        "margem_por_venda": "Show real margin per sale (decomposed by the same engine)",
        "margem_anunciada": "Naive margin (revenue − COGS)",
        "margem_real": "Real margin",
        "perda_periodo": "Margin lost in the period",
        "margem_liquida": "Net margin",
        "margem_pct": "Margin %",
        "aliquota_efetiva": "Simples effective tax rate",
        "decomposicao": "Decomposition — where revenue dies",
        "maior_queda": "Largest margin drop",
        "instabilidade": "Margin instability",
        "margem_mensal": "Margin % by month",
        "lucro_acumulado": "Cumulative profit",
        "cenarios_caption": (
            "Each scenario re-runs the same calculation engine with the "
            "shocked parameter — no parallel formula."
        ),
        "margem_cenario": "Margin in scenario",
        "impacto_reais": "Impact (R$)",
        "impacto_pp": "Impact (p.p.)",
        "crescimento_caption": (
            "How to bill more — with numbers from your own data, not "
            "promises: where each real earns the most, the right price per "
            "channel and how much room you have inside Simples."
        ),
        "caminho": "Practical next step:",
        "simular_canal": "Simulate selling more in a channel",
        "canal": "Channel",
        "crescimento_vendas": "Sales growth (%)",
        "margem_hoje": "Margin today",
        "ganho": "Gain (R$)",
        "calculadora": "Price calculator (inverted margin engine)",
        "custo_produto": "Product cost (R$)",
        "frete": "Shipping (R$)",
        "canal_venda": "Sales channel",
        "margem_alvo": "Target margin (%)",
        "preco_equilibrio": "Break-even price (zero margin)",
        "preco_para": "Price for a {pct}% margin",
        "vazamentos": "Detected leaks (transparent heuristics)",
        "sem_achados": "No leaks detected by the v1 rules.",
        "base_legal": "Legal basis (retrieved from the corpus):",
        "pendente": " · _human review pending_",
        "fonte_oficial": "official source",
        "pergunte": "Ask in your own words",
        "pergunta_exemplo": "E.g.: 'my card machine fee looks too high, can I switch?'",
        "modo_extrativo": (
            "Extractive mode (no API key) — set ANTHROPIC_API_KEY for "
            "natural-language answers."
        ),
        "relatorio_caption": (
            "3-page PDF: margin X-ray, scenarios and legal findings. Every "
            "number computed by tested code."
        ),
        "gerar_pdf": "Generate PDF report",
        "baixar_pdf": "Download relatorio_carchuna.pdf",
        "nota_motor": (
            "Engine narratives (findings, opportunities, scenario names) are "
            "in Portuguese — the audience's language; the interface is "
            "bilingual."
        ),
    },
}

ROTULO_FONTE_EN = {
    "tributos": "Taxes (Simples/MEI)",
    "comissoes_canal": "Channel commissions",
    "adquirencia": "Card acquiring",
    "antecipacao": "Receivables prepayment",
    "frete": "Shipping",
    "devolucoes": "Returns",
    "cmv": "COGS (product cost)",
}

with st.sidebar:
    idioma = st.radio("Idioma / Language", ["PT", "EN"], horizontal=True, key="idioma")
lang = "pt" if idioma == "PT" else "en"
t = T[lang]


def _brl(v: Decimal) -> str:
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


st.title(t["titulo"])
st.caption(t["subtitulo"])
if t["nota_motor"]:
    st.caption(t["nota_motor"])

# ---------------------------------------------------------------------------
# Barra lateral: dados e configuração tributária
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header(t["dados"])
    upload = st.file_uploader(
        t["upload"], type=["csv", "json", "xlsx"], help=t["upload_ajuda"]
    )
    if upload is not None:
        try:
            transacoes = carregar_transacoes(upload, name=upload.name)
            st.success(f"{len(transacoes)} {t['importadas']}")
        except (ValueError, TypeError) as erro:
            st.error(f"{t['falha_importacao']} {erro}")
            st.stop()
    else:
        meses_demo = st.slider(t["meses_demo"], 2, 12, 6)
        transacoes = transacoes_sinteticas(meses=meses_demo)
        st.info(t["aviso_demo"])

    st.header(t["tributacao"])
    regime = st.selectbox(t["regime"], ["simples", "mei"], format_func=str.upper)
    if regime == "simples":
        anexo = st.selectbox(t["anexo"], ["I", "II", "III", "IV", "V"])
        rbt12 = st.number_input(
            t["rbt12"],
            min_value=1_000,
            max_value=4_800_000,
            value=4_200_000,
            step=10_000,
        )
        config = ConfigTributaria(
            regime="simples", anexo_simples=anexo, rbt12=Decimal(int(rbt12))
        )
    else:
        das = st.number_input(t["das"], 1, 500, 76)
        config = ConfigTributaria(regime="mei", das_mei_mensal=Decimal(int(das)))

    st.header(t["custos"])
    taxa_adq = st.number_input(t["taxa_adq"], 0.0, 10.0, 2.0, 0.1)
    taxa_ant = st.number_input(t["taxa_ant"], 0.0, 10.0, 1.99, 0.01)
    tabela = TabelaCustos(
        taxa_adquirencia=Decimal(str(taxa_adq)) / 100,
        taxa_antecipacao_mensal=Decimal(str(taxa_ant)) / 100,
    )
    atividade = st.selectbox(t["atividade"], ["comercio", "industria", "servicos"])

# A fachada OO reúne os quatro motores; resultados caros ficam em cache.
analise = AnalisadorMargem(
    transacoes, config, tabela, ParametrosDiagnostico(atividade=atividade)
)
decomposicao = analise.decomposicao
serie = analise.serie

(
    aba_vendas,
    aba_margem,
    aba_cenarios,
    aba_crescimento,
    aba_diagnostico,
    aba_relatorio,
) = st.tabs(t["abas"])

# ---------------------------------------------------------------------------
with aba_vendas:
    frame = pd.DataFrame(
        [
            {
                "data": tr.data,
                "canal": tr.canal,
                "valor_bruto": float(tr.valor_bruto),
                "custo_produto": float(tr.custo_produto),
                "frete_pago": float(tr.frete_pago),
                "devolvida": tr.devolvida,
                "prazo_dias": tr.prazo_recebimento_dias,
            }
            for tr in transacoes
        ]
    )
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(t["transacoes"], len(frame))
    col2.metric(t["receita_bruta"], _brl(decomposicao.receita_bruta))
    col3.metric(t["canais"], frame["canal"].nunique())
    col4.metric(t["devolucoes"], int(frame["devolvida"].sum()))
    st.subheader(t["receita_por_canal"])
    st.bar_chart(frame.groupby("canal")["valor_bruto"].sum())
    st.subheader(t["transacoes"])
    if st.toggle(t["margem_por_venda"], value=len(frame) <= 500):
        por_venda = analise.margem_por_venda()
        frame["margem_liquida"] = [float(v.margem_liquida) for v in por_venda]
        frame["margem_%"] = [float(v.margem_pct) for v in por_venda]
    st.dataframe(frame, use_container_width=True, height=320)

# ---------------------------------------------------------------------------
with aba_margem:
    resumo = analise.resumo_executivo()
    if lang == "pt":
        st.info(resumo.frase())
    else:
        maior = resumo.maior_fonte
        st.info(
            f"Over {resumo.meses} month(s), {_brl(resumo.perda_total)} of "
            f"margin was lost between the naive margin "
            f"({resumo.margem_anunciada_pct}%) and the real one "
            f"({resumo.margem_real_pct}%); "
            f"{maior.pct_da_perda.quantize(Decimal('1'))}% of that loss came "
            f"from {ROTULO_FONTE_EN.get(maior.nome, maior.rotulo)}."
        )
    col1, col2, col3 = st.columns(3)
    col1.metric(
        t["margem_anunciada"],
        _brl(resumo.margem_anunciada),
        f"{resumo.margem_anunciada_pct}%",
    )
    col2.metric(
        t["margem_real"], _brl(resumo.margem_real), f"{resumo.margem_real_pct}%"
    )
    col3.metric(t["perda_periodo"], _brl(resumo.perda_total))

    col1, col2, col3 = st.columns(3)
    col1.metric(t["margem_liquida"], _brl(decomposicao.margem_liquida))
    col2.metric(t["margem_pct"], f"{decomposicao.margem_pct}%")
    if decomposicao.aliquota_efetiva is not None:
        col3.metric(
            t["aliquota_efetiva"],
            f"{(decomposicao.aliquota_efetiva * 100).quantize(Decimal('0.0001'))}%",
        )

    st.subheader(t["decomposicao"])
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "deducao": d.nome,
                    "valor": _brl(d.valor),
                    "%": f"{d.pct_receita}%",
                    "confianca": d.confianca,
                    "fonte": d.fonte,
                }
                for d in decomposicao.deducoes
            ]
        ),
        use_container_width=True,
    )

    if len(serie) >= 2:
        col_a, col_b = st.columns(2)
        col_a.metric(t["maior_queda"], f"{analise.maior_queda()} p.p.")
        col_b.metric(t["instabilidade"], f"{analise.instabilidade()} p.p.")
    st.subheader(t["margem_mensal"])
    st.line_chart(pd.Series({mes: float(m) for mes, m in serie}, name="%"))
    st.subheader(t["lucro_acumulado"])
    st.area_chart(
        pd.Series({mes: float(v) for mes, v in analise.lucro_acumulado()}, name="R$")
    )

# ---------------------------------------------------------------------------
with aba_cenarios:
    st.caption(t["cenarios_caption"])
    for resultado in analise.cenarios():
        with st.container(border=True):
            st.markdown(f"**{resultado.nome}**")
            c1, c2, c3 = st.columns(3)
            c1.metric(t["margem_cenario"], _brl(resultado.cenario.margem_liquida))
            c2.metric(t["impacto_reais"], _brl(resultado.impacto_reais))
            c3.metric(t["impacto_pp"], f"{resultado.impacto_pp:+.2f}")

# ---------------------------------------------------------------------------
with aba_crescimento:
    st.caption(t["crescimento_caption"])
    for oportunidade in analise.crescimento():
        with st.container(border=True):
            ganho = _brl(oportunidade.ganho_estimado_mensal)
            mes = "mês" if lang == "pt" else "mo"
            st.markdown(
                f"**{oportunidade.titulo}** — ~{ganho}/{mes} "
                f"[{oportunidade.confianca} · {oportunidade.tipo}]"
            )
            st.write(oportunidade.explicacao)
            for disp in oportunidade.base_legal:
                st.markdown(
                    f"- **{disp.lei}, {disp.artigo}** — {disp.resumo} "
                    f"[[{t['fonte_oficial']}]({disp.fonte})]"
                )
            st.markdown(f"**{t['caminho']}** {oportunidade.caminho_pratico}")

    st.subheader(t["simular_canal"])
    col_c1, col_c2 = st.columns(2)
    canal_cresc = col_c1.selectbox(
        t["canal"], sorted({tr.canal for tr in transacoes}), key="canal_cresc"
    )
    pct_cresc = col_c2.slider(t["crescimento_vendas"], 5, 100, 20, 5)
    try:
        simulacao = analise.simular(
            CenarioCrescimentoCanal(canal_cresc, Decimal(pct_cresc) / 100)
        )
        c1, c2, c3 = st.columns(3)
        c1.metric(t["margem_hoje"], _brl(simulacao.base.margem_liquida))
        c2.metric(t["margem_cenario"], _brl(simulacao.cenario.margem_liquida))
        c3.metric(t["ganho"], _brl(simulacao.impacto_reais))
    except ValueError as erro:
        st.warning(str(erro))

    st.subheader(t["calculadora"])
    col_p1, col_p2, col_p3, col_p4 = st.columns(4)
    calc_custo = col_p1.number_input(t["custo_produto"], 0.01, 100000.0, 40.0)
    calc_frete = col_p2.number_input(t["frete"], 0.0, 10000.0, 10.0)
    calc_canal = col_p3.selectbox(
        t["canal_venda"],
        ["mercado_livre", "shopee", "amazon", "loja_propria", "fisico"],
        key="calc_canal",
    )
    calc_margem = col_p4.number_input(t["margem_alvo"], 0.0, 60.0, 10.0, 1.0)
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
        col_r1.metric(t["preco_equilibrio"], _brl(equilibrio))
        col_r2.metric(t["preco_para"].format(pct=f"{calc_margem:.0f}"), _brl(alvo))
    except ValueError as erro:
        st.error(str(erro))
    st.caption(AVISO_CRESCIMENTO)

# ---------------------------------------------------------------------------
with aba_diagnostico:
    retriever = analise.retriever
    st.warning(retriever.aviso_corpus)

    st.subheader(t["vazamentos"])
    achados = analise.diagnosticar()
    if not achados:
        st.success(t["sem_achados"])
    for achado in achados:
        with st.expander(
            f"{achado.titulo} — ~{_brl(achado.impacto_mensal)}"
            f"/{'mês' if lang == 'pt' else 'mo'} [{achado.confianca}]"
        ):
            st.write(achado.explicacao)
            st.markdown(f"**{t['base_legal']}**")
            for disp in achado.base_legal:
                pendente = "" if disp.revisado else t["pendente"]
                st.markdown(
                    f"- **{disp.lei}, {disp.artigo}**{pendente} — {disp.resumo} "
                    f"[[{t['fonte_oficial']}]({disp.fonte})]"
                )
            st.markdown(f"**{t['caminho']}** {achado.caminho_pratico}")
            st.caption(achado.aviso)

    st.subheader(t["pergunte"])
    pergunta = st.text_input(t["pergunta_exemplo"])
    if pergunta:
        dispositivos = retriever.buscar(pergunta)
        resposta = gerar_resposta(pergunta, dispositivos)
        if resposta is None:
            resposta = resposta_extrativa(pergunta, dispositivos)
            st.caption(t["modo_extrativo"])
        st.write(resposta)

# ---------------------------------------------------------------------------
with aba_relatorio:
    st.caption(t["relatorio_caption"])
    if st.button(t["gerar_pdf"]):
        buffer = io.BytesIO()
        analise.gerar_pdf(buffer)
        st.download_button(
            t["baixar_pdf"],
            data=buffer.getvalue(),
            file_name="relatorio_carchuna.pdf",
            mime="application/pdf",
        )
    st.caption(AVISO_LEGAL)
