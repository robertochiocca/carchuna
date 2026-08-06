"""Testes da fachada AnalisadorMargem, resumo executivo e margem por venda."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.analise import AnalisadorMargem
from carchuna.cenarios import CenarioComissao, cenario_comissao
from carchuna.margem import ConfigTributaria, Transacao

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _venda(valor="100", canal="mercado_livre", **kwargs):
    padrao = dict(
        data=date(2026, 5, 10),
        canal=canal,
        valor_bruto=Decimal(valor),
        custo_produto=Decimal("40"),
        frete_pago=Decimal("10"),
    )
    padrao.update(kwargs)
    return Transacao(**padrao)


def test_resumo_executivo_da_venda_de_100_conferido_a_mao():
    """Anunciada 60% vs real 32,35%: perda de 27,65 — 43,4% vem da comissão."""
    resumo = AnalisadorMargem([_venda()], CONFIG).resumo_executivo()
    assert resumo.margem_anunciada == Decimal("60.00")  # 100 − CMV 40
    assert resumo.margem_anunciada_pct == Decimal("60.00")
    assert resumo.margem_real == Decimal("32.35")
    assert resumo.perda_total == Decimal("27.65")  # 5,65 + 12 + 10

    fontes = {f.nome: f for f in resumo.fontes_perda}
    assert resumo.maior_fonte.nome == "comissoes_canal"
    assert fontes["comissoes_canal"].pct_da_perda == Decimal("43.4")  # 12/27,65
    assert fontes["frete"].pct_da_perda == Decimal("36.2")  # 10/27,65
    assert fontes["tributos"].pct_da_perda == Decimal("20.4")  # 5,65/27,65

    frase = resumo.frase()
    assert "R$ 27,65 de margem" in frase
    assert "43% dessa perda veio de Comissões de canal" in frase


def test_margem_por_venda_e_o_mvp_da_review():
    """Cada venda decomposta pelo mesmo motor: margem venda a venda."""
    analise = AnalisadorMargem(
        [_venda("100"), _venda("200", canal="shopee", custo_produto=Decimal("80"))],
        CONFIG,
    )
    por_venda = analise.margem_por_venda()
    assert len(por_venda) == 2
    # venda 1 é o caso clássico conferido à mão
    assert por_venda[0].margem_liquida == Decimal("32.35")
    assert por_venda[0].margem_pct == Decimal("32.35")
    # venda 2: 200 − 11,30 (5,65%) − 28 (shopee 14%) − 10 − 80 = 70,70
    assert por_venda[1].margem_liquida == Decimal("70.70")
    # a soma das margens por venda bate com a decomposição do período
    soma = sum(v.margem_liquida for v in por_venda)
    assert soma == analise.decomposicao.margem_liquida


def test_margem_por_venda_no_mei_nao_rateia_o_das():
    config = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76"))
    analise = AnalisadorMargem([_venda()], config)
    (venda,) = analise.margem_por_venda()
    assert venda.decomposicao.deducao("tributos").valor == Decimal("0.00")
    # ...mas a visão mensal cobra o DAS cheio
    assert analise.decomposicao.deducao("tributos").valor == Decimal("76.00")


def test_margem_por_produto_ranqueia_campeoes_e_viloes():
    """Fone (2 vendas boas) no topo; Brinde vendido abaixo do custo no fundo."""
    vendas = [
        _venda("100", produto="Fone"),
        _venda("100", produto="Fone"),
        _venda("100", produto="Brinde", custo_produto=Decimal("95")),
    ]
    analise = AnalisadorMargem(vendas, CONFIG)
    fone, brinde = analise.margem_por_produto()
    assert fone.nome == "Fone"
    assert fone.vendas == 2
    assert fone.margem == Decimal("64.70")  # 2 × 32,35
    assert fone.margem_pct == Decimal("32.35")
    assert brinde.nome == "Brinde"
    # 100 − 5,65 − 12 − 10 − 95 = −22,65: vilão de margem
    assert brinde.margem == Decimal("-22.65")
    assert brinde.margem_pct < 0


def test_margem_por_produto_sem_produto_agrupa_por_canal():
    vendas = [_venda("100"), _venda("100", canal="shopee")]
    nomes = {r.nome for r in AnalisadorMargem(vendas, CONFIG).margem_por_produto()}
    assert nomes == {"mercado_livre", "shopee"}


def test_composicao_deducao_quebra_por_canal_e_por_mes():
    """Drill-down do raio-X: comissões por canal e por mês, conferidas à mão."""
    vendas = [
        _venda("100"),  # maio, ML: comissão 12,00
        _venda("200", canal="shopee"),  # maio, Shopee: 200 × 14% = 28,00
        _venda("100", data=date(2026, 6, 10)),  # junho, ML: 12,00
        _venda("100", canal="fisico"),  # maio, físico: comissão 0 → some
    ]
    comp = AnalisadorMargem(vendas, CONFIG).composicao_deducao("comissoes_canal")
    assert comp["por_canal"] == [
        ("shopee", Decimal("28.00")),
        ("mercado_livre", Decimal("24.00")),
    ]
    assert comp["por_mes"] == [
        ("2026-05", Decimal("40.00")),
        ("2026-06", Decimal("12.00")),
    ]


def test_composicao_deducao_mei_nao_rateia_das_por_canal():
    config = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76"))
    comp = AnalisadorMargem([_venda()], config).composicao_deducao("tributos")
    assert comp["por_canal"] == []  # DAS fixo mensal: não rateável por canal
    assert comp["por_mes"] == [("2026-05", Decimal("76.00"))]


TODAS_AS_DEDUCOES = (
    "tributos",
    "comissoes_canal",
    "adquirencia",
    "antecipacao",
    "frete",
    "devolucoes",
    "cmv",
)


def test_a_composicao_por_canal_fecha_centavo_a_centavo_com_o_raio_x():
    """A quebra não pode divergir do número que ela explica.

    Se a soma por canal não bater com a dedução do raio-X, o drill-down
    estaria contando outra história que a da tela — que é exatamente o
    defeito que ele existe para não ter.
    """
    analise = AnalisadorMargem.demo(meses=4)
    for nome in TODAS_AS_DEDUCOES:
        total = analise.decomposicao.deducao(nome).valor
        comp = analise.composicao_deducao(nome)
        assert sum(v for _, v in comp["por_canal"]) == total, nome


def test_a_composicao_por_mes_fecha_a_menos_do_arredondamento_do_mes():
    """Por mês, a soma pode diferir por centavos de arredondamento.

    Cada mês é decomposto e arredondado por conta própria, então a soma
    dos doze pode não bater com o total do período no último centavo. Com
    os dados de exemplo isso aparece na antecipação. O teste fixa o
    tamanho aceitável do desvio — um centavo por mês, no pior caso — em
    vez de escolher só as deduções que fecham exato e fingir que o
    problema não existe.
    """
    analise = AnalisadorMargem.demo(meses=4)
    tolerancia = Decimal("0.01") * len(analise.mensal)
    for nome in TODAS_AS_DEDUCOES:
        total = analise.decomposicao.deducao(nome).valor
        soma = sum(v for _, v in analise.composicao_deducao(nome)["por_mes"])
        assert abs(soma - total) <= tolerancia, nome


def test_fachada_delega_para_os_motores():
    analise = AnalisadorMargem.demo(meses=3)
    assert analise.decomposicao.receita_bruta > 0
    assert len(analise.mensal) >= 3
    assert analise.maior_queda() >= 0
    assert analise.instabilidade() >= 0
    assert analise.lucro_acumulado()[-1][1] == sum(
        (d.margem_liquida for d in analise.mensal.values()), Decimal("0")
    )
    assert analise.cenarios()
    # simular um cenário avulso == atalho funcional equivalente
    resultado = analise.simular(CenarioComissao())
    atalho = cenario_comissao(analise.transacoes, analise.config, analise.tabela)
    assert resultado.impacto_reais == atalho.impacto_reais


def test_radar_delega_para_o_motor_de_insights():
    """A fachada não pode contar história diferente do motor."""
    from carchuna.insights import MotorInsights

    analise = AnalisadorMargem.demo(meses=6)
    pela_fachada = analise.radar()
    direto = MotorInsights().radar(analise.transacoes, analise.config, analise.tabela)
    assert [(i.categoria, i.impacto_mensal) for i in pela_fachada] == [
        (i.categoria, i.impacto_mensal) for i in direto
    ]


def test_construtor_de_arquivo(tmp_path):
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        "data,canal,valor_bruto,custo_produto,frete_pago\n"
        "2026-05-10,mercado_livre,100,40,10\n",
        encoding="utf-8",
    )
    analise = AnalisadorMargem.de_arquivo(arquivo, CONFIG)
    assert analise.decomposicao.margem_liquida == Decimal("32.35")


def test_analisador_valida_entrada():
    with pytest.raises(ValueError, match="transacoes"):
        AnalisadorMargem([], CONFIG)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
