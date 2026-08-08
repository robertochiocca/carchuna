"""A cacheira somava um número e a manchete dizia outro.

Os pontos de margem de cada linha saíam da subtração de dois percentuais
já arredondados ao centésimo. Cada subtração dessas carrega meio centésimo
de erro de cada lado, e com sete deduções a soma da decomposição chegava a
ficar 0,02 ponto longe da variação anunciada no topo — em seis dos oito
meses da base de demonstração.

Dois centésimos não mudam decisão nenhuma. O que muda é a confiança de
quem senta com a calculadora, soma as linhas da tela e encontra um resto
que a tela não explica em lugar nenhum. Uma ferramenta cujo argumento é
"todo número é verificável" não pode ter um resto órfão.

A correção é fazer a conta em precisão cheia a partir dos reais e só
arredondar no fim, repartindo o resíduo por maior-resto. E, quando o
resíduo for grande demais para ser arredondamento, **não** repartir: ali
o defeito é outro, e fechar a soma na marra o esconderia.
"""

import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.analise import AnalisadorMargem
from carchuna.margem import ConfigTributaria, Transacao
from carchuna.metricas import (
    _pct_exato,
    _repartir_residuo_pp,
    conferir_aditividade_pp,
    explicar_variacao,
    margem_mensal,
)
from carchuna.validade import PRECISAO_PP, limiar_divergencia_pp

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _venda(mes, valor, custo="400", dia=10, frete="15"):
    return Transacao(
        data=date(2026, mes, dia),
        canal="shopee",
        valor_bruto=Decimal(valor),
        custo_produto=Decimal(custo),
        frete_pago=Decimal(frete),
    )


# ---------------------------------------------------------------------------
# A soma fecha na unha — não "dentro da tolerância"
# ---------------------------------------------------------------------------


def test_a_soma_das_linhas_e_exatamente_a_manchete():
    """`==`, e não `<= tolerância`: é essa a diferença que a fase trouxe.

    A conferência de aditividade que já existia aceitava até 0,05 p.p. de
    folga, e por isso passava tanto no código velho quanto no novo. Este
    teste é o que separa os dois.
    """
    mensal = AnalisadorMargem.demo(meses=8).mensal
    meses = list(mensal)
    assert len(meses) >= 3
    for mes in meses[1:]:
        exp = explicar_variacao(mensal, mes)
        soma = sum(c.delta_pp for c in exp.contribuicoes)
        assert soma == exp.delta_margem_pp, mes


def test_o_defeito_existia_de_fato_na_base_de_demonstracao():
    """Sem isto o teste acima poderia estar pinando uma coincidência.

    Refaz aqui a conta antiga — diferença de percentuais já arredondados —
    e exige que ela divirja em algum mês. Se um dia o motor mudar a ponto
    de as duas contas coincidirem sempre, este teste avisa que o outro
    parou de ter conteúdo.
    """
    mensal = AnalisadorMargem.demo(meses=8).mensal
    meses = list(mensal)
    divergencias = []
    for i, mes in enumerate(meses[1:], start=1):
        a, b = mensal[meses[i - 1]], mensal[mes]
        antiga = sum(
            -(d.pct_receita - a.deducao(d.nome).pct_receita) for d in b.deducoes
        )
        divergencias.append(abs(antiga - (b.margem_pct - a.margem_pct)))
    assert max(divergencias) > 0


