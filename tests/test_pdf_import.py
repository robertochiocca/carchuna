"""Teste da importação de vendas via PDF (tabela no layout do modelo)."""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("pdfplumber")
matplotlib = pytest.importorskip("matplotlib")

from carchuna.dados import carregar_transacoes

LINHAS = [
    ["data", "canal", "valor_bruto", "custo_produto", "frete_pago", "produto"],
    ["2026-05-01", "shopee", "129,90", "70,00", "14,00", "Fone"],
    ["2026-05-02", "mercado_livre", "89,90", "45,00", "12,00", "Capa"],
]


@pytest.fixture
def pdf_com_tabela(tmp_path):
    """Gera um PDF com uma tabela de grade (como um relatório real)."""
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figura, eixo = plt.subplots(figsize=(8, 3))
    eixo.axis("off")
    tabela = eixo.table(cellText=LINHAS, loc="center", cellLoc="center")
    tabela.scale(1, 1.6)
    caminho = tmp_path / "relatorio.pdf"
    figura.savefig(caminho, format="pdf")
    plt.close(figura)
    return caminho


def test_pdf_com_tabela_no_layout_do_modelo(pdf_com_tabela):
    transacoes = carregar_transacoes(pdf_com_tabela)
    assert len(transacoes) == 2
    assert transacoes[0].canal == "shopee"
    assert transacoes[0].valor_bruto == Decimal("129.90")  # vírgula BR no PDF
    assert transacoes[0].produto == "Fone"
    assert transacoes[1].canal == "mercado_livre"


def test_pdf_sem_tabela_explica_o_caminho(tmp_path):
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figura, eixo = plt.subplots(figsize=(6, 2))
    eixo.axis("off")
    eixo.text(0.1, 0.5, "Relatório sem tabela alguma")
    caminho = tmp_path / "sem_tabela.pdf"
    figura.savefig(caminho, format="pdf")
    plt.close(figura)

    with pytest.raises(ValueError, match="CSV/Excel"):
        carregar_transacoes(caminho)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
