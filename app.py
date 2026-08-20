"""Dashboard da Carchuna — pensado para o lojista, não para o analista.

Sete abas em linguagem simples: Resumo (o essencial em uma tela),
Vendas e Produtos (campeões e vilões de margem), Histórico (evolução
mês a mês), E se…? (testes de estresse), Crescer (como faturar mais),
Diagnóstico Legal e Relatório. Interface bilíngue (PT/EN); roda 100%
offline com dados sintéticos e aceita upload de CSV/JSON/XLSX.

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
    carregar_com_relatorio,
    transacoes_sinteticas,
)
from carchuna.crescimento import AVISO_CRESCIMENTO
from carchuna.dados import (
    COLUNAS_OBRIGATORIAS,
    leitura_por_caminho_ligada,
    ler_linhas_brutas,
    sugerir_mapeamento,
    transacoes_de_mapa,
)
from carchuna.rag.llm import estado_da_geracao, gerar_resposta, resposta_extrativa
from carchuna.rag.retrieval import AVISO_LEGAL
from paginas._comum import (
    _CONSTANTES_MAPA,
    ATIVIDADES,
    ROTULOS_EN,
    ROTULOS_SIMPLES_PT,
    T,
    _brl,
    _brl_inteiro,
    _lacunas_do_arquivo,
    _lista_de_meses,
    _percentual,
    _rotulo_opcao,
    _transacoes_do_resultado,
)
from paginas._estado import (
    _composicao_cacheada,
    _resultados_cacheados,
    _retriever_cacheado,
)
from paginas._graficos import (
    _grafico_barras_h,
    _grafico_barras_v,
    _grafico_cachoeira,
    _grafico_serie,
)

st.set_page_config(page_title="Carchuna", layout="wide")

# Tipografia dos números: serenos, tabulares, em água-clara — e métricas
# como cartões uniformes, para a simetria entre as colunas.
st.markdown(
    """
    <style>
    [data-testid="stMetric"] {
        background: rgba(10, 56, 64, 0.55);
        border: 1px solid #134d57;
        border-radius: 14px;
        padding: 14px 18px;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.6rem;
        font-weight: 600;
        color: #9ff2e9;
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.01em;
    }
    [data-testid="stMetricLabel"] { color: #87a9a8; }
    [data-testid="stMetricDelta"] { font-size: 0.85rem; }
    [data-testid="stTable"], [data-testid="stDataFrame"] {
        font-variant-numeric: tabular-nums;
    }
    h1 { letter-spacing: -0.5px; }
    h2, h3 { letter-spacing: -0.3px; }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    idioma = st.radio("Idioma / Language", ["PT", "EN"], horizontal=True, key="idioma")
lang = "pt" if idioma == "PT" else "en"
t = T[lang]
rotulos = ROTULOS_SIMPLES_PT if lang == "pt" else ROTULOS_EN


st.title(t["titulo"])
st.caption(t["subtitulo"])
if t["nota_motor"]:
    st.caption(t["nota_motor"])

# ---------------------------------------------------------------------------
# Barra lateral: 3 passos simples
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header(t["passo1"])
    upload = st.file_uploader(
        t["upload"], type=["csv", "json", "xlsx", "pdf"], help=t["upload_ajuda"]
    )
    caminho_arquivo = ""
    monitorar = False
    with st.expander(t["tempo_real"]):
        # O campo não aparece desligado, em vez de aparecer e recusar:
        # campo que só devolve erro é pior que campo nenhum, e a caixa de
        # texto sozinha já convida a tentar um caminho do servidor.
        if leitura_por_caminho_ligada():
            caminho_arquivo = st.text_input(
                t["caminho_arquivo"], help=t["tempo_real_ajuda"], key="caminho_arquivo"
            ).strip()
            monitorar = st.toggle(t["monitorar"], value=bool(caminho_arquivo))
        else:
            st.info(t["caminho_desligado"])
    linhas_brutas = None
    if upload is not None:
        try:
            transacoes = _transacoes_do_resultado(
                carregar_com_relatorio(upload, name=upload.name), t
            )
        except (ValueError, TypeError) as erro:
            upload.seek(0)
            try:
                linhas_brutas = ler_linhas_brutas(upload, name=upload.name)
            except (ValueError, TypeError, ImportError):
                st.error(f"{t['falha_importacao']} {erro}")
                st.stop()
    elif caminho_arquivo:
        try:
            transacoes = _transacoes_do_resultado(
                carregar_com_relatorio(caminho_arquivo), t
            )
            if monitorar:
                st.info(t["monitorando"])
        except OSError:
            # A mensagem do sistema operacional traz errno e o caminho
            # inteiro, e as três respostas possíveis (não existe, sem
            # permissão, existe e não parseia) desenham um oráculo de
            # arquivos do servidor. O motivo do motor é escrito para o
            # lojista; este não é escrito para ninguém.
            st.error(t["falha_arquivo"])
            st.stop()
        except (ValueError, TypeError, ImportError) as erro:
            st.error(f"{t['falha_importacao']} {erro}")
            st.stop()
    else:
        meses_demo = st.slider(t["meses_demo"], 2, 12, 6)
        transacoes = transacoes_sinteticas(meses=meses_demo)

    if linhas_brutas is not None:
        # Mapeador de colunas: o relatório real veio com outros nomes —
        # o usuário aponta o de-para e a análise segue normalmente.
        st.info(t["mapa_sidebar"])
        st.caption(t["mapa_caption"])
        colunas_arquivo = sorted({chave for lin in linhas_brutas for chave in lin})
        palpites = sugerir_mapeamento(colunas_arquivo)
        mapa: dict[str, str] = {}
        for campo, rotulo in t["mapa_campos"].items():
            opcoes = ["", *colunas_arquivo, *_CONSTANTES_MAPA.get(campo, [])]
            palpite = palpites.get(campo) or ""
            mapa[campo] = st.selectbox(
                rotulo,
                opcoes,
                index=opcoes.index(palpite) if palpite in opcoes else 0,
                key=f"mapa_{campo}",
                format_func=lambda opcao: _rotulo_opcao(opcao, t),
            )
        faltando = [
            t["mapa_campos"][campo].rstrip(" •")
            for campo in COLUNAS_OBRIGATORIAS
            if not mapa.get(campo)
        ]
        if faltando:
            st.warning(t["mapa_incompleto"].format(campos=", ".join(faltando)))
            st.stop()
        try:
            transacoes = transacoes_de_mapa(
                linhas_brutas, {c: o for c, o in mapa.items() if o}
            )
            st.success(f"{len(transacoes)} {t['importadas']}")
        except (ValueError, TypeError) as erro:
            st.error(f"{t['falha_importacao']} {erro}")
            st.stop()

    # Um upload transcreve tudo: com dados reais, a RBT12 é sugerida do
    # próprio arquivo (média mensal x 12) — editável e para confirmar
    # com o PGDAS-D; a alíquota do Simples sai dela, pela LC 123.
    rbt12_sugerida = None
    if upload is not None or caminho_arquivo:
        meses_arquivo = len({(tr.data.year, tr.data.month) for tr in transacoes})
        receita_arquivo = sum((tr.valor_bruto for tr in transacoes), Decimal("0"))
        rbt12_sugerida = int(
            min(
                max(receita_arquivo / meses_arquivo * 12, Decimal("1000")),
                Decimal("4800000"),
            )
        )

    st.header(t["passo2"])
    regime = st.selectbox(
        t["regime"],
        ["simples", "mei"],
        format_func=str.upper,
        help=t["regime_ajuda"],
    )
    if regime == "simples":
        anexo = st.selectbox(
            t["anexo"], ["I", "II", "III", "IV", "V"], help=t["anexo_ajuda"]
        )
        rbt12 = st.number_input(
            t["rbt12"],
            min_value=1_000,
            max_value=4_800_000,
            value=rbt12_sugerida or 750_000,
            step=10_000,
            help=t["rbt12_ajuda"],
            key="rbt12",
        )
        if rbt12_sugerida:
            st.caption(t["rbt12_sugerida"])
        usar_rbt12_movel = st.toggle(
            t["rbt12_movel"],
            value=False,
            help=t["rbt12_movel_ajuda"],
            key="rbt12_movel",
        )
        # Mês vazio no MEIO da janela é a única pergunta que o lojista sabe
        # responder — e a Carchuna não. Fica na barra lateral, antes do
        # cálculo, porque a resposta dele muda a alíquota da série.
        confirmar_lacunas = False
        if usar_rbt12_movel:
            lacunas = _lacunas_do_arquivo(transacoes)
            if lacunas:
                st.warning(t["rbt12_lacuna"].format(meses=_lista_de_meses(lacunas, t)))
                confirmar_lacunas = st.checkbox(
                    t["rbt12_lacuna_confirmar"],
                    value=False,
                    help=t["rbt12_lacuna_ajuda"],
                    key="confirmar_lacunas",
                )
        config = ConfigTributaria(
            regime="simples", anexo_simples=anexo, rbt12=Decimal(int(rbt12))
        )
    else:
        usar_rbt12_movel = False
        confirmar_lacunas = False
        das = st.number_input(t["das"], 1, 500, 76, help=t["das_ajuda"])
        config = ConfigTributaria(regime="mei", das_mei_mensal=Decimal(int(das)))

    st.header(t["passo3"])
    # Percentual entra como TEXTO, não `st.number_input`: aquele widget
    # devolve `float`, e este número multiplica cada venda da base. Com o
    # parser da planilha (`decimal_de_texto`) o valor vira Decimal direto,
    # e a regra da casa segue com uma exceção só — a do openpyxl.
    taxa_adq = _percentual(t["taxa_adq"], "2,00", t["taxa_adq_ajuda"], t, "taxa_adq")
    taxa_ant = _percentual(t["taxa_ant"], "1,99", t["taxa_ant_ajuda"], t, "taxa_ant")
    tabela = TabelaCustos(
        taxa_adquirencia=taxa_adq / 100,
        taxa_antecipacao_mensal=taxa_ant / 100,
    )
    atividade = st.selectbox(
        t["atividade"],
        ["comercio", "industria", "servicos"],
        format_func=lambda a: ATIVIDADES[lang][a],
    )

if upload is None and not caminho_arquivo:
    st.warning(t["aviso_demo"])

if monitorar and caminho_arquivo:
    # Vigia o arquivo apontado: quando o mtime muda (a pessoa salvou a
    # planilha), dispara um rerun completo — os números se atualizam
    # sozinhos. Roda como fragment para custar quase nada entre reruns.
    @st.fragment(run_every="3s")
    def _vigiar_arquivo():
        from pathlib import Path

        try:
            mtime = Path(caminho_arquivo).stat().st_mtime
        except OSError:
            return
        if st.session_state.get("_mtime_arquivo") != mtime:
            st.session_state["_mtime_arquivo"] = mtime
            st.rerun(scope="app")

    _vigiar_arquivo()

# Rastreabilidade: o nome do arquivo real alimenta a ficha de linhagem.
# Dado de exemplo se declara como exemplo — na ficha, não só no aviso.
if upload is not None:
    origem_dados = upload.name
elif caminho_arquivo:
    origem_dados = caminho_arquivo
else:
    origem_dados = (
        "dados sintéticos de exemplo" if lang == "pt" else "synthetic sample data"
    )

# Motores rodam uma vez por (dados, config) via cache; a fachada fica
# disponível para as ações sob demanda (simular, preço, PDF, busca legal).
res = _resultados_cacheados(
    tuple(transacoes),
    config,
    tabela,
    atividade,
    usar_rbt12_movel,
    origem_dados,
    confirmar_lacunas,
)


def _motor(chave: str):
    """O resultado do motor, ou o motivo na tela e ``None`` no lugar.

    Publica onde é chamada, de propósito: o mesmo motor alimenta abas
    diferentes, e cada aba tem de explicar a própria lacuna em vez de
    mandar o lojista procurar o aviso em outra.
    """
    if chave in res["falhas"]:
        st.error(f"**{t['motor_falhou']}** {res['falhas'][chave]}")
    return res[chave]


def _falhou(chave: str) -> bool:
    """Distingue "o motor não rodou" de "rodou e não achou nada".

    Sem isto, a lista vazia de um motor que estourou herdaria a mensagem
    de sucesso do caso em que ele roda e não encontra nada — trocando um
    erro por um "está tudo bem" que ninguém pediu.
    """
    return chave in res["falhas"]


# A decomposição não é um motor entre outros: é a base de todos. Sem ela
# as abas não teriam o que mostrar, e fingir o contrário seria pior que
# parar — então o motivo vai para a tela e o desenho para aqui.
if res["decomposicao"] is None or res["resumo"] is None:
    st.error(
        f"**{t['motor_falhou_base']}** "
        + (res["falhas"].get("decomposicao") or res["falhas"].get("resumo", ""))
    )
    st.stop()

analise = AnalisadorMargem(
    transacoes,
    config,
    tabela,
    ParametrosDiagnostico(atividade=atividade),
    retriever=_retriever_cacheado(),
    rbt12_movel=usar_rbt12_movel,
    confirmar_lacunas=confirmar_lacunas,
    origem=origem_dados,
)
if usar_rbt12_movel:
    # Honestidade na tela: dizer em quantos meses a alíquota saiu do
    # próprio arquivo e em quantos veio do valor que o lojista digitou.
    janelas = _motor("rbt12_mensal") or {}
    _com_janela = sum(1 for v in janelas.values() if v)
    if _com_janela:
        st.caption(t["rbt12_movel_aplicada"].format(n=_com_janela, total=len(janelas)))
    else:
        st.info(t["rbt12_movel_sem_janela"])
    if confirmar_lacunas:
        # O caminho escolhido fica escrito na tela, não só no objeto.
        st.caption(t["rbt12_lacuna_confirmada"])
decomposicao = res["decomposicao"]
resumo = res["resumo"]

(
    aba_resumo,
    aba_vendas,
    aba_historico,
    aba_ese,
    aba_crescer,
    aba_diagnostico,
    aba_relatorio,
) = st.tabs(t["abas"])

# ---------------------------------------------------------------------------
with aba_resumo:
    # Faixa de plausibilidade: quando o número não cabe em realidade
    # contábil nenhuma, o motivo vem ANTES dos números — e os números
    # continuam na tela, porque escondê-los não conserta o dado de origem.
    plausibilidade = _motor("plausibilidade")
    if plausibilidade is not None and not plausibilidade.ok:
        st.error(f"**{t['implausivel_titulo']}** {plausibilidade.motivo}")
    reconciliacao = _motor("reconciliacao")
    if reconciliacao is not None and not reconciliacao.ok:
        st.error(f"**{t['reconciliacao_titulo']}** {reconciliacao.motivo}")

    # Avisos do motor: o número saiu e vale, mas há algo que ele não
    # cobre — o ICMS/ISS fora do DAS acima do sublimite, o ritmo de
    # faturamento que projeta estouro do teto do MEI. Vêm em `warning`,
    # não em `error`, porque não invalidam nada do que está abaixo; vêm
    # acima dos números porque uma ressalva lida depois da margem é uma
    # ressalva que já não foi lida.
    for aviso in decomposicao.avisos:
        st.warning(f"**{t['aviso_titulo']}** {aviso}")

    if lang == "pt":
        st.info(resumo.frase())
    else:
        maior = resumo.maior_fonte
        st.info(
            f"Over {resumo.meses} month(s), {_brl(resumo.perda_total)} of "
            f"margin was lost between the head-math margin "
            f"({resumo.margem_anunciada_pct}%) and the real one "
            f"({resumo.margem_real_pct}%); "
            f"{maior.pct_da_perda.quantize(Decimal('1'))}% of that came "
            f"from {ROTULOS_EN.get(maior.nome, maior.rotulo)}."
        )
    col1, col2, col3 = st.columns(3)
    col1.metric(t["faturou"], _brl(resumo.receita_bruta))
    col2.metric(t["sobrou"], _brl(resumo.margem_real), f"{resumo.margem_real_pct}%")
    col3.metric(
        t["foi_embora"],
        _brl(resumo.perda_total + decomposicao.deducao("cmv").valor),
    )

    st.subheader(t["para_onde"])
    evento = st.altair_chart(
        _grafico_cachoeira(decomposicao, rotulos, t),
        width="stretch",
        on_select="rerun",
        key="cachoeira",
    )
    clicados = [
        p.get("nome")
        for p in (evento.selection.get("ponto") or [])
        if p.get("nome") not in (None, "receita", "margem")
    ]
    if clicados:
        nome_drill = clicados[0]
        comp = _composicao_cacheada(tuple(transacoes), config, tabela, nome_drill)
        rotulo_drill = rotulos.get(nome_drill, nome_drill)
        st.markdown(f"##### {t['drill_titulo'].format(rotulo=rotulo_drill)}")
        col_canal, col_mes = st.columns(2)
        with col_canal:
            st.caption(t["drill_por_canal"])
            if comp["por_canal"]:
                st.altair_chart(
                    _grafico_barras_h(
                        [
                            {
                                "rotulo": canal,
                                "valor": float(valor),
                                "texto": _brl_inteiro(valor),
                            }
                            for canal, valor in comp["por_canal"]
                        ]
                    ),
                    width="stretch",
                )
            else:
                st.info(t["drill_sem_canal"])
        with col_mes:
            st.caption(t["drill_por_mes"])
            st.altair_chart(
                _grafico_barras_v(
                    [
                        {
                            "rotulo": mes,
                            "valor": float(valor),
                            "texto": _brl_inteiro(valor),
                        }
                        for mes, valor in comp["por_mes"]
                    ]
                ),
                width="stretch",
            )
    else:
        st.caption(t["cachoeira_dica"])

    st.subheader(t["radar_titulo"])
    st.caption(t["radar_caption"])
    radar = _motor("radar") or []
    if not radar and not _falhou("radar"):
        st.success(t["radar_vazio"])
    estilo_sev = {
        "critico": st.error,
        "atencao": st.warning,
        "oportunidade": st.success,
    }
    for sinal in radar:
        corpo = (
            f"**{t['radar_sev'][sinal.severidade]} · {sinal.titulo}** — "
            f"~{_brl(sinal.impacto_mensal)}/{t['por_mes']}\n\n{sinal.explicacao}"
        )
        if sinal.esperado and sinal.observado:
            corpo += (
                f"\n\n{t['radar_esperado']}: {sinal.esperado} · "
                f"{t['radar_observado']}: {sinal.observado}"
            )
        nota_sinal = t["conf_nota"].format(
            pct=sinal.confianca.pct, nivel=sinal.confianca.nivel
        )
        corpo += f"\n\n{nota_sinal} — {sinal.confianca.frase}"
        estilo_sev[sinal.severidade](corpo)
        st.caption(f"{t['radar_metodo']} {sinal.metodo}")
        st.caption(sinal.caminho_pratico)
    st.caption(t["radar_aviso"])

    st.subheader(t["acoes_titulo"])
    st.caption(t["acoes_caption"])
    acoes = [
        (a.impacto_mensal, a.titulo, a.caminho_pratico) for a in _motor("achados") or []
    ] + [
        (o.ganho_estimado_mensal, o.titulo, o.caminho_pratico)
        for o in _motor("oportunidades") or []
    ]
    acoes.sort(key=lambda x: x[0], reverse=True)
    if not acoes and not (_falhou("achados") or _falhou("oportunidades")):
        st.success(t["sem_acoes"])
    for valor, titulo, caminho in acoes[:3]:
        with st.container(border=True):
            st.markdown(f"**{titulo}** — ~{_brl(valor)}/{t['por_mes']}")
            st.caption(caminho)

    nota = _motor("confianca")
    if nota is not None:
        with st.expander(
            f"{t['conf_titulo']} — "
            + t["conf_nota"].format(pct=nota.pct, nivel=nota.nivel.upper())
        ):
            st.markdown(f"_{nota.frase}_")
            st.caption(t["conf_caption"])
            for componente in nota.componentes:
                st.markdown(
                    f"- **{componente.pontos}/{componente.maximo}** — "
                    f"{componente.motivo}"
                )

    with st.expander(t["lin_titulo"]):
        st.caption(t["lin_caption"])
        fichas = _motor("linhagem")
        if fichas:
            nome_ficha = st.selectbox(
                t["lin_numero"],
                list(fichas),
                format_func=lambda n: (
                    f"{rotulos.get(n, fichas[n].rotulo)} — {_brl(fichas[n].valor)}"
                ),
                key="linhagem_numero",
            )
            ficha = fichas[nome_ficha]
            st.markdown(f"**{t['lin_origem']}:** `{ficha.origem_dados}`")
            st.markdown(f"**{t['lin_colunas']}:** `{'`, `'.join(ficha.colunas)}`")
            st.markdown(f"**{t['lin_formula']}:** {ficha.formula}")
            st.markdown(f"**{t['lin_transf']}:**")
            for transformacao in ficha.transformacoes:
                st.markdown(f"- {transformacao}")
            if ficha.premissas:
                st.markdown(f"**{t['lin_premissas']}:**")
                for premissa in ficha.premissas:
                    st.markdown(f"- {premissa}")
            if ficha.limitacoes:
                st.markdown(f"**{t['lin_limitacoes']}:**")
                for limitacao in ficha.limitacoes:
                    st.markdown(f"- {limitacao}")
            st.caption(
                f"{t['lin_fonte']} {ficha.fonte} · [{ficha.confianca_dados}] · "
                f"{t['lin_quando']} {ficha.calculado_em.strftime('%d/%m/%Y %H:%M')}"
            )

    with st.expander(t["como_ler"]):
        st.markdown(t["como_ler_texto"])

# ---------------------------------------------------------------------------
with aba_vendas:
    frame = pd.DataFrame(
        [
            {
                "data": tr.data,
                "produto": tr.produto or "—",
                "canal": tr.canal,
                "valor_bruto": float(tr.valor_bruto),
                "custo_produto": float(tr.custo_produto),
                "frete_pago": float(tr.frete_pago),
                "devolvida": tr.devolvida,
            }
            for tr in transacoes
        ]
    )
    m = t["vendas_metricas"]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(m[0], len(frame))
    col2.metric(m[1], _brl(decomposicao.receita_bruta))
    col3.metric(m[2], frame["canal"].nunique())
    col4.metric(m[3], int(frame["devolvida"].sum()))

    produtos = _motor("por_produto") or []
    campeoes = [p for p in produtos if p.margem > 0][:3]
    viloes = [p for p in produtos if p.margem < 0]

    st.subheader(t["campeoes"])
    st.caption(t["campeoes_caption"])
    colunas = st.columns(max(len(campeoes), 1))
    for coluna, produto in zip(colunas, campeoes, strict=False):
        with coluna, st.container(border=True):
            st.markdown(f"**{produto.nome}**")
            st.metric(
                t["col_margem_pct"],
                f"{produto.margem_pct}%",
                _brl(produto.margem),
            )
            st.caption(f"R$ {produto.margem_pct:.0f} {t['cada_100']}")

    st.subheader(t["viloes"])
    if not viloes:
        st.success(t["sem_viloes"])
    else:
        st.caption(t["viloes_caption"])
        for produto in viloes:
            st.error(
                f"**{produto.nome}** — {produto.vendas}x · "
                f"{_brl(produto.margem)} {t['prejuizo_por_venda']} "
                f"({produto.margem_pct}%)"
            )

    st.subheader(t["tabela_produtos"])
    st.dataframe(
        pd.DataFrame(
            [
                {
                    t["col_produto"]: p.nome,
                    t["col_vendas"]: p.vendas,
                    t["col_devolvidas"]: p.devolvidas,
                    t["col_receita"]: _brl(p.receita),
                    t["col_margem"]: _brl(p.margem),
                    t["col_margem_pct"]: f"{p.margem_pct}%",
                }
                for p in produtos
            ]
        ),
        width="stretch",
    )

    st.subheader(t["receita_por_canal"])
    por_canal = frame.groupby("canal")["valor_bruto"].sum()
    st.altair_chart(
        _grafico_barras_h(
            [
                {
                    "rotulo": canal,
                    "valor": float(valor),
                    "texto": _brl_inteiro(Decimal(str(round(valor)))),
                }
                for canal, valor in por_canal.items()
            ]
        ),
        width="stretch",
    )

    with st.expander(t["todas_vendas"]):
        if st.toggle(t["margem_por_venda"], value=len(frame) <= 500):
            por_venda = _motor("por_venda")
            if por_venda is not None:
                frame["margem"] = [float(v.margem_liquida) for v in por_venda]
                frame["margem_%"] = [float(v.margem_pct) for v in por_venda]
        st.dataframe(frame, width="stretch", height=320)

# ---------------------------------------------------------------------------
with aba_historico:
    st.caption(t["hist_caption"])
    mensal = _motor("mensal") or {}
    if len(mensal) < 2:
        if not _falhou("mensal"):
            st.info(t["hist_um_mes"])
    else:
        meses_lst = list(mensal.items())
        (mes_a, dec_a), (mes_b, dec_b) = meses_lst[-2], meses_lst[-1]
        delta_pp = dec_b.margem_pct - dec_a.margem_pct
        difs = {
            d.nome: (
                dec_b.deducao(d.nome).pct_receita - dec_a.deducao(d.nome).pct_receita
            )
            for d in dec_b.deducoes
        }
        causa = max(difs, key=lambda n: abs(difs[n]))
        modelo = t["hist_frase_melhora"] if delta_pp >= 0 else t["hist_frase_piora"]
        st.info(
            modelo.format(
                m1=mes_a,
                m2=mes_b,
                a=dec_a.margem_pct,
                b=dec_b.margem_pct,
                d=abs(delta_pp),
                causa=rotulos.get(causa, causa),
                ca=dec_a.deducao(causa).pct_receita,
                cb=dec_b.deducao(causa).pct_receita,
            )
        )
        st.subheader(t["hist_comparacao"])
        c1, c2, c3 = st.columns(3)
        c1.metric(
            t["delta_receita"],
            _brl(dec_b.receita_bruta),
            _brl(dec_b.receita_bruta - dec_a.receita_bruta),
        )
        c2.metric(
            t["delta_margem"],
            _brl(dec_b.margem_liquida),
            _brl(dec_b.margem_liquida - dec_a.margem_liquida),
        )
        c3.metric(t["delta_pp"], f"{dec_b.margem_pct}%", f"{delta_pp:+.2f}")

        dec = (lambda v: v.replace(".", ",")) if lang == "pt" else (lambda v: v)
        st.subheader(t["hist_receita"])
        st.altair_chart(
            _grafico_barras_v(
                [
                    {
                        "rotulo": mes,
                        "valor": float(d.receita_bruta),
                        "texto": _brl_inteiro(d.receita_bruta),
                    }
                    for mes, d in mensal.items()
                ]
            ),
            width="stretch",
        )
        st.subheader(t["hist_margem"])
        st.altair_chart(
            _grafico_serie(
                [
                    {
                        "rotulo": mes,
                        "valor": float(d.margem_pct),
                        "texto": dec(f"{d.margem_pct}%"),
                    }
                    for mes, d in mensal.items()
                ],
                modo="linha",
            ),
            width="stretch",
        )
        st.subheader(t["hist_lucro"])
        st.altair_chart(
            _grafico_serie(
                [
                    {"rotulo": mes, "valor": float(v), "texto": _brl_inteiro(v)}
                    for mes, v in _motor("lucro") or []
                ],
                modo="area",
            ),
            width="stretch",
        )

        st.subheader(t["hist_tabela"])
        historico = pd.DataFrame(
            [
                {
                    t["col_mes"]: mes,
                    t["col_receita"]: float(d.receita_bruta),
                    t["col_margem"]: float(d.margem_liquida),
                    t["col_margem_pct"]: float(d.margem_pct),
                    t["col_maior_custo"]: rotulos.get(
                        max(d.deducoes, key=lambda x: x.valor).nome, ""
                    ),
                }
                for mes, d in mensal.items()
            ]
        )
        st.dataframe(historico, width="stretch")
        st.download_button(
            t["baixar_hist"],
            data=historico.to_csv(index=False).encode("utf-8"),
            file_name="historico_carchuna.csv",
            mime="text/csv",
        )

# ---------------------------------------------------------------------------
with aba_ese:
    st.caption(t["ese_caption"])
    for resultado in _motor("cenarios") or []:
        with st.container(border=True):
            st.markdown(f"**{resultado.nome}**")
            c1, c2, c3 = st.columns(3)
            c1.metric(t["margem_cenario"], _brl(resultado.cenario.margem_liquida))
            c2.metric(t["impacto_reais"], _brl(resultado.impacto_reais))
            c3.metric(t["impacto_pp"], f"{resultado.impacto_pp:+.2f}")
            # Carimbo do cenário: ressalva do estado SIMULADO, embaixo do
            # número a que ela se refere. Antes o cenário que atravessava
            # o sublimite sumia da bateria — e a travessia era o que ele
            # tinha de mais útil a dizer.
            for aviso in resultado.avisos:
                st.warning(aviso)

# ---------------------------------------------------------------------------
with aba_crescer:
    st.caption(t["crescimento_caption"])
    for oportunidade in _motor("oportunidades") or []:
        with st.container(border=True):
            ganho = _brl(oportunidade.ganho_estimado_mensal)
            st.markdown(
                f"**{oportunidade.titulo}** — ~{ganho}/{t['por_mes']} "
                f"[{oportunidade.confianca}]"
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
    st.caption(t["calculadora_caption"])
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
    st.caption(t["diag_caption"])
    retriever = analise.retriever
    st.warning(retriever.aviso_corpus)

    st.subheader(t["vazamentos"])
    achados = _motor("achados") or []
    if not achados and not _falhou("achados"):
        st.success(t["sem_achados"])
    for achado in achados:
        with st.expander(
            f"{achado.titulo} — ~{_brl(achado.impacto_mensal)}"
            f"/{t['por_mes']} [{achado.confianca}]"
        ):
            st.write(achado.explicacao)
            st.markdown(f"**{t['base_legal']}**")
            for disp in achado.base_legal:
                # Dois estados visíveis, não um. "Sem aviso" era o jeito
                # de dizer conferido, e ausência de aviso não diz nada:
                # some junto se alguém marcar `revisado` por engano, e
                # nunca diz QUANDO — que é a parte que envelhece.
                if not disp.revisado:
                    pendente = t["pendente"]
                elif disp.conferido_em:
                    pendente = t["conferido_em"].format(data=disp.conferido_em)
                else:
                    pendente = t["pendente"]
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
            # Nenhum erro vira silêncio: se a narrativa não saiu por
            # configuração faltando ou por falha na chamada, o motivo
            # aparece aqui em vez de o lojista ficar sem saber.
            motivo = estado_da_geracao()["motivo"]
            if motivo:
                st.caption(t["narrativa_indisponivel"].format(motivo=motivo))
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
