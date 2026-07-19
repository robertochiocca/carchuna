"""Testes da importação de vendas e dos dados sintéticos."""

import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.dados import carregar_transacoes, transacoes_sinteticas

CSV_BASICO = (
    "data,canal,valor_bruto,custo_produto,frete_pago,devolvida,"
    "prazo_recebimento_dias\n"
    "2026-05-01,mercado_livre,100.50,40.00,10.00,nao,30\n"
    "2026-05-02,shopee,200.00,90.00,12.00,sim,15\n"
)

CSV_BRASILEIRO = """data;canal;valor_bruto;custo_produto;frete_pago
2026-05-01;loja_propria;1.234,56;600,00;25,90
"""


def test_csv_basico(tmp_path):
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(CSV_BASICO, encoding="utf-8")
    transacoes = carregar_transacoes(arquivo)
    assert len(transacoes) == 2
    assert transacoes[0].valor_bruto == Decimal("100.50")
    assert transacoes[0].devolvida is False
    assert transacoes[1].devolvida is True
    assert transacoes[1].prazo_recebimento_dias == 15


def test_csv_separador_ponto_e_virgula_e_virgula_decimal(tmp_path):
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(CSV_BRASILEIRO, encoding="utf-8")
    (transacao,) = carregar_transacoes(arquivo)
    assert transacao.valor_bruto == Decimal("1234.56")
    assert transacao.frete_pago == Decimal("25.90")


def test_json_preserva_dinheiro_sem_float(tmp_path):
    arquivo = tmp_path / "vendas.json"
    arquivo.write_text(
        json.dumps(
            [
                {
                    "data": "2026-05-01",
                    "canal": "amazon",
                    "valor_bruto": 199.99,
                    "custo_produto": "80.10",
                    "frete_pago": 0,
                }
            ]
        ),
        encoding="utf-8",
    )
    (transacao,) = carregar_transacoes(arquivo)
    # 199.99 chega exato: o parser JSON lê números como texto (parse_float=str)
    assert transacao.valor_bruto == Decimal("199.99")


def test_xlsx_roundtrip(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    arquivo = tmp_path / "vendas.xlsx"
    planilha = openpyxl.Workbook()
    aba = planilha.active
    aba.append(["data", "canal", "valor_bruto", "custo_produto", "frete_pago"])
    aba.append(["2026-05-01", "fisico", "150.00", "70.00", "0"])
    planilha.save(arquivo)
    (transacao,) = carregar_transacoes(arquivo)
    assert transacao.canal == "fisico"
    assert transacao.valor_bruto == Decimal("150.00")


def test_erros_de_importacao(tmp_path):
    vazio = tmp_path / "vazio.csv"
    vazio.write_text("data,canal,valor_bruto,custo_produto,frete_pago\n")
    with pytest.raises(ValueError, match="nenhuma transação"):
        carregar_transacoes(vazio)

    sem_coluna = tmp_path / "sem_coluna.csv"
    sem_coluna.write_text("data,canal\n2026-05-01,shopee\n")
    with pytest.raises(ValueError, match="obrigatórias"):
        carregar_transacoes(sem_coluna)

    formato = tmp_path / "vendas.txt"
    formato.write_text("qualquer coisa")
    with pytest.raises(ValueError, match="não suportado"):
        carregar_transacoes(formato)

    invalido = tmp_path / "invalido.csv"
    invalido.write_text(
        "data,canal,valor_bruto,custo_produto,frete_pago\n"
        "2026-05-01,shopee,abc,1,1\n"
    )
    with pytest.raises(ValueError, match="valor monetário"):
        carregar_transacoes(invalido)


def test_sintetico_reprodutivel_e_na_escala_do_publico_alvo():
    """Mesma seed → mesmas vendas; receita na casa dos R$ 400 mil/mês."""
    a = transacoes_sinteticas(meses=3, seed=7)
    b = transacoes_sinteticas(meses=3, seed=7)
    c = transacoes_sinteticas(meses=3, seed=8)
    assert a == b
    assert a != c

    receita = sum(t.valor_bruto for t in a)
    meses = len({(t.data.year, t.data.month) for t in a})
    media_mensal = receita / meses
    assert Decimal("250000") < media_mensal < Decimal("600000")

    canais = {t.canal for t in a}
    assert "mercado_livre" in canais and "fisico" in canais
    assert any(t.devolvida for t in a)

    with pytest.raises(ValueError, match="meses"):
        transacoes_sinteticas(meses=0)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
