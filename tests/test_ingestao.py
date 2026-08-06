"""Testes da ingestão do Planalto — todos offline, com HTML sintético.

O HTML abaixo reproduz as manias da página real: ordinal em ``<sup>``,
artigo com sufixo de letra, tabela, e um bloco de script que não pode
vazar para o texto extraído.
"""

from __future__ import annotations

import copy
import json

import pytest

from carchuna.rag.ingestao import (
    TEMAS_VALIDOS,
    decodificar_html,
    extrair_artigos,
    extrair_texto_html,
    gerar_esqueletos,
    mesclar_no_corpus,
)

HTML = """
<html><head><title>LCP 123</title>
<style>.x{color:red}</style></head>
<body>
<script>var rastreador = "nao deve aparecer";</script>
<p>Art. 3<sup>o</sup>  Consideram-se microempresas ou empresas de pequeno porte.</p>
<p>Art. 18.  O valor devido mensalmente ser&aacute; determinado mediante
aplica&ccedil;&atilde;o das al&iacute;quotas efetivas.</p>
<p>Art. 18-A.  O Microempreendedor Individual poder&aacute; optar pelo
recolhimento em valores fixos mensais.</p>
<p>Art. 1.694.  Podem os parentes pedir uns aos outros os alimentos.</p>
</body></html>
"""

FONTE = "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm"
LEI = "Lei Complementar nº 123/2006"


def test_script_e_estilo_nao_vazam_para_o_texto():
    texto = extrair_texto_html(HTML)
    assert "rastreador" not in texto
    assert "color:red" not in texto


def test_entidades_html_viram_acentos():
    texto = extrair_texto_html(HTML)
    assert "será" in texto
    assert "alíquotas" in texto


def test_extrai_artigos_com_ordinal_sufixo_e_numero_composto():
    numeros = [a["numero"] for a in extrair_artigos(HTML)]
    assert numeros == ["3", "18", "18-A", "1.694"]


def test_artigo_com_sufixo_nao_engole_o_seguinte():
    artigos = {a["numero"]: a["texto"] for a in extrair_artigos(HTML)}
    assert "Microempreendedor Individual" in artigos["18-A"]
    assert "Microempreendedor" not in artigos["18"]


