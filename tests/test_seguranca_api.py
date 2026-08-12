"""A fronteira HTTP, vista de fora — corpo hostil, sem autenticação.

A API é stateless e pública. Não há usuário para escalar privilégio nem
banco para injetar; o que resta é o corpo da requisição, e é ele que
este arquivo ataca.

**V1 na porta HTTP.** Antes da correção, ``"valor_bruto":"1e999"``
respondia **HTTP 500**: `decimal.InvalidOperation` subia por fora do
`except (ValueError, TypeError)` do `_analisador`. Um 500 num serviço
sem auth é indisponibilidade a custo zero para quem chama.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from carchuna.api.main import app
from carchuna.api.schemas import (
    MAX_PERGUNTA,
    MAX_TRANSACOES_POR_CHAMADA,
)
from carchuna.margem import MAX_PRAZO_RECEBIMENTO_DIAS

# `raise_server_exceptions=False` faz o cliente devolver o 500 em vez de
# relançar a exceção: é assim que o servidor de verdade se comporta, e é
# o 500 que estes testes precisam ver.
CLIENTE = TestClient(app, raise_server_exceptions=False)

CONFIG = {"regime": "simples", "anexo_simples": "I", "rbt12": "360000"}
VENDA = {
    "data": "2026-05-10",
    "canal": "shopee",
    "valor_bruto": "100",
    "custo_produto": "40",
    "frete_pago": "10",
}

ANALITICOS = (
    "/api/v1/margem/decompor",
    "/api/v1/cenarios",
    "/api/v1/diagnostico",
    "/api/v1/crescimento",
)


def _post(rota, **campos):
    corpo = {"transacoes": [VENDA], "config": CONFIG}
    corpo.update(campos)
    return CLIENTE.post(rota, json=corpo)


# ---------------------------------------------------------------------------
# V1 — número absurdo não pode virar 500
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rota", ANALITICOS)
def test_valor_absurdo_devolve_422_e_nao_500(rota):
    """500 é a aplicação caindo; 422 é a aplicação recusando.

    A diferença importa para quem opera: um 500 sem auth é
    indisponibilidade a custo zero para o atacante, e some no log como
    "erro interno" sem dizer que veio de fora.
    """
    resposta = _post(rota, transacoes=[{**VENDA, "valor_bruto": "1e999"}])
    assert resposta.status_code == 422


@pytest.mark.parametrize(
    "campo", ["valor_bruto", "custo_produto", "frete_pago", "comissao_cobrada"]
)
def test_todos_os_campos_de_dinheiro_recusam_o_absurdo(campo):
    resposta = _post("/api/v1/margem/decompor", transacoes=[{**VENDA, campo: "1e999"}])
    assert resposta.status_code == 422


def test_taxa_absurda_na_tabela_tambem_e_422():
    resposta = _post(
        "/api/v1/margem/decompor",
        tabela={"taxa_adquirencia": "1e999"},
    )
    assert resposta.status_code == 422


def test_prazo_gigante_para_na_fronteira_antes_do_motor():
    """Pydantic recusa pelo `le`, sem construir uma `Transacao`."""
    resposta = _post(
        "/api/v1/margem/decompor",
        transacoes=[{**VENDA, "prazo_recebimento_dias": 10**30}],
    )
    assert resposta.status_code == 422
    assert "prazo_recebimento_dias" in str(resposta.json())


def test_o_prazo_no_teto_continua_aceito():
    resposta = _post(
        "/api/v1/margem/decompor",
        transacoes=[{**VENDA, "prazo_recebimento_dias": MAX_PRAZO_RECEBIMENTO_DIAS}],
    )
    assert resposta.status_code == 200


# ---------------------------------------------------------------------------
# Tetos de payload
# ---------------------------------------------------------------------------


def test_lista_acima_do_teto_e_recusada_sem_calcular():
    """422 pela validação, não 200 depois de queimar CPU."""
    resposta = _post(
        "/api/v1/margem/decompor", transacoes=[VENDA] * (MAX_TRANSACOES_POR_CHAMADA + 1)
    )
    assert resposta.status_code == 422
    assert "too_long" in str(resposta.json())


def test_pergunta_acima_do_teto_e_recusada():
    resposta = CLIENTE.get(
        "/api/v1/legal/buscar", params={"q": "a" * (MAX_PERGUNTA + 1)}
    )
    assert resposta.status_code == 422


def test_texto_livre_da_transacao_tem_teto():
    resposta = _post(
        "/api/v1/margem/decompor", transacoes=[{**VENDA, "produto": "x" * 201}]
    )
    assert resposta.status_code == 422


# ---------------------------------------------------------------------------
# Corpo malformado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "corpo",
    [
        {"transacoes": [], "config": CONFIG},
        {"transacoes": [VENDA]},
        {"transacoes": "não é lista", "config": CONFIG},
        {"transacoes": [{"data": "não é data"}], "config": CONFIG},
        {"transacoes": [VENDA], "config": {"regime": "inexistente"}},
        {"transacoes": [{**VENDA, "canal": "canal_que_nao_existe"}], "config": CONFIG},
    ],
)
def test_corpo_malformado_e_422_nunca_500(corpo):
    resposta = CLIENTE.post("/api/v1/margem/decompor", json=corpo)
    assert resposta.status_code == 422


def test_json_quebrado_nao_derruba_o_processo():
    resposta = CLIENTE.post(
        "/api/v1/margem/decompor",
        content=b'{"transacoes": [',
        headers={"content-type": "application/json"},
    )
    assert resposta.status_code == 422


# ---------------------------------------------------------------------------
# Limite de chamadas
# ---------------------------------------------------------------------------


def test_busca_legal_acima_do_limite_e_429_com_retry_after():
    """O único endpoint que pode virar chamada paga por requisição."""
    from carchuna.api.limite import LIMITE_POR_JANELA
    from carchuna.api.main import _limite

    _limite._marcas.clear()
    ultima = None
    for _ in range(LIMITE_POR_JANELA + 1):
        ultima = CLIENTE.get("/api/v1/legal/buscar", params={"q": "simples nacional"})

    assert ultima.status_code == 429
    assert "Retry-After" in ultima.headers
    assert int(ultima.headers["Retry-After"]) >= 1
    _limite._marcas.clear()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
