"""Testes da API FastAPI (casca fina sobre o motor testado)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from carchuna.api.main import app

CLIENTE = TestClient(app)

VENDA_100 = {
    "data": "2026-05-10",
    "canal": "mercado_livre",
    "valor_bruto": "100",
    "custo_produto": "40",
    "frete_pago": "10",
}
CORPO = {
    "transacoes": [VENDA_100],
    "config": {"regime": "simples", "anexo_simples": "I", "rbt12": "360000"},
}


def test_saude():
    resposta = CLIENTE.get("/api/v1/saude")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "ok"
    assert corpo["dispositivos_no_corpus"] >= 20


def test_decompor_devolve_dinheiro_como_string_nunca_float():
    """A venda de R$ 100 conferida à mão, agora via HTTP — e sem float."""
    resposta = CLIENTE.post("/api/v1/margem/decompor", json=CORPO)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["decomposicao"]["margem_liquida"] == "32.35"
    assert corpo["decomposicao"]["aliquota_efetiva"] == "0.056500"
    tributos = next(
        d for d in corpo["decomposicao"]["deducoes"] if d["nome"] == "tributos"
    )
    assert tributos["valor"] == "5.65"  # string: Decimal preservado no JSON
    assert "LC 123/2006" in tributos["fonte"]
    assert corpo["resumo"]["perda_total"] == "27.65"
    assert "dessa perda veio de" in corpo["resumo"]["frase"]


def test_cenarios_incluem_migracao_de_canal():
    resposta = CLIENTE.post("/api/v1/cenarios", json=CORPO)
    assert resposta.status_code == 200
    nomes = [c["nome"] for c in resposta.json()]
    assert any("Migração" in n for n in nomes)
    assert any("Anexo" in n for n in nomes)


def test_diagnostico_com_achado_e_aviso(monkeypatch):
    monkeypatch.setenv("CARCHUNA_USAR_LLM", "0")
    corpo = {
        "transacoes": [VENDA_100],
        "config": {"regime": "simples", "anexo_simples": "III", "rbt12": "360000"},
        "atividade": "comercio",
    }
    resposta = CLIENTE.post("/api/v1/diagnostico", json=corpo)
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["aviso_corpus"]
    (achado,) = dados["achados"]
    assert achado["tipo"] == "tributario"
    # (8,6% − 5,65%) × R$ 100 = R$ 2,95/mês, conferido à mão
    assert achado["impacto_mensal"] == "2.95"
    assert achado["base_legal"], "achado sem base legal não deve existir"
    assert "contador" in achado["aviso"]


def test_busca_legal_na_lingua_do_lojista(monkeypatch):
    monkeypatch.setenv("CARCHUNA_USAR_LLM", "0")
    resposta = CLIENTE.get(
        "/api/v1/legal/buscar", params={"q": "taxa da maquininha cara"}
    )
    assert resposta.status_code == 200
    dados = resposta.json()
    ids = {d["id"] for d in dados["dispositivos"]}
    assert ids & {"lei12865-6", "cmn-4734"}
    assert all(d["revisado"] is False for d in dados["dispositivos"])
    assert "contador" in dados["aviso"]


def test_entrada_invalida_vira_422_com_explicacao():
    corpo = {
        "transacoes": [VENDA_100],
        "config": {"regime": "simples", "anexo_simples": "I", "rbt12": "0"},
    }
    resposta = CLIENTE.post("/api/v1/margem/decompor", json=corpo)
    assert resposta.status_code == 422
    assert "rbt12" in str(resposta.json()["detail"])

    sem_vendas = {"transacoes": [], "config": CORPO["config"]}
    assert CLIENTE.post("/api/v1/margem/decompor", json=sem_vendas).status_code == 422


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
