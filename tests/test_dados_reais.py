"""Ingestão de exports CRUS de marketplace — o arquivo como o lojista baixa.

Cada teste aqui parte de um arquivo que um lojista realmente teria na
pasta de Downloads: acentuação do Excel brasileiro (latin-1/cp1252),
linhas de título antes do cabeçalho, data em dd/mm/aaaa, uma linha
estragada no meio das boas. O critério é o do produto: **entra sem
intervenção manual, ou falha com uma frase que o lojista entende**.
"""

import io
import sys
from datetime import date
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


# ---------------------------------------------------------------------------
# Linhas de título antes do cabeçalho e detecção de separador
# ---------------------------------------------------------------------------


def test_linhas_de_titulo_antes_do_cabecalho(tmp_path):
    """Relatório de marketplace vem com título e período antes da tabela.

    O cabeçalho de verdade é a 4ª linha; as três primeiras são texto solto
    e uma linha em branco. Antes, o `DictReader` tomava 'Relatório de
    vendas' como cabeçalho e todas as colunas ficavam vazias.
    """
    arquivo = tmp_path / "shopee.csv"
    arquivo.write_text(
        "Relatório de vendas - Shopee\n"
        "Período: 01/05/2026 a 31/05/2026\n"
        "\n" + CABECALHO + "2026-05-01;shopee;Capa;100,00;40,00;10,00\n"
        "2026-05-02;shopee;Fone;200,00;90,00;12,00\n",
        encoding="utf-8",
    )
    transacoes = carregar_transacoes(arquivo)
    assert len(transacoes) == 2
    assert transacoes[0].valor_bruto == Decimal("100.00")
    assert transacoes[1].valor_bruto == Decimal("200.00")


def test_separador_detectado_no_cabecalho_e_nao_na_primeira_linha(tmp_path):
    """A linha de título tem vírgulas; a tabela é separada por ';'.

    Detectar o separador na 1ª linha ('Período: 01/05/2026, loja X, ...')
    escolheria ',' e quebraria a tabela inteira.
    """
    arquivo = tmp_path / "ml.csv"
    arquivo.write_text(
        "Relatório, gerado em 01/06/2026, loja Exemplo, todas as contas\n"
        + CABECALHO
        + "2026-05-01;mercado_livre;Capa;1.234,56;600,00;25,90\n",
        encoding="utf-8",
    )
    (transacao,) = carregar_transacoes(arquivo)
    assert transacao.canal == "mercado_livre"
    assert transacao.valor_bruto == Decimal("1234.56")


def test_separador_tab_do_export_copiado_da_tela(tmp_path):
    """Colar a tabela do painel no Excel e salvar gera TSV."""
    arquivo = tmp_path / "colado.tsv"
    arquivo.write_text(
        CABECALHO.replace(";", "\t")
        + "2026-05-01\tshopee\tCapa\t100,00\t40,00\t10,00\n",
        encoding="utf-8",
    )
    (transacao,) = carregar_transacoes(arquivo)
    assert transacao.valor_bruto == Decimal("100.00")


def test_arquivo_sem_nenhum_cabecalho_reconhecivel(tmp_path):
    """Sem colunas conhecidas, a mensagem diz o que fazer — não estoura."""
    arquivo = tmp_path / "extrato.csv"
    arquivo.write_text(
        "Extrato bancário\nlançamento;histórico;valor\n01/05;PIX recebido;100,00\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(arquivo)
    mensagem = str(erro.value)
    assert "cabeçalho" in mensagem.lower()
    # a frase precisa citar as colunas que a Carchuna procura
    assert "valor_bruto" in mensagem


# ---------------------------------------------------------------------------
# Datas em formatos mistos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("2026-05-01", date(2026, 5, 1)),  # ISO, o formato do modelo
        ("01/05/2026", date(2026, 5, 1)),  # dd/mm/aaaa — padrão brasileiro
        ("01-05-2026", date(2026, 5, 1)),  # dd-mm-aaaa — export de ERP
        ("01.05.2026", date(2026, 5, 1)),  # dd.mm.aaaa
        ("2026/05/01", date(2026, 5, 1)),  # aaaa/mm/dd
        ("01/05/26", date(2026, 5, 1)),  # ano com 2 dígitos
        ("2026-05-01 14:32:07", date(2026, 5, 1)),  # ISO com hora
        ("01/05/2026 14:32", date(2026, 5, 1)),  # brasileiro com hora
        ("2026-05-01T14:32:07Z", date(2026, 5, 1)),  # ISO 8601 de API
    ],
)
def test_formatos_de_data_aceitos(tmp_path, texto, esperado):
    """Cada painel exporta a data de um jeito; todos viram a mesma date."""
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        CABECALHO + f"{texto};shopee;Capa;100,00;40,00;10,00\n", encoding="utf-8"
    )
    (transacao,) = carregar_transacoes(arquivo)
    assert transacao.data == esperado


