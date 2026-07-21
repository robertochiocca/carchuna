"""Projeção de caixa: a agenda de recebíveis que as vendas já criaram.

Lucro no papel não paga boleto — uma empresa lucrativa quebra sem caixa.
Este módulo projeta o fôlego financeiro combinando duas fontes, cada uma
com a sua etiqueta de confiança:

- **Recebimentos (calculado)** — cada venda a prazo já feita tem data
  prevista de repasse (``data + prazo_recebimento_dias``) e valor
  líquido estimável (bruto − comissão do canal − adquirência, quando
  aplicável). Isso é agenda, não previsão.
- **Saídas (estimado)** — a planilha de vendas não sabe quanto você paga
  de aluguel, salário e fornecedor; o usuário informa uma saída mensal
  média, diluída linearmente por dia (simplificação documentada).

Honestidade inegociável: NADA aqui prevê vendas futuras — previsão de
demanda é roadmap explícito. A projeção enxerga só o que as vendas já
realizadas vão depositar, contra as saídas informadas. O DAS do Simples
é pago à parte (não sai do repasse), então inclua-o nas saídas mensais.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from carchuna.margem import TabelaCustos, Transacao


def _q2(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def valor_liquido_recebivel(t: Transacao, tabela: TabelaCustos) -> Decimal:
    """Quanto desta venda cai na conta: bruto − comissão − adquirência.

    Usa a comissão real do extrato quando informada; senão, a tabela do
    canal. Devoluções não geram recebível. O custo de antecipação não é
    descontado aqui: a agenda mostra o repasse no prazo NORMAL — antecipar
    é uma decisão à parte (e o custo dela aparece na margem).
    """
    if t.devolvida:
        return Decimal("0.00")
    if t.comissao_cobrada is not None:
        comissao = t.comissao_cobrada
    else:
        comissao = t.valor_bruto * tabela.comissao_canal.get(t.canal, Decimal("0"))
    adquirencia = (
        t.valor_bruto * tabela.taxa_adquirencia
        if t.canal in tabela.canais_com_adquirencia
        else Decimal("0")
    )
    return _q2(t.valor_bruto - comissao - adquirencia)


def agenda_recebimentos(
    transacoes: list[Transacao],
    tabela: TabelaCustos | None = None,
    a_partir_de: date | None = None,
) -> list[tuple[date, Decimal]]:
    """Datas e valores líquidos que as vendas já feitas vão depositar.

    ``a_partir_de`` filtra o passado (default: a data da última venda —
    o "hoje" do arquivo). Devolve pares (data, total do dia) ordenados.
    """
    if not transacoes:
        raise ValueError("`transacoes` não pode ser vazio.")
    tabela = tabela or TabelaCustos()
    hoje = a_partir_de or max(t.data for t in transacoes)
    por_dia: dict[date, Decimal] = {}
    for t in transacoes:
        liquido = valor_liquido_recebivel(t, tabela)
        if liquido == 0:
            continue
        quando = t.data + timedelta(days=t.prazo_recebimento_dias)
        if quando < hoje:
            continue  # já caiu na conta: pertence ao caixa inicial
        por_dia[quando] = por_dia.get(quando, Decimal("0")) + liquido
    return sorted(por_dia.items())


@dataclass(frozen=True)
class ProjecaoCaixa:
    """Curva diária do caixa projetado e o primeiro dia no vermelho."""

    hoje: date
    horizonte_dias: int
    curva: tuple[tuple[date, Decimal], ...]  # saldo ao fim de cada dia
    recebimentos_no_horizonte: Decimal  # calculado (vendas já feitas)
    saidas_no_horizonte: Decimal  # estimado (informado pelo usuário)
    dia_negativo: date | None  # primeiro dia com saldo < 0 (None = fôlego ok)

    @property
    def dias_de_folego(self) -> int | None:
        """Dias até o caixa virar negativo (None = não vira no horizonte)."""
        if self.dia_negativo is None:
            return None
        return (self.dia_negativo - self.hoje).days


@dataclass(frozen=True)
class JanelaCaixa:
    """Uma janela da projeção (30/60/90 dias): entradas, saídas e saldo."""

    dias: int
    entradas: Decimal  # calculado — agenda das vendas já feitas
    saidas: Decimal  # estimado — informado pelo usuário
    saldo_final: Decimal  # saldo projetado no fim da janela


@dataclass(frozen=True)
class InteligenciaCaixa:
    """Riscos de liquidez da projeção, cada alerta com a origem explicada.

    - **janelas** 30/60/90 dias, no formato "+entradas −saídas → saldo";
    - **concentração de recebíveis**: fatia do maior dia (e a data) — um
      atraso ali derruba o caixa de uma vez;
    - **descasamento**: quantos dias de saídas correm antes do primeiro
      repasse cair;
    - **alertas** em texto, cada um dizendo DE ONDE o risco vem.
    """

    janelas: tuple[JanelaCaixa, ...]
    concentracao_pct: Decimal  # maior dia de recebimento / total (%)
    dia_concentracao: date | None
    dias_ate_primeiro_recebimento: int | None  # None = nada a receber
    alertas: tuple[str, ...]


def analisar_caixa(
    projecao: ProjecaoCaixa,
    agenda: list[tuple[date, Decimal]],
) -> InteligenciaCaixa:
    """Extrai janelas, concentração, descasamento e alertas da projeção.

    ``agenda`` é a saída de :func:`agenda_recebimentos` para as mesmas
    transações — nada é recalculado, só lido e explicado.
    """
    curva = dict(projecao.curva)
    saida_diaria = projecao.saidas_no_horizonte / projecao.horizonte_dias
    janelas = []
    for dias in (30, 60, 90):
        if dias > projecao.horizonte_dias:
            continue
        limite = projecao.hoje + timedelta(days=dias)
        entradas = sum(
            (v for d, v in agenda if projecao.hoje < d <= limite), Decimal("0")
        )
        janelas.append(
            JanelaCaixa(
                dias=dias,
                entradas=_q2(entradas),
                saidas=_q2(saida_diaria * dias),
                saldo_final=curva[limite],
            )
        )

    no_horizonte = [
        (d, v)
        for d, v in agenda
        if projecao.hoje < d <= projecao.hoje + timedelta(days=projecao.horizonte_dias)
    ]
    total = sum((v for _, v in no_horizonte), Decimal("0"))
    if no_horizonte and total > 0:
        dia_maior, valor_maior = max(no_horizonte, key=lambda item: item[1])
        concentracao = (valor_maior / total * 100).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        dias_ate_primeiro = (min(d for d, _ in no_horizonte) - projecao.hoje).days
    else:
        dia_maior, concentracao, dias_ate_primeiro = None, Decimal("0"), None

    alertas: list[str] = []
    for j in janelas:
        if j.saldo_final < 0:
            alertas.append(
                f"Déficit projetado de R$ {abs(j.saldo_final)} em {j.dias} dias: "
                f"entram R$ {j.entradas} (agenda das vendas já feitas) contra "
                f"R$ {j.saidas} de saídas informadas."
            )
            break  # o primeiro déficit é o que importa; os demais derivam dele
    # Limiar de 50%: um único dia carregando metade dos recebíveis é
    # ponto único de falha; abaixo disso (ex.: 3 repasses uniformes de
    # 33%) é distribuição normal de agenda, não risco.
    if concentracao > 50 and dia_maior is not None:
        alertas.append(
            f"Concentração de recebíveis: {concentracao}% do que há para "
            f"receber cai num único dia ({dia_maior.strftime('%d/%m')}). Um "
            "atraso nesse repasse derruba o caixa de uma vez."
        )
    if (
        dias_ate_primeiro is not None
        and projecao.dias_de_folego is not None
        and dias_ate_primeiro > projecao.dias_de_folego
    ):
        alertas.append(
            f"Descasamento: o caixa aguenta {projecao.dias_de_folego} dia(s) "
            f"de saídas, mas o primeiro repasse só cai em "
            f"{dias_ate_primeiro} dia(s). Antecipar recebíveis ou adiar "
            "saídas cobre o vão."
        )
    if dias_ate_primeiro is None and projecao.saidas_no_horizonte > 0:
        alertas.append(
            "Nada a receber no horizonte: a projeção só enxerga as vendas "
            "do arquivo — sem vendas novas, o caixa só desce."
        )
    return InteligenciaCaixa(
        janelas=tuple(janelas),
        concentracao_pct=concentracao,
        dia_concentracao=dia_maior,
        dias_ate_primeiro_recebimento=dias_ate_primeiro,
        alertas=tuple(alertas),
    )


def projetar_caixa(
    transacoes: list[Transacao],
    tabela: TabelaCustos | None = None,
    caixa_inicial: Decimal = Decimal("0"),
    saidas_mensais: Decimal = Decimal("0"),
    hoje: date | None = None,
    horizonte_dias: int = 90,
) -> ProjecaoCaixa:
    """Projeta o saldo dia a dia: caixa + agenda de recebíveis − saídas.

    As saídas mensais são diluídas em ``saidas_mensais / 30`` por dia
    (aproximação linear documentada — vencimentos concentrados no início
    do mês apertam mais que a curva mostra).
    """
    tabela = tabela or TabelaCustos()
    hoje = hoje or max(t.data for t in transacoes)
    agenda = dict(agenda_recebimentos(transacoes, tabela, a_partir_de=hoje))
    saida_diaria = Decimal(saidas_mensais) / 30

    saldo = Decimal(caixa_inicial)
    curva: list[tuple[date, Decimal]] = []
    recebido = Decimal("0")
    dia_negativo: date | None = None
    for i in range(1, horizonte_dias + 1):
        dia = hoje + timedelta(days=i)
        entrada = agenda.get(dia, Decimal("0"))
        recebido += entrada
        saldo = _q2(saldo + entrada - saida_diaria)
        curva.append((dia, saldo))
        if saldo < 0 and dia_negativo is None:
            dia_negativo = dia
    return ProjecaoCaixa(
        hoje=hoje,
        horizonte_dias=horizonte_dias,
        curva=tuple(curva),
        recebimentos_no_horizonte=_q2(recebido),
        saidas_no_horizonte=_q2(saida_diaria * horizonte_dias),
        dia_negativo=dia_negativo,
    )
