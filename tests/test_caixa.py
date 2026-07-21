"""Testes da projeção de caixa (agenda de recebíveis + saídas informadas).

Valores calculados à mão: comissão de tabela do Mercado Livre 12%;
adquirência de 2% só em loja própria e loja física.
"""

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.caixa import (
    agenda_recebimentos,
    projetar_caixa,
    valor_liquido_recebivel,
)
from carchuna.margem import TabelaCustos, Transacao

TABELA = TabelaCustos()


def _venda(valor, dia, canal="mercado_livre", **kwargs):
    return Transacao(
        data=dia,
        canal=canal,
        valor_bruto=Decimal(valor),
        custo_produto=Decimal("0"),
        frete_pago=Decimal("0"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Valor líquido de cada recebível
# ---------------------------------------------------------------------------


def test_liquido_marketplace_desconta_so_comissao():
    # ML: 100 − 12 (comissão 12%) = 88,00; sem adquirência em marketplace.
    t = _venda("100", date(2026, 6, 10))
    assert valor_liquido_recebivel(t, TABELA) == Decimal("88.00")


def test_liquido_loja_propria_desconta_adquirencia():
    # Loja própria: comissão 0, adquirência 2% → 100 − 2 = 98,00.
    t = _venda("100", date(2026, 6, 10), canal="loja_propria")
    assert valor_liquido_recebivel(t, TABELA) == Decimal("98.00")


def test_liquido_usa_comissao_real_do_extrato_quando_informada():
    t = _venda("100", date(2026, 6, 10), comissao_cobrada=Decimal("16.50"))
    assert valor_liquido_recebivel(t, TABELA) == Decimal("83.50")


def test_devolucao_nao_gera_recebivel():
    t = _venda("100", date(2026, 6, 10), devolvida=True)
    assert valor_liquido_recebivel(t, TABELA) == Decimal("0.00")


# ---------------------------------------------------------------------------
# Agenda de recebimentos
# ---------------------------------------------------------------------------


def test_agenda_projeta_no_prazo_e_ignora_o_que_ja_caiu():
    # A venda de 01/06 com prazo 0 recebe em 01/06 — antes do "hoje" do
    # arquivo (10/06, a última venda) → pertence ao caixa inicial, sai da
    # agenda. A de 10/06 com prazo 30 deposita 88,00 em 10/07.
    vendas = [
        _venda("100", date(2026, 6, 1)),
        _venda("100", date(2026, 6, 10), prazo_recebimento_dias=30),
    ]
    assert agenda_recebimentos(vendas, TABELA) == [
        (date(2026, 7, 10), Decimal("88.00"))
    ]


def test_agenda_soma_recebiveis_do_mesmo_dia():
    hoje = date(2026, 6, 10)
    vendas = [
        _venda("100", hoje, prazo_recebimento_dias=14),
        _venda("200", hoje, prazo_recebimento_dias=14),  # 176,00
    ]
    assert agenda_recebimentos(vendas, TABELA) == [
        (hoje + timedelta(days=14), Decimal("264.00"))
    ]


def test_agenda_recusa_lista_vazia():
    with pytest.raises(ValueError):
        agenda_recebimentos([], TABELA)


# ---------------------------------------------------------------------------
# Projeção de caixa e fôlego
# ---------------------------------------------------------------------------


def test_projecao_acha_o_primeiro_dia_no_vermelho():
    # Caixa 100, saídas 300/mês → 10/dia. Dia 10: saldo 0 (ainda não é
    # vermelho); dia 11 (21/06): −10 → primeiro dia negativo, fôlego = 11.
    # A venda de 100 no ML deposita 88,00 no dia 30 (10/07): saldo do dia
    # 30 = 100 − 300 + 88 = −112,00.
    hoje = date(2026, 6, 10)
    vendas = [_venda("100", hoje, prazo_recebimento_dias=30)]
    proj = projetar_caixa(
        vendas,
        TABELA,
        caixa_inicial=Decimal("100"),
        saidas_mensais=Decimal("300"),
        horizonte_dias=90,
    )
    assert proj.hoje == hoje
    assert proj.dia_negativo == date(2026, 6, 21)
    assert proj.dias_de_folego == 11
    curva = dict(proj.curva)
    assert curva[date(2026, 6, 20)] == Decimal("0.00")
    assert curva[date(2026, 6, 21)] == Decimal("-10.00")
    assert curva[date(2026, 7, 10)] == Decimal("-112.00")
    assert proj.recebimentos_no_horizonte == Decimal("88.00")
    assert proj.saidas_no_horizonte == Decimal("900.00")


def test_projecao_sem_saidas_nunca_fica_negativa():
    hoje = date(2026, 6, 10)
    vendas = [_venda("100", hoje, prazo_recebimento_dias=7)]
    proj = projetar_caixa(vendas, TABELA, caixa_inicial=Decimal("50"))
    assert proj.dia_negativo is None
    assert proj.dias_de_folego is None
    assert proj.curva[-1][1] == Decimal("138.00")  # 50 + 88


# ---------------------------------------------------------------------------
# Inteligência de caixa (janelas, concentração, descasamento)
# ---------------------------------------------------------------------------


def test_janelas_concentracao_e_descasamento_conferidos_a_mao():
    # Venda ML 3.000 (líquido 2.640) com prazo 45 → repasse em 25/07.
    # Caixa 1.000, saídas 3.000/mês (100/dia):
    #   30 dias: entra 0, sai 3.000 → saldo −2.000 (déficit!)
    #   60 dias: entra 2.640, sai 6.000 → saldo −2.360
    #   90 dias: entra 2.640, sai 9.000 → saldo −5.360
    # Fôlego: 11 dias (dia 11 fica −100+... = −100? não: 1.000 − 100×10 = 0
    # no dia 10; dia 11 = −100). Primeiro repasse só no dia 45 →
    # descasamento. 100% dos recebíveis num único dia → concentração.
    from carchuna.caixa import analisar_caixa

    hoje = date(2026, 6, 10)
    vendas = [_venda("3000", hoje, prazo_recebimento_dias=45)]
    proj = projetar_caixa(
        vendas,
        TABELA,
        caixa_inicial=Decimal("1000"),
        saidas_mensais=Decimal("3000"),
    )
    intel = analisar_caixa(proj, agenda_recebimentos(vendas, TABELA))
    j30, j60, j90 = intel.janelas
    assert (j30.entradas, j30.saidas, j30.saldo_final) == (
        Decimal("0.00"),
        Decimal("3000.00"),
        Decimal("-2000.00"),
    )
    assert (j60.entradas, j60.saldo_final) == (Decimal("2640.00"), Decimal("-2360.00"))
    assert j90.saldo_final == Decimal("-5360.00")
    assert intel.concentracao_pct == Decimal("100.0")
    assert intel.dia_concentracao == date(2026, 7, 25)
    assert intel.dias_ate_primeiro_recebimento == 45
    assert proj.dias_de_folego == 11
    assert len(intel.alertas) == 3  # déficit + concentração + descasamento
    assert "Déficit projetado de R$ 2000.00 em 30 dias" in intel.alertas[0]
    assert "100.0%" in intel.alertas[1] and "25/07" in intel.alertas[1]
    assert "aguenta 11 dia(s)" in intel.alertas[2]


def test_sem_recebiveis_futuros_o_alerta_explica_a_origem():
    from carchuna.caixa import analisar_caixa

    hoje = date(2026, 6, 10)
    vendas = [_venda("100", hoje)]  # prazo 0: já caiu no caixa inicial
    proj = projetar_caixa(
        vendas, TABELA, caixa_inicial=Decimal("500"), saidas_mensais=Decimal("300")
    )
    intel = analisar_caixa(proj, agenda_recebimentos(vendas, TABELA))
    assert intel.dias_ate_primeiro_recebimento is None
    assert any("Nada a receber" in a for a in intel.alertas)


def test_caixa_saudavel_nao_gera_alerta():
    from carchuna.caixa import analisar_caixa

    hoje = date(2026, 6, 10)
    vendas = [
        _venda("1000", hoje, prazo_recebimento_dias=7),
        _venda("1000", hoje, prazo_recebimento_dias=14),
        _venda("1000", hoje, prazo_recebimento_dias=21),
    ]
    proj = projetar_caixa(
        vendas, TABELA, caixa_inicial=Decimal("5000"), saidas_mensais=Decimal("600")
    )
    intel = analisar_caixa(proj, agenda_recebimentos(vendas, TABELA))
    assert intel.alertas == ()
    assert intel.concentracao_pct == Decimal("33.3")  # 880 de 2.640


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