def test_dia_e_mes_ambiguos_resolvem_para_o_padrao_brasileiro(tmp_path):
    """05/01/2026 é 5 de janeiro no Brasil, não 1º de maio.

    Ambíguo por natureza (nos EUA seria o contrário); o público da
    Carchuna é brasileiro, então dd/mm vence — e a decisão está no
    docstring do módulo para quem for ler depois.
    """
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        CABECALHO + "05/01/2026;shopee;Capa;100,00;40,00;10,00\n", encoding="utf-8"
    )
    (transacao,) = carregar_transacoes(arquivo)
    assert transacao.data == date(2026, 1, 5)


def test_data_invalida_diz_qual_e_a_linha_e_o_que_esperava(tmp_path):
    """Data ilegível vira frase de lojista, não `Invalid isoformat string`."""
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        CABECALHO + "ontem;shopee;Capa;100,00;40,00;10,00\n", encoding="utf-8"
    )
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(arquivo)
    mensagem = str(erro.value)
    assert "linha 2" in mensagem
    assert "ontem" in mensagem
    assert "dd/mm/aaaa" in mensagem


def test_data_com_dia_31_em_mes_de_30_e_recusada(tmp_path):
    """31/04 não existe: recusar é mais honesto que 'corrigir' para 30/04."""
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        CABECALHO + "31/04/2026;shopee;Capa;100,00;40,00;10,00\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="linha 2"):
        carregar_transacoes(arquivo)


# ---------------------------------------------------------------------------
# Linhas parcialmente inválidas: relatório de rejeitadas, nunca descarte mudo
# ---------------------------------------------------------------------------

CSV_COM_LINHAS_RUINS = (
    CABECALHO + "2026-05-01;shopee;Capa;100,00;40,00;10,00\n"  # linha 2: boa
    "2026-05-02;shopee;Fone;LIXO;90,00;12,00\n"  # linha 3: valor ilegível
    "2026-05-03;shopee;Caixa;200,00;90,00;12,00\n"  # linha 4: boa
    "ontem;shopee;Capa;50,00;20,00;5,00\n"  # linha 5: data ilegível
    ";shopee;Capa;50,00;20,00;5,00\n"  # linha 6: data vazia
    "2026-05-06;shopee;Relógio;300,00;100,00;15,00\n"  # linha 7: boa
)


def test_relatorio_de_rejeitadas_separa_boas_de_ruins(tmp_path):
    """3 linhas boas, 3 ruins: importa as 3 e explica as outras 3.

    Conferido à mão: linhas 2, 4 e 7 são válidas (100 + 200 + 300 = 600
    de receita bruta); linhas 3, 5 e 6 caem, cada uma com o seu motivo.
    """
    from carchuna.dados import carregar_com_relatorio

    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(CSV_COM_LINHAS_RUINS, encoding="utf-8")
    resultado = carregar_com_relatorio(arquivo)

    assert len(resultado.transacoes) == 3
    assert sum(t.valor_bruto for t in resultado.transacoes) == Decimal("600.00")

    assert [r.numero for r in resultado.rejeitadas] == [3, 5, 6]
    # nenhuma linha some sem explicação
    assert resultado.total_lidas == 6
    assert resultado.total_lidas == len(resultado.transacoes) + len(
        resultado.rejeitadas
    )


def test_cada_rejeitada_diz_o_motivo_e_guarda_a_linha_original(tmp_path):
    """O lojista precisa achar a linha na planilha dele e ver o porquê."""
    from carchuna.dados import carregar_com_relatorio

    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(CSV_COM_LINHAS_RUINS, encoding="utf-8")
    resultado = carregar_com_relatorio(arquivo)
    por_numero = {r.numero: r for r in resultado.rejeitadas}

    assert "valor monetário" in por_numero[3].motivo
    assert por_numero[3].conteudo["produto"] == "Fone"

    assert "data" in por_numero[5].motivo.lower()
    assert "`data`" in por_numero[6].motivo and "vazia" in por_numero[6].motivo


def test_resumo_da_importacao_e_frase_de_lojista(tmp_path):
    """'3 de 6 linhas ficaram de fora' — número e motivo, sem jargão."""
    from carchuna.dados import carregar_com_relatorio

    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(CSV_COM_LINHAS_RUINS, encoding="utf-8")
    resumo = carregar_com_relatorio(arquivo).resumo()

    assert "3" in resumo and "6" in resumo
    assert "linha" in resumo.lower()
    assert "Traceback" not in resumo


