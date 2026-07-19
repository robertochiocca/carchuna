"""Teste do relatório PDF (requer matplotlib, extra `viz`)."""

import io
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("matplotlib")

from carchuna.cenarios import rodar_cenarios_padrao
from carchuna.dados import transacoes_sinteticas
from carchuna.diagnostico import ParametrosDiagnostico, diagnosticar
from carchuna.margem import ConfigTributaria, TabelaCustos, decompor_margem
from carchuna.rag.retrieval import Retriever
from carchuna.relatorio import _brl, gerar_pdf_relatorio

CONFIG = ConfigTributaria(
    regime="simples", anexo_simples="III", rbt12=Decimal("360000")
)


def test_brl_formata_moeda_brasileira():
    assert _brl(Decimal("1234567.89")) == "R$ 1.234.567,89"
    assert _brl(Decimal("-42.50")) == "-R$ 42,50"
    assert _brl(Decimal("0.00")) == "R$ 0,00"


def test_pdf_de_3_paginas_com_cenarios_e_achados():
    transacoes = transacoes_sinteticas(meses=2)
    tabela = TabelaCustos(taxa_antecipacao_mensal=Decimal("0.03"))
    decomposicao = decompor_margem(transacoes, CONFIG, tabela)
    cenarios = rodar_cenarios_padrao(transacoes, CONFIG, tabela)
    achados = diagnosticar(
        transacoes, CONFIG, tabela, ParametrosDiagnostico(), Retriever()
    )
    assert achados, "cenário do teste deveria produzir achados"

    buffer = io.BytesIO()
    gerar_pdf_relatorio(
        decomposicao, cenarios, achados, buffer, narrativa="Resumo de teste."
    )
    conteudo = buffer.getvalue()
    assert conteudo.startswith(b"%PDF")
    assert conteudo.count(b"/Type /Page ") == 3  # exatamente 3 páginas


def test_pdf_vazio_de_cenarios_e_achados_tambem_sai():
    transacoes = transacoes_sinteticas(meses=2)
    decomposicao = decompor_margem(transacoes, CONFIG)
    buffer = io.BytesIO()
    gerar_pdf_relatorio(decomposicao, [], [], buffer)
    assert buffer.getvalue().startswith(b"%PDF")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
