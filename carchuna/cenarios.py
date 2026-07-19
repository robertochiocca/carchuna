"""Cenários de stress da margem — "e se amanhã o custo subir?".

Adaptação do ``stress.py`` da Calahonda: em vez de choques do Ibovespa,
os choques que realmente atingem o PME vendedor:

- comissão do marketplace sobe (ex.: +2 p.p.);
- custo de antecipação sobe (ex.: Selic +3 p.p. ao ano);
- devoluções/inadimplência dobram;
- mudança de anexo do Simples.

Cada cenário reexecuta ``decompor_margem`` com os parâmetros alterados —
nada de fórmula paralela: o mesmo motor calculado e testado produz o
"antes" e o "depois", e a diferença é o impacto.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from carchuna.margem import (
    ConfigTributaria,
    DecomposicaoMargem,
    TabelaCustos,
    Transacao,
    decompor_margem,
)


@dataclass(frozen=True)
class ResultadoCenario:
    """Margem antes e depois de um choque, com o impacto isolado."""

    nome: str
    base: DecomposicaoMargem
    cenario: DecomposicaoMargem
    impacto_reais: Decimal  # variação da margem líquida (negativo = piora)
    impacto_pp: Decimal  # variação da margem %, em pontos percentuais


def _comparar(
    nome: str, base: DecomposicaoMargem, novo: DecomposicaoMargem
) -> ResultadoCenario:
    return ResultadoCenario(
        nome=nome,
        base=base,
        cenario=novo,
        impacto_reais=novo.margem_liquida - base.margem_liquida,
        impacto_pp=novo.margem_pct - base.margem_pct,
    )


def cenario_comissao(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
    delta_pp: Decimal = Decimal("0.02"),
) -> ResultadoCenario:
    """Comissão de todos os marketplaces sobe ``delta_pp`` (fração; 0.02 = +2 p.p.)."""
    tabela = tabela or TabelaCustos()
    base = decompor_margem(transacoes, config, tabela)
    nova_tabela = TabelaCustos(
        comissao_canal={
            canal: (pct + delta_pp if pct > 0 else pct)
            for canal, pct in tabela.comissao_canal.items()
        },
        taxa_adquirencia=tabela.taxa_adquirencia,
        taxa_antecipacao_mensal=tabela.taxa_antecipacao_mensal,
        canais_com_adquirencia=tabela.canais_com_adquirencia,
    )
    # Comissões observadas no extrato também sobem delta_pp sobre o valor.
    novas_transacoes = [
        (
            replace(t, comissao_cobrada=t.comissao_cobrada + t.valor_bruto * delta_pp)
            if t.comissao_cobrada is not None
            else t
        )
        for t in transacoes
    ]
    novo = decompor_margem(novas_transacoes, config, nova_tabela)
    pct = (delta_pp * 100).quantize(Decimal("0.01"))
    return _comparar(f"Comissão dos marketplaces +{pct} p.p.", base, novo)


def cenario_antecipacao(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
    delta_ano: Decimal = Decimal("0.03"),
) -> ResultadoCenario:
    """Custo anual de antecipação sobe ``delta_ano`` (ex.: Selic +3 p.p. a.a.).

    O repasse é aproximado por ``delta_ano / 12`` na taxa mensal —
    aproximação linear documentada (juros compostos ficam para a v2).
    """
    tabela = tabela or TabelaCustos()
    base = decompor_margem(transacoes, config, tabela)
    nova_tabela = TabelaCustos(
        comissao_canal=dict(tabela.comissao_canal),
        taxa_adquirencia=tabela.taxa_adquirencia,
        taxa_antecipacao_mensal=tabela.taxa_antecipacao_mensal + delta_ano / 12,
        canais_com_adquirencia=tabela.canais_com_adquirencia,
    )
    novo = decompor_margem(transacoes, config, nova_tabela)
    pct = (delta_ano * 100).quantize(Decimal("0.01"))
    return _comparar(f"Antecipação +{pct} p.p. ao ano (efeito Selic)", base, novo)


def cenario_devolucoes_dobram(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
) -> ResultadoCenario:
    """Devoluções dobram: marca mais vendas como devolvidas até ~2× o valor atual.

    Heurística determinística e transparente: percorre as vendas não
    devolvidas em ordem de data e vai marcando como devolvidas até o
    valor devolvido alcançar o dobro do observado. Se hoje não há
    nenhuma devolução, usa 3% da receita como base (taxa típica de
    e-commerce usada nos dados sintéticos).
    """
    tabela = tabela or TabelaCustos()
    base = decompor_margem(transacoes, config, tabela)
    valor_atual = base.deducao("devolucoes").valor
    alvo = valor_atual * 2 if valor_atual > 0 else base.receita_bruta * Decimal("0.03")

    novas: list[Transacao] = []
    devolvido = valor_atual
    for t in sorted(transacoes, key=lambda t: (t.data, t.valor_bruto)):
        if not t.devolvida and devolvido < alvo:
            devolvido += t.valor_bruto
            novas.append(replace(t, devolvida=True))
        else:
            novas.append(t)
    novo = decompor_margem(novas, config, tabela)
    return _comparar("Devoluções/inadimplência dobram", base, novo)


def cenario_mudanca_anexo(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
    novo_anexo: str = "III",
) -> ResultadoCenario:
    """Reenquadramento em outro anexo do Simples (LC 123/2006, art. 18)."""
    if config.regime != "simples":
        raise ValueError("Cenário de anexo só se aplica ao regime Simples.")
    tabela = tabela or TabelaCustos()
    base = decompor_margem(transacoes, config, tabela)
    nova_config = ConfigTributaria(
        regime="simples", anexo_simples=novo_anexo, rbt12=config.rbt12
    )
    novo = decompor_margem(transacoes, nova_config, tabela)
    return _comparar(
        f"Mudança do Anexo {config.anexo_simples} para o Anexo {novo_anexo}",
        base,
        novo,
    )


def rodar_cenarios_padrao(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
) -> list[ResultadoCenario]:
    """Roda a bateria padrão de cenários (a "página de stress" do relatório)."""
    resultados = [
        cenario_comissao(transacoes, config, tabela),
        cenario_antecipacao(transacoes, config, tabela),
        cenario_devolucoes_dobram(transacoes, config, tabela),
    ]
    if config.regime == "simples":
        outro = "III" if config.anexo_simples != "III" else "I"
        resultados.append(cenario_mudanca_anexo(transacoes, config, tabela, outro))
    return resultados
