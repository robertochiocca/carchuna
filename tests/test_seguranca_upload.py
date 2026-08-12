"""Arquivo hostil na ingestão — o que entra pela porta do lojista.

O dashboard roda num processo compartilhado do Streamlit Community
Cloud, sem login, e aceita CSV/JSON/XLSX/PDF de qualquer visitante. Tudo
que este arquivo prende começa numa célula de planilha.

**V1 — cinco caracteres derrubavam a aplicação.** ``Decimal("1e999")``
passava por toda a defesa de ``_dinheiro``: é ``Decimal``, é finito, não
é ``float``. O estouro vinha adiante, em ``_q().quantize()``, com
``decimal.InvalidOperation`` — que herda de ``ArithmeticError`` e **não**
de ``ValueError`` nem de ``TypeError``, que são exatamente as duas que o
projeto inteiro captura para conter erro de dado. Resultado medido antes
da correção: HTTP 500 na API e traceback na tela do dashboard.

A correção não é um ``except`` novo. É recusar o valor na fronteira,
onde a linha ruim vira linha rejeitada com motivo, e o arquivo continua
importando as boas.
"""

import sys
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.dados import (
    MAX_LINHAS_ARQUIVO,
    MAX_PAGINAS_PDF,
    _conferir_profundidade_json,
    carregar_com_relatorio,
    ler_linhas_brutas,
)
from carchuna.margem import (
    MAX_DINHEIRO,
    MAX_PRAZO_RECEBIMENTO_DIAS,
    ConfigTributaria,
    TabelaCustos,
    Transacao,
    decompor_margem,
)

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))

CABECALHO = "data;canal;valor_bruto;custo_produto;frete_pago\n"


def _venda(**kwargs):
    campos = {
        "data": date(2026, 1, 10),
        "canal": "loja_propria",
        "valor_bruto": Decimal("100"),
        "custo_produto": Decimal("0"),
        "frete_pago": Decimal("0"),
    }
    campos.update(kwargs)
    return Transacao(**campos)


def _csv(tmp_path, linhas: str) -> str:
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(CABECALHO + linhas, encoding="utf-8")
    return str(arquivo)


# ---------------------------------------------------------------------------
# V1 — o número que não é número
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("absurdo", ["1e999", "1E1000", "-1e999", "1e400", "1e26"])
def test_valor_fora_da_faixa_aritmetica_e_recusado_na_fronteira(absurdo):
    """Antes: `InvalidOperation` lá adiante, sem ninguém para capturar.

    O corte é aritmético, não de opinião: acima de 1e26 o `quantize` a
    centavos não cabe na precisão do `Decimal`, e o motor multiplica e
    soma antes de chegar lá. `1e26` está na lista de propósito — é a
    fronteira exata onde a conta deixa de existir.
    """
    with pytest.raises(ValueError, match="faixa de dinheiro"):
        _venda(valor_bruto=Decimal(absurdo))


def test_a_recusa_e_ValueError_para_a_linha_cair_sozinha(tmp_path):
    """`ValueError`, e não `TypeError`, porque o tipo está certo.

    É a mesma decisão do NaN: assim o relatório de importação recusa a
    linha com número e motivo, e as outras entram. Recusar o arquivo
    inteiro por causa de uma célula seria trocar um defeito por outro.
    """
    caminho = _csv(
        tmp_path,
        "2026-01-01;shopee;1e999;10;5\n2026-01-02;shopee;200;80;5\n",
    )
    resultado = carregar_com_relatorio(caminho)

    assert len(resultado.transacoes) == 1  # a venda boa entrou
    assert len(resultado.rejeitadas) == 1
    assert "faixa de dinheiro" in resultado.rejeitadas[0].motivo
    assert resultado.rejeitadas[0].numero == 2  # a linha da planilha


def test_o_estouro_nao_e_ValueError_nem_TypeError():
    """O fato que explica por que nenhum `except` do projeto pegava.

    Sem esta conferência, alguém "simplifica" a guarda achando que o
    `except (ValueError, TypeError)` de `carregar_com_relatorio` já
    cobria — e o defeito volta inteiro.
    """
    import decimal

    assert not issubclass(decimal.InvalidOperation, (ValueError, TypeError))
    assert issubclass(decimal.InvalidOperation, ArithmeticError)


def test_todos_os_campos_de_dinheiro_estao_cobertos():
    """A porta não era uma só: `_dinheiro` valida oito campos."""
    for campo in ("valor_bruto", "custo_produto", "frete_pago", "comissao_cobrada"):
        with pytest.raises(ValueError, match="faixa de dinheiro"):
            _venda(**{campo: Decimal("1e999")})


