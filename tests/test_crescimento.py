"""Testes do motor de crescimento: como faturar mais, validado à mão."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.cenarios import CenarioCrescimentoCanal
from carchuna.crescimento import (
    MotorCrescimento,
    preco_para_margem,
)
from carchuna.margem import ConfigTributaria, Transacao
from carchuna.rag.retrieval import Retriever

RETRIEVER = Retriever()
CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))
MOTOR = MotorCrescimento(retriever=RETRIEVER)


def _venda(valor="100", canal="mercado_livre", custo="40", frete="10", **kwargs):
    padrao = dict(
        data=date(2026, 5, 10),
        canal=canal,
        valor_bruto=Decimal(valor),
        custo_produto=Decimal(custo),
        frete_pago=Decimal(frete),
    )
    padrao.update(kwargs)
    return Transacao(**padrao)


# ---------------------------------------------------------------------------
# Calculadora de preço — o motor de margem invertido
# ---------------------------------------------------------------------------


def test_preco_para_margem_conferido_a_mao():
    """Custo 40 + frete 10 no ML (12%), Simples 5,65%, alvo 10%.

    preço = 50 / (1 − 0,0565 − 0,12 − 0,10) = 50 / 0,7235 = 69,11.
    """
    preco = preco_para_margem(
        Decimal("40"),
        Decimal("10"),
        "mercado_livre",
        CONFIG,
        margem_alvo=Decimal("0.10"),
    )
    assert preco == Decimal("69.11")
    # equilíbrio (margem zero): 50 / 0,8235 = 60,72
    equilibrio = preco_para_margem(
        Decimal("40"), Decimal("10"), "mercado_livre", CONFIG
    )
    assert equilibrio == Decimal("60.72")


def test_preco_no_alvo_entrega_a_margem_prometida():
    """Vender pelo preço sugerido gera margem >= alvo no próprio motor."""
    from carchuna.margem import decompor_margem

    preco = preco_para_margem(
        Decimal("40"),
        Decimal("10"),
        "mercado_livre",
        CONFIG,
        margem_alvo=Decimal("0.10"),
    )
    venda = _venda(valor=str(preco))
    resultado = decompor_margem([venda], CONFIG)
    assert resultado.margem_pct >= Decimal("10.00")


def test_preco_para_margem_no_mei_ignora_das_fixo():
    config = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76"))
    preco = preco_para_margem(Decimal("50"), Decimal("0"), "fisico", config)
    # físico: só adquirência 2% → 50 / 0,98 = 51,03 (arredondado p/ cima)
    assert preco == Decimal("51.03")


def test_margem_alvo_inatingivel_explica_o_motivo():
    with pytest.raises(ValueError, match="inatingível"):
        preco_para_margem(
            Decimal("40"),
            Decimal("10"),
            "mercado_livre",
            CONFIG,
            margem_alvo=Decimal("0.90"),
        )


# ---------------------------------------------------------------------------
# Análises do motor
# ---------------------------------------------------------------------------


def test_mix_de_canais_aponta_o_canal_que_rende_mais():
    """ML 22,35% vs loja própria 32,35%: gap de 10 p.p., ganho de 10/mês.

    Ganho = gap × receita do pior canal × 10% (premissa editável).
    """
    vendas = [
        _venda("1000", canal="mercado_livre", custo="600", frete="0"),
        _venda("1000", canal="loja_propria", custo="600", frete="0"),
    ]
    (oportunidade,) = [
        o for o in MOTOR.sugerir(vendas, CONFIG) if o.tipo == "mix_canais"
    ]
    assert "loja_propria" in oportunidade.titulo
    assert oportunidade.ganho_estimado_mensal == Decimal("10.00")
    assert oportunidade.confianca == "estimado"
    assert "garantia" in oportunidade.aviso


def test_mix_de_canais_nao_dispara_com_gap_pequeno():
    vendas = [
        _venda("1000", canal="mercado_livre", custo="600", frete="0"),
        # shopee 14% vs ML 12%: gap de só 2 p.p. — abaixo do mínimo de 5
        _venda("1000", canal="shopee", custo="600", frete="0"),
    ]
    assert not [o for o in MOTOR.sugerir(vendas, CONFIG) if o.tipo == "mix_canais"]


def test_vendas_no_prejuizo_sao_quantificadas():
    """Venda 100 com custo 95 + frete 10 no ML: margem −22,65."""
    vendas = [_venda("100", custo="95", frete="10"), _venda("100")]
    (oportunidade,) = [
        o for o in MOTOR.sugerir(vendas, CONFIG) if o.tipo == "precificacao"
    ]
    assert oportunidade.ganho_estimado_mensal == Decimal("22.65")
    assert oportunidade.confianca == "calculado"
    assert "R$ 145.13" in oportunidade.explicacao  # (95+10)/0,7235 p/ 10%


def test_espaco_no_simples_calculado_a_mao():
    """RBT12 300k: cabem 60k na faixa; efetiva 5,32% hoje → 5,65% no fim."""
    config = ConfigTributaria(
        regime="simples", anexo_simples="I", rbt12=Decimal("300000")
    )
    (oportunidade,) = [
        o for o in MOTOR.sugerir([_venda()], config) if o.tipo == "espaco_tributario"
    ]
    assert oportunidade.ganho_estimado_mensal == Decimal("5000.00")  # 60k/12
    assert "R$ 60000" in oportunidade.explicacao
    assert "5.32%" in oportunidade.explicacao
    assert "5.65%" in oportunidade.explicacao
    assert oportunidade.base_legal, "espaço tributário cita a LC 123"

    config_mei = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76"))
    assert not [
        o
        for o in MOTOR.sugerir([_venda()], config_mei)
        if o.tipo == "espaco_tributario"
    ]


def test_oportunidades_ordenadas_e_entrada_validada():
    vendas = [
        _venda("1000", canal="mercado_livre", custo="600", frete="0"),
        _venda("1000", canal="loja_propria", custo="600", frete="0"),
        _venda("100", custo="95", frete="10"),
    ]
    oportunidades = MOTOR.sugerir(vendas, CONFIG)
    ganhos = [o.ganho_estimado_mensal for o in oportunidades]
    assert ganhos == sorted(ganhos, reverse=True)
    with pytest.raises(ValueError, match="transacoes"):
        MOTOR.sugerir([], CONFIG)


# ---------------------------------------------------------------------------
# Cenário de crescimento de canal
# ---------------------------------------------------------------------------


def test_cenario_crescimento_dobra_um_canal_conferido_a_mao():
    """Uma venda na loja própria, +100%: a venda é replicada e a margem dobra."""
    venda = _venda("100", canal="loja_propria", custo="40", frete="10")
    resultado = CenarioCrescimentoCanal("loja_propria", Decimal("1")).executar(
        [venda], CONFIG
    )
    assert resultado.cenario.receita_bruta == Decimal("200.00")
    assert resultado.impacto_reais == resultado.base.margem_liquida
    assert "100% a mais" in resultado.nome


def test_cenario_crescimento_valida_entradas():
    with pytest.raises(ValueError, match="fracao"):
        CenarioCrescimentoCanal(fracao=Decimal("1.5"))
    with pytest.raises(ValueError, match="não há vendas"):
        CenarioCrescimentoCanal("amazon").executar([_venda()], CONFIG)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