def test_o_ponto_de_cada_linha_sai_dos_reais_e_nao_de_dois_arredondados():
    """O defeito concreto, com os números na mão.

    O CMV vai de 24,43% para 34,86% da receita. Subtrair os dois
    percentuais publicados dá −10,43; o valor exato é −10,437760…, cujo
    arredondamento correto é −10,44. E, como a soma tinha de fechar com a
    manchete de −13,14, o centésimo que faltava saía do frete, que era
    publicado em −2,71 no lugar de −2,70.

    Duas linhas erradas para o total fechar. Fazer a conta em precisão
    cheia acerta as duas: o resíduo passa a ir para quem de fato perdeu no
    arredondamento, em vez de ir para quem estiver à mão.
    """
    dados = [("2557.73", "624.75", "85.13"), ("3328.36", "1160.39", "200.58")]
    vendas = [
        Transacao(
            data=date(2026, mes, 10),
            canal="shopee",
            valor_bruto=Decimal(v),
            custo_produto=Decimal(c),
            frete_pago=Decimal(f),
        )
        for mes, (v, c, f) in zip((1, 2), dados, strict=True)
    ]
    mensal = margem_mensal(vendas, CONFIG)
    exp = explicar_variacao(mensal)
    por_nome = {c.nome: c.delta_pp for c in exp.contribuicoes}

    a, b = mensal["2026-01"], mensal["2026-02"]
    assert (a.deducao("cmv").pct_receita, b.deducao("cmv").pct_receita) == (
        Decimal("24.43"),
        Decimal("34.86"),
    )
    assert por_nome["cmv"] == Decimal("-10.44")  # a conta antiga dava -10,43
    assert por_nome["frete"] == Decimal("-2.70")  # e empurrava esta para -2,71
    assert sum(c.delta_pp for c in exp.contribuicoes) == exp.delta_margem_pp


def test_a_soma_fecha_tambem_com_prejuizo_nos_dois_meses():
    """A moeda que sobrevive ao zero também tem que fechar."""
    vendas = [_venda(1, "1000", custo="1200"), _venda(2, "1000", custo="1050")]
    exp = explicar_variacao(margem_mensal(vendas, CONFIG))
    assert sum(c.delta_pp for c in exp.contribuicoes) == exp.delta_margem_pp


def test_nenhuma_linha_e_distorcida_para_a_soma_fechar():
    """Fechar a soma não pode ser desculpa para publicar linha errada.

    Cada valor publicado fica a no máximo um centésimo do valor exato: o
    arredondamento normal, mais o centésimo que a linha eventualmente
    recebeu do resíduo. Sem esta conferência, "somar certo" poderia ser
    obtido empurrando tudo para uma linha só.
    """
    mensal = AnalisadorMargem.demo(meses=8).mensal
    meses = list(mensal)
    for i, mes in enumerate(meses[1:], start=1):
        a, b = mensal[meses[i - 1]], mensal[mes]
        exp = explicar_variacao(mensal, mes)
        for c in exp.contribuicoes:
            if c.nome == "receita":
                continue
            exato = _pct_exato(a.deducao(c.nome).valor, a.receita_bruta) - _pct_exato(
                b.deducao(c.nome).valor, b.receita_bruta
            )
            assert abs(c.delta_pp - exato) <= PRECISAO_PP, (mes, c.nome)


# ---------------------------------------------------------------------------
# Quem não pode receber resíduo
#
# Os dois testes desta seção são pinos do invariante publicado, não
# armadilhas: procurei em 120 mil pares de meses gerados ao acaso um dado
# em que tirar essas marcas mudasse algum número na tela, e não existe. O
# resíduo negativo, que é o único que escolheria uma linha de resto zero,
# só aparece quando alguma linha foi arredondada para cima — e aí é ela,
# não a linha parada, quem tem o resto extremo.
#
# Quem cobra o mecanismo é o teste de `_repartir_residuo_pp` mais abaixo,
# onde a marca é posta de propósito em quem o maior-resto escolheria.
# ---------------------------------------------------------------------------


def test_a_receita_continua_em_zero_estrutural():
    """Margem é razão: faturar mais pelo mesmo preço não move a margem.

    A receita entra na cachoeira em reais e com zero ponto. Esse zero não
    é um número arredondado que possa absorver centésimo — é a afirmação
    de que a receita não move a margem por si só. Recebê-los publicaria
    movimento onde não há nenhum.
    """
    mensal = AnalisadorMargem.demo(meses=8).mensal
    for mes in list(mensal)[1:]:
        exp = explicar_variacao(mensal, mes)
        por_nome = {c.nome: c.delta_pp for c in exp.contribuicoes}
        assert por_nome["receita"] == Decimal("0"), mes