def test_arquivo_todo_bom_nao_tem_rejeitadas(tmp_path):
    """Caminho feliz: relatório vazio, resumo diz que entrou tudo."""
    from carchuna.dados import carregar_com_relatorio

    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        CABECALHO + "2026-05-01;shopee;Capa;100,00;40,00;10,00\n", encoding="utf-8"
    )
    resultado = carregar_com_relatorio(arquivo)
    assert resultado.rejeitadas == []
    assert "1" in resultado.resumo()


def test_carregar_transacoes_continua_estrito(tmp_path):
    """O contrato de hoje não muda: quem chama `carregar_transacoes`
    quer tudo ou nada, e continua recebendo a exceção da primeira linha
    ruim. Quem quer importar o que dá é quem chama `carregar_com_relatorio`.
    """
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(CSV_COM_LINHAS_RUINS, encoding="utf-8")
    with pytest.raises(ValueError, match="linha 3"):
        carregar_transacoes(arquivo)


def test_arquivo_so_com_linhas_ruins_nao_finge_sucesso(tmp_path):
    """Zero transações válidas: o resultado diz isso na cara."""
    from carchuna.dados import carregar_com_relatorio

    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        CABECALHO + "ontem;shopee;Capa;LIXO;20,00;5,00\n", encoding="utf-8"
    )
    resultado = carregar_com_relatorio(arquivo)
    assert resultado.transacoes == []
    assert len(resultado.rejeitadas) == 1
    assert "nenhuma" in resultado.resumo().lower()


# ---------------------------------------------------------------------------
# Coluna que não existe no arquivo: a mensagem tem que ensinar onde achar
# ---------------------------------------------------------------------------


