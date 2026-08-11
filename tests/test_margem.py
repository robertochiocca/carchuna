"""Testes do coração da Carchuna: alíquota do Simples e decomposição.

A validação de referência (o "VaR ≈ 1.645·σ" daqui): alíquotas efetivas
da LC 123/2006 conferidas à mão pela fórmula oficial do art. 18, § 1º-A,
e uma venda-exemplo de R$ 100 decomposta manualmente.

Uso::

    pytest
    python tests/test_margem.py
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.margem import (
    TETO_SIMPLES,
    ConfigTributaria,
    TabelaCustos,
    Transacao,
    aliquota_efetiva_simples,
    decompor_margem,
)


def _venda(valor="100", canal="mercado_livre", **kwargs) -> Transacao:
    padrao = dict(
        data=date(2026, 5, 10),
        canal=canal,
        valor_bruto=Decimal(valor),
        custo_produto=Decimal("40"),
        frete_pago=Decimal("10"),
    )
    padrao.update(kwargs)
    return Transacao(**padrao)


CONFIG_SIMPLES = ConfigTributaria(
    regime="simples", anexo_simples="I", rbt12=Decimal("360000")
)


# ---------------------------------------------------------------------------
# Alíquota efetiva do Simples — casos calculados à mão (LC 123, art. 18 §1º-A)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rbt12", "anexo", "esperada"),
    [
        # 1ª faixa: alíquota nominal pura (PD = 0)
        ("180000", "I", "0.04"),
        # 2ª faixa: (360000×7,3% − 5940) / 360000 = 20340/360000 = 5,65%
        ("360000", "I", "0.0565"),
        # 3ª faixa: (720000×9,5% − 13860) / 720000 = 54540/720000 = 7,575%
        ("720000", "I", "0.07575"),
        # 6ª faixa (teto): (4,8M×19% − 378000) / 4,8M = 534000/4,8M = 11,125%
        ("4800000", "I", "0.11125"),
        # 6ª faixa: (4,2M×19% − 378000) / 4,2M = 420000/4,2M = 10% exatos
        ("4200000", "I", "0.10"),
        # Anexo III, 2ª faixa: (300000×11,2% − 9360) / 300000 = 8,08%
        ("300000", "III", "0.0808"),
        # Anexo II, 1ª faixa: nominal 4,5%
        ("100000", "II", "0.045"),
    ],
)
def test_aliquota_efetiva_casos_manuais(rbt12, anexo, esperada):
    assert aliquota_efetiva_simples(Decimal(rbt12), anexo) == Decimal(esperada)


def test_aliquota_efetiva_nunca_excede_nominal_e_cresce_ate_o_sublimite():
    """Até R$ 3,6M a efetiva é não-decrescente e contínua entre faixas.

    Na 6ª faixa a efetiva CAI (8,5% no início contra 11,875% no fim da
    5ª): não é bug — acima do sublimite de R$ 3,6M o ICMS/ISS saem da
    guia do Simples (LC 123/2006, arts. 19 e 20) e a 6ª faixa cobre só
    os tributos restantes. O teste documenta os dois regimes.
    """
    anterior = Decimal("0")
    for rbt12 in range(60000, 3600001, 60000):
        efetiva = aliquota_efetiva_simples(Decimal(rbt12), "I")
        assert efetiva <= Decimal("0.19")
        assert efetiva >= anterior
        anterior = efetiva
    # fronteira da 6ª faixa: degrau para baixo, conferido à mão
    assert aliquota_efetiva_simples(Decimal("3600000"), "I") == Decimal("0.11875")
    assert aliquota_efetiva_simples(Decimal("3600001"), "I") < Decimal("0.09")


def test_aliquota_rejeita_fora_do_regime():
    with pytest.raises(ValueError, match="teto do Simples"):
        aliquota_efetiva_simples(TETO_SIMPLES + 1, "I")
    with pytest.raises(ValueError, match="positivo"):
        aliquota_efetiva_simples(Decimal("0"), "I")
    with pytest.raises(ValueError, match="anexo"):
        aliquota_efetiva_simples(Decimal("100000"), "VI")


def test_dinheiro_rejeita_float():
    """Regra da trilogia: float nunca entra em campo monetário."""
    with pytest.raises(TypeError, match="float"):
        aliquota_efetiva_simples(360000.0, "I")
    with pytest.raises(TypeError, match="float"):
        _venda(valor_bruto=100.0)


# ---------------------------------------------------------------------------
# Decomposição — venda-exemplo de R$ 100 conferida manualmente
# ---------------------------------------------------------------------------


def test_decomposicao_venda_de_100_conferida_a_mao():
    """ML, Simples Anexo I RBT12 360k: 100 − 5,65 − 12 − 10 − 40 = 32,35."""
    resultado = decompor_margem([_venda("100")], CONFIG_SIMPLES, TabelaCustos())
    assert resultado.receita_bruta == Decimal("100.00")
    assert resultado.aliquota_efetiva == Decimal("0.0565")
    assert resultado.deducao("tributos").valor == Decimal("5.65")
    assert resultado.deducao("comissoes_canal").valor == Decimal("12.00")  # ML 12%
    assert resultado.deducao("adquirencia").valor == Decimal("0.00")  # embutida
    assert resultado.deducao("antecipacao").valor == Decimal("0.00")  # à vista
    assert resultado.deducao("frete").valor == Decimal("10.00")
    assert resultado.deducao("devolucoes").valor == Decimal("0.00")
    assert resultado.deducao("cmv").valor == Decimal("40.00")
    assert resultado.margem_liquida == Decimal("32.35")
    assert resultado.margem_pct == Decimal("32.35")


def test_invariante_soma_das_deducoes_mais_margem_igual_receita():
    """Invariante contábil: deduções + margem == receita, centavo a centavo."""
    from carchuna.dados import transacoes_sinteticas

    resultado = decompor_margem(
        transacoes_sinteticas(meses=3), CONFIG_SIMPLES, TabelaCustos()
    )
    soma = sum(d.valor for d in resultado.deducoes) + resultado.margem_liquida
    assert soma == resultado.receita_bruta


def test_propriedade_margem_nunca_excede_receita():
    from carchuna.dados import transacoes_sinteticas

    for seed in range(5):
        resultado = decompor_margem(
            transacoes_sinteticas(meses=2, seed=seed), CONFIG_SIMPLES
        )
        assert resultado.margem_liquida <= resultado.receita_bruta


def test_venda_devolvida_sai_da_base_do_simples_e_do_cmv():
    """LC 123, art. 3º, §1º: devolução não compõe a receita tributável."""
    vendas = [_venda("100"), _venda("100", devolvida=True)]
    resultado = decompor_margem(vendas, CONFIG_SIMPLES)
    # tributos só sobre os 100 não devolvidos; devolução vira dedução própria
    assert resultado.deducao("tributos").valor == Decimal("5.65")
    assert resultado.deducao("devolucoes").valor == Decimal("100.00")
    assert resultado.deducao("cmv").valor == Decimal("40.00")  # só a venda efetiva
    assert resultado.deducao("comissoes_canal").valor == Decimal("12.00")


def test_adquirencia_e_antecipacao_na_loja_propria():
    """Loja própria 300, prazo 30d: adquirência 2% = antecipação 2%×1 mês = 6,00."""
    venda = _venda("300", canal="loja_propria", prazo_recebimento_dias=30)
    tabela = TabelaCustos(
        taxa_adquirencia=Decimal("0.02"),
        taxa_antecipacao_mensal=Decimal("0.02"),
    )
    resultado = decompor_margem([venda], CONFIG_SIMPLES, tabela)
    assert resultado.deducao("adquirencia").valor == Decimal("6.00")
    assert resultado.deducao("antecipacao").valor == Decimal("6.00")


def test_comissao_cobrada_do_extrato_prevalece_sobre_tabela():
    venda = _venda("100", comissao_cobrada=Decimal("17.50"))
    resultado = decompor_margem([venda], CONFIG_SIMPLES)
    assert resultado.deducao("comissoes_canal").valor == Decimal("17.50")


def test_mei_paga_das_fixo_por_mes():
    config = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76.00"))
    vendas = [
        _venda("100", data=date(2026, 4, 5)),
        _venda("100", data=date(2026, 5, 5)),
    ]
    resultado = decompor_margem(vendas, config)
    assert resultado.deducao("tributos").valor == Decimal("152.00")  # 2 meses
    assert resultado.aliquota_efetiva is None


def test_presumido_e_roadmap_explicito():
    config = ConfigTributaria(regime="presumido")
    with pytest.raises(ValueError, match="roadmap"):
        decompor_margem([_venda("100")], config)


def test_validacoes_de_config_e_transacao():
    with pytest.raises(ValueError, match="regime"):
        ConfigTributaria(regime="lucro_real")
    with pytest.raises(ValueError, match="anexo"):
        ConfigTributaria(regime="simples", anexo_simples="X", rbt12=Decimal("1"))
    with pytest.raises(ValueError, match="rbt12"):
        ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("0"))
    with pytest.raises(ValueError, match="das_mei_mensal"):
        ConfigTributaria(regime="mei")
    with pytest.raises(ValueError, match="canal"):
        _venda("100", canal="aliexpress")
    with pytest.raises(ValueError, match="transacoes"):
        decompor_margem([], CONFIG_SIMPLES)


# ---------------------------------------------------------------------------
# Teto do MEI — o número que erra para cima
# ---------------------------------------------------------------------------


def _mei(valor_mensal, meses, ano=2026):
    from carchuna.margem import Transacao

    return [
        Transacao(
            data=date(ano, m, 15),
            canal="loja_propria",
            valor_bruto=Decimal(valor_mensal),
            custo_produto=Decimal("0"),
            frete_pago=Decimal("0"),
        )
        for m in range(1, meses + 1)
    ]


CONFIG_MEI = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76.00"))


def test_mei_acima_do_teto_anual_e_recusado_com_base_legal():
    """R$ 480 mil no MEI dava margem linda e nenhum aviso.

    É o pior número que este produto pode emitir: erra para cima, no campo
    em que o lojista mais confia, e o erro é de enquadramento — o custo do
    desenquadramento retroativo é ordens de grandeza maior que a diferença
    de imposto que a tela mostrava.
    """
    with pytest.raises(ValueError) as erro:
        decompor_margem(_mei("40000", 12), CONFIG_MEI)
    mensagem = str(erro.value)
    assert "81.000" in mensagem or "81000" in mensagem
    assert "art. 18-A" in mensagem
    assert "480.000" in mensagem or "480000" in mensagem


def test_mei_dentro_do_teto_continua_calculando():
    d = decompor_margem(_mei("6000", 12), CONFIG_MEI)
    assert d.receita_bruta == Decimal("72000.00")
    assert d.deducao("tributos").valor == Decimal("912.00")  # 76 × 12


def test_o_ritmo_que_projeta_estouro_avisa_e_nao_recusa():
    """Reescrito: antes isto era recusa, e a recusa estava errada.

    O teste anterior exigia `ValueError` para dois meses de R$ 10 mil,
    citando o art. 18-A, § 2º como fundamento de um teto proporcional à
    janela do arquivo. O § 2º é a proporcionalidade do ano de ABERTURA do
    MEI — um arquivo de dois meses não reduz o teto de ninguém, e quem
    ainda está dentro da lei não pode ter o cálculo recusado.

    R$ 20 mil em dois meses continua sendo informação útil: no ritmo, o
    ano fecharia em R$ 120 mil. Isso agora sai como aviso, com a conta
    feita e válida ao lado.
    """
    d = decompor_margem(_mei("10000", 2), CONFIG_MEI)
    assert d.receita_bruta == Decimal("20000.00")
    assert d.deducao("tributos").valor == Decimal("152.00")  # 76 × 2 meses

    assert len(d.avisos) == 1
    aviso = d.avisos[0]
    assert "120.000" in aviso
    assert "81.000" in aviso
    assert "regra de três" in aviso  # heurística de produto, e diz que é

    # o ritmo que projeta dentro do teto não avisa nada
    assert decompor_margem(_mei("6750", 2), CONFIG_MEI).avisos == ()


def test_o_teto_do_mei_e_conferido_ano_a_ano_e_nao_no_total_do_arquivo():
    """Reescrito: a regra de ano a ano ficou, o divisor do span mudou.

    O teto é anual, e somar o arquivo inteiro recusaria um MEI regular só
    por ele ter histórico longo. Isso continua valendo. O que mudou é o
    caso de baixo: dois anos parciais, cada um dentro do teto, em que a
    conferência antiga dividia o teto pelos meses COM VENDA e recusava.
    """
    dois_anos = _mei("5000", 12, ano=2025) + _mei("5000", 12, ano=2026)
    d = decompor_margem(dois_anos, CONFIG_MEI)
    assert d.receita_bruta == Decimal("120000.00")
    assert d.avisos == ()

    # cada ano com 3 meses de R$ 20 mil: R$ 60 mil por ano, dentro do teto
    parciais = _mei("20000", 3, ano=2025) + _mei("20000", 3, ano=2026)
    parcial = decompor_margem(parciais, CONFIG_MEI)
    assert parcial.receita_bruta == Decimal("120000.00")
    # e o aviso de ritmo sai um por ano, nomeando o ano
    assert len(parcial.avisos) == 2
    assert "2025" in parcial.avisos[0] and "2026" in parcial.avisos[1]


def test_o_simples_nao_e_afetado_pelo_teto_do_mei():
    assert decompor_margem(_mei("40000", 12), CONFIG_SIMPLES).receita_bruta == Decimal(
        "480000.00"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