def test_linha_parada_nao_ganha_centesimo_do_residuo():
    """Dedução idêntica nos dois meses tem que sair com zero cravado.

    Sem antecipação nos dois meses, a linha não se mexeu. Se o resíduo
    caísse ali, a tela diria que a antecipação mexeu a margem em 0,01 —
    e o lojista iria procurar uma antecipação que não existe.
    """
    vendas = [_venda(1, "1000", custo="333.33"), _venda(2, "1777.77", custo="611.11")]
    exp = explicar_variacao(margem_mensal(vendas, CONFIG))
    por_nome = {c.nome: c.delta_pp for c in exp.contribuicoes}
    assert por_nome["antecipacao"] == Decimal("0")
    assert por_nome["devolucoes"] == Decimal("0")
    assert sum(c.delta_pp for c in exp.contribuicoes) == exp.delta_margem_pp


# ---------------------------------------------------------------------------
# A repartição em si, e o limite dela
# ---------------------------------------------------------------------------


def test_mes_sem_receita_nao_vira_divisao_por_zero():
    """Sem faturamento não há percentual da receita — e não há erro.

    Espelha `_pct` do motor: devolve zero em vez de estourar. O mês sem
    receita não tem margem para comparar, e quem avisa isso é
    `conferir_receita`, não uma exceção no meio da cachoeira.
    """
    assert _pct_exato(Decimal("10"), Decimal("0")) == Decimal("0")


def test_o_centesimo_que_falta_vai_para_quem_mais_perdeu_arredondando():
    """Maior-resto: 0,334 perdeu mais no arredondamento que 0,333."""
    saida = _repartir_residuo_pp(
        [Decimal("0.334"), Decimal("0.333"), Decimal("0.333")],
        [True, True, True],
        Decimal("1.00"),
    )
    assert saida == [Decimal("0.34"), Decimal("0.33"), Decimal("0.33")]
    assert sum(saida) == Decimal("1.00")


def test_o_centesimo_que_sobra_sai_de_quem_mais_ganhou_arredondando():
    """A repartição funciona nas duas direções, não só para cima."""
    saida = _repartir_residuo_pp(
        [Decimal("0.336"), Decimal("0.336"), Decimal("0.336")],
        [True, True, True],
        Decimal("1.00"),
    )
    assert sum(saida) == Decimal("1.00")
    assert sorted(saida) == [Decimal("0.33"), Decimal("0.33"), Decimal("0.34")]


def test_quem_nao_e_ajustavel_e_pulado_mesmo_sendo_o_maior_resto():
    """A marca de "não ajustável" tem de vencer o critério do maior resto.

    Nos dois casos abaixo o índice 0 é quem o maior-resto escolheria — e
    é justamente ele que está marcado como fora. O centésimo tem de cair
    no índice 1. Se a marca fosse só decorativa, esta conferência não
    notaria a diferença, porque a soma fecharia dos dois jeitos.
    """
    para_cima = _repartir_residuo_pp(
        [Decimal("0.0049"), Decimal("0.001"), Decimal("0.001")],
        [False, True, True],
        Decimal("0.01"),
    )
    assert para_cima == [Decimal("0.00"), Decimal("0.01"), Decimal("0.00")]

    para_baixo = _repartir_residuo_pp(
        [Decimal("-0.0049"), Decimal("-0.001"), Decimal("-0.001")],
        [False, True, True],
        Decimal("-0.01"),
    )
    assert para_baixo == [Decimal("0.00"), Decimal("-0.01"), Decimal("0.00")]


def test_residuo_grande_demais_nao_e_repartido():
    """O portão que separa arredondamento de defeito.

    Três linhas que somam 0,012 não podem virar 5,00 por redistribuição.
    Um resíduo desse tamanho é driver faltando, e fechar a soma na marra
    esconderia justamente o que a aditividade existe para pegar.
    """
    exatos = [Decimal("0.004"), Decimal("0.004"), Decimal("0.004")]
    saida = _repartir_residuo_pp(exatos, [True, True, True], Decimal("5.00"))
    assert saida == [Decimal("0.00"), Decimal("0.00"), Decimal("0.00")]
    assert sum(saida) != Decimal("5.00")


