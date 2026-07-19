"""Carchuna — o raio-X verificável da margem para o PME brasileiro.

Você fatura 400; a Carchuna mostra, com prova, por que sobra 8 — e o que
a lei permite recuperar.
"""

from carchuna.cenarios import (
    ResultadoCenario,
    cenario_antecipacao,
    cenario_comissao,
    cenario_devolucoes_dobram,
    cenario_mudanca_anexo,
    rodar_cenarios_padrao,
)
from carchuna.dados import carregar_transacoes, transacoes_sinteticas
from carchuna.diagnostico import (
    Achado,
    ParametrosDiagnostico,
    diagnosticar,
)
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
from carchuna.metricas import (
    instabilidade_margem,
    lucro_acumulado,
    maior_queda_margem,
    margem_mensal,
    serie_margem_pct,
)

__version__ = "1.0.0"

__all__ = [
    "ANEXOS_SIMPLES",
    "Achado",
    "ConfigTributaria",
    "DecomposicaoMargem",
    "Deducao",
    "ParametrosDiagnostico",
    "ResultadoCenario",
    "TabelaCustos",
    "Transacao",
    "aliquota_efetiva_simples",
    "carregar_transacoes",
    "cenario_antecipacao",
    "cenario_comissao",
    "cenario_devolucoes_dobram",
    "cenario_mudanca_anexo",
    "decompor_margem",
    "diagnosticar",
    "instabilidade_margem",
    "lucro_acumulado",
    "maior_queda_margem",
    "margem_mensal",
    "rodar_cenarios_padrao",
    "serie_margem_pct",
    "transacoes_sinteticas",
]
