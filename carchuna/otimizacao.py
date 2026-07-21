"""Otimizador de decisões: "qual combinação maximiza o lucro?".

Busca em grade **determinística e transparente** sobre as alavancas que
o motor consegue modelar com honestidade hoje:

- **preço** (reajuste de −10% a +15%, passo configurável) — reusa o
  transformador do :class:`~carchuna.cenarios.CenarioPreco`;
- **migração de canal** (fração das vendas de marketplace para canal
  próprio) — reusa o :class:`~carchuna.cenarios.CenarioMigracaoCanal`.

Cada candidato da grade roda no MESMO motor de margem testado; nada de
solver caixa-preta. O resultado lista TODOS os candidatos avaliados, o
motivo de cada descarte (qual restrição violou) e por que o vencedor
venceu — a explicação é a própria grade.

Premissa de volume, sempre explícita:

- sem elasticidade informada, o volume é constante (``estimado`` — a
  planilha de vendas não tem como dizer quanto de demanda se perde);
- o usuário PODE informar uma elasticidade (% de volume perdido por
  +1% de preço) como premissa dele; o lucro é escalado linearmente
  (todas as parcelas da margem são proporcionais ao volume).

Restrições suportadas: margem mínima (%), queda máxima de volume (%),
preço médio máximo (R$). Alavancas sem dado honesto (publicidade,
conversão, custos operacionais) são roadmap — ver README.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from carchuna.cenarios import CenarioMigracaoCanal, CenarioPreco
from carchuna.margem import ConfigTributaria, TabelaCustos, Transacao, decompor_margem

DELTAS_PRECO_PADRAO = tuple(
    Decimal(i) / 100 for i in range(-10, 16)
)  # −10% a +15%, passo 1 p.p.
FRACOES_MIGRACAO_PADRAO = (
    Decimal("0"),
    Decimal("0.10"),
    Decimal("0.20"),
    Decimal("0.30"),
)


@dataclass
class Restricoes:
    """Limites do lojista — cada um vira um filtro nomeado na grade."""

    margem_minima_pct: Decimal | None = None  # ex.: 20 → margem ≥ 20%
    queda_maxima_volume: Decimal | None = None  # ex.: 0.15 → perder ≤ 15%
    preco_medio_maximo: Decimal | None = None  # ticket médio ≤ R$ X


@dataclass
class ParametrosOtimizacao:
    """A grade avaliada — visível e editável, nunca escondida."""

    deltas_preco: tuple[Decimal, ...] = field(default=DELTAS_PRECO_PADRAO)
    fracoes_migracao: tuple[Decimal, ...] = field(default=FRACOES_MIGRACAO_PADRAO)
    # % de volume perdido por +1% de preço (premissa do usuário; None =
    # volume constante, premissa declarada no resultado)
    elasticidade: Decimal | None = None


@dataclass(frozen=True)
class Candidato:
    """Um ponto da grade: alavancas, resultado e restrições violadas."""

    delta_preco: Decimal
    fracao_migracao: Decimal
    fator_volume: Decimal
    margem_pct: Decimal
    lucro_mensal: Decimal  # já escalado pelo fator de volume
    ticket_medio: Decimal
    violacoes: tuple[str, ...]  # vazio = viável

    @property
    def viavel(self) -> bool:
        return not self.violacoes


@dataclass(frozen=True)
class ResultadoOtimizacao:
    """O vencedor, a base, TODA a grade e a explicação em texto."""

    objetivo: str
    base: Candidato
    melhor: Candidato | None  # None = nenhum candidato viável
    ganho_mensal: Decimal
    candidatos: tuple[Candidato, ...]
    premissas: tuple[str, ...]
    explicacao: str


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(v: Decimal) -> str:
    return f"{(v * 100).quantize(Decimal('1'))}%"


class MotorOtimizacao:
    """Busca em grade sobre preço × migração de canal, com restrições."""

    def __init__(self, parametros: ParametrosOtimizacao | None = None):
        self.parametros = parametros or ParametrosOtimizacao()

    def _avaliar(
        self,
        transacoes: list[Transacao],
        config: ConfigTributaria,
        tabela: TabelaCustos,
        dp: Decimal,
        fm: Decimal,
        meses: int,
        restricoes: Restricoes,
    ) -> Candidato:
        atuais = list(transacoes)
        if dp != 0:
            atuais, config, tabela = CenarioPreco(dp).transformar(
                atuais, config, tabela
            )
        if fm > 0:
            atuais, config, tabela = CenarioMigracaoCanal(fracao=fm).transformar(
                atuais, config, tabela
            )
        d = decompor_margem(atuais, config, tabela)

        elasticidade = self.parametros.elasticidade
        fator_volume = Decimal("1")
        if elasticidade is not None:
            # elasticidade = % de volume perdido por +1% de preço; com
            # dp em fração, a queda de volume é elasticidade × dp.
            fator_volume = max(Decimal("0"), Decimal("1") - elasticidade * dp)
        lucro = _q2(d.margem_liquida / meses * fator_volume)
        efetivas = [t for t in atuais if not t.devolvida]
        ticket = (
            _q2(sum((t.valor_bruto for t in efetivas), Decimal("0")) / len(efetivas))
            if efetivas
            else Decimal("0")
        )

        violacoes: list[str] = []
        r = restricoes
        if r.margem_minima_pct is not None and d.margem_pct < r.margem_minima_pct:
            violacoes.append(
                f"margem {d.margem_pct}% abaixo do mínimo de {r.margem_minima_pct}%"
            )
        queda = Decimal("1") - fator_volume
        if r.queda_maxima_volume is not None and queda > r.queda_maxima_volume:
            violacoes.append(
                f"queda de volume {_pct(queda)} acima do teto de "
                f"{_pct(r.queda_maxima_volume)}"
            )
        if r.preco_medio_maximo is not None and ticket > r.preco_medio_maximo:
            violacoes.append(
                f"ticket médio R$ {ticket} acima do teto de "
                f"R$ {r.preco_medio_maximo}"
            )
        return Candidato(
            delta_preco=dp,
            fracao_migracao=fm,
            fator_volume=fator_volume,
            margem_pct=d.margem_pct,
            lucro_mensal=lucro,
            ticket_medio=ticket,
            violacoes=tuple(violacoes),
        )

    def otimizar(
        self,
        transacoes: list[Transacao],
        config: ConfigTributaria,
        tabela: TabelaCustos | None = None,
        restricoes: Restricoes | None = None,
    ) -> ResultadoOtimizacao:
        """Avalia a grade inteira e explica o vencedor (ou a inviabilidade)."""
        if not transacoes:
            raise ValueError("`transacoes` não pode ser vazio.")
        tabela = tabela or TabelaCustos()
        restricoes = restricoes or Restricoes()
        meses = len({(t.data.year, t.data.month) for t in transacoes}) or 1

        tem_ml = any(t.canal == "mercado_livre" for t in transacoes)
        fracoes = self.parametros.fracoes_migracao if tem_ml else (Decimal("0"),)
        candidatos = [
            self._avaliar(transacoes, config, tabela, dp, fm, meses, restricoes)
            for dp in self.parametros.deltas_preco
            for fm in fracoes
        ]
        base = next(
            c for c in candidatos if c.delta_preco == 0 and c.fracao_migracao == 0
        )
        viaveis = [c for c in candidatos if c.viavel]
        melhor = (
            max(viaveis, key=lambda c: (c.lucro_mensal, -abs(c.delta_preco)))
            if viaveis
            else None
        )
        ganho = melhor.lucro_mensal - base.lucro_mensal if melhor else Decimal("0")

        elasticidade = self.parametros.elasticidade
        premissas = [
            "busca em grade determinística — todos os candidatos avaliados "
            "estão listados no resultado",
            "lucro escalado linearmente pelo volume (cada parcela da margem "
            "é proporcional ao volume)",
        ]
        if elasticidade is None:
            premissas.append(
                "volume constante (nenhuma elasticidade informada): a planilha "
                "de vendas não tem como estimar a demanda perdida — premissa "
                "'estimado'"
            )
        else:
            premissas.append(
                f"elasticidade informada por você: {elasticidade}% de volume "
                "perdido a cada +1% de preço (premissa sua, não medida)"
            )

        descartados = len(candidatos) - len(viaveis)
        if melhor is None:
            explicacao = (
                f"Nenhum dos {len(candidatos)} candidatos atende as restrições "
                "— afrouxe algum limite ou revise as premissas."
            )
        else:
            partes = [
                f"Avaliados {len(candidatos)} candidatos "
                f"(preço × migração de canal); {descartados} violaram restrições."
            ]
            partes.append(
                f"Vencedor: preço {_pct(melhor.delta_preco)} e migração de "
                f"{_pct(melhor.fracao_migracao)} do Mercado Livre para canal "
                f"próprio → lucro de R$ {melhor.lucro_mensal}/mês "
                f"(margem {melhor.margem_pct}%), contra R$ {base.lucro_mensal}"
                f"/mês na base — ganho de R$ {_q2(ganho)}/mês."
            )
            if descartados:
                exemplo = next(c for c in candidatos if not c.viavel)
                partes.append(
                    "Exemplo de descarte: preço "
                    f"{_pct(exemplo.delta_preco)} caiu por: "
                    f"{exemplo.violacoes[0]}."
                )
            explicacao = " ".join(partes)

        return ResultadoOtimizacao(
            objetivo="maximizar o lucro líquido mensal",
            base=base,
            melhor=melhor,
            ganho_mensal=_q2(ganho),
            candidatos=tuple(candidatos),
            premissas=tuple(premissas),
            explicacao=explicacao,
        )
