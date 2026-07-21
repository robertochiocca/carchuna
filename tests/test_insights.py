"""Testes do radar de insights (detector de vazamentos de margem).

Todos os valores esperados são calculados à mão nos comentários, com a
alíquota efetiva do Anexo I em RBT12 = 360.000:
(360000 × 7,30% − 5.940) / 360000 = 20.340 / 360000 = 5,65%.
Comissão de tabela do Mercado Livre: 12% (anúncio Clássico).
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.insights import (
    ContextoInsights,
    MesForaDoPadrao,
    MotorInsights,
    ParametrosInsights,
    ProdutosMargemMagra,
    TendenciaCustos,
)
from carchuna.margem import ConfigTributaria, TabelaCustos, Transacao

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _venda(valor, mes, dia=15, **kwargs):
    return Transacao(
        data=date(2026, mes, dia),
        canal=kwargs.pop("canal", "mercado_livre"),
        valor_bruto=Decimal(valor),
        custo_produto=kwargs.pop("custo", Decimal("0")),
        frete_pago=kwargs.pop("frete", Decimal("0")),
        **kwargs,
    )


def _ctx(vendas):
    return ContextoInsights(
        transacoes=vendas,
        config=CONFIG,
        tabela=TabelaCustos(),
        parametros=ParametrosInsights(),
    )


# ---------------------------------------------------------------------------
# Tendência de custos (dedução subindo como % da receita)
# ---------------------------------------------------------------------------


def test_tendencia_comissao_subindo_8pp_e_critico_com_impacto_80():
    # Mês 1: venda 1000, comissão cobrada 120 → 12,00% da receita.
    # Mês 2: venda 1000, comissão cobrada 200 → 20,00% da receita.
    # Delta = 8,00 p.p. ≥ 3 (limiar crítico); impacto = 8% × 1000 = 80,00.
    vendas = [
        _venda("1000", 5, comissao_cobrada=Decimal("120")),
        _venda("1000", 6, comissao_cobrada=Decimal("200")),
    ]
    insights = MotorInsights().radar(vendas, CONFIG)
    assert len(insights) == 1
    (i,) = insights
    assert i.severidade == "critico"
    assert i.impacto_mensal == Decimal("80.00")
    assert "8.00 p.p." in i.titulo
    assert i.confianca == "calculado"


def test_tendencia_alta_pequena_vira_atencao_e_abaixo_do_limiar_silencia():
    # Delta de 2,00 p.p. (120 → 140 sobre 1000): atenção (1,5 ≤ 2 < 3).
    vendas = [
        _venda("1000", 5, comissao_cobrada=Decimal("120")),
        _venda("1000", 6, comissao_cobrada=Decimal("140")),
    ]
    (i,) = TendenciaCustos().avaliar(_ctx(vendas))
    assert i.severidade == "atencao"
    assert i.impacto_mensal == Decimal("20.00")

    # Delta de 1,00 p.p. (120 → 130): abaixo de 1,5 → sem sinal.
    vendas = [
        _venda("1000", 5, comissao_cobrada=Decimal("120")),
        _venda("1000", 6, comissao_cobrada=Decimal("130")),
    ]
    assert TendenciaCustos().avaliar(_ctx(vendas)) == []


def test_tendencia_exige_dois_meses():
    assert TendenciaCustos().avaliar(_ctx([_venda("1000", 5)])) == []


# ---------------------------------------------------------------------------
# Produtos de margem magra (com ganho de reajuste recalculado pelo motor)
# ---------------------------------------------------------------------------


def test_produto_magro_detectado_com_ganho_exato_do_reajuste():
    # Capinha: 100 − 5,65 (tributo) − 12 (comissão) − 66,35 (CMV) − 10
    #          (frete) = 6,00 → margem 6,00% < 8% → magra.
    # Fone:    100 − 5,65 − 12 − 20 − 5 = 57,35 → 57,35% → saudável.
    # Reajuste de 5% só na Capinha: bruto 105, tributo 105 × 5,65% = 5,93,
    # comissão 105 × 12% = 12,60 → margem da carteira sobe de
    # (200 − 11,30 − 24 − 86,35 − 15) = 63,35 para
    # (205 − 11,58 − 24,60 − 86,35 − 15) = 67,47 → ganho = 4,12/mês.
    vendas = [
        _venda(
            "100", 5, custo=Decimal("66.35"), frete=Decimal("10"), produto="Capinha"
        ),
        _venda("100", 5, custo=Decimal("20"), frete=Decimal("5"), produto="Fone"),
    ]
    insights = MotorInsights().radar(vendas, CONFIG)
    assert len(insights) == 1
    (i,) = insights
    assert i.severidade == "oportunidade"
    assert i.impacto_mensal == Decimal("4.12")
    assert "Capinha" in i.explicacao
    assert "Fone" not in i.explicacao
    assert "premissa" in i.explicacao  # honestidade: mesmo volume é premissa


def test_sem_produto_magro_sem_sinal():
    vendas = [_venda("100", 5, custo=Decimal("20"), produto="Fone")]
    assert ProdutosMargemMagra().avaliar(_ctx(vendas)) == []


# ---------------------------------------------------------------------------
# Mês fora do padrão (2σ+ sobre 4+ meses)
# ---------------------------------------------------------------------------


def test_mes_fora_do_padrao_detecta_salto_de_margem():
    # Meses 1–4: margens 42,35 / 42,15 / 42,55 / 42,35 (média 42,35%,
    # σ ≈ 0,163). Mês 5: CMV cai para 300 → margem 52,35% → +10 p.p.
    # (≈ 61σ). Impacto = 10% × 1000 = 100,00. Como as deduções CAÍRAM,
    # a tendência de custos não dispara — só a anomalia (oportunidade).
    vendas = [
        _venda("1000", 1, custo=Decimal("400")),
        _venda("1000", 2, custo=Decimal("402")),
        _venda("1000", 3, custo=Decimal("398")),
        _venda("1000", 4, custo=Decimal("400")),
        _venda("1000", 5, custo=Decimal("300")),
    ]
    insights = MotorInsights().radar(vendas, CONFIG)
    assert len(insights) == 1
    (i,) = insights
    assert i.severidade == "oportunidade"
    assert i.impacto_mensal == Decimal("100.00")
    assert "acima" in i.explicacao
    assert i.confianca == "estimado"


def test_anomalia_exige_quatro_meses_e_historico_com_variacao():
    tres_meses = [_venda("1000", m, custo=Decimal("400")) for m in (1, 2, 3)]
    assert MesForaDoPadrao().avaliar(_ctx(tres_meses)) == []
    # Histórico perfeitamente constante (σ = 0) não permite medir desvio.
    constantes = [_venda("1000", m, custo=Decimal("400")) for m in (1, 2, 3, 4, 5)]
    assert MesForaDoPadrao().avaliar(_ctx(constantes)) == []


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------


def test_radar_ordena_por_severidade_e_recusa_lista_vazia():
    # Crítico (comissão +8 p.p.) e oportunidade (produto magro) juntos:
    # o crítico vem primeiro. Capinha nos 2 meses: receita 2000, tributos
    # 113, comissões 320, CMV 1500 → margem 67 → 3,35% (magra).
    vendas = [
        _venda(
            "1000",
            5,
            comissao_cobrada=Decimal("120"),
            custo=Decimal("750"),
            produto="Capinha",
        ),
        _venda(
            "1000",
            6,
            comissao_cobrada=Decimal("200"),
            custo=Decimal("750"),
            produto="Capinha",
        ),
    ]
    insights = MotorInsights().radar(vendas, CONFIG)
    assert len(insights) >= 2
    severidades = [i.severidade for i in insights]
    assert severidades == sorted(
        severidades, key=["critico", "atencao", "oportunidade"].index
    )
    with pytest.raises(ValueError):
        MotorInsights().radar([], CONFIG)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
