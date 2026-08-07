"""Testes do motor legal: corpus, retriever BM25, sinônimos e camada LLM."""

import json
import re
import sys
from decimal import Decimal
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


class _APIError(Exception):
    """A base da hierarquia de erros do SDK, no falso."""


class _APIConnectionError(_APIError):
    pass


class _AuthenticationError(_APIError):
    pass


def _instalar_cliente(monkeypatch, resposta=None, erro=None):
    """Põe um `anthropic` falso no lugar do módulo real.

    O falso carrega as classes de erro além do cliente: `gerar_resposta`
    distingue erro previsto do SDK de falha inesperada, e sem elas o
    caminho previsto não teria como ser exercitado.
    """
    import types

    falso = types.SimpleNamespace(
        Anthropic=lambda *a, **k: _ClienteFalso(resposta=resposta, erro=erro),
        APIError=_APIError,
        APIConnectionError=_APIConnectionError,
        AuthenticationError=_AuthenticationError,
    )
    monkeypatch.setattr(llm, "anthropic", falso)
    monkeypatch.setenv("CARCHUNA_USAR_LLM", "1")
    llm._limpar_falha()


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
    """`stop_reason == "refusal"` não vira resposta — e o app cai no extrativo.

    Afirmar só `is None` não valeria o nome do teste: o que importa é que
    o caminho de quem chama (`gerar_resposta(...) or resposta_extrativa(...)`)
    entregue a resposta com os dispositivos e o aviso.
    """
    _instalar_cliente(
        monkeypatch, _Resposta([_BlocoTexto("...")], stop_reason="refusal")
    )
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=2)
    pergunta = "qual o limite do MEI?"
    assert llm.gerar_resposta(pergunta, dispositivos) is None

    entregue = llm.gerar_resposta(pergunta, dispositivos) or llm.resposta_extrativa(
        pergunta, dispositivos
    )
    assert dispositivos[0].lei in entregue
    assert "contador ou advogado" in entregue


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
    """Degradação graciosa: sem rede, sem crédito ou API fora, cai para None.

    O carimbo do erro mudou de `RuntimeError` para a classe do SDK: hoje
    `gerar_resposta` distingue os dois casos, e usar uma exceção genérica
    aqui exercitaria a rede de segurança em vez do caminho previsto.
    """
    _instalar_cliente(monkeypatch, erro=_APIConnectionError("connection refused"))
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=2)
    assert llm.gerar_resposta("qual o limite do MEI?", dispositivos) is None


def test_desligar_o_llm_por_variavel_de_ambiente(monkeypatch):
    """`CARCHUNA_USAR_LLM=0` desliga a geração mesmo com cliente disponível."""
    _instalar_cliente(monkeypatch, _Resposta([_BlocoTexto("não deveria aparecer")]))
    monkeypatch.setenv("CARCHUNA_USAR_LLM", "0")
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=2)
    assert llm.gerar_resposta("qual o limite do MEI?", dispositivos) is None


def test_o_numero_e_o_mesmo_com_llm_e_sem_llm(monkeypatch):
    """A regra da casa, testada pelo comportamento: **a IA nunca calcula**.

    O LLM falso devolve um texto recheado de números errados. Se algum
    caminho de código deixasse o modelo influenciar dinheiro, a
    decomposição mudaria. Ela não muda — centavo a centavo, com e sem.
    """
    from datetime import date

    from carchuna.analise import AnalisadorMargem
    from carchuna.margem import ConfigTributaria, Transacao

    vendas = [
        Transacao(
            data=date(2026, 5, dia),
            canal="shopee",
            valor_bruto=Decimal(valor),
            custo_produto=Decimal("40.00"),
            frete_pago=Decimal("10.00"),
        )
        for dia, valor in enumerate(["100.00", "200.00", "300.00"], 1)
    ]
    config = ConfigTributaria(
        regime="simples", anexo_simples="I", rbt12=Decimal("360000")
    )

    def _numeros() -> tuple:
        d = AnalisadorMargem(list(vendas), config).decomposicao
        return (
            d.receita_bruta,
            d.margem_liquida,
            d.margem_pct,
            d.aliquota_efetiva,
            tuple((x.nome, x.valor) for x in d.deducoes),
        )

    sem_llm = _numeros()

    _instalar_cliente(
        monkeypatch,
        _Resposta(
            [
                _BlocoTexto(
                    "Sua margem líquida é de R$ 999.999,99 e a alíquota "
                    "efetiva é 0,01%. Você tem direito a R$ 50.000 de volta."
                )
            ]
        ),
    )
    com_llm = _numeros()

    assert com_llm == sem_llm
    # e o número de verdade continua sendo o do motor: 100+200+300
    assert sem_llm[0] == Decimal("600.00")


