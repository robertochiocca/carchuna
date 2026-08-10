"""Mês vazio no meio da janela: a Carchuna pergunta em vez de decidir.

A regra de fundo (ver `test_rbt12_movel.py`) é que mês sem lançamento é
dado ausente, e dado ausente não vira zero. Ela está certa e fica: errar
a RBT12 para baixo gera alíquota menor e imposto a menos, o que é risco
com o Fisco; cair na RBT12 informada é só inconveniente.

Mas cair em silêncio é o defeito. O lojista que de fato passou um mês sem
vender vê a alíquota informada valer por doze meses sem nada explicando o
porquê. Então: a lacuna é detectada, os meses são nomeados, e o lojista
pode confirmar que foram faturamento zero — e o resultado registra qual
caminho a conta tomou.

O que ele NÃO pode confirmar é um arquivo que começa tarde: ali não há
mês vazio para responder, há período que o arquivo nunca cobriu.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.margem import ConfigTributaria, Transacao
from carchuna.metricas import (
    lacunas_na_janela,
    margem_mensal,
    procedencia_rbt12,
    rbt12_movel,
)

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("4200000"))


def _vendas(meses: int, valor_mes: str, inicio=(2025, 1)) -> list[Transacao]:
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


def _sem(vendas, *meses_fora):
    return [v for v in vendas if (v.data.year, v.data.month) not in meses_fora]


# ---------------------------------------------------------------------------
# Detecção: qual mês está faltando, e é do tipo que dá para perguntar?
# ---------------------------------------------------------------------------


def test_a_lacuna_do_meio_e_detectada_e_nomeada():
    """Não basta saber que falta algo: a tela precisa dizer QUAL mês."""
    vendas = _sem(_vendas(13, "10000.00"), (2025, 6))
    assert lacunas_na_janela(vendas, "2026-01") == ("2025-06",)


def test_varias_lacunas_saem_em_ordem_cronologica():
    vendas = _sem(_vendas(13, "10000.00"), (2025, 3), (2025, 9))
    assert lacunas_na_janela(vendas, "2026-01") == ("2025-03", "2025-09")


def test_arquivo_que_comeca_tarde_nao_tem_lacuna_para_confirmar():
    """Seis meses de arquivo: não há mês vazio, há janela que não se alcança.

    A diferença importa porque a pergunta "foi mês sem faturamento?" não
    tem sentido aqui — o lojista não está sendo perguntado sobre um mês
    que o arquivo cobre e veio vazio, e sim sobre meio ano que o arquivo
    nunca teve.
    """
    vendas = _vendas(6, "10000.00", inicio=(2025, 7))
    assert lacunas_na_janela(vendas, "2026-01") == ()


def test_arquivo_completo_nao_acusa_lacuna_nenhuma():
    assert lacunas_na_janela(_vendas(13, "10000.00"), "2026-01") == ()


# ---------------------------------------------------------------------------
# A confirmação do lojista
# ---------------------------------------------------------------------------


def test_sem_confirmacao_a_lacuna_continua_devolvendo_none():
    """O padrão é o conservador: ignorar a pergunta mantém a informada."""
    vendas = _sem(_vendas(13, "10000.00"), (2025, 6))
    assert rbt12_movel(vendas, "2026-01") is None
    assert rbt12_movel(vendas, "2026-01", confirmar_lacunas=False) is None


def test_com_confirmacao_a_rbt12_sai_do_arquivo():
    """11 meses de R$ 10.000 e um mês confirmado como zero = R$ 110.000."""
    vendas = _sem(_vendas(13, "10000.00"), (2025, 6))
    assert rbt12_movel(vendas, "2026-01", confirmar_lacunas=True) == Decimal(
        "110000.00"
    )


def test_confirmar_nao_salva_arquivo_que_comeca_tarde():
    """A confirmação não é um interruptor geral de "pode chutar".

    Este é o teste que impede a opção de virar exatamente o defeito que
    ela existe para contornar: se confirmar valesse para tudo, um arquivo
    de 3 meses passaria a calcular uma RBT12 dez meses menor que a real.
    """
    vendas = _vendas(3, "10000.00", inicio=(2025, 11))
    assert rbt12_movel(vendas, "2026-01", confirmar_lacunas=True) is None


def test_confirmar_nao_salva_arquivo_que_comeca_tarde_e_tem_buraco():
    """Mistura dos dois: parte confirmável, parte não. Vence o não."""
    vendas = _sem(_vendas(8, "10000.00", inicio=(2025, 5)), (2025, 8))
    assert lacunas_na_janela(vendas, "2026-01") == ("2025-08",)
    assert rbt12_movel(vendas, "2026-01", confirmar_lacunas=True) is None


# ---------------------------------------------------------------------------
# O registro: o resultado diz qual caminho foi usado
# ---------------------------------------------------------------------------


def test_a_procedencia_diz_de_onde_veio_cada_mes():
    vendas = _sem(_vendas(14, "10000.00"), (2025, 6))
    serie = procedencia_rbt12(vendas)

    janeiro = serie["2026-01"]
    assert janeiro.origem == "informada"
    assert janeiro.lacunas == ("2025-06",)
    assert janeiro.confirmada is False
    assert janeiro.valor is None


def test_a_procedencia_registra_a_confirmacao_do_lojista():
    vendas = _sem(_vendas(14, "10000.00"), (2025, 6))
    janeiro = procedencia_rbt12(vendas, confirmar_lacunas=True)["2026-01"]

    assert janeiro.origem == "arquivo"
    assert janeiro.confirmada is True
    assert janeiro.lacunas == ("2025-06",)
    assert janeiro.valor == Decimal("110000.00")


def test_mes_sem_lacuna_nunca_aparece_como_confirmado():
    """`confirmada` só é verdade onde houve de fato o que confirmar."""
    janeiro = procedencia_rbt12(_vendas(14, "10000.00"), confirmar_lacunas=True)[
        "2026-01"
    ]
    assert janeiro.origem == "arquivo"
    assert janeiro.lacunas == ()
    assert janeiro.confirmada is False


def test_a_serie_mensal_muda_de_aliquota_quando_o_lojista_confirma():
    """O efeito na conta, não só no registro.

    Sem confirmar, 2026-01 é tributado pela RBT12 informada de
    R$ 4.200.000 → 10% efetivos. Confirmando, pela do arquivo
    (R$ 110.000, 1ª faixa do Anexo I) → 4%.
    """
    vendas = _sem(_vendas(13, "10000.00"), (2025, 6))

    sem = margem_mensal(vendas, CONFIG, usar_rbt12_movel=True)
    assert sem["2026-01"].aliquota_efetiva == Decimal("0.10")

    com = margem_mensal(vendas, CONFIG, usar_rbt12_movel=True, confirmar_lacunas=True)
    assert com["2026-01"].aliquota_efetiva == Decimal("0.04")


def test_confirmar_nao_muda_nada_em_arquivo_sem_lacuna():
    """A opção é inerte onde não há lacuna — não é um atalho global."""
    vendas = _vendas(14, "10000.00")
    assert margem_mensal(vendas, CONFIG, usar_rbt12_movel=True) == margem_mensal(
        vendas, CONFIG, usar_rbt12_movel=True, confirmar_lacunas=True
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