def test_esqueleto_sai_no_formato_do_corpus():
    (esq,) = gerar_esqueletos(
        HTML, lei=LEI, fonte=FONTE, tema="tributario", numeros=["18"], prefixo="lc123"
    )
    assert set(esq) == {
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
    assert esq["id"] == "lc123-18"
    assert esq["artigo"] == "Art. 18"
    assert esq["revisado"] is False
    assert esq["resumo"].startswith("TODO")
    assert esq["palavras_chave"] == []


def test_id_de_artigo_com_sufixo_perde_o_hifen():
    (esq,) = gerar_esqueletos(
        HTML, lei=LEI, fonte=FONTE, numeros=["18-A"], prefixo="lc123"
    )
    assert esq["id"] == "lc123-18a"


def test_filtro_de_artigos_e_case_insensitive():
    esqueletos = gerar_esqueletos(
        HTML, lei=LEI, fonte=FONTE, numeros=["18-a"], prefixo="lc123"
    )
    assert [e["artigo"] for e in esqueletos] == ["Art. 18-A"]


def test_sem_prefixo_o_id_usa_o_slug_da_lei():
    # NFKD decompõe o ordinal "º" em "o" — daí "lei-no", não "lei-n".
    (esq,) = gerar_esqueletos(
        HTML, lei="Lei nº 8.078/1990", fonte=FONTE, numeros=["18"]
    )
    assert esq["id"] == "lei-no-8-078-1990-18"


def test_tema_fora_do_corpus_e_rejeitado():
    with pytest.raises(ValueError, match="fora do corpus"):
        gerar_esqueletos(HTML, lei=LEI, fonte=FONTE, tema="trabalhista")


def test_temas_validos_cobrem_os_temas_em_uso_no_corpus(corpus_real):
    em_uso = {d["tema"] for d in corpus_real["dispositivos"]}
    assert em_uso <= TEMAS_VALIDOS


def test_reingestao_nao_encosta_em_nenhum_dispositivo_do_corpus_real(corpus_real):
    """A garantia que importa, cobrada contra o corpus de verdade.

    Hoje os 21 dispositivos têm resumo escrito à mão e ``revisado: false``,
    porque o que falta é a conferência na fonte oficial — não o texto. Uma
    regra ingênua ("não revisado, pode sobrescrever") apagaria os 21 de uma
    vez, em silêncio, e o prejuízo só apareceria semanas depois.

    Este teste reingere artigos com os mesmos ids e exige que cada um dos
    existentes saia da mesclagem idêntico, campo por campo.
    """
    antes = copy.deepcopy(corpus_real["dispositivos"])
    ids_existentes = [d["id"] for d in antes]

    # texto novo para TODOS os ids que já estão no corpus, mais um inédito
    artigos = "".join(
        f"<p>Art. {i}. texto novo vindo de uma reingestao.</p>"
        for i in range(1, len(ids_existentes) + 2)
    )
    novos = gerar_esqueletos(
        artigos, lei=LEI, fonte=FONTE, tema="tributario", prefixo="lc123"
    )
    novos = [n for n in novos if n["id"] in ids_existentes] + [
        {**novos[0], "id": "lc123-inedito"}
    ]

    resultado = mesclar_no_corpus(corpus_real, novos)

    assert resultado.atualizados == [], "nenhum dispositivo do corpus pode ser tocado"
    assert resultado.adicionados == ["lc123-inedito"]
    assert sorted(resultado.preservados) == sorted(
        n["id"] for n in novos if n["id"] != "lc123-inedito"
    )
    # e os originais seguem idênticos, campo por campo
    assert corpus_real["dispositivos"][: len(antes)] == antes


# ------------------------------------------------------------------ mesclagem
def _corpus(*dispositivos):
    return {
        "aviso": "…",
        "data_ingestao": "2026-01-01",
        "dispositivos": list(dispositivos),
    }


def test_mesclagem_adiciona_id_novo():
    corpus = _corpus()
    novos = gerar_esqueletos(
        HTML, lei=LEI, fonte=FONTE, numeros=["18"], prefixo="lc123"
    )
    resultado = mesclar_no_corpus(corpus, novos)
    assert resultado.adicionados == ["lc123-18"]
    assert len(corpus["dispositivos"]) == 1


def test_mesclagem_nunca_sobrescreve_dispositivo_revisado():
    revisado = {
        "id": "lc123-18",
        "lei": LEI,
        "artigo": "Art. 18",
        "tema": "tributario",
        "texto": "texto conferido à mão",
        "resumo": "resumo escrito por um humano",
        "palavras_chave": ["simples"],
        "fonte": FONTE,
        "revisado": True,
    }
    corpus = _corpus(copy.deepcopy(revisado))
    novos = gerar_esqueletos(
        HTML, lei=LEI, fonte=FONTE, numeros=["18"], prefixo="lc123"
    )

    resultado = mesclar_no_corpus(corpus, novos)

    assert resultado.preservados == ["lc123-18"]
    assert resultado.atualizados == []
    assert corpus["dispositivos"][0] == revisado


def test_mesclagem_atualiza_esqueleto_intocado():
    antigo = {
        "id": "lc123-18",
        "lei": LEI,
        "artigo": "Art. 18",
        "tema": "revisar",
        "texto": "texto errado da primeira tentativa",
        "resumo": "TODO: escrever resumo",
        "palavras_chave": [],
        "fonte": FONTE,
        "revisado": False,
    }
    corpus = _corpus(antigo)
    novos = gerar_esqueletos(
        HTML, lei=LEI, fonte=FONTE, tema="tributario", numeros=["18"], prefixo="lc123"
    )

    resultado = mesclar_no_corpus(corpus, novos)

    assert resultado.atualizados == ["lc123-18"]
    assert corpus["dispositivos"][0]["tema"] == "tributario"
    assert "alíquotas efetivas" in corpus["dispositivos"][0]["texto"]


def test_resumo_escrito_a_mao_sobrevive_mesmo_sem_revisao():
    # O caso do corpus real: 21 dispositivos com resumo humano e
    # revisado: false, porque falta a conferência na fonte — não o texto.
    escrito = {
        "id": "lc123-18a",
        "lei": LEI,
        "artigo": "Art. 18-A",
        "tema": "tributario",
        "texto": "texto condensado à mão",
        "resumo": "O MEI recolhe valor fixo por mês, independente do faturamento.",
        "palavras_chave": ["mei", "fixo"],
        "fonte": FONTE,
        "revisado": False,
    }
    corpus = _corpus(copy.deepcopy(escrito))
    novos = gerar_esqueletos(
        HTML, lei=LEI, fonte=FONTE, tema="tributario", numeros=["18-A"], prefixo="lc123"
    )

    resultado = mesclar_no_corpus(corpus, novos)

    assert resultado.preservados == ["lc123-18a"]
    assert corpus["dispositivos"][0] == escrito


def test_mesclagem_preserva_a_ordem_dos_existentes():
    corpus = _corpus(
        {"id": "a", "revisado": True},
        {"id": "b", "revisado": True},
    )
    mesclar_no_corpus(corpus, [{"id": "c", "revisado": False}])
    assert [d["id"] for d in corpus["dispositivos"]] == ["a", "b", "c"]


# ---------------------------------------------------------------- decodificação
def test_decodifica_utf8_de_pagina_salva_no_navegador():
    assert "alíquota" in decodificar_html("alíquota".encode())


def test_decodifica_windows1252_de_pagina_baixada_crua():
    assert "alíquota" in decodificar_html("alíquota".encode("windows-1252"))


def test_encoding_declarado_errado_nao_produz_mojibake():
    # O Planalto declara UTF-8 em páginas que estão em windows-1252.
    bruto = "alíquota".encode("windows-1252")
    assert "alíquota" in decodificar_html(bruto, encoding_declarado="utf-8")


@pytest.fixture
def corpus_real():
    from carchuna.rag.retrieval import DATA_PATH

    return json.loads(DATA_PATH.read_text(encoding="utf-8"))