def test_o_llm_nunca_recebe_a_decomposicao_para_recalcular(monkeypatch):
    """O contexto que vai ao modelo é texto de lei, não a conta.

    Se a decomposição fosse enviada, o modelo poderia "corrigir" o
    número na narrativa — e a narrativa é o que o lojista lê.
    """
    _instalar_cliente(monkeypatch, _Resposta([_BlocoTexto("ok")]))
    dispositivos = RETRIEVER.buscar("comissão do marketplace", top_k=3)
    llm.gerar_resposta("por que sobra tão pouco?", dispositivos)

    enviado = _ClienteFalso.ultima_chamada
    conteudo = enviado["messages"][0]["content"]
    for disp in dispositivos:
        assert disp.texto in conteudo
    assert "margem_liquida" not in conteudo
    assert "receita_bruta" not in conteudo
    assert "Não invente lei, número, alíquota" in enviado["system"][0]["text"]


# ---------------------------------------------------------------------------
# O valor que a narrativa cita tem que existir fora dela
# ---------------------------------------------------------------------------

# "R$ 1.234,56", "R$ 81.000,00", "R$ 999.999,99"
_MOEDA = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})?")


def _valores_citados(texto: str) -> set[str]:
    """Todo valor em reais que aparece no texto, normalizado."""
    return {m.replace("R$", "").replace(" ", "").strip() for m in _MOEDA.findall(texto)}


def _valores_com_lastro(decomposicao, dispositivos) -> set[str]:
    """Os únicos valores que a narrativa pode citar.

    Ou o motor calculou, ou está escrito na lei recuperada. Nada mais.
    """
    do_motor = [decomposicao.receita_bruta, decomposicao.margem_liquida]
    do_motor += [d.valor for d in decomposicao.deducoes]
    lastro = {
        f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        for v in do_motor
    }
    for disp in dispositivos:
        lastro |= _valores_citados(f"{disp.texto} {disp.resumo}")
    return lastro


def _sem_lastro(narrativa: str, decomposicao, dispositivos) -> set[str]:
    """Valores citados na narrativa que não existem em lugar nenhum."""
    return _valores_citados(narrativa) - _valores_com_lastro(decomposicao, dispositivos)


def _decomposicao_de_exemplo():
    from datetime import date

    from carchuna.margem import (
        ConfigTributaria,
        Transacao,
        decompor_margem,
    )

    vendas = [
        Transacao(
            data=date(2026, 5, 1),
            canal="shopee",
            valor_bruto=Decimal("1000.00"),
            custo_produto=Decimal("400.00"),
            frete_pago=Decimal("50.00"),
        )
    ]
    return decompor_margem(
        vendas,
        ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000")),
    )


def test_a_narrativa_do_llm_nao_pode_citar_valor_que_ninguem_calculou(monkeypatch):
    """O teste que faltava: pega o dia em que alguém religar os dois lados.

    Se um caminho de código passar a mandar a decomposição ao modelo, ele
    vai produzir valores monetários na narrativa — e narrativa é o que o
    lojista lê. A regra: todo valor citado tem que estar OU no que o
    motor calculou, OU no texto da lei recuperada. O resto é invenção.
    """
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=3)
    decomposicao = _decomposicao_de_exemplo()

    _instalar_cliente(
        monkeypatch,
        _Resposta(
            [
                _BlocoTexto(
                    "Em regra, a sua situação se relaciona ao art. 18 da "
                    "LC 123/2006. Confirme com seu contador ou advogado "
                    "antes de agir."
                )
            ]
        ),
    )
    narrativa = llm.gerar_resposta("posso continuar no MEI?", dispositivos)
    assert _sem_lastro(narrativa, decomposicao, dispositivos) == set()


def test_o_detector_acusa_quando_o_modelo_inventa_um_valor(monkeypatch):
    """A régua acima só vale se souber acusar — aqui ela acusa.

    Sem este teste, o anterior passaria para sempre só porque a narrativa
    de hoje não tem número nenhum.
    """
    dispositivos = RETRIEVER.buscar("limite do MEI", top_k=3)
    decomposicao = _decomposicao_de_exemplo()

    _instalar_cliente(
        monkeypatch,
        _Resposta(
            [
                _BlocoTexto(
                    "Sua margem líquida foi de R$ 999.999,99 e você tem "
                    "direito a R$ 50.000,00 de volta."
                )
            ]
        ),
    )
    narrativa = llm.gerar_resposta("por que sobra tão pouco?", dispositivos)
    assert _sem_lastro(narrativa, decomposicao, dispositivos) == {
        "999.999,99",
        "50.000,00",
    }


def test_valor_que_o_motor_calculou_passa_pela_regua(monkeypatch):
    """Narrar o número certo é o trabalho do LLM — isso não pode acusar.

    A venda de R$ 1.000,00 com CMV de R$ 400,00: os dois são do motor e
    a régua tem que deixar passar.
    """
    dispositivos = RETRIEVER.buscar("comissão do marketplace", top_k=2)
    decomposicao = _decomposicao_de_exemplo()

    _instalar_cliente(
        monkeypatch,
        _Resposta(
            [
                _BlocoTexto(
                    "Das suas vendas de R$ 1.000,00, R$ 400,00 foram para o "
                    "custo do produto."
                )
            ]
        ),
    )
    narrativa = llm.gerar_resposta("para onde foi o dinheiro?", dispositivos)
    assert _sem_lastro(narrativa, decomposicao, dispositivos) == set()