def test_o_limite_da_repartição_e_um_centesimo_por_linha():
    """Na fronteira ela ainda reparte; um centésimo além, não.

    Três linhas ajustáveis absorvem até três centésimos. O quarto não tem
    onde cair sem tirar dois de alguém, e tirar dois já não é
    arredondamento.
    """
    exatos = [Decimal("0"), Decimal("0"), Decimal("0")]
    assert sum(_repartir_residuo_pp(exatos, [True] * 3, Decimal("0.03"))) == Decimal(
        "0.03"
    )
    assert sum(_repartir_residuo_pp(exatos, [True] * 3, Decimal("0.04"))) == Decimal(
        "0.00"
    )


# ---------------------------------------------------------------------------
# O limiar de divergência: o que é ruído depende de quem está olhando
# ---------------------------------------------------------------------------


def test_o_limiar_encolhe_junto_com_a_margem_da_loja():
    """Meio ponto é ruído a 30% de margem e é um sexto do resultado a 3%."""
    assert limiar_divergencia_pp(Decimal("30")) == Decimal("1.0")
    assert limiar_divergencia_pp(Decimal("10")) == Decimal("1.0")
    assert limiar_divergencia_pp(Decimal("3")) == Decimal("0.30")
    assert limiar_divergencia_pp(Decimal("0.5")) == Decimal("0.05")


def test_o_limiar_tem_teto_e_tem_piso():
    """Teto: a loja gorda não aceita qualquer coisa em nome da folga.

    Piso: não se exige do número precisão menor que a casa publicada.
    """
    assert limiar_divergencia_pp(Decimal("90")) == Decimal("1.0")
    assert limiar_divergencia_pp(Decimal("0")) == PRECISAO_PP
    assert limiar_divergencia_pp(Decimal("0.01")) == PRECISAO_PP


def test_prejuizo_entra_em_modulo():
    """Num mês negativo o que importa é a ordem de grandeza, não o lado."""
    assert limiar_divergencia_pp(Decimal("-3")) == limiar_divergencia_pp(Decimal("3"))


def test_a_mesma_divergencia_passa_numa_loja_e_para_na_outra():
    """É este o motivo do limiar variável, e não um limiar fixo qualquer.

    Meio ponto de decomposição sem explicação: para quem fecha o mês em
    30%, é arredondamento de tela. Para quem fecha em 3%, é um sexto do
    lucro do mês sem dono — e essa loja precisa saber antes de agir.
    """
    exp = explicar_variacao(AnalisadorMargem.demo(meses=4).mensal)
    torto = replace(
        exp,
        contribuicoes=tuple(
            replace(c, delta_pp=c.delta_pp + Decimal("0.5")) if c.nome == "cmv" else c
            for c in exp.contribuicoes
        ),
    )
    assert conferir_aditividade_pp(replace(torto, margem_base_pct=Decimal("30"))).ok
    magra = conferir_aditividade_pp(replace(torto, margem_base_pct=Decimal("3")))
    assert not magra.ok
    assert magra.valor == Decimal("0.5")


def test_a_conferencia_passa_na_base_real():
    mensal = AnalisadorMargem.demo(meses=8).mensal
    for mes in list(mensal)[1:]:
        resultado = conferir_aditividade_pp(explicar_variacao(mensal, mes))
        assert resultado.ok, (mes, resultado.motivo)
        assert resultado.valor == Decimal("0")


def test_a_recusa_diz_os_dois_numeros_e_o_limiar():
    """Motivo sem número é motivo que não dá para conferir."""
    exp = explicar_variacao(AnalisadorMargem.demo(meses=4).mensal)
    maior = max(exp.contribuicoes, key=lambda c: abs(c.delta_pp)).nome
    sem_o_maior = replace(
        exp,
        margem_base_pct=Decimal("2"),
        contribuicoes=tuple(c for c in exp.contribuicoes if c.nome != maior),
    )
    resultado = conferir_aditividade_pp(sem_o_maior)
    assert resultado.status == "implausivel"
    assert str(exp.delta_margem_pp) in resultado.motivo
    assert str(limiar_divergencia_pp(Decimal("2"))) in resultado.motivo


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
