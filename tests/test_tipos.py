"""Testes dos tipos semânticos: booleano ≠ categórico ≠ ausente.

Cobrem os nove casos obrigatórios da correção do bug "devolvida =
'Solicitação aprovada' não é sim/não" — a coluna de devolução pode vir
como booleano OU como status categórico, e valor ausente nunca é valor
inválido.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.dados import carregar_transacoes, transacoes_de_mapa
from carchuna.tipos import (
    como_booleano,
    eh_ausente,
    inferir_tipo_coluna,
    interpretar_devolucao,
    normalizar_valor,
    resumo_devolucao,
)

# ---------------------------------------------------------------------------
# Inferência de tipo de coluna (casos 1–6)
# ---------------------------------------------------------------------------


def test_caso1_booleano_simples():
    tipo = inferir_tipo_coluna(["Sim", "Não", "Sim"])
    assert tipo.tipo == "booleano"
    assert tipo.valores_distintos == ("Sim", "Não")


def test_caso2_booleano_em_ingles():
    assert inferir_tipo_coluna(["True", "False"]).tipo == "booleano"


def test_caso3_booleano_numerico():
    # 1/0 são booleanos confiáveis (compatível com o léxico já aceito
    # pela importação desde a v1).
    assert inferir_tipo_coluna(["1", "0", "1"]).tipo == "booleano"


def test_caso4_status_categorico_nao_e_booleano_e_nao_da_erro():
    tipo = inferir_tipo_coluna(["Solicitação aprovada", "Solicitação recusada"])
    assert tipo.tipo == "categorico"
    assert tipo.valores_distintos == (
        "Solicitação aprovada",
        "Solicitação recusada",
    )


def test_caso5_multiplos_status_sao_categoricos():
    tipo = inferir_tipo_coluna(["Aprovado", "Recusado", "Em análise"])
    assert tipo.tipo == "categorico"


def test_caso6_valores_ausentes_contados_e_nunca_invalidados():
    tipo = inferir_tipo_coluna(["Sim", None, "Não", "NaN", ""])
    assert tipo.tipo == "booleano"  # os presentes decidem o tipo
    assert tipo.ausentes == 3
    for ausente in (None, "", "  ", "nan", "NaN", "null", "N/A", "-"):
        assert eh_ausente(ausente)
    assert not eh_ausente("Não")  # "não" é valor, não ausência


def test_colunas_numericas_datas_e_texto_livre():
    assert inferir_tipo_coluna(["1.234,56", "R$ 10", "7"]).tipo == "numerico"
    assert inferir_tipo_coluna(["2026-05-01", "02/06/2026"]).tipo == "data"
    textos = [f"observação livre nº {i}" for i in range(30)]
    assert inferir_tipo_coluna(textos).tipo == "texto"


# ---------------------------------------------------------------------------
# Semântica de negócio da devolução (casos 7–8)
# ---------------------------------------------------------------------------


def test_caso7_valores_ambiguos_preservam_a_incerteza():
    # "Em análise" NUNCA vira True/False em silêncio.
    assert interpretar_devolucao("Em análise") == "indefinido"
    assert interpretar_devolucao("Aguardando documentos") == "indefinido"
    assert interpretar_devolucao("qualquer coisa inédita") == "desconhecido"


def test_caso8_variacoes_de_texto_normalizam_igual():
    assert normalizar_valor("  SIM ") == normalizar_valor("sim") == "sim"
    assert como_booleano("  SIM ") is True
    assert como_booleano("Não") is como_booleano("NAO") is False
    assert como_booleano("Solicitação aprovada") is None  # categoria ≠ booleano


def test_semantica_de_devolucao_por_estado():
    assert interpretar_devolucao("Sim") == "devolvida"
    assert interpretar_devolucao("Solicitação aprovada") == "devolvida"
    assert interpretar_devolucao("Reembolso realizado") == "devolvida"
    assert interpretar_devolucao("Devolvido") == "devolvida"
    assert interpretar_devolucao("Não") == "nao_devolvida"
    assert interpretar_devolucao("Solicitação recusada") == "nao_devolvida"
    assert interpretar_devolucao("Reembolso recusado") == "nao_devolvida"
    assert interpretar_devolucao("Não se aplica") == "nao_devolvida"
    assert interpretar_devolucao("Não devolvida") == "nao_devolvida"


def test_resumo_agrupa_categorias_por_estado_para_o_mapeador():
    grupos = resumo_devolucao(
        ["Solicitação aprovada", "Em análise", "Solicitação recusada", "", None]
    )
    assert grupos["devolvida"] == ["Solicitação aprovada"]
    assert grupos["nao_devolvida"] == ["Solicitação recusada"]
    assert grupos["indefinido"] == ["Em análise"]
    assert grupos["desconhecido"] == []


# ---------------------------------------------------------------------------
# Ingestão de ponta a ponta (o bug original + caso 9, regressão)
# ---------------------------------------------------------------------------

_CSV_STATUS = (
    "data,canal,valor_bruto,custo_produto,frete_pago,devolvida\n"
    "2026-05-10,shopee,100,40,10,Solicitação aprovada\n"
    "2026-05-11,shopee,100,40,10,Solicitação recusada\n"
    "2026-05-12,shopee,100,40,10,\n"
)


def test_bug_original_status_categorico_importa_sem_erro(tmp_path):
    arquivo = tmp_path / "devolucoes.csv"
    arquivo.write_text(_CSV_STATUS, encoding="utf-8")
    t1, t2, t3 = carregar_transacoes(arquivo)
    assert t1.devolvida is True  # solicitação aprovada = devolução aconteceu
    assert t2.devolvida is False
    assert t3.devolvida is False  # ausente = sem devolução (premissa docum.)
    # o valor ORIGINAL fica preservado, sem destruir a semântica
    assert t1.devolucao_status == "Solicitação aprovada"
    assert t2.devolucao_status == "Solicitação recusada"
    assert t3.devolucao_status is None


def test_status_indefinido_exige_decisao_do_usuario(tmp_path):
    arquivo = tmp_path / "pendentes.csv"
    arquivo.write_text(
        "data,canal,valor_bruto,custo_produto,frete_pago,devolvida\n"
        "2026-05-10,shopee,100,40,10,Em análise\n",
        encoding="utf-8",
    )
    # sem decisão: erro CLARO, nunca chute silencioso
    with pytest.raises(ValueError, match="status intermediário"):
        carregar_transacoes(arquivo)
    # com a decisão do usuário ("em análise ainda não é devolução"): passa
    (t,) = carregar_transacoes(arquivo, interpretacao_devolvida={"em analise": False})
    assert t.devolvida is False
    assert t.devolucao_status == "Em análise"


def test_mapeador_com_status_e_decisao_do_usuario():
    linhas = [
        {"dia": "2026-05-10", "preço": "100", "status reembolso": "Aprovado"},
        {"dia": "2026-05-11", "preço": "100", "status reembolso": "Em disputa"},
    ]
    mapa = {
        "data": "dia",
        "canal": "=shopee",
        "valor_bruto": "preço",
        "custo_produto": "=0",
        "frete_pago": "=0",
        "devolvida": "status reembolso",
    }
    with pytest.raises(ValueError, match="não adivinha"):
        transacoes_de_mapa(linhas, mapa)
    t1, t2 = transacoes_de_mapa(
        linhas, mapa, interpretacao_devolvida={"em disputa": False}
    )
    assert t1.devolvida is True  # "Aprovado": léxico conclusivo
    assert t2.devolvida is False  # "Em disputa": decisão explícita do usuário
    # a decisão do usuário SEMPRE sobrepõe o léxico
    t3, _ = transacoes_de_mapa(
        linhas,
        mapa,
        interpretacao_devolvida={"aprovado": False, "em disputa": False},
    )
    assert t3.devolvida is False


def test_caso9_regressao_formatos_booleanos_seguem_funcionando(tmp_path):
    csv = tmp_path / "v.csv"
    csv.write_text(
        "data,canal,valor_bruto,custo_produto,frete_pago,devolvida\n"
        "2026-05-10,mercado_livre,100,40,10,sim\n"
        "2026-05-11,mercado_livre,100,40,10,0\n"
        "2026-05-12,mercado_livre,100,40,10,True\n",
        encoding="utf-8",
    )
    t1, t2, t3 = carregar_transacoes(csv)
    assert (t1.devolvida, t2.devolvida, t3.devolvida) == (True, False, True)

    json_arq = tmp_path / "v.json"
    json_arq.write_text(
        '[{"data": "2026-05-10", "canal": "shopee", "valor_bruto": "100",'
        ' "custo_produto": "40", "frete_pago": "10",'
        ' "devolvida": "Reembolso realizado"}]',
        encoding="utf-8",
    )
    (tj,) = carregar_transacoes(json_arq)
    assert tj.devolvida is True
    assert tj.devolucao_status == "Reembolso realizado"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
