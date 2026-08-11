"""O teto do MEI media intensidade de venda e chamava aquilo de teto.

A conferência dividia ``TETO_MEI_ANUAL`` pelo número de meses **com
venda** no ano e recusava o cálculo acima disso. Duas coisas erradas
numa conta só.

A primeira: o divisor. Um MEI sazonal — barraca de praia, artesão de
Natal, cabana de festa junina — fatura em dois ou três meses e passa o
resto do ano parado. Com dois meses de venda, o "teto" virava R$ 13.500,
e uma loja que fecha o ano em R$ 35.000, folgadamente dentro do teto de
R$ 81.000, era recusada. O que a conta media era concentração de
faturamento, não enquadramento.

A segunda: o fundamento. A recusa citava o art. 18-A, § 2º, que é a
proporcionalidade do ano de **abertura** do MEI. Um arquivo de três
meses não reduz o teto de ninguém, e uma projeção apresentada com
parágrafo de lei ao lado passa por obrigação onde é só um alerta.

Agora a recusa é factual — a receita do ano passou de R$ 81.000 — e o
ritmo que projeta estouro futuro sai como aviso, com a conta feita e
válida ao lado.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.cenarios import rodar_cenarios_padrao
from carchuna.margem import (
    TETO_MEI_ANUAL,
    ConfigTributaria,
    Transacao,
    decompor_margem,
)

MEI = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76.00"))


def _venda(mes, valor, ano=2026, dia=15):
    return Transacao(
        data=date(ano, mes, dia),
        canal="loja_propria",
        valor_bruto=Decimal(valor),
        custo_produto=Decimal("0"),
        frete_pago=Decimal("0"),
    )


# ---------------------------------------------------------------------------
# O caso que a conta antiga recusava sem motivo
# ---------------------------------------------------------------------------


def test_mei_sazonal_calcula_normalmente():
    """Novembro e dezembro, R$ 35.000 no ano — menos da metade do teto.

    Este é o defeito com nome e sobrenome. Pela conta antiga: dois meses
    com venda, teto de R$ 13.500, recusa. Pela lei: R$ 35.000 está a
    R$ 46.000 do teto e não há nada de irregular a apontar.
    """
    vendas = [_venda(11, "20000"), _venda(12, "15000")]
    d = decompor_margem(vendas, MEI)

    assert d.receita_bruta == Decimal("35000.00")
    assert d.deducao("tributos").valor == Decimal("152.00")  # DAS fixo × 2 meses
    # 35.000 − 152 de DAS − 700 de adquirência (2% da loja própria)
    assert d.margem_liquida == Decimal("34148.00")


def test_o_sazonal_ainda_recebe_o_aviso_de_ritmo():
    """Calcular não é o mesmo que ficar calado.

    O ritmo de R$ 17.500/mês, se mantido, fecharia o ano bem acima do
    teto — e a loja precisa saber disso antes de dezembro. O aviso sai, e
    diz na própria frase que quem vende concentrado o dispara sem estar
    perto do teto: é heurística, não previsão.
    """
    d = decompor_margem([_venda(11, "20000"), _venda(12, "15000")], MEI)

    assert len(d.avisos) == 1
    assert "210.000" in d.avisos[0]  # 35.000 ÷ 2 × 12
    assert "concentrado em poucos meses" in d.avisos[0]


def test_o_span_conta_o_mes_vazio_do_meio():
    """A janela é do primeiro ao último mês, não os meses com venda.

    Janeiro e dezembro com venda e nada entre eles é um ano inteiro de
    arquivo, não dois meses de operação. Contar dois faria a projeção
    multiplicar por seis um faturamento que já é anual.
    """
    d = decompor_margem([_venda(1, "20000"), _venda(12, "15000")], MEI)
    assert d.receita_bruta == Decimal("35000.00")
    assert d.avisos == ()  # span de 12: nada a projetar


# ---------------------------------------------------------------------------
# A recusa que ficou, e só ela
# ---------------------------------------------------------------------------


def test_o_estouro_de_verdade_continua_recusado():
    """R$ 81.000 é o teto do art. 18-A, § 1º, e passar dele é fato."""
    vendas = [_venda(m, "7000") for m in range(1, 13)]  # R$ 84.000
    with pytest.raises(ValueError) as erro:
        decompor_margem(vendas, MEI)

    mensagem = str(erro.value)
    assert "84.000" in mensagem
    assert "81.000" in mensagem
    assert "art. 18-A" in mensagem
    assert "art. 3º, § 10" in mensagem  # desenquadramento retroativo


def test_a_recusa_nao_cita_mais_o_paragrafo_2o_como_fundamento():
    """§ 2º é o ano de abertura do MEI, não a janela do arquivo.

    Citar o parágrafo errado é pior que não citar: dá lastro legal a uma
    regra que a lei não tem, e num produto cujo argumento é "todo número
    vem da lei" isso é o defeito mais caro que existe.
    """
    vendas = [_venda(m, "7000") for m in range(1, 13)]
    with pytest.raises(ValueError) as erro:
        decompor_margem(vendas, MEI)
    assert "§ 2º" not in str(erro.value)

    projetado = decompor_margem([_venda(1, "20000")], MEI)
    assert projetado.avisos and "§ 2º" not in projetado.avisos[0]


def test_o_estouro_de_um_ano_nao_e_diluido_pelos_outros():
    """A conferência é ano a ano, e isso não mudou."""
    vendas = [_venda(m, "1000", ano=2025) for m in range(1, 13)]
    vendas += [_venda(m, "7000", ano=2026) for m in range(1, 13)]
    with pytest.raises(ValueError, match="2026"):
        decompor_margem(vendas, MEI)


def test_exatamente_no_teto_ainda_passa():
    """A recusa é para quem passou, não para quem chegou."""
    vendas = [_venda(m, "6750") for m in range(1, 13)]
    d = decompor_margem(vendas, MEI)
    assert d.receita_bruta == TETO_MEI_ANUAL
    assert d.avisos == ()


# ---------------------------------------------------------------------------
# O encontro com a bateria de cenários
# ---------------------------------------------------------------------------


def test_mei_quase_no_teto_roda_os_cenarios_sem_estourar():
    """R$ 79.200 no ano: dentro do teto, e +5% de preço passa dele.

    O cenário de preço leva o ano a R$ 83.160 e não tem resposta possível
    no MEI — mas isso é uma pergunta que não cabe, não um erro do
    arquivo. A bateria devolve os outros cenários em vez de sumir
    inteira, e a loja continua vendo as simulações que fazem sentido para
    ela.
    """
    vendas = [_venda(m, "6600") for m in range(1, 13)]  # R$ 79.200
    assert decompor_margem(vendas, MEI).receita_bruta == Decimal("79200.00")

    resultados = rodar_cenarios_padrao(vendas, MEI)

    assert resultados, "a bateria inteira sumiu por causa de um cenário"
    assert all("preço" not in r.nome.lower() for r in resultados)
    # e os que sobraram são números de verdade, não placeholders
    assert all(r.impacto_reais is not None for r in resultados)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
