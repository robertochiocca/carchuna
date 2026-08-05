"""Ingestão de exports CRUS de marketplace — o arquivo como o lojista baixa.

Cada teste aqui parte de um arquivo que um lojista realmente teria na
pasta de Downloads: acentuação do Excel brasileiro (latin-1/cp1252),
linhas de título antes do cabeçalho, data em dd/mm/aaaa, uma linha
estragada no meio das boas. O critério é o do produto: **entra sem
intervenção manual, ou falha com uma frase que o lojista entende**.
"""

import io
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.dados import carregar_transacoes

CABECALHO = "data;canal;produto;valor_bruto;custo_produto;frete_pago\n"


def test_csv_em_latin1_do_excel_brasileiro(tmp_path):
    """Excel em português salva 'CSV (separado por vírgulas)' em cp1252.

    O byte 0xF3 ('ó' em latin-1) não é UTF-8 válido: antes desta correção
    o arquivo morria com `UnicodeDecodeError`, que não é frase de lojista.
    """
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_bytes(
        (CABECALHO + "2026-05-01;Loja Própria;Relógio;1.234,56;600,00;25,90\n").encode(
            "latin-1"
        )
    )
    (transacao,) = carregar_transacoes(arquivo)
    # 'Loja Própria' normalizado: minúsculas, sem acento, espaço -> _
    assert transacao.canal == "loja_propria"
    assert transacao.produto == "Relógio"
    assert transacao.valor_bruto == Decimal("1234.56")


def test_csv_em_cp1252_com_caractere_fora_do_latin1(tmp_path):
    """cp1252 tem o travessão '–' (0x96), que latin-1 lê como controle.

    Títulos de anúncio de marketplace vivem cheios deles: 'Fone – 2 unid.'
    """
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_bytes(
        (CABECALHO + "2026-05-01;shopee;Fone – 2 unid.;100,00;40,00;10,00\n").encode(
            "cp1252"
        )
    )
    (transacao,) = carregar_transacoes(arquivo)
    assert transacao.produto == "Fone – 2 unid."
    assert transacao.valor_bruto == Decimal("100.00")


def test_utf8_e_utf8_com_bom_continuam_funcionando(tmp_path):
    """Sem regressão: o caminho feliz de hoje segue idêntico."""
    linha = CABECALHO + "2026-05-01;Físico;Relógio;100,00;40,00;10,00\n"

    utf8 = tmp_path / "utf8.csv"
    utf8.write_text(linha, encoding="utf-8")
    (t_utf8,) = carregar_transacoes(utf8)

    com_bom = tmp_path / "bom.csv"
    com_bom.write_text(linha, encoding="utf-8-sig")
    (t_bom,) = carregar_transacoes(com_bom)

    assert t_utf8.canal == t_bom.canal == "fisico"
    assert t_utf8.produto == t_bom.produto == "Relógio"
    assert t_utf8.valor_bruto == t_bom.valor_bruto == Decimal("100.00")


def test_upload_em_bytes_tambem_aceita_latin1():
    """O upload do Streamlit chega como buffer de bytes, não como caminho."""
    bruto = (CABECALHO + "2026-05-01;Físico;Capa;80,00;30,00;0,00\n").encode("latin-1")
    (transacao,) = carregar_transacoes(io.BytesIO(bruto), name="vendas.csv")
    assert transacao.canal == "fisico"
    assert transacao.custo_produto == Decimal("30.00")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
