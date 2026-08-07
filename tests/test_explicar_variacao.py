"""Por que o lucro mudou: a identidade contábil conferida à mão.

Caso de referência:
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
from carchuna.margem import ConfigTributaria, Transacao
from carchuna.metricas import explicar_variacao

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


def test_decomposicao_da_queda_fecha_centavo_a_centavo():
    exp = explicar_variacao(_analise().mensal)
    assert (exp.mes_a, exp.mes_b) == ("2026-05", "2026-06")
    # base positiva nos dois: o percentual está definido e vale
    assert exp.var_receita_pct.ok and exp.var_receita_pct.valor == Decimal("20.0")
    assert exp.var_lucro_pct.ok and exp.var_lucro_pct.valor == Decimal("-28.6")
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
    with pytest.raises(ValueError, match="2 meses"):
        explicar_variacao({"2026-05": _analise().mensal["2026-05"]})


def test_a_identidade_fecha_em_qualquer_par_de_meses_da_demo():
    """A soma das contribuições é o Δlucro — sempre, não só no caso montado.

    É o mesmo invariante que o motor já garante dentro de um mês
    (deduções + margem == receita), aplicado à diferença entre dois. Se
    ele não fechasse, a explicação estaria atribuindo a variação a
    fatores que não a produziram.
    """
    mensal = AnalisadorMargem.demo(meses=8).mensal
    meses = list(mensal)
    assert len(meses) >= 3
    for mes in meses[1:]:
        exp = explicar_variacao(mensal, mes)
        assert sum(c.delta_reais for c in exp.contribuicoes) == exp.delta_lucro
        # a pressão distribui 100% entre quem empurrou no sentido da variação
        pressoes = [c.pct_da_pressao for c in exp.contribuicoes if c.pct_da_pressao > 0]
        if pressoes:
            assert abs(sum(pressoes) - Decimal("100")) <= Decimal("0.5")


def test_sem_mes_indicado_explica_o_ultimo():
    mensal = AnalisadorMargem.demo(meses=5).mensal
    ultimo = list(mensal)[-1]
    assert explicar_variacao(mensal).mes_b == ultimo
    assert explicar_variacao(mensal, ultimo).mes_b == ultimo


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
