"""Relatório em PDF de 3 páginas (matplotlib, padrão da Calahonda).

Página 1 — raio-X da margem: cascata da receita bruta até a margem
líquida, com fonte de cada dedução. Página 2 — cenários de stress.
Página 3 — achados do diagnóstico com base legal citada.

Requer ``matplotlib`` (extra opcional ``viz``); todo o resto do pacote
funciona sem ele — degradação graciosa.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from carchuna.cenarios import ResultadoCenario
from carchuna.diagnostico import Achado
from carchuna.margem import DecomposicaoMargem
from carchuna.rag.retrieval import AVISO_LEGAL

# Paleta "águas de Carchuna": mar transparente, areia e alerta.
AZUL_MAR = "#0e7c86"
AZUL_FUNDO = "#083f47"
AREIA = "#e8dcc3"
CORAL = "#e4572e"
VERDE_ALGA = "#7fb069"
CINZA_TEXTO = "#2f3e46"

_ROTULOS = {
    "tributos": "Tributos (Simples/MEI)",
    "comissoes_canal": "Comissões de canal",
    "adquirencia": "Adquirência",
    "antecipacao": "Antecipação",
    "frete": "Frete",
    "devolucoes": "Devoluções",
    "cmv": "CMV (custo do produto)",
}


def _brl(valor: Decimal) -> str:
    inteiro, _, centavos = f"{valor:.2f}".partition(".")
    sinal = "-" if inteiro.startswith("-") else ""
    inteiro = inteiro.lstrip("-")
    grupos = []
    while inteiro:
        grupos.append(inteiro[-3:])
        inteiro = inteiro[:-3]
    return f"{sinal}R$ {'.'.join(reversed(grupos))},{centavos}"


def gerar_pdf_relatorio(
    decomposicao: DecomposicaoMargem,
    cenarios: list[ResultadoCenario],
    achados: list[Achado],
    output,
    titulo: str = "Raio-X da Margem — Carchuna",
    narrativa: str | None = None,
):
    """Gera o relatório em PDF e devolve o destino (caminho ou buffer).

    Parameters
    ----------
    decomposicao : DecomposicaoMargem
        Resultado de ``decompor_margem`` do período analisado.
    cenarios : list[ResultadoCenario]
        Saída de ``rodar_cenarios_padrao`` (pode ser vazia).
    achados : list[Achado]
        Saída de ``diagnosticar`` (pode ser vazia).
    output : str | Path | file-like
        Caminho do PDF ou buffer (ex.: ``io.BytesIO`` para download).
    narrativa : str | None
        Parágrafo opcional gerado pela camada LLM; ``None`` omite (o
        relatório completo nunca depende de LLM).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    plt.rcParams.update(
        {
            "font.size": 9,
            "text.color": CINZA_TEXTO,
            "axes.edgecolor": CINZA_TEXTO,
            "axes.labelcolor": CINZA_TEXTO,
            "xtick.color": CINZA_TEXTO,
            "ytick.color": CINZA_TEXTO,
        }
    )

    with PdfPages(output) as pdf:
        _pagina_margem(plt, pdf, decomposicao, titulo, narrativa)
        _pagina_cenarios(plt, pdf, cenarios)
        _pagina_achados(plt, pdf, achados)
    return output


def _pagina_margem(plt, pdf, d: DecomposicaoMargem, titulo, narrativa):
    fig, (ax_topo, ax) = plt.subplots(
        2, 1, figsize=(8.27, 11.69), height_ratios=[1, 2.2]
    )
    fig.suptitle(titulo, fontsize=16, fontweight="bold", color=AZUL_FUNDO, y=0.97)

    ax_topo.axis("off")
    resumo = (
        f"Receita bruta do período: {_brl(d.receita_bruta)}\n"
        f"Margem líquida: {_brl(d.margem_liquida)}  ({d.margem_pct}% da receita)\n"
        + (
            f"Alíquota efetiva do Simples: "
            f"{(d.aliquota_efetiva * 100).quantize(Decimal('0.0001'))}%\n"
            if d.aliquota_efetiva is not None
            else ""
        )
        + f"Gerado em {date.today().isoformat()} · números calculados por código "
        "testado; fontes de cada dedução na tabela do repositório."
    )
    ax_topo.text(0, 0.75, resumo, fontsize=11, va="top", linespacing=1.8)
    if narrativa:
        ax_topo.text(
            0,
            0.18,
            "\n".join(_quebrar(narrativa, 100)),
            fontsize=8.5,
            va="top",
            style="italic",
        )

    nomes = ["Receita bruta"] + [_ROTULOS.get(x.nome, x.nome) for x in d.deducoes]
    nomes += ["Margem líquida"]
    valores = [float(d.receita_bruta)]
    valores += [-float(x.valor) for x in d.deducoes]
    valores += [float(d.margem_liquida)]
    cores = [AZUL_MAR] + [CORAL] * len(d.deducoes) + [VERDE_ALGA]

    posicoes = range(len(nomes))
    ax.barh(posicoes, valores, color=cores)
    ax.set_yticks(posicoes, nomes)
    ax.invert_yaxis()
    ax.set_xlabel("R$ (barras negativas = deduções)")
    ax.set_title("Onde a receita vira (ou deixa de virar) lucro", color=AZUL_FUNDO)
    for i, v in enumerate(valores):
        ax.text(
            v,
            i,
            f" {_brl(Decimal(str(round(v, 2))))}",
            va="center",
            ha="left" if v >= 0 else "right",
            fontsize=8,
        )
    ax.margins(x=0.25)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    pdf.savefig(fig)
    plt.close(fig)


