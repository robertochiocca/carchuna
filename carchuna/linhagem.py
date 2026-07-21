"""Linhagem de dados: "como a Carchuna chegou a este número?".

Para cada número importante da decomposição, uma ficha navegável com:

- de qual **arquivo** o dado veio (ou dados de exemplo, sinalizados);
- quais **colunas** da planilha alimentam o cálculo;
- quais **transformações** foram aplicadas na importação;
- a **fórmula** usada, com os parâmetros reais do caso;
- as **premissas** (o que foi assumido) e as **limitações** (o que os
  dados não têm como dizer);
- a **fonte** (lei ou tabela) e a etiqueta de confiança do número;
- **quando** o cálculo foi feito.

Nada aqui recalcula: a ficha descreve o caminho que o motor testado
(`margem.decompor_margem`) já percorreu — os valores vêm da própria
``DecomposicaoMargem``, e a soma fecha pelo invariante testado
``margem = receita − Σ deduções``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from carchuna.margem import (
    ROTULOS_DEDUCOES,
    ConfigTributaria,
    DecomposicaoMargem,
    TabelaCustos,
    Transacao,
    aliquota_efetiva_simples,
)

# Colunas da planilha que alimentam cada número (o mapeador de colunas
# converte nomes reais de relatórios para estes canônicos).
COLUNAS_POR_NUMERO: dict[str, tuple[str, ...]] = {
    "receita_bruta": ("valor_bruto",),
    "tributos": ("valor_bruto", "devolvida", "data"),
    "comissoes_canal": ("valor_bruto", "canal", "comissao_cobrada", "devolvida"),
    "adquirencia": ("valor_bruto", "canal"),
    "antecipacao": ("valor_bruto", "prazo_recebimento_dias"),
    "frete": ("frete_pago",),
    "devolucoes": ("valor_bruto", "devolvida"),
    "cmv": ("custo_produto", "devolvida"),
    "margem_liquida": ("todas acima",),
}

TRANSFORMACOES_IMPORTACAO = (
    "valores monetários convertidos para Decimal (float é rejeitado)",
    "vírgula decimal brasileira aceita e normalizada na importação",
    "nomes de canal normalizados (acentos, espaços e sinônimos)",
    "quando o arquivo tem outros nomes de coluna, o de-para do mapeador "
    "é aplicado antes do cálculo",
)


@dataclass(frozen=True)
class Linhagem:
    """A ficha de rastreabilidade de um número financeiro."""

    nome: str
    rotulo: str
    valor: Decimal
    origem_dados: str  # nome do arquivo, ou dados de exemplo (sinalizado)
    colunas: tuple[str, ...]
    formula: str  # com os parâmetros reais do caso
    transformacoes: tuple[str, ...]
    premissas: tuple[str, ...]
    limitacoes: tuple[str, ...]
    fonte: str  # lei/tabela citada
    confianca_dados: str  # "calculado" | "estimado"
    calculado_em: datetime


def _formula_tributos(config: ConfigTributaria) -> str:
    if config.regime == "mei":
        return (
            f"DAS fixo mensal de R$ {config.das_mei_mensal} × meses do período "
            "(LC 123/2006, arts. 18-A e ss.) — não varia com o faturamento"
        )
    aliquota = aliquota_efetiva_simples(config.rbt12, config.anexo_simples)
    pct = (aliquota * 100).quantize(Decimal("0.01"))
    return (
        "(receita − devoluções) × alíquota efetiva; alíquota efetiva = "
        f"(RBT12 × alíquota nominal − parcela a deduzir) / RBT12 = {pct}% "
        f"para RBT12 R$ {config.rbt12} no Anexo {config.anexo_simples} "
        "(LC 123/2006, art. 18, § 1º-A)"
    )


def _contagem_comissao(transacoes: list[Transacao]) -> tuple[int, int]:
    efetivas = [t for t in transacoes if not t.devolvida]
    reais = sum(1 for t in efetivas if t.comissao_cobrada is not None)
    return reais, len(efetivas)


def montar_linhagem(
    decomposicao: DecomposicaoMargem,
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos,
    origem_dados: str,
    calculado_em: datetime,
) -> dict[str, Linhagem]:
    """Uma ficha de linhagem por número da decomposição (dict por nome)."""
    reais, efetivas = _contagem_comissao(transacoes)
    adq_pct = (tabela.taxa_adquirencia * 100).quantize(Decimal("0.01"))
    ant_pct = (tabela.taxa_antecipacao_mensal * 100).quantize(Decimal("0.01"))

    formulas: dict[str, str] = {
        "receita_bruta": "soma de valor_bruto de todas as vendas do período",
        "tributos": _formula_tributos(config),
        "comissoes_canal": (
            "comissão real do extrato quando informada; senão valor_bruto × "
            "taxa da tabela do canal — comissão efetiva ponderada "
            f"({reais} de {efetivas} vendas efetivas com comissão real)"
        ),
        "adquirencia": (
            f"valor_bruto × {adq_pct}% nos canais próprios (loja própria e "
            "física); nos marketplaces a tarifa já vem na comissão/split"
        ),
        "antecipacao": (
            f"valor antecipado × {ant_pct}% ao mês × prazo/30 — só nas "
            "vendas a prazo"
        ),
        "frete": "soma de frete_pago das vendas não devolvidas",
        "devolucoes": "soma de valor_bruto das vendas marcadas como devolvidas",
        "cmv": "soma de custo_produto das vendas não devolvidas",
        "margem_liquida": (
            "receita − impostos − comissões − adquirência − antecipação − "
            "frete − devoluções − custo dos produtos (invariante testado: "
            "a soma das partes fecha com a receita, centavo a centavo)"
        ),
    }
    premissas: dict[str, tuple[str, ...]] = {
        "tributos": (
            ("RBT12 informada pelo usuário na barra lateral",)
            if config.regime == "simples"
            else ("valor do DAS informado pelo usuário",)
        ),
        "comissoes_canal": (
            "onde o extrato não traz a comissão real, vale a tabela pública "
            "do canal (editável)",
        ),
        "adquirencia": ("taxa média da maquininha, editável na barra lateral",),
        "antecipacao": (
            "assume que TODA venda a prazo é antecipada à taxa informada — "
            "se você espera o prazo, este custo é zero",
        ),
    }
    limitacoes: dict[str, tuple[str, ...]] = {
        "tributos": ("a RBT12 sugerida do arquivo é média × 12 — confirme no PGDAS-D",),
        "comissoes_canal": (
            (
                f"{efetivas - reais} venda(s) sem comissão real no arquivo: "
                "nelas o número usa a tabela, não o extrato",
            )
            if reais < efetivas
            else ()
        ),
        "margem_liquida": (
            "custos fora da planilha de vendas (aluguel, salários, anúncios) "
            "não entram nesta margem — use a aba Caixa para as saídas totais",
        ),
    }

    fichas: dict[str, Linhagem] = {}
    numeros: list[tuple[str, str, Decimal, str, str]] = [
        (
            "receita_bruta",
            "Receita bruta",
            decomposicao.receita_bruta,
            "soma direta do arquivo",
            "calculado",
        )
    ]
    numeros += [
        (d.nome, ROTULOS_DEDUCOES.get(d.nome, d.nome), d.valor, d.fonte, d.confianca)
        for d in decomposicao.deducoes
    ]
    numeros.append(
        (
            "margem_liquida",
            "Margem líquida",
            decomposicao.margem_liquida,
            "motor de margem (decompor_margem), com invariante testado",
            "calculado",
        )
    )
    for nome, rotulo, valor, fonte, confianca in numeros:
        fichas[nome] = Linhagem(
            nome=nome,
            rotulo=rotulo,
            valor=valor,
            origem_dados=origem_dados,
            colunas=COLUNAS_POR_NUMERO.get(nome, ()),
            formula=formulas.get(nome, ""),
            transformacoes=TRANSFORMACOES_IMPORTACAO,
            premissas=premissas.get(nome, ()),
            limitacoes=limitacoes.get(nome, ()),
            fonte=fonte,
            confianca_dados=confianca,
            calculado_em=calculado_em,
        )
    return fichas
