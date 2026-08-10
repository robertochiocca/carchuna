"""Os percentuais da tela somavam o que quisessem, e nada conferia.

As três conferências da casa olhavam os REAIS. `reconciliar()` refaz a
margem lançamento a lançamento e compara valores; `conferir_plausibilidade`
olha valores; a identidade estrutural soma valores. Os percentuais são
outro número — `valor ÷ receita bruta`, calculado à parte para cada
dedução — e são justamente eles que aparecem na cachoeira, no drill-down
e no resumo.

O buraco não é teórico, e o defeito que o prova é de boa-fé: trocar o
denominador do percentual do tributo para a base do tributo
(`receita − devoluções`) é uma "correção" plausível, porque aquela É a
base legal do art. 3º, § 1º. Feita a troca, todos os valores em reais
continuam certos, `reconciliar()` diz ok, a identidade estrutural fecha —
e a tela publica percentuais que somam 101,41%.
"""

import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.margem import (
    ConfigTributaria,
    TabelaCustos,
    Transacao,
    conferir_fechamento_percentual,
    conferir_plausibilidade,
    decompor_margem,
    reconciliar,
)

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _vendas() -> list[Transacao]:
    """Quatro vendas, uma devolvida — para o denominador ter como divergir."""
    return [
        Transacao(
            data=date(2026, 5, 10),
            canal="shopee",
            valor_bruto=Decimal("1000"),
            custo_produto=Decimal("400"),
            frete_pago=Decimal("50"),
            devolvida=(i == 0),
        )
        for i in range(4)
    ]


def test_o_motor_fecha_em_cem():
    vendas = _vendas()
    d = decompor_margem(vendas, CONFIG, TabelaCustos())
    soma = sum((x.pct_receita for x in d.deducoes), Decimal("0"))
    assert soma + d.margem_pct == Decimal("100.00")
    assert conferir_fechamento_percentual(d).ok


def test_denominador_trocado_e_pego_mesmo_com_todos_os_reais_certos():
    """O defeito que passa pelas outras três conferências.

    Reproduzido aqui trocando o percentual do tributo na decomposição
    pronta, em vez de mexer no motor: o efeito na tela é o mesmo, e o
    teste não depende de ninguém reintroduzir o bug para valer.
    """
    vendas = _vendas()
    d = decompor_margem(vendas, CONFIG, TabelaCustos())
    receita, devolucoes = d.receita_bruta, d.deducao("devolucoes").valor

    tributos = d.deducao("tributos")
    pct_sobre_a_base = (tributos.valor / (receita - devolucoes) * 100).quantize(
        Decimal("0.01")
    )
    adulterada = replace(
        d,
        deducoes=tuple(
            replace(x, pct_receita=pct_sobre_a_base) if x.nome == "tributos" else x
            for x in d.deducoes
        ),
    )

    # os reais não mudaram: as outras conferências seguem satisfeitas
    assert adulterada.identidade_estrutural_fecha()
    assert reconciliar(vendas, CONFIG, adulterada).ok

    # e o percentual publicado, esse, não fecha
    soma = sum((x.pct_receita for x in adulterada.deducoes), Decimal("0"))
    assert soma + adulterada.margem_pct == Decimal("101.41")

    resultado = conferir_fechamento_percentual(adulterada)
    assert resultado.status == "implausivel"
    assert "101.41" in resultado.motivo
    assert "receita bruta" in resultado.motivo


def test_a_plausibilidade_carrega_o_fechamento_junto():
    """Quem já chamava `conferir_plausibilidade` ganha a conferência nova."""
    vendas = _vendas()
    d = decompor_margem(vendas, CONFIG, TabelaCustos())
    quebrada = replace(
        d,
        deducoes=tuple(
            (
                replace(x, pct_receita=x.pct_receita + Decimal("5"))
                if x.nome == "cmv"
                else x
            )
            for x in d.deducoes
        ),
    )
    assert conferir_plausibilidade(quebrada).status == "implausivel"


def test_a_tolerancia_e_de_arredondamento_e_nao_de_erro():
    """Meio centésimo por percentual publicado passa; um décimo não.

    Sem esta fronteira a conferência seria decorativa: uma tolerância
    generosa absorveria justamente o tipo de divergência que ela existe
    para pegar.
    """
    vendas = _vendas()
    d = decompor_margem(vendas, CONFIG, TabelaCustos())

    for delta, esperado in ((Decimal("0.04"), True), (Decimal("0.10"), False)):
        mexida = replace(
            d,
            deducoes=tuple(
                (
                    replace(x, pct_receita=x.pct_receita + delta)
                    if x.nome == "frete"
                    else x
                )
                for x in d.deducoes
            ),
        )
        assert conferir_fechamento_percentual(mexida).ok is esperado, delta


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