def _pagina_cenarios(plt, pdf, cenarios: list[ResultadoCenario]):
    fig, ax = plt.subplots(figsize=(8.27, 11.69))
    fig.suptitle(
        "Cenários de stress — e se o custo subir?",
        fontsize=14,
        fontweight="bold",
        color=AZUL_FUNDO,
        y=0.97,
    )
    if not cenarios:
        ax.axis("off")
        ax.text(0.5, 0.5, "Nenhum cenário calculado.", ha="center")
    else:
        nomes = ["\n".join(_quebrar(c.nome, 28)) for c in cenarios]
        impactos = [float(c.impacto_reais) for c in cenarios]
        ax.bar(range(len(cenarios)), impactos, color=CORAL, width=0.55)
        ax.set_xticks(range(len(cenarios)), nomes, fontsize=8)
        ax.axhline(0, color=CINZA_TEXTO, linewidth=0.8)
        ax.set_ylabel("Impacto na margem líquida do período (R$)")
        for i, c in enumerate(cenarios):
            ax.text(
                i,
                impactos[i],
                f"{_brl(c.impacto_reais)}\n({c.impacto_pp:+.2f} p.p.)",
                ha="center",
                va="top" if impactos[i] < 0 else "bottom",
                fontsize=8,
            )
        ax.set_title(
            "Mesmo motor de cálculo do raio-X, com o parâmetro chocado",
            fontsize=9,
            color=CINZA_TEXTO,
        )
    fig.tight_layout(rect=(0, 0.02, 1, 0.93))
    pdf.savefig(fig)
    plt.close(fig)


def _pagina_achados(plt, pdf, achados: list[Achado]):
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.suptitle(
        "Diagnóstico legal — indícios com base citada",
        fontsize=14,
        fontweight="bold",
        color=AZUL_FUNDO,
        y=0.97,
    )
    ax = fig.add_axes((0.07, 0.05, 0.86, 0.86))
    ax.axis("off")
    if not achados:
        linhas = ["Nenhum vazamento detectado pelas regras da v1 — bom sinal."]
    else:
        linhas = []
        for i, a in enumerate(achados, 1):
            linhas.append(
                f"{i}. {a.titulo}  ·  ~{_brl(a.impacto_mensal)}/mês  "
                f"[{a.confianca}, {a.tipo}]"
            )
            linhas += ["   " + s for s in _quebrar(a.explicacao, 95)]
            for disp in a.base_legal[:3]:
                linhas.append(f"   ⚖ {disp.lei}, {disp.artigo}")
                linhas.append(f"      {disp.fonte}")
            linhas += ["   → " + s for s in _quebrar(a.caminho_pratico, 92)]
            linhas.append("")
    linhas.append("")
    linhas += _quebrar(f"Aviso: {AVISO_LEGAL}", 100)
    ax.text(0, 1, "\n".join(linhas), va="top", fontsize=8.2, linespacing=1.55)
    pdf.savefig(fig)
    plt.close(fig)


def _quebrar(texto: str, largura: int) -> list[str]:
    palavras = texto.split()
    linhas, atual = [], ""
    for p in palavras:
        if len(atual) + len(p) + 1 > largura:
            linhas.append(atual)
            atual = p
        else:
            atual = f"{atual} {p}".strip()
    if atual:
        linhas.append(atual)
    return linhas
