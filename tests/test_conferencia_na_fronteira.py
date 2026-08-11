"""A conferência valia para quem entrava pela tela, e só.

O argumento inteiro do projeto é que todo número sai conferido. Mas as
quatro conferências viviam em `carchuna/margem.py` sem que ninguém as
chamasse fora dos testes, com uma exceção: o dashboard rodava
``conferir_plausibilidade``. A API devolvia a decomposição crua. Quem
integrasse por HTTP recebia uma margem de −1854% com exatamente a mesma
cara de um número bom.

E ``reconciliar`` — que é a única das quatro que **valida o número**, em
vez de conferir a soma que o próprio motor montou — não era chamada em
lugar nenhum da produção. Ela existia, era testada, e não protegia
ninguém.

Este arquivo prende as duas fronteiras: o que a API devolve e o que a
tela mostra. A promessa não pode depender da porta por onde se entra.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("streamlit")
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from carchuna.api.main import app

CLIENTE = TestClient(app)

CONFIG = {"regime": "simples", "anexo_simples": "I", "rbt12": "360000"}


def _venda(valor, custo, frete="10", dia=10):
    return {
        "data": f"2026-05-{dia:02d}",
        "canal": "shopee",
        "valor_bruto": valor,
        "custo_produto": custo,
        "frete_pago": frete,
    }


def _decompor(transacoes):
    resposta = CLIENTE.post(
        "/api/v1/margem/decompor",
        json={"transacoes": transacoes, "config": CONFIG},
    )
    assert resposta.status_code == 200
    return resposta.json()


# ---------------------------------------------------------------------------
# A fronteira da API
# ---------------------------------------------------------------------------


def test_a_api_devolve_as_conferencias_junto_com_o_numero():
    """Base sadia: as duas conferências saem `ok` e a reconciliação fecha."""
    corpo = _decompor([_venda("1000", "400")])
    conferencias = corpo["conferencias"]

    assert conferencias["plausibilidade"]["status"] == "ok"
    assert conferencias["reconciliacao"]["status"] == "ok"
    # os dois caminhos de cálculo dão o mesmo lucro, ao centavo
    assert conferencias["reconciliacao"]["valor"] == "0.00"


def test_a_api_carimba_o_numero_absurdo_em_vez_de_devolve_lo_calado():
    """CMV de R$ 5.000 numa venda de R$ 100 — o caso que motivou tudo.

    Antes: HTTP 200, margem de −4.909% no corpo, nada dizendo nada. O
    cliente que confiasse na API mostraria isso ao lojista.
    """
    corpo = _decompor([_venda("100", "5000")])

    assert corpo["conferencias"]["plausibilidade"]["status"] == "implausivel"
    motivo = corpo["conferencias"]["plausibilidade"]["motivo"]
    assert "mais que todo o faturamento" in motivo
    # e o número continua lá, porque escondê-lo não conserta o dado
    assert corpo["decomposicao"]["margem_liquida"] == "-4929.65"


def test_o_carimbo_nao_vira_erro_de_requisicao():
    """Implausível é resposta 200 com aviso, não 4xx.

    A conta rodou e o número existe: quem chamou tem direito de auditá-lo.
    Devolver erro esconderia justamente o dado que precisa ser olhado.
    """
    resposta = CLIENTE.post(
        "/api/v1/margem/decompor",
        json={"transacoes": [_venda("100", "5000")], "config": CONFIG},
    )
    assert resposta.status_code == 200


def test_a_reconciliacao_da_api_e_dinheiro_em_string():
    """A garantia do centavo vale também para a conferência.

    Se a diferença entre os dois caminhos viajasse como float, a
    conferência do float estaria sendo publicada em float — o defeito
    dentro da própria checagem contra ele.
    """
    corpo = _decompor([_venda("1000", "400"), _venda("777.77", "333.33", dia=20)])
    assert isinstance(corpo["conferencias"]["reconciliacao"]["valor"], str)
    assert isinstance(corpo["conferencias"]["plausibilidade"]["valor"], str)


def test_a_conferencia_acompanha_todas_as_deducoes_e_nao_so_o_cmv():
    """Comissão informada acima do faturamento também é carimbada."""
    venda = _venda("100", "10")
    venda["comissao_cobrada"] = "900"
    corpo = _decompor([venda])
    assert corpo["conferencias"]["plausibilidade"]["status"] == "implausivel"


# ---------------------------------------------------------------------------
# A fronteira da tela
# ---------------------------------------------------------------------------


def _rodar_com(csv: str, tmp_path):
    """Aponta o campo de caminho do app para um arquivo — como `test_app.py`."""
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(csv, encoding="utf-8")
    teste = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=120
    ).run()
    teste.text_input("caminho_arquivo").set_value(str(arquivo))
    return teste.run()


def test_a_tela_roda_as_duas_conferencias_e_nao_so_a_plausibilidade():
    """Guarda estrutural, na linha do teste de widget cacheado.

    Comportamento aqui não serve: numa base sadia as duas conferências
    passam e nada é impresso, então apagar a chamada não derrubaria teste
    nenhum. E não dá para fabricar uma reconciliação que falhe pela tela —
    ela só falha se o motor estiver quebrado, que é exatamente o defeito
    que ela existe para pegar.

    Então este lê a árvore sintática do `app.py`: a reconciliação é
    chamada, o resultado entra na bandeja que as abas consomem, e ele é
    mostrado em `st.error` como a plausibilidade já era.
    """
    import ast

    fonte = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte)

    chamadas = {
        no.func.id
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name)
    }
    assert {"reconciliar", "conferir_plausibilidade"} <= chamadas

    chaves = {
        no.value
        for no in ast.walk(arvore)
        if isinstance(no, ast.Constant) and isinstance(no.value, str)
    }
    assert {"reconciliacao", "plausibilidade"} <= chaves

    mostrados = {
        ast.unparse(no)
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr == "error"
    }
    # As duas leituras passaram a sair de variável local em vez de
    # `res[...]` direto, porque cada motor agora atravessa `_motor`, que
    # publica o motivo quando ele não roda. O que esta conferência guarda
    # continua sendo o mesmo: as duas são chamadas e as duas aparecem.
    assert any("reconciliacao.motivo" in texto for texto in mostrados)
    assert any("plausibilidade.motivo" in texto for texto in mostrados)


def test_a_base_sadia_nao_imprime_aviso_de_reconciliacao(tmp_path):
    """Aviso que aparece sempre vira ruído e deixa de ser aviso."""
    teste = _rodar_com(
        "data;canal;produto;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;shopee;Capa;100,00;40,00;10,00\n"
        "02/05/2026;shopee;Fone;200,00;90,00;12,00\n",
        tmp_path,
    )
    assert not teste.exception
    erros = " ".join(e.value for e in teste.error)
    assert "caminhos de cálculo não bateram" not in erros


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
