"""A planilha .xlsx tinha que entrar como o .csv entra — e não entrava.

Duas assimetrias no mesmo caminho:

1. o CSV procura o cabeçalho em até 30 linhas, porque relatório de
   marketplace quase nunca começa na tabela; o XLSX assumia a linha 1. A
   MESMA exportação do MESMO painel, salva em .xlsx, era recusada;
2. o XLSX convertia cada célula com ``str()`` e o comentário admitia que
   "células numéricas do Excel chegam como float". ``str()`` não desfaz o
   erro de ponto flutuante — congela ele, e entrega ao motor um texto que
   passa por baixo da guarda que rejeita ``float``.
"""

import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("openpyxl")

from carchuna.dados import carregar_com_relatorio, ler_linhas_brutas  # noqa: E402


def _planilha(caminho, linhas):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for linha in linhas:
        ws.append(linha)
    wb.save(caminho)
    return caminho


def test_xlsx_com_linhas_de_titulo_antes_do_cabecalho(tmp_path):
    """O mesmo relatório que o CSV já lia, agora em planilha."""
    arquivo = _planilha(
        tmp_path / "vendas.xlsx",
        [
            ["Relatório de Pedidos"],
            ["Loja: Exemplo Comércio Ltda"],
            ["Período: 01/05/2026 - 31/05/2026"],
            [],
            ["Data do pedido", "Preço acordado", "Taxa de envio", "Tarifa de venda"],
            ["01/05/2026", "89,90", "9,90", "10,79"],
            ["02/05/2026", "129,90", "12,00", "15,59"],
        ],
    )
    linhas = ler_linhas_brutas(arquivo)
    assert len(linhas) == 2
    assert linhas[0]["Data do pedido"] == "01/05/2026"
    assert linhas[0]["Preço acordado"] == "89,90"


def test_xlsx_sem_cabecalho_reconhecivel_da_a_mesma_frase_do_csv(tmp_path):
    arquivo = _planilha(
        tmp_path / "extrato.xlsx",
        [["Extrato bancário"], ["lançamento", "histórico"], ["PIX", "recebido"]],
    )
    with pytest.raises(ValueError) as erro:
        ler_linhas_brutas(arquivo)
    assert "cabeçalho" in str(erro.value)


def test_planilha_vazia_avisa_em_vez_de_estourar_stopiteration(tmp_path):
    """`next()` numa planilha vazia levantava StopIteration crua.

    StopIteration não é mensagem para lojista — e, pior, dentro de um
    gerador ela vira encerramento silencioso em vez de erro.
    """
    arquivo = _planilha(tmp_path / "vazia.xlsx", [])
    with pytest.raises(ValueError) as erro:
        ler_linhas_brutas(arquivo)
    assert "linha" in str(erro.value).lower()


def test_dinheiro_do_excel_e_quantizado_a_centavos_na_ingestao(tmp_path):
    """0.1 + 0.2 no Excel chega como 0.30000000000000004.

    `str()` congelava esse valor e o entregava ao motor como texto — que
    passa pela guarda do `float` sem tocar nela. A quantização na fronteira
    é o único lugar onde ainda dá para cortar o rastro.
    """
    arquivo = _planilha(
        tmp_path / "float.xlsx",
        [
            ["data", "canal", "valor_bruto", "custo_produto", "frete_pago"],
            ["2026-05-01", "shopee", 0.1 + 0.2, 0.1, 0.0],
            ["2026-05-02", "shopee", 1234.565, 100.0, 0.0],
        ],
    )
    linhas = ler_linhas_brutas(arquivo)
    assert linhas[0]["valor_bruto"] == "0.30", linhas[0]["valor_bruto"]
    # meio centavo arredonda para cima (ROUND_HALF_UP, prática comercial)
    assert linhas[1]["valor_bruto"] == "1234.57"

    resultado = carregar_com_relatorio(arquivo)
    assert resultado.rejeitadas == []
    assert sum(t.valor_bruto for t in resultado.transacoes) == Decimal("1234.87")


def test_texto_e_data_do_excel_nao_sao_quantizados(tmp_path):
    """Só dinheiro vira centavo. Nome de produto e data seguem intactos.

    "Capa 2.0" é o caso que pega: tem ponto e dígito dos dois lados, e um
    corte por regex acharia que é número.
    """
    arquivo = _planilha(
        tmp_path / "misto.xlsx",
        [
            ["data", "canal", "produto", "valor_bruto", "custo_produto", "frete_pago"],
            ["2026-05-01", "shopee", "Capa 2.0", 100.5, 40.0, 10.0],
        ],
    )
    (linha,) = ler_linhas_brutas(arquivo)
    assert linha["produto"] == "Capa 2.0"
    assert linha["data"] == "2026-05-01"
    assert linha["valor_bruto"] == "100.50"
    # 40,00 o Excel guarda como o inteiro 40 — nada se perdeu, nada a somar
    assert linha["custo_produto"] == "40"


def test_celula_infinita_ou_nan_vira_marcador_e_nao_contamina_a_soma():
    """`Decimal("nan")` não estoura — cria um NaN que come a soma inteira.

    Este é o único teste do arquivo que chama o conversor direto, e por um
    motivo: o openpyxl grava NaN como célula VAZIA, então não dá para
    produzir o caso salvando uma planilha com ele. Um arquivo escrito por
    outra ferramenta produz, e aí a célula chega como float NaN.
    """
    from carchuna.dados import _celula_de_planilha

    assert _celula_de_planilha(float("nan")) == "#ERRO"
    assert _celula_de_planilha(float("inf")) == "#ERRO"
    # o que importa: o marcador não vira Decimal, então a linha é recusada
    assert Decimal("nan") + Decimal("10") != Decimal("10")
    with pytest.raises(InvalidOperation):
        Decimal(_celula_de_planilha(float("nan")))


def test_inteiro_do_excel_nao_ganha_centavo_falso(tmp_path):
    """Quantidade e prazo são inteiros: não viram 30,00 dias."""
    arquivo = _planilha(
        tmp_path / "int.xlsx",
        [
            ["data", "canal", "valor_bruto", "custo_produto", "frete_pago", "prazo"],
            ["2026-05-01", "shopee", 100.0, 40.0, 10.0, 30],
        ],
    )
    (linha,) = ler_linhas_brutas(arquivo)
    assert linha["prazo"] == "30"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