def test_as_taxas_da_tabela_tambem_estouravam():
    """Multiplicador absurdo derruba a conta igual a parcela absurda."""
    with pytest.raises(ValueError, match="faixa de dinheiro"):
        TabelaCustos(taxa_adquirencia=Decimal("1e999"))
    with pytest.raises(ValueError, match="faixa de dinheiro"):
        TabelaCustos(taxa_antecipacao_mensal=Decimal("1e999"))
    with pytest.raises(ValueError, match="faixa de dinheiro"):
        TabelaCustos(comissao_canal={"shopee": Decimal("1e999")})


def test_o_prazo_de_recebimento_tambem_era_porta():
    """`prazo` é `int` puro e não passava por `_dinheiro`.

    Ele multiplica o valor no custo de antecipação, então um inteiro
    gigante estoura a conta com todo o resto dentro da faixa.
    """
    with pytest.raises(ValueError, match="passa de 365 dias"):
        _venda(prazo_recebimento_dias=10**30)


# ---------------------------------------------------------------------------
# O limite não pode ser tão apertado que estorve uso real
# ---------------------------------------------------------------------------


def test_a_comissao_de_900_por_cento_continua_passando():
    """Este é o limite do limite, e ele é deliberado.

    Uma comissão de 900% da receita é absurda — e quem a carimba é
    `conferir_plausibilidade`, não `_dinheiro`. A divisão de trabalho é
    a do projeto: aqui recusa-se o que **não é número calculável**; lá
    carimba-se o que **é número e não cabe na realidade**. Confundir as
    duas apagaria o teste que prova que a identidade estrutural não vê
    absurdo nenhum.
    """
    tabela = TabelaCustos(comissao_canal={"shopee": Decimal("9")})
    assert tabela.comissao_canal["shopee"] == Decimal("9")


def test_o_valor_exatamente_no_limite_passa():
    """A recusa é para quem passou, não para quem chegou."""
    assert _venda(valor_bruto=MAX_DINHEIRO).valor_bruto == MAX_DINHEIRO
    assert _venda(prazo_recebimento_dias=MAX_PRAZO_RECEBIMENTO_DIAS)


def test_o_pior_caso_aritmetico_ainda_cabe():
    """O limite foi escolhido para esta conta fechar, então ela é teste.

    Pior caso do motor: custo de antecipação (`valor × taxa × dias/30`)
    somado sobre a lista inteira. No teto de todos os campos, com o teto
    de lançamentos da API, o resultado ainda tem de quantizar.
    """
    from carchuna.api.schemas import MAX_TRANSACOES_POR_CHAMADA

    pior = (
        Decimal(MAX_TRANSACOES_POR_CHAMADA)
        * MAX_DINHEIRO
        * MAX_DINHEIRO
        * Decimal(MAX_PRAZO_RECEBIMENTO_DIAS)
        / Decimal(30)
    )
    assert pior.quantize(Decimal("0.01"))  # não levanta InvalidOperation


def test_uma_venda_grande_de_verdade_continua_calculando():
    """R$ 1 milhão numa linha é raro e legítimo; tem de passar."""
    d = decompor_margem([_venda(valor_bruto=Decimal("1000000"))], CONFIG)
    assert d.receita_bruta == Decimal("1000000.00")


def test_a_mensagem_ensina_a_achar_a_celula():
    """Mensagem de erro que não diz onde olhar é mensagem inútil.

    E ela não pode virar mapa para atacante: sem caminho de arquivo, sem
    nome de módulo, sem stack.
    """
    with pytest.raises(ValueError) as erro:
        _venda(valor_bruto=Decimal("1e999"))
    mensagem = str(erro.value)

    assert "valor_bruto" in mensagem
    assert "notação científica" in mensagem
    assert "1.000.000.000,00" in mensagem  # o limite, em português
    for vazamento in ("Traceback", "carchuna/", ".py", 'File "'):
        assert vazamento not in mensagem


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------------
# V3 — tetos de ingestão
#
# Duas exceções desta seção são da mesma família do V1: `RecursionError`
# (JSON aninhado) e `OSError` (pacote XLSX corrompido) também escapam do
# `except (ValueError, TypeError)` com que o projeto contém erro de dado.
# Foram achadas medindo, não lendo — e o padrão já tinha nome.
# ---------------------------------------------------------------------------


def _xlsx_com(tmp_path, nome, partes):
    caminho = tmp_path / nome
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as pacote:
        for interno, conteudo in partes.items():
            pacote.writestr(interno, conteudo)
    return str(caminho)


def test_json_aninhado_e_recusado_antes_de_ser_parseado():
    """`json.load` estoura com `RecursionError`, que ninguém captura.

    A contagem é feita no texto justamente para não pagar o parse que
    ela evita.
    """
    fundo = "[" + "[" * 50_000 + "]" * 50_000 + "]"
    with pytest.raises(ValueError, match="aninhada demais"):
        _conferir_profundidade_json(fundo)


