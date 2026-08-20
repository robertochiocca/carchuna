"""Os cinco gráficos do dashboard, e a paleta que só eles usam.

Extraído do `app.py` sem alteração de comportamento. As cores vieram
junto porque não são usadas em nenhum outro lugar: fora destas funções o
`app.py` não referenciava `AGUA`, `TEAL_CALMO` nem `_SEM_FUNDO`.

Cada função devolve um gráfico Altair pronto; nenhuma desenha na tela.
Quem chama decide onde e se mostra.
"""

from __future__ import annotations

from decimal import Decimal

import altair as alt
import pandas as pd

from paginas._comum import _brl_inteiro

AGUA = "#2ee6d6"
AGUA_TEXTO = "#cfe9e6"
TEAL_CALMO = "#4fb3c1"
_SEM_FUNDO = {"background": "rgba(0,0,0,0)"}


def _base_config(grafico):
    return grafico.configure(**_SEM_FUNDO).configure_view(strokeOpacity=0)


def _grafico_cachoeira(decomposicao, rotulos: dict, t: dict):
    """A cachoeira da margem: do faturamento ao que sobrou, degrau a degrau.

    Cada dedução é um degrau descendo do acumulado; a última barra é o
    que sobrou. As barras de custo são clicáveis (seleção nomeada
    ``ponto``): o app abre a composição por canal e por mês da dedução
    clicada. Estilo da casa: sem eixo Y, valor escrito sobre cada barra.
    """
    linhas = [
        {
            "nome": "receita",
            "rotulo": t["wf_receita"],
            "inicio": 0.0,
            "fim": float(decomposicao.receita_bruta),
            "topo": float(decomposicao.receita_bruta),
            "texto": _brl_inteiro(decomposicao.receita_bruta),
            "tipo": "receita",
        }
    ]
    acumulado = decomposicao.receita_bruta
    for d in decomposicao.deducoes:
        linhas.append(
            {
                "nome": d.nome,
                "rotulo": rotulos.get(d.nome, d.nome),
                "inicio": float(acumulado - d.valor),
                "fim": float(acumulado),
                "topo": float(acumulado),
                "texto": f"− {_brl_inteiro(d.valor)}",
                "tipo": "deducao",
            }
        )
        acumulado -= d.valor
    margem = decomposicao.margem_liquida
    linhas.append(
        {
            "nome": "margem",
            "rotulo": t["sobrou"],
            "inicio": float(min(Decimal("0"), margem)),
            "fim": float(max(Decimal("0"), margem)),
            "topo": float(max(Decimal("0"), margem)),
            "texto": _brl_inteiro(margem),
            "tipo": "margem",
        }
    )
    dados = pd.DataFrame(linhas)
    selecao = alt.selection_point(name="ponto", fields=["nome"], on="click")
    base = alt.Chart(dados).encode(
        x=alt.X(
            "rotulo:N",
            sort=dados["rotulo"].tolist(),
            title=None,
            axis=alt.Axis(
                labelAngle=-22,
                labelFontSize=12,
                labelColor="#d8e7e5",
                labelLimit=0,
                labelOverlap=False,
            ),
        )
    )
    barras = (
        base.mark_bar(cornerRadius=6, size=46)
        .encode(
            y=alt.Y(
                "inicio:Q",
                title=None,
                axis=alt.Axis(labels=False, grid=False, ticks=False, domain=False),
            ),
            y2="fim:Q",
            color=alt.Color(
                "tipo:N",
                scale=alt.Scale(
                    domain=["receita", "deducao", "margem"],
                    range=[TEAL_CALMO, "#cf8a70", "#8fd694"],
                ),
                legend=None,
            ),
            opacity=alt.condition(selecao, alt.value(1.0), alt.value(0.55)),
            tooltip=[
                alt.Tooltip("rotulo:N", title=" "),
                alt.Tooltip("texto:N", title="R$"),
            ],
        )
        .add_params(selecao)
    )
    textos = base.mark_text(
        dy=-10, color=AGUA_TEXTO, fontSize=11.5, font="monospace"
    ).encode(y=alt.Y("topo:Q"), text="texto:N")
    return _base_config((barras + textos).properties(height=320, padding={"top": 16}))


