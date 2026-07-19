"""Carchuna — o raio-X verificável da margem para o PME brasileiro.

Você fatura 400; a Carchuna mostra, com prova, por que sobra 8 — e o que
a lei permite recuperar.
"""

from carchuna.dados import carregar_transacoes, transacoes_sinteticas
from carchuna.margem import (
    ANEXOS_SIMPLES,
    ConfigTributaria,
    DecomposicaoMargem,
    Deducao,
    TabelaCustos,
    Transacao,
    aliquota_efetiva_simples,
    decompor_margem,
)

__version__ = "1.0.0"

__all__ = [
    "ANEXOS_SIMPLES",
    "ConfigTributaria",
    "DecomposicaoMargem",
    "Deducao",
    "TabelaCustos",
    "Transacao",
    "aliquota_efetiva_simples",
    "carregar_transacoes",
    "decompor_margem",
    "transacoes_sinteticas",
]
