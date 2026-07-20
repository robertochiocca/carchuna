"""Motor de crescimento: como faturar mais — com prova, não com promessa.

O espelho do diagnóstico: em vez de "onde a margem morre", responde
"onde crescer rende mais". Três análises calculadas dos próprios dados
do lojista (mesmo padrão OO das regras de detecção):

1. **Mix de canais** — qual canal tem a melhor margem real e quanto
   renderia deslocar vendas para ele;
2. **Precificação** — vendas que saem no prejuízo e o preço mínimo/alvo
   por canal (fórmula fechada, invertendo o próprio motor de margem);
3. **Espaço tributário** — quanto dá para faturar a mais dentro da
   faixa atual do Simples, e onde ficam os marcos que mudam o jogo
   (fim da faixa, sublimite de ICMS/ISS, teto de exclusão).

Honestidade inegociável: a Carchuna mostra ONDE crescer rende mais e
QUANTO cabe — vender mais depende de demanda e execução, e nenhuma
projeção aqui é garantia. Sem previsão de vendas por ML (roadmap
explícito): só aritmética transparente sobre dados reais.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal

from carchuna.margem import (
    ANEXOS_SIMPLES,
    TETO_SIMPLES,
    ConfigTributaria,
    TabelaCustos,
    Transacao,
    aliquota_efetiva_simples,
    decompor_margem,
)
from carchuna.rag.retrieval import Dispositivo, Retriever

# Sublimite estadual do ICMS/ISS dentro do Simples (LC 123/2006, arts. 19-20).
SUBLIMITE_ICMS_ISS = Decimal("3600000")

AVISO_CRESCIMENTO = (
    "A Carchuna calcula onde crescer rende mais com base nos seus números; "
    "vender mais depende de demanda e execução — nenhuma projeção é garantia. "
    "Decisões tributárias: confirme com seu contador antes de agir."
)


@dataclass(frozen=True)
class Oportunidade:
    """Uma alavanca de crescimento com ganho estimado e caminho prático."""

    tipo: str  # "mix_canais" | "precificacao" | "espaco_tributario"
    titulo: str
    ganho_estimado_mensal: Decimal  # R$/mês, com a premissa explícita no texto
    explicacao: str
    base_legal: tuple[Dispositivo, ...]
    caminho_pratico: str
    confianca: str  # "calculado" | "estimado"
    aviso: str = AVISO_CRESCIMENTO


@dataclass
class ParametrosCrescimento:
    """Premissas das análises, editáveis e documentadas."""

    # gap mínimo de margem entre canais para virar oportunidade (p.p.)
    min_gap_canais_pp: Decimal = Decimal("5")
    # fração das vendas do pior canal usada como premissa de deslocamento
    fracao_migracao: Decimal = Decimal("0.10")
    # margem líquida alvo sugerida na reprecificação (fração)
    margem_alvo: Decimal = Decimal("0.10")


def _q2(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(valor: Decimal) -> Decimal:
    return (valor * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def preco_para_margem(
    custo_produto,
    frete,
    canal: str,
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
    margem_alvo: Decimal = Decimal("0"),
) -> Decimal:
    """Preço de venda que entrega a margem alvo — o motor de margem invertido.

    Resolve ``preco × (1 − alíquota − comissão − adquirência − alvo) =
    custo + frete``. Com ``margem_alvo=0`` devolve o preço de equilíbrio
    (abaixo dele, a venda dá prejuízo). Arredonda para CIMA, para a
    margem nunca ficar abaixo do alvo.

    Simplificação documentada: o custo de antecipação (que depende do
    prazo de cada venda) fica fora da fórmula fechada — para vendas a
    prazo antecipadas, considere o preço devolvido como piso.
    """
    tabela = tabela or TabelaCustos()
    custo = Decimal(custo_produto) + Decimal(frete)
    if config.regime == "simples":
        aliquota = aliquota_efetiva_simples(config.rbt12, config.anexo_simples)
    else:  # MEI: DAS fixo mensal não varia com o preço da venda
        aliquota = Decimal("0")
    comissao = tabela.comissao_canal.get(canal, Decimal("0"))
    adquirencia = (
        tabela.taxa_adquirencia
        if canal in tabela.canais_com_adquirencia
        else Decimal("0")
    )
    denominador = Decimal("1") - aliquota - comissao - adquirencia - margem_alvo
    if denominador <= 0:
        raise ValueError(
            f"Margem alvo de {_pct(margem_alvo)}% é inatingível no canal "
            f"{canal!r}: alíquota + comissão + adquirência já consomem "
            f"{_pct(aliquota + comissao + adquirencia)}% do preço."
        )
    return (custo / denominador).quantize(Decimal("0.01"), rounding=ROUND_UP)


@dataclass
class ContextoCrescimento:
    """Entradas pré-calculadas compartilhadas pelas análises."""

    transacoes: list[Transacao]
    config: ConfigTributaria
    tabela: TabelaCustos
    parametros: ParametrosCrescimento
    retriever: Retriever

    @property
    def meses(self) -> int:
        return len({(t.data.year, t.data.month) for t in self.transacoes}) or 1


class AnaliseCrescimento(ABC):
    """Uma análise de crescimento: recebe o contexto, devolve oportunidades."""

    @abstractmethod
    def avaliar(self, ctx: ContextoCrescimento) -> list[Oportunidade]:
        """Lista de oportunidades (vazia quando não há o que apontar)."""


class AnaliseMixCanais(AnaliseCrescimento):
    """Análise 1 — em qual canal cada real vendido rende mais margem."""

    def avaliar(self, ctx: ContextoCrescimento) -> list[Oportunidade]:
        por_canal: dict[str, list[Transacao]] = {}
        for t in ctx.transacoes:
            por_canal.setdefault(t.canal, []).append(t)
        if len(por_canal) < 2:
            return []
        margens = {
            canal: decompor_margem(grupo, ctx.config, ctx.tabela)
            for canal, grupo in por_canal.items()
        }
        melhor = max(margens, key=lambda c: margens[c].margem_pct)
        pior = min(margens, key=lambda c: margens[c].margem_pct)
        gap = margens[melhor].margem_pct - margens[pior].margem_pct
        if gap < ctx.parametros.min_gap_canais_pp:
            return []
        fracao = ctx.parametros.fracao_migracao
        receita_pior = margens[pior].receita_bruta
        ganho = _q2(gap / 100 * receita_pior * fracao / ctx.meses)
        return [
            Oportunidade(
                tipo="mix_canais",
                titulo=f"Cada real vendido em {melhor} rende mais que em {pior}",
                ganho_estimado_mensal=ganho,
                explicacao=(
                    f"Margem real por canal: {melhor} = "
                    f"{margens[melhor].margem_pct}% contra {pior} = "
                    f"{margens[pior].margem_pct}% ({gap} p.p. de diferença). "
                    f"Premissa editável: deslocando {_pct(fracao)}% das vendas "
                    f"de {pior} para {melhor}, sobrariam cerca de "
                    f"R$ {ganho}/mês a mais — mesmo faturamento, mais margem; "
                    "faturando mais no canal certo, o ganho cresce junto."
                ),
                base_legal=(),
                caminho_pratico=(
                    f"Antes de investir em anúncio no {pior}, teste levar os "
                    f"produtos campeões para {melhor} (a aba Cenários simula o "
                    "impacto exato da migração)."
                ),
                confianca="estimado",
            )
        ]


class AnaliseVendasNoPrejuizo(AnaliseCrescimento):
    """Análise 2 — vendas que saem abaixo do custo real (margem negativa)."""

    def avaliar(self, ctx: ContextoCrescimento) -> list[Oportunidade]:
        prejuizo = Decimal("0")
        exemplos: list[Transacao] = []
        for t in ctx.transacoes:
            if t.devolvida:
                continue
            margem = decompor_margem([t], ctx.config, ctx.tabela).margem_liquida
            if margem < 0:
                prejuizo += -margem
                exemplos.append(t)
        if not exemplos:
            return []
        ganho = _q2(prejuizo / ctx.meses)
        pior = max(exemplos, key=lambda t: t.custo_produto + t.frete_pago)
        preco_alvo = preco_para_margem(
            pior.custo_produto,
            pior.frete_pago,
            pior.canal,
            ctx.config,
            ctx.tabela,
            ctx.parametros.margem_alvo,
        )
        return [
            Oportunidade(
                tipo="precificacao",
                titulo=f"{len(exemplos)} venda(s) saíram no prejuízo",
                ganho_estimado_mensal=ganho,
                explicacao=(
                    f"Depois de imposto, comissão, frete e custo, "
                    f"{len(exemplos)} venda(s) tiveram margem NEGATIVA — "
                    f"R$ {ganho}/mês queimados vendendo. Faturar mais com "
                    "esses preços só aumenta o prejuízo: reprecificar é a "
                    "forma mais barata de 'faturar mais'. Exemplo: o item de "
                    f"custo R$ {pior.custo_produto} (+ frete R$ {pior.frete_pago}) "
                    f"em {pior.canal} precisaria sair por R$ {preco_alvo} para "
                    f"deixar {_pct(ctx.parametros.margem_alvo)}% de margem."
                ),
                base_legal=(),
                caminho_pratico=(
                    "Use a calculadora de preço (aba Crescimento) para achar o "
                    "preço mínimo e o preço alvo de cada produto por canal; "
                    "suba o preço ou corte o item do catálogo."
                ),
                confianca="calculado",
            )
        ]


class AnaliseEspacoSimples(AnaliseCrescimento):
    """Análise 3 — quanto dá para crescer dentro do Simples, e a que custo."""

    def avaliar(self, ctx: ContextoCrescimento) -> list[Oportunidade]:
        if ctx.config.regime != "simples":
            return []
        rbt12 = ctx.config.rbt12
        anexo = ctx.config.anexo_simples
        limite_faixa = next(
            limite for limite, _, _ in ANEXOS_SIMPLES[anexo] if rbt12 <= limite
        )
        espaco_faixa = limite_faixa - rbt12
        efetiva_hoje = aliquota_efetiva_simples(rbt12, anexo)
        efetiva_fim = aliquota_efetiva_simples(limite_faixa, anexo)
        base_legal = ctx.retriever.buscar(
            "limite teto sublimite exclusão faixa alíquota simples"
        )
        partes = [
            f"Sua RBT12 é R$ {rbt12}. Dentro da faixa atual do Anexo {anexo} "
            f"ainda cabem R$ {espaco_faixa} de faturamento; nesse trajeto a "
            f"alíquota efetiva sobe gradualmente de {_pct(efetiva_hoje)}% para "
            f"{_pct(efetiva_fim)}% — crescer não 'estoura' o imposto de uma "
            "vez (a progressividade é suave dentro da faixa)."
        ]
        if rbt12 < SUBLIMITE_ICMS_ISS:
            partes.append(
                f"Marcos à frente: em R$ {SUBLIMITE_ICMS_ISS} o ICMS/ISS saem "
                "da guia única (arts. 19-20) e em "
                f"R$ {TETO_SIMPLES} vem a exclusão do regime (art. 3º, II) — "
                "planeje ambos com antecedência."
            )
        else:
            partes.append(
                f"Você já passou do sublimite de R$ {SUBLIMITE_ICMS_ISS} "
                "(ICMS/ISS por fora); o próximo marco é o teto de "
                f"R$ {TETO_SIMPLES}, quando ocorre a exclusão do regime."
            )
        return [
            Oportunidade(
                tipo="espaco_tributario",
                titulo="Quanto cabe crescer dentro do Simples",
                ganho_estimado_mensal=_q2(espaco_faixa / 12),
                explicacao=" ".join(partes),
                base_legal=tuple(base_legal),
                caminho_pratico=(
                    "O número do título é o espaço da faixa dividido por 12 "
                    "(ritmo mensal que mantém você na faixa atual por um ano). "
                    "Perto do teto, discuta com o contador o momento certo de "
                    "planejar a transição de regime — antes de a Receita "
                    "decidir por você."
                ),
                confianca="calculado",
            )
        ]


class MotorCrescimento:
    """Orquestra as análises de crescimento (mesmo padrão do diagnóstico)."""

    def __init__(
        self,
        retriever: Retriever | None = None,
        parametros: ParametrosCrescimento | None = None,
        analises: tuple[AnaliseCrescimento, ...] | None = None,
    ):
        self.retriever = retriever or Retriever()
        self.parametros = parametros or ParametrosCrescimento()
        self.analises = (
            analises
            if analises is not None
            else (
                AnaliseMixCanais(),
                AnaliseVendasNoPrejuizo(),
                AnaliseEspacoSimples(),
            )
        )

    def sugerir(
        self,
        transacoes: list[Transacao],
        config: ConfigTributaria,
        tabela: TabelaCustos | None = None,
    ) -> list[Oportunidade]:
        """Roda as análises e devolve oportunidades por ganho decrescente."""
        if not transacoes:
            raise ValueError("`transacoes` não pode ser vazio.")
        ctx = ContextoCrescimento(
            transacoes=transacoes,
            config=config,
            tabela=tabela or TabelaCustos(),
            parametros=self.parametros,
            retriever=self.retriever,
        )
        oportunidades: list[Oportunidade] = []
        for analise in self.analises:
            oportunidades.extend(analise.avaliar(ctx))
        return sorted(
            oportunidades, key=lambda o: o.ganho_estimado_mensal, reverse=True
        )
