"""Nota de confiança explicável — quanto dá para confiar em cada conclusão.

Nada de número mágico: a nota é a soma de quatro componentes com rubrica
fixa e documentada, e cada componente carrega o motivo em texto. O
objetivo é separar com clareza:

- **"Os dados mostram isso."** — evidência calculada dos próprios dados
  e da lei/tabela, com histórico e amostra suficientes;
- **"Esta é uma hipótese possível."** — conclusão apoiada em premissa,
  taxa média editável ou evidência ainda magra.

Rubrica (máximo 100 pontos):

===============  ====  =====================================================
Componente       Máx.  Regra
===============  ====  =====================================================
evidência          40  ``calculado`` (dados + lei/tabela) = 40;
                       ``estimado`` (premissa/taxa média editável) = 25
histórico          20  meses distintos: ≥12 → 20 · ≥6 → 15 · ≥3 → 10 ·
                       2 → 6 · 1 → 3
amostra            20  vendas na base: ≥200 → 20 · ≥50 → 15 · ≥12 → 10 ·
                       ≥1 → 5
completude         20  média das frações de campos opcionais presentes
                       (comissão real do extrato, produto identificado,
                       prazo de recebimento informado) × 20
===============  ====  =====================================================

Níveis: ≥80 alta · ≥55 média · <55 baixa.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from carchuna.margem import Transacao

NIVEIS = ("alta", "media", "baixa")

FRASE_DADOS = "Os dados mostram isso."
FRASE_HIPOTESE = "Esta é uma hipótese possível — confirme antes de agir."


@dataclass(frozen=True)
class ComponenteConfianca:
    """Uma parcela da nota: nome, pontos obtidos, máximo e o porquê."""

    nome: str
    pontos: int
    maximo: int
    motivo: str


@dataclass(frozen=True)
class NotaConfianca:
    """A confiança de uma conclusão, decomposta em componentes com motivo."""

    pct: int  # 0–100, soma dos componentes
    nivel: str  # "alta" | "media" | "baixa"
    componentes: tuple[ComponenteConfianca, ...]

    @property
    def motivos(self) -> tuple[str, ...]:
        return tuple(c.motivo for c in self.componentes)

    @property
    def frase(self) -> str:
        """Dados mostram × hipótese: evidência calculada E nota ≥ 70."""
        evidencia = next(c for c in self.componentes if c.nome == "evidencia")
        if evidencia.pontos == 40 and self.pct >= 70:
            return FRASE_DADOS
        return FRASE_HIPOTESE


def _pontos_historico(meses: int) -> tuple[int, str]:
    if meses >= 12:
        pontos = 20
    elif meses >= 6:
        pontos = 15
    elif meses >= 3:
        pontos = 10
    elif meses == 2:
        pontos = 6
    else:
        pontos = 3
    return pontos, f"{meses} mês(es) de histórico na base"


def _pontos_amostra(n: int) -> tuple[int, str]:
    if n >= 200:
        pontos = 20
    elif n >= 50:
        pontos = 15
    elif n >= 12:
        pontos = 10
    else:
        pontos = 5
    return pontos, f"{n} venda(s) na base"


def _pontos_completude(transacoes: list[Transacao]) -> tuple[int, str]:
    n = Decimal(len(transacoes))
    com_comissao = sum(1 for t in transacoes if t.comissao_cobrada is not None)
    com_produto = sum(1 for t in transacoes if t.produto)
    com_prazo = sum(1 for t in transacoes if t.prazo_recebimento_dias > 0)
    fracao = (Decimal(com_comissao) + com_produto + com_prazo) / (3 * n)
    pontos = int((fracao * 20).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    pct = (fracao * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    detalhe = (
        f"{pct}% dos campos opcionais preenchidos (comissão real: "
        f"{com_comissao}/{n}, produto: {com_produto}/{n}, prazo: {com_prazo}/{n})"
    )
    return pontos, detalhe


def avaliar_confianca(
    transacoes: list[Transacao],
    base: str = "calculado",
) -> NotaConfianca:
    """Nota de confiança pela rubrica documentada no módulo.

    ``base`` é a natureza da evidência da conclusão sendo avaliada:
    ``"calculado"`` (sai dos dados e da lei/tabela) ou ``"estimado"``
    (depende de premissa ou taxa média editável).
    """
    if not transacoes:
        raise ValueError("`transacoes` não pode ser vazio.")
    if base not in ("calculado", "estimado"):
        raise ValueError(f"base {base!r} inválida; use 'calculado' ou 'estimado'.")

    if base == "calculado":
        evidencia = ComponenteConfianca(
            "evidencia", 40, 40, "evidência calculada dos seus dados e da lei/tabela"
        )
    else:
        evidencia = ComponenteConfianca(
            "evidencia", 25, 40, "evidência apoiada em premissa ou taxa média editável"
        )

    meses = len({(t.data.year, t.data.month) for t in transacoes})
    p_hist, m_hist = _pontos_historico(meses)
    p_amostra, m_amostra = _pontos_amostra(len(transacoes))
    p_comp, m_comp = _pontos_completude(transacoes)

    componentes = (
        evidencia,
        ComponenteConfianca("historico", p_hist, 20, m_hist),
        ComponenteConfianca("amostra", p_amostra, 20, m_amostra),
        ComponenteConfianca("completude", p_comp, 20, m_comp),
    )
    pct = sum(c.pontos for c in componentes)
    nivel = "alta" if pct >= 80 else "media" if pct >= 55 else "baixa"
    return NotaConfianca(pct=pct, nivel=nivel, componentes=componentes)
