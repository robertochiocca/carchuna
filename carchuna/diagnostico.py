"""Diagnóstico: o casamento do motor numérico com o motor legal.

Cada vazamento de margem detectado pelo ``margem.py`` vira um
``Achado``: impacto mensal calculado (reproduzível), explicação na
língua do lojista, base legal restrita ao que o ``Retriever`` recuperou
do corpus, um caminho prático e o nível de confiança sempre explícito
("calculado" ou "estimado").

Organização orientada a objetos (padrão DireitoAberto): cada regra é uma
classe :class:`RegraDeteccao` com uma única responsabilidade — avaliar o
contexto e devolver achados — e o :class:`MotorDiagnostico` orquestra as
regras registradas. Para adicionar uma regra nova, herde de
``RegraDeteccao`` e inclua-a na lista do motor; nada mais muda.

As regras da v1 são heurísticas transparentes — não há ML nem caixa
preta; cada limiar tem default documentado e é editável pelo chamador.
A Carchuna aponta indícios; quem decide é o lojista com o contador ou
advogado dele (aviso em toda resposta, padrão DireitoAberto).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from carchuna.margem import (
    ConfigTributaria,
    DecomposicaoMargem,
    TabelaCustos,
    Transacao,
    aliquota_efetiva_simples,
    decompor_margem,
)
from carchuna.rag.retrieval import AVISO_LEGAL, Dispositivo, Retriever

# Anexo esperado por tipo de atividade (LC 123/2006, art. 18, §§ 4º e ss.):
# revenda → Anexo I; industrialização própria → Anexo II; serviços → III/IV/V.
ANEXO_POR_ATIVIDADE: dict[str, tuple[str, ...]] = {
    "comercio": ("I",),
    "industria": ("II",),
    "servicos": ("III", "IV", "V"),
}

# Mediana de mercado da taxa mensal de antecipação usada como régua da
# regra 2. Default ESTIMADO e editável: desde o registro de recebíveis
# (Resolução CMN 4.734/2019) as taxas são negociáveis e variam por perfil;
# calibre com cotações reais do seu caso.
MEDIANA_ANTECIPACAO_MENSAL = Decimal("0.016")

# Limiar da regra 3: devoluções acima deste % da receita merecem atenção
# (default estimado a partir de taxas típicas de e-commerce; editável).
LIMIAR_DEVOLUCOES = Decimal("0.03")


@dataclass(frozen=True)
class Achado:
    """Um vazamento de margem com impacto calculado e base legal citada."""

    tipo: str  # "tributario" | "contratual" | "financeiro" | "operacional"
    titulo: str
    impacto_mensal: Decimal  # R$/mês, reproduzível a partir dos dados
    explicacao: str  # linguagem do lojista
    base_legal: tuple[Dispositivo, ...]  # APENAS o que o Retriever recuperou
    caminho_pratico: str  # próximo passo concreto
    confianca: str  # "calculado" | "estimado" — sempre explícito
    aviso: str = AVISO_LEGAL


@dataclass
class ParametrosDiagnostico:
    """Limiar de cada regra, editável e com default documentado."""

    atividade: str = "comercio"  # "comercio" | "industria" | "servicos"
    mediana_antecipacao_mensal: Decimal = MEDIANA_ANTECIPACAO_MENSAL
    limiar_devolucoes: Decimal = LIMIAR_DEVOLUCOES
    # Divergência mínima (R$/mês) entre comissão cobrada e tabela pública
    # para gerar achado — evita ruído de arredondamento.
    tolerancia_comissao: Decimal = Decimal("50")

    def __post_init__(self):
        if self.atividade not in ANEXO_POR_ATIVIDADE:
            raise ValueError(
                f"atividade {self.atividade!r} inválida; "
                f"use uma de {sorted(ANEXO_POR_ATIVIDADE)}."
            )


def _q2(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class ContextoDiagnostico:
    """Tudo que uma regra precisa para avaliar um caso, já pré-calculado."""

    transacoes: list[Transacao]
    config: ConfigTributaria
    tabela: TabelaCustos
    parametros: ParametrosDiagnostico
    retriever: Retriever
    decomposicao: DecomposicaoMargem

    @property
    def meses(self) -> int:
        return len({(t.data.year, t.data.month) for t in self.transacoes}) or 1


class RegraDeteccao(ABC):
    """Uma heurística de detecção: recebe o contexto, devolve achados."""

    @abstractmethod
    def avaliar(self, ctx: ContextoDiagnostico) -> list[Achado]:
        """Lista de achados (vazia quando a regra não dispara)."""


class RegraAnexoErrado(RegraDeteccao):
    """Regra 1 — anexo do Simples incompatível com a atividade declarada."""

    def avaliar(self, ctx: ContextoDiagnostico) -> list[Achado]:
        if ctx.config.regime != "simples":
            return []
        esperados = ANEXO_POR_ATIVIDADE[ctx.parametros.atividade]
        if ctx.config.anexo_simples in esperados:
            return []

        atual = aliquota_efetiva_simples(ctx.config.rbt12, ctx.config.anexo_simples)
        esperado = esperados[0]
        correta = aliquota_efetiva_simples(ctx.config.rbt12, esperado)
        base = (
            ctx.decomposicao.receita_bruta
            - ctx.decomposicao.deducao("devolucoes").valor
        )
        impacto_mensal = _q2((atual - correta) * base / ctx.meses)

        base_legal = ctx.retriever.buscar(
            "anexo errado enquadramento atividade simples"
        )
        base_legal += ctx.retriever.buscar(
            "restituição imposto pago a maior erro alíquota"
        )
        if impacto_mensal > 0:
            explicacao = (
                f"Sua atividade declarada é {ctx.parametros.atividade!r}, que em "
                f"regra recolhe pelo Anexo {esperado}, mas a configuração indica o "
                f"Anexo {ctx.config.anexo_simples}. Com a sua RBT12, a alíquota "
                f"efetiva atual é {(atual * 100).quantize(Decimal('0.01'))}% contra "
                f"{(correta * 100).quantize(Decimal('0.01'))}% no anexo esperado — "
                "há indício de imposto pago a maior."
            )
            caminho = (
                "Leve o enquadramento (CNAE × anexo) ao seu contador. Se o erro se "
                "confirmar, o art. 165 do CTN garante pedir restituição do que foi "
                "pago a maior nos últimos 5 anos (art. 168)."
            )
        else:
            explicacao = (
                f"Sua atividade declarada é {ctx.parametros.atividade!r} (Anexo "
                f"{esperado}, em regra), mas a configuração indica o Anexo "
                f"{ctx.config.anexo_simples}, de alíquota MENOR. Se o enquadramento "
                "estiver errado, há risco de autuação e cobrança retroativa."
            )
            caminho = (
                "Confirme com seu contador se o enquadramento atual tem amparo; "
                "regularizar antes de fiscalização reduz multa e juros."
            )
        return [
            Achado(
                tipo="tributario",
                titulo="Anexo do Simples possivelmente errado",
                impacto_mensal=abs(impacto_mensal),
                explicacao=explicacao,
                base_legal=tuple(_dedup(base_legal)),
                caminho_pratico=caminho,
                confianca="calculado",
            )
        ]


class RegraAntecipacaoCara(RegraDeteccao):
    """Regra 2 — taxa de antecipação acima da mediana de mercado."""

    def avaliar(self, ctx: ContextoDiagnostico) -> list[Achado]:
        mediana = ctx.parametros.mediana_antecipacao_mensal
        taxa = ctx.tabela.taxa_antecipacao_mensal
        if taxa <= mediana:
            return []
        custo_atual = ctx.decomposicao.deducao("antecipacao").valor
        if custo_atual == 0:
            return []
        # Custo proporcional à taxa: na mediana, o mesmo volume antecipado
        # custaria custo_atual × (mediana / taxa).
        impacto_mensal = _q2(custo_atual * (taxa - mediana) / taxa / ctx.meses)
        base_legal = ctx.retriever.buscar(
            "antecipação de recebíveis taxa registro negociar maquininha"
        )
        return [
            Achado(
                tipo="financeiro",
                titulo="Taxa de antecipação acima da mediana de mercado",
                impacto_mensal=impacto_mensal,
                explicacao=(
                    f"Sua taxa de antecipação é "
                    f"{(taxa * 100).quantize(Decimal('0.01'))}% ao mês; a mediana "
                    f"de referência é {(mediana * 100).quantize(Decimal('0.01'))}% "
                    "(valor editável — calibre com cotações do seu perfil). A "
                    "diferença custa cerca de "
                    f"R$ {impacto_mensal}/mês no seu volume atual."
                ),
                base_legal=tuple(base_legal),
                caminho_pratico=(
                    "Desde o registro de recebíveis (Resolução CMN 4.734/2019), "
                    "sua agenda de cartão pode ser antecipada por qualquer banco "
                    "ou fintech, não só pela sua maquininha. Cote a taxa em 2–3 "
                    "instituições e negocie."
                ),
                confianca="estimado",
            )
        ]


class RegraDevolucoesAltas(RegraDeteccao):
    """Regra 3 — devoluções acima do limiar (% da receita)."""

    def avaliar(self, ctx: ContextoDiagnostico) -> list[Achado]:
        devolucoes = ctx.decomposicao.deducao("devolucoes").valor
        limite = ctx.decomposicao.receita_bruta * ctx.parametros.limiar_devolucoes
        if devolucoes <= limite:
            return []
        impacto_mensal = _q2((devolucoes - limite) / ctx.meses)
        pct = (
            (devolucoes / ctx.decomposicao.receita_bruta * 100).quantize(Decimal("0.1"))
            if ctx.decomposicao.receita_bruta
            else Decimal("0")
        )
        base_legal = ctx.retriever.buscar(
            "devolução arrependimento sete dias e-commerce venda cancelada"
        )
        limiar_pct = (ctx.parametros.limiar_devolucoes * 100).quantize(Decimal("0.1"))
        return [
            Achado(
                tipo="operacional",
                titulo="Devoluções acima do esperado",
                impacto_mensal=impacto_mensal,
                explicacao=(
                    f"Suas devoluções somam {pct}% da receita — acima do limiar de "
                    f"{limiar_pct}% (editável). O excesso corrói a margem em cerca "
                    f"de R$ {impacto_mensal}/mês. Lembre: vendas devolvidas não "
                    "compõem a base do Simples (LC 123/2006, art. 3º, § 1º) — "
                    "confira se o seu contador está excluindo essas vendas da "
                    "apuração."
                ),
                base_legal=tuple(base_legal),
                caminho_pratico=(
                    "Investigue as causas (descrição do anúncio, embalagem, "
                    "transportadora) canal a canal; devolução por arrependimento "
                    "em 7 dias é direito do consumidor (CDC, art. 49), mas o "
                    "índice é administrável."
                ),
                confianca="calculado",
            )
        ]


class RegraComissaoDivergente(RegraDeteccao):
    """Regra 4 — comissão cobrada no extrato diverge da tabela do canal."""

    def avaliar(self, ctx: ContextoDiagnostico) -> list[Achado]:
        por_canal: dict[str, Decimal] = {}
        for t in ctx.transacoes:
            if t.devolvida or t.comissao_cobrada is None:
                continue
            esperada = t.valor_bruto * ctx.tabela.comissao_canal.get(
                t.canal, Decimal("0")
            )
            por_canal[t.canal] = por_canal.get(t.canal, Decimal("0")) + (
                t.comissao_cobrada - esperada
            )
        achados = []
        for canal, divergencia_total in sorted(por_canal.items()):
            impacto_mensal = _q2(divergencia_total / ctx.meses)
            if abs(impacto_mensal) < ctx.parametros.tolerancia_comissao:
                continue
            pct_tabela = (
                ctx.tabela.comissao_canal.get(canal, Decimal("0")) * 100
            ).quantize(Decimal("0.01"))
            base_legal = ctx.retriever.buscar(
                "cobrança indevida tarifa restituição cláusula contrato marketplace"
            )
            achados.append(
                Achado(
                    tipo="contratual",
                    titulo=f"Comissão cobrada em {canal} diverge da tabela",
                    impacto_mensal=abs(impacto_mensal),
                    explicacao=(
                        f"No canal {canal}, a comissão registrada nos seus "
                        "extratos diverge da tabela configurada "
                        f"({pct_tabela}%) em cerca de R$ {abs(impacto_mensal)}/mês "
                        f"({'cobrança acima' if impacto_mensal > 0 else 'abaixo'} "
                        "da tabela). Pode ser mudança de plano, tarifa extra por "
                        "categoria — ou erro de cobrança."
                    ),
                    base_legal=tuple(base_legal),
                    caminho_pratico=(
                        "Confira o plano contratado e a tabela vigente do canal; "
                        "havendo cobrança sem previsão contratual, abra "
                        "contestação formal no canal e guarde os extratos de "
                        "repasse."
                    ),
                    confianca="calculado",
                )
            )
        return achados


class MotorDiagnostico:
    """Orquestra as regras de detecção sobre um conjunto de vendas.

    As regras padrão são as quatro da v1; injete ``regras`` para
    estender ou substituir (padrão aberto/fechado — o motor não muda).
    """

    def __init__(
        self,
        retriever: Retriever | None = None,
        parametros: ParametrosDiagnostico | None = None,
        regras: tuple[RegraDeteccao, ...] | None = None,
    ):
        self.retriever = retriever or Retriever()
        self.parametros = parametros or ParametrosDiagnostico()
        self.regras = (
            regras
            if regras is not None
            else (
                RegraAnexoErrado(),
                RegraAntecipacaoCara(),
                RegraDevolucoesAltas(),
                RegraComissaoDivergente(),
            )
        )

    def diagnosticar(
        self,
        transacoes: list[Transacao],
        config: ConfigTributaria,
        tabela: TabelaCustos | None = None,
    ) -> list[Achado]:
        """Roda todas as regras e devolve achados por impacto decrescente."""
        if not transacoes:
            raise ValueError("`transacoes` não pode ser vazio.")
        tabela = tabela or TabelaCustos()
        ctx = ContextoDiagnostico(
            transacoes=transacoes,
            config=config,
            tabela=tabela,
            parametros=self.parametros,
            retriever=self.retriever,
            decomposicao=decompor_margem(transacoes, config, tabela),
        )
        achados: list[Achado] = []
        for regra in self.regras:
            achados.extend(regra.avaliar(ctx))
        return sorted(achados, key=lambda a: a.impacto_mensal, reverse=True)


def diagnosticar(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
    parametros: ParametrosDiagnostico | None = None,
    retriever: Retriever | None = None,
) -> list[Achado]:
    """Atalho funcional para ``MotorDiagnostico(...).diagnosticar(...)``.

    Regras da v1 (heurísticas transparentes, sem ML):

    1. **Anexo do Simples possivelmente errado** dada a atividade declarada;
    2. **Taxa de antecipação acima da mediana** de mercado (editável);
    3. **Devoluções acima do limiar** (% da receita, editável);
    4. **Comissão cobrada divergente** da tabela pública do canal.
    """
    motor = MotorDiagnostico(retriever=retriever, parametros=parametros)
    return motor.diagnosticar(transacoes, config, tabela)


def _dedup(dispositivos: list[Dispositivo]) -> list[Dispositivo]:
    vistos: set[str] = set()
    unicos = []
    for d in dispositivos:
        if d.id not in vistos:
            vistos.add(d.id)
            unicos.append(d)
    return unicos