def _grafico_destino(decomposicao, rotulos: dict, t: dict):
    """Barras horizontais com rótulos completos e valores nas pontas.

    Substitui o gráfico nativo (que trunca rótulos longos): Altair com
    ``labelLimit=0``, cores calmas — quente-suave para o que foi embora,
    verde-alga para o que sobrou — e o valor escrito ao fim de cada barra.
    """
    linhas = [
        {
            "rotulo": rotulos.get(d.nome, d.nome),
            "valor": float(d.valor),
            "texto": _brl_inteiro(d.valor),
            "tipo": t["foi_embora"],
        }
        for d in decomposicao.deducoes
    ]
    linhas.append(
        {
            "rotulo": t["sobrou"],
            "valor": float(decomposicao.margem_liquida),
            "texto": _brl_inteiro(decomposicao.margem_liquida),
            "tipo": t["sobrou"],
        }
    )
    dados = pd.DataFrame(linhas)
    ordem = dados.sort_values("valor", ascending=False)["rotulo"].tolist()
    base = alt.Chart(dados).encode(
        y=alt.Y(
            "rotulo:N",
            sort=ordem,
            title=None,
            axis=alt.Axis(labelLimit=0, labelFontSize=13, labelColor="#d8e7e5"),
        ),
        x=alt.X(
            "valor:Q",
            title=None,
            axis=alt.Axis(labels=False, grid=False, ticks=False, domain=False),
            scale=alt.Scale(paddingOuter=0.02),
        ),
    )
    barras = base.mark_bar(cornerRadiusEnd=7, height=22).encode(
        color=alt.Color(
            "tipo:N",
            scale=alt.Scale(
                domain=[t["foi_embora"], t["sobrou"]],
                range=["#cf8a70", "#8fd694"],
            ),
            legend=None,
        )
    )
    textos = base.mark_text(
        align="left", dx=8, color="#cfe9e6", fontSize=12.5, font="monospace"
    ).encode(text="texto:N")
    return _base_config(
        (barras + textos).properties(height=len(linhas) * 38, padding={"right": 90})
    )


def _grafico_barras_h(linhas: list[dict], cor: str = TEAL_CALMO):
    """Barras horizontais no estilo da casa: rótulo inteiro, valor na ponta."""
    dados = pd.DataFrame(linhas)
    ordem = dados.sort_values("valor", ascending=False)["rotulo"].tolist()
    base = alt.Chart(dados).encode(
        y=alt.Y(
            "rotulo:N",
            sort=ordem,
            title=None,
            axis=alt.Axis(labelLimit=0, labelFontSize=13, labelColor="#d8e7e5"),
        ),
        x=alt.X(
            "valor:Q",
            title=None,
            axis=alt.Axis(labels=False, grid=False, ticks=False, domain=False),
        ),
    )
    barras = base.mark_bar(cornerRadiusEnd=7, height=22, color=cor)
    textos = base.mark_text(
        align="left", dx=8, color=AGUA_TEXTO, fontSize=12.5, font="monospace"
    ).encode(text="texto:N")
    return _base_config(
        (barras + textos).properties(height=len(linhas) * 38, padding={"right": 90})
    )


def _grafico_barras_v(linhas: list[dict], cor: str = TEAL_CALMO):
    """Barras verticais (ex.: meses) com o valor escrito no topo de cada uma."""
    dados = pd.DataFrame(linhas)
    base = alt.Chart(dados).encode(
        x=alt.X(
            "rotulo:N",
            sort=dados["rotulo"].tolist(),
            title=None,
            axis=alt.Axis(labelAngle=0, labelFontSize=12.5, labelColor="#d8e7e5"),
        ),
        y=alt.Y(
            "valor:Q",
            title=None,
            axis=alt.Axis(labels=False, grid=False, ticks=False, domain=False),
        ),
    )
    barras = base.mark_bar(
        cornerRadiusTopLeft=7, cornerRadiusTopRight=7, size=44, color=cor
    )
    textos = base.mark_text(
        dy=-10, color=AGUA_TEXTO, fontSize=12, font="monospace"
    ).encode(text="texto:N")
    return _base_config((barras + textos).properties(height=280, padding={"top": 16}))


def _grafico_serie(linhas: list[dict], modo: str = "linha"):
    """Linha (ou área) mensal com o valor escrito em cada ponto."""
    dados = pd.DataFrame(linhas)
    base = alt.Chart(dados).encode(
        x=alt.X(
            "rotulo:N",
            sort=dados["rotulo"].tolist(),
            title=None,
            axis=alt.Axis(labelAngle=0, labelFontSize=12.5, labelColor="#d8e7e5"),
        ),
        y=alt.Y(
            "valor:Q",
            title=None,
            scale=alt.Scale(zero=(modo == "area")),
            axis=alt.Axis(labels=False, grid=False, ticks=False, domain=False),
        ),
    )
    ponto = alt.OverlayMarkDef(color=AGUA, size=70)
    if modo == "area":
        gradiente = alt.Gradient(
            gradient="linear",
            stops=[
                alt.GradientStop(color="rgba(46,230,214,0.02)", offset=0),
                alt.GradientStop(color="rgba(46,230,214,0.30)", offset=1),
            ],
            x1=1,
            x2=1,
            y1=1,
            y2=0,
        )
        marca = base.mark_area(
            line={"color": AGUA, "strokeWidth": 2.5}, color=gradiente, point=ponto
        )
    else:
        marca = base.mark_line(color=AGUA, strokeWidth=2.5, point=ponto)
    textos = base.mark_text(
        dy=-15, color=AGUA_TEXTO, fontSize=12, font="monospace"
    ).encode(text="texto:N")
    return _base_config((marca + textos).properties(height=280, padding={"top": 18}))