def test_o_json_profundo_recusa_pelo_caminho_de_verdade(tmp_path):
    """Pelo `ler_linhas_brutas`, e não chamando a guarda na mão.

    Sem passar pelo leitor, este arquivo derrubava a aplicação com
    `RecursionError` em vez de recusar o arquivo — que é o defeito, e não
    a existência da função de contagem.
    """
    fundo = tmp_path / "fundo.json"
    fundo.write_text("[" + "[" * 50_000 + "]" * 50_000 + "]", encoding="utf-8")

    with pytest.raises(ValueError, match="aninhada demais"):
        ler_linhas_brutas(str(fundo))


def test_o_recursion_error_tambem_escapava_do_except_do_projeto():
    """O fato que põe este teto na mesma família do V1."""
    assert not issubclass(RecursionError, (ValueError, TypeError))


def test_aspas_e_escape_nao_confundem_a_contagem():
    """Colchete dentro de string não é aninhamento.

    Sem isto, um nome de produto com `[[[` no texto derrubaria a
    importação de um arquivo perfeitamente válido.
    """
    _conferir_profundidade_json('[{"produto": "' + "[" * 100 + '"}]')
    _conferir_profundidade_json('[{"produto": "aspa escapada \\" e [[["}]')


def test_a_profundidade_normal_de_uma_lista_de_vendas_passa():
    _conferir_profundidade_json('[{"data": "2026-01-01", "canal": "shopee"}]')


def test_zip_bomb_e_recusado_sem_expandir(tmp_path):
    """199 KB no disco declarando 210 MB — razão de 1028x.

    O tamanho descomprimido está no cabeçalho do zip, então a conferência
    não paga o custo que evita.
    """
    bomba = _xlsx_com(
        tmp_path,
        "bomba.xlsx",
        {"[Content_Types].xml": "<x/>", "carga.bin": b"\0" * (200 * 1024 * 1024)},
    )
    assert Path(bomba).stat().st_size < 1024 * 1024  # pequeno no disco

    with pytest.raises(ValueError, match="expande para um tamanho"):
        ler_linhas_brutas(bomba)


def test_xlsx_que_nao_e_zip_recusa_sem_derrubar(tmp_path):
    """Extensão mentirosa: `.xlsx` que é texto puro."""
    mentiroso = tmp_path / "mentira.xlsx"
    mentiroso.write_text("isto é texto, não uma planilha", encoding="utf-8")
    with pytest.raises(ValueError, match="não é uma planilha"):
        ler_linhas_brutas(str(mentiroso))


def test_o_openpyxl_levantava_OSError_por_fora_de_todo_except():
    """Pacote corrompido derrubava a tela em vez de recusar o arquivo."""
    assert not issubclass(OSError, (ValueError, TypeError))


def test_csv_acima_do_teto_de_linhas_e_recusado(tmp_path):
    gigante = tmp_path / "gigante.csv"
    gigante.write_text(
        CABECALHO + "2026-01-01;shopee;10;5;1\n" * (MAX_LINHAS_ARQUIVO + 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="processa até"):
        ler_linhas_brutas(str(gigante))


def test_json_com_array_gigante_e_recusado(tmp_path):
    enorme = tmp_path / "enorme.json"
    item = '{"data":"2026-01-01","canal":"shopee"}'
    enorme.write_text(
        "[" + ",".join([item] * (MAX_LINHAS_ARQUIVO + 1)) + "]", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="processa até"):
        ler_linhas_brutas(str(enorme))


def test_o_teto_de_paginas_do_pdf_esta_declarado():
    """`extract_tables()` custa caro por página.

    Um PDF pequeno e denso é o jeito mais barato de queimar CPU alheia, e
    até aqui não havia corte nenhum no laço `for pagina in pdf.pages`.
    """
    fonte = Path("carchuna/dados.py").read_text(encoding="utf-8")
    assert "MAX_PAGINAS_PDF" in fonte
    assert "if len(pdf.pages) > MAX_PAGINAS_PDF:" in fonte
    assert MAX_PAGINAS_PDF > 0


def test_o_teto_de_upload_do_streamlit_esta_configurado():
    """Sem a seção `[server]`, vale o default de 200 MB."""
    config = Path(".streamlit/config.toml").read_text(encoding="utf-8")
    configurado = tomllib.loads(config)
    assert configurado["server"]["maxUploadSize"] <= 50


def test_as_fixtures_reais_continuam_importando_igual():
    """Regressão: nenhum teto pode estorvar o arquivo de verdade."""
    reais = Path("tests/fixtures/reais")
    crus = sorted(reais.glob("*_cru.csv"))
    assert crus, "as fixtures reais sumiram"
    for arquivo in crus:
        assert ler_linhas_brutas(str(arquivo)), arquivo.name
