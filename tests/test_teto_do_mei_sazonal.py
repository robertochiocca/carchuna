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
    TETO_MEI_COM_EXCESSO,
    ConfigTributaria,
    Transacao,
    decompor_margem,
)

MEI = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76.00"))


def _venda(mes, valor, ano=2026, dia=15, devolvida=False):
    return Transacao(
        data=date(ano, mes, dia),
        canal="loja_propria",
        valor_bruto=Decimal(valor),
        custo_produto=Decimal("0"),
        frete_pago=Decimal("0"),
        devolvida=devolvida,
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
#
# A fronteira da recusa subiu de R$ 81.000 para R$ 97.200: excesso de até
# 20% não desenquadra no ato (art. 18-A, § 7º), e recusar ali negava um
# número que continuava válido. As fixtures destes testes subiram junto —
# o que eles afirmam é sobre a recusa, e a recusa mudou de lugar.
# ---------------------------------------------------------------------------


def test_o_estouro_de_verdade_continua_recusado():
    """Acima de 20% de excesso o desenquadramento retroage, e aí sim recusa."""
    vendas = [_venda(m, "8500") for m in range(1, 13)]  # R$ 102.000
    with pytest.raises(ValueError) as erro:
        decompor_margem(vendas, MEI)

    mensagem = str(erro.value)
    assert "102.000" in mensagem
    assert "81.000" in mensagem
    assert "97.200" in mensagem  # o corte de fato
    assert "art. 18-A" in mensagem
    assert "art. 3º, § 10" in mensagem  # desenquadramento retroativo


def test_a_recusa_nao_cita_mais_o_paragrafo_2o_como_fundamento():
    """§ 2º é o ano de abertura do MEI, não a janela do arquivo.

    Citar o parágrafo errado é pior que não citar: dá lastro legal a uma
    regra que a lei não tem, e num produto cujo argumento é "todo número
    vem da lei" isso é o defeito mais caro que existe.
    """
    vendas = [_venda(m, "8500") for m in range(1, 13)]
    with pytest.raises(ValueError) as erro:
        decompor_margem(vendas, MEI)
    assert "§ 2º" not in str(erro.value)

    projetado = decompor_margem([_venda(1, "20000")], MEI)
    assert projetado.avisos and "§ 2º" not in projetado.avisos[0]


def test_o_estouro_de_um_ano_nao_e_diluido_pelos_outros():
    """A conferência é ano a ano, e isso não mudou."""
    vendas = [_venda(m, "1000", ano=2025) for m in range(1, 13)]
    vendas += [_venda(m, "8500", ano=2026) for m in range(1, 13)]
    with pytest.raises(ValueError, match="2026"):
        decompor_margem(vendas, MEI)


def test_exatamente_no_teto_ainda_passa():
    """A recusa é para quem passou, não para quem chegou."""
    vendas = [_venda(m, "6750") for m in range(1, 13)]
    d = decompor_margem(vendas, MEI)
    assert d.receita_bruta == TETO_MEI_ANUAL
    assert d.avisos == ()


# ---------------------------------------------------------------------------
# Devolução não compõe a receita bruta (art. 3º, § 1º)
# ---------------------------------------------------------------------------


def test_venda_devolvida_nao_conta_para_o_teto():
    """O caso que bloqueava a análise inteira de quem estava dentro da lei.

    R$ 83.000 na coluna de valor, R$ 5.000 devolvidos: a receita bruta é
    R$ 78.000, três mil abaixo do teto. Somar a devolvida contradizia o
    art. 3º, § 1º — o mesmo dispositivo que este módulo já cita para a
    base do Simples e que a `rbt12_movel` respeita — e recusava o cálculo
    de um MEI perfeitamente regular.
    """
    vendas = [_venda(m, "6500") for m in range(1, 13)]  # R$ 78.000
    vendas.append(_venda(6, "5000", devolvida=True))  # R$ 83.000 na coluna

    d = decompor_margem(vendas, MEI)  # não levanta

    assert d.receita_bruta == Decimal("83000.00")  # a bruta inclui, e deve
    assert d.avisos == ()  # mas o teto olha os R$ 78.000


def test_a_devolucao_tambem_sai_da_projecao():
    """A regra de três do ritmo mede o que ficou, não o que voltou.

    Sem isto, um mês com muita devolução inflaria a projeção e dispararia
    aviso de estouro para quem está longe dele.
    """
    vendas = [_venda(1, "20000"), _venda(2, "20000", devolvida=True)]
    d = decompor_margem(vendas, MEI)

    # R$ 20.000 líquidos em 2 meses de span → projeção de R$ 120.000
    assert len(d.avisos) == 1
    assert "120.000" in d.avisos[0]


# ---------------------------------------------------------------------------
# A faixa dos 20%: calcula e avisa, não recusa
# ---------------------------------------------------------------------------


def test_a_faixa_dos_vinte_por_cento_calcula_e_avisa():
    """R$ 90.000: passou do teto, mas segue MEI até 31/12.

    A recusa antiga era larga demais. Excesso de até 20% não desenquadra
    no ato: o DAS fixo continua sendo o imposto daquele mês e a margem do
    período está certa. Bloquear a análise aqui era negar um número
    válido a quem ainda é MEI.
    """
    vendas = [_venda(m, "7500") for m in range(1, 13)]  # R$ 90.000
    d = decompor_margem(vendas, MEI)  # não levanta

    assert d.receita_bruta == Decimal("90000.00")
    assert d.deducao("tributos").valor == Decimal("912.00")  # 76 × 12, DAS fixo

    (aviso,) = d.avisos
    assert "90.000" in aviso
    assert "81.000" in aviso
    assert "31/12" in aviso
    assert "art. 18-A, § 7º" in aviso


def test_o_aviso_diz_que_nao_calcula_o_complementar():
    """Há tributo sobre o excesso, e a Carchuna não sabe qual.

    Este é o ponto em que um produto apressado inventaria um número. O
    aviso diz que o recolhimento existe, diz que ela não o calcula, e
    manda ao contador — sem estimar.
    """
    vendas = [_venda(m, "7500") for m in range(1, 13)]
    (aviso,) = decompor_margem(vendas, MEI).avisos

    assert "não calcula" in aviso
    assert "contador" in aviso


def test_um_centavo_acima_do_teto_ja_avisa_e_nao_recusa():
    vendas = [_venda(m, "6750") for m in range(1, 13)]  # R$ 81.000 exatos
    vendas.append(_venda(12, "0.01"))

    d = decompor_margem(vendas, MEI)
    assert len(d.avisos) == 1
    assert "não calcula" in d.avisos[0]


def test_exatamente_no_corte_dos_vinte_por_cento_ainda_e_aviso():
    """R$ 97.200 é o limite, e ele também é inclusivo.

    "Excesso superior a 20%" é o que antecipa o desenquadramento. Em cima
    dos 20% o excesso não é superior a eles.
    """
    assert Decimal("97200") == TETO_MEI_COM_EXCESSO
    vendas = [_venda(m, "8100") for m in range(1, 13)]  # R$ 97.200

    d = decompor_margem(vendas, MEI)
    assert len(d.avisos) == 1


def test_um_centavo_acima_do_corte_ja_recusa():
    vendas = [_venda(m, "8100") for m in range(1, 13)]
    vendas.append(_venda(12, "0.01"))
    with pytest.raises(ValueError, match="97.200"):
        decompor_margem(vendas, MEI)


# ---------------------------------------------------------------------------
# O encontro com a bateria de cenários
# ---------------------------------------------------------------------------


def test_mei_quase_no_teto_agora_ve_o_cenario_de_preco():
    """R$ 79.200 no ano: +5% leva a R$ 83.160, que é faixa de aviso.

    Este teste mudou de resposta junto com a lei que ele descreve. Antes,
    R$ 83.160 passava do teto e o cenário sumia da bateria — pergunta sem
    resposta possível. Agora R$ 83.160 é excesso de menos de 3%: o
    lojista segue MEI até dezembro, o DAS fixo continua sendo o imposto
    do mês, e a simulação tem resposta. Ela sai.

    É a pergunta mais útil que um MEI a R$ 79.200 pode fazer — "e se eu
    subir os preços?" —, e ela vinha voltando vazia.
    """
    vendas = [_venda(m, "6600") for m in range(1, 13)]  # R$ 79.200
    assert decompor_margem(vendas, MEI).receita_bruta == Decimal("79200.00")

    resultados = rodar_cenarios_padrao(vendas, MEI)

    preco = [r for r in resultados if "preço" in r.nome.lower()]
    assert len(preco) == 1, "o cenário de preço não voltou para a bateria"
    assert preco[0].impacto_reais is not None
    assert all(r.impacto_reais is not None for r in resultados)


def test_o_cenario_que_passa_dos_vinte_por_cento_continua_omitido():
    """A omissão não sumiu: subiu de lugar, junto com a recusa.

    R$ 96.000 no ano está na faixa do aviso (acima do teto, dentro dos
    20%) e calcula. Subir 5% leva a R$ 100.800, acima de R$ 97.200 — ali
    o desenquadramento retroage e não há margem que a Carchuna saiba
    calcular. O cenário sai da lista, e os outros continuam.
    """
    vendas = [_venda(m, "8000") for m in range(1, 13)]  # R$ 96.000
    base = decompor_margem(vendas, MEI)
    assert base.receita_bruta == Decimal("96000.00")
    assert len(base.avisos) == 1  # está na faixa do aviso

    resultados = rodar_cenarios_padrao(vendas, MEI)

    assert resultados, "a bateria inteira sumiu por causa de um cenário"
    assert all("preço" not in r.nome.lower() for r in resultados)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
