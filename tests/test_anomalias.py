"""Testes da detecção de anomalias — métodos e limiares conferidos à mão.

Alíquota efetiva do Anexo I em RBT12 = 360.000: 5,65% (conferida em
test_margem). Comissões informadas via ``comissao_cobrada`` para
controlar a série mensal com exatidão.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.anomalias import MotorAnomalias
from carchuna.margem import ConfigTributaria, Transacao

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _venda(valor, mes, **kwargs):
    return Transacao(
        data=date(2026, mes, 15),
        canal="mercado_livre",
        valor_bruto=Decimal(valor),
        custo_produto=kwargs.pop("custo", Decimal("0")),
        frete_pago=kwargs.pop("frete", Decimal("0")),
        **kwargs,
    )


def test_historico_constante_dispara_no_salto_e_calcula_o_impacto():
    # Comissão em 12,00% da receita por 3 meses; no 4º, 20,00%.
    # σ = 0 → regra do histórico constante (desvio 8 p.p. > 0,5 p.p.).
    # Esperado 12%, observado 20%, desvio (20−12)/12 = +66,7%,
    # impacto = 8% × 1.000 = 80,00. Custo caiu? Não — subiu → crítico.
    vendas = [_venda("1000", m, comissao_cobrada=Decimal("120")) for m in (1, 2, 3)] + [
        _venda("1000", 4, comissao_cobrada=Decimal("200"))
    ]
    (a,) = MotorAnomalias().detectar(vendas, CONFIG)
    assert a.metrica == "comissoes_canal_pct"
    assert a.severidade == "critico"
    assert a.esperado == "12.00% da receita"
    assert a.observado == "20.00% da receita"
    assert a.desvio_pct == Decimal("66.7")
    assert a.impacto_mensal == Decimal("80.00")
    assert "histórico constante" in a.metodo
    assert a.confianca.pct > 0


def test_z_score_com_iqr_confirmando():
    # Série de comissão: 12,00 / 12,20 / 11,80 / 12,00 (média 12,00%,
    # σ ≈ 0,163) e o 5º mês em 13,00% → z ≈ 6,1σ ≥ 3 → crítico; a cerca
    # IQR (Q3 12,05 + 1,5×0,10 = 12,20) também é ultrapassada.
    # Impacto = 1% × 1.000 = 10,00.
    comissoes = ["120", "122", "118", "120", "130"]
    vendas = [
        _venda("1000", m, comissao_cobrada=Decimal(c))
        for m, c in enumerate(comissoes, start=1)
    ]
    (a,) = MotorAnomalias().detectar(vendas, CONFIG)
    assert a.severidade == "critico"
    assert a.impacto_mensal == Decimal("10.00")
    assert "z-score" in a.metodo and "IQR" in a.metodo


def test_custo_que_cai_fora_do_padrao_vira_oportunidade():
    vendas = [_venda("1000", m, comissao_cobrada=Decimal("200")) for m in (1, 2, 3)] + [
        _venda("1000", 4, comissao_cobrada=Decimal("120"))
    ]
    (a,) = MotorAnomalias().detectar(vendas, CONFIG)
    assert a.severidade == "oportunidade"
    assert "caiu" in a.titulo
    assert a.impacto_mensal == Decimal("80.00")


def test_frete_por_pedido_contra_a_media_movel():
    # 2 pedidos/mês com frete 10 cada nos meses 1–3 (R$ 10/pedido);
    # no mês 4, frete 15 cada → R$ 15/pedido = +50% ≥ 25% → atenção.
    # Impacto = (15 − 10) × 2 pedidos = 10,00. A fatia do frete na
    # receita sobe exatamente 0,5 p.p. — no limiar, não acima — então a
    # regra de dedução NÃO dispara junto (sem duplicidade).
    vendas = []
    for m in (1, 2, 3):
        vendas += [_venda("1000", m, frete=Decimal("10")) for _ in range(2)]
    vendas += [_venda("1000", 4, frete=Decimal("15")) for _ in range(2)]
    (a,) = MotorAnomalias().detectar(vendas, CONFIG)
    assert a.metrica == "frete_por_pedido"
    assert a.severidade == "atencao"
    assert a.esperado == "R$ 10.00/pedido"
    assert a.observado == "R$ 15.00/pedido"
    assert a.desvio_pct == Decimal("50.0")
    assert a.impacto_mensal == Decimal("10.00")
    assert "média móvel" in a.metodo


def test_receita_sobe_lucro_cai_aponta_a_causa():
    # Mês 1: receita 1.000, comissão 120, CMV 400 → lucro 423,50.
    # Mês 2: receita 1.200 (+20%), comissão 350, CMV 480 → lucro 302,20
    # (−28,6%). Esperado se a margem acompanhasse: 423,50 × 1,2 = 508,20
    # → impacto 206,00. Causa: comissão, de 12% para 29,17% da receita.
    vendas = [
        _venda("1000", 1, comissao_cobrada=Decimal("120"), custo=Decimal("400")),
        _venda("1200", 2, comissao_cobrada=Decimal("350"), custo=Decimal("480")),
    ]
    (a,) = MotorAnomalias().detectar(vendas, CONFIG)
    assert a.metrica == "receita_x_lucro"
    assert a.severidade == "critico"
    assert a.esperado.startswith("R$ 508.20")
    assert a.observado.startswith("R$ 302.20")
    assert a.impacto_mensal == Decimal("206.00")
    assert "Comissões de canal" in a.o_que_aconteceu
    assert "divergência" in a.metodo


def test_meses_estaveis_nao_geram_anomalia_e_lista_vazia_e_recusada():
    vendas = [
        _venda("1000", m, comissao_cobrada=Decimal("120"), custo=Decimal("400"))
        for m in (1, 2, 3, 4, 5)
    ]
    assert MotorAnomalias().detectar(vendas, CONFIG) == []
    with pytest.raises(ValueError):
        MotorAnomalias().detectar([], CONFIG)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
