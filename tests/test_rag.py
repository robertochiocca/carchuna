"""Testes do motor legal: corpus, retriever BM25, sinônimos e camada LLM."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.rag import llm
from carchuna.rag.retrieval import DATA_PATH, Retriever
from carchuna.rag.sinonimos import SINONIMOS_LOJISTA

RETRIEVER = Retriever()


# ---------------------------------------------------------------------------
# Corpus — formato e honestidade
# ---------------------------------------------------------------------------


def test_corpus_tem_o_formato_do_direitoaberto_e_20_dispositivos():
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert raw["aviso"], "corpus precisa do aviso de revisão"
    dispositivos = raw["dispositivos"]
    assert len(dispositivos) >= 20
    obrigatorios = {
        "id",
        "lei",
        "artigo",
        "tema",
        "texto",
        "resumo",
        "palavras_chave",
        "fonte",
        "revisado",
    }
    ids = set()
    for disp in dispositivos:
        assert obrigatorios <= set(disp), f"{disp.get('id')} com campos faltando"
        assert disp["fonte"].startswith("https://"), disp["id"]
        assert disp["id"] not in ids, f"id duplicado: {disp['id']}"
        ids.add(disp["id"])


def test_ingestao_sai_com_revisado_false_ate_revisao_humana():
    """Padrão da trilogia: nada entra como revisado sem revisão humana."""
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert all(d["revisado"] is False for d in raw["dispositivos"])
    # e o Retriever propaga o status para quem exibe
    resultado = RETRIEVER.buscar("simples nacional alíquota")
    assert all(r.revisado is False for r in resultado)


def test_temas_do_corpus_sao_os_do_diagnostico():
    assert set(RETRIEVER.temas()) <= {
        "tributario",
        "contratual",
        "financeiro",
        "operacional",
        "consumidor",
    }


# ---------------------------------------------------------------------------
# Retriever — a língua do lojista encontra a lei
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pergunta", "ids_esperados"),
    [
        # "maquininha" não aparece no texto legal — só via sinônimos
        ("a taxa da maquininha tá muito cara", {"lei12865-6", "cmn-4734"}),
        ("quero antecipar meus recebíveis mais barato", {"cmn-4734"}),
        ("cliente devolveu o produto comprado na internet", {"cdc-49", "d7962"}),
        ("qual o limite do MEI", {"lc123-18a"}),
        ("como funciona a alíquota do simples", {"lc123-18", "lc123-anexo1"}),
        ("paguei imposto a mais, dá pra recuperar?", {"ctn-165", "ctn-168"}),
        ("vou estourar o teto e sair do simples", {"lc123-30", "lc123-3"}),
    ],
)
def test_perguntas_do_lojista_recuperam_o_dispositivo_certo(pergunta, ids_esperados):
    ids = {r.id for r in RETRIEVER.buscar(pergunta)}
    assert ids & ids_esperados, f"{pergunta!r} → {ids}"


def test_filtro_por_tema_e_score_minimo():
    so_tributario = RETRIEVER.buscar("imposto simples", tema="tributario")
    assert so_tributario and all(r.tema == "tributario" for r in so_tributario)
    assert RETRIEVER.buscar("zzz xyzw qqqq") == []


def test_resultados_ordenados_por_score_com_top_k():
    resultados = RETRIEVER.buscar("simples nacional", top_k=3)
    assert len(resultados) <= 3
    scores = [r.score for r in resultados]
    assert scores == sorted(scores, reverse=True)


def test_sinonimos_do_lojista_sao_a_diferenca():
    """Sem o dicionário, 'maquininha' não acharia nada: prova do valor dele."""
    assert "maquininha" in SINONIMOS_LOJISTA
    assert "adquirência" in SINONIMOS_LOJISTA["maquininha"]
    for chave, alvos in SINONIMOS_LOJISTA.items():
        assert alvos, f"sinônimo {chave!r} sem alvos"


# ---------------------------------------------------------------------------
# Camada LLM — degradação graciosa sem chave
# ---------------------------------------------------------------------------


def test_gerar_resposta_sem_credencial_devolve_none(monkeypatch):
    monkeypatch.setenv("CARCHUNA_USAR_LLM", "0")
    dispositivos = RETRIEVER.buscar("limite do mei")
    assert llm.gerar_resposta("qual o limite do MEI?", dispositivos) is None
    assert llm.gerar_resposta("qualquer coisa", []) is None


def test_resposta_extrativa_cita_dispositivos_e_aviso():
    dispositivos = RETRIEVER.buscar("limite do mei")
    resposta = llm.resposta_extrativa("qual o limite do MEI?", dispositivos)
    assert "18-A" in resposta
    assert "revisão humana pendente" in resposta
    assert "contador ou advogado" in resposta


def test_resposta_extrativa_sem_resultados_orienta_sem_inventar():
    resposta = llm.resposta_extrativa("pergunta sem relação", [])
    assert "Não encontrei" in resposta
    assert "contador" in resposta


def test_prompt_do_sistema_mantem_o_dna_da_trilogia():
    assert "EXCLUSIVAMENTE" in llm.SYSTEM_PROMPT
    assert "Não invente" in llm.SYSTEM_PROMPT
    assert "contador ou advogado" in llm.SYSTEM_PROMPT
    # anti-escopo: nunca prometer recuperação de valores
    assert "recuperação tributária" in llm.SYSTEM_PROMPT


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------------
# O caminho do LLM, sem chave de API nenhuma
# ---------------------------------------------------------------------------


class _BlocoTexto:
    """Imita um bloco de conteúdo da resposta da API da Anthropic."""

    def __init__(self, texto: str, tipo: str = "text"):
        self.text = texto
        self.type = tipo


class _Resposta:
    def __init__(self, blocos, stop_reason="end_turn"):
        self.content = blocos
        self.stop_reason = stop_reason


class _ClienteFalso:
    """Cliente que devolve o que o teste mandar — e guarda o que recebeu."""

    ultima_chamada: dict = {}

    def __init__(self, resposta=None, erro=None):
        self._resposta = resposta
        self._erro = erro
        self.messages = self

    def create(self, **kwargs):
        type(self).ultima_chamada = kwargs
        if self._erro:
            raise self._erro
        return self._resposta


def _instalar_cliente(monkeypatch, resposta=None, erro=None):
    """Põe um `anthropic` falso no lugar do módulo real."""
    import types

    falso = types.SimpleNamespace(
        Anthropic=lambda *a, **k: _ClienteFalso(resposta=resposta, erro=erro)
    )
    monkeypatch.setattr(llm, "anthropic", falso)
    monkeypatch.setenv("CARCHUNA_USAR_LLM", "1")


def test_gerar_resposta_devolve_o_texto_do_modelo(monkeypatch):
    """Caminho feliz do LLM, exercitado sem chave e sem rede."""
    _instalar_cliente(monkeypatch, _Resposta([_BlocoTexto("  Em regra, sim.  ")]))
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=2)
    assert llm.gerar_resposta("qual o limite do MEI?", dispositivos) == "Em regra, sim."


def test_o_prompt_leva_os_dispositivos_recuperados(monkeypatch):
    """A IA só pode falar do que o Retriever achou — é o contrato do RAG."""
    _instalar_cliente(monkeypatch, _Resposta([_BlocoTexto("ok")]))
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=2)
    llm.gerar_resposta("qual o limite do MEI?", dispositivos)

    enviado = _ClienteFalso.ultima_chamada
    conteudo = enviado["messages"][0]["content"]
    for disp in dispositivos:
        assert disp.lei in conteudo
        assert disp.fonte in conteudo
    assert "qual o limite do MEI?" in conteudo
    # o system prompt vai com cache_control, e é o da casa
    assert enviado["system"][0]["text"] == llm.SYSTEM_PROMPT


def test_recusa_do_modelo_cai_no_modo_extrativo(monkeypatch):
    """`stop_reason == "refusal"` não vira resposta — vira None."""
    _instalar_cliente(
        monkeypatch, _Resposta([_BlocoTexto("...")], stop_reason="refusal")
    )
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=2)
    assert llm.gerar_resposta("qual o limite do MEI?", dispositivos) is None


def test_resposta_vazia_do_modelo_cai_no_modo_extrativo(monkeypatch):
    """Texto em branco é o mesmo que não ter resposta."""
    _instalar_cliente(monkeypatch, _Resposta([_BlocoTexto("   ")]))
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=2)
    assert llm.gerar_resposta("qual o limite do MEI?", dispositivos) is None


def test_bloco_que_nao_e_texto_e_ignorado(monkeypatch):
    """Só blocos `type == "text"` entram na resposta."""
    _instalar_cliente(
        monkeypatch,
        _Resposta([_BlocoTexto("ignore", tipo="thinking"), _BlocoTexto("vale")]),
    )
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=2)
    assert llm.gerar_resposta("qual o limite do MEI?", dispositivos) == "vale"


def test_erro_da_api_nao_derruba_o_app(monkeypatch):
    """Degradação graciosa: sem rede, sem crédito ou API fora, cai para None."""
    _instalar_cliente(monkeypatch, erro=RuntimeError("connection refused"))
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=2)
    assert llm.gerar_resposta("qual o limite do MEI?", dispositivos) is None


def test_desligar_o_llm_por_variavel_de_ambiente(monkeypatch):
    """`CARCHUNA_USAR_LLM=0` desliga a geração mesmo com cliente disponível."""
    _instalar_cliente(monkeypatch, _Resposta([_BlocoTexto("não deveria aparecer")]))
    monkeypatch.setenv("CARCHUNA_USAR_LLM", "0")
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=2)
    assert llm.gerar_resposta("qual o limite do MEI?", dispositivos) is None


def test_nenhum_valor_monetario_sai_do_llm(monkeypatch):
    """A IA nunca calcula: o prompt não manda o modelo produzir número.

    O contexto enviado carrega texto de lei, não a decomposição da
    margem — o número já saiu do motor antes de o LLM ser chamado.
    """
    _instalar_cliente(monkeypatch, _Resposta([_BlocoTexto("ok")]))
    dispositivos = RETRIEVER.buscar("comissão do marketplace", top_k=3)
    llm.gerar_resposta("por que sobra tão pouco?", dispositivos)

    enviado = _ClienteFalso.ultima_chamada
    assert "calcule" not in enviado["system"][0]["text"].lower()
    assert "Não invente lei, número, alíquota" in enviado["system"][0]["text"]
