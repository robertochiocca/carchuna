"""A narrativa opcional some em silêncio — e agora diz por quê.

Quatro coisas diferentes produziam exatamente o mesmo efeito na tela (o
texto extrativo, sem aviso nenhum): pacote não instalado, credencial
ausente, geração desligada por variável, modelo trocado. Quem estava
subindo a Carchuna não tinha como saber em qual dos casos estava, e a
única pista possível era ler o código.

Testa também a fronteira que não pode vazar: `/api/v1/saude` conta se
existe credencial, nunca qual é.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.rag import llm


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    """Cada teste começa sem credencial e com a geração ligada."""
    for chave in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CARCHUNA_MODEL"):
        monkeypatch.delenv(chave, raising=False)
    monkeypatch.setenv("CARCHUNA_USAR_LLM", "1")


# ---------------------------------------------------------------------------
# O modelo padrão
# ---------------------------------------------------------------------------


def test_o_modelo_padrao_e_um_id_publicado_e_nao_um_palpite():
    """O padrão precisa existir de verdade, senão quebra em quem clona.

    A asserção é a forma do id, não o id em si — travar a string exata
    aqui só obrigaria a mexer no teste toda vez que o padrão mudar. O que
    não pode acontecer é o padrão virar vazio ou virar um nome inventado
    com espaço, maiúscula ou versão pontuada.
    """
    padrao = llm.MODELO_PADRAO
    assert padrao and padrao == padrao.strip()
    assert padrao.islower()
    assert " " not in padrao
    assert "." not in padrao  # a API usa hífen: `-4-8`, nunca `4.8`


def test_o_modelo_default_e_carregado_quando_o_ambiente_nao_diz_nada():
    assert llm.modelo_configurado() == llm.MODELO_PADRAO
    assert llm.estado_da_geracao()["modelo"] == llm.MODELO_PADRAO


def test_a_variavel_de_ambiente_ganha_do_default(monkeypatch):
    monkeypatch.setenv("CARCHUNA_MODEL", "outro-modelo-qualquer")
    assert llm.modelo_configurado() == "outro-modelo-qualquer"


def test_variavel_vazia_cai_no_default_em_vez_de_pedir_modelo_vazio(monkeypatch):
    """`CARCHUNA_MODEL=` no .env mandaria `model=""` para a API."""
    monkeypatch.setenv("CARCHUNA_MODEL", "")
    assert llm.modelo_configurado() == llm.MODELO_PADRAO


def test_o_modelo_e_lido_a_cada_chamada_e_nao_congelado_na_importacao(monkeypatch):
    """Dashboard e API são processos longos: trocar a variável tem que valer."""
    monkeypatch.setenv("CARCHUNA_MODEL", "primeiro")
    assert llm.modelo_configurado() == "primeiro"
    monkeypatch.setenv("CARCHUNA_MODEL", "segundo")
    assert llm.modelo_configurado() == "segundo"


# ---------------------------------------------------------------------------
# Chave ausente
# ---------------------------------------------------------------------------


def test_chave_ausente_vira_frase_acionavel_e_nao_silencio(monkeypatch):
    monkeypatch.setattr(llm, "anthropic", object())  # pacote presente
    estado = llm.estado_da_geracao()
    assert estado["credencial_no_ambiente"] is False
    assert "ANTHROPIC_API_KEY" in estado["motivo"]
    # e diz o que acontece enquanto isso, para ninguém achar que quebrou
    assert "extrativo" in estado["motivo"]


def test_chave_presente_nao_gera_aviso(monkeypatch):
    monkeypatch.setattr(llm, "anthropic", object())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste-nao-usada")
    estado = llm.estado_da_geracao()
    assert estado["credencial_no_ambiente"] is True
    assert estado["motivo"] is None


def test_o_token_alternativo_tambem_conta_como_credencial(monkeypatch):
    monkeypatch.setattr(llm, "anthropic", object())
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-de-teste")
    assert llm.estado_da_geracao()["credencial_no_ambiente"] is True


def test_sem_credencial_no_ambiente_a_chamada_ainda_e_tentada(monkeypatch):
    """Perfil gravado em disco é caminho de autenticação legítimo.

    Barrar a chamada por ausência das variáveis recusaria quem autenticou
    assim — e produziria exatamente o sintoma que este item existe para
    acabar: a narrativa some e ninguém sabe por quê.
    """
    tentou = []

    class _Cliente:
        def __init__(self, *a, **k):
            tentou.append(True)
            self.messages = self

        def create(self, **kwargs):
            class _R:
                content = []
                stop_reason = "end_turn"

            return _R()

    monkeypatch.setattr(llm, "anthropic", type("F", (), {"Anthropic": _Cliente}))
    llm.gerar_resposta("qualquer dúvida", [object()])
    assert tentou == [True]


# ---------------------------------------------------------------------------
# Pacote ausente e chave desligada
# ---------------------------------------------------------------------------


def test_pacote_ausente_ensina_como_instalar(monkeypatch):
    monkeypatch.setattr(llm, "anthropic", None)
    estado = llm.estado_da_geracao()
    assert estado["disponivel"] is False
    assert "pip install" in estado["motivo"]


def test_desligada_por_variavel_diz_qual_variavel(monkeypatch):
    monkeypatch.setattr(llm, "anthropic", object())
    monkeypatch.setenv("CARCHUNA_USAR_LLM", "0")
    estado = llm.estado_da_geracao()
    assert estado["disponivel"] is False
    assert "CARCHUNA_USAR_LLM" in estado["motivo"]


# ---------------------------------------------------------------------------
# A fronteira da API
# ---------------------------------------------------------------------------


def test_saude_expoe_geracao_sem_vazar_a_credencial(monkeypatch):
    from fastapi.testclient import TestClient

    from carchuna.api.main import app

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-segredo-que-nao-pode-sair")
    corpo = TestClient(app).get("/api/v1/saude").json()

    assert corpo["status"] == "ok"
    assert corpo["geracao"]["modelo"] == llm.MODELO_PADRAO
    assert corpo["geracao"]["credencial_no_ambiente"] is True
    assert "sk-segredo-que-nao-pode-sair" not in str(corpo)


def test_saude_diz_o_motivo_quando_a_narrativa_nao_vai_sair(monkeypatch):
    from fastapi.testclient import TestClient

    from carchuna.api.main import app

    monkeypatch.setenv("CARCHUNA_USAR_LLM", "0")
    geracao = TestClient(app).get("/api/v1/saude").json()["geracao"]
    assert geracao["disponivel"] is False
    assert geracao["motivo"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
