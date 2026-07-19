"""Decomposição da margem líquida do lojista — o coração da Carchuna.

Responde, com cálculo reproduzível, a pergunta-guia do produto: "você
fatura 400; por que sobra 8?". A receita bruta é decomposta, dedução a
dedução (tributos, comissões de marketplace, adquirência, antecipação,
frete, devoluções, CMV), até a margem líquida — e cada dedução carrega a
sua ``fonte`` (lei, contrato ou tabela editável do usuário).

Regras inegociáveis deste módulo:

- **Dinheiro é ``Decimal``, nunca ``float``** — valores em ``float`` são
  rejeitados com ``TypeError``.
- **Invariante contábil** — soma das deduções + margem líquida == receita
  bruta, centavo a centavo (verificado por teste).
- **Nenhuma alíquota sem lastro** — a alíquota efetiva do Simples segue a
  fórmula oficial do art. 18, § 1º-A, da LC 123/2006, com as tabelas dos
  Anexos transcritas da redação da LC 155/2016.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

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
    antecipacao = Decimal("0")
    for t in base_adq:
        if t.prazo_recebimento_dias > 0:
            antecipacao += (
                t.valor_bruto
                * tabela.taxa_antecipacao_mensal
                * Decimal(t.prazo_recebimento_dias)
                / Decimal(30)
            )
    antecipacao = _q(antecipacao)

    # --- frete, devoluções, CMV --------------------------------------------
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
