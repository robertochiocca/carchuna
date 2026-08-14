"""O erro de mil vezes tinha um lado desprotegido, e era o americano.

`_para_decimal` já recusava o ponto ambíguo ("1234.567" pode ser milhar
ou três casas decimais). Do outro lado, o ramo da vírgula apagava os
pontos e trocava a vírgula por ponto **sem olhar a ordem dos
separadores** — então "1,234.56", que é como a Amazon Seller Central e
boa parte dos ERPs exportam, virava `Decimal("1.23456")`.

Mil vezes menor. E o pior tipo de erro que este projeto pode ter: não
estoura, não aparece em log nenhum, entra na soma e sai na tela como
margem. Quem olha o resultado não tem como desconfiar — a margem fica
ótima, porque o custo encolheu mil vezes junto.

A correção não converte: recusa. Converter en-US em silêncio seria
adivinhar locale, e há valores em que nem o locale resolve — "1,234" é
mil duzentos e trinta e quatro em en-US e um vírgula duzentos e trinta e
quatro em pt-BR, e nada no texto diz qual. Aceitar o caso decidível e
recusar o indecidível deixaria metade do arquivo numa leitura e metade
na outra, que é pior que recusar as duas.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decimal import Decimal, InvalidOperation  # noqa: E402

import pytest

from carchuna.dados import (
    _para_decimal,
    carregar_com_relatorio,
    decimal_de_texto,
)

CABECALHO = "data;canal;produto;valor_bruto;custo_produto;frete_pago"


# ---------------------------------------------------------------------------
# O defeito
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada",
    ["1,234.56", "2,500.00", "1,234,567.89"],
)
def test_formato_americano_e_recusado(entrada):
    """O ponto vem depois da vírgula: só pode ser en-US."""
    with pytest.raises(ValueError):
        _para_decimal(entrada)


@pytest.mark.parametrize(
    ("entrada", "americano", "brasileiro"),
    [
        ("1,234.56", "1234.56", "1.23456"),
        ("2,500.00", "2500.00", "2.50000"),
        ("1,234,567.89", "1234567.89", "1.234.56789"),
    ],
)
def test_a_recusa_mostra_as_duas_leituras(entrada, americano, brasileiro):
    """Recusar sem explicar manda o lojista adivinhar o que fazer.

    A mensagem tem que trazer os dois números lado a lado, porque é a
    distância entre eles que justifica a recusa: não é preciosismo de
    formato, é um fator de mil no valor que vai virar margem.
    """
    with pytest.raises(ValueError) as erro:
        _para_decimal(entrada)

    mensagem = str(erro.value)
    assert americano in mensagem, "falta a leitura americana"
    assert brasileiro in mensagem, "falta o que sairia lido como brasileiro"
    assert "pt-BR" in mensagem  # e o que fazer a respeito


def test_so_o_en_us_de_uma_virgula_era_silencioso():
    """Nem todos os três casos eram iguais, e isso muda o tamanho do defeito.

    Com UMA vírgula ("1,234.56") o ramo brasileiro produzia "1.23456" —
    `Decimal` perfeitamente válido, mil vezes menor, publicado sem um
    ruído. Com DUAS ("1,234,567.89") ele produzia "1.234.56789", que não
    é `Decimal` nenhum: já estourava `InvalidOperation` e virava "não é
    um valor monetário válido".

    Então o furo calado era o dos valores abaixo de dez mil — que é a
    faixa de quase toda venda de marketplace. O ganho no caso de duas
    vírgulas é outro: a mensagem deixa de ser genérica e passa a dizer
    que o problema é o formato, com as duas leituras lado a lado.

    Este teste fixa a distinção para que ninguém a perca reescrevendo a
    recusa mais tarde.
    """
    uma_virgula = "1,234.56".replace(".", "").replace(",", ".")
    assert Decimal(uma_virgula) == Decimal("1.23456")  # era aceito, e errado

    duas_virgulas = "1,234,567.89".replace(".", "").replace(",", ".")
    with pytest.raises(InvalidOperation):
        Decimal(duas_virgulas)  # já barrava, com mensagem genérica


def test_a_recusa_nao_chuta_o_formato():
    """A Carchuna não adivinha locale, e a mensagem diz isso."""
    with pytest.raises(ValueError) as erro:
        _para_decimal("1,234.56")
    assert "não adivinha" in str(erro.value)


# ---------------------------------------------------------------------------
# Regressão: nada do que já funcionava pode ter mudado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("R$ 1.234,56", "1234.56"),  # brasileiro completo
        ("1.234", "1234"),  # milhar sem centavos
        ("1234.56", "1234.56"),  # decimal com ponto, sem vírgula
        ("1,5", "1.5"),  # vírgula decimal, uma casa
        ("12,3456", "12.3456"),  # vírgula decimal, quatro casas
        ("0,00", "0.00"),  # zero
        ("1 234,56", "1234.56"),  # milhar com espaço
    ],
)
def test_o_que_ja_funcionava_continua(entrada, esperado):
    assert _para_decimal(entrada) == Decimal(esperado)


def test_o_ponto_ambiguo_continua_recusando():
    """A proteção do outro lado do erro de mil não foi afrouxada."""
    with pytest.raises(ValueError, match="mil vezes"):
        _para_decimal("1234.567")


def test_a_vírgula_sozinha_nunca_dispara_a_recusa_americana():
    """Sem os DOIS separadores não há ordem para comparar.

    Uma checagem que olhasse só `rfind(".")` mandaria "1234.56" — decimal
    com ponto, o caso mais comum de export em inglês simples — para a
    recusa, e aí a correção teria quebrado mais do que consertou.
    """
    assert _para_decimal("1234.56") == Decimal("1234.56")
    assert _para_decimal("1,56") == Decimal("1.56")


# ---------------------------------------------------------------------------
# Pelo caminho de importação: a linha cai, o arquivo não
# ---------------------------------------------------------------------------


def test_linha_em_en_us_vira_linha_rejeitada_com_linha_e_coluna(tmp_path):
    """Uma célula americana não pode derrubar o arquivo inteiro.

    É a regra da casa na ingestão: a linha problemática sai com motivo, o
    resto importa. E o motivo precisa dizer ONDE — sem o número da linha
    e o nome da coluna, o relatório manda procurar a agulha no palheiro.
    """
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        f"{CABECALHO}\n"
        "01/05/2026;shopee;Capa;100,00;40,00;10,00\n"
        "02/05/2026;shopee;Fone;2,500.00;90,00;12,00\n"
        "03/05/2026;shopee;Caixa;300,00;120,00;15,00\n",
        encoding="utf-8",
    )
    resultado = carregar_com_relatorio(arquivo)

    assert len(resultado.transacoes) == 2  # as duas boas entraram
    (rejeitada,) = resultado.rejeitadas
    assert rejeitada.numero == 3
    assert "valor_bruto" in rejeitada.motivo
    assert "linha 3" in rejeitada.motivo
    assert "2500.00" in rejeitada.motivo  # a leitura americana, na mensagem


def test_o_valor_americano_nao_entra_na_soma(tmp_path):
    """A prova de que o defeito não sobrevive em nenhum canto.

    Antes, R$ 2.500,00 escritos em en-US entravam como R$ 2,50 e a
    receita do arquivo saía R$ 2.497,50 menor — sem nada na tela.
    """
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        f"{CABECALHO}\n"
        "01/05/2026;shopee;Capa;100,00;40,00;10,00\n"
        "02/05/2026;shopee;Fone;2,500.00;90,00;12,00\n",
        encoding="utf-8",
    )
    resultado = carregar_com_relatorio(arquivo)
    receita = sum(t.valor_bruto for t in resultado.transacoes)

    assert receita == Decimal("100.00")
    assert Decimal("2.50") not in [t.valor_bruto for t in resultado.transacoes]


def test_o_campo_digitado_tambem_recusa():
    """A barra lateral usa o mesmo parser, e herda a mesma recusa."""
    with pytest.raises(ValueError) as erro:
        decimal_de_texto("1,234.56", "taxa_adquirencia")
    assert "taxa_adquirencia" in str(erro.value)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
