"""Motor de decisão: "qual problema devo resolver primeiro?".

Não cria diagnóstico novo — consome o que os motores existentes já
produzem (achados do diagnóstico legal, sinais do radar de insights e
oportunidades de crescimento) e transforma cada um em uma
:class:`Recomendacao` priorizada.

O fluxo é o do CFO: problema detectado → impacto financeiro → ação →
esforço → confiança → prioridade. A priorização é uma fórmula aberta,
sem caixa preta::

    pontuação = impacto (R$/mês)
                × confiança (0–1, rubrica do confianca.py)
                × fator de esforço × fator de velocidade
                × fator de risco × fator de reversibilidade

Os fatores vêm de tabelas fixas documentadas abaixo (1,00 = não penaliza;
quanto menor, mais a dimensão desconta). Cada recomendação carrega a
``justificativa`` com a conta armada — o usuário vê POR QUE uma ação
ficou acima da outra, e pode discordar dos fatores (eles são parâmetros).

O perfil de cada ação (esforço/velocidade/risco/reversibilidade) vem de
um catálogo por tipo de problema — avaliação editorial documentada, não
medida; por isso a pontuação é régua de ORDENAÇÃO, não previsão.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal

from carchuna.confianca import NotaConfianca, avaliar_confianca
from carchuna.crescimento import MotorCrescimento, Oportunidade
from carchuna.diagnostico import Achado, MotorDiagnostico
from carchuna.insights import Insight, MotorInsights
from carchuna.margem import ConfigTributaria, TabelaCustos, Transacao

# Fatores de desconto da pontuação (1,00 = não desconta). Editáveis via
# ParametrosDecisao; os defaults expressam preferência por ações rápidas,
# fáceis, seguras e reversíveis — a régua clássica de priorização.
FATOR_ESFORCO = {
    "baixo": Decimal("1.00"),
    "medio": Decimal("0.80"),
    "alto": Decimal("0.60"),
}
FATOR_VELOCIDADE = {
    "dias": Decimal("1.00"),
    "semanas": Decimal("0.90"),
    "meses": Decimal("0.75"),
}
FATOR_RISCO = {
    "baixo": Decimal("1.00"),
    "medio": Decimal("0.85"),
    "alto": Decimal("0.65"),
}
FATOR_REVERSIBILIDADE = {
    "reversivel": Decimal("1.00"),
    "parcial": Decimal("0.90"),
    "irreversivel": Decimal("0.75"),
}


@dataclass(frozen=True)
class PerfilAcao:
    """Como uma ação se comporta: esforço, velocidade, risco, reversibilidade."""

    acao: str
    esforco: str  # "baixo" | "medio" | "alto"
    velocidade: str  # "dias" | "semanas" | "meses"
    risco: str  # "baixo" | "medio" | "alto"
    reversibilidade: str  # "reversivel" | "parcial" | "irreversivel"


# Catálogo editorial: perfil da ação típica para cada tipo de problema
# que os motores existentes detectam. Chave = (origem, tipo/categoria).
CATALOGO_ACOES: dict[tuple[str, str], PerfilAcao] = {
    ("diagnostico", "tributario"): PerfilAcao(
        "Revisar o enquadramento com o contador e, se confirmado, pedir restituição",
        esforco="medio",
        velocidade="semanas",
        risco="baixo",
        reversibilidade="reversivel",
    ),
    ("diagnostico", "financeiro"): PerfilAcao(
        "Cotar a antecipação em 2–3 instituições e trocar pela taxa menor",
        esforco="baixo",
        velocidade="dias",
        risco="baixo",
        reversibilidade="reversivel",
    ),
    ("diagnostico", "operacional"): PerfilAcao(
        "Atacar as causas das devoluções, canal a canal",
        esforco="medio",
        velocidade="semanas",
        risco="baixo",
        reversibilidade="reversivel",
    ),
    ("diagnostico", "contratual"): PerfilAcao(
        "Conferir o plano contratado e contestar a cobrança no canal",
        esforco="medio",
        velocidade="semanas",
        risco="baixo",
        reversibilidade="reversivel",
    ),
    ("radar", "tendencia_custos"): PerfilAcao(
        "Localizar a origem da alta (drill-down) e renegociar ou reprecificar",
        esforco="medio",
        velocidade="semanas",
        risco="baixo",
        reversibilidade="reversivel",
    ),
    ("radar", "margem_magra"): PerfilAcao(
        "Reprecificar os produtos de margem magra (calculadora da aba Crescer)",
        esforco="baixo",
        velocidade="dias",
        risco="medio",
        reversibilidade="reversivel",
    ),
    ("radar", "mes_fora_padrao"): PerfilAcao(
        "Investigar o que mudou no mês fora do padrão (aba Histórico)",
        esforco="baixo",
        velocidade="dias",
        risco="baixo",
        reversibilidade="reversivel",
    ),
    ("crescimento", "mix_canais"): PerfilAcao(
        "Deslocar esforço de venda para o canal onde cada real rende mais",
        esforco="medio",
        velocidade="semanas",
        risco="medio",
        reversibilidade="reversivel",
    ),
    ("crescimento", "precificacao"): PerfilAcao(
        "Reprecificar (ou tirar do catálogo) os itens que saem no prejuízo",
        esforco="baixo",
        velocidade="dias",
        risco="medio",
        reversibilidade="reversivel",
    ),
    ("crescimento", "espaco_tributario"): PerfilAcao(
        "Planejar o crescimento dentro da faixa do Simples com o contador",
        esforco="medio",
        velocidade="meses",
        risco="baixo",
        reversibilidade="reversivel",
    ),
}

# Quando o tipo não está no catálogo (regra nova de terceiros, por
# exemplo), a ação vira o caminho prático do próprio item, com perfil
# neutro-conservador.
PERFIL_PADRAO = PerfilAcao(
    "", esforco="medio", velocidade="semanas", risco="medio", reversibilidade="parcial"
)


@dataclass
class ParametrosDecisao:
    """Fatores da fórmula de prioridade — editáveis, nunca escondidos."""

    fator_esforco: dict[str, Decimal] = field(
        default_factory=lambda: dict(FATOR_ESFORCO)
    )
    fator_velocidade: dict[str, Decimal] = field(
        default_factory=lambda: dict(FATOR_VELOCIDADE)
    )
    fator_risco: dict[str, Decimal] = field(default_factory=lambda: dict(FATOR_RISCO))
    fator_reversibilidade: dict[str, Decimal] = field(
        default_factory=lambda: dict(FATOR_REVERSIBILIDADE)
    )


@dataclass(frozen=True)
class Recomendacao:
    """Uma ação priorizada: problema, impacto, confiança, perfil e o porquê."""

    prioridade: int  # 1 = resolver primeiro
    origem: str  # "diagnostico" | "radar" | "crescimento"
    tipo: str
    problema: str  # título do problema detectado
    acao: str  # o que fazer
    caminho_pratico: str  # como fazer (do motor de origem)
    impacto_mensal: Decimal  # R$/mês
    confianca: NotaConfianca
    esforco: str
    velocidade: str
    risco: str
    reversibilidade: str
    pontuacao: Decimal
    justificativa: str  # a conta da pontuação, armada


def _q2(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class MotorDecisao:
    """Consolida os três motores em UMA fila de ação priorizada."""

    def __init__(self, parametros: ParametrosDecisao | None = None):
        self.parametros = parametros or ParametrosDecisao()

    def _pontuar(
        self, impacto: Decimal, nota: NotaConfianca, perfil: PerfilAcao
    ) -> tuple[Decimal, str]:
        p = self.parametros
        fe = p.fator_esforco[perfil.esforco]
        fv = p.fator_velocidade[perfil.velocidade]
        fr = p.fator_risco[perfil.risco]
        frev = p.fator_reversibilidade[perfil.reversibilidade]
        confianca = Decimal(nota.pct) / 100
        pontuacao = _q2(impacto * confianca * fe * fv * fr * frev)
        justificativa = (
            f"R$ {impacto}/mês de impacto × {nota.pct}% de confiança × "
            f"{fe} (esforço {perfil.esforco}) × {fv} (resultado em "
            f"{perfil.velocidade}) × {fr} (risco {perfil.risco}) × "
            f"{frev} ({perfil.reversibilidade}) = {pontuacao} pontos"
        )
        return pontuacao, justificativa

    def _montar(
        self,
        origem: str,
        tipo: str,
        problema: str,
        caminho: str,
        impacto: Decimal,
        base_confianca: str,
        transacoes: list[Transacao],
    ) -> Recomendacao:
        perfil = CATALOGO_ACOES.get((origem, tipo), PERFIL_PADRAO)
        acao = perfil.acao or caminho
        nota = avaliar_confianca(transacoes, base=base_confianca)
        pontuacao, justificativa = self._pontuar(impacto, nota, perfil)
        return Recomendacao(
            prioridade=0,  # atribuída na ordenação final
            origem=origem,
            tipo=tipo,
            problema=problema,
            acao=acao,
            caminho_pratico=caminho,
            impacto_mensal=impacto,
            confianca=nota,
            esforco=perfil.esforco,
            velocidade=perfil.velocidade,
            risco=perfil.risco,
            reversibilidade=perfil.reversibilidade,
            pontuacao=pontuacao,
            justificativa=justificativa,
        )

    def recomendar(
        self,
        transacoes: list[Transacao],
        achados: list[Achado],
        insights: list[Insight],
        oportunidades: list[Oportunidade],
    ) -> list[Recomendacao]:
        """A fila de ação: recomendações ordenadas por pontuação decrescente."""
        if not transacoes:
            raise ValueError("`transacoes` não pode ser vazio.")
        itens: list[Recomendacao] = []
        for a in achados:
            itens.append(
                self._montar(
                    "diagnostico",
                    a.tipo,
                    a.titulo,
                    a.caminho_pratico,
                    a.impacto_mensal,
                    a.confianca,
                    transacoes,
                )
            )
        for i in insights:
            itens.append(
                self._montar(
                    "radar",
                    i.categoria,
                    i.titulo,
                    i.caminho_pratico,
                    i.impacto_mensal,
                    i.confianca,
                    transacoes,
                )
            )
        for o in oportunidades:
            itens.append(
                self._montar(
                    "crescimento",
                    o.tipo,
                    o.titulo,
                    o.caminho_pratico,
                    o.ganho_estimado_mensal,
                    o.confianca,
                    transacoes,
                )
            )
        itens.sort(key=lambda r: (-r.pontuacao, -r.impacto_mensal, r.problema))
        return [replace(r, prioridade=n) for n, r in enumerate(itens, start=1)]


def recomendar(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
    motor_diagnostico: MotorDiagnostico | None = None,
) -> list[Recomendacao]:
    """Atalho: roda os três motores existentes e prioriza tudo junto."""
    tabela = tabela or TabelaCustos()
    diag = motor_diagnostico or MotorDiagnostico()
    achados = diag.diagnosticar(transacoes, config, tabela)
    insights = MotorInsights().radar(transacoes, config, tabela)
    oportunidades = MotorCrescimento(retriever=diag.retriever).sugerir(
        transacoes, config, tabela
    )
    return MotorDecisao().recomendar(transacoes, achados, insights, oportunidades)
