"""Decomposição da margem líquida do lojista — o coração da Carchuna.

Responde, com cálculo reproduzível, a pergunta-guia do produto: "você
fatura 400; por que sobra 8?". A receita bruta é decomposta, dedução a
dedução (tributos, comissões de marketplace, adquirência, antecipação,
frete, devoluções, CMV), até a margem líquida — e cada dedução carrega a
sua ``fonte`` (lei, contrato ou tabela editável do usuário).

Regras inegociáveis deste módulo:

- **Dinheiro é ``Decimal``, nunca ``float``** — valores em ``float`` são
  rejeitados com ``TypeError``.
- **Identidade estrutural** — soma das deduções + margem líquida == receita
  bruta. Ela prova que o código não perdeu nem duplicou termo na soma, e
  **não** prova que os números são válidos: a margem é construída como
  resíduo, então a igualdade fecha até com entrada absurda. Quem valida o
  número é ``reconciliar()``, que refaz a conta por outro caminho; quem
  pega absurdo é ``conferir_plausibilidade()``.
- **Nenhuma alíquota sem lastro** — a alíquota efetiva do Simples segue a
  fórmula oficial do art. 18, § 1º-A, da LC 123/2006, com as tabelas dos
  Anexos transcritas da redação da LC 155/2016.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from carchuna.validade import (
    FATOR_DEDUCAO_SOBRE_RECEITA,
    MARGEM_MAXIMA_PLAUSIVEL,
    MARGEM_MINIMA_PLAUSIVEL,
    TOLERANCIA_RECONCILIACAO,
    Resultado,
)

# ---------------------------------------------------------------------------
# Fontes oficiais
# ---------------------------------------------------------------------------

FONTE_LC123 = "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm"

# Nota de conferência (padrão de honestidade da trilogia): os valores dos
# Anexos abaixo seguem a redação dada pela LC 155/2016, vigente desde
# 01/01/2018. A conferência automática na fonte oficial (planalto.gov.br)
# foi tentada em 19/07/2026 e o portal retornou HTTP 503 para acesso
# automatizado; confira os valores na fonte antes de qualquer uso real.
DATA_CONSULTA_FONTES = date(2026, 7, 19)

TETO_SIMPLES = Decimal("4800000")  # LC 123/2006, art. 3º, II (EPP)
TETO_MEI_ANUAL = Decimal("81000")  # LC 123/2006, art. 18-A, § 1º

# Anexos do Simples Nacional (LC 123/2006, art. 18, redação da LC 155/2016).
# Cada faixa: (limite superior da RBT12, alíquota nominal, parcela a deduzir).
_Faixa = tuple[Decimal, Decimal, Decimal]

ANEXOS_SIMPLES: dict[str, list[_Faixa]] = {
    # Anexo I — Comércio
    "I": [
        (Decimal("180000"), Decimal("0.040"), Decimal("0")),
        (Decimal("360000"), Decimal("0.073"), Decimal("5940")),
        (Decimal("720000"), Decimal("0.095"), Decimal("13860")),
        (Decimal("1800000"), Decimal("0.107"), Decimal("22500")),
        (Decimal("3600000"), Decimal("0.143"), Decimal("87300")),
        (Decimal("4800000"), Decimal("0.190"), Decimal("378000")),
    ],
    # Anexo II — Indústria
    "II": [
        (Decimal("180000"), Decimal("0.045"), Decimal("0")),
        (Decimal("360000"), Decimal("0.078"), Decimal("5940")),
        (Decimal("720000"), Decimal("0.100"), Decimal("13860")),
        (Decimal("1800000"), Decimal("0.112"), Decimal("22500")),
        (Decimal("3600000"), Decimal("0.147"), Decimal("85500")),
        (Decimal("4800000"), Decimal("0.300"), Decimal("720000")),
    ],
    # Anexo III — Serviços (art. 18, § 5º-B, entre outros)
    "III": [
        (Decimal("180000"), Decimal("0.060"), Decimal("0")),
        (Decimal("360000"), Decimal("0.112"), Decimal("9360")),
        (Decimal("720000"), Decimal("0.135"), Decimal("17640")),
        (Decimal("1800000"), Decimal("0.160"), Decimal("35640")),
        (Decimal("3600000"), Decimal("0.210"), Decimal("125640")),
        (Decimal("4800000"), Decimal("0.330"), Decimal("648000")),
    ],
    # Anexo IV — Serviços (art. 18, § 5º-C)
    "IV": [
        (Decimal("180000"), Decimal("0.045"), Decimal("0")),
        (Decimal("360000"), Decimal("0.090"), Decimal("8100")),
        (Decimal("720000"), Decimal("0.102"), Decimal("12420")),
        (Decimal("1800000"), Decimal("0.140"), Decimal("39780")),
        (Decimal("3600000"), Decimal("0.220"), Decimal("183780")),
        (Decimal("4800000"), Decimal("0.330"), Decimal("828000")),
    ],
    # Anexo V — Serviços (art. 18, § 5º-I)
    "V": [
        (Decimal("180000"), Decimal("0.155"), Decimal("0")),
        (Decimal("360000"), Decimal("0.180"), Decimal("4500")),
        (Decimal("720000"), Decimal("0.195"), Decimal("9900")),
        (Decimal("1800000"), Decimal("0.205"), Decimal("17100")),
        (Decimal("3600000"), Decimal("0.230"), Decimal("62100")),
        (Decimal("4800000"), Decimal("0.305"), Decimal("540000")),
    ],
}

CANAIS_VALIDOS = ("mercado_livre", "shopee", "amazon", "loja_propria", "fisico")

# Rótulos legíveis das deduções (dashboard, PDF e resumo executivo).
ROTULOS_DEDUCOES: dict[str, str] = {
    "tributos": "Tributos (Simples/MEI)",
    "comissoes_canal": "Comissões de canal",
    "adquirencia": "Adquirência",
    "antecipacao": "Antecipação",
    "frete": "Frete",
    "devolucoes": "Devoluções",
    "cmv": "CMV (custo do produto)",
}

_CENTAVO = Decimal("0.01")


def _dinheiro(valor, campo: str) -> Decimal:
    """Converte para ``Decimal`` rejeitando ``float`` (regra da trilogia)."""
    if isinstance(valor, float):
        raise TypeError(
            f"`{campo}` recebeu float ({valor!r}): use Decimal (ou str/int) "
            "para dinheiro — float acumula erro de arredondamento."
        )
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, (int, str)):
        return Decimal(valor)
    raise TypeError(f"`{campo}` deve ser Decimal, int ou str, recebeu {type(valor)}.")


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Transacao:
    """Uma venda individual, em qualquer canal."""

    data: date
    canal: str  # "mercado_livre" | "shopee" | "amazon" | "loja_propria" | "fisico"
    valor_bruto: Decimal
    custo_produto: Decimal
    frete_pago: Decimal
    devolvida: bool = False
    prazo_recebimento_dias: int = 0
    # Comissão efetivamente cobrada pelo canal nesta venda (do extrato de
    # repasse). ``None`` usa a tabela pública do canal (TabelaCustos).
    comissao_cobrada: Decimal | None = None
    # Nome do produto (opcional): habilita o ranking de campeões e vilões
    # de margem por produto no dashboard.
    produto: str | None = None
    # Valor ORIGINAL da coluna de devolução no arquivo (ex.: "Solicitação
    # aprovada"). O motor calcula com o booleano `devolvida`; o status
    # preserva a semântica do dado bruto (linhagem/auditoria).
    devolucao_status: str | None = None

    def __post_init__(self):
        if self.canal not in CANAIS_VALIDOS:
            raise ValueError(
                f"canal {self.canal!r} inválido; use um de {CANAIS_VALIDOS}."
            )
        for campo in ("valor_bruto", "custo_produto", "frete_pago"):
            object.__setattr__(self, campo, _dinheiro(getattr(self, campo), campo))
        if self.comissao_cobrada is not None:
            object.__setattr__(
                self,
                "comissao_cobrada",
                _dinheiro(self.comissao_cobrada, "comissao_cobrada"),
            )
        if self.valor_bruto < 0:
            raise ValueError(f"valor_bruto negativo: {self.valor_bruto}.")
        if self.prazo_recebimento_dias < 0:
            raise ValueError(
                f"prazo_recebimento_dias negativo: {self.prazo_recebimento_dias}."
            )


@dataclass(frozen=True)
class ConfigTributaria:
    """Regime tributário do lojista."""

    regime: str  # "simples" | "presumido" | "mei"
    anexo_simples: str | None = None  # "I" a "V" (obrigatório no Simples)
    rbt12: Decimal = Decimal("0")  # receita bruta dos últimos 12 meses
    # DAS fixo mensal do MEI (valor muda todo ano com o salário mínimo;
    # informe o vigente — LC 123/2006, art. 18-A, § 3º, V).
    das_mei_mensal: Decimal | None = None

    def __post_init__(self):
        if self.regime not in ("simples", "presumido", "mei"):
            raise ValueError(
                f"regime {self.regime!r} inválido; use simples, presumido ou mei."
            )
        object.__setattr__(self, "rbt12", _dinheiro(self.rbt12, "rbt12"))
        if self.das_mei_mensal is not None:
            object.__setattr__(
                self, "das_mei_mensal", _dinheiro(self.das_mei_mensal, "das_mei_mensal")
            )
        if self.regime == "simples":
            if self.anexo_simples not in ANEXOS_SIMPLES:
                raise ValueError(
                    f"anexo_simples {self.anexo_simples!r} inválido; "
                    f"use um de {sorted(ANEXOS_SIMPLES)}."
                )
            if self.rbt12 <= 0:
                raise ValueError("No Simples, `rbt12` deve ser positivo.")
        if self.regime == "mei" and self.das_mei_mensal is None:
            raise ValueError(
                "No MEI, informe `das_mei_mensal` (valor fixo vigente do DAS)."
            )


# Defaults editáveis pelo usuário. Percentuais de comissão conforme as
# tabelas públicas dos canais (páginas oficiais de tarifas, consultadas em
# 19/07/2026 — valores variam por categoria/modalidade; ajuste pelos seus
# contratos). Confiança: "estimado" até o usuário informar os próprios.
_COMISSOES_DEFAULT: dict[str, Decimal] = {
    "mercado_livre": Decimal("0.12"),  # anúncio Clássico (típico)
    "shopee": Decimal("0.14"),
    "amazon": Decimal("0.15"),
    "loja_propria": Decimal("0"),
    "fisico": Decimal("0"),
}

FONTES_COMISSAO: dict[str, str] = {
    "mercado_livre": "https://www.mercadolivre.com.br/ajuda/custos-de-vender_870",
    "shopee": "https://seller.shopee.com.br/edu/article/6802",
    "amazon": "https://venda.amazon.com.br/precos",
}


@dataclass
class TabelaCustos:
    """Custos de venda editáveis pelo usuário, com defaults documentados.

    Os defaults são pontos de partida com fonte pública; os números do seu
    contrato sempre prevalecem — edite-os.
    """

    comissao_canal: dict[str, Decimal] = field(
        default_factory=lambda: dict(_COMISSOES_DEFAULT)
    )
    # Taxa média da maquininha/adquirência sobre o valor da venda.
    taxa_adquirencia: Decimal = Decimal("0.02")
    # Custo mensal de antecipação de recebíveis (juro sobre o valor antecipado).
    taxa_antecipacao_mensal: Decimal = Decimal("0.0199")
    # Canais em que o lojista paga adquirência diretamente (nos marketplaces
    # a tarifa de pagamento já vem embutida na comissão/split do canal).
    canais_com_adquirencia: frozenset[str] = frozenset({"loja_propria", "fisico"})
    # Canais em que existe custo de antecipação de recebíveis. Por padrão,
    # TODOS: a antecipação não é privilégio de quem tem maquininha própria —
    # marketplace segura o repasse por 15 a 30 dias e vende a liberação
    # adiantada exatamente como a adquirente vende. Amarrar a antecipação
    # aos canais de adquirência zerava esse custo justamente onde ele é
    # mais comum. Quem espera o prazo em vez de antecipar informa
    # `prazo_recebimento_dias=0`, e aí não há custo em canal nenhum.
    canais_com_antecipacao: frozenset[str] = frozenset(CANAIS_VALIDOS)

    def __post_init__(self):
        self.comissao_canal = {
            canal: _dinheiro(v, f"comissao_canal[{canal}]")
            for canal, v in self.comissao_canal.items()
        }
        self.taxa_adquirencia = _dinheiro(self.taxa_adquirencia, "taxa_adquirencia")
        self.taxa_antecipacao_mensal = _dinheiro(
            self.taxa_antecipacao_mensal, "taxa_antecipacao_mensal"
        )


@dataclass(frozen=True)
class Deducao:
    """Uma fatia da receita que não vira lucro — sempre com fonte."""

    nome: str
    valor: Decimal
    pct_receita: Decimal  # percentual da receita bruta (ex.: 5.65)
    fonte: str
    confianca: str = "calculado"  # "calculado" | "estimado"


@dataclass(frozen=True)
class DecomposicaoMargem:
    """Resultado de ``decompor_margem``: receita → deduções → margem."""

    receita_bruta: Decimal
    deducoes: tuple[Deducao, ...]
    margem_liquida: Decimal
    margem_pct: Decimal
    aliquota_efetiva: Decimal | None  # fração (ex.: 0.0565) — só no Simples

    def deducao(self, nome: str) -> Deducao:
        """Busca uma dedução pelo nome (ex.: ``"tributos"``)."""
        for d in self.deducoes:
            if d.nome == nome:
                return d
        raise KeyError(
            f"dedução {nome!r} não existe; há {[d.nome for d in self.deducoes]}."
        )

    def identidade_estrutural_fecha(self) -> bool:
        """A soma dos termos bate com a receita — e só isso.

        **Leia o que esta conferência NÃO é.** A margem é construída como
        ``receita − Σ deduções``, então esta igualdade não pode falhar por
        causa de dado ruim: ela falha apenas se alguém perder ou duplicar
        um termo ao mexer no código. É teste de regressão de implementação,
        não validação de número.

        Rodando o motor com uma comissão de 900% da receita, a margem sai
        em −1854% e esta conferência fecha normalmente. Quem valida o
        número é ``reconciliar()``, que refaz a conta por outro caminho; e
        quem pega absurdo é ``conferir_plausibilidade()``.
        """
        return sum(d.valor for d in self.deducoes) + self.margem_liquida == (
            self.receita_bruta
        )


# ---------------------------------------------------------------------------
# Alíquota efetiva do Simples Nacional
# ---------------------------------------------------------------------------


def aliquota_efetiva_simples(rbt12, anexo: str) -> Decimal:
    """Alíquota efetiva do Simples: fórmula oficial do art. 18, § 1º-A.

    ``(RBT12 × ALIQ − PD) / RBT12``, onde ALIQ é a alíquota nominal e PD a
    parcela a deduzir da faixa da RBT12 (LC 123/2006, redação da LC
    155/2016). Devolve a fração (ex.: ``Decimal("0.0565")`` = 5,65%).

    Parameters
    ----------
    rbt12 : Decimal | int | str
        Receita bruta acumulada dos últimos 12 meses.
    anexo : str
        Anexo do Simples ("I" a "V").
    """
    rbt12 = _dinheiro(rbt12, "rbt12")
    if anexo not in ANEXOS_SIMPLES:
        raise ValueError(
            f"anexo {anexo!r} inválido; use um de {sorted(ANEXOS_SIMPLES)}."
        )
    if rbt12 <= 0:
        raise ValueError(f"rbt12 deve ser positivo, recebeu {rbt12}.")
    if rbt12 > TETO_SIMPLES:
        raise ValueError(
            f"rbt12 {rbt12} excede o teto do Simples (R$ {TETO_SIMPLES}) — "
            "hipótese de exclusão do regime (LC 123/2006, art. 3º, II)."
        )
    for limite, aliq, pd in ANEXOS_SIMPLES[anexo]:
        if rbt12 <= limite:
            efetiva = (rbt12 * aliq - pd) / rbt12
            return efetiva.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    raise AssertionError("faixa não encontrada — tabela do anexo inconsistente.")


# ---------------------------------------------------------------------------
# Decomposição
# ---------------------------------------------------------------------------


def _q(valor: Decimal) -> Decimal:
    """Arredonda para centavos (half-up, como na prática comercial)."""
    return valor.quantize(_CENTAVO, rounding=ROUND_HALF_UP)


def _pct(valor: Decimal, receita: Decimal) -> Decimal:
    if receita == 0:
        return Decimal("0.00")
    return (valor / receita * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _brl(valor: Decimal) -> str:
    """R$ 480000.00 → '480.000,00' — para a mensagem que o lojista lê."""
    inteiro, _, centavos = f"{valor:.2f}".partition(".")
    milhares = f"{int(inteiro):,}".replace(",", ".")
    return f"{milhares},{centavos}"


def _conferir_teto_do_mei(transacoes: list[Transacao]) -> None:
    """Recusa o cálculo quando o faturamento estoura o teto do MEI.

    O teto é anual (LC 123/2006, art. 18-A, § 1º) e proporcional ao número
    de meses no ano de abertura (§ 2º) — então a conferência é ano a ano,
    com o limite reduzido pelos meses que o arquivo cobre naquele ano.
    Somar o arquivo inteiro recusaria um MEI regular só por ele ter dois
    anos de histórico, que é o oposto do que se quer.

    Recusar é a resposta honesta. Acima do teto o enquadramento muda —
    excesso de mais de 20% desenquadra retroativamente ao início do ano
    (art. 18-A, § 7º, e art. 3º, § 10) — e o DAS fixo deixa de descrever o
    imposto devido. Um número calculado nesse estado erra **para cima**, no
    campo em que o lojista mais confia, e o custo do desenquadramento
    retroativo é ordens de grandeza maior que a diferença que a tela
    mostraria.
    """
    por_ano: dict[int, list[Transacao]] = {}
    for t in transacoes:
        por_ano.setdefault(t.data.year, []).append(t)

    for ano, do_ano in sorted(por_ano.items()):
        receita = _q(sum((t.valor_bruto for t in do_ano), Decimal("0")))
        meses = len({t.data.month for t in do_ano})
        limite = _q(TETO_MEI_ANUAL * Decimal(meses) / Decimal(12))
        if receita <= limite:
            continue
        proporcao = (
            f"{meses} mês(es) de {ano} no arquivo, então o teto proporcional "
            f"é R$ {_brl(limite)}"
            if meses < 12
            else f"o teto do ano é R$ {_brl(TETO_MEI_ANUAL)}"
        )
        raise ValueError(
            f"Em {ano} este arquivo soma R$ {_brl(receita)} de faturamento, e "
            f"isso passa do teto do MEI — {proporcao} (LC 123/2006, art. 18-A, "
            "§ 1º e § 2º). A Carchuna não sabe calcular a sua margem nesse "
            "estado: acima do teto o enquadramento muda, e quem passa de 20% "
            "do limite é desenquadrado retroativamente ao início do ano "
            "(art. 18-A, § 7º, e art. 3º, § 10) — o DAS fixo deixa de ser o "
            "imposto devido. Fale com o seu contador sobre a migração para o "
            "Simples e recalcule aqui com o anexo certo; estimar por cima "
            "seria mostrar um lucro que você não tem."
        )


def decompor_margem(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
) -> DecomposicaoMargem:
    """Decompõe a receita bruta até a margem líquida, dedução a dedução.

    Ordem das deduções (cada uma com valor, % da receita e fonte):
    tributos → comissões de canal → adquirência → antecipação → frete →
    devoluções → CMV. Invariante garantido: soma das deduções + margem
    líquida == receita bruta.

    Simplificações documentadas da v1 (ver README):

    - a base do Simples exclui devoluções/vendas canceladas (LC 123/2006,
      art. 3º, § 1º);
    - comissão e CMV não são computados sobre vendas devolvidas (canal
    estorna a comissão e o produto retorna ao estoque);
    - o custo de antecipação é ``taxa mensal × prazo/30 × valor`` das
      vendas a prazo nos canais com adquirência própria.
    """
    if not transacoes:
        raise ValueError("`transacoes` não pode ser vazio.")
    if config.regime == "presumido":
        raise ValueError(
            "Lucro Presumido é roadmap explícito da v1 (depende de ICMS/ISS "
            "estaduais e municipais); a Carchuna calcula hoje Simples e MEI. "
            "Ver tabela de status no README."
        )
    tabela = tabela or TabelaCustos()

    receita = _q(sum((t.valor_bruto for t in transacoes), Decimal("0")))
    if config.regime == "mei":
        _conferir_teto_do_mei(transacoes)
    devolucoes = _q(
        sum((t.valor_bruto for t in transacoes if t.devolvida), Decimal("0"))
    )
    vendas_efetivas = [t for t in transacoes if not t.devolvida]

    # --- tributos -----------------------------------------------------------
    aliquota: Decimal | None = None
    if config.regime == "simples":
        aliquota = aliquota_efetiva_simples(config.rbt12, config.anexo_simples)
        base_tributavel = receita - devolucoes  # LC 123/2006, art. 3º, § 1º
        tributos = _q(base_tributavel * aliquota)
        fonte_tributos = (
            f"LC 123/2006, art. 18, § 1º-A e Anexo {config.anexo_simples} "
            f"(redação da LC 155/2016) — alíquota efetiva "
            f"{(aliquota * 100).quantize(Decimal('0.0001'))}% sobre a receita "
            f"menos devoluções (art. 3º, § 1º). {FONTE_LC123}"
        )
    else:  # mei
        meses = {(t.data.year, t.data.month) for t in transacoes}
        tributos = _q(config.das_mei_mensal * len(meses))
        fonte_tributos = (
            "LC 123/2006, art. 18-A, § 3º, V — DAS fixo mensal do MEI "
            f"(R$ {config.das_mei_mensal}/mês × {len(meses)} mês(es)). "
            f"{FONTE_LC123}"
        )

    # --- comissões de canal -------------------------------------------------
    comissoes = Decimal("0")
    for t in vendas_efetivas:
        if t.comissao_cobrada is not None:
            comissoes += t.comissao_cobrada
        else:
            pct = tabela.comissao_canal.get(t.canal, Decimal("0"))
            comissoes += t.valor_bruto * pct
    comissoes = _q(comissoes)
    fonte_comissoes = (
        "Tabelas públicas de tarifas dos canais (defaults editáveis; "
        "consulta em 19/07/2026): "
        + "; ".join(f"{c}: {url}" for c, url in FONTES_COMISSAO.items())
    )

    # --- adquirência --------------------------------------------------------
    base_adq = [t for t in vendas_efetivas if t.canal in tabela.canais_com_adquirencia]
    adquirencia = _q(
        sum((t.valor_bruto for t in base_adq), Decimal("0")) * tabela.taxa_adquirencia
    )

    # --- antecipação de recebíveis -----------------------------------------
    base_ant = [t for t in vendas_efetivas if t.canal in tabela.canais_com_antecipacao]
    antecipacao = Decimal("0")
    for t in base_ant:
        if t.prazo_recebimento_dias > 0:
            antecipacao += (
                t.valor_bruto
                * tabela.taxa_antecipacao_mensal
                * Decimal(t.prazo_recebimento_dias)
                / Decimal(30)
            )
    antecipacao = _q(antecipacao)

    # --- frete, devoluções, CMV --------------------------------------------
    # ATENÇÃO à assimetria, que é deliberada e não descuido: o frete soma
    # sobre `transacoes` (TODAS, devolvidas inclusive) e o CMV sobre
    # `vendas_efetivas` (só as que ficaram de pé). Comissão, adquirência e
    # antecipação seguem o CMV.
    #
    # A razão é o que acontece de fato quando uma venda volta. O frete de
    # ida já foi pago à transportadora e não volta — e na devolução o
    # lojista costuma pagar também o de retorno, então tratá-lo como
    # recuperado erraria a favor da margem. O produto, esse volta para o
    # estoque: o CMV não se realizou. A comissão o canal estorna, e sem
    # repasse não há o que antecipar.
    #
    # A premissa é do frete de IDA. Quem paga também o retorno e quer isso
    # na conta lança a linha de retorno como transação própria — a
    # Carchuna não inventa um custo que o arquivo não traz.
    frete = _q(sum((t.frete_pago for t in transacoes), Decimal("0")))
    cmv = _q(sum((t.custo_produto for t in vendas_efetivas), Decimal("0")))

    deducoes = (
        Deducao("tributos", tributos, _pct(tributos, receita), fonte_tributos),
        Deducao(
            "comissoes_canal",
            comissoes,
            _pct(comissoes, receita),
            fonte_comissoes,
            confianca="estimado",
        ),
        Deducao(
            "adquirencia",
            adquirencia,
            _pct(adquirencia, receita),
            "Taxa da maquininha na tabela do usuário (default estimado "
            "editável); mercado regulado pela Lei 12.865/2013.",
            confianca="estimado",
        ),
        Deducao(
            "antecipacao",
            antecipacao,
            _pct(antecipacao, receita),
            "Taxa de antecipação da tabela do usuário × prazo/30. Registro "
            "de recebíveis: Resolução CMN 4.734/2019.",
            confianca="estimado",
        ),
        Deducao(
            "frete",
            frete,
            _pct(frete, receita),
            "Soma de `frete_pago` das transações importadas.",
        ),
        Deducao(
            "devolucoes",
            devolucoes,
            _pct(devolucoes, receita),
            "Soma de `valor_bruto` das transações devolvidas; direito de "
            "arrependimento em 7 dias no e-commerce: CDC, art. 49.",
        ),
        Deducao("cmv", cmv, _pct(cmv, receita), "Soma de `custo_produto` das vendas."),
    )

    margem = receita - sum(d.valor for d in deducoes)
    return DecomposicaoMargem(
        receita_bruta=receita,
        deducoes=deducoes,
        margem_liquida=margem,
        margem_pct=_pct(margem, receita),
        aliquota_efetiva=aliquota,
    )


# ---------------------------------------------------------------------------
# Plausibilidade e reconciliação — as duas coisas que a identidade não faz
# ---------------------------------------------------------------------------


def conferir_plausibilidade(
    decomposicao: DecomposicaoMargem,
) -> Resultado:
    """A margem do período cabe em alguma realidade contábil?

    Confere os dois lados, porque eles denunciam coisas diferentes:

    - **entrada**: uma dedução isolada maior que a receita bruta do período
      é quase sempre coluna trocada no mapeamento ou unidade errada
      (centavos lidos como reais), não um mês muito ruim;
    - **saída**: margem fora da faixa de ``validade.py`` — acima de 100% é
      impossível, abaixo de −100% quer dizer gastar mais que o dobro do que
      se faturou.

    Devolve a margem em % carimbada. Não corrige, não limita e não zera o
    valor: um número absurdo escondido atrás de um teto continua absurdo e
    passa a ser também invisível.
    """
    receita = decomposicao.receita_bruta
    if receita > 0:
        for d in decomposicao.deducoes:
            if d.valor > receita * FATOR_DEDUCAO_SOBRE_RECEITA:
                rotulo = ROTULOS_DEDUCOES.get(d.nome, d.nome)
                return Resultado.implausivel(
                    decomposicao.margem_pct,
                    f"{rotulo} soma R$ {d.valor}, mais que todo o faturamento "
                    f"do período (R$ {receita}). Isso não é um mês ruim: é "
                    "quase sempre coluna trocada no mapeamento, ou valor em "
                    "outra unidade. Confira essa coluna antes de usar o "
                    "número.",
                )
    if decomposicao.margem_pct > MARGEM_MAXIMA_PLAUSIVEL:
        return Resultado.implausivel(
            decomposicao.margem_pct,
            f"A margem deu {decomposicao.margem_pct}% da receita, e mais de "
            "100% é impossível — sobrar mais do que entrou significa dedução "
            "com sinal trocado no arquivo.",
        )
    if decomposicao.margem_pct < MARGEM_MINIMA_PLAUSIVEL:
        return Resultado.implausivel(
            decomposicao.margem_pct,
            f"A margem deu {decomposicao.margem_pct}% da receita: os custos "
            "passaram do dobro do faturamento do período. Prejuízo acontece, "
            "mas nessa ordem de grandeza é erro de dado antes de ser "
            "prejuízo — confira as colunas de custo e de comissão.",
        )
    return Resultado.de_valor(decomposicao.margem_pct)


def reconciliar(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    decomposicao: DecomposicaoMargem,
    tabela: TabelaCustos | None = None,
) -> Resultado:
    """Refaz o lucro pelos lançamentos e compara com o do motor.

    Esta é a asserção que **pode** falhar, e é por isso que ela existe. A
    identidade estrutural confere a soma que o próprio motor montou; aqui a
    margem é reconstruída lançamento a lançamento, a partir dos campos
    crus, sem passar por ``decompor_margem`` — dois caminhos, duas somas.
    Se o motor esquecer de excluir uma venda devolvida do CMV, ou trocar a
    base do tributo, a identidade continua fechando e esta conta não.

    Devolve a diferença entre os dois caminhos, ``ok`` quando cabe em
    ``TOLERANCIA_RECONCILIACAO`` e ``implausivel`` quando não cabe.
    """
    tabela = tabela or TabelaCustos()
    efetivas = [t for t in transacoes if not t.devolvida]

    receita = sum((t.valor_bruto for t in transacoes), Decimal("0"))
    devolvido = sum((t.valor_bruto for t in transacoes if t.devolvida), Decimal("0"))

    if config.regime == "simples":
        aliquota = aliquota_efetiva_simples(config.rbt12, config.anexo_simples)
        tributo = (receita - devolvido) * aliquota
    else:
        meses = {(t.data.year, t.data.month) for t in transacoes}
        tributo = config.das_mei_mensal * len(meses)

    perdido = devolvido + tributo
    for t in efetivas:
        perdido += (
            t.comissao_cobrada
            if t.comissao_cobrada is not None
            else t.valor_bruto * tabela.comissao_canal.get(t.canal, Decimal("0"))
        )
        perdido += t.custo_produto
        if t.canal in tabela.canais_com_adquirencia:
            perdido += t.valor_bruto * tabela.taxa_adquirencia
        # Antecipação tem base própria: marketplace não cobra adquirência do
        # lojista e mesmo assim vende a liberação adiantada do repasse.
        if t.canal in tabela.canais_com_antecipacao and t.prazo_recebimento_dias > 0:
            perdido += (
                t.valor_bruto
                * tabela.taxa_antecipacao_mensal
                * Decimal(t.prazo_recebimento_dias)
                / Decimal(30)
            )
    perdido += sum((t.frete_pago for t in transacoes), Decimal("0"))

    lucro_reconstruido = _q(receita - perdido)
    diferenca = abs(lucro_reconstruido - decomposicao.margem_liquida)
    if diferenca <= TOLERANCIA_RECONCILIACAO:
        return Resultado.de_valor(diferenca)
    return Resultado.implausivel(
        diferenca,
        f"Os dois caminhos de cálculo da margem não fecham: o motor devolveu "
        f"R$ {decomposicao.margem_liquida} e a reconferência lançamento a "
        f"lançamento deu R$ {lucro_reconstruido}, uma diferença de "
        f"R$ {diferenca} — acima da tolerância de "
        f"R$ {TOLERANCIA_RECONCILIACAO}, que só cobre arredondamento.",
    )
