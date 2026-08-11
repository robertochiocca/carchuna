"""Cenário que mexia na receita deixava a RBT12 parada.

A alíquota efetiva do Simples sai da receita bruta acumulada dos doze
meses anteriores (LC 123/2006, art. 18, § 1º e § 1º-A). Dois cenários
mexem exatamente nessa receita — subir todos os preços e crescer um
canal — e os dois devolviam a ``rbt12`` original, congelada.

O erro tem direção, e é a pior das duas. Com a RBT12 parada, o cenário
mantém a loja na faixa antiga: o tributo simulado sai menor do que
seria e a margem simulada sai maior. A tela responde "aumentar o preço
rende X" com X inflado — bem no número que o lojista usa para decidir
aumentar o preço.

Perto de uma virada de faixa o engano deixa de ser detalhe. Uma loja com
RBT12 de R$ 175.000 está a R$ 5.000 da 2ª faixa do Anexo I; +5% de preço
a leva a R$ 183.750 e muda a alíquota, e a simulação antiga não mostrava
nada disso.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.cenarios import (
    CenarioComissao,
    CenarioCrescimentoCanal,
    CenarioPreco,
)
from carchuna.margem import (
    ConfigTributaria,
    TabelaCustos,
    Transacao,
    aliquota_efetiva_simples,
    decompor_margem,
)

# R$ 175.000 de RBT12: R$ 5.000 abaixo da virada para a 2ª faixa do Anexo I.
NA_BEIRA = ConfigTributaria(
    regime="simples", anexo_simples="I", rbt12=Decimal("175000")
)
MEI = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76.00"))


def _vendas(valor="10000", canal="loja_propria", meses=12, **kwargs):
    return [
        Transacao(
            data=date(2026, m, 15),
            canal=canal,
            valor_bruto=Decimal(valor),
            custo_produto=Decimal("5000"),
            frete_pago=Decimal("0"),
            **kwargs,
        )
        for m in range(1, meses + 1)
    ]


def _config_do_cenario(cenario, vendas, config):
    """A configuração que o cenário entrega ao motor."""
    _, nova_config, _ = cenario.transformar(vendas, config, TabelaCustos())
    return nova_config


# ---------------------------------------------------------------------------
# Preço
# ---------------------------------------------------------------------------


def test_o_aumento_de_preco_leva_a_rbt12_junto():
    """+5% no preço é +5% na receita, e a RBT12 é receita acumulada."""
    vendas = _vendas()
    nova = _config_do_cenario(CenarioPreco(Decimal("0.05")), vendas, NA_BEIRA)
    assert nova.rbt12 == Decimal("183750.00")  # 175.000 × 1,05


def test_o_aumento_de_preco_atravessa_a_faixa_e_a_aliquota_muda():
    """O efeito que a simulação antiga escondia inteiro.

    R$ 175.000 está na 1ª faixa do Anexo I (4,0000% efetivos). A R$
    183.750 a loja já está na 2ª, e a alíquota efetiva sobe. Sem isto o
    cenário tributava o faturamento maior pela alíquota do menor.
    """
    vendas = _vendas()
    nova = _config_do_cenario(CenarioPreco(Decimal("0.05")), vendas, NA_BEIRA)

    antes = aliquota_efetiva_simples(NA_BEIRA.rbt12, "I")
    depois = aliquota_efetiva_simples(nova.rbt12, "I")
    assert antes == Decimal("0.040000")
    assert depois > antes


def test_o_ganho_simulado_encolhe_quando_a_faixa_entra_na_conta():
    """A diferença chega ao número que vai para a tela.

    Este é o teste que dá o tamanho do defeito: o mesmo cenário, a única
    diferença sendo a RBT12 acompanhar ou não, e o impacto publicado
    muda. O congelado era o maior — errava a favor de recomendar o
    aumento.
    """
    vendas = _vendas()
    honesto = CenarioPreco(Decimal("0.05")).executar(vendas, NA_BEIRA)

    # o que a versão antiga publicava: mesma transformação, RBT12 parada
    novas, _, _ = CenarioPreco(Decimal("0.05")).transformar(
        vendas, NA_BEIRA, TabelaCustos()
    )
    congelado = decompor_margem(novas, NA_BEIRA)
    base = decompor_margem(vendas, NA_BEIRA)
    impacto_congelado = congelado.margem_pct - base.margem_pct

    assert honesto.impacto_pp < impacto_congelado
    assert impacto_congelado - honesto.impacto_pp > Decimal("0.05")


def test_a_baixa_de_preco_tambem_move_a_rbt12():
    """A proporção vale nas duas direções, não só para cima."""
    nova = _config_do_cenario(CenarioPreco(Decimal("-0.10")), _vendas(), NA_BEIRA)
    assert nova.rbt12 == Decimal("157500.00")  # 175.000 × 0,90


# ---------------------------------------------------------------------------
# Crescimento de canal
# ---------------------------------------------------------------------------


def test_crescer_um_canal_leva_a_rbt12_junto():
    """Dobrar o único canal dobra a receita — e a base do Simples."""
    vendas = _vendas()
    nova = _config_do_cenario(
        CenarioCrescimentoCanal("loja_propria", Decimal("1")), vendas, NA_BEIRA
    )
    assert nova.rbt12 == Decimal("350000.00")


def test_crescer_parte_de_um_canal_move_a_rbt12_na_proporcao_certa():
    """Metade das vendas num canal de dois: a RBT12 sobe o que a receita subiu."""
    vendas = _vendas(canal="loja_propria") + _vendas(canal="shopee")
    todas, nova, _ = CenarioCrescimentoCanal(
        "loja_propria", Decimal("0.50")
    ).transformar(vendas, NA_BEIRA, TabelaCustos())

    receita_base = sum(t.valor_bruto for t in vendas)
    receita_nova = sum(t.valor_bruto for t in todas)
    esperado = (NA_BEIRA.rbt12 * receita_nova / receita_base).quantize(Decimal("0.01"))
    assert nova.rbt12 == esperado
    assert nova.rbt12 > NA_BEIRA.rbt12


# ---------------------------------------------------------------------------
# Onde a proporção não se aplica
# ---------------------------------------------------------------------------


def test_a_devolucao_fica_de_fora_da_proporcao():
    """A base é a mesma que `rbt12_movel` acumula: art. 3º, § 1º.

    Venda devolvida não é receita bruta. Se ela entrasse na proporção, o
    cenário e o real estariam medindo coisas diferentes — e a
    inconsistência apareceria justamente na loja com muita devolução.

    O cenário de preço não serve para conferir isto: ele escala tudo,
    devolvida inclusive, e as duas contas dão a mesma razão. O de
    crescimento separa, porque só replica venda que ficou de pé.

    R$ 120.000 de pé e R$ 120.000 devolvidos. Dobrar o canal soma outros
    R$ 120.000 de pé:

    - pela receita **sem devoluções**: 240.000 ÷ 120.000 = **2,0** ✓
    - pela receita bruta com tudo:     360.000 ÷ 240.000 = 1,5 ✗
    """
    vendas = _vendas() + _vendas(devolvida=True, devolucao_status="Devolvida")
    nova = _config_do_cenario(
        CenarioCrescimentoCanal("loja_propria", Decimal("1")), vendas, NA_BEIRA
    )
    assert nova.rbt12 == Decimal("350000.00")  # 175.000 × 2, e não × 1,5


def test_no_mei_a_config_sai_intacta():
    """O DAS do MEI é fixo e não tem faixa (art. 18-A, § 3º, V)."""
    vendas = _vendas(valor="5000")
    nova = _config_do_cenario(CenarioPreco(Decimal("0.05")), vendas, MEI)
    assert nova is MEI


def test_cenario_que_nao_mexe_na_receita_nao_mexe_na_rbt12():
    """A comissão sobe, o faturamento não — nada a reproporcionalizar."""
    vendas = _vendas()
    _, nova, _ = CenarioComissao(Decimal("0.02")).transformar(
        vendas, NA_BEIRA, TabelaCustos()
    )
    assert nova.rbt12 == NA_BEIRA.rbt12


def test_receita_zerada_nao_vira_divisao_por_zero():
    """Sem receita não há proporção — e não há exceção."""
    vendas = [
        Transacao(
            data=date(2026, 1, 15),
            canal="loja_propria",
            valor_bruto=Decimal("0"),
            custo_produto=Decimal("0"),
            frete_pago=Decimal("0"),
        )
    ]
    nova = _config_do_cenario(CenarioPreco(Decimal("0.05")), vendas, NA_BEIRA)
    assert nova.rbt12 == NA_BEIRA.rbt12


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
