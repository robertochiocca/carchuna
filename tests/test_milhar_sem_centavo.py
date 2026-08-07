"""O erro de mil vezes: "1.234" lido como um real e vinte e três.

A heurística antiga era "tem vírgula, então é formato brasileiro". Um
arquivo brasileiro exportado sem centavos — que é o caso comum quando o
painel exporta valores redondos — cai fora dela, e cada linha da coluna de
dinheiro é dividida por mil em silêncio.

Silêncio é o problema. Um valor mil vezes menor não estoura nada: ele
passa pela validação, entra na soma, sai na tela como margem e ninguém
tem como desconfiar olhando o resultado.
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.dados import _para_decimal, decimal_de_texto


@pytest.mark.parametrize(
    "texto, esperado",
    [
        # o defeito: ponto de milhar sem centavos
        ("1.234", "1234"),
        ("R$ 1.234", "1234"),
        ("12.345", "12345"),
        ("123.456", "123456"),
        ("1.234.567", "1234567"),
        ("12.345.678", "12345678"),
        # vírgula presente: o caminho antigo, que já estava certo
        ("1.234,56", "1234.56"),
        ("1.234.567,89", "1234567.89"),
        ("2,49", "2.49"),
        # ponto decimal com 1 ou 2 casas: continua sendo decimal
        ("1234.5", "1234.5"),
        ("1234.56", "1234.56"),
        ("2.49", "2.49"),
        ("0.5", "0.5"),
        # sem separador nenhum
        ("1234", "1234"),
        ("0", "0"),
    ],
)
def test_o_ponto_de_milhar_deixa_de_dividir_por_mil(texto, esperado):
    assert _para_decimal(texto) == Decimal(esperado)


def test_o_caso_genuinamente_ambiguo_e_recusado_em_vez_de_chutado():
    """Ambíguo de verdade: 1.234.567 ou 1234 e 567 milésimos?

    Não dá para saber pelo texto, e as duas leituras diferem por mil. A
    recusa vai irritar alguém — irritar é melhor que errar por mil, e
    quem for irritado ainda pode reexportar com centavos.
    """
    with pytest.raises(ValueError) as erro:
        _para_decimal("1234.567")
    mensagem = str(erro.value)
    assert "1234.567" in mensagem
    assert "centavos" in mensagem

    with pytest.raises(ValueError):
        _para_decimal("98765.432")


def test_zero_com_tres_casas_e_decimal_e_nao_milhar():
    """Meio real se escreve 0,500 — e quinhentos reais, nunca.

    Sem esta exceção a regra do milhar transformaria 0,5 em 500 — o mesmo
    erro de mil vezes que ela existe para corrigir, na outra direção.
    """
    assert _para_decimal("0.500") == Decimal("0.500")
    assert _para_decimal("0.750") == Decimal("0.750")


def test_a_recusa_chega_ao_lojista_com_frase_e_nao_com_traceback():
    with pytest.raises(ValueError) as erro:
        decimal_de_texto("1234.567", "valor_bruto")
    assert "valor_bruto" in str(erro.value)
    assert "centavos" in str(erro.value)


def test_o_arquivo_inteiro_com_milhar_sem_centavo_soma_certo():
    """O caminho que interessa: a planilha, não a função isolada."""
    from carchuna.dados import carregar_com_relatorio

    caminho = Path(__file__).parent / "_milhar.csv"
    caminho.write_text(
        "data;canal;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;shopee;1.500;600;20\n"
        "02/05/2026;shopee;2.300;900;30\n",
        encoding="utf-8",
    )
    try:
        resultado = carregar_com_relatorio(caminho)
        assert resultado.rejeitadas == []
        assert sum(t.valor_bruto for t in resultado.transacoes) == Decimal("3800")
    finally:
        caminho.unlink()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
