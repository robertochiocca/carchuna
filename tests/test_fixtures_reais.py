"""Os dois exports crus entram ponta a ponta pelo `dados.py`.

Leia `tests/fixtures/reais/PROCEDENCIA.md` antes: estes arquivos
reproduzem a FORMA do relatório (encoding, linhas de título, separador,
decimal com vírgula, data com hora, linha estragada), não são um export
capturado de um lojista real.

O critério do produto é o do enunciado: o arquivo cru entra sem
intervenção manual, ou falha com uma frase que o lojista entende.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.dados import (
    carregar_transacoes,
    ler_linhas_brutas,
    sugerir_mapeamento,
    transacoes_de_mapa,
)

FIXTURES = Path(__file__).parent / "fixtures" / "reais"
SHOPEE = FIXTURES / "shopee_pedidos_cru.csv"
MERCADO_LIVRE = FIXTURES / "mercado_livre_vendas_cru.csv"


# ---------------------------------------------------------------------------
# Shopee
# ---------------------------------------------------------------------------


def test_shopee_cru_e_lido_apesar_da_bagunca():
    """cp1252 + 4 linhas de título + ';' + vírgula decimal, tudo junto."""
    linhas = ler_linhas_brutas(SHOPEE)
    assert len(linhas) == 6
    assert linhas[0]["Data do pedido"] == "01/05/2026"
    assert linhas[0]["Preço acordado"] == "89,90"
    # o travessão do cp1252 sobreviveu à decodificação
    assert linhas[3]["Nome do Produto"] == "Relógio – Prata"


def test_shopee_o_palpite_do_mapeador_acerta_sozinho():
    """Sem o lojista clicar em nada, o de-para já vem certo."""
    linhas = ler_linhas_brutas(SHOPEE)
    mapa = sugerir_mapeamento(sorted({c for lin in linhas for c in lin}))
    assert mapa["data"] == "Data do pedido"
    assert mapa["produto"] == "Nome do Produto"
    assert mapa["valor_bruto"] == "Preço acordado"
    assert mapa["frete_pago"] == "Taxa de envio"
    assert mapa["comissao_cobrada"] == "Tarifa de venda"
    assert mapa["devolvida"] == "Devolução"
    # o relatório não tem essas duas, e não deve inventar palpite
    assert mapa["canal"] is None
    assert mapa["custo_produto"] is None


def test_shopee_sem_mapa_falha_com_frase_de_lojista():
    """Direto no `carregar_transacoes`, o erro ensina o caminho."""
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(SHOPEE)
    mensagem = str(erro.value)
    assert 'parece ser "Preço acordado"' in mensagem
    assert "custo_produto" in mensagem and "marketplace não conhece" in mensagem
    assert "mapeador" in mensagem


def test_shopee_com_o_mapa_completo_vira_venda_com_valor_conferido():
    """As 5 linhas boas viram vendas; a de data vazia é a exceção.

    Soma conferida à mão sobre as linhas com data:
    89,90 + 129,90 + 249,90 + 349,00 + 89,90 = 908,60
    (a linha 2605050005, de data vazia, fica de fora)
    """
    from carchuna.dados import relatorio_de_mapa

    linhas = ler_linhas_brutas(SHOPEE)
    mapa = sugerir_mapeamento(sorted({c for lin in linhas for c in lin}))
    # o que o relatório não tem, o lojista fixa no mapeador
    mapa["canal"] = "=shopee"
    mapa["custo_produto"] = "=40.00"

    resultado = relatorio_de_mapa(linhas, {c: o for c, o in mapa.items() if o})

    assert len(resultado.transacoes) == 5
    assert sum(t.valor_bruto for t in resultado.transacoes) == Decimal("908.60")
    assert resultado.transacoes[0].data == date(2026, 5, 1)
    assert resultado.transacoes[0].canal == "shopee"
    assert resultado.transacoes[0].comissao_cobrada == Decimal("10.79")
    assert resultado.transacoes[-1].devolvida is True

    (rejeitada,) = resultado.rejeitadas
    assert rejeitada.numero == 6  # 5ª linha de dados, cabeçalho é a 1
    assert "`data`" in rejeitada.motivo


# ---------------------------------------------------------------------------
# Mercado Livre
# ---------------------------------------------------------------------------


def test_mercado_livre_cru_e_lido_apesar_da_bagunca():
    """BOM + 2 linhas de título + ',' com os decimais entre aspas."""
    linhas = ler_linhas_brutas(MERCADO_LIVRE)
    assert len(linhas) == 5
    # a vírgula decimal está DENTRO das aspas: não pode virar coluna nova
    assert linhas[0]["Receita por produtos (BRL)"] == "249,90"
    assert linhas[0]["Data da venda"] == "2026-05-02T14:32:07"


def test_mercado_livre_o_palpite_nao_confunde_receita_com_produto():
    """'Receita por produtos' é dinheiro; 'Título do anúncio' é o produto.

    As duas colunas contêm palavras que casam com campos diferentes; o
    palpite tem que ficar com a mais específica de cada uma. Mesma coisa
    entre 'Custo do envio' (frete) e o custo do produto, que não existe
    neste relatório.
    """
    linhas = ler_linhas_brutas(MERCADO_LIVRE)
    mapa = sugerir_mapeamento(sorted({c for lin in linhas for c in lin}))
    assert mapa["valor_bruto"] == "Receita por produtos (BRL)"
    assert mapa["produto"] == "Título do anúncio"
    assert mapa["frete_pago"] == "Custo do envio (BRL)"
    assert mapa["comissao_cobrada"] == "Tarifa de venda (BRL)"
    assert mapa["custo_produto"] is None  # o ML não sabe o seu CMV
    assert mapa["canal"] is None


def test_mercado_livre_com_o_mapa_vira_venda_com_valor_conferido():
    """4 vendas boas; a de valor 'ver detalhe' cai com motivo.

    Soma conferida à mão: 249,90 + 89,90 + 549,00 + 259,80 = 1.148,60
    """
    from carchuna.dados import relatorio_de_mapa

    linhas = ler_linhas_brutas(MERCADO_LIVRE)
    mapa = sugerir_mapeamento(sorted({c for lin in linhas for c in lin}))
    mapa["canal"] = "=mercado_livre"
    mapa["custo_produto"] = "=100.00"

    resultado = relatorio_de_mapa(linhas, {c: o for c, o in mapa.items() if o})

    assert len(resultado.transacoes) == 4
    assert sum(t.valor_bruto for t in resultado.transacoes) == Decimal("1148.60")
    # data com hora vira o dia, sem a hora
    assert resultado.transacoes[0].data == date(2026, 5, 2)

    (rejeitada,) = resultado.rejeitadas
    assert rejeitada.numero == 6
    assert "ver detalhe" in rejeitada.motivo


def test_mercado_livre_sem_mapa_falha_com_frase_de_lojista():
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(MERCADO_LIVRE)
    mensagem = str(erro.value)
    assert 'parece ser "Receita por produtos (BRL)"' in mensagem
    assert "mapeador" in mensagem


# ---------------------------------------------------------------------------
# O raio-X roda em cima do que entrou
# ---------------------------------------------------------------------------


def test_export_cru_atravessa_ate_a_margem_com_invariante_fechada():
    """Ponta a ponta: arquivo cru da Shopee → margem decomposta.

    Invariante contábil da casa: soma das deduções + margem líquida ==
    receita bruta, centavo a centavo.
    """
    from carchuna.analise import AnalisadorMargem
    from carchuna.dados import relatorio_de_mapa
    from carchuna.margem import ConfigTributaria

    linhas = ler_linhas_brutas(SHOPEE)
    mapa = sugerir_mapeamento(sorted({c for lin in linhas for c in lin}))
    mapa["canal"] = "=shopee"
    mapa["custo_produto"] = "=40.00"
    resultado = relatorio_de_mapa(linhas, {c: o for c, o in mapa.items() if o})

    analise = AnalisadorMargem(
        resultado.transacoes,
        ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("4200000")),
    )
    decomposicao = analise.decomposicao

    # receita bruta = as 5 linhas boas, conferidas no teste acima
    assert decomposicao.receita_bruta == Decimal("908.60")
    deducoes = sum(d.valor for d in decomposicao.deducoes)
    assert deducoes + decomposicao.margem_liquida == decomposicao.receita_bruta


def test_transacoes_de_mapa_continua_estrito():
    """O contrato antigo não muda: linha ruim derruba o lote."""
    linhas = ler_linhas_brutas(SHOPEE)
    mapa = sugerir_mapeamento(sorted({c for lin in linhas for c in lin}))
    mapa["canal"] = "=shopee"
    mapa["custo_produto"] = "=40.00"
    with pytest.raises(ValueError, match="linha 6"):
        transacoes_de_mapa(linhas, {c: o for c, o in mapa.items() if o})


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
