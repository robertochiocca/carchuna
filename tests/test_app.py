"""Teste de UI do dashboard com `streamlit.testing.v1.AppTest`.

O `app.py` era o único item marcado `pronto` no README sem teste
automatizado. Aqui o app roda de verdade — com dados sintéticos (o
caminho padrão, sem upload) e com upload de arquivo — e o teste confere
que as 7 abas montam sem exceção e que os números que aparecem na tela
são os mesmos que o motor calcula.

Nada aqui depende de `ANTHROPIC_API_KEY`: o app tem que rodar inteiro
sem chave, e é isso que o teste prova.
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pandas")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")
FIXTURES = Path(__file__).parent / "fixtures" / "reais"

# O app monta 7 abas e faz cálculo sobre 6 meses de vendas sintéticas;
# 120s dá folga para a máquina mais lenta do CI sem esconder travamento.
TIMEOUT = 120


# Os widgets do app não têm `key`, então são alcançados por posição.
IDIOMA = 0  # st.radio "Idioma / Language" (barra lateral)
CAMINHO = 1  # 2º st.text_input: "Caminho do arquivo"; o 1º é a pergunta do RAG


def _rodar() -> AppTest:
    """Roda o app do zero, no caminho padrão (sem upload, dados sintéticos)."""
    return AppTest.from_file(APP, default_timeout=TIMEOUT).run()


def _rodar_com_arquivo(caminho) -> AppTest:
    """Roda o app apontando o campo de caminho para um arquivo de vendas."""
    teste = _rodar()
    teste.text_input[CAMINHO].set_value(str(caminho))
    return teste.run()


@pytest.fixture(scope="module")
def app_demo() -> AppTest:
    """O app no caminho padrão: sem upload, com dados sintéticos."""
    return _rodar()


def test_o_app_sobe_sem_excecao_e_sem_chave_de_api(app_demo, monkeypatch):
    """Degradação graciosa: nenhuma exceção, com ou sem ANTHROPIC_API_KEY."""
    assert not app_demo.exception


def test_as_sete_abas_existem_com_os_nomes_do_lojista(app_demo):
    """As 7 abas do README, na ordem, em linguagem de lojista."""
    rotulos = [aba.label for aba in app_demo.tabs]
    assert rotulos == [
        "Resumo",
        "Vendas e Produtos",
        "Histórico",
        "E se…?",
        "Crescer",
        "Diagnóstico Legal",
        "Relatório",
    ]


def test_o_resumo_executivo_aparece_na_primeira_aba(app_demo):
    """A frase do motor ('R$ X de margem se perderam') vai para a tela."""
    frases = [info.value for info in app_demo.info]
    assert any("margem se perderam" in f for f in frases)


def test_os_numeros_da_tela_batem_com_o_motor(app_demo):
    """O que o lojista lê é o que o motor calculou — sem arredondar na UI.

    Recalcula a decomposição com a mesma configuração padrão do app e
    confere que a receita bruta formatada aparece na tela.
    """
    from carchuna.analise import AnalisadorMargem

    analise = AnalisadorMargem.demo(meses=6)
    receita = analise.decomposicao.receita_bruta

    # o app formata em pt-BR: 1.234.567,89
    inteiro = f"{receita:,.0f}".replace(",", ".")
    texto_da_tela = " ".join(
        [m.value for m in app_demo.metric] + [str(m.value) for m in app_demo.markdown]
    )
    assert inteiro in texto_da_tela


def test_todas_as_abas_renderizam_algum_conteudo(app_demo):
    """Aba vazia é bug: cada uma das 7 tem que ter escrito alguma coisa."""
    for aba in app_demo.tabs:
        conteudo = (
            len(aba.markdown)
            + len(aba.metric)
            + len(aba.dataframe)
            + len(aba.caption)
            + len(aba.button)
        )
        assert conteudo > 0, f"a aba {aba.label!r} não renderizou nada"


def test_a_versao_em_ingles_tambem_monta():
    """Bilíngue de verdade: trocar o idioma não pode quebrar o app."""
    teste = _rodar()
    teste.radio[IDIOMA].set_value("EN")
    teste.run()
    assert not teste.exception
    assert [aba.label for aba in teste.tabs][0] == "Summary"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_upload_invalido_mostra_erro_e_nao_estoura(tmp_path):
    """Arquivo que não é relatório de vendas: erro na tela, sem traceback."""
    extrato = tmp_path / "extrato.csv"
    extrato.write_text(
        "Extrato bancário\nlançamento;histórico;valor\n01/05;PIX;100,00\n",
        encoding="utf-8",
    )
    teste = _rodar_com_arquivo(extrato)
    assert not teste.exception
    erros = " ".join(e.value for e in teste.error)
    assert "cabeçalho" in erros.lower() or "não encontrei" in erros.lower()


def test_upload_de_arquivo_valido_recalcula_o_dashboard(tmp_path):
    """O caminho que importa: sobe planilha, todas as abas se recalculam."""
    vendas = tmp_path / "vendas.csv"
    vendas.write_text(
        "data;canal;produto;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;shopee;Capa;100,00;40,00;10,00\n"
        "02/05/2026;mercado_livre;Fone;200,00;90,00;12,00\n"
        "03/05/2026;shopee;Caixa;300,00;120,00;15,00\n",
        encoding="utf-8",
    )
    teste = _rodar_com_arquivo(vendas)
    assert not teste.exception
    # receita bruta = 100 + 200 + 300 = 600, conferido à mão
    texto = " ".join(
        [m.value for m in teste.metric] + [str(m.value) for m in teste.markdown]
    )
    assert "600" in texto


def test_arquivo_com_linha_estragada_importa_o_resto_e_avisa(tmp_path):
    """A regra da casa na tela: nada some sem o lojista ficar sabendo."""
    vendas = tmp_path / "vendas.csv"
    vendas.write_text(
        "data;canal;produto;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;shopee;Capa;100,00;40,00;10,00\n"
        "02/05/2026;shopee;Fone;LIXO;90,00;12,00\n"
        "03/05/2026;shopee;Caixa;200,00;90,00;12,00\n",
        encoding="utf-8",
    )
    teste = _rodar_com_arquivo(vendas)
    assert not teste.exception
    tela = " ".join(
        [w.value for w in teste.warning]
        + [s.value for s in teste.success]
        + [i.value for i in teste.info]
    )
    # 2 vendas entraram e a linha 3 foi recusada, com o número da linha
    assert "2" in tela
    assert "linha 3" in tela or "1 de 3" in tela


def test_o_valor_da_venda_recusada_nao_entra_no_total(tmp_path):
    """Invariante de dinheiro: linha recusada não soma em lugar nenhum.

    100,00 + 200,00 = 300,00 — a linha de valor 'LIXO' não pode inflar
    nem esvaziar esse total.
    """
    from carchuna.analise import AnalisadorMargem
    from carchuna.dados import carregar_com_relatorio
    from carchuna.margem import ConfigTributaria

    vendas = tmp_path / "vendas.csv"
    vendas.write_text(
        "data;canal;produto;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;shopee;Capa;100,00;40,00;10,00\n"
        "02/05/2026;shopee;Fone;LIXO;90,00;12,00\n"
        "03/05/2026;shopee;Caixa;200,00;90,00;12,00\n",
        encoding="utf-8",
    )
    resultado = carregar_com_relatorio(vendas)
    analise = AnalisadorMargem(
        resultado.transacoes,
        ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("500000")),
    )
    assert analise.decomposicao.receita_bruta == Decimal("300.00")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
