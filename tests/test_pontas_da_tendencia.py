"""A tendência de custos pendurava tudo em duas pontas frágeis.

`TendenciaCustos` compara o percentual de uma dedução no primeiro mês
com o do último e chama a diferença de inclinação. É o detector do
vazamento mais caro que existe — o custo que sobe devagar e nunca é
anômalo em mês nenhum. Mas ele lia as duas pontas sem perguntar de que
eram feitas.

Ponta de três vendas não tem percentual estável: uma venda atípica
desloca a fatia de um custo em pontos inteiros, e a tela publicava
"comissão subiu 8 pontos, crítico" para o acaso de um mês magro.

Ponta cortada ao meio é outro problema: o mês que só tem a primeira
quinzena carrega o mix daquela quinzena, e mix move fatia de custo.

Os dois recebem tratamento diferente de propósito, e a diferença está
explicada em `test_ponta_parcial_rebaixa_em_vez_de_silenciar`.
"""

import calendar
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.insights import (
    ContextoInsights,
    ParametrosInsights,
    TendenciaCustos,
)
from carchuna.margem import ConfigTributaria, TabelaCustos, Transacao

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _vendas(mes, comissao, n=10, primeiro_dia=1, ultimo_dia=None, total="1000"):
    """`n` vendas somando `total`, com a comissão pedida, entre dois dias."""
    fim = ultimo_dia or calendar.monthrange(2026, mes)[1]
    fatia = Decimal(total) / n
    por_venda = Decimal(comissao) / n
    return [
        Transacao(
            data=date(2026, mes, primeiro_dia + (i * (fim - primeiro_dia)) // (n - 1)),
            canal="mercado_livre",
            valor_bruto=fatia,
            custo_produto=Decimal("0"),
            frete_pago=Decimal("0"),
            comissao_cobrada=por_venda,
        )
        for i in range(n)
    ]


def _ctx(vendas, **kwargs):
    return ContextoInsights(
        transacoes=vendas,
        config=CONFIG,
        tabela=TabelaCustos(),
        parametros=ParametrosInsights(**kwargs),
    )


def _alta_de_8pp(**kwargs):
    """Comissão de 12% para 20% da receita: 8 p.p., bem acima do crítico."""
    return _vendas(5, "120", **kwargs) + _vendas(6, "200", **kwargs)


# ---------------------------------------------------------------------------
# Volume na ponta
# ---------------------------------------------------------------------------


def test_ponta_com_poucas_vendas_silencia_o_sinal():
    """Três vendas num mês não têm percentual, têm acaso.

    O sinal é idêntico ao do caso denso — 8 p.p. de alta de comissão —,
    e é justamente esse o ponto: o número não distingue os dois, só o
    volume da ponta distingue.
    """
    ralas = _vendas(5, "120", n=3) + _vendas(6, "200", n=3)
    assert TendenciaCustos().avaliar(_ctx(ralas)) == []


def test_a_ponta_densa_continua_falando():
    (i,) = TendenciaCustos().avaliar(_ctx(_alta_de_8pp()))
    assert i.severidade == "critico"
    assert "8.00 p.p." in i.titulo


def test_basta_UMA_das_pontas_ser_rala():
    """A inclinação tem dois apoios; um frouxo derruba a reta inteira."""
    so_o_comeco_ralo = _vendas(5, "120", n=3) + _vendas(6, "200", n=10)
    assert TendenciaCustos().avaliar(_ctx(so_o_comeco_ralo)) == []

    so_o_fim_ralo = _vendas(5, "120", n=10) + _vendas(6, "200", n=3)
    assert TendenciaCustos().avaliar(_ctx(so_o_fim_ralo)) == []


def test_o_mes_do_meio_ralo_nao_atrapalha():
    """Só as pontas entram na conta — o meio não é comparado com nada."""
    vendas = _vendas(5, "120") + _vendas(6, "150", n=2) + _vendas(7, "200")
    assert TendenciaCustos().avaliar(_ctx(vendas))


def test_o_minimo_e_parametro_e_nao_numero_solto_no_meio_do_codigo():
    """Quem opera com poucas vendas grandes pode baixar o corte."""
    ralas = _vendas(5, "120", n=3) + _vendas(6, "200", n=3)
    assert TendenciaCustos().avaliar(_ctx(ralas, min_vendas_tendencia=3))


def test_na_fronteira_exata_o_sinal_passa():
    """Dez vendas é o mínimo, não o primeiro valor recusado."""
    assert TendenciaCustos().avaliar(_ctx(_alta_de_8pp(n=10)))
    assert (
        TendenciaCustos().avaliar(_ctx(_vendas(5, "120", n=9) + _vendas(6, "200")))
        == []
    )


# ---------------------------------------------------------------------------
# Mês cortado ao meio
# ---------------------------------------------------------------------------


def test_ponta_parcial_rebaixa_em_vez_de_silenciar():
    """A escolha que separa este caso do anterior, e o porquê dela.

    O arquivo termina no dia 10 de junho. Isso é a regra, não a exceção:
    quase todo export real termina no meio do mês, porque o lojista
    exporta no dia em que abre a Carchuna. Silenciar por mês parcial
    desligaria este detector em praticamente toda base de verdade —
    trocaria ruído a menos por detector a menos, no vazamento mais caro
    que existe.

    Rebaixar diz a coisa certa: o sinal é real, a intensidade dele é que
    não está confirmada.
    """
    cortado = _vendas(5, "120") + _vendas(6, "200", ultimo_dia=10)
    (i,) = TendenciaCustos().avaliar(_ctx(cortado))

    assert i.severidade == "atencao"  # seria "critico" com o mês inteiro
    assert "8.00 p.p." in i.titulo  # o número não muda, só o carimbo


def test_o_comeco_cortado_rebaixa_do_mesmo_jeito():
    cortado = _vendas(5, "120", primeiro_dia=12) + _vendas(6, "200")
    (i,) = TendenciaCustos().avaliar(_ctx(cortado))
    assert i.severidade == "atencao"


def test_o_motivo_do_rebaixamento_fica_escrito_no_metodo():
    """Severidade que muda sem explicação é severidade que ninguém confere."""
    cortado = _vendas(5, "120") + _vendas(6, "200", ultimo_dia=10)
    (i,) = TendenciaCustos().avaliar(_ctx(cortado))
    assert "rebaixado a atenção" in i.metodo
    assert "corta ao meio" in i.metodo


def test_o_rebaixamento_nao_promove_o_que_ja_era_atencao():
    """Rebaixar é um caminho só: de crítico para atenção, nunca ao contrário."""
    cortado = _vendas(5, "120") + _vendas(6, "140", ultimo_dia=10)
    (i,) = TendenciaCustos().avaliar(_ctx(cortado))
    assert i.severidade == "atencao"
    assert "2.00 p.p." in i.titulo


def test_mes_inteiro_nos_dois_lados_nao_menciona_rebaixamento():
    """Aviso que aparece sempre deixa de ser aviso."""
    (i,) = TendenciaCustos().avaliar(_ctx(_alta_de_8pp()))
    assert "rebaixado" not in i.metodo


def test_o_ultimo_dia_do_mes_e_perguntado_ao_calendario():
    """Fevereiro é o teste; maio e junho não separam nada.

    Um número fixo de 30 ou 31 passa despercebido em quase todo mês do
    ano — e rebaixa em silêncio todo arquivo que fecha em fevereiro, que
    termina no dia 28. O mês curto é o único que denuncia a diferença
    entre perguntar ao calendário e chutar.
    """
    fevereiro = _vendas(1, "120") + _vendas(2, "200", ultimo_dia=28)
    (i,) = TendenciaCustos().avaliar(_ctx(fevereiro))
    assert i.severidade == "critico"  # 2026 não é bissexto: fevereiro fecha em 28

    # e o mês longo continua exigindo o dia 31
    maio = _vendas(4, "120") + _vendas(5, "200", ultimo_dia=30)
    (j,) = TendenciaCustos().avaliar(_ctx(maio))
    assert j.severidade == "atencao"  # maio tem 31 dias: o arquivo parou antes


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
