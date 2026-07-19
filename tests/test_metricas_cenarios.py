"""Testes das métricas de margem e dos cenários de stress."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.cenarios import (
    cenario_antecipacao,
    cenario_comissao,
    cenario_devolucoes_dobram,
    cenario_mudanca_anexo,
    rodar_cenarios_padrao,
)
from carchuna.margem import ConfigTributaria, TabelaCustos, Transacao
from carchuna.metricas import (
    instabilidade_margem,
    lucro_acumulado,
    maior_queda_margem,
    margem_mensal,
)

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _venda(valor, mes, canal="mercado_livre", **kwargs):
    return Transacao(
        data=date(2026, mes, 15),
        canal=canal,
        valor_bruto=Decimal(valor),
        custo_produto=kwargs.pop("custo", Decimal("0")),
        frete_pago=Decimal("0"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------


def test_margem_mensal_agrupa_e_ordena():
    vendas = [_venda("100", 5), _venda("100", 3), _venda("100", 4)]
    mensal = margem_mensal(vendas, CONFIG)
    assert list(mensal) == ["2026-03", "2026-04", "2026-05"]
    # cada mês: 100 − 5,65 (tributos) − 12 (ML) = 82,35 → 82,35%
    assert all(d.margem_pct == Decimal("82.35") for d in mensal.values())


def test_maior_queda_e_instabilidade_calculadas_a_mao():
    serie = [
        ("2026-01", Decimal("10")),
        ("2026-02", Decimal("12")),  # pico
        ("2026-03", Decimal("7")),  # queda de 5 p.p. desde o pico
        ("2026-04", Decimal("9")),
    ]
    assert maior_queda_margem(serie) == Decimal("5")
    # média = 9,5; variância amostral = (0,25+6,25+6,25+0,25)/3 = 13/3
    # desvio = √4,333... ≈ 2,08
    assert instabilidade_margem(serie) == Decimal("2.08")


def test_lucro_acumulado_soma_corrente():
    vendas = [_venda("100", 3), _venda("100", 4)]
    curva = lucro_acumulado(margem_mensal(vendas, CONFIG))
    assert curva[0] == ("2026-03", Decimal("82.35"))
    assert curva[1] == ("2026-04", Decimal("164.70"))


def test_metricas_validam_entradas():
    with pytest.raises(ValueError):
        maior_queda_margem([])
    with pytest.raises(ValueError):
        instabilidade_margem([("2026-01", Decimal("10"))])
    with pytest.raises(ValueError):
        margem_mensal([], CONFIG)
    with pytest.raises(ValueError):
        lucro_acumulado({})


# ---------------------------------------------------------------------------
# Cenários — validados contra o efeito exato esperado
# ---------------------------------------------------------------------------


def test_cenario_comissao_mais_2pp_custa_exatamente_2pct_da_venda():
    resultado = cenario_comissao([_venda("100", 5)], CONFIG)
    assert resultado.cenario.deducao("comissoes_canal").valor == Decimal("14.00")
    assert resultado.impacto_reais == Decimal("-2.00")
    assert resultado.impacto_pp == Decimal("-2.00")


def test_cenario_comissao_ajusta_tambem_comissao_observada():
    venda = _venda("100", 5, comissao_cobrada=Decimal("15.00"))
    resultado = cenario_comissao([venda], CONFIG)
    assert resultado.cenario.deducao("comissoes_canal").valor == Decimal("17.00")


def test_cenario_antecipacao_selic_3pp_ao_ano():
    venda = _venda("1200", 5, canal="loja_propria", prazo_recebimento_dias=30)
    tabela = TabelaCustos(taxa_antecipacao_mensal=Decimal("0.02"))
    resultado = cenario_antecipacao([venda], CONFIG, tabela)
    # base: 1200×2% = 24; cenário: taxa 2% + 3%/12 = 2,25% → 27; impacto −3
    assert resultado.base.deducao("antecipacao").valor == Decimal("24.00")
    assert resultado.cenario.deducao("antecipacao").valor == Decimal("27.00")
    assert resultado.impacto_reais == Decimal("-3.00")


def test_cenario_devolucoes_dobram():
    vendas = [
        _venda("100", 5, devolvida=True),
        _venda("100", 5),
        _venda("100", 5),
    ]
    resultado = cenario_devolucoes_dobram(vendas, CONFIG)
    assert resultado.base.deducao("devolucoes").valor == Decimal("100.00")
    assert resultado.cenario.deducao("devolucoes").valor == Decimal("200.00")
    assert resultado.impacto_reais < 0


def test_cenario_mudanca_anexo_usa_aliquota_do_novo_anexo():
    resultado = cenario_mudanca_anexo([_venda("100", 5)], CONFIG, novo_anexo="III")
    # Anexo III, RBT12 360k: (360000×11,2% − 9360)/360000 = 30960/360000 = 8,6%
    assert resultado.cenario.aliquota_efetiva == Decimal("0.086")
    assert resultado.cenario.deducao("tributos").valor == Decimal("8.60")
    assert resultado.impacto_reais == Decimal("-2.95")  # 5,65 → 8,60


def test_bateria_padrao_inclui_anexo_so_no_simples():
    vendas = [_venda("100", 5)]
    assert len(rodar_cenarios_padrao(vendas, CONFIG)) == 4
    config_mei = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76"))
    assert len(rodar_cenarios_padrao(vendas, config_mei)) == 3
    with pytest.raises(ValueError, match="Simples"):
        cenario_mudanca_anexo(vendas, config_mei)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
