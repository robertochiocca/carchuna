"""Nem toda melhora de margem foi mérito de alguém.

A cachoeira dizia *o que* mudou — "o tributo pesou 0,83 ponto a mais" — e
parava ali. Duas causas muito diferentes produzem essa mesma linha, e o
lojista precisa distingui-las porque a ação que cabe em cada uma é o
oposto da outra:

- **diluição do custo fixo.** No MEI o DAS é valor fixo por mês (LC
  123/2006, art. 18-A, § 3º, V). Faturar o dobro faz o DAS pesar metade,
  e a margem sobe sem que nada tenha melhorado na operação. Quem lê a
  melhora como resultado de uma decisão vai repetir a decisão errada.
- **faixa da RBT12.** No Simples a alíquota efetiva do mês vem da receita
  dos doze meses anteriores (art. 18, § 1º e § 1º-A). Vender mais faz a
  margem cair sozinha, e quem lê a queda como problema de operação vai
  procurar um defeito que não existe.

Os dois são recorte da linha do tributo, não linha nova: entram em
``estruturais``, fora da soma da cachoeira, porque somá-los junto
contaria o mesmo efeito duas vezes.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.margem import ConfigTributaria, Transacao, decompor_margem
from carchuna.metricas import _drivers_estruturais, explicar_variacao, margem_mensal

MEI = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("75.60"))
SIMPLES = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("180000"))


def _venda(ano, mes, valor, canal="loja_propria", **extra):
    return Transacao(
        data=date(ano, mes, 15),
        canal=canal,
        valor_bruto=Decimal(valor),
        custo_produto=Decimal("0"),
        frete_pago=Decimal("0"),
        **extra,
    )


def _por_nome(explicacao):
    return {d.nome: d for d in explicacao.estruturais}


# ---------------------------------------------------------------------------
# Diluição do custo fixo — o regime em que ela é a história inteira
# ---------------------------------------------------------------------------


def test_o_das_fixo_diluido_por_faturamento_maior_ganha_nome():
    """R$ 75,60 sobre R$ 3.000 é 2,52%; sobre R$ 6.000 é 1,26%.

    A margem sobe 1,26 ponto sem que nada tenha mudado na operação: o
    mesmo produto, o mesmo custo, o mesmo canal. Sem este driver, o
    lojista lê a linha do tributo e não tem como saber que 100% do
    movimento é tamanho do mês.
    """
    mensal = margem_mensal([_venda(2026, 1, "3000"), _venda(2026, 2, "6000")], MEI)
    exp = explicar_variacao(mensal)

    driver = _por_nome(exp)["diluicao_fixo"]
    assert driver.delta_pp == Decimal("1.26")
    assert driver.delta_pp == exp.delta_margem_pp  # aqui é a variação inteira


def test_faturar_menos_concentra_o_custo_fixo_e_o_texto_diz_isso():
    """O mesmo mecanismo na direção que dói — e a frase acompanha."""
    mensal = margem_mensal([_venda(2026, 1, "6000"), _venda(2026, 2, "3000")], MEI)
    driver = _por_nome(explicar_variacao(mensal))["diluicao_fixo"]

    assert driver.delta_pp == Decimal("-1.26")
    assert "concentrou" in driver.explicacao
    assert "75.60" in driver.explicacao


def test_sem_mudanca_de_faturamento_o_texto_nao_inventa_movimento():
    """Zero com explicação de zero, não zero com frase de quem se mexeu.

    Publicar "faturar mais diluiu o custo" num par de meses idênticos
    seria uma frase falsa carregando um número certo — o tipo de coisa
    que o lojista lê e a planilha desmente.
    """
    mensal = margem_mensal([_venda(2026, 1, "5000"), _venda(2026, 2, "5000")], MEI)
    driver = _por_nome(explicar_variacao(mensal))["diluicao_fixo"]

    assert driver.delta_pp == Decimal("0.00")
    assert "nada da variação da margem veio de diluição" in driver.explicacao


# ---------------------------------------------------------------------------
# Faixa da RBT12 — o regime em que diluição não existe
# ---------------------------------------------------------------------------


def _doze_meses_de(valor):
    return [_venda(2025, m, valor) for m in range(1, 13)]


def test_a_troca_de_faixa_da_rbt12_ganha_nome():
    """RBT12 de R$ 240.000 leva a 1ª faixa do Anexo I para a 2ª.

    A alíquota efetiva sai de 4,0000% para 4,8250%, e a margem de janeiro
    cai 0,83 ponto por isso — não por nada que tenha sido vendido em
    janeiro. O mês foi idêntico ao anterior em preço, custo e canal.
    """
    vendas = _doze_meses_de("20000") + [_venda(2026, 1, "20000")]
    mensal = margem_mensal(vendas, SIMPLES, usar_rbt12_movel=True)
    assert mensal["2025-12"].aliquota_efetiva == Decimal("0.040000")
    assert mensal["2026-01"].aliquota_efetiva == Decimal("0.048250")

    driver = _por_nome(explicar_variacao(mensal, "2026-01"))["faixa_rbt12"]
    assert driver.delta_pp == Decimal("-0.83")  # −(4,8250% − 4,0000%)
    assert "4.00%" in driver.explicacao and "4.82%" in driver.explicacao
    assert "art. 18" in driver.explicacao


def test_a_devolucao_encolhe_o_efeito_da_faixa():
    """A alíquota incide sobre receita menos devoluções (art. 3º, § 1º).

    Com um quarto do mês devolvido, a base tributável é 75% da receita, e
    o efeito da mesma troca de faixa sobre a margem é 75% do anterior.
    Sem o fator da base, o driver diria −0,83 num mês em que o tributo
    nem chegou a incidir sobre tudo.
    """
    vendas = _doze_meses_de("20000") + [
        _venda(2026, 1, "15000"),
        _venda(2026, 1, "5000", devolvida=True, devolucao_status="Devolvida"),
    ]
    mensal = margem_mensal(vendas, SIMPLES, usar_rbt12_movel=True)
    driver = _por_nome(explicar_variacao(mensal, "2026-01"))["faixa_rbt12"]

    assert driver.delta_pp == Decimal("-0.62")  # 75% de −0,825 = −0,61875


def test_faixa_parada_nao_vira_frase_de_faixa_que_mudou():
    vendas = _doze_meses_de("20000") + [_venda(2026, m, "20000") for m in (1, 2)]
    mensal = margem_mensal(vendas, SIMPLES, usar_rbt12_movel=True)
    driver = _por_nome(explicar_variacao(mensal, "2026-02"))["faixa_rbt12"]

    assert driver.delta_pp == Decimal("0.00")
    assert "não mudou de faixa" in driver.explicacao


# ---------------------------------------------------------------------------
# Cada driver só no regime em que ele existe
# ---------------------------------------------------------------------------


def test_no_simples_nao_ha_diluicao_para_publicar():
    """Tributo proporcional não dilui: faturar o dobro paga o dobro.

    Publicar "diluição: 0,00" aqui sugeriria que a conta olhou e não
    achou nada, quando na verdade a conta não se aplica.
    """
    mensal = margem_mensal([_venda(2026, 1, "3000"), _venda(2026, 2, "6000")], SIMPLES)
    nomes = _por_nome(explicar_variacao(mensal))
    assert "diluicao_fixo" not in nomes
    assert "faixa_rbt12" in nomes


def test_no_mei_nao_ha_faixa_para_publicar():
    """O DAS do MEI não tem alíquota — não há faixa que possa mudar."""
    mensal = margem_mensal([_venda(2026, 1, "3000"), _venda(2026, 2, "6000")], MEI)
    nomes = _por_nome(explicar_variacao(mensal))
    assert "faixa_rbt12" not in nomes
    assert "diluicao_fixo" in nomes


def test_mes_sem_faturamento_nao_gera_driver():
    """Os dois recortes dividem pela receita — sem ela não há o que dizer.

    Diluição é custo fixo sobre faturamento e faixa é tributo sobre
    faturamento. Num mês zerado nenhuma das duas tem denominador, e sair
    calado é a resposta certa: quem avisa que o mês não tem margem para
    comparar é `conferir_receita`, e não um p.p. inventado aqui.
    """
    zerado = decompor_margem([_venda(2026, 1, "0")], MEI)
    assert zerado.receita_bruta == Decimal("0.00")
    assert _drivers_estruturais(zerado, zerado) == ()


def test_regimes_diferentes_nos_dois_meses_nao_geram_driver():
    """Comparar MEI com Simples precisa de outra conversa, não de um p.p.

    Nenhum dos dois recortes faz sentido atravessando o regime: no MEI o
    tributo não tem alíquota, no Simples não tem parte fixa. Sair calado
    aqui é melhor que sair com um número que não quer dizer nada.
    """
    mei = decompor_margem([_venda(2026, 1, "3000")], MEI)
    simples = decompor_margem([_venda(2026, 2, "3000")], SIMPLES)
    assert _drivers_estruturais(mei, simples) == ()
    assert _drivers_estruturais(simples, mei) == ()


# ---------------------------------------------------------------------------
# O recorte não pode ser contado duas vezes
# ---------------------------------------------------------------------------


def test_os_drivers_estruturais_ficam_fora_da_soma_da_cachoeira():
    """São recorte da linha do tributo, que já está na soma.

    Somá-los junto contaria o mesmo efeito duas vezes e quebraria a
    aditividade que a fase inteira existe para garantir.
    """
    mensal = margem_mensal([_venda(2026, 1, "3000"), _venda(2026, 2, "6000")], MEI)
    exp = explicar_variacao(mensal)

    assert sum(c.delta_pp for c in exp.contribuicoes) == exp.delta_margem_pp
    assert exp.estruturais  # e existem, senão o teste acima é vazio
    assert {d.nome for d in exp.estruturais}.isdisjoint(
        {c.nome for c in exp.contribuicoes}
    )


def test_o_recorte_nao_pode_passar_do_movimento_que_ele_recorta():
    """Diluição explica parte da linha do tributo, nunca mais que ela.

    No MEI a diluição é a história inteira e os dois números coincidem;
    no Simples a faixa é parte do movimento. Em nenhum dos casos o
    recorte pode ter módulo maior que a linha, tirado o centésimo de
    arredondamento que cada um leva por conta própria.
    """
    vendas = _doze_meses_de("20000") + [_venda(2026, 1, "24000")]
    mensal = margem_mensal(vendas, SIMPLES, usar_rbt12_movel=True)
    exp = explicar_variacao(mensal, "2026-01")

    tributo = next(c for c in exp.contribuicoes if c.nome == "tributos")
    faixa = _por_nome(exp)["faixa_rbt12"]
    assert abs(faixa.delta_pp) <= abs(tributo.delta_pp) + Decimal("0.01")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
