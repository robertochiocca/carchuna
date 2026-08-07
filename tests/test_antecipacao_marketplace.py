"""Antecipação em marketplace: o custo existia e a conta dava zero.

A antecipação estava amarrada aos canais de adquirência — loja própria e
físico. Marketplace não cobra adquirência do lojista (a tarifa de
pagamento vem embutida na comissão), então caía fora da lista e a
antecipação dele era zero, mesmo com prazo de repasse declarado na
planilha.

É justamente onde o custo é mais comum: o marketplace segura o repasse
por 15 a 30 dias e vende a liberação adiantada exatamente como a
adquirente vende. Nos dados sintéticos da própria Carchuna, 80% do
faturamento sai por canais que tinham esse custo zerado.

O erro é da família dos outros: não estoura, não aparece, e infla a
margem — o lado que ninguém contesta olhando a tela.
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


def _venda(canal: str, prazo: int, valor="1000") -> Transacao:
    return Transacao(
        data=date(2026, 5, 10),
        canal=canal,
        valor_bruto=Decimal(valor),
        custo_produto=Decimal("400"),
        frete_pago=Decimal("0"),
        prazo_recebimento_dias=prazo,
    )


@pytest.mark.parametrize("canal", ["mercado_livre", "shopee", "amazon", "loja_propria"])
def test_todo_canal_com_prazo_paga_antecipacao(canal):
    """R$ 1.000 a 30 dias, 1,99% ao mês = R$ 19,90 — em qualquer canal.

    Antes, os três marketplaces davam R$ 0,00 nesta mesma conta.
    """
    tabela = TabelaCustos(taxa_antecipacao_mensal=Decimal("0.0199"))
    d = decompor_margem([_venda(canal, 30)], CONFIG, tabela)
    assert d.deducao("antecipacao").valor == Decimal("19.90")


def test_o_prazo_e_que_manda_e_nao_o_canal():
    """Quem espera o repasse em vez de antecipar informa prazo zero.

    A pergunta que o motor responde é "houve antecipação?", e a resposta
    está no prazo — não em qual canal a venda saiu.
    """
    tabela = TabelaCustos(taxa_antecipacao_mensal=Decimal("0.0199"))
    d = decompor_margem([_venda("shopee", 0)], CONFIG, tabela)
    assert d.deducao("antecipacao").valor == Decimal("0.00")


def test_a_antecipacao_e_proporcional_aos_dias():
    """15 dias custa metade de 30: R$ 1.000 × 1,99% × 15/30 = R$ 9,95."""
    tabela = TabelaCustos(taxa_antecipacao_mensal=Decimal("0.0199"))
    d = decompor_margem([_venda("shopee", 15)], CONFIG, tabela)
    assert d.deducao("antecipacao").valor == Decimal("9.95")


def test_marketplace_continua_sem_adquirencia():
    """O ajuste é só da antecipação — a adquirência segue embutida.

    Sem este teste, a correção poderia ter sido feita jogando os
    marketplaces em `canais_com_adquirencia`, o que cobraria do lojista
    uma taxa de maquininha que ele não paga.
    """
    d = decompor_margem([_venda("shopee", 30)], CONFIG, TabelaCustos())
    assert d.deducao("adquirencia").valor == Decimal("0.00")
    assert d.deducao("antecipacao").valor > 0


def test_a_lista_de_canais_com_antecipacao_e_editavel():
    """Quem não antecipa em canal nenhum tira o canal da lista."""
    tabela = TabelaCustos(
        canais_com_antecipacao=frozenset({"loja_propria"}),
        taxa_antecipacao_mensal=Decimal("0.0199"),
    )
    d = decompor_margem([_venda("shopee", 30)], CONFIG, tabela)
    assert d.deducao("antecipacao").valor == Decimal("0.00")


def test_venda_devolvida_nao_paga_antecipacao():
    """Repasse que não veio não foi antecipado."""
    devolvida = Transacao(
        data=date(2026, 5, 10),
        canal="shopee",
        valor_bruto=Decimal("1000"),
        custo_produto=Decimal("400"),
        frete_pago=Decimal("0"),
        prazo_recebimento_dias=30,
        devolvida=True,
    )
    d = decompor_margem([devolvida], CONFIG, TabelaCustos())
    assert d.deducao("antecipacao").valor == Decimal("0.00")


def test_os_dois_caminhos_de_calculo_continuam_fechando():
    """A reconciliação é quem pegou o meio-conserto — e ela fica de guarda.

    Ao corrigir só `decompor_margem`, `reconciliar` seguiu somando a
    antecipação pela regra antiga e os dois caminhos passaram a divergir
    em R$ 19,90. Foi ela quem acusou, não uma revisão de código.
    """
    vendas = [
        _venda("mercado_livre", 30),
        _venda("shopee", 15),
        _venda("loja_propria", 30),
        _venda("fisico", 0),
    ]
    d = decompor_margem(vendas, CONFIG, TabelaCustos())
    assert d.deducao("antecipacao").valor > 0
    assert reconciliar(vendas, CONFIG, d).ok


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