def test_coluna_de_valor_ausente_diz_como_ela_se_chama_na_shopee(tmp_path):
    """O caso do enunciado: 'a coluna de valor não foi encontrada'.

    O arquivo é um export da Shopee com os nomes do painel. A mensagem
    precisa dizer QUAL coluna falta, COMO ela costuma se chamar lá, e o
    que o lojista faz agora.
    """
    arquivo = tmp_path / "shopee.csv"
    arquivo.write_text(
        "Data do pedido;Status;Custo unitário;Valor do frete\n"
        "01/05/2026;Concluído;40,00;10,00\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(arquivo)
    mensagem = str(erro.value)

    assert "valor_bruto" in mensagem
    assert "Shopee" in mensagem
    # diz o que o lojista tem no arquivo, para ele se localizar
    assert "Data do pedido" in mensagem
    # e o caminho de saída
    assert "mapeador" in mensagem.lower()
    # não vaza jargão de Python
    assert "['" not in mensagem


def test_falta_de_custo_explica_que_o_marketplace_nao_sabe_o_custo(tmp_path):
    """Nenhum relatório de marketplace traz o CMV — ele é do lojista.

    Mandar o usuário procurar 'a coluna de custo no painel da Shopee'
    seria mentira: ela não existe lá. A frase tem que dizer isso.
    """
    arquivo = tmp_path / "shopee.csv"
    arquivo.write_text(
        "Data do pedido;Valor total do pedido;Valor do frete\n"
        "01/05/2026;100,00;10,00\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(arquivo)
    mensagem = str(erro.value)
    assert "custo_produto" in mensagem
    assert "marketplace não" in mensagem or "marketplace nao" in mensagem


def test_falta_de_canal_explica_relatorio_de_um_canal_so(tmp_path):
    """Relatório de um canal só não tem coluna de canal — e tudo bem."""
    arquivo = tmp_path / "shopee.csv"
    arquivo.write_text(
        "data;valor_bruto;custo_produto;frete_pago\n" "01/05/2026;100,00;40,00;10,00\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(arquivo)
    mensagem = str(erro.value)
    assert "canal" in mensagem
    assert "um canal só" in mensagem or "um canal so" in mensagem


def test_varias_colunas_faltando_saem_todas_de_uma_vez(tmp_path):
    """Corrigir uma, subir de novo, descobrir a próxima é tortura."""
    arquivo = tmp_path / "quase_nada.csv"
    arquivo.write_text("data;produto\n01/05/2026;Capa\n", encoding="utf-8")
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(arquivo)
    mensagem = str(erro.value)
    for coluna in ("canal", "valor_bruto", "custo_produto", "frete_pago"):
        assert coluna in mensagem


def test_coluna_existe_mas_vazia_e_erro_de_linha_nao_de_arquivo(tmp_path):
    """Distinção que importa: a coluna existe, a célula é que está vazia.

    Isso é problema de UMA linha (vai para o relatório de rejeitadas),
    não do arquivo — e a mensagem tem que dizer a linha.
    """
    from carchuna.dados import carregar_com_relatorio

    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        CABECALHO + "2026-05-01;shopee;Capa;;40,00;10,00\n"
        "2026-05-02;shopee;Fone;100,00;40,00;10,00\n",
        encoding="utf-8",
    )
    resultado = carregar_com_relatorio(arquivo)
    assert len(resultado.transacoes) == 1
    (rejeitada,) = resultado.rejeitadas
    assert rejeitada.numero == 2
    assert "valor_bruto" in rejeitada.motivo
    assert "vazia" in rejeitada.motivo or "em branco" in rejeitada.motivo


def test_mensagem_aponta_a_coluna_do_arquivo_que_parece_ser_a_certa(tmp_path):
    """Se a informação está lá com outro nome, a mensagem diz qual é.

    O arquivo tem 'Data do pedido' e 'Valor total do pedido': em vez de
    só reclamar que falta `data`, a frase mostra o palpite do de-para.
    """
    arquivo = tmp_path / "shopee.csv"
    arquivo.write_text(
        "Data do pedido;Valor total do pedido;Custo unitário;Taxa de envio\n"
        "01/05/2026;100,00;40,00;10,00\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(arquivo)
    mensagem = str(erro.value)
    assert 'parece ser "Data do pedido"' in mensagem
    assert 'parece ser "Valor total do pedido"' in mensagem
    # `canal` não tem candidato nenhum no arquivo: nada de palpite inventado
    trecho_canal = mensagem.split("`canal`")[1].split("•")[0]
    assert "parece ser" not in trecho_canal


def test_concordancia_da_mensagem_no_singular_e_no_plural(tmp_path):
    """'Faltou 1 coluna' / 'Faltaram 3 colunas' — texto que vai para a tela."""
    uma = tmp_path / "uma.csv"
    uma.write_text(
        "data;canal;valor_bruto;custo_produto\n01/05/2026;shopee;100,00;40,00\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(uma)
    assert "Faltou 1 coluna" in str(erro.value)

    varias = tmp_path / "varias.csv"
    varias.write_text("data;canal\n01/05/2026;shopee\n", encoding="utf-8")
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(varias)
    assert "Faltaram 3 colunas" in str(erro.value)


def test_relatorio_de_mercado_livre_tambem_e_citado(tmp_path):
    """As duas plataformas do público-alvo aparecem na dica."""
    arquivo = tmp_path / "ml.csv"
    arquivo.write_text("data;canal\n01/05/2026;mercado_livre\n", encoding="utf-8")
    with pytest.raises(ValueError) as erro:
        carregar_transacoes(arquivo)
    assert "Mercado Livre" in str(erro.value)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------------
# O mesmo parser serve o formulário do dashboard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "digitado,esperado",
    [
        ("2,49", "2.49"),
        ("2.49", "2.49"),
        ("2", "2"),
        ("1,99", "1.99"),
        ("0", "0"),
        ("R$ 1.234,56", "1234.56"),
        (" 3,5 ", "3.5"),
    ],
)
def test_decimal_de_texto_le_o_que_o_lojista_digita(digitado, esperado):
    """O que o usuário digita vira Decimal direto, sem passar por float.

    É o mesmo parser das planilhas, reaproveitado no formulário: a taxa
    da maquininha entra como texto e nunca encosta em `float`, senão
    2,49% viraria 0.024900000000000002 antes de multiplicar dinheiro.
    """
    from carchuna.dados import decimal_de_texto

    assert decimal_de_texto(digitado, "taxa") == Decimal(esperado)


def test_decimal_de_texto_recusa_lixo_com_frase_de_lojista():
    from carchuna.dados import decimal_de_texto

    with pytest.raises(ValueError) as erro:
        decimal_de_texto("dois e meio", "taxa da maquininha")
    assert "taxa da maquininha" in str(erro.value)
    assert "dois e meio" in str(erro.value)


def test_a_taxa_do_formulario_nao_perde_precisao_como_o_float_perderia():
    """A prova de que a regra tem consequência prática.

    2,49% via float: 2.49/100 = 0.024900000000000002 — e esse resto
    multiplica cada venda da base. Via Decimal é 0.0249 exato.
    """
    from carchuna.dados import decimal_de_texto

    por_decimal = decimal_de_texto("2,49", "taxa") / 100
    assert por_decimal == Decimal("0.0249")
    assert str(por_decimal) == "0.0249"
    # o caminho antigo, para deixar registrado o que se estava evitando
    assert Decimal(str(2.49)) / 100 == Decimal("0.0249")  # str() salva...
    assert Decimal(2.49) / 100 != Decimal("0.0249")  # ...mas o float cru, não
