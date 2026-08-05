"""RBT12 móvel: a alíquota do mês sai dos 12 meses ANTERIORES a ele.

O Simples não tem uma alíquota do ano: tem uma por mês de apuração,
calculada sobre a receita bruta acumulada nos doze meses anteriores
(LC 123/2006, art. 18, § 1º). Um lojista que cresceu 40% no ano paga,
em dezembro, uma alíquota maior do que a de janeiro — e a v1 usava a
mesma RBT12 informada em todos os meses da série, o que achatava
justamente a variação que o lojista quer ver.

A regra de honestidade aqui: **só se calcula a RBT12 do próprio arquivo
quando o arquivo cobre os 12 meses inteiros da janela.** Se ele começa
no meio, os meses que faltam não valem zero — a Carchuna não sabe se
não houve venda ou se o dado não veio. Nesses meses vale a RBT12 que o
lojista informou, e a série diz qual foi qual.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.margem import ConfigTributaria, Transacao
from carchuna.metricas import margem_mensal, rbt12_movel, rbt12_por_mes

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("4200000"))


def _vendas(meses: int, valor_mes: str, inicio=(2025, 1)) -> list[Transacao]:
    """Uma venda por mês, do valor pedido, a partir de `inicio`."""
    ano, mes = inicio
    vendas = []
    for i in range(meses):
        a, m = ano + (mes - 1 + i) // 12, (mes - 1 + i) % 12 + 1
        vendas.append(
            Transacao(
                data=date(a, m, 15),
                canal="shopee",
                valor_bruto=Decimal(valor_mes),
                custo_produto=Decimal("40.00"),
                frete_pago=Decimal("10.00"),
            )
        )
    return vendas


# ---------------------------------------------------------------------------
# A janela dos 12 meses anteriores
# ---------------------------------------------------------------------------


def test_rbt12_do_13o_mes_soma_os_12_anteriores():
    """13 meses de R$ 10.000: em janeiro/2026 a RBT12 é 12 × 10.000.

    Conta à mão: os doze meses anteriores a 2026-01 são 2025-01 até
    2025-12 = 12 × R$ 10.000,00 = R$ 120.000,00. O mês de apuração
    (2026-01) NÃO entra na própria janela.
    """
    vendas = _vendas(13, "10000.00", inicio=(2025, 1))
    assert rbt12_movel(vendas, "2026-01") == Decimal("120000.00")


def test_o_mes_de_apuracao_nao_entra_na_propria_janela():
    """Se entrasse, a de 2026-01 daria 130.000 em vez de 120.000."""
    vendas = _vendas(13, "10000.00", inicio=(2025, 1))
    assert rbt12_movel(vendas, "2026-01") != Decimal("130000.00")


def test_arquivo_que_nao_cobre_os_12_meses_devolve_none():
    """6 meses de arquivo: nenhum mês tem a janela inteira.

    Zero não é resposta: a Carchuna não sabe distinguir "não vendeu" de
    "o dado não veio". Devolver None é o que deixa quem chama usar a
    RBT12 informada e dizer isso na tela.
    """
    vendas = _vendas(6, "10000.00", inicio=(2025, 1))
    for mes in ("2025-01", "2025-06", "2025-07"):
        assert rbt12_movel(vendas, mes) is None


def test_o_primeiro_mes_com_janela_inteira_e_o_13o():
    """Fronteira exata: 2025-12 ainda não tem; 2026-01 tem."""
    vendas = _vendas(13, "10000.00", inicio=(2025, 1))
    assert rbt12_movel(vendas, "2025-12") is None
    assert rbt12_movel(vendas, "2026-01") == Decimal("120000.00")


def test_mes_sem_venda_dentro_da_janela_conta_como_zero():
    """Buraco no MEIO da janela é zero de verdade: o arquivo cobre o mês.

    Diferente do arquivo que começa tarde — aqui o lojista tem dado de
    antes e de depois, então o mês vazio é venda zero, não dado ausente.
    """
    vendas = _vendas(13, "10000.00", inicio=(2025, 1))
    # tira as vendas de 2025-06: sobram 11 meses com venda na janela
    vendas = [v for v in vendas if not (v.data.year == 2025 and v.data.month == 6)]
    assert rbt12_movel(vendas, "2026-01") == Decimal("110000.00")


def test_devolucao_sai_da_rbt12():
    """Receita bruta exclui venda cancelada (LC 123/2006, art. 3º, § 1º).

    12 meses de R$ 10.000 e um deles devolvido: 120.000 − 10.000 =
    R$ 110.000,00 — a mesma base que `decompor_margem` já usa.
    """
    vendas = _vendas(13, "10000.00", inicio=(2025, 1))
    vendas[3] = Transacao(
        data=vendas[3].data,
        canal=vendas[3].canal,
        valor_bruto=vendas[3].valor_bruto,
        custo_produto=vendas[3].custo_produto,
        frete_pago=vendas[3].frete_pago,
        devolvida=True,
    )
    assert rbt12_movel(vendas, "2026-01") == Decimal("110000.00")


# ---------------------------------------------------------------------------
# A série mês a mês
# ---------------------------------------------------------------------------


def test_rbt12_por_mes_marca_de_onde_veio_cada_valor():
    """Cada mês diz se a RBT12 saiu do arquivo ou da que o lojista informou."""
    vendas = _vendas(14, "10000.00", inicio=(2025, 1))
    serie = rbt12_por_mes(vendas)
    assert serie["2025-01"] is None  # janela incompleta
    assert serie["2026-01"] == Decimal("120000.00")
    assert serie["2026-02"] == Decimal("120000.00")  # 2025-02..2026-01
    assert list(serie) == sorted(serie)  # em ordem cronológica


def test_a_aliquota_muda_de_mes_para_mes_quando_o_lojista_cresce():
    """O ponto do item: quem cresce paga alíquota maior no fim do ano.

    Cenário conferido à mão, Anexo I, com a FAIXA identificada antes de
    cada conta (as faixas são 1ª ≤180.000, 2ª ≤360.000, 3ª ≤720.000).
    2025 inteiro a R$ 30.000/mês; 2026 a R$ 60.000/mês.

    - 2026-01: janela = 2025-01..2025-12 = 12 × 30.000 = R$ 360.000
      → 2ª faixa (nominal 7,3%, PD 5.940)
      efetiva = (360.000 × 0,073 − 5.940) / 360.000
              = (26.280 − 5.940) / 360.000 = 20.340/360.000 = 5,65%

    - 2026-02: janela = 2025-02..2026-01 = 11×30.000 + 60.000 = R$ 390.000
      → 3ª faixa (nominal 9,5%, PD 13.860)
      efetiva = (390.000 × 0,095 − 13.860) / 390.000
              = (37.050 − 13.860) / 390.000 = 23.190/390.000 ≈ 5,9462%

    - 2026-03: janela = 2025-03..2026-02 = 10×30.000 + 2×60.000 = R$ 420.000
      → 3ª faixa
      efetiva = (420.000 × 0,095 − 13.860) / 420.000
              = (39.900 − 13.860) / 420.000 = 26.040/420.000 = 6,20%

    A alíquota sobe mês a mês e ainda atravessa a fronteira da 2ª para a
    3ª faixa. Com a RBT12 fixa da v1 os três meses sairiam idênticos.
    """
    vendas = _vendas(12, "30000.00", inicio=(2025, 1)) + _vendas(
        3, "60000.00", inicio=(2026, 1)
    )
    meses = margem_mensal(vendas, CONFIG, rbt12_movel=True)

    jan = meses["2026-01"].aliquota_efetiva
    fev = meses["2026-02"].aliquota_efetiva
    mar = meses["2026-03"].aliquota_efetiva
    assert jan == Decimal("0.0565")
    assert mar == Decimal("0.0620")
    assert jan < fev < mar


def test_mes_sem_janela_usa_a_rbt12_informada_e_nao_inventa():
    """Sem os 12 meses, vale o que o lojista informou — nada de anualizar.

    RBT12 informada = R$ 4.200.000 (6ª faixa do Anexo I):
    efetiva = (4.200.000 × 19% − 378.000) / 4.200.000
            = (798.000 − 378.000) / 4.200.000 = 10% exatos.
    """
    vendas = _vendas(6, "10000.00", inicio=(2025, 1))
    meses = margem_mensal(vendas, CONFIG, rbt12_movel=True)
    for mes in meses.values():
        assert mes.aliquota_efetiva == Decimal("0.10")


def test_o_padrao_nao_muda_nada_para_quem_ja_usava():
    """`rbt12_movel=False` é o padrão: série idêntica à de antes."""
    vendas = _vendas(14, "10000.00", inicio=(2025, 1))
    antes = margem_mensal(vendas, CONFIG)
    com_flag = margem_mensal(vendas, CONFIG, rbt12_movel=False)
    assert antes == com_flag
    for mes in antes.values():
        assert mes.aliquota_efetiva == Decimal("0.10")


def test_a_invariante_contabil_vale_em_todo_mes_da_serie_movel():
    """Trocar a alíquota mês a mês não pode furar a conta em nenhum mês."""
    vendas = _vendas(15, "10000.00", inicio=(2025, 1))
    for mes, d in margem_mensal(vendas, CONFIG, rbt12_movel=True).items():
        deducoes = sum(x.valor for x in d.deducoes)
        assert deducoes + d.margem_liquida == d.receita_bruta, mes


def test_mei_e_arquivo_vazio_nao_quebram():
    """RBT12 móvel só faz sentido no Simples; os outros seguem iguais."""
    mei = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("75.60"))
    vendas = _vendas(13, "1000.00", inicio=(2025, 1))
    meses = margem_mensal(vendas, mei, rbt12_movel=True)
    assert all(d.aliquota_efetiva is None for d in meses.values())

    with pytest.raises(ValueError, match="vazio"):
        margem_mensal([], CONFIG, rbt12_movel=True)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
