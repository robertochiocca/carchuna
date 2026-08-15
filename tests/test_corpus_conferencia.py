"""`revisado: true` sozinho não afirma nada, e o corpus agora sabe disso.

O campo `revisado` era um booleano solto. Marcá-lo não dizia **quem**
conferiu nem **quando** — e as duas coisas importam, porque o que se
confere no corpus da Carchuna não é a transcrição do texto legal: é o
**resumo** (que é interpretação nossa) e a **vigência** do dispositivo
naquela data. As duas envelhecem. Sem data, não há como saber se
envelheceram.

Pior: um `revisado: true` marcado em lote num arquivo de 21 itens é
indistinguível de um conferido dispositivo a dispositivo por um
advogado. A tela publica os dois com a mesma cara, e o diferencial que o
README vende — "nenhuma afirmação sem lastro" — vira um selo que
ninguém assinou.

O esquema passou a ter três campos que descrevem um estado só, e a carga
do corpus recusa qualquer combinação incoerente. Este arquivo fixa a
regra nos dois sentidos: `true` sem data é recusado, e data sem `true`
também.

**Nenhum dispositivo foi conferido**, e o teste que afirma isso está
aqui de propósito: no dia em que o primeiro for, ele quebra e obriga a
atualizar o README e o ROADMAP junto — que é exatamente o acoplamento
que se quer.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.rag.ingestao import _e_esqueleto_intocado, mesclar_no_corpus
from carchuna.rag.retrieval import Retriever, conferir_integridade_do_corpus

CORPUS = Path(__file__).resolve().parents[1] / "data" / "corpus_pme.json"


def _corpus() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# O esquema
# ---------------------------------------------------------------------------


def test_todo_dispositivo_tem_os_tres_campos():
    """Sem os três em todos, a regra de integridade não teria o que conferir."""
    for disp in _corpus()["dispositivos"]:
        assert "revisado" in disp, disp["id"]
        assert "conferido_em" in disp, disp["id"]
        assert "conferido_por" in disp, disp["id"]


def test_nenhum_dispositivo_foi_conferido_ainda():
    """A frase do README e do ROADMAP, conferida contra o arquivo.

    "Ainda não conferi nenhum" é uma afirmação sobre o estado do
    repositório, e ela precisa continuar verdadeira enquanto ninguém
    conferir. Quando o primeiro dispositivo for conferido de verdade,
    este teste quebra — e é para quebrar: a documentação tem de mudar no
    mesmo commit.
    """
    dispositivos = _corpus()["dispositivos"]
    assert len(dispositivos) == 21

    conferidos = [d["id"] for d in dispositivos if d["revisado"]]
    assert (
        conferidos == []
    ), f"conferidos de verdade? atualize README/ROADMAP: {conferidos}"
    assert all(d["conferido_em"] is None for d in dispositivos)
    assert all(d["conferido_por"] is None for d in dispositivos)


def test_o_aviso_do_corpus_explica_o_que_o_selo_significa():
    """O arquivo se explica sozinho para quem o abrir sem contexto."""
    aviso = _corpus()["aviso"]
    assert "conferido_em" in aviso
    assert "conferido_por" in aviso
    assert "RESUMO" in aviso  # é o resumo que se confere, não o texto
    assert "VIGÊNCIA" in aviso


# ---------------------------------------------------------------------------
# A regra de integridade, nos dois sentidos
# ---------------------------------------------------------------------------


def test_revisado_sem_data_e_recusado():
    """O caso que a regra existe para impedir: o selo sem assinatura."""
    with pytest.raises(ValueError, match="lc123-18"):
        conferir_integridade_do_corpus(
            [
                {
                    "id": "lc123-18",
                    "revisado": True,
                    "conferido_em": None,
                    "conferido_por": None,
                }
            ]
        )


def test_revisado_com_data_mas_sem_assinatura_e_recusado():
    """Data sozinha diz quando, não quem. Os dois ou nenhum."""
    with pytest.raises(ValueError):
        conferir_integridade_do_corpus(
            [
                {
                    "id": "lc123-18",
                    "revisado": True,
                    "conferido_em": "2026-08-14",
                    "conferido_por": None,
                }
            ]
        )


def test_data_sem_revisado_tambem_e_recusado():
    """O sentido inverso, que passaria despercebido num arquivo editado à mão.

    Alguém preenche a data ao começar a conferência, se distrai e não
    vira o booleano: o dispositivo fica com cara de conferido no JSON e
    de pendente na tela. Estado incoerente é pior que estado ruim,
    porque não dá para saber qual dos dois campos mente.
    """
    with pytest.raises(ValueError, match="lc123-18"):
        conferir_integridade_do_corpus(
            [
                {
                    "id": "lc123-18",
                    "revisado": False,
                    "conferido_em": "2026-08-14",
                    "conferido_por": "Roberto Chiocca",
                }
            ]
        )


def test_o_par_completo_passa():
    """A regra recusa incoerência, não conferência."""
    conferir_integridade_do_corpus(
        [
            {
                "id": "lc123-18",
                "revisado": True,
                "conferido_em": "2026-08-14",
                "conferido_por": "Roberto Chiocca",
            }
        ]
    )


def test_o_corpus_de_verdade_passa_na_regra():
    """E ela roda na carga: corpus incoerente não chega à tela."""
    conferir_integridade_do_corpus(_corpus()["dispositivos"])
    Retriever()  # não levanta


# ---------------------------------------------------------------------------
# Propagação pelas camadas
# ---------------------------------------------------------------------------


def test_o_retriever_propaga_os_dois_campos():
    resultados = Retriever().buscar("sublimite de ICMS", top_k=3)
    assert resultados
    for disp in resultados:
        assert hasattr(disp, "conferido_em")
        assert hasattr(disp, "conferido_por")
        assert disp.conferido_em is None  # nenhum conferido ainda


def test_o_esqueleto_da_ingestao_nasce_com_os_tres_campos():
    """Esqueleto novo não pode nascer com cara de conferido."""
    from carchuna.rag.ingestao import gerar_esqueletos

    html = "<p>Art. 1º Esta lei estabelece normas gerais.</p>"
    (esqueleto,) = gerar_esqueletos(
        html, lei="Lei de teste", prefixo="teste", tema="tributario", fonte="http://x"
    )
    assert esqueleto["revisado"] is False
    assert esqueleto["conferido_em"] is None
    assert esqueleto["conferido_por"] is None
    conferir_integridade_do_corpus([esqueleto])


# ---------------------------------------------------------------------------
# A mesclagem continua não destruindo trabalho humano
# ---------------------------------------------------------------------------


def test_dispositivo_conferido_nunca_e_sobrescrito():
    """A garantia antiga, agora também para o que tem data.

    Uma reingestão do Planalto não pode apagar uma conferência. O
    dispositivo conferido é preservado inteiro, com os três campos.
    """
    corpus = {
        "dispositivos": [
            {
                "id": "teste-1",
                "lei": "Lei",
                "artigo": "Art. 1º",
                "tema": "tributario",
                "texto": "texto humano",
                "resumo": "resumo escrito à mão",
                "palavras_chave": ["a"],
                "fonte": "http://x",
                "revisado": True,
                "conferido_em": "2026-08-14",
                "conferido_por": "Roberto Chiocca",
            }
        ]
    }
    novo = {
        "id": "teste-1",
        "lei": "Lei",
        "artigo": "Art. 1º",
        "tema": "tributario",
        "texto": "texto reingerido",
        "resumo": "TODO: resumir",
        "palavras_chave": [],
        "fonte": "http://x",
        "revisado": False,
        "conferido_em": None,
        "conferido_por": None,
    }
    resultado = mesclar_no_corpus(corpus, [novo])

    assert resultado.preservados == ["teste-1"]
    (guardado,) = corpus["dispositivos"]
    assert guardado["resumo"] == "resumo escrito à mão"
    assert guardado["conferido_em"] == "2026-08-14"


def test_data_de_conferencia_impede_o_descarte_mesmo_com_resumo_TODO():
    """A guarda mais barata: conferido nunca é esqueleto.

    Sem a checagem de `conferido_em`, um resumo reescrito para começar
    com "TODO" depois de conferido derrubaria a conferência na próxima
    reingestão — e o campo `revisado` sozinho já não estaria lá para
    defender, porque o par pode ter sido editado à mão.
    """
    conferido_mas_com_cara_de_esqueleto = {
        "id": "teste-2",
        "resumo": "TODO: revisar a redação",
        "palavras_chave": [],
        "revisado": False,
        "conferido_em": "2026-08-14",
    }
    assert not _e_esqueleto_intocado(conferido_mas_com_cara_de_esqueleto)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------------
# lc123-19 estava errado: fundia duas regras do art. 19 e perdia uma
# ---------------------------------------------------------------------------


def _lc123_19() -> dict:
    (disp,) = [d for d in _corpus()["dispositivos"] if d["id"] == "lc123-19"]
    return disp


def test_o_sublimite_do_corpus_separa_as_duas_hipoteses():
    """R$ 3,6 mi não vale para todo mundo, e o texto antigo dizia que sim.

    O art. 19 tem duas hipóteses e o dispositivo trazia uma só: Estado
    com até 1% do PIB pode optar por R$ 1.800.000 (caput); nos demais, e
    nos que não exercerem a opção, vale obrigatoriamente R$ 3.600.000
    (§ 4º). Quem estivesse num Estado do primeiro grupo lia no corpus
    uma fronteira que é o dobro da dele.
    """
    disp = _lc123_19()
    for pedaco in ("1.800.000,00", "3.600.000,00", "1%", "caput", "§ 4º"):
        assert pedaco in disp["texto"], f"falta {pedaco!r} no texto"
    for pedaco in ("1.800.000,00", "3.600.000,00"):
        assert pedaco in disp["resumo"], f"falta {pedaco!r} no resumo"


def test_o_resumo_do_sublimite_manda_confirmar_qual_vale():
    """Duas hipóteses sem dizer como escolher é meia informação.

    A Carchuna não sabe em que Estado o lojista está nem quais Estados
    exerceram a opção no ano — então o resumo diz isso, em vez de deixar
    o leitor achar que pode deduzir sozinho.
    """
    resumo = _lc123_19()["resumo"]
    assert "Estado" in resumo
    assert "contador" in resumo


def test_o_motor_declara_que_assume_o_sublimite_maior():
    """A simplificação do motor está escrita onde o número mora.

    `SUBLIMITE_ICMS_ISS` é R$ 3.600.000 para todos, e isso é decisão de
    implementação, não leitura da lei. O comentário tem de dizer o que
    ela custa: num Estado que tenha adotado o opcional, o aviso e a
    recusa saem tarde demais, porque a fronteira real é a metade.
    """
    fonte = (Path(__file__).resolve().parents[1] / "carchuna" / "margem.py").read_text(
        "utf-8"
    )
    trecho = fonte[
        fonte.index("SUBLIMITE_ICMS_ISS")
        - 2000 : fonte.index("SUBLIMITE_ICMS_ISS")
        + 200
    ]
    assert "1.800.000" in trecho
    assert "simplificação declarada" in trecho


# ---------------------------------------------------------------------------
# O selo na tela: dois estados visíveis, não um
# ---------------------------------------------------------------------------


def test_o_selo_de_pendente_continua_saindo():
    from carchuna.rag.llm import selo_de_conferencia
    from carchuna.rag.retrieval import Dispositivo

    disp = Dispositivo(
        id="x",
        lei="LC 123",
        artigo="Art. 18",
        tema="tributario",
        texto="t",
        resumo="r",
        fonte="http://x",
        revisado=False,
        score=1.0,
    )
    assert selo_de_conferencia(disp) == " [revisão humana pendente]"


def test_o_selo_de_conferido_traz_a_data():
    """ "Sem aviso" era o jeito de dizer conferido, e não dizia nada.

    Ausência de aviso some junto se alguém marcar `revisado` por engano,
    e nunca diz QUANDO — que é a parte que envelhece, porque resumo é
    interpretação e vigência muda.
    """
    from carchuna.rag.llm import selo_de_conferencia
    from carchuna.rag.retrieval import Dispositivo

    disp = Dispositivo(
        id="x",
        lei="LC 123",
        artigo="Art. 18",
        tema="tributario",
        texto="t",
        resumo="r",
        fonte="http://x",
        revisado=True,
        score=1.0,
        conferido_em="2026-08-14",
        conferido_por="Roberto Chiocca",
    )
    assert selo_de_conferencia(disp) == " [conferido em 2026-08-14]"


def test_conferido_sem_data_nao_finge_conferencia():
    """Estado que a regra de integridade impede, mas a tela não inventa.

    Se um dispositivo chegar aqui por outro caminho — corpus montado na
    mão, teste, chamador externo —, o selo mostra o estado bruto em vez
    de exibir uma data que não existe ou de sumir como se estivesse tudo
    certo.
    """
    from carchuna.rag.llm import selo_de_conferencia
    from carchuna.rag.retrieval import Dispositivo

    disp = Dispositivo(
        id="x",
        lei="LC 123",
        artigo="Art. 18",
        tema="tributario",
        texto="t",
        resumo="r",
        fonte="http://x",
        revisado=True,
        score=1.0,
    )
    assert selo_de_conferencia(disp) == " [conferido, sem data registrada]"


def test_o_retriever_recusa_corpus_incoerente_na_carga(tmp_path):
    """A regra tem de estar LIGADA no caminho real, não só existir.

    Conferir chamando a função direto não prova nada sobre a produção:
    era o buraco da primeira versão deste arquivo, e o mutante que
    removia a chamada do construtor passava em tudo. O que importa é que
    um corpus incoerente não chegue à tela — e quem carrega o corpus para
    a tela é o `Retriever`.
    """
    corpus = _corpus()
    corpus["dispositivos"][0]["revisado"] = True  # sem data nem assinatura
    arquivo = tmp_path / "corpus_torto.json"
    arquivo.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="conferido_em"):
        Retriever(data_path=arquivo)


# ---------------------------------------------------------------------------
# A lacuna de vigência: registrada no ROADMAP, nunca no corpus
# ---------------------------------------------------------------------------


def _roadmap() -> str:
    """O ROADMAP com o espaço normalizado.

    O Markdown quebra linha no meio das frases, então procurar por
    "último dia útil de setembro" no texto cru falha por causa de um
    `\n` — e o teste estaria reclamando da largura da coluna, não do
    conteúdo. Colapsar o espaço faz a asserção falar do que importa.
    """
    bruto = (Path(__file__).resolve().parents[1] / "ROADMAP.md").read_text("utf-8")
    return " ".join(bruto.split())


def test_a_reforma_nao_entrou_no_corpus_por_engano():
    """O corpus é o lugar do que tem lastro; o roadmap, do que falta.

    Nenhuma das leis da reforma foi conferida em fonte oficial. Se uma
    delas aparecer no corpus sem que a data de conferência exista, é
    porque alguém escreveu de memória — que é o defeito que este projeto
    inteiro existe para não cometer.
    """
    corpus_cru = CORPUS.read_text("utf-8")
    for lei in ("214/2025", "227/2026"):
        assert lei not in corpus_cru, f"LC {lei} no corpus sem conferência"


def test_o_roadmap_registra_as_duas_leis_da_reforma():
    """A LC 227/2026 existe e pode ter mexido no que a 214 dizia.

    Registrar a 214 como marco final seria repetir, com antecedência, o
    erro de citar dispositivo sem abrir a lei.
    """
    roadmap = _roadmap()
    assert "LC 214/2025" in roadmap
    assert "LC 227/2026" in roadmap
    assert "não sei o alcance" in roadmap.lower()


def test_o_roadmap_registra_os_DOIS_prazos_de_setembro():
    """Eram dois, e o registro anterior trazia um.

    Além da escolha do regime de IBS/CBS, o prazo de opção pelo Simples
    passou para o último dia útil de setembro do ano anterior — em
    setembro de 2026 se opta para 2027. O público da Carchuna decide as
    duas coisas na mesma janela.
    """
    roadmap = _roadmap()
    assert "DOIS prazos" in roadmap
    assert "IBS/CBS" in roadmap
    assert "último dia útil de setembro" in roadmap
    assert "2027" in roadmap


def test_o_todo_da_rbt12_cita_a_lei_e_nao_mudou_a_janela():
    """A citação entrou; o cálculo, não. As duas coisas são o ponto.

    A janela continua `range(1, 13)` — a regra vigente. Trocar por
    `range(2, 14)` agora seria mudar cálculo tributário com base em lei
    que ainda não foi aberta na fonte.
    """
    fonte = (
        Path(__file__).resolve().parents[1] / "carchuna" / "metricas.py"
    ).read_text("utf-8")

    assert "art. 18 da LC 123/2006 c/c LC 214/2025" in fonte
    assert "range(2, 14)" in fonte  # o que vai mudar, escrito
    assert "range(1, 13)" in fonte  # o que ainda vale, rodando
    assert "NÃO implementado de propósito" in fonte
