"""Métricas da margem ao longo do tempo.

Tradução das métricas de risco da Calahonda para o mundo do lojista:

- curva de patrimônio → **curva de lucro acumulado**;
- drawdown → **maior queda de margem** (em pontos percentuais desde o
  melhor mês);
- volatilidade → **instabilidade da margem** (desvio-padrão da margem
  mensal).

Tudo em ``Decimal`` e Python puro; a decomposição de cada mês é feita
pelo próprio ``decompor_margem``, então cada número da série herda as
fontes das deduções.

Simplificação documentada da v1: a mesma ``ConfigTributaria`` (mesma
RBT12) é usada em todos os meses da série; a RBT12 móvel mês a mês está
no roadmap.
"""

from __future__ import annotations

from decimal import Decimal

from carchuna.margem import (
    ConfigTributaria,
    DecomposicaoMargem,
    TabelaCustos,
    Transacao,
    decompor_margem,
)


def margem_mensal(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
) -> dict[str, DecomposicaoMargem]:
    """Decomposição completa da margem para cada mês ("AAAA-MM"), em ordem."""
    if not transacoes:
        raise ValueError("`transacoes` não pode ser vazio.")
    por_mes: dict[str, list[Transacao]] = {}
    for t in transacoes:
        por_mes.setdefault(f"{t.data.year:04d}-{t.data.month:02d}", []).append(t)
    return {
        mes: decompor_margem(grupo, config, tabela)
        for mes, grupo in sorted(por_mes.items())
    }


def serie_margem_pct(
    decomposicoes: dict[str, DecomposicaoMargem],
) -> list[tuple[str, Decimal]]:
    """Série (mês, margem %) a partir de ``margem_mensal``."""
    return [(mes, d.margem_pct) for mes, d in decomposicoes.items()]


def maior_queda_margem(serie: list[tuple[str, Decimal]]) -> Decimal:
    """Maior queda da margem, em pontos percentuais, desde o melhor mês anterior.

    Análogo do máximo drawdown da Calahonda: percorre a série guardando o
    pico e mede a maior distância pico → vale. Devolve um valor >= 0
    (``Decimal("4.20")`` = a margem já caiu 4,2 p.p. do topo).
    """
    if not serie:
        raise ValueError("`serie` não pode ser vazia.")
    pico = serie[0][1]
    maior_queda = Decimal("0")
    for _, margem in serie:
        pico = max(pico, margem)
        maior_queda = max(maior_queda, pico - margem)
    return maior_queda


def instabilidade_margem(serie: list[tuple[str, Decimal]]) -> Decimal:
    """Desvio-padrão (amostral) da margem mensal, em pontos percentuais.

    Margem estável ≈ 0; margem que oscila muito entre meses = número
    alto. É a "volatilidade" da Calahonda no vocabulário do lojista.
    """
    if len(serie) < 2:
        raise ValueError("`serie` precisa de pelo menos 2 meses.")
    valores = [margem for _, margem in serie]
    n = Decimal(len(valores))
    media = sum(valores) / n
    variancia = sum((v - media) ** 2 for v in valores) / (n - 1)
    return variancia.sqrt().quantize(Decimal("0.01"))


def lucro_acumulado(
    decomposicoes: dict[str, DecomposicaoMargem],
) -> list[tuple[str, Decimal]]:
    """Curva de lucro acumulado: soma corrente da margem líquida mensal."""
    if not decomposicoes:
        raise ValueError("`decomposicoes` não pode ser vazio.")
    acumulado = Decimal("0")
    curva = []
    for mes, d in decomposicoes.items():
        acumulado += d.margem_liquida
        curva.append((mes, acumulado))
    return curva
