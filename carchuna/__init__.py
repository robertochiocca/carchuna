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
from carchuna.anomalias import Anomalia, MotorAnomalias, ParametrosAnomalias
from carchuna.benchmarks import Benchmark, comparar_benchmarks
from carchuna.caixa import (
    InteligenciaCaixa,
    JanelaCaixa,
    ProjecaoCaixa,
    agenda_recebimentos,
    analisar_caixa,
    projetar_caixa,
    valor_liquido_recebivel,
)
from carchuna.cenarios import (
    Cenario,
    CenarioAntecipacao,
    CenarioComissao,
    CenarioCrescimentoCanal,
    CenarioDevolucoesDobram,
    CenarioMigracaoCanal,
    CenarioMudancaAnexo,
    CenarioPreco,
    ResultadoCenario,
    cenario_antecipacao,
    cenario_comissao,
    cenario_devolucoes_dobram,
    cenario_migracao_canal,
    cenario_mudanca_anexo,
    rodar_cenarios_padrao,
)
from carchuna.confianca import NotaConfianca, avaliar_confianca
from carchuna.copiloto import Copiloto, RespostaCopiloto, explicar_variacao
from carchuna.crescimento import (
    MotorCrescimento,
    Oportunidade,
    ParametrosCrescimento,
    preco_para_margem,
)
from carchuna.dados import carregar_transacoes, transacoes_sinteticas
from carchuna.decisao import MotorDecisao, Recomendacao, recomendar
from carchuna.diagnostico import (
    Achado,
    MotorDiagnostico,
    ParametrosDiagnostico,
    RegraDeteccao,
    diagnosticar,
)
from carchuna.insights import Insight, MotorInsights, ParametrosInsights
from carchuna.linhagem import Linhagem
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
from carchuna.otimizacao import (
    MotorOtimizacao,
    ParametrosOtimizacao,
    Restricoes,
    ResultadoOtimizacao,
)
from carchuna.tipos import (
    TipoColuna,
    inferir_tipo_coluna,
    interpretar_devolucao,
    resumo_devolucao,
)

__version__ = "1.1.0"

__all__ = [
    "ANEXOS_SIMPLES",
    "ROTULOS_DEDUCOES",
    "Achado",
    "AnalisadorMargem",
    "Anomalia",
    "Benchmark",
    "Copiloto",
    "InteligenciaCaixa",
    "JanelaCaixa",
    "Linhagem",
    "MotorAnomalias",
    "MotorDecisao",
    "MotorOtimizacao",
    "NotaConfianca",
    "ParametrosAnomalias",
    "ParametrosOtimizacao",
    "Recomendacao",
    "RespostaCopiloto",
    "Restricoes",
    "ResultadoOtimizacao",
    "Cenario",
    "CenarioAntecipacao",
    "CenarioComissao",
    "CenarioCrescimentoCanal",
    "CenarioDevolucoesDobram",
    "CenarioMigracaoCanal",
    "CenarioMudancaAnexo",
    "CenarioPreco",
    "ConfigTributaria",
    "DecomposicaoMargem",
    "Deducao",
    "FontePerda",
    "Insight",
    "MargemVenda",
    "MotorCrescimento",
    "MotorDiagnostico",
    "MotorInsights",
    "Oportunidade",
    "ParametrosCrescimento",
    "ParametrosDiagnostico",
    "ParametrosInsights",
    "ProjecaoCaixa",
    "RegraDeteccao",
    "ResultadoCenario",
    "ResumoExecutivo",
    "TabelaCustos",
    "TipoColuna",
    "Transacao",
    "agenda_recebimentos",
    "aliquota_efetiva_simples",
    "analisar_caixa",
    "avaliar_confianca",
    "carregar_transacoes",
    "comparar_benchmarks",
    "explicar_variacao",
    "recomendar",
    "resumo_devolucao",
    "cenario_antecipacao",
    "cenario_comissao",
    "cenario_devolucoes_dobram",
    "cenario_migracao_canal",
    "cenario_mudanca_anexo",
    "decompor_margem",
    "diagnosticar",
    "inferir_tipo_coluna",
    "instabilidade_margem",
    "interpretar_devolucao",
    "lucro_acumulado",
    "maior_queda_margem",
    "margem_mensal",
    "preco_para_margem",
    "projetar_caixa",
    "rodar_cenarios_padrao",
    "serie_margem_pct",
    "transacoes_sinteticas",
    "valor_liquido_recebivel",
]
