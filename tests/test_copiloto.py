"""Testes do copiloto — o roteador e a decomposição de variação, à mão.

Caso de referência (o mesmo da anomalia de divergência):
mês 5: receita 1.000, comissão 120, CMV 400 → lucro 423,50;
mês 6: receita 1.200, comissão 350, CMV 480 → lucro 302,20.
Δlucro = −121,30. Contribuições (identidade contábil):
receita +200,00 · tributos −11,30 · comissão −230,00 · CMV −80,00
(soma = −121,30, fecha centavo a centavo). Pressão negativa total =
321,30 → comissão 71,6%, CMV 24,9%, tributos 3,5%.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.analise import AnalisadorMargem
from carchuna.copiloto import Copiloto, explicar_variacao
from carchuna.margem import ConfigTributaria, Transacao

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))

VENDAS = [
    Transacao(
        data=date(2026, 5, 15),
        canal="mercado_livre",
        valor_bruto=Decimal("1000"),
        custo_produto=Decimal("400"),
        frete_pago=Decimal("0"),
        comissao_cobrada=Decimal("120"),
        produto="Fone",
    ),
    Transacao(
        data=date(2026, 6, 15),
        canal="mercado_livre",
        valor_bruto=Decimal("1200"),
        custo_produto=Decimal("480"),
        frete_pago=Decimal("0"),
        comissao_cobrada=Decimal("350"),
        produto="Fone",
    ),
]


def _analise():
    return AnalisadorMargem(VENDAS, CONFIG, origem="vendas.csv")


# ---------------------------------------------------------------------------
# explicar_variacao (identidade contábil conferida à mão)
# ---------------------------------------------------------------------------


def test_decomposicao_da_queda_fecha_centavo_a_centavo():
    exp = explicar_variacao(_analise().mensal)
    assert (exp.mes_a, exp.mes_b) == ("2026-05", "2026-06")
    assert exp.var_receita_pct == Decimal("20.0")
    assert exp.var_lucro_pct == Decimal("-28.6")
    assert exp.delta_lucro == Decimal("-121.30")
    # a soma das contribuições é exatamente o delta do lucro
    soma = sum(c.delta_reais for c in exp.contribuicoes)
    assert soma == exp.delta_lucro
    por_nome = {c.nome: c for c in exp.contribuicoes}
    assert por_nome["comissoes_canal"].delta_reais == Decimal("-230.00")
    assert por_nome["comissoes_canal"].pct_da_pressao == Decimal("71.6")
    assert por_nome["cmv"].pct_da_pressao == Decimal("24.9")
    assert por_nome["tributos"].pct_da_pressao == Decimal("3.5")
    # a receita empurrou CONTRA a queda: delta positivo, pressão zero
    assert por_nome["receita"].delta_reais == Decimal("200.00")
    assert por_nome["receita"].pct_da_pressao == Decimal("0")


def test_frase_aponta_causa_principal_e_secundaria():
    frase = explicar_variacao(_analise().mensal).frase()
    assert "o lucro caiu 28.6%" in frase
    assert "Principal causa: Comissões de canal" in frase
    assert "71.6% da pressão" in frase
    assert "Causa secundária" in frase


def test_variacao_valida_meses():
    mensal = _analise().mensal
    with pytest.raises(ValueError, match="não está na base"):
        explicar_variacao(mensal, "2026-12")
    with pytest.raises(ValueError, match="primeiro mês"):
        explicar_variacao(mensal, "2026-05")


# ---------------------------------------------------------------------------
# Roteador de intenções
# ---------------------------------------------------------------------------


def test_por_que_o_lucro_caiu_em_junho():
    r = Copiloto(_analise()).responder("Por que meu lucro caiu em junho?")
    assert r.intencao == "variacao_lucro"
    assert "71.6% da pressão" in r.texto
    assert r.dados["variacao_lucro"] == "-28.6%"
    assert "pressao_comissoes_canal" in r.dados


def test_quanto_sobrou_usa_o_resumo_executivo():
    r = Copiloto(_analise()).responder("quanto sobrou de verdade?")
    assert r.intencao == "resumo"
    assert r.texto == _analise().resumo_executivo().frase()


def test_produto_campeao_e_caixa_e_impostos():
    copiloto = Copiloto(_analise())
    assert copiloto.responder("qual meu produto campeão?").intencao == "produtos"
    caixa = copiloto.responder("quanto vou receber ainda?")
    assert caixa.intencao == "caixa"
    imposto = copiloto.responder("quanto pago de imposto?")
    assert imposto.intencao == "impostos"
    assert "LC 123/2006" in imposto.texto  # a fórmula da linhagem, com a lei


def test_pergunta_juridica_vai_para_o_rag():
    # fora das intenções numéricas → None: o app cai no Retriever legal
    r = Copiloto(_analise()).responder("posso contestar uma tarifa no contrato?")
    assert r is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
