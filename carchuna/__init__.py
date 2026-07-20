"""Carchuna — inteligência de margem verificável para o PME brasileiro.

Você fatura 400; a Carchuna mostra, com prova, por que sobra 8 — e o que
a lei permite recuperar.
"""

from carchuna.analise import (
    AnalisadorMargem,
    FontePerda,
    MargemVenda,
    ResumoExecutivo,
)
from carchuna.cenarios import (
    Cenario,
    CenarioAntecipacao,
    CenarioComissao,
    CenarioCrescimentoCanal,
    CenarioDevolucoesDobram,
    CenarioMigracaoCanal,
    CenarioMudancaAnexo,
    ResultadoCenario,
    cenario_antecipacao,
    cenario_comissao,
    cenario_devolucoes_dobram,
    cenario_migracao_canal,
    cenario_mudanca_anexo,
    rodar_cenarios_padrao,
)
from carchuna.crescimento import (
    MotorCrescimento,
    Oportunidade,
    ParametrosCrescimento,
    preco_para_margem,
)
from carchuna.dados import carregar_transacoes, transacoes_sinteticas
from carchuna.diagnostico import (
    Achado,
    MotorDiagnostico,
    ParametrosDiagnostico,
    RegraDeteccao,
    diagnosticar,
)
from carchuna.margem import (
    ANEXOS_SIMPLES,
    ROTULOS_DEDUCOES,
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

__version__ = "1.1.0"

__all__ = [
    "ANEXOS_SIMPLES",
    "ROTULOS_DEDUCOES",
    "Achado",
    "AnalisadorMargem",
    "Cenario",
    "CenarioAntecipacao",
    "CenarioComissao",
    "CenarioCrescimentoCanal",
    "CenarioDevolucoesDobram",
    "CenarioMigracaoCanal",
    "CenarioMudancaAnexo",
    "ConfigTributaria",
    "DecomposicaoMargem",
    "Deducao",
    "FontePerda",
    "MargemVenda",
    "MotorCrescimento",
    "MotorDiagnostico",
    "Oportunidade",
    "ParametrosCrescimento",
    "ParametrosDiagnostico",
    "RegraDeteccao",
    "ResultadoCenario",
    "ResumoExecutivo",
    "TabelaCustos",
    "Transacao",
    "aliquota_efetiva_simples",
    "carregar_transacoes",
    "cenario_antecipacao",
    "cenario_comissao",
    "cenario_devolucoes_dobram",
    "cenario_migracao_canal",
    "cenario_mudanca_anexo",
    "decompor_margem",
    "diagnosticar",
    "instabilidade_margem",
    "lucro_acumulado",
    "maior_queda_margem",
    "margem_mensal",
    "preco_para_margem",
    "rodar_cenarios_padrao",
    "serie_margem_pct",
    "transacoes_sinteticas",
]
