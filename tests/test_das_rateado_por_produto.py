"""No MEI, o DAS era cobrado uma vez por produto do catálogo.

O DAS é valor FIXO do mês (LC 123/2006, art. 18-A, § 3º, V), não um
percentual: `decompor_margem` o cobra inteiro em qualquer conjunto que
receba. O detector de margem magra decompõe produto a produto para
comparar margens — e com dez produtos no catálogo, cobrava dez DAS.

O efeito não é acadêmico: cada produto sai mais magro do que é, e o
detector acusa "produto com margem abaixo de 8%" por causa da própria
contagem. O lojista é mandado reprecificar um produto que está bem.

Rateio por receita porque é a única repartição que o dado sustenta — o
DAS não tem base de cálculo por item, então qualquer alocação é
convenção, e "quem faturou mais carrega mais" é a que não precisa de
explicação.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.insights import (
    ContextoInsights,
    ParametrosInsights,
    ProdutosMargemMagra,
    _config_rateada,
)
from carchuna.margem import ConfigTributaria, TabelaCustos, Transacao, decompor_margem

MEI = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76.00"))
SIMPLES = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _venda(produto: str, valor="500", mes=5, custo="200") -> Transacao:
    return Transacao(
        data=date(2026, mes, 10),
        canal="shopee",
        valor_bruto=Decimal(valor),
        custo_produto=Decimal(custo),
        frete_pago=Decimal("0"),
        produto=produto,
    )


def _tributos_por_produto(vendas, config) -> Decimal:
    """Soma o tributo de cada grupo de produto, como o detector faz."""
    por_produto: dict[str, list[Transacao]] = {}
    for t in vendas:
        por_produto.setdefault(t.produto, []).append(t)
    receita = sum((t.valor_bruto for t in vendas), Decimal("0"))
    meses = len({(t.data.year, t.data.month) for t in vendas})
    return sum(
        decompor_margem(
            grupo, _config_rateada(config, grupo, receita, meses), TabelaCustos()
        )
        .deducao("tributos")
        .valor
        for grupo in por_produto.values()
    )


# ---------------------------------------------------------------------------
# O rateio fecha
# ---------------------------------------------------------------------------


def test_a_soma_do_das_por_produto_e_o_das_do_periodo():
    """Três produtos no mesmo mês: um DAS, não três.

    A soma fecha a menos de um centavo por produto — R$ 76,00 ÷ 3 não é
    exato, e cada parte é arredondada sozinha. Aqui isso basta, e é
    proposital afirmar só isso: este número não vai para a tela, ele
    alimenta a comparação com o limiar de margem magra. Exigir igualdade
    ao centavo pediria repartir o resíduo, que é máquina sem ganho para o
    lojista. Onde a soma É publicada — a quebra por canal do raio-X — o
    resíduo é repartido, e lá tem teste de igualdade exata.
    """
    vendas = [_venda("A"), _venda("B"), _venda("C")]
    inteiro = decompor_margem(vendas, MEI).deducao("tributos").valor
    assert inteiro == Decimal("76.00")

    soma = _tributos_por_produto(vendas, MEI)
    assert abs(soma - inteiro) <= Decimal("0.03")  # ≤ 1 centavo por produto
    # e o defeito que isto conserta era de outra ordem de grandeza
    assert soma < Decimal("100.00")


def test_quem_fatura_mais_carrega_mais_das():
    """R$ 3.000 e R$ 1.000: 75% e 25% do DAS de R$ 76,00."""
    vendas = [_venda("A", "3000"), _venda("B", "1000")]
    receita = Decimal("4000")
    a = decompor_margem(
        [vendas[0]], _config_rateada(MEI, [vendas[0]], receita, 1), TabelaCustos()
    )
    b = decompor_margem(
        [vendas[1]], _config_rateada(MEI, [vendas[1]], receita, 1), TabelaCustos()
    )
    assert a.deducao("tributos").valor == Decimal("57.00")  # 76 × 0,75
    assert b.deducao("tributos").valor == Decimal("19.00")  # 76 × 0,25


def test_produto_vendido_em_poucos_meses_leva_o_das_que_lhe_cabe():
    """O rateio é por receita, não por presença no calendário.

    `decompor_margem` multiplica o DAS pelos meses do grupo que recebe.
    Um produto vendido em 1 dos 3 meses levaria um terço do que lhe cabe
    se o ajuste não desfizesse essa multiplicação.
    """
    vendas = [
        _venda("A", "1000", mes=1),
        _venda("A", "1000", mes=2),
        _venda("A", "1000", mes=3),
        _venda("B", "3000", mes=3),
    ]
    # 3 meses × R$ 76 = R$ 228 de DAS no período; A e B faturam R$ 3.000 cada
    assert decompor_margem(vendas, MEI).deducao("tributos").valor == Decimal("228.00")
    assert _tributos_por_produto(vendas, MEI) == Decimal("228.00")

    so_b = [t for t in vendas if t.produto == "B"]
    b = decompor_margem(
        so_b, _config_rateada(MEI, so_b, Decimal("6000"), 3), TabelaCustos()
    )
    assert b.deducao("tributos").valor == Decimal("114.00")  # metade dos 228


def test_no_simples_nao_ha_o_que_ratear():
    """O tributo do Simples já é proporcional à receita do grupo."""
    grupo = [_venda("A")]
    assert _config_rateada(SIMPLES, grupo, Decimal("1000"), 1) is SIMPLES


def test_receita_zero_nao_estoura():
    """Arquivo só de devoluções não pode derrubar o detector."""
    grupo = [_venda("A")]
    assert _config_rateada(MEI, grupo, Decimal("0"), 1) is MEI


# ---------------------------------------------------------------------------
# O efeito visível: o detector para de acusar por causa da própria contagem
# ---------------------------------------------------------------------------


def test_o_detector_nao_acusa_produto_saudavel_por_causa_do_das_multiplicado():
    """Dez produtos idênticos e saudáveis; antes, dez DAS os afundavam.

    Os números são calibrados para o defeito passar por eles, e não para
    o teste passar: R$ 500 de venda, R$ 350 de custo, 14% de comissão da
    Shopee. Com o DAS rateado (R$ 7,60) sobram R$ 72,40 — 14,48%, bem
    acima do limiar de 8%. Com o DAS cobrado dez vezes (R$ 76) sobram
    R$ 4,00 — 0,8%, e o detector mandava reprecificar dez produtos
    saudáveis por causa da própria contagem.

    Os valores cabem no teto do MEI de propósito: R$ 5.000 no mês, contra
    o teto proporcional de R$ 6.750.
    """
    vendas = [_venda(f"P{i}", custo="350") for i in range(10)]
    ctx = ContextoInsights(
        transacoes=vendas,
        config=MEI,
        tabela=TabelaCustos(),
        parametros=ParametrosInsights(),
    )
    assert ProdutosMargemMagra().avaliar(ctx) == []


def test_o_detector_continua_acusando_produto_de_fato_magro():
    """O conserto não pode ter sido calar o detector.

    P0 tem custo de R$ 395 sobre R$ 500: mesmo com o DAS rateado
    corretamente (R$ 7,60), sobram R$ 27,40 — 5,48%, abaixo do limiar de
    8% e ainda positivo, que é a faixa que este detector cobre.
    """
    vendas = [_venda("P0", custo="395")] + [_venda(f"P{i}") for i in range(1, 10)]
    ctx = ContextoInsights(
        transacoes=vendas,
        config=MEI,
        tabela=TabelaCustos(),
        parametros=ParametrosInsights(),
    )
    achados = ProdutosMargemMagra().avaliar(ctx)
    assert len(achados) == 1
    assert "1 produto" in achados[0].titulo


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
