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
  pega absurdo é ``conferir_plausibilidade()``; e quem confere os
  PERCENTUAIS — que são outro número, e são os que vão para a tela — é
  ``conferir_fechamento_percentual()``.
- **Nenhuma alíquota sem lastro** — a alíquota efetiva do Simples segue a
  fórmula oficial do art. 18, § 1º-A, da LC 123/2006, com as tabelas dos
  Anexos transcritas da redação da LC 155/2016.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from carchuna.validade import (
    FATOR_DEDUCAO_SOBRE_RECEITA,
    MARGEM_MAXIMA_PLAUSIVEL,
    MARGEM_MINIMA_PLAUSIVEL,
    TOLERANCIA_ADITIVIDADE_PP,
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

# Passar do teto do MEI não tem um efeito só: tem dois, e a fronteira
# entre eles são 20% de excesso (LC 123/2006, art. 18-A, § 7º).
#
# Até 20% — de R$ 81.000,01 a R$ 97.200 — o lojista CONTINUA MEI até
# 31/12. O DAS fixo segue sendo o imposto daquele mês; o excesso é
# recolhido à parte e o desenquadramento vale a partir de janeiro
# seguinte. Nessa faixa a margem do período está certa, e recusar o
# cálculo seria negar um número válido.
#
# Acima de 20%, o desenquadramento retroage ao início do ano (art. 18-A,
# § 7º, e art. 3º, § 10): o DAS fixo deixa de descrever o imposto devido
# do período inteiro que está sendo calculado, e aí a recusa é a resposta
# honesta.
TETO_MEI_COM_EXCESSO = TETO_MEI_ANUAL * Decimal("1.2")  # R$ 97.200

# ---------------------------------------------------------------------------
# Sublimite do ICMS/ISS
#
# Passando dele, a empresa CONTINUA no Simples para os tributos federais,
# mas recolhe ICMS e/ou ISS **fora do DAS**, pelas regras normais do
# Estado e do Município (LC 123/2006, arts. 19 e 20; art. 9º da Resolução
# CGSN nº 140/2018). A Carchuna não calcula esse ICMS/ISS de fora e não
# tem como calcular — é o mesmo bloqueio do Lucro Presumido no ROADMAP:
# cada alíquota depende do estado e do município.
#
# **Este valor muda todo ano.** O sublimite é fixado ano a ano por
# portaria do CGSN; R$ 3.600.000 é o do ano-calendário **2026**, pela
# Portaria CGSN nº 54/2025, uniforme para todos os Estados e o DF.
# Reconferir na virada do ano, como se reconfere o DAS do MEI.
#
# Consulta: mesma ressalva do `DATA_CONSULTA_FONTES` acima — o valor não
# foi conferido automaticamente na fonte oficial.
SUBLIMITE_ICMS_ISS = Decimal("3600000")

# Excesso de mais de 20% sobre o sublimite tira o ICMS/ISS do DAS já no
# mês seguinte ao do excesso; até 20%, a saída fica para janeiro do ano
# seguinte (LC 123/2006, art. 20, § 1º). É essa diferença de prazo que
# separa a recusa do aviso em `_conferir_sublimite_icms_iss`.
EXCESSO_SUBLIMITE_IMEDIATO = SUBLIMITE_ICMS_ISS * Decimal("1.2")  # R$ 4.320.000

# ---------------------------------------------------------------------------
# Faixa aritmética do dinheiro
#
# Não é limiar de plausibilidade — esse mora em `validade.py` e responde
# outra pergunta. Este aqui é a faixa em que a conta **existe**: acima
# dela, `Decimal.quantize()` levanta `InvalidOperation` e a aplicação cai.
#
# O número sai da aritmética, não de opinião. O contexto Decimal padrão
# tem 28 dígitos significativos, e quantizar a centavos estoura a partir
# de 1e26. O pior caso do motor é o custo de antecipação —
# `valor × taxa × dias/30`, somado sobre todos os lançamentos —, então o
# teto de um campo tem de ser a raiz disso, com folga:
#
#     200.000 lançamentos × (1e9)² × 365/30 ≈ 2,4e24  <  1e26
#
# Um bilhão de reais num único lançamento é três ordens de grandeza acima
# do teto do Simples (R$ 4,8 milhões/ano). Nenhuma PME chega perto, e
# quem chegar tem problema maior que este limite.
MAX_DINHEIRO = Decimal("1e9")

# Teto do prazo de recebimento. Entra na mesma conta acima: sem ele, o
# produto cresce sem limite mesmo com todos os valores dentro da faixa.
# Um ano é generoso — repasse de marketplace se mede em dias.
MAX_PRAZO_RECEBIMENTO_DIAS = 365

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
    """Converte para ``Decimal`` rejeitando ``float`` (regra da trilogia).

    Rejeita mais três coisas que passavam caladas:

    ``bool`` é subclasse de ``int`` em Python, então ``valor_bruto=True``
    chegava como ``Decimal("1")`` — uma venda de um real, sem aviso. É o
    erro típico de uma coluna de sim/não mapeada na coluna errada.

    ``Decimal`` não-finito (``NaN``, ``Infinity``) passava intacto pelo
    ramo do ``Decimal``, e NaN é pior que estourar: ``NaN + 10`` é NaN,
    toda comparação com ele é falsa, e a contaminação se espalha pela
    soma inteira sem nada acusar. ``Decimal("nan")`` também não estoura na
    construção, então texto "nan" vindo de planilha chegava até aqui — a
    recusa fecha esse caminho para CSV, JSON e Excel de uma vez.

    A recusa do não-finito é ``ValueError``, e não ``TypeError``, porque o
    tipo está certo e o valor é que não serve: assim a linha é recusada
    com número e nome de coluna pelo relatório de importação, em vez de
    derrubar o arquivo inteiro.
    """
    if isinstance(valor, bool):
        raise TypeError(
            f"`{campo}` recebeu booleano ({valor!r}): em Python `True` vira "
            "1 e `False` vira 0, então isto entraria como dinheiro sem "
            "ninguém perceber. Confira se uma coluna de sim/não foi mapeada "
            "nesta coluna de valor."
        )
    if isinstance(valor, float):
        raise TypeError(
            f"`{campo}` recebeu float ({valor!r}): use Decimal (ou str/int) "
            "para dinheiro — float acumula erro de arredondamento."
        )
    if isinstance(valor, (Decimal, int, str)):
        convertido = valor if isinstance(valor, Decimal) else Decimal(valor)
        if not convertido.is_finite():
            raise ValueError(
                f"`{campo}` = {valor!r} não é um número utilizável. NaN e "
                "infinito contaminam toda a soma em silêncio (NaN + 10 = "
                "NaN), então a linha é recusada aqui em vez de estragar o "
                "total. Confira essa célula na planilha."
            )
        if abs(convertido) > MAX_DINHEIRO:
            raise ValueError(
                f"`{campo}` está fora da faixa de dinheiro que a Carchuna "
                f"calcula (o limite é R$ {_brl(MAX_DINHEIRO)} por "
                "lançamento). Confira essa célula: notação científica "
                "exportada por engano (1e9), separador de milhar lido como "
                "decimal e coluna trocada são as três causas comuns."
            )
        return convertido
    raise TypeError(f"`{campo}` deve ser Decimal, int ou str, recebeu {type(valor)}.")


# Nome público do guardião de dinheiro.
#
# "Dinheiro é `Decimal`, `float` é recusado com `TypeError`" é regra da
# trilogia, e ela vale em toda fronteira que recebe valor de fora — não
# só na `Transacao`. `crescimento.py` fazia `Decimal(custo) + Decimal(frete)`
# cru na calculadora de preço, e `Decimal(2.49)` aceita o float em
# silêncio, com a bagagem binária inteira: 2,4900000000000002131628...
#
# Quem escrever fronteira nova chama isto, e não `Decimal()`.
dinheiro = _dinheiro


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
        # Os QUATRO campos de dinheiro recusam negativo, não só o
        # `valor_bruto`.
        #
        # O defeito que isto fecha: extrato de repasse de marketplace
        # lança estorno como valor negativo, e quem monta a planilha põe
        # esse número na coluna de custo. Uma venda com
        # `custo_produto=-500` no meio de dez normais levava a margem de
        # 36,55% para 44,73% — e passava nas TRÊS conferências:
        # `identidade_estrutural_fecha()` verdadeira (a margem é resíduo,
        # fecha por definição), `conferir_plausibilidade()` ok (nenhuma
        # dedução passa da receita) e `reconciliar()` ok (os dois
        # caminhos somam o mesmo número errado). É o "sinal trocado" que
        # este módulo diz caçar, entrando pela porta da frente.
        #
        # O que a recusa NÃO faz: compensar. Não existe aqui regra que
        # some estorno negativo em outra linha — inventar compensação
        # sobre um dado que ninguém conferiu seria trocar um erro
        # silencioso por outro. Estorno e crédito são lançamento próprio.
        for campo in ("valor_bruto", "custo_produto", "frete_pago", "comissao_cobrada"):
            valor = getattr(self, campo)
            if valor is not None and valor < 0:
                raise ValueError(
                    f"{campo} negativo: {valor}. Em campo de dinheiro a "
                    "Carchuna só aceita valor positivo ou zero. Se isto veio "
                    "de um estorno, de um crédito ou de um ajuste do "
                    "marketplace, ele é lançamento próprio e não custo "
                    "negativo: um custo negativo aumenta a sua margem em "
                    "silêncio e passa em todas as conferências. Lance o "
                    "estorno como devolução da venda de origem, ou tire "
                    "essa linha do arquivo e trate o ajuste à parte."
                )
        if self.prazo_recebimento_dias < 0:
            raise ValueError(
                f"prazo_recebimento_dias negativo: {self.prazo_recebimento_dias}."
            )
        if self.prazo_recebimento_dias > MAX_PRAZO_RECEBIMENTO_DIAS:
            raise ValueError(
                f"prazo_recebimento_dias = {self.prazo_recebimento_dias} passa "
                f"de {MAX_PRAZO_RECEBIMENTO_DIAS} dias. Repasse de "
                "marketplace se mede em dias, não em anos — confira se essa "
                "coluna não é uma data que veio como número."
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
    # Coisas verdadeiras sobre este período que não recusam o cálculo e
    # não cabem em nenhuma dedução — hoje, a projeção de teto do MEI. Não
    # confundir com as conferências: `Resultado` carimba um número; aqui é
    # texto para o lojista ler, e o número ao lado vale.
    avisos: tuple[str, ...] = ()

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


def _conferir_teto_do_mei(transacoes: list[Transacao]) -> tuple[str, ...]:
    """Três faixas no teto do MEI; só a última recusa o cálculo.

    **A receita que conta é a bruta LÍQUIDA DE DEVOLUÇÃO.** Venda
    devolvida não compõe a base (LC 123/2006, art. 3º, § 1º) — é o mesmo
    dispositivo que este módulo já cita para a base do Simples
    (``base_tributavel = receita - devolucoes``) e que a
    ``metricas.rbt12_movel`` respeita. Somar as devolvidas aqui recusava
    quem estava dentro da lei: R$ 83.000 na coluna de valor com R$ 5.000
    devolvidos são R$ 78.000 de receita bruta, dentro do teto, e a
    análise inteira era bloqueada.

    **As três faixas, e por que a fronteira são 20%** (art. 18-A, § 7º):

    - até ``TETO_MEI_ANUAL`` → calcula, sem nada a dizer;
    - de lá até ``TETO_MEI_COM_EXCESSO`` → **calcula e avisa**. O
      excesso de até 20% não desenquadra no ato: o lojista segue MEI até
      31/12, o DAS fixo continua sendo o imposto daquele mês e a
      migração para ME vale a partir de janeiro. A margem do período
      está certa, e recusá-la seria negar um número válido;
    - acima disso → **recusa**. O desenquadramento retroage ao início do
      ano (art. 18-A, § 7º, e art. 3º, § 10), o DAS fixo deixa de
      descrever o imposto devido do período inteiro que está sendo
      calculado, e a conta erra **para cima** — no campo em que o
      lojista mais confia. O custo do desenquadramento retroativo é
      ordens de grandeza maior que a diferença que a tela mostraria.

    A recusa antiga cobria as duas faixas de cima e por isso era larga
    demais: bloqueava a análise de quem tinha faturado R$ 85.000 e
    continuava, para todo efeito daquele ano, MEI.

    **O que o aviso da faixa dos 20% NÃO faz: calcular o DAS
    complementar.** Há tributo a recolher sobre o excesso, e o valor
    depende de regra que a Carchuna não implementa. O aviso diz que ele
    existe e manda ao contador; inventar o número seria pior que não
    dá-lo.

    **A projeção é outra coisa e não recusa nada.** Quando o ano do
    arquivo ainda não fechou, o ritmo dos meses cobertos pode apontar para
    um estouro que ainda não aconteceu. Isso é informação útil e é hora de
    o lojista falar com o contador — mas não é fato consumado, e recusar
    o cálculo por causa dele é punir quem ainda está dentro da lei.

    Antes esta conferência tratava as duas coisas como uma. Pior: ela
    dividia o teto pelo número de meses **com venda**, não pela janela do
    arquivo. Um MEI sazonal que fatura em novembro e dezembro e fecha o
    ano em R$ 35.000 — folgadamente dentro do teto — era recusado, porque
    dois meses de venda valiam um teto de R$ 13.500. A conta media
    intensidade de venda e chamava aquilo de teto.

    A janela agora é o **span**: do primeiro ao último mês daquele ano
    presente no arquivo, inclusive. Mês vazio no meio conta, porque ele
    faz parte do período que o arquivo cobre.

    Nota sobre o fundamento, que estava errado no texto anterior: o § 2º
    é a proporcionalidade do ano de **abertura** do MEI, não da janela de
    um arquivo de vendas. Um arquivo de três meses não reduz o teto de
    ninguém. Por isso a projeção sai daqui sem citação legal: ela é
    **heurística de produto** — regra de três sobre o ritmo observado —, e
    apresentá-la com um parágrafo de lei ao lado a faria passar por
    obrigação onde ela é só um alerta antecipado.

    O que a Carchuna não sabe, e o aviso não substitui: quem abriu o MEI
    no meio do ano tem teto proporcional de verdade (§ 2º), menor que
    ``TETO_MEI_ANUAL`` — e a data de abertura não está no arquivo de
    vendas.

    Devolve os avisos de projeção, um por ano. Quem chama publica.
    """
    por_ano: dict[int, list[Transacao]] = {}
    for t in transacoes:
        por_ano.setdefault(t.data.year, []).append(t)

    avisos: list[str] = []
    for ano, do_ano in sorted(por_ano.items()):
        # Devolvida não compõe a receita bruta (art. 3º, § 1º) — mesma
        # regra da base do Simples, alguns parágrafos abaixo.
        efetivas = [t for t in do_ano if not t.devolvida]
        receita = _q(sum((t.valor_bruto for t in efetivas), Decimal("0")))
        if receita > TETO_MEI_COM_EXCESSO:
            raise ValueError(
                f"Em {ano} este arquivo soma R$ {_brl(receita)} de receita "
                f"bruta (já sem as devoluções), e isso passa em mais de 20% "
                f"do teto do MEI de R$ {_brl(TETO_MEI_ANUAL)} por ano — o "
                f"corte está em R$ {_brl(TETO_MEI_COM_EXCESSO)} (LC "
                "123/2006, art. 18-A, § 1º e § 7º). A Carchuna não sabe "
                "calcular a sua margem nesse estado: passando de 20% o "
                "desenquadramento retroage ao início do ano (art. 18-A, "
                "§ 7º, e art. 3º, § 10), então o DAS fixo deixa de ser o "
                "imposto devido do período inteiro que está aqui. Fale com "
                "o seu contador sobre a migração para o Simples e recalcule "
                "aqui com o anexo certo; estimar por cima seria mostrar um "
                "lucro que você não tem."
            )
        if receita > TETO_MEI_ANUAL:
            avisos.append(
                f"Em {ano} este arquivo soma R$ {_brl(receita)} de receita "
                f"bruta (já sem as devoluções) e passou do teto do MEI de "
                f"R$ {_brl(TETO_MEI_ANUAL)} por ano (LC 123/2006, art. 18-A, "
                "§ 1º). Como o excesso é de até 20%, você **continua MEI até "
                "31/12** e o DAS fixo segue sendo o imposto do mês: a conta "
                "desta tela vale para o período. O que muda é depois — há "
                "tributo a recolher sobre o excesso, e a migração para ME "
                "vale a partir de janeiro (art. 18-A, § 7º). **A Carchuna "
                "não calcula esse recolhimento complementar** e não tem como "
                "calcular; procure o seu contador ainda este ano, porque a "
                "conta dele é sobre o que já aconteceu."
            )

        # O span sai de TODAS as transações, não só das efetivas: ele mede
        # a janela que o arquivo cobre, e um mês em que tudo foi devolvido
        # continua sendo um mês coberto. Tirá-lo daqui encurtaria a janela
        # e INFLARIA a projeção — o contrário do que a exclusão de
        # devolvidas existe para fazer.
        meses = {t.data.month for t in do_ano}
        span = max(meses) - min(meses) + 1
        if span >= 12:
            continue
        projetado = _q(receita * Decimal(12) / Decimal(span))
        if projetado <= TETO_MEI_ANUAL:
            continue
        avisos.append(
            f"Em {ano} o arquivo cobre {span} mês(es) e soma "
            f"R$ {_brl(receita)}, que ainda está dentro do teto do MEI de "
            f"R$ {_brl(TETO_MEI_ANUAL)} por ano (LC 123/2006, art. 18-A, "
            f"§ 1º). Mantido esse ritmo, o ano fecharia em torno de "
            f"R$ {_brl(projetado)} e passaria do teto. A conta está feita e "
            "vale; isto é só um aviso para você falar com o contador antes "
            "de o ano fechar. É uma regra de três sobre o que o arquivo "
            "mostra, não uma previsão: quem vende concentrado em poucos "
            "meses do ano dispara este aviso sem estar perto do teto."
        )
    return tuple(avisos)


def _conferir_sublimite_icms_iss(
    config: ConfigTributaria, *, hipotetico: bool = False
) -> tuple[str, ...]:
    """Acima do sublimite, o DAS deixa de ser o imposto todo.

    **O que esta conferência é.** Passando de ``SUBLIMITE_ICMS_ISS``, a
    empresa continua no Simples para os tributos federais, mas recolhe
    ICMS e/ou ISS **fora do DAS**, pelas regras normais do Estado e do
    Município (LC 123/2006, arts. 19 e 20). A dedução ``tributos`` desta
    decomposição cobre só o DAS — então, nessa faixa, ela fica incompleta
    e a margem sai **para cima**. É o mesmo erro direcional que o motor já
    se recusa a cometer no MEI acima do teto, e recebe o mesmo tratamento.

    **A diferença entre recusar e avisar é de prazo, e vem da lei.**
    Excesso de mais de 20% sobre o sublimite tira o ICMS/ISS do DAS já no
    mês seguinte ao do excesso; até 20%, a saída fica para janeiro do ano
    seguinte (art. 20, § 1º). Por isso:

    - acima de ``EXCESSO_SUBLIMITE_IMEDIATO`` → **recusa**, porque o
      período que está sendo calculado provavelmente já é um período em
      que o ICMS/ISS saiu do DAS, e o número sairia errado para cima;
    - entre o sublimite e ele → **aviso**, porque o cálculo do período
      corrente pode continuar valendo, e recusar seria negar um número
      que ainda está certo.

    **O que esta conferência NÃO é.** Ela não calcula o ICMS/ISS de fora,
    nem estima. Não dá para: cada alíquota depende do estado e do
    município, e nenhuma foi conferida em fonte oficial — é o mesmo
    bloqueio que mantém o Lucro Presumido no ROADMAP. O que ela faz é
    impedir que a Carchuna publique uma margem que ela sabe estar
    incompleta.

    **``hipotetico`` — por que um cenário não é recusado.** A recusa
    protege o lojista de ler como seu um número que já está errado. Num
    cenário isso se inverte: ninguém está naquele estado, e a travessia
    do sublimite é justamente o achado mais valioso da simulação —
    "subir 5% te leva para uma faixa em que você passa a recolher
    ICMS/ISS por fora". Omitir o cenário esconderia exatamente isso, e
    era o que acontecia: ele sumia da bateria em silêncio. Com
    ``hipotetico=True`` a recusa vira aviso, o número sai carimbado, e o
    carimbo diz que o ganho mostrado não considera o ICMS/ISS de fora.

    O teto do MEI não recebe o mesmo tratamento, e a diferença é a mesma
    de sempre: acima do sublimite a empresa continua no Simples e o DAS
    continua certo, só incompleto; acima do teto do MEI o DAS fixo é o
    instrumento errado, e um cenário calculado com ele não seria
    incompleto, seria sem sentido.

    **A imprecisão assumida.** O teste da lei é a receita bruta acumulada
    no **ano-calendário**; a ``rbt12`` é uma janela móvel de doze meses.
    Não são a mesma coisa: em julho, a RBT12 carrega o segundo semestre
    do ano anterior, que não conta para o sublimite deste ano. Usar a
    RBT12 como gatilho é **proxy conservador** — dispara antes da hora
    para quem cresceu no ano passado e desacelerou, e nunca depois. Isso
    está aqui escrito e não corrigido de propósito: corrigir exigiria a
    receita do ano-calendário, que a configuração não traz.

    Devolve os avisos. Quem chama publica.
    """
    if config.regime != "simples":
        return ()
    # Acima do teto do Simples não há sublimite a discutir: a empresa está
    # fora do regime inteiro, não só do ICMS/ISS. Quem responde nessa faixa
    # é `aliquota_efetiva_simples`, com a mensagem do teto — dizer aqui que
    # o problema é o sublimite trocaria o fato maior pelo menor.
    if config.rbt12 > TETO_SIMPLES:
        return ()
    if config.rbt12 > EXCESSO_SUBLIMITE_IMEDIATO:
        if hipotetico:
            return (
                f"Este cenário leva a RBT12 a R$ {_brl(config.rbt12)}, mais "
                f"de 20% acima do sublimite de ICMS/ISS de "
                f"R$ {_brl(SUBLIMITE_ICMS_ISS)} (Portaria CGSN nº 54/2025). "
                "Nessa faixa o ICMS e/ou o ISS saem do DAS já no mês "
                "seguinte ao do excesso (LC 123/2006, art. 20, § 1º) e "
                "passam a ser recolhidos pelas regras do seu Estado e do "
                "seu Município. **O ganho mostrado aqui não considera esse "
                "imposto de fora** — a Carchuna não sabe calculá-lo, porque "
                "a alíquota depende do estado e do município. Trate o "
                "número como teto, não como resultado, e leve a simulação "
                "ao seu contador antes de decidir.",
            )
        raise ValueError(
            f"A RBT12 informada (R$ {_brl(config.rbt12)}) passa em mais de "
            f"20% do sublimite de ICMS/ISS, que em 2026 é de "
            f"R$ {_brl(SUBLIMITE_ICMS_ISS)} (Portaria CGSN nº 54/2025). "
            "Nesse excesso o ICMS e/ou o ISS saem do DAS já no mês seguinte "
            "e passam a ser recolhidos pelas regras do seu Estado e do seu "
            "Município (LC 123/2006, art. 20, § 1º). A Carchuna não sabe "
            "calcular a sua margem nesse estado: ela calcula o DAS, e o "
            "DAS deixou de ser o imposto todo — o que ela mostrasse sairia "
            "para cima, no campo em que você mais confia. Fale com o seu "
            "contador sobre o ICMS/ISS por fora e some esse valor por "
            "conta; estimar por aqui seria inventar alíquota de estado e "
            "de município."
        )
    if config.rbt12 > SUBLIMITE_ICMS_ISS:
        return (
            f"A RBT12 informada (R$ {_brl(config.rbt12)}) passou do "
            f"sublimite de ICMS/ISS de R$ {_brl(SUBLIMITE_ICMS_ISS)}, que "
            "vale para 2026 (Portaria CGSN nº 54/2025). Como o excesso é "
            "de até 20%, o ICMS e/ou o ISS só saem do DAS em janeiro do "
            "ano que vem (LC 123/2006, art. 20, § 1º), e a conta deste "
            "período continua valendo. **Mas a linha de tributos aqui é só "
            "o DAS**: a partir da virada, você vai recolher ICMS/ISS por "
            "fora, pelas regras do seu Estado e do seu Município, e esse "
            "valor não está em nenhum número desta tela. Fale com o seu "
            "contador antes de planejar o ano que vem com esta margem.",
        )
    return ()


BASE_RATEADA = "rateada"
BASE_VARIAVEL = "variavel"


def config_do_subconjunto(
    config: ConfigTributaria,
    subconjunto: list[Transacao],
    todas: list[Transacao],
    *,
    base: str,
) -> ConfigTributaria:
    """A regra de como o DAS do MEI entra na margem de um SUBCONJUNTO.

    Este é o único lugar onde essa decisão está escrita. Quem decompõe um
    recorte das vendas — por produto, por canal, venda a venda — chama
    aqui em vez de resolver por conta própria, porque resolver por conta
    própria foi como o projeto acabou com duas regras opostas para a
    mesma pergunta.

    **O problema.** O DAS é valor fixo do mês (LC 123/2006, art. 18-A,
    § 3º, V): não tem base de cálculo por item, por canal nem por venda.
    ``decompor_margem`` o cobra inteiro em qualquer conjunto que receba,
    então decompor dez produtos cobra dez DAS. Qualquer repartição para
    um recorte é convenção nossa, e a convenção certa depende do que o
    número vai responder.

    **``BASE_RATEADA`` — o número é lido como margem.** Vale quando o
    recorte é comparado com o título da tela ou com um recorte irmão
    (margem por produto, margem por canal). O DAS do período é repartido
    pela participação do grupo na receita, que é a única repartição com
    as duas propriedades que essa leitura exige: as partes somam o todo,
    e cada parte fica no mesmo pé do título. De quebra, o rateio por
    receita desloca TODO grupo pelo mesmo tanto — ``DAS ÷ receita`` —,
    então comparar dois grupos entre si dá o mesmo resultado que dá com o
    DAS fora. Ele não pode inventar diferença entre grupos; só multiplicar
    o DAS inventa (era o defeito).

    **``BASE_VARIAVEL`` — o número responde "o que muda se esta linha
    sumir".** Vale para detectar venda no prejuízo e para a visão venda a
    venda. O DAS não muda se a venda parar, então cobrar dela um pedaço
    dele responde a pergunta errada: manda o lojista matar uma venda que
    estava ajudando a pagar o boleto. Repare que isso não é regalia do
    MEI — no Simples esse caminho já é assim, porque lá todo custo por
    venda é variável de fato.

    **O que esta função NÃO faz.** Publicar DAS alocado como valor em
    reais de um grupo ("tributos do canal Shopee: R$ 76"). Aí não é
    convenção declarada dentro de uma taxa, é afirmação de um fato que o
    dado não tem — quem publica assim suprime a linha (ver
    ``AnalisadorMargem.composicao_deducao``).

    Fora do MEI devolve a configuração intacta: no Simples o tributo já é
    proporcional à receita do grupo e não há o que repartir.
    """
    if base not in (BASE_RATEADA, BASE_VARIAVEL):
        raise ValueError(
            f"base {base!r} desconhecida; use BASE_RATEADA ou BASE_VARIAVEL."
        )
    if config.regime != "mei":
        return config
    if base == BASE_VARIAVEL:
        return replace(config, das_mei_mensal=Decimal("0"))

    receita_total = sum((t.valor_bruto for t in todas), Decimal("0"))
    if not receita_total:
        return config
    receita_grupo = sum((t.valor_bruto for t in subconjunto), Decimal("0"))
    meses_periodo = len({(t.data.year, t.data.month) for t in todas}) or 1
    meses_grupo = len({(t.data.year, t.data.month) for t in subconjunto}) or 1
    # `decompor_margem` vai multiplicar por `meses_grupo`; a divisão aqui
    # desfaz essa multiplicação. Sem ela, um produto vendido em 2 dos 6
    # meses levaria um terço do DAS que lhe cabe.
    das_do_periodo = config.das_mei_mensal * meses_periodo
    das_do_grupo = das_do_periodo * receita_grupo / receita_total
    return replace(config, das_mei_mensal=das_do_grupo / meses_grupo)


def decompor_margem(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
    *,
    hipotetico: bool = False,
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

    ``hipotetico=True`` marca que estas entradas são um **cenário**, não
    o estado da loja: a recusa por excesso de sublimite vira aviso, e o
    resultado sai carimbado em ``avisos``. Só os cenários passam isso —
    ver ``_conferir_sublimite_icms_iss``. O padrão, e tudo que descreve a
    loja de verdade, continua recusando.
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
    avisos: tuple[str, ...] = ()
    if config.regime == "mei":
        avisos = _conferir_teto_do_mei(transacoes)
    else:
        avisos = _conferir_sublimite_icms_iss(config, hipotetico=hipotetico)
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
        avisos=avisos,
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
    fechamento = conferir_fechamento_percentual(decomposicao)
    if not fechamento.ok:
        return fechamento
    return Resultado.de_valor(decomposicao.margem_pct)


def conferir_fechamento_percentual(decomposicao: DecomposicaoMargem) -> Resultado:
    """Os percentuais publicados somam 100 com a margem?

    A terceira conferência olha os REAIS: ``reconciliar()`` refaz a margem
    lançamento a lançamento e compara valores. Os percentuais são outro
    número — ``valor ÷ receita bruta``, calculado à parte para cada
    dedução — e nada os conferia, embora sejam eles que aparecem na
    cachoeira, no drill-down e no resumo.

    O buraco não é teórico. Trocar o denominador do percentual do tributo
    para a base do tributo (``receita − devoluções``) é uma "correção" que
    qualquer um faz de boa-fé, já que aquela É a base legal do art. 3º,
    § 1º. Feita essa troca, todos os valores em reais continuam certos,
    ``reconciliar()`` diz ok, a identidade estrutural fecha — e a tela
    publica percentuais que somam 101,41.

    Esta conferência é sobre o denominador, então: todo percentual
    publicado tem de ser fração da MESMA receita bruta. A tolerância é de
    arredondamento (``TOLERANCIA_ADITIVIDADE_PP``), não de erro.
    """
    soma = sum((d.pct_receita for d in decomposicao.deducoes), Decimal("0"))
    total = soma + decomposicao.margem_pct
    divergencia = abs(total - Decimal("100"))
    if divergencia <= TOLERANCIA_ADITIVIDADE_PP:
        return Resultado.de_valor(decomposicao.margem_pct)
    return Resultado.implausivel(
        decomposicao.margem_pct,
        f"Os percentuais da tela somam {total}% em vez de 100%: as deduções "
        f"dão {soma}% e a margem, {decomposicao.margem_pct}%. Os valores em "
        "reais podem estar certos — o que não fecha é o denominador de "
        "algum percentual, que precisa ser sempre a receita bruta do "
        "período. Não use os percentuais até conferir.",
    )


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
