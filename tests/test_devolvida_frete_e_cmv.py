"""Venda devolvida: o frete fica, o produto volta.

O motor trata os dois lados de forma diferente de propósito, e isso não
estava escrito em lugar nenhum — só no comportamento. Uma assimetria não
documentada é candidata a "conserto" na próxima leitura do código: alguém
nota que o frete usa `transacoes` e o CMV usa `vendas_efetivas`, conclui
que é descuido, uniformiza, e a margem muda sem ninguém perceber.

A razão é o que acontece de fato quando a venda volta:

- **frete** — pago à transportadora na ida, não volta. Continua na conta.
- **CMV** — o produto volta ao estoque, o custo não se realizou. Sai.
- **comissão** — o canal estorna junto com o repasse. Sai.
- **adquirência e antecipação** — sem repasse não há o que antecipar nem
  taxa de captura a pagar. Saem.

Errar em qualquer direção aqui muda a margem: tirar o frete a infla,
manter o CMV a afunda. Este arquivo existe para que o próximo a mexer
tenha de discordar por escrito, e não por distração.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.margem import (
    ConfigTributaria,
    TabelaCustos,
    Transacao,
    decompor_margem,
    reconciliar,
)

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))
TABELA = TabelaCustos(taxa_antecipacao_mensal=Decimal("0.0199"))


def _venda(devolvida: bool) -> Transacao:
    return Transacao(
        data=date(2026, 5, 10),
        canal="loja_propria",
        valor_bruto=Decimal("1000"),
        custo_produto=Decimal("400"),
        frete_pago=Decimal("50"),
        prazo_recebimento_dias=30,
        devolvida=devolvida,
    )


def test_o_frete_da_venda_devolvida_continua_na_conta():
    """A transportadora não devolve o frete porque o cliente desistiu."""
    d = decompor_margem([_venda(devolvida=True)], CONFIG, TABELA)
    assert d.deducao("frete").valor == Decimal("50.00")


def test_o_cmv_da_venda_devolvida_sai_da_conta():
    """O produto voltou ao estoque: o custo não se realizou."""
    d = decompor_margem([_venda(devolvida=True)], CONFIG, TABELA)
    assert d.deducao("cmv").valor == Decimal("0.00")


@pytest.mark.parametrize("deducao", ["comissoes_canal", "adquirencia", "antecipacao"])
def test_o_que_depende_do_repasse_sai_junto_com_a_devolucao(deducao):
    """Sem repasse não há comissão, captura nem antecipação."""
    d = decompor_margem([_venda(devolvida=True)], CONFIG, TABELA)
    assert d.deducao(deducao).valor == Decimal("0.00")


def test_a_conta_inteira_de_uma_venda_devolvida():
    """Uma venda só, devolvida: sobra o prejuízo do frete.

    Receita R$ 1.000 (a devolução é dedução própria, não some da
    receita), menos R$ 1.000 de devolução, menos R$ 50 de frete. Tributo
    zero: a base do Simples exclui a venda cancelada (art. 3º, § 1º).
    Margem: −R$ 50,00, que é exatamente o que o lojista perdeu.
    """
    d = decompor_margem([_venda(devolvida=True)], CONFIG, TABELA)
    assert d.receita_bruta == Decimal("1000.00")
    assert d.deducao("devolucoes").valor == Decimal("1000.00")
    assert d.deducao("tributos").valor == Decimal("0.00")
    assert d.margem_liquida == Decimal("-50.00")


def test_a_diferenca_entre_a_venda_que_ficou_e_a_que_voltou():
    """Lado a lado, a assimetria em números.

    A venda que ficou de pé paga tudo; a que voltou paga só o frete.
    """
    ficou = decompor_margem([_venda(devolvida=False)], CONFIG, TABELA)
    voltou = decompor_margem([_venda(devolvida=True)], CONFIG, TABELA)

    assert ficou.deducao("frete").valor == voltou.deducao("frete").valor
    assert ficou.deducao("cmv").valor > voltou.deducao("cmv").valor
    assert ficou.margem_liquida > voltou.margem_liquida


def test_os_dois_caminhos_de_calculo_concordam_sobre_a_devolucao():
    """A reconciliação refaz a conta por fora e tem de chegar no mesmo.

    É ela que pegaria um "conserto" que uniformizasse só um dos lados.
    """
    vendas = [_venda(devolvida=False), _venda(devolvida=True)]
    d = decompor_margem(vendas, CONFIG, TABELA)
    assert reconciliar(vendas, CONFIG, d).ok


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
