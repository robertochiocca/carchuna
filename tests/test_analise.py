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
