"""Testes do motor de decisão e da nota de confiança explicável.

A rubrica de confiança e os fatores de prioridade estão documentados nos
módulos; aqui cada nota e cada pontuação é conferida à mão.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.confianca import FRASE_DADOS, FRASE_HIPOTESE, avaliar_confianca
from carchuna.crescimento import Oportunidade
from carchuna.decisao import MotorDecisao, recomendar
from carchuna.diagnostico import Achado
from carchuna.insights import Insight
from carchuna.margem import ConfigTributaria, Transacao

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _venda(mes, **kwargs):
    return Transacao(
        data=date(2026, mes, 15),
        canal="mercado_livre",
        valor_bruto=Decimal("100"),
        custo_produto=Decimal("40"),
        frete_pago=Decimal("10"),
        **kwargs,
    )


# Base pequena: 2 vendas, 2 meses, ambas com comissão real, sem produto,
# sem prazo → evidência calculada 40 + histórico 6 + amostra 5 +
# completude (2+0+0)/(3×2) = 1/3 → 6,67 → 7. Total = 58 (média).
BASE_PEQUENA = [
    _venda(5, comissao_cobrada=Decimal("12")),
    _venda(6, comissao_cobrada=Decimal("12")),
]


# ---------------------------------------------------------------------------
# Nota de confiança (rubrica conferida à mão)
# ---------------------------------------------------------------------------


def test_nota_base_pequena_calculada_da_58_media_e_frase_de_hipotese():
    nota = avaliar_confianca(BASE_PEQUENA, base="calculado")
    assert nota.pct == 58
    assert nota.nivel == "media"
    por_nome = {c.nome: c.pontos for c in nota.componentes}
    assert por_nome == {"evidencia": 40, "historico": 6, "amostra": 5, "completude": 7}
    # 58 < 70: mesmo evidência calculada ainda é hipótese
    assert nota.frase == FRASE_HIPOTESE


def test_nota_maxima_com_12_meses_240_vendas_e_dados_completos():
    vendas = [
        _venda(
            mes,
            comissao_cobrada=Decimal("12"),
            produto="Fone",
            prazo_recebimento_dias=14,
        )
        for mes in range(1, 13)
        for _ in range(20)
    ]
    nota = avaliar_confianca(vendas, base="calculado")
    assert nota.pct == 100
    assert nota.nivel == "alta"
    assert nota.frase == FRASE_DADOS
    # a mesma base com evidência estimada nunca diz "os dados mostram"
    estimada = avaliar_confianca(vendas, base="estimado")
    assert estimada.pct == 85  # 25 + 20 + 20 + 20
    assert estimada.frase == FRASE_HIPOTESE


def test_nota_valida_entradas():
    with pytest.raises(ValueError):
        avaliar_confianca([], base="calculado")
    with pytest.raises(ValueError, match="base"):
        avaliar_confianca(BASE_PEQUENA, base="chute")


# ---------------------------------------------------------------------------
# Motor de decisão (pontuação conferida à mão)
# ---------------------------------------------------------------------------


def _achado(impacto):
    return Achado(
        tipo="contratual",
        titulo="Comissão diverge da tabela",
        impacto_mensal=Decimal(impacto),
        explicacao="",
        base_legal=(),
        caminho_pratico="Contestar no canal.",
        confianca="calculado",
    )


def _insight(impacto):
    return Insight(
        severidade="oportunidade",
        titulo="Produtos de margem magra",
        impacto_mensal=Decimal(impacto),
        explicacao="",
        caminho_pratico="Use a calculadora de preço.",
        confianca="calculado",
        categoria="margem_magra",
    )


def _oportunidade(ganho):
    return Oportunidade(
        tipo="espaco_tributario",
        titulo="Quanto cabe crescer no Simples",
        ganho_estimado_mensal=Decimal(ganho),
        explicacao="",
        base_legal=(),
        caminho_pratico="Planejar com o contador.",
        confianca="estimado",
    )


def test_pontuacao_e_ordenacao_conferidas_a_mao():
    # Confiança na base pequena: calculado 58%, estimado 43% (25+6+5+7).
    # Achado contratual (médio/semanas/baixo/reversível → 0,80×0,90 = 0,72):
    #   1000 × 0,58 × 0,72 = 417,60
    # Insight margem magra (baixo/dias/médio/reversível → 0,85):
    #   800 × 0,58 × 0,85 = 394,40
    # Oportunidade espaço tributário (médio/meses/baixo/rev. → 0,80×0,75 = 0,60):
    #   2000 × 0,43 × 0,60 = 516,00
    recs = MotorDecisao().recomendar(
        BASE_PEQUENA, [_achado("1000")], [_insight("800")], [_oportunidade("2000")]
    )
    assert [r.pontuacao for r in recs] == [
        Decimal("516.00"),
        Decimal("417.60"),
        Decimal("394.40"),
    ]
    assert [r.prioridade for r in recs] == [1, 2, 3]
    assert recs[0].origem == "crescimento"
    assert recs[1].acao.startswith("Conferir o plano")
    # a justificativa mostra a conta armada, fator a fator
    assert "0.80 (esforço medio)" in recs[1].justificativa
    assert "= 417.60 pontos" in recs[1].justificativa
    assert recs[1].confianca.pct == 58


def test_tipo_fora_do_catalogo_usa_o_caminho_pratico_como_acao():
    desconhecido = Achado(
        tipo="regra_de_terceiro",
        titulo="Achado novo",
        impacto_mensal=Decimal("100"),
        explicacao="",
        base_legal=(),
        caminho_pratico="Fazer algo específico.",
        confianca="calculado",
    )
    (rec,) = MotorDecisao().recomendar(BASE_PEQUENA, [desconhecido], [], [])
    assert rec.acao == "Fazer algo específico."
    assert rec.esforco == "medio" and rec.reversibilidade == "parcial"


def test_atalho_integra_os_tres_motores():
    from carchuna.dados import transacoes_sinteticas

    vendas = transacoes_sinteticas(meses=6)
    recs = recomendar(vendas, CONFIG)
    assert recs, "a base sintética deve gerar ao menos uma recomendação"
    assert [r.prioridade for r in recs] == list(range(1, len(recs) + 1))
    pontuacoes = [r.pontuacao for r in recs]
    assert pontuacoes == sorted(pontuacoes, reverse=True)


def test_recusa_lista_vazia():
    with pytest.raises(ValueError):
        MotorDecisao().recomendar([], [], [], [])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
