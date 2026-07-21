"""Detector de vazamentos de margem — o radar do CFO virtual.

Insights gerados automaticamente dos dados do lojista, com severidade
explícita e impacto calculado pelo próprio motor de margem:

- **Tendência de custos** — uma dedução subiu como % da receita entre o
  primeiro e o último mês ("suas comissões subiram 8 p.p. em 3 meses");
- **Produtos de margem magra** — itens com margem positiva porém abaixo
  do limiar, com o ganho EXATO de um reajuste de preço simulado pelo
  motor (mesmo volume — premissa explícita);
- **Mês fora do padrão** — a margem do último mês desvia mais de 2
  desvios-padrão do histórico (precisa de 4+ meses).

Mesmo padrão OO das regras de diagnóstico: cada análise é uma classe;
estender = herdar e registrar. Heurísticas transparentes, sem ML — e
nenhuma promessa: severidade é sinal de atenção, não veredito.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal

from carchuna.margem import (
    ROTULOS_DEDUCOES,
    ConfigTributaria,
    TabelaCustos,
    Transacao,
    decompor_margem,
)
from carchuna.metricas import margem_mensal

AVISO_INSIGHTS = (
    "Insights calculados dos seus números por regras transparentes — são "
    "sinais para investigar, não veredito. Confirme causas antes de agir."
)

SEVERIDADES = ("critico", "atencao", "oportunidade")


@dataclass(frozen=True)
class Insight:
    """Um sinal do radar: severidade, impacto e o que fazer a respeito."""

    severidade: str  # "critico" | "atencao" | "oportunidade"
    titulo: str
    impacto_mensal: Decimal  # R$/mês
    explicacao: str
    caminho_pratico: str
    confianca: str  # "calculado" | "estimado"
    # Qual análise gerou o sinal — usada pelo motor de decisão para achar
    # o perfil da ação no catálogo (decisao.CATALOGO_ACOES).
    categoria: str = ""
    aviso: str = AVISO_INSIGHTS


@dataclass
class ParametrosInsights:
    """Limiar de cada análise, editável e documentado."""

    # alta de dedução (em p.p. da receita) que vira atenção / crítico
    tendencia_atencao_pp: Decimal = Decimal("1.5")
    tendencia_critico_pp: Decimal = Decimal("3")
    # margem de produto abaixo disto (e >= 0) é "magra"
    margem_magra_pct: Decimal = Decimal("8")
    # reajuste simulado nos produtos magros
    reajuste_simulado: Decimal = Decimal("0.05")
    # desvios-padrão para o mês fora do padrão
    desvios_anomalia: Decimal = Decimal("2")


def _q2(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class ContextoInsights:
    transacoes: list[Transacao]
    config: ConfigTributaria
    tabela: TabelaCustos
    parametros: ParametrosInsights

    @property
    def mensal(self):
        return margem_mensal(self.transacoes, self.config, self.tabela)


class AnaliseInsight(ABC):
    @abstractmethod
    def avaliar(self, ctx: ContextoInsights) -> list[Insight]:
        """Lista de insights (vazia quando não há sinal)."""


class TendenciaCustos(AnaliseInsight):
    """Deduções que cresceram como fatia da receita entre os meses."""

    def avaliar(self, ctx: ContextoInsights) -> list[Insight]:
        mensal = list(ctx.mensal.items())
        if len(mensal) < 2:
            return []
        (mes_a, dec_a), (mes_b, dec_b) = mensal[0], mensal[-1]
        insights = []
        for deducao in dec_b.deducoes:
            delta = deducao.pct_receita - dec_a.deducao(deducao.nome).pct_receita
            if delta < ctx.parametros.tendencia_atencao_pp:
                continue
            severidade = (
                "critico" if delta >= ctx.parametros.tendencia_critico_pp else "atencao"
            )
            impacto = _q2(delta / 100 * dec_b.receita_bruta)
            rotulo = ROTULOS_DEDUCOES.get(deducao.nome, deducao.nome)
            insights.append(
                Insight(
                    severidade=severidade,
                    titulo=f"{rotulo} subiu {delta} p.p. entre {mes_a} e {mes_b}",
                    impacto_mensal=impacto,
                    explicacao=(
                        f"{rotulo} consumia "
                        f"{dec_a.deducao(deducao.nome).pct_receita}% da receita em "
                        f"{mes_a} e passou a consumir {deducao.pct_receita}% em "
                        f"{mes_b}. No faturamento do último mês, essa alta "
                        f"equivale a R$ {impacto}/mês de lucro a menos."
                    ),
                    caminho_pratico=(
                        "Abra o detalhamento desta dedução por canal e por mês "
                        "(clique na barra do raio-X) para localizar a origem da "
                        "alta antes de renegociar ou reprecificar."
                    ),
                    confianca="calculado",
                    categoria="tendencia_custos",
                )
            )
        return insights


class ProdutosMargemMagra(AnaliseInsight):
    """Produtos com margem positiva porém magra, e o ganho de um reajuste."""

    def avaliar(self, ctx: ContextoInsights) -> list[Insight]:
        por_produto: dict[str, list[Transacao]] = {}
        for t in ctx.transacoes:
            por_produto.setdefault(t.produto or t.canal, []).append(t)
        magros: list[str] = []
        margem_magros = Decimal("0")
        for nome, grupo in por_produto.items():
            d = decompor_margem(grupo, ctx.config, ctx.tabela)
            if Decimal("0") <= d.margem_pct < ctx.parametros.margem_magra_pct:
                magros.append(nome)
                margem_magros += d.margem_liquida
        if not magros:
            return []

        reajuste = ctx.parametros.reajuste_simulado
        alvo = set(magros)
        ajustadas = [
            (
                replace(
                    t,
                    valor_bruto=_q2(t.valor_bruto * (1 + reajuste)),
                    comissao_cobrada=(
                        _q2(t.comissao_cobrada * (1 + reajuste))
                        if t.comissao_cobrada is not None
                        else None
                    ),
                )
                if (t.produto or t.canal) in alvo
                else t
            )
            for t in ctx.transacoes
        ]
        base = decompor_margem(ctx.transacoes, ctx.config, ctx.tabela)
        novo = decompor_margem(ajustadas, ctx.config, ctx.tabela)
        meses = len({(t.data.year, t.data.month) for t in ctx.transacoes}) or 1
        ganho = _q2((novo.margem_liquida - base.margem_liquida) / meses)
        pct = (reajuste * 100).quantize(Decimal("1"))
        limiar = ctx.parametros.margem_magra_pct
        return [
            Insight(
                severidade="oportunidade",
                titulo=(f"{len(magros)} produto(s) com margem abaixo de {limiar}%"),
                impacto_mensal=ganho,
                explicacao=(
                    f"Estes produtos vendem sem prejuízo, mas deixam pouco: "
                    f"{', '.join(sorted(magros)[:5])}"
                    f"{'…' if len(magros) > 5 else ''}. Um reajuste de {pct}% "
                    f"nos preços deles — mantido o mesmo volume (premissa) — "
                    f"adicionaria cerca de R$ {ganho}/mês de lucro, recalculado "
                    "pelo motor com imposto e comissão sobre o preço novo."
                ),
                caminho_pratico=(
                    "Use a calculadora de preço (aba Crescer) para achar o "
                    "preço-alvo de cada um; teste o reajuste nos campeões de "
                    "venda primeiro."
                ),
                confianca="calculado",
                categoria="margem_magra",
            )
        ]


class MesForaDoPadrao(AnaliseInsight):
    """Margem do último mês desviando 2σ+ do histórico (4+ meses)."""

    def avaliar(self, ctx: ContextoInsights) -> list[Insight]:
        mensal = list(ctx.mensal.items())
        if len(mensal) < 4:
            return []
        historico = [d.margem_pct for _, d in mensal[:-1]]
        mes_atual, dec_atual = mensal[-1]
        n = Decimal(len(historico))
        media = sum(historico) / n
        variancia = sum((v - media) ** 2 for v in historico) / (n - 1)
        desvio = variancia.sqrt()
        if desvio == 0:
            return []
        afastamento = abs(dec_atual.margem_pct - media) / desvio
        if afastamento <= ctx.parametros.desvios_anomalia:
            return []
        delta = dec_atual.margem_pct - media
        impacto = _q2(abs(delta) / 100 * dec_atual.receita_bruta)
        direcao = "abaixo" if delta < 0 else "acima"
        return [
            Insight(
                severidade="atencao" if delta < 0 else "oportunidade",
                titulo=f"Margem de {mes_atual} fora do padrão histórico",
                impacto_mensal=impacto,
                explicacao=(
                    f"A margem de {mes_atual} ({dec_atual.margem_pct}%) ficou "
                    f"{direcao} do padrão dos meses anteriores (média "
                    f"{media.quantize(Decimal('0.01'))}%), um desvio de "
                    f"{afastamento.quantize(Decimal('0.1'))}σ — cerca de "
                    f"R$ {impacto} no mês. Vale investigar o que mudou."
                ),
                caminho_pratico=(
                    "Compare o mês na aba Histórico: a frase de comparação "
                    "aponta qual dedução mais mudou."
                ),
                confianca="estimado",
                categoria="mes_fora_padrao",
            )
        ]


class MotorInsights:
    """Orquestra as análises do radar (mesmo padrão do diagnóstico)."""

    def __init__(
        self,
        parametros: ParametrosInsights | None = None,
        analises: tuple[AnaliseInsight, ...] | None = None,
    ):
        self.parametros = parametros or ParametrosInsights()
        self.analises = (
            analises
            if analises is not None
            else (TendenciaCustos(), ProdutosMargemMagra(), MesForaDoPadrao())
        )

    def radar(
        self,
        transacoes: list[Transacao],
        config: ConfigTributaria,
        tabela: TabelaCustos | None = None,
    ) -> list[Insight]:
        """Insights ordenados por severidade e impacto."""
        if not transacoes:
            raise ValueError("`transacoes` não pode ser vazio.")
        ctx = ContextoInsights(
            transacoes=transacoes,
            config=config,
            tabela=tabela or TabelaCustos(),
            parametros=self.parametros,
        )
        insights: list[Insight] = []
        for analise in self.analises:
            insights.extend(analise.avaliar(ctx))
        ordem = {s: i for i, s in enumerate(SEVERIDADES)}
        return sorted(
            insights,
            key=lambda i: (ordem[i.severidade], -i.impacto_mensal),
        )
