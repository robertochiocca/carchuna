""" "Cancelado" não diz o que foi cancelado — e as leituras se opõem.

O termo estava na lista dos negativos, junto com "recusado" e
"rejeitado", então todo cancelamento virava venda normal. Metade das
vezes isso está certo: "solicitação de devolução cancelada" quer dizer
que a venda ficou de pé.

A outra metade é o defeito. "Pedido cancelado" quer dizer que a venda
NUNCA aconteceu — e entrava na receita com CMV e comissão de uma venda
que não existiu, além de inflar a base do tributo, que por lei exclui a
venda cancelada (LC 123/2006, art. 3º, § 1º).

A saída não é escolher um dos dois lados por padrão. Quando o texto DIZ
o que foi cancelado, a leitura sai daí; quando não diz, o valor cai num
estado próprio e o lojista decide — a mesma regra do "Em análise".
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.dados import _devolvida_de
from carchuna.margem import ConfigTributaria, TabelaCustos, Transacao, decompor_margem
from carchuna.tipos import ESTADOS_DEVOLUCAO, interpretar_devolucao, resumo_devolucao

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


# ---------------------------------------------------------------------------
# Quando o texto diz o que foi cancelado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        "Pedido cancelado",
        "PEDIDO CANCELADO",
        "Venda cancelada",
        "Compra cancelada",
        "Order canceled",
        "Cancelado pelo comprador",
    ],
)
def test_pedido_cancelado_e_venda_que_nao_aconteceu(texto):
    """Antes virava venda normal: receita cheia, CMV e comissão de nada."""
    assert interpretar_devolucao(texto) == "devolvida"


@pytest.mark.parametrize(
    "texto",
    [
        "Solicitação de devolução cancelada",
        "Devolução cancelada",
        "Solicitação cancelada",
        "Reembolso cancelado",
        "Return canceled",
    ],
)
def test_devolucao_cancelada_deixa_a_venda_de_pe(texto):
    """Cancelar o PEDIDO DE DEVOLUÇÃO é o oposto de cancelar o pedido."""
    assert interpretar_devolucao(texto) == "nao_devolvida"


def test_a_ordem_dos_lexicos_e_o_que_faz_isso_funcionar():
    """ "Devolução cancelada" contém "cancelad" E "devolucao".

    Casaria com o lado errado em qualquer ordem que não seja a que está
    no código — este teste existe para a ordem não ser mexida por
    engano.
    """
    assert interpretar_devolucao("devolucao cancelada") == "nao_devolvida"
    assert interpretar_devolucao("pedido cancelado") == "devolvida"


# ---------------------------------------------------------------------------
# Quando o texto não diz
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("texto", ["Cancelado", "Cancelada", "CANCELED"])
def test_cancelamento_sem_objeto_ganha_estado_proprio(texto):
    """As duas leituras se opõem e nenhuma é dedutível do dado."""
    assert interpretar_devolucao(texto) == "cancelada"


def test_o_estado_novo_esta_no_lexico_publicado():
    """O mapeador do dashboard itera `ESTADOS_DEVOLUCAO` para agrupar."""
    assert "cancelada" in ESTADOS_DEVOLUCAO
    grupos = resumo_devolucao(["Cancelado", "Em análise", "Aprovada"])
    assert grupos["cancelada"] == ["Cancelado"]


def test_a_recusa_explica_as_duas_leituras_ao_lojista():
    """Mensagem que ensina a decidir, não que só diz "não sei"."""
    with pytest.raises(ValueError) as erro:
        _devolvida_de("Cancelado", 7, None)
    mensagem = str(erro.value)
    assert "linha 7" in mensagem
    assert "SOLICITAÇÃO DE DEVOLUÇÃO" in mensagem
    assert "PEDIDO" in mensagem


def test_a_decisao_do_usuario_continua_ganhando():
    """O mapeador sobrepõe qualquer inferência — inclusive esta."""
    assert _devolvida_de("Cancelado", 7, {"cancelado": True}) is True
    assert _devolvida_de("Cancelado", 7, {"cancelado": False}) is False


# ---------------------------------------------------------------------------
# O efeito na conta
# ---------------------------------------------------------------------------


def test_pedido_cancelado_sai_da_base_do_tributo():
    """Art. 3º, § 1º: venda cancelada não é receita bruta.

    Duas vendas de R$ 1.000, uma cancelada. Antes as duas eram tratadas
    como venda boa: tributo sobre R$ 2.000 e CMV das duas. Agora o
    tributo é sobre R$ 1.000 e o produto cancelado volta ao estoque.
    """
    vendas = [
        Transacao(
            data=date(2026, 5, 10),
            canal="shopee",
            valor_bruto=Decimal("1000"),
            custo_produto=Decimal("400"),
            frete_pago=Decimal("0"),
            devolvida=_devolvida_de(status, 1, None),
            devolucao_status=status,
        )
        for status in ("Solicitação recusada", "Pedido cancelado")
    ]
    d = decompor_margem(vendas, CONFIG, TabelaCustos())

    assert d.receita_bruta == Decimal("2000.00")
    assert d.deducao("devolucoes").valor == Decimal("1000.00")
    assert d.deducao("cmv").valor == Decimal("400.00")  # só a venda boa
    # tributo sobre R$ 1.000, e não sobre R$ 2.000
    assert d.deducao("tributos").valor == Decimal("56.50")


def test_o_status_original_fica_preservado():
    """A linhagem não pode perder o texto que o arquivo trazia."""
    t = Transacao(
        data=date(2026, 5, 10),
        canal="shopee",
        valor_bruto=Decimal("1000"),
        custo_produto=Decimal("400"),
        frete_pago=Decimal("0"),
        devolvida=_devolvida_de("Pedido cancelado", 1, None),
        devolucao_status="Pedido cancelado",
    )
    assert t.devolvida is True
    assert t.devolucao_status == "Pedido cancelado"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
