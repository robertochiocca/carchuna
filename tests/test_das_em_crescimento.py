"""O DAS fixo fabricava prejuízo e fabricava gap entre canais.

Mesma causa que o defeito do detector de margem magra, em dois lugares
que ninguém tinha olhado: `crescimento.py` decompõe subconjuntos —
venda a venda numa análise, canal a canal na outra — e `decompor_margem`
cobra o DAS inteiro em qualquer conjunto que receba.

Os dois pontos caem em lados opostos da regra escrita em
`config_do_subconjunto`, e é isso que este arquivo trava:

- **venda no prejuízo** é pergunta sobre o que muda se a venda parar. O
  DAS não muda, então fica fora (`BASE_VARIAVEL`).
- **mix de canais** é comparação entre grupos lida como margem. O DAS é
  rateado por receita (`BASE_RATEADA`), o que desloca todo canal pelo
  mesmo tanto e não pode inventar diferença entre eles.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.crescimento import (
    AnaliseMixCanais,
    AnaliseVendasNoPrejuizo,
    ContextoCrescimento,
    ParametrosCrescimento,
)
from carchuna.margem import ConfigTributaria, TabelaCustos, Transacao, decompor_margem
from carchuna.rag.retrieval import Retriever

MEI = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76.00"))
SIMPLES = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))
RETRIEVER = Retriever()


def _t(canal: str, valor: str, custo: str) -> Transacao:
    return Transacao(
        data=date(2026, 5, 10),
        canal=canal,
        valor_bruto=Decimal(valor),
        custo_produto=Decimal(custo),
        frete_pago=Decimal("0"),
    )


def _ctx(vendas, config=MEI) -> ContextoCrescimento:
    return ContextoCrescimento(
        transacoes=vendas,
        config=config,
        tabela=TabelaCustos(),
        parametros=ParametrosCrescimento(),
        retriever=RETRIEVER,
    )


# ---------------------------------------------------------------------------
# (a) Vendas no prejuízo — o DAS fica de fora
# ---------------------------------------------------------------------------


def test_venda_saudavel_nao_e_acusada_de_prejuizo_pelo_das_fixo():
    """Dez vendas que dão lucro no conjunto, acusadas uma a uma.

    Calibrado para o defeito passar por aqui: R$ 200 de venda, R$ 150 de
    custo, loja própria (2% de adquirência, sem comissão). O conjunto
    inteiro dá +R$ 384,00 de margem. Venda a venda, com o DAS de R$ 76
    caindo inteiro em cada uma, cada venda sai a −R$ 30,00 e as dez são
    marcadas — R$ 300/mês de prejuízo que não existe em lugar nenhum.

    É mais grave que o defeito do produto magro: lá o app mandava
    reprecificar algo bom, aqui ele diz ao lojista que está vendendo no
    vermelho e manda matar a venda que paga o próprio boleto.
    """
    vendas = [_t("loja_propria", "200", "150") for _ in range(10)]
    assert decompor_margem(vendas, MEI, TabelaCustos()).margem_liquida > 0

    assert AnaliseVendasNoPrejuizo().avaliar(_ctx(vendas)) == []


def test_venda_de_fato_no_prejuizo_continua_sendo_apontada():
    """O conserto não pode ter sido calar a análise.

    R$ 200 de venda com R$ 210 de custo: o produto sai abaixo do preço
    antes de qualquer custo fixo. Nenhuma convenção de DAS salva isto.
    """
    vendas = [_t("loja_propria", "200", "150") for _ in range(9)]
    vendas.append(_t("loja_propria", "200", "210"))

    achados = AnaliseVendasNoPrejuizo().avaliar(_ctx(vendas))
    assert len(achados) == 1
    assert achados[0].ganho_estimado_mensal > 0


def test_no_simples_o_caminho_ja_estava_certo_e_continua():
    """Ali todo custo por venda é variável de fato — nada mudou."""
    vendas = [_t("shopee", "200", "150") for _ in range(10)]
    assert AnaliseVendasNoPrejuizo().avaliar(_ctx(vendas, SIMPLES)) == []

    caras = vendas + [_t("shopee", "200", "400")]
    assert AnaliseVendasNoPrejuizo().avaliar(_ctx(caras, SIMPLES))


# ---------------------------------------------------------------------------
# (b) Mix de canais — o DAS é rateado
# ---------------------------------------------------------------------------


def test_economia_unitaria_identica_com_volumes_diferentes_nao_gera_oportunidade():
    """O teste que prova que o gap era artefato, e não sinal.

    Os dois canais vendem exatamente a mesma coisa pelo mesmo preço com
    o mesmo custo: R$ 1.000 com R$ 700 de custo, nenhuma comissão em
    nenhum dos dois. A ÚNICA diferença é volume — cinco vendas contra
    uma.

    Com o DAS inteiro em cada canal, o menor carregava os mesmos R$ 76
    sobre um quinto da receita: 26,48% contra 20,40%, gap de 6,08 p.p.
    sobre um limiar de 5. A análise disparava e mandava migrar vendas
    entre canais que rendem igual — e a recomendação se invertia se o
    volume se invertesse, que é a assinatura de um artefato.
    """
    vendas = [_t("loja_propria", "1000", "700") for _ in range(5)]
    vendas.append(_t("fisico", "1000", "700"))

    assert AnaliseMixCanais().avaliar(_ctx(vendas)) == []


def test_gap_de_canais_de_fato_real_continua_disparando():
    """Economia unitária diferente de verdade: a comissão da Shopee.

    Mesmo preço e mesmo custo nos dois, mas a Shopee leva 14% de
    comissão e a loja própria não leva nenhuma. O gap sobrevive a
    qualquer convenção de DAS porque não veio dele.
    """
    vendas = [_t("loja_propria", "1000", "700") for _ in range(3)]
    vendas += [_t("shopee", "1000", "700") for _ in range(3)]

    achados = AnaliseMixCanais().avaliar(_ctx(vendas))
    assert len(achados) == 1
    assert "shopee" in achados[0].titulo.lower()


def test_o_rateio_desloca_todo_canal_pelo_mesmo_tanto():
    """A propriedade que faz o rateio ser seguro para comparar.

    `DAS × share ÷ receita_do_grupo` é `DAS ÷ receita_total` para
    qualquer grupo — constante. Então o rateio não consegue inventar
    diferença entre canais; só multiplicar o DAS inventa.
    """
    from carchuna.margem import BASE_RATEADA, config_do_subconjunto

    vendas = [_t("loja_propria", "1000", "700") for _ in range(5)]
    vendas.append(_t("fisico", "1000", "700"))

    pcts = []
    for canal in ("loja_propria", "fisico"):
        grupo = [t for t in vendas if t.canal == canal]
        cfg = config_do_subconjunto(MEI, grupo, vendas, base=BASE_RATEADA)
        pcts.append(decompor_margem(grupo, cfg, TabelaCustos()).margem_pct)

    assert pcts[0] == pcts[1]
    # e a parte fica no mesmo pé do título da tela
    assert pcts[0] == decompor_margem(vendas, MEI, TabelaCustos()).margem_pct


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
