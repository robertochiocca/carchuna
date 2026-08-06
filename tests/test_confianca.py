"""Nota de confiança: a rubrica inteira conferida à mão.

A nota só vale alguma coisa se cada ponto dela puder ser reconstruído sem
rodar o código. Por isso cada caso aqui traz a conta escrita: componente
por componente, com o total fechando no fim.

Os testes vieram do arquivo em que a rubrica nasceu acoplada ao motor de
decisão; aqui ela é testada sozinha, que é como ela é usada.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.confianca import FRASE_DADOS, FRASE_HIPOTESE, avaliar_confianca
from carchuna.margem import Transacao


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


def test_cada_componente_carrega_o_motivo_em_texto():
    """Nota sem motivo é número mágico — o que a rubrica existe para evitar."""
    nota = avaliar_confianca(BASE_PEQUENA, base="estimado")
    por_nome = {c.nome: c for c in nota.componentes}

    assert "premissa" in por_nome["evidencia"].motivo
    assert "2 mês(es) de histórico" in por_nome["historico"].motivo
    assert "2 venda(s) na base" in por_nome["amostra"].motivo
    # a completude diz QUAL campo faltou, não só o percentual
    completude = por_nome["completude"].motivo
    assert "comissão real: 2/2" in completude
    assert "produto: 0/2" in completude
    assert "prazo: 0/2" in completude

    assert nota.motivos == tuple(c.motivo for c in nota.componentes)
    # o total é a soma dos componentes, não um número à parte
    assert nota.pct == sum(c.pontos for c in nota.componentes)
    assert all(c.pontos <= c.maximo for c in nota.componentes)


def test_as_faixas_de_historico_e_amostra_batem_com_a_rubrica():
    """Os degraus documentados no módulo, um a um."""

    def historico(meses):
        vendas = [
            _venda(m, comissao_cobrada=Decimal("12")) for m in range(1, meses + 1)
        ]
        nota = avaliar_confianca(vendas, base="calculado")
        return next(c.pontos for c in nota.componentes if c.nome == "historico")

    assert historico(1) == 3
    assert historico(2) == 6
    assert historico(3) == 10
    assert historico(6) == 15
    assert historico(12) == 20

    def amostra(n):
        vendas = [_venda(5) for _ in range(n)]
        nota = avaliar_confianca(vendas, base="calculado")
        return next(c.pontos for c in nota.componentes if c.nome == "amostra")

    assert amostra(1) == 5
    assert amostra(12) == 10
    assert amostra(50) == 15
    assert amostra(200) == 20


def test_o_nivel_muda_exatamente_nos_limiares_de_80_e_55():
    """≥80 alta · ≥55 média · <55 baixa — sem zona cinzenta."""
    # 12 meses, 240 vendas, tudo preenchido, mas evidência estimada: 85 → alta
    completas = [
        _venda(
            m, comissao_cobrada=Decimal("12"), produto="Fone", prazo_recebimento_dias=14
        )
        for m in range(1, 13)
        for _ in range(20)
    ]
    assert avaliar_confianca(completas, base="estimado").nivel == "alta"

    # 1 mês, 1 venda, nada opcional preenchido: 40 + 3 + 5 + 0 = 48 → baixa
    magra = avaliar_confianca([_venda(5)], base="calculado")
    assert magra.pct == 48
    assert magra.nivel == "baixa"
    assert magra.frase == FRASE_HIPOTESE


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
