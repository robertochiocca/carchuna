"""Testes da interface Conector e do conector de arquivo."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.conectores import Conector, ConectorArquivo

CSV = (
    "data,canal,valor_bruto,custo_produto,frete_pago\n"
    "2026-04-10,shopee,100,40,10\n"
    "2026-05-10,shopee,200,80,10\n"
    "2026-06-10,mercado_livre,300,120,10\n"
)


@pytest.fixture
def arquivo(tmp_path):
    caminho = tmp_path / "vendas.csv"
    caminho.write_text(CSV, encoding="utf-8")
    return caminho


def test_conector_arquivo_implementa_a_interface(arquivo):
    conector = ConectorArquivo(arquivo)
    assert isinstance(conector, Conector)
    assert "vendas.csv" in conector.nome
    transacoes = conector.transacoes()
    assert len(transacoes) == 3
    assert transacoes[0].valor_bruto == Decimal("100")


def test_conector_arquivo_filtra_por_periodo(arquivo):
    conector = ConectorArquivo(arquivo)
    maio = conector.transacoes(inicio=date(2026, 5, 1), fim=date(2026, 5, 31))
    assert [t.data.month for t in maio] == [5]
    desde_maio = conector.transacoes(inicio=date(2026, 5, 1))
    assert len(desde_maio) == 2


def test_interface_nao_pode_ser_instanciada():
    with pytest.raises(TypeError):
        Conector()  # abstrata: um conector precisa implementar os métodos


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
