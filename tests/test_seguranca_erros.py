"""Mensagem de erro é útil para o lojista e muda para o atacante.

A Carchuna explica muito, de propósito: qual coluna faltou, em que linha,
o que fazer. Isso é funcionalidade, e nenhuma correção de segurança pode
apagá-la — um erro que só diz "erro" empurra o lojista para o suporte e
não protege ninguém.

O que não pode sair é o que **não foi escrito para ninguém ler**: a
mensagem do sistema operacional, com errno e caminho absoluto; o stack;
o nome do módulo interno; o nome de uma variável de ambiente de
credencial.

A distinção que este arquivo prende é essa. `ValueError` do motor é
texto curado — sai inteiro. `OSError` é texto do sistema operacional —
não sai.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("streamlit")
import streamlit as st
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from carchuna.api.main import app
from carchuna.dados import CHAVE_LEITURA_POR_CAMINHO

CLIENTE = TestClient(app, raise_server_exceptions=False)
APP = str(Path(__file__).resolve().parents[1] / "app.py")

CONFIG = {"regime": "simples", "anexo_simples": "I", "rbt12": "360000"}
VENDA = {
    "data": "2026-05-10",
    "canal": "shopee",
    "valor_bruto": "100",
    "custo_produto": "40",
    "frete_pago": "10",
}

# O que nunca pode aparecer numa resposta ou numa tela.
VAZAMENTOS = (
    "Traceback",
    'File "',
    ".py",
    "carchuna/",
    "site-packages",
    "/home/",
    "/usr/",
    "Errno",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
)


def _sem_vazamento(texto: str) -> None:
    for marca in VAZAMENTOS:
        assert marca not in texto, f"vazou {marca!r} em: {texto[:200]}"


@pytest.fixture(autouse=True)
def _limites_zerados():
    from carchuna.api.main import _limite, _limite_calculo

    _limite._marcas.clear()
    _limite_calculo._marcas.clear()
    st.cache_data.clear()
    yield
    _limite._marcas.clear()
    _limite_calculo._marcas.clear()
    st.cache_data.clear()


# ---------------------------------------------------------------------------
# A API
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "corpo",
    [
        {"transacoes": [{**VENDA, "valor_bruto": "1e999"}], "config": CONFIG},
        {"transacoes": [VENDA], "config": {"regime": "mei"}},
        {"transacoes": [VENDA], "config": {"regime": "simples", "rbt12": "0"}},
        {
            "transacoes": [VENDA],
            "config": CONFIG,
            "tabela": {"taxa_adquirencia": "1e999"},
        },
        {"transacoes": [{**VENDA, "canal": "inexistente"}], "config": CONFIG},
        {"transacoes": "nem lista é", "config": CONFIG},
    ],
)
def test_nenhuma_resposta_de_erro_carrega_interno(corpo):
    resposta = CLIENTE.post("/api/v1/margem/decompor", json=corpo)
    assert resposta.status_code in (200, 422)
    _sem_vazamento(resposta.text)


def test_o_erro_do_motor_continua_dizendo_o_que_fazer():
    """Podar demais é o outro jeito de errar.

    A mensagem tem de continuar apontando o campo e o caminho — é ela que
    resolve o problema do lojista sem ele abrir um chamado.
    """
    resposta = CLIENTE.post(
        "/api/v1/margem/decompor",
        json={"transacoes": [{**VENDA, "valor_bruto": "1e999"}], "config": CONFIG},
    )
    detalhe = resposta.json()["detail"]

    assert "valor_bruto" in detalhe
    assert "notação científica" in detalhe
    _sem_vazamento(detalhe)


def test_a_saude_nao_revela_credencial_nem_ambiente():
    """`/saude` diz por que a narrativa não sai — sem dizer o segredo."""
    corpo = CLIENTE.get("/api/v1/saude").json()
    texto = str(corpo)

    assert corpo["status"] == "ok"
    assert "sk-ant" not in texto
    for marca in ("Traceback", "site-packages", "/home/", "/usr/"):
        assert marca not in texto


def test_o_429_nao_revela_o_estado_interno_do_limitador():
    from carchuna.api.limite import LIMITE_CALCULO_POR_JANELA

    ultima = None
    for _ in range(LIMITE_CALCULO_POR_JANELA + 1):
        ultima = CLIENTE.post(
            "/api/v1/cenarios", json={"transacoes": [VENDA], "config": CONFIG}
        )
    assert ultima.status_code == 429
    _sem_vazamento(ultima.text)
    assert "_marcas" not in ultima.text


# ---------------------------------------------------------------------------
# A tela
# ---------------------------------------------------------------------------


def test_caminho_inexistente_nao_devolve_errno_nem_o_caminho(monkeypatch, tmp_path):
    """Antes: `[Errno 2] No such file or directory: '<caminho>'` na tela.

    Três respostas distinguíveis — não existe, sem permissão, existe e
    não parseia — desenham um oráculo de arquivos do servidor. Agora as
    falhas de sistema de arquivos dão a mesma mensagem.
    """
    monkeypatch.setenv(CHAVE_LEITURA_POR_CAMINHO, "1")
    teste = AppTest.from_file(APP, default_timeout=120).run()
    teste.text_input("caminho_arquivo").set_value(str(tmp_path / "nao_existe.csv"))
    teste.run()

    erros = " ".join(e.value for e in teste.error)
    assert "Não consegui abrir esse arquivo" in erros
    _sem_vazamento(erros)


def test_um_diretorio_no_lugar_de_arquivo_da_a_mesma_mensagem(monkeypatch, tmp_path):
    """Mensagem igual para causas diferentes — é isso que fecha o oráculo."""
    monkeypatch.setenv(CHAVE_LEITURA_POR_CAMINHO, "1")
    pasta = tmp_path / "uma_pasta.csv"
    pasta.mkdir()

    teste = AppTest.from_file(APP, default_timeout=120).run()
    teste.text_input("caminho_arquivo").set_value(str(pasta))
    teste.run()

    erros = " ".join(e.value for e in teste.error)
    assert "Não consegui abrir esse arquivo" in erros
    _sem_vazamento(erros)


def test_o_arquivo_ruim_continua_explicando_o_que_esta_errado(monkeypatch, tmp_path):
    """Fechar o oráculo não pode calar o diagnóstico do arquivo de verdade."""
    monkeypatch.setenv(CHAVE_LEITURA_POR_CAMINHO, "1")
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        "data;canal;valor_bruto\n2026-01-01;shopee;100\n", encoding="utf-8"
    )

    teste = AppTest.from_file(APP, default_timeout=120).run()
    teste.text_input("caminho_arquivo").set_value(str(arquivo))
    teste.run()

    erros = " ".join(e.value for e in teste.error)
    assert "custo_produto" in erros  # diz QUAL coluna faltou
    _sem_vazamento(erros)


def test_a_base_de_demonstracao_nao_imprime_erro_nenhum():
    teste = AppTest.from_file(APP, default_timeout=120).run()
    assert not teste.exception
    _sem_vazamento(" ".join(e.value for e in teste.error))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
