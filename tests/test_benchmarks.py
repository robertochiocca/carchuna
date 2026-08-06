"""Testes do benchmarking honesto — cada comparação com a fonte etiquetada."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.benchmarks import comparar_benchmarks
from carchuna.margem import ConfigTributaria, Transacao

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _venda(**kwargs):
    padrao = dict(
        data=date(2026, 5, 10),
        canal="mercado_livre",
        valor_bruto=Decimal("100"),
        custo_produto=Decimal("40"),
        frete_pago=Decimal("10"),
    )
    padrao.update(kwargs)
    return Transacao(**padrao)


def test_comissao_efetiva_contra_a_tabela_publica_do_canal():
    # Extrato com 15,00 sobre 100 → 15% efetiva vs 12% da tabela = +3 p.p.
    vendas = [_venda(comissao_cobrada=Decimal("15"))]
    bm = {b.metrica: b for b in comparar_benchmarks(vendas, CONFIG)}
    b = bm["comissao_mercado_livre"]
    assert b.valor_usuario == "15.00% da receita"
    assert b.diferenca == "+3.00 p.p."
    assert b.tipo_fonte == "tabela_publica"
    assert b.fonte.startswith("https://")  # a tabela oficial, com link


def test_antecipacao_compara_com_a_mediana_editavel():
    b = {b.metrica: b for b in comparar_benchmarks([_venda()], CONFIG)}[
        "taxa_antecipacao"
    ]
    # default do projeto: 1,99% vs mediana 1,60% → +0,39 p.p.
    assert b.diferenca == "+0.39 p.p."
    assert b.tipo_fonte == "default_editavel"
    assert "Acima da mediana" in b.leitura


def test_margem_sem_referencia_diz_que_nao_ha_fonte_em_vez_de_inventar():
    b = {b.metrica: b for b in comparar_benchmarks([_venda()], CONFIG)}[
        "margem_liquida_pct"
    ]
    assert b.tipo_fonte == "indisponivel"
    assert b.referencia is None
    assert "benchmark inventado não entra" in b.fonte


def test_margem_com_referencia_do_usuario_e_etiquetada_como_dele():
    # Venda de 100 com comissão da tabela: margem 32,35% vs 20% do usuário.
    bms = comparar_benchmarks(
        [_venda()],
        CONFIG,
        referencias_usuario={"margem_liquida_pct": Decimal("20")},
    )
    b = {b.metrica: b for b in bms}["margem_liquida_pct"]
    assert b.tipo_fonte == "informado_usuario"
    assert b.valor_usuario == "32.35%"
    assert b.diferenca == "+12.35 p.p."
    assert "acima" in b.leitura
    with pytest.raises(ValueError):
        comparar_benchmarks([], CONFIG)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
