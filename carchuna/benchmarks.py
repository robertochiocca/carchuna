"""Benchmarking honesto: comparar só com régua que tem fonte.

Regra inegociável do projeto: **nunca apresentar benchmark inventado
como dado de mercado**. Cada comparação carrega ``tipo_fonte``:

- ``tabela_publica`` — a tabela oficial do canal, com link (a régua
  mais dura que existe: o próprio contrato público);
- ``default_editavel`` — referência estimada e DOCUMENTADA do projeto
  (mediana de antecipação, limiar de devoluções), editável pelo usuário;
- ``informado_usuario`` — benchmark que VOCÊ trouxe (do seu contador,
  associação ou relatório pago) — a Carchuna compara, mas a fonte é sua;
- ``indisponivel`` — a comparação existiria, mas não há fonte gratuita
  confiável; a ficha explica o que falta em vez de inventar número.

Percentis ("você está no 32º percentil") exigem a DISTRIBUIÇÃO do
mercado, não uma média — nenhuma fonte gratuita e auditável publica
isso por segmento; por honestidade, não há percentil aqui.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from carchuna.diagnostico import LIMIAR_DEVOLUCOES, MEDIANA_ANTECIPACAO_MENSAL
from carchuna.margem import (
    FONTES_COMISSAO,
    ConfigTributaria,
    TabelaCustos,
    Transacao,
    decompor_margem,
)

TIPOS_FONTE = (
    "tabela_publica",
    "default_editavel",
    "informado_usuario",
    "indisponivel",
)


@dataclass(frozen=True)
class Benchmark:
    """Uma comparação sua × referência, sempre com a natureza da fonte."""

    metrica: str
    rotulo: str
    valor_usuario: str  # formatado com unidade
    referencia: str | None  # None = sem referência confiável
    diferenca: str | None
    tipo_fonte: str
    fonte: str  # de onde a referência vem (ou por que não existe)
    leitura: str  # a comparação em uma frase honesta


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def comparar_benchmarks(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
    referencias_usuario: dict[str, Decimal] | None = None,
) -> list[Benchmark]:
    """As comparações possíveis com honestidade sobre a fonte de cada uma.

    ``referencias_usuario`` aceita ``{"margem_liquida_pct": Decimal}``
    para a comparação de margem — que sem dado seu fica ``indisponivel``.
    """
    if not transacoes:
        raise ValueError("`transacoes` não pode ser vazio.")
    tabela = tabela or TabelaCustos()
    referencias_usuario = referencias_usuario or {}
    d = decompor_margem(transacoes, config, tabela)
    resultados: list[Benchmark] = []

    # 1. Comissão efetiva observada × tabela pública, canal a canal.
    por_canal: dict[str, tuple[Decimal, Decimal]] = {}
    for t in transacoes:
        if t.devolvida or t.comissao_cobrada is None:
            continue
        soma, receita = por_canal.get(t.canal, (Decimal("0"), Decimal("0")))
        por_canal[t.canal] = (soma + t.comissao_cobrada, receita + t.valor_bruto)
    for canal, (soma, receita) in sorted(por_canal.items()):
        if receita == 0 or canal not in FONTES_COMISSAO:
            continue
        efetiva = _q2(soma / receita * 100)
        tabela_pct = _q2(tabela.comissao_canal.get(canal, Decimal("0")) * 100)
        delta = _q2(efetiva - tabela_pct)
        resultados.append(
            Benchmark(
                metrica=f"comissao_{canal}",
                rotulo=f"Comissão efetiva em {canal}",
                valor_usuario=f"{efetiva}% da receita",
                referencia=f"{tabela_pct}% (tabela pública do canal)",
                diferenca=f"{delta:+} p.p.",
                tipo_fonte="tabela_publica",
                fonte=FONTES_COMISSAO[canal],
                leitura=(
                    f"Seus extratos mostram {efetiva}% contra {tabela_pct}% da "
                    "tabela pública — "
                    + (
                        "diferença compatível com plano/categoria; confira o "
                        "seu contrato."
                        if abs(delta) < Decimal("1")
                        else "vale conferir plano, categoria e tarifas extras."
                    )
                ),
            )
        )

    # 2. Taxa de antecipação × mediana de referência (default documentado).
    taxa = _q2(tabela.taxa_antecipacao_mensal * 100)
    mediana = _q2(MEDIANA_ANTECIPACAO_MENSAL * 100)
    resultados.append(
        Benchmark(
            metrica="taxa_antecipacao",
            rotulo="Taxa de antecipação (% a.m.)",
            valor_usuario=f"{taxa}% ao mês",
            referencia=f"{mediana}% ao mês (mediana de referência, editável)",
            diferenca=f"{_q2(taxa - mediana):+} p.p.",
            tipo_fonte="default_editavel",
            fonte=(
                "estimativa documentada no diagnóstico (Resolução CMN "
                "4.734/2019 tornou a taxa negociável); calibre com cotações "
                "do seu perfil"
            ),
            leitura=(
                "Acima da mediana: cote em 2–3 instituições."
                if taxa > mediana
                else "Na mediana ou abaixo — taxa saudável."
            ),
        )
    )

    # 3. Devoluções × limiar típico de e-commerce (default documentado).
    devolucoes_pct = d.deducao("devolucoes").pct_receita
    limiar_pct = _q2(LIMIAR_DEVOLUCOES * 100)
    resultados.append(
        Benchmark(
            metrica="devolucoes_pct",
            rotulo="Devoluções (% da receita)",
            valor_usuario=f"{devolucoes_pct}% da receita",
            referencia=f"{limiar_pct}% (limiar típico de e-commerce, editável)",
            diferenca=f"{_q2(devolucoes_pct - limiar_pct):+} p.p.",
            tipo_fonte="default_editavel",
            fonte="limiar documentado no diagnóstico, a partir de taxas típicas",
            leitura=(
                "Acima do limiar — investigue causas por canal."
                if devolucoes_pct > limiar_pct
                else "Dentro do esperado para e-commerce."
            ),
        )
    )

    # 4. Margem líquida × mercado: SÓ com referência trazida pelo usuário.
    margem_ref = referencias_usuario.get("margem_liquida_pct")
    if margem_ref is not None:
        delta = _q2(d.margem_pct - margem_ref)
        resultados.append(
            Benchmark(
                metrica="margem_liquida_pct",
                rotulo="Margem líquida (% da receita)",
                valor_usuario=f"{d.margem_pct}%",
                referencia=f"{_q2(margem_ref)}% (informado por você)",
                diferenca=f"{delta:+} p.p.",
                tipo_fonte="informado_usuario",
                fonte="benchmark trazido por você — a Carchuna não o audita",
                leitura=(
                    f"Sua margem está {abs(delta)} p.p. "
                    f"{'acima' if delta >= 0 else 'abaixo'} da SUA referência."
                ),
            )
        )
    else:
        resultados.append(
            Benchmark(
                metrica="margem_liquida_pct",
                rotulo="Margem líquida (% da receita)",
                valor_usuario=f"{d.margem_pct}%",
                referencia=None,
                diferenca=None,
                tipo_fonte="indisponivel",
                fonte=(
                    "não há fonte gratuita e auditável de margem líquida por "
                    "segmento no Brasil; benchmark inventado não entra aqui"
                ),
                leitura=(
                    "Sem referência confiável para comparar. Se você tem um "
                    "número do seu contador ou associação, informe-o e a "
                    "comparação aparece — com a fonte etiquetada como sua."
                ),
            )
        )
    return resultados
