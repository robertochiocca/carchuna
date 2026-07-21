"""Testes do otimizador — a grade inteira conferida à mão.

Caso base (o clássico do projeto): venda ML de 100 com CMV 50 no Anexo I
@ 360k → margem 32,35 (32,35%). Com +5%: 36,47. Com +10%:
110 − 6,22 − 13,20 − 50 = 40,58.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.margem import ConfigTributaria, Transacao
from carchuna.otimizacao import (
    MotorOtimizacao,
    ParametrosOtimizacao,
    Restricoes,
)

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))

GRADE_PRECO = (Decimal("0"), Decimal("0.05"), Decimal("0.10"))


def _venda(valor="100", **kwargs):
    padrao = dict(
        data=date(2026, 5, 10),
        canal="mercado_livre",
        valor_bruto=Decimal(valor),
        custo_produto=Decimal("50"),
        frete_pago=Decimal("0"),
    )
    padrao.update(kwargs)
    return Transacao(**padrao)


def _motor(**kwargs):
    kwargs.setdefault("deltas_preco", GRADE_PRECO)
    kwargs.setdefault("fracoes_migracao", (Decimal("0"),))
    return MotorOtimizacao(ParametrosOtimizacao(**kwargs))


def test_sem_elasticidade_o_maior_preco_viavel_vence():
    # Volume constante: lucro cresce com o preço → vence +10% (40,58).
    r = _motor().otimizar([_venda()], CONFIG)
    assert r.base.lucro_mensal == Decimal("32.35")
    assert r.melhor.delta_preco == Decimal("0.10")
    assert r.melhor.lucro_mensal == Decimal("40.58")
    assert r.ganho_mensal == Decimal("8.23")
    assert len(r.candidatos) == 3  # a grade inteira está no resultado
    assert any("volume constante" in p for p in r.premissas)


def test_teto_de_preco_barra_o_candidato_e_a_explicacao_diz_por_que():
    # Ticket médio ≤ 105: o +10% (ticket 110) viola; vence +5% (36,47).
    r = _motor().otimizar(
        [_venda()], CONFIG, restricoes=Restricoes(preco_medio_maximo=Decimal("105"))
    )
    assert r.melhor.delta_preco == Decimal("0.05")
    assert r.melhor.lucro_mensal == Decimal("36.47")
    descartado = next(c for c in r.candidatos if not c.viavel)
    assert descartado.delta_preco == Decimal("0.10")
    assert "acima do teto" in descartado.violacoes[0]
    assert "1 violaram restrições" in r.explicacao


def test_elasticidade_do_usuario_cria_otimo_interior():
    # Elasticidade 2 (perde 2% de volume por +1% de preço):
    # +5%: 36,47 × 0,90 = 32,82 · +10%: 40,58 × 0,80 = 32,46 →
    # o ótimo é +5%, não o maior preço.
    r = _motor(elasticidade=Decimal("2")).otimizar([_venda()], CONFIG)
    assert r.melhor.delta_preco == Decimal("0.05")
    assert r.melhor.lucro_mensal == Decimal("32.82")
    assert r.melhor.fator_volume == Decimal("0.90")
    assert any("elasticidade informada" in p for p in r.premissas)


def test_queda_maxima_de_volume_como_restricao():
    # Elasticidade 2 e teto de queda 5%: +5% perde 10% de volume → viola;
    # +10% perde 20% → viola; só resta a base (0%).
    r = _motor(elasticidade=Decimal("2")).otimizar(
        [_venda()],
        CONFIG,
        restricoes=Restricoes(queda_maxima_volume=Decimal("0.05")),
    )
    assert r.melhor.delta_preco == Decimal("0")
    assert r.ganho_mensal == Decimal("0.00")


def test_margem_minima_pode_inviabilizar_tudo():
    # Margem mínima de 50%: nenhum candidato chega lá (máx. 36,89% a +10%).
    r = _motor().otimizar(
        [_venda()], CONFIG, restricoes=Restricoes(margem_minima_pct=Decimal("50"))
    )
    assert r.melhor is None
    assert "Nenhum dos 3 candidatos" in r.explicacao


def test_migracao_de_canal_entra_na_grade_quando_ha_ml():
    # Migrar 100% da venda ML para loja própria: comissão 12 → some,
    # adquirência 2% entra → margem 100 − 5,65 − 2 − 50 = 42,35 > 32,35.
    motor = MotorOtimizacao(
        ParametrosOtimizacao(
            deltas_preco=(Decimal("0"),),
            fracoes_migracao=(Decimal("0"), Decimal("1")),
        )
    )
    r = motor.otimizar([_venda()], CONFIG)
    assert r.melhor.fracao_migracao == Decimal("1")
    assert r.melhor.lucro_mensal == Decimal("42.35")
    # sem vendas de ML, a alavanca de migração sai da grade sozinha
    so_fisico = [_venda(canal="fisico")]
    r2 = motor.otimizar(so_fisico, CONFIG)
    assert {c.fracao_migracao for c in r2.candidatos} == {Decimal("0")}


def test_determinismo_e_validacao():
    a = _motor().otimizar([_venda()], CONFIG)
    b = _motor().otimizar([_venda()], CONFIG)
    assert a == b  # mesma grade, mesmo resultado, sempre
    with pytest.raises(ValueError):
        _motor().otimizar([], CONFIG)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
