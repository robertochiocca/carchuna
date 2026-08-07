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
    """A FORMA do id, separada do id em si (que o teste seguinte trava).

    Separar os dois faz o teste que falha dizer qual é o problema: aqui,
    que o padrão virou vazio ou ganhou espaço, maiúscula ou versão
    pontuada — coisas que nenhum id de modelo tem; ali, que o padrão
    mudou de valor.
    """
    padrao = llm.MODELO_PADRAO
    assert padrao and padrao == padrao.strip()
    assert padrao.islower()
    assert " " not in padrao
    assert "." not in padrao  # a API usa hífen: `-4-8`, nunca `4.8`


def test_o_modelo_default_e_carregado_quando_o_ambiente_nao_diz_nada():
    """O id em cheio, e não `== MODELO_PADRAO`, que passaria com qualquer coisa.

    Travar a string faz o teste ter de ser mexido quando o padrão mudar —
    e é exatamente esse o ponto: trocar o modelo que a Carchuna usa por
    omissão é decisão de produto, não detalhe que deva passar despercebido
    num diff.
    """
    assert llm.MODELO_PADRAO == "claude-sonnet-5"
    assert llm.modelo_configurado() == "claude-sonnet-5"
    assert llm.estado_da_geracao()["modelo"] == "claude-sonnet-5"


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
# Falha na chamada: nem derruba o app, nem vira silêncio
# ---------------------------------------------------------------------------


class _ErroDoSDK(Exception):
    """Base da hierarquia de erros no `anthropic` falso."""


class AuthenticationError(_ErroDoSDK):
    """O nome da classe é o que o motor casa com a frase — sem prefixo."""


class _Dispositivo:
    """O mínimo que `_montar_contexto` lê de um dispositivo do corpus."""

    lei = "LC 123/2006"
    artigo = "art. 18-A"
    texto = "texto do dispositivo"
    fonte = "https://www.planalto.gov.br/"


def _instalar(monkeypatch, erro):
    """Instala um `anthropic` falso cujo cliente estoura `erro`."""
    import types

    class _Cliente:
        def __init__(self, *a, **k):
            self.messages = self

        def create(self, **kwargs):
            raise erro

    monkeypatch.setattr(
        llm,
        "anthropic",
        types.SimpleNamespace(Anthropic=_Cliente, APIError=_ErroDoSDK),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    llm._limpar_falha()


def test_erro_conhecido_do_sdk_vira_frase_acionavel(monkeypatch):
    """Credencial recusada não pode sair igual a "não configurei nada"."""
    _instalar(monkeypatch, AuthenticationError("401"))
    assert llm.gerar_resposta("dúvida", [_Dispositivo()]) is None

    estado = llm.estado_da_geracao()
    assert "recusada" in estado["motivo"]
    assert "ANTHROPIC_API_KEY" in estado["motivo"]


def test_excecao_inesperada_nao_derruba_o_app_mas_fica_registrada(monkeypatch):
    """A rede de segurança: o app segue de pé e o erro ganha nome.

    Este é o teste que impede o `except Exception` de voltar a ser o que
    era. Uma exceção fora da hierarquia do SDK — assinatura que mudou,
    dependência quebrada — continua não derrubando o diagnóstico, que
    nunca dependeu da narrativa; mas para de sumir.
    """

    class _AlgoInesperado(RuntimeError):
        pass

    _instalar(monkeypatch, _AlgoInesperado("isto não deveria acontecer"))
    assert llm.gerar_resposta("dúvida", [_Dispositivo()]) is None

    falha = llm.ultima_falha()
    assert falha is not None
    assert "_AlgoInesperado" in falha  # a CLASSE, para dar o que investigar
    assert "inesperada" in falha
    assert llm.estado_da_geracao()["motivo"] == falha


def test_a_falha_registrada_nao_carrega_a_mensagem_crua_do_erro(monkeypatch):
    """Mensagem de terceiro pode trazer credencial, URL interna ou payload."""
    _instalar(monkeypatch, _ErroDoSDK("x-api-key: sk-vazou-aqui em https://interno"))
    llm.gerar_resposta("dúvida", [_Dispositivo()])

    falha = llm.ultima_falha()
    assert "sk-vazou-aqui" not in falha
    assert "interno" not in falha


def test_uma_chamada_bem_sucedida_limpa_a_falha_anterior(monkeypatch):
    """Erro de rede que passou não pode ficar avisando para sempre."""
    import types

    _instalar(monkeypatch, _ErroDoSDK("timeout"))
    llm.gerar_resposta("dúvida", [_Dispositivo()])
    assert llm.ultima_falha() is not None

    class _Bloco:
        type = "text"
        text = "resposta boa"

    class _Cliente:
        def __init__(self, *a, **k):
            self.messages = self

        def create(self, **kwargs):
            return types.SimpleNamespace(content=[_Bloco()], stop_reason="end_turn")

    monkeypatch.setattr(
        llm,
        "anthropic",
        types.SimpleNamespace(Anthropic=_Cliente, APIError=_ErroDoSDK),
    )
    assert llm.gerar_resposta("dúvida", [_Dispositivo()]) == "resposta boa"
    assert llm.ultima_falha() is None


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
