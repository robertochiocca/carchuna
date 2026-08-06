"""Radar de margem: cada limiar e cada método conferido à mão.

Todos os valores esperados estão calculados nos comentários, com a
alíquota efetiva do Anexo I em RBT12 = 360.000:
(360000 × 7,30% − 5.940) / 360000 = 20.340 / 360000 = 5,65%.
Comissão de tabela do Mercado Livre: 12% (anúncio Clássico).

Os casos vêm dos dois arquivos que testavam a mesma pergunta em módulos
separados — a tendência e a margem magra de um lado, os métodos
estatísticos do outro. Nenhum caso se perdeu na junção; o que mudou foi
que "mês fora do padrão" passou a ser detectado em um lugar só.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.insights import (
    ContextoInsights,
    DeducaoForaDoPadrao,
    MotorInsights,
    ParametrosInsights,
    ProdutosMargemMagra,
    TendenciaCustos,
    detectar_fora_do_padrao,
)
from carchuna.margem import ConfigTributaria, TabelaCustos, Transacao

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _venda(valor, mes, dia=15, **kwargs):
    return Transacao(
        data=date(2026, mes, dia),
        canal=kwargs.pop("canal", "mercado_livre"),
        valor_bruto=Decimal(valor),
        custo_produto=kwargs.pop("custo", Decimal("0")),
        frete_pago=kwargs.pop("frete", Decimal("0")),
        **kwargs,
    )


def _ctx(vendas):
    return ContextoInsights(
        transacoes=vendas,
        config=CONFIG,
        tabela=TabelaCustos(),
        parametros=ParametrosInsights(),
    )


# ---------------------------------------------------------------------------
# Tendência de custos (dedução subindo como % da receita)
# ---------------------------------------------------------------------------


def test_tendencia_comissao_subindo_8pp_e_critico_com_impacto_80():
    # Mês 1: venda 1000, comissão cobrada 120 → 12,00% da receita.
    # Mês 2: venda 1000, comissão cobrada 200 → 20,00% da receita.
    # Delta = 8,00 p.p. ≥ 3 (limiar crítico); impacto = 8% × 1000 = 80,00.
    vendas = [
        _venda("1000", 5, comissao_cobrada=Decimal("120")),
        _venda("1000", 6, comissao_cobrada=Decimal("200")),
    ]
    insights = MotorInsights().radar(vendas, CONFIG)
    assert len(insights) == 1
    (i,) = insights
    assert i.severidade == "critico"
    assert i.impacto_mensal == Decimal("80.00")
    assert "8.00 p.p." in i.titulo
    assert i.base_evidencia == "calculado"
    assert i.confianca.pct > 0


def test_tendencia_alta_pequena_vira_atencao_e_abaixo_do_limiar_silencia():
    # Delta de 2,00 p.p. (120 → 140 sobre 1000): atenção (1,5 ≤ 2 < 3).
    vendas = [
        _venda("1000", 5, comissao_cobrada=Decimal("120")),
        _venda("1000", 6, comissao_cobrada=Decimal("140")),
    ]
    (i,) = TendenciaCustos().avaliar(_ctx(vendas))
    assert i.severidade == "atencao"
    assert i.impacto_mensal == Decimal("20.00")

    # Delta de 1,00 p.p. (120 → 130): abaixo de 1,5 → sem sinal.
    vendas = [
        _venda("1000", 5, comissao_cobrada=Decimal("120")),
        _venda("1000", 6, comissao_cobrada=Decimal("130")),
    ]
    assert TendenciaCustos().avaliar(_ctx(vendas)) == []


def test_tendencia_exige_dois_meses():
    assert TendenciaCustos().avaliar(_ctx([_venda("1000", 5)])) == []


# ---------------------------------------------------------------------------
# Produtos de margem magra (com ganho de reajuste recalculado pelo motor)
# ---------------------------------------------------------------------------


def test_produto_magro_detectado_com_ganho_exato_do_reajuste():
    # Capinha: 100 − 5,65 (tributo) − 12 (comissão) − 66,35 (CMV) − 10
    #          (frete) = 6,00 → margem 6,00% < 8% → magra.
    # Fone:    100 − 5,65 − 12 − 20 − 5 = 57,35 → 57,35% → saudável.
    # Reajuste de 5% só na Capinha: bruto 105, tributo 105 × 5,65% = 5,93,
    # comissão 105 × 12% = 12,60 → margem da carteira sobe de
    # (200 − 11,30 − 24 − 86,35 − 15) = 63,35 para
    # (205 − 11,58 − 24,60 − 86,35 − 15) = 67,47 → ganho = 4,12/mês.
    vendas = [
        _venda(
            "100", 5, custo=Decimal("66.35"), frete=Decimal("10"), produto="Capinha"
        ),
        _venda("100", 5, custo=Decimal("20"), frete=Decimal("5"), produto="Fone"),
    ]
    insights = MotorInsights().radar(vendas, CONFIG)
    assert len(insights) == 1
    (i,) = insights
    assert i.severidade == "oportunidade"
    assert i.impacto_mensal == Decimal("4.12")
    assert "Capinha" in i.explicacao
    assert "Fone" not in i.explicacao
    assert "premissa" in i.explicacao  # honestidade: mesmo volume é premissa


def test_sem_produto_magro_sem_sinal():
    vendas = [_venda("100", 5, custo=Decimal("20"), produto="Fone")]
    assert ProdutosMargemMagra().avaliar(_ctx(vendas)) == []


# ---------------------------------------------------------------------------
# Detecção de mês fora do padrão — o método, isolado
# ---------------------------------------------------------------------------


def test_deteccao_exige_tres_meses_de_historico():
    p = ParametrosInsights()
    assert detectar_fora_do_padrao(
        [Decimal("10"), Decimal("20")], Decimal("99"), p
    ) is (None)
    assert (
        detectar_fora_do_padrao(
            [Decimal("10"), Decimal("11"), Decimal("10")], Decimal("99"), p
        )
        is not None
    )


def test_historico_perfeitamente_constante_so_dispara_acima_de_meio_pp():
    p = ParametrosInsights()
    serie = [Decimal("12.00")] * 4
    # 0,40 p.p. de desvio: dentro do limiar do histórico constante
    assert detectar_fora_do_padrao(serie, Decimal("12.40"), p) is None
    fora = detectar_fora_do_padrao(serie, Decimal("12.60"), p)
    assert fora is not None
    assert fora.forte is True
    assert "histórico constante" in fora.metodo


def test_a_cerca_de_iqr_veta_o_sinal_fraco_que_ela_nao_confirma():
    """O poder de veto da cerca, no ponto exato em que ele muda a resposta.

    Histórico espalhado 10 / 20 / 30 / 40: média 25, σ = 12,91, quartis
    17,50 e 32,50 → IQR 15 e cerca em 55. Um mês a 51 está a 2,01σ — o
    z-score chamaria de atenção — mas ainda dentro da cerca, e por isso é
    descartado. A 56 os dois métodos concordam e o sinal passa.

    O contraste que fecha o argumento está no fim: com três meses de
    histórico não há cerca para arbitrar, e um sinal de 2,2σ passa. É
    exatamente a situação — histórico curto — em que o corte por σ
    sozinho erra mais, e é por isso que a cerca entra assim que há pontos
    suficientes para calculá-la.
    """
    p = ParametrosInsights()
    serie = [Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40")]

    assert detectar_fora_do_padrao(serie, Decimal("51"), p) is None  # 2,01σ, vetado

    confirmado = detectar_fora_do_padrao(serie, Decimal("56"), p)  # 2,40σ
    assert confirmado is not None
    assert confirmado.forte is False
    assert "IQR" in confirmado.metodo

    # acima de 3σ o sinal passa mesmo sem confirmação da cerca
    forte = detectar_fora_do_padrao(serie, Decimal("64"), p)
    assert forte is not None and forte.forte is True

    # com 3 pontos não há cerca: o mesmo nível de sinal fraco passa
    curto = detectar_fora_do_padrao(serie[:3], Decimal("42"), p)  # 2,2σ
    assert curto is not None
    assert curto.forte is False
    assert "IQR" not in curto.metodo


# ---------------------------------------------------------------------------
# Dedução fora do padrão (a detecção acima, com narrativa)
# ---------------------------------------------------------------------------


def test_historico_constante_dispara_no_salto_e_calcula_o_impacto():
    # Comissão em 12,00% da receita por 3 meses; no 4º, 20,00%.
    # σ = 0 → regra do histórico constante (desvio 8 p.p. > 0,5 p.p.).
    # Esperado 12%, observado 20%, desvio (20−12)/12 = +66,7%,
    # impacto = 8% × 1.000 = 80,00. Custo caiu? Não — subiu → crítico.
    vendas = [_venda("1000", m, comissao_cobrada=Decimal("120")) for m in (1, 2, 3)] + [
        _venda("1000", 4, comissao_cobrada=Decimal("200"))
    ]
    (i,) = DeducaoForaDoPadrao().avaliar(_ctx(vendas))
    assert i.categoria == "comissoes_canal_pct"
    assert i.severidade == "critico"
    assert i.esperado == "12.00% da receita"
    assert i.observado == "20.00% da receita"
    assert i.desvio_pct == Decimal("66.7")
    assert i.impacto_mensal == Decimal("80.00")
    assert "histórico constante" in i.metodo
    assert i.confianca.pct > 0


def test_z_score_com_iqr_confirmando():
    # Série de comissão: 12,00 / 12,20 / 11,80 / 12,00 (média 12,00%,
    # σ ≈ 0,163) e o 5º mês em 13,00% → z ≈ 6,1σ ≥ 3 → crítico; a cerca
    # IQR (Q3 12,05 + 1,5×0,10 = 12,20) também é ultrapassada.
    # Impacto = 1% × 1.000 = 10,00.
    comissoes = ["120", "122", "118", "120", "130"]
    vendas = [
        _venda("1000", m, comissao_cobrada=Decimal(c))
        for m, c in enumerate(comissoes, start=1)
    ]
    (i,) = DeducaoForaDoPadrao().avaliar(_ctx(vendas))
    assert i.severidade == "critico"
    assert i.impacto_mensal == Decimal("10.00")
    assert "z-score" in i.metodo and "IQR" in i.metodo


def test_custo_que_cai_fora_do_padrao_vira_oportunidade():
    vendas = [_venda("1000", m, comissao_cobrada=Decimal("200")) for m in (1, 2, 3)] + [
        _venda("1000", 4, comissao_cobrada=Decimal("120"))
    ]
    (i,) = DeducaoForaDoPadrao().avaliar(_ctx(vendas))
    assert i.severidade == "oportunidade"
    assert "caiu" in i.titulo
    assert i.impacto_mensal == Decimal("80.00")


def test_o_salto_de_margem_aparece_pela_deducao_que_se_mexeu():
    """O caso que antes virava "margem fora do padrão", agora nomeando a causa.

    Meses 1–4: CMV 400/402/398/400 (40,00% / 40,20% / 39,80% / 40,00% da
    receita). Mês 5: CMV cai para 300 → 30,00% → −10 p.p., muito além da
    cerca. Impacto = 10% × 1.000 = 100,00 — o mesmo número que a leitura
    pela margem dava, com a vantagem de dizer QUAL dedução se moveu.
    """
    vendas = [
        _venda("1000", 1, custo=Decimal("400")),
        _venda("1000", 2, custo=Decimal("402")),
        _venda("1000", 3, custo=Decimal("398")),
        _venda("1000", 4, custo=Decimal("400")),
        _venda("1000", 5, custo=Decimal("300")),
    ]
    insights = MotorInsights().radar(vendas, CONFIG)
    assert len(insights) == 1
    (i,) = insights
    assert i.categoria == "cmv_pct"
    assert i.severidade == "oportunidade"
    assert i.impacto_mensal == Decimal("100.00")
    assert "caiu" in i.titulo
    assert i.esperado == "40.00% da receita"
    assert i.observado == "30.00% da receita"


def test_exige_quatro_meses_e_historico_com_variacao():
    tres_meses = [_venda("1000", m, custo=Decimal("400")) for m in (1, 2, 3)]
    assert DeducaoForaDoPadrao().avaliar(_ctx(tres_meses)) == []
    # Histórico perfeitamente constante E mês igual: nada a relatar.
    constantes = [_venda("1000", m, custo=Decimal("400")) for m in (1, 2, 3, 4, 5)]
    assert DeducaoForaDoPadrao().avaliar(_ctx(constantes)) == []


# ---------------------------------------------------------------------------
# Economia unitária e divergência receita × lucro
# ---------------------------------------------------------------------------


def test_frete_por_pedido_contra_a_media_movel():
    # 2 pedidos/mês com frete 10 cada nos meses 1–3 (R$ 10/pedido);
    # no mês 4, frete 15 cada → R$ 15/pedido = +50% ≥ 25% → atenção.
    # Impacto = (15 − 10) × 2 pedidos = 10,00. A fatia do frete na
    # receita sobe exatamente 0,5 p.p. — no limiar, não acima — então a
    # regra de dedução NÃO dispara junto (sem duplicidade).
    vendas = []
    for m in (1, 2, 3):
        vendas += [_venda("1000", m, frete=Decimal("10")) for _ in range(2)]
    vendas += [_venda("1000", 4, frete=Decimal("15")) for _ in range(2)]
    (i,) = MotorInsights().radar(vendas, CONFIG)
    assert i.categoria == "frete_por_pedido"
    assert i.severidade == "atencao"
    assert i.esperado == "R$ 10.00/pedido"
    assert i.observado == "R$ 15.00/pedido"
    assert i.desvio_pct == Decimal("50.0")
    assert i.impacto_mensal == Decimal("10.00")
    assert "média móvel" in i.metodo


def test_receita_sobe_lucro_cai_aponta_a_causa():
    # Mês 1: receita 1.000, comissão 120, CMV 400 → lucro 423,50.
    # Mês 2: receita 1.200 (+20%), comissão 350, CMV 480 → lucro 302,20
    # (−28,6%). Esperado se a margem acompanhasse: 423,50 × 1,2 = 508,20
    # → impacto 206,00. Causa: comissão, de 12% para 29,17% da receita.
    vendas = [
        _venda("1000", 1, comissao_cobrada=Decimal("120"), custo=Decimal("400")),
        _venda("1200", 2, comissao_cobrada=Decimal("350"), custo=Decimal("480")),
    ]
    insights = MotorInsights().radar(vendas, CONFIG)
    divergencia = [i for i in insights if i.categoria == "receita_x_lucro"]
    (i,) = divergencia
    assert i.severidade == "critico"
    assert i.esperado.startswith("R$ 508.20")
    assert i.observado.startswith("R$ 302.20")
    assert i.impacto_mensal == Decimal("206.00")
    assert "Comissões de canal" in i.explicacao
    assert "divergência" in i.metodo


def test_meses_estaveis_nao_geram_sinal_e_lista_vazia_e_recusada():
    vendas = [
        _venda("1000", m, comissao_cobrada=Decimal("120"), custo=Decimal("400"))
        for m in (1, 2, 3, 4, 5)
    ]
    assert MotorInsights().radar(vendas, CONFIG) == []
    with pytest.raises(ValueError):
        MotorInsights().radar([], CONFIG)


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------


def test_radar_ordena_por_severidade_e_todo_sinal_traz_metodo_e_confianca():
    # Crítico (comissão +8 p.p.) e oportunidade (produto magro) juntos:
    # o crítico vem primeiro. Capinha nos 2 meses: receita 2000, tributos
    # 113, comissões 320, CMV 1500 → margem 67 → 3,35% (magra).
    vendas = [
        _venda(
            "1000",
            5,
            comissao_cobrada=Decimal("120"),
            custo=Decimal("750"),
            produto="Capinha",
        ),
        _venda(
            "1000",
            6,
            comissao_cobrada=Decimal("200"),
            custo=Decimal("750"),
            produto="Capinha",
        ),
    ]
    insights = MotorInsights().radar(vendas, CONFIG)
    assert len(insights) >= 2
    severidades = [i.severidade for i in insights]
    assert severidades == sorted(
        severidades, key=["critico", "atencao", "oportunidade"].index
    )
    # nenhum sinal chega ao lojista sem método declarado e nota de confiança
    for i in insights:
        assert i.metodo
        assert i.confianca.pct > 0
        assert i.base_evidencia in ("calculado", "estimado")
        assert i.aviso


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
