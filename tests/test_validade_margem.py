"""Os dois defeitos do motor, virados fixture permanente.

Cada caso aqui existe porque o motor já respondeu errado — ou respondeu
número onde não havia número — e não podia. São dois defeitos com a mesma
raiz: **o motor nunca se recusava a responder**.

1. variação percentual de lucro com base negativa inverte o sinal, e
   melhorar de −100 para −50 saía como queda de 50%;
2. a identidade contábil não podia falhar, então uma margem de −1854%
   atravessava a decomposição inteira sem um ruído.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.analise import AnalisadorMargem
from carchuna.margem import (
    TOLERANCIA_RECONCILIACAO,
    ConfigTributaria,
    TabelaCustos,
    Transacao,
    conferir_plausibilidade,
    decompor_margem,
    reconciliar,
)
from carchuna.metricas import explicar_variacao, margem_mensal
from carchuna.validade import (
    TOLERANCIA_ADITIVIDADE_PP,
    Resultado,
    conferir_receita,
    variacao_percentual,
)

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))
CANAIS = ("mercado_livre", "shopee", "amazon", "loja_propria", "fisico")


def _venda(mes, bruto, *, custo="0", frete="0", comissao=None, dia=15, devolvida=False):
    return Transacao(
        data=date(2026, mes, dia),
        canal="mercado_livre",
        valor_bruto=Decimal(bruto),
        custo_produto=Decimal(custo),
        frete_pago=Decimal(frete),
        comissao_cobrada=None if comissao is None else Decimal(comissao),
        devolvida=devolvida,
    )


def _mensal(vendas):
    return margem_mensal(vendas, CONFIG)


# ---------------------------------------------------------------------------
# 1. Prejuízo nos dois períodos, com melhora — nunca reportar piora
# ---------------------------------------------------------------------------


def test_melhora_dentro_do_prejuizo_nao_pode_ser_reportada_como_piora():
    """O defeito original, no caso mais direto.

    Dois meses no vermelho, o segundo menos vermelho que o primeiro. O
    percentual de lucro dividia por uma base negativa e devolvia um número
    com o sinal trocado, que se lia como piora. Agora ele se recusa, e
    quem responde são as duas moedas que atravessam o zero sem mentir:
    reais e pontos de margem.
    """
    vendas = [
        _venda(1, "1000", custo="1200"),  # prejuízo grande
        _venda(2, "1000", custo="1050"),  # prejuízo menor: MELHOROU
    ]
    exp = explicar_variacao(_mensal(vendas))

    assert exp.delta_lucro > 0, "o lucro subiu: menos prejuízo é melhora"
    assert exp.delta_margem_pp > 0, "a margem subiu, em pontos"

    assert not exp.var_lucro_pct.ok
    assert exp.var_lucro_pct.status == "indefinido"
    assert exp.var_lucro_pct.valor is None
    assert "negativo" in exp.var_lucro_pct.motivo
    assert "inverte o sinal" in exp.var_lucro_pct.motivo

    # e a frase que o lojista lê diz "subiu", não "caiu"
    assert "o lucro subiu" in exp.frase()
    assert "ponto(s) de margem" in exp.frase()


# ---------------------------------------------------------------------------
# 2. Travessia do zero, nos dois sentidos
# ---------------------------------------------------------------------------


def test_travessia_do_zero_de_lucro_para_prejuizo():
    vendas = [_venda(1, "1000", custo="400"), _venda(2, "1000", custo="1100")]
    exp = explicar_variacao(_mensal(vendas))
    assert exp.delta_lucro < 0
    assert exp.delta_margem_pp < 0
    # base do mês anterior é positiva: aqui o percentual ainda vale
    assert exp.var_lucro_pct.ok
    assert exp.var_lucro_pct.valor < 0
    assert "o lucro caiu" in exp.frase()


def test_travessia_do_zero_de_prejuizo_para_lucro():
    """O sentido em que o percentual mais enganava: melhora virava número negativo."""
    vendas = [_venda(1, "1000", custo="1100"), _venda(2, "1000", custo="400")]
    exp = explicar_variacao(_mensal(vendas))
    assert exp.delta_lucro > 0
    assert exp.delta_margem_pp > 0
    assert not exp.var_lucro_pct.ok  # base negativa → sem percentual
    assert "o lucro subiu" in exp.frase()


# ---------------------------------------------------------------------------
# 3. Comissão de 900% da receita — implausível, não número limpo
# ---------------------------------------------------------------------------


def test_comissao_de_900_por_cento_e_implausivel_e_a_identidade_nao_percebe():
    """O caso que motivou a faixa de plausibilidade.

    A identidade estrutural fecha — ela sempre fecha, porque a margem é
    construída como resíduo. Quem grita é a conferência de faixa.
    """
    vendas = [_venda(1, "1000"), _venda(1, "1000", dia=20)]
    absurda = TabelaCustos(comissao_canal={c: Decimal("9") for c in CANAIS})
    d = decompor_margem(vendas, CONFIG, absurda)

    assert d.margem_pct < Decimal("-800")
    assert (
        d.identidade_estrutural_fecha() is True
    ), "a identidade não detecta entrada absurda — é esse o ponto"

    resultado = conferir_plausibilidade(d)
    assert resultado.status == "implausivel"
    assert resultado.valor == d.margem_pct  # o valor não é limitado nem zerado
    assert "mais que todo o faturamento" in resultado.motivo
    assert "coluna trocada" in resultado.motivo


def test_margem_saudavel_passa_pela_faixa_sem_carimbo():
    d = decompor_margem([_venda(1, "1000", custo="400")], CONFIG)
    assert conferir_plausibilidade(d).ok


def test_margem_abaixo_do_piso_e_implausivel_pela_saida():
    """Custo espalhado em várias linhas: nenhuma dedução isolada passa da
    receita, mas a soma passa do dobro — quem pega é o piso da margem."""
    vendas = [_venda(1, "1000", custo="900", frete="900", comissao="900")]
    d = decompor_margem(vendas, CONFIG)
    resultado = conferir_plausibilidade(d)
    assert resultado.status == "implausivel"
    assert "dobro do faturamento" in resultado.motivo


# ---------------------------------------------------------------------------
# 4. Receita zero em qualquer período
# ---------------------------------------------------------------------------


def test_receita_zero_produz_indefinido_com_motivo():
    zero = conferir_receita(Decimal("0"), "2026-03")
    assert zero.status == "indefinido"
    assert zero.valor is None
    assert "2026-03" in zero.motivo and "sem faturamento" in zero.motivo

    negativa = conferir_receita(Decimal("-10"), "2026-04")
    assert negativa.status == "indefinido"
    assert "sinal trocado" in negativa.motivo

    assert conferir_receita(Decimal("1"), "2026-05").ok


def test_variacao_percentual_com_base_zero_e_indefinida():
    r = variacao_percentual(Decimal("0"), Decimal("500"), "lucro")
    assert r.status == "indefinido"
    assert "zero" in r.motivo
    assert "variação em reais" in r.motivo


# ---------------------------------------------------------------------------
# 5. Base de lucro exatamente zero
# ---------------------------------------------------------------------------


def test_lucro_anterior_exatamente_zero_nao_vira_divisao():
    """Mês que fechou no zero a zero: não há base para percentual."""
    # 1000 de receita − 56,50 de tributo (5,65%) − 120,00 de comissão (12%
    # da tabela do ML) − 823,50 de custo = 0,00 exato
    vendas = [_venda(1, "1000", custo="823.50"), _venda(2, "1000", custo="400")]
    mensal = _mensal(vendas)
    assert mensal["2026-01"].margem_liquida == Decimal("0.00")

    exp = explicar_variacao(mensal)
    assert not exp.var_lucro_pct.ok
    assert "zero" in exp.var_lucro_pct.motivo
    # as moedas que continuam respondendo
    assert exp.delta_lucro > 0
    assert exp.delta_margem_pp > 0


# ---------------------------------------------------------------------------
# 6. Reconciliação com termo corrompido — TEM que falhar
# ---------------------------------------------------------------------------


def test_margem_acima_de_cem_por_cento_e_implausivel_pelo_teto():
    """Sobrar mais do que entrou não é resultado bom: é dedução com sinal trocado.

    A decomposição é montada à mão porque o motor não produz dedução
    negativa a partir de arquivo — é justamente por isso que o teto existe:
    ele protege contra um dado de entrada invertido, não contra o cálculo.
    """
    from dataclasses import replace

    d = decompor_margem([_venda(1, "1000", custo="400")], CONFIG)
    invertida = replace(
        d,
        deducoes=tuple(
            replace(x, valor=-x.valor) if x.nome == "cmv" else x for x in d.deducoes
        ),
        margem_liquida=Decimal("1200.00"),
        margem_pct=Decimal("120.00"),
    )
    resultado = conferir_plausibilidade(invertida)
    assert resultado.status == "implausivel"
    assert "mais de" in resultado.motivo and "100%" in resultado.motivo
    assert "sinal trocado" in resultado.motivo


def test_reconciliacao_fecha_no_mei_onde_o_tributo_e_fixo_por_mes():
    """O DAS não é percentual da receita: o outro caminho precisa saber disso."""
    config_mei = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76"))
    vendas = [_venda(m, "1000", custo="400", comissao="120") for m in (1, 2, 3)]
    d = decompor_margem(vendas, config_mei)
    assert d.deducao("tributos").valor == Decimal("228.00")  # 76 × 3 meses
    assert reconciliar(vendas, config_mei, d).ok


def test_reconciliacao_fecha_com_adquirencia_e_antecipacao():
    """Loja própria e físico pagam maquininha, e a prazo pagam antecipação.

    Sem este caso a reconciliação nunca percorreria os dois termos que
    dependem do canal — e uma reconferência que não passa pelo caminho é
    uma reconferência que não confere nada ali.
    """
    vendas = [
        Transacao(
            data=date(2026, 1, 15),
            canal=canal,
            valor_bruto=Decimal("1000"),
            custo_produto=Decimal("400"),
            frete_pago=Decimal("10"),
            prazo_recebimento_dias=prazo,
        )
        for canal, prazo in (("loja_propria", 30), ("fisico", 0), ("shopee", 30))
    ]
    d = decompor_margem(vendas, CONFIG)
    assert d.deducao("adquirencia").valor > 0
    assert d.deducao("antecipacao").valor > 0
    assert reconciliar(vendas, CONFIG, d).ok


def test_reconciliacao_fecha_no_caminho_honesto():
    vendas = [
        _venda(m, "1000", custo="400", frete="20", comissao="120") for m in range(1, 7)
    ]
    d = decompor_margem(vendas, CONFIG)
    r = reconciliar(vendas, CONFIG, d)
    assert r.ok
    assert r.valor <= TOLERANCIA_RECONCILIACAO


def test_reconciliacao_falha_com_um_termo_deliberadamente_corrompido():
    """A prova de que a reconciliação é independente de verdade.

    Se este teste passasse — isto é, se a reconciliação continuasse
    fechando com um termo adulterado — ela estaria refazendo a mesma
    soma do motor e não valeria nada. É a diferença entre esta conferência
    e a identidade estrutural, que fecha justamente por não ser
    independente.
    """
    from dataclasses import replace

    vendas = [
        _venda(m, "1000", custo="400", frete="20", comissao="120") for m in range(1, 7)
    ]
    d = decompor_margem(vendas, CONFIG)
    assert reconciliar(vendas, CONFIG, d).ok

    # corrompe UM termo: o CMV encolhe R$ 500, e a margem cresce o mesmo
    # tanto — de modo que a identidade estrutural continua fechando
    cmv = d.deducao("cmv")
    corrompida = replace(
        d,
        deducoes=tuple(
            replace(x, valor=x.valor - Decimal("500")) if x.nome == "cmv" else x
            for x in d.deducoes
        ),
        margem_liquida=d.margem_liquida + Decimal("500"),
    )
    assert corrompida.deducao("cmv").valor == cmv.valor - Decimal("500")
    assert (
        corrompida.identidade_estrutural_fecha() is True
    ), "a corrupção foi montada para passar pela identidade"

    r = reconciliar(vendas, CONFIG, corrompida)
    assert not r.ok, "a reconciliação TEM que pegar o termo corrompido"
    assert r.status == "implausivel"
    assert r.valor == Decimal("500.00")
    assert "não fecham" in r.motivo
    assert "tolerância" in r.motivo


def test_reconciliacao_pega_erro_de_regra_e_nao_so_de_valor():
    """Erro de fórmula, não de dígito: CMV cobrado sobre venda devolvida.

    Este é o defeito que a identidade estrutural jamais pegaria, porque
    uma decomposição errada e internamente consistente fecha igual.
    """
    from dataclasses import replace

    vendas = [
        _venda(1, "1000", custo="400"),
        _venda(1, "1000", custo="400", dia=20, devolvida=True),
    ]
    d = decompor_margem(vendas, CONFIG)
    # o motor exclui a devolvida do CMV; a versão "errada" a inclui
    errada = replace(
        d,
        deducoes=tuple(
            replace(x, valor=x.valor + Decimal("400")) if x.nome == "cmv" else x
            for x in d.deducoes
        ),
        margem_liquida=d.margem_liquida - Decimal("400"),
    )
    assert errada.identidade_estrutural_fecha() is True
    assert not reconciliar(vendas, CONFIG, errada).ok


# ---------------------------------------------------------------------------
# 7. Aditividade dos drivers em pontos de margem
# ---------------------------------------------------------------------------


def test_a_soma_dos_drivers_em_pp_reproduz_o_delta_margem():
    """``margem% = 100 − Σ (dedução como % da receita)`` — logo os deltas somam.

    A igualdade é exata em precisão cheia. O que o motor publica é
    arredondado ao centésimo de ponto em cada linha, então a soma pode
    ficar a até ``TOLERANCIA_ADITIVIDADE_PP`` do total — meio centésimo por
    linha arredondada, e nada além disso. Erro de fórmula produziria
    divergência de pontos inteiros, não de centésimos.

    A receita entra com ``delta_pp`` zero de propósito: margem é razão, e
    faturar mais pelo mesmo preço unitário não move a margem. O que move
    são as fatias.
    """
    mensal = AnalisadorMargem.demo(meses=8).mensal
    meses = list(mensal)
    assert len(meses) >= 3
    for mes in meses[1:]:
        exp = explicar_variacao(mensal, mes)
        soma = sum(c.delta_pp for c in exp.contribuicoes)
        assert abs(soma - exp.delta_margem_pp) <= TOLERANCIA_ADITIVIDADE_PP, mes
    # a receita não contribui em pontos de margem
    exp = explicar_variacao(mensal)
    assert {c.nome: c.delta_pp for c in exp.contribuicoes}["receita"] == Decimal("0")


def test_a_aditividade_vale_tambem_com_prejuizo_nos_dois_meses():
    """A moeda que sobrevive ao zero também tem que somar direito."""
    vendas = [_venda(1, "1000", custo="1200"), _venda(2, "1000", custo="1050")]
    exp = explicar_variacao(_mensal(vendas))
    soma = sum(c.delta_pp for c in exp.contribuicoes)
    assert abs(soma - exp.delta_margem_pp) <= TOLERANCIA_ADITIVIDADE_PP


def test_a_tolerancia_de_aditividade_nao_absorve_erro_de_formula():
    """A tolerância cobre arredondamento; um driver a menos ela não cobre.

    Sem esta conferência, alargar a tolerância silenciaria justamente o
    defeito que a aditividade existe para pegar.
    """
    mensal = AnalisadorMargem.demo(meses=6).mensal
    exp = explicar_variacao(mensal)
    sem_o_maior = sorted(exp.contribuicoes, key=lambda c: abs(c.delta_pp))[:-1]
    soma_incompleta = sum(c.delta_pp for c in sem_o_maior)
    assert abs(soma_incompleta - exp.delta_margem_pp) > TOLERANCIA_ADITIVIDADE_PP


# ---------------------------------------------------------------------------
# O tipo de resultado em si
# ---------------------------------------------------------------------------


def test_resultado_recusa_estado_incoerente():
    with pytest.raises(ValueError, match="status"):
        Resultado(valor=Decimal("1"), status="mais_ou_menos")
    with pytest.raises(ValueError, match="motivo"):
        Resultado(valor=None, status="indefinido", motivo="   ")
    with pytest.raises(ValueError, match="precisa de valor"):
        Resultado(valor=None, status="ok")
    with pytest.raises(ValueError, match="não carrega valor"):
        Resultado(valor=Decimal("1"), status="indefinido", motivo="x")


def test_resultado_mostra_o_motivo_no_lugar_do_numero():
    """A camada de apresentação nunca recebe traço mudo nem zero."""
    assert Resultado.de_valor(Decimal("12.5")).texto() == "12.5"
    indefinido = Resultado.indefinido("o mês anterior fechou em zero")
    assert indefinido.texto() == "o mês anterior fechou em zero"
    assert indefinido.texto() != ""
    implausivel = Resultado.implausivel(Decimal("-1854"), "custos acima do dobro")
    assert implausivel.texto() == "custos acima do dobro"
    assert implausivel.valor == Decimal("-1854")  # o valor segue disponível


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
