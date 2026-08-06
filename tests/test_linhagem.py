"""Testes da linhagem de dados: cada ficha responde "de onde veio isto?"."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.analise import AnalisadorMargem
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


def test_ficha_dos_tributos_traz_formula_com_os_parametros_reais():
    analise = AnalisadorMargem([_venda()], CONFIG, origem="vendas_maio.csv")
    ficha = analise.linhagem("tributos")
    assert ficha.valor == Decimal("5.65")
    assert ficha.origem_dados == "vendas_maio.csv"
    # fórmula com a alíquota efetiva do caso: 5,65% para 360k no Anexo I
    assert "5.65%" in ficha.formula
    assert "LC 123/2006" in ficha.formula
    assert "valor_bruto" in ficha.colunas and "devolvida" in ficha.colunas
    assert any("RBT12" in p for p in ficha.premissas)
    assert any("PGDAS-D" in li for li in ficha.limitacoes)
    assert ficha.confianca_dados == "calculado"
    assert ficha.calculado_em == analise.criado_em


def test_ficha_de_comissoes_conta_extrato_real_versus_tabela():
    vendas = [_venda(comissao_cobrada=Decimal("15")), _venda()]
    ficha = AnalisadorMargem(vendas, CONFIG).linhagem("comissoes_canal")
    # 1 de 2 vendas com comissão real → a fórmula declara a ponderação
    assert "1 de 2 vendas efetivas com comissão real" in ficha.formula
    assert any("1 venda(s) sem comissão real" in li for li in ficha.limitacoes)


def test_ficha_da_margem_fecha_com_o_motor_e_cita_o_invariante():
    analise = AnalisadorMargem([_venda()], CONFIG)
    ficha = analise.linhagem("margem_liquida")
    assert ficha.valor == analise.decomposicao.margem_liquida == Decimal("32.35")
    assert "invariante testado" in ficha.formula
    assert any("aluguel" in li for li in ficha.limitacoes)


def test_todas_as_fichas_cobrem_receita_deducoes_e_margem():
    analise = AnalisadorMargem([_venda()], CONFIG)
    fichas = analise.linhagem()
    nomes = set(fichas)
    assert {"receita_bruta", "margem_liquida"} <= nomes
    assert {d.nome for d in analise.decomposicao.deducoes} <= nomes
    for ficha in fichas.values():
        assert ficha.transformacoes  # importação sempre documentada
        assert ficha.fonte


def test_origem_padrao_e_sinalizada_e_demo_se_declara_sintetica():
    sem_origem = AnalisadorMargem([_venda()], CONFIG)
    assert sem_origem.origem == "origem não informada"
    demo = AnalisadorMargem.demo(meses=2)
    assert "sintéticos" in demo.origem
    assert demo.linhagem("receita_bruta").origem_dados == demo.origem


def test_de_arquivo_propaga_o_nome_do_arquivo(tmp_path):
    arquivo = tmp_path / "vendas_junho.csv"
    arquivo.write_text(
        "data,canal,valor_bruto,custo_produto,frete_pago\n"
        "2026-06-10,mercado_livre,100,40,10\n",
        encoding="utf-8",
    )
    analise = AnalisadorMargem.de_arquivo(arquivo, CONFIG, name="vendas_junho.csv")
    assert analise.linhagem("receita_bruta").origem_dados == "vendas_junho.csv"


def test_mei_explica_das_fixo():
    config = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76"))
    ficha = AnalisadorMargem([_venda()], config).linhagem("tributos")
    assert "DAS fixo mensal" in ficha.formula
    assert "não varia com o faturamento" in ficha.formula


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
