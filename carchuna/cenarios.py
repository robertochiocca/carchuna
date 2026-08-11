"""Cenários de stress da margem — "e se amanhã o custo subir?".

Adaptação do ``stress.py`` da Calahonda, organizada em objetos no padrão
do DireitoAberto: cada cenário é uma classe com uma única
responsabilidade — **transformar** as entradas (transações, config,
tabela) — e a classe-base cuida do resto: reexecutar ``decompor_margem``
com os parâmetros alterados e comparar antes/depois. Nada de fórmula
paralela: o mesmo motor calculado e testado produz o "antes" e o
"depois", e a diferença é o impacto.

Cenários da v1:

- :class:`CenarioComissao` — comissão dos marketplaces sobe (+2 p.p.);
- :class:`CenarioAntecipacao` — custo de antecipação sobe (Selic +3 p.p. a.a.);
- :class:`CenarioDevolucoesDobram` — devoluções/inadimplência dobram;
- :class:`CenarioMudancaAnexo` — reenquadramento no Simples;
- :class:`CenarioMigracaoCanal` — parte das vendas migra de marketplace
  para canal próprio ("e se 30% do ML virasse loja própria?").

Para criar um cenário novo, basta herdar de :class:`Cenario` e
implementar ``transformar`` — a comparação e o invariante contábil vêm
de graça. As funções ``cenario_*`` são atalhos finos mantidos por
compatibilidade.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from decimal import Decimal

from carchuna.margem import (
    ConfigTributaria,
    DecomposicaoMargem,
    TabelaCustos,
    Transacao,
    decompor_margem,
)

_Entradas = tuple[list[Transacao], ConfigTributaria, TabelaCustos]


@dataclass(frozen=True)
class ResultadoCenario:
    """Margem antes e depois de um choque, com o impacto isolado."""

    nome: str
    base: DecomposicaoMargem
    cenario: DecomposicaoMargem
    impacto_reais: Decimal  # variação da margem líquida (negativo = piora)
    impacto_pp: Decimal  # variação da margem %, em pontos percentuais


class Cenario(ABC):
    """Classe-base dos cenários: transforma entradas, o motor faz o resto."""

    @property
    @abstractmethod
    def nome(self) -> str:
        """Nome legível do cenário (aparece no dashboard e no PDF)."""

    @abstractmethod
    def transformar(
        self,
        transacoes: list[Transacao],
        config: ConfigTributaria,
        tabela: TabelaCustos,
    ) -> _Entradas:
        """Devolve as entradas alteradas pelo choque deste cenário."""

    def executar(
        self,
        transacoes: list[Transacao],
        config: ConfigTributaria,
        tabela: TabelaCustos | None = None,
    ) -> ResultadoCenario:
        """Roda o motor de margem no estado atual e no estado chocado."""
        tabela = tabela or TabelaCustos()
        base = decompor_margem(transacoes, config, tabela)
        novo = decompor_margem(*self.transformar(transacoes, config, tabela))
        return ResultadoCenario(
            nome=self.nome,
            base=base,
            cenario=novo,
            impacto_reais=novo.margem_liquida - base.margem_liquida,
            impacto_pp=novo.margem_pct - base.margem_pct,
        )


def _copiar_tabela(tabela: TabelaCustos, **mudancas) -> TabelaCustos:
    campos = {
        "comissao_canal": dict(tabela.comissao_canal),
        "taxa_adquirencia": tabela.taxa_adquirencia,
        "taxa_antecipacao_mensal": tabela.taxa_antecipacao_mensal,
        "canais_com_adquirencia": tabela.canais_com_adquirencia,
    }
    campos.update(mudancas)
    return TabelaCustos(**campos)


class CenarioComissao(Cenario):
    """Comissão de todos os marketplaces sobe ``delta_pp`` (0.02 = +2 p.p.)."""

    def __init__(self, delta_pp: Decimal = Decimal("0.02")):
        self.delta_pp = delta_pp

    @property
    def nome(self) -> str:
        pct = (self.delta_pp * 100).quantize(Decimal("0.01"))
        return f"Comissão dos marketplaces +{pct} p.p."

    def transformar(self, transacoes, config, tabela) -> _Entradas:
        nova_tabela = _copiar_tabela(
            tabela,
            comissao_canal={
                canal: (pct + self.delta_pp if pct > 0 else pct)
                for canal, pct in tabela.comissao_canal.items()
            },
        )
        # Comissões observadas no extrato também sobem delta_pp sobre o valor.
        novas_transacoes = [
            (
                replace(
                    t,
                    comissao_cobrada=t.comissao_cobrada + t.valor_bruto * self.delta_pp,
                )
                if t.comissao_cobrada is not None
                else t
            )
            for t in transacoes
        ]
        return novas_transacoes, config, nova_tabela


class CenarioAntecipacao(Cenario):
    """Custo anual de antecipação sobe ``delta_ano`` (ex.: Selic +3 p.p. a.a.).

    O repasse é aproximado por ``delta_ano / 12`` na taxa mensal —
    aproximação linear documentada (juros compostos ficam para a v2).
    """

    def __init__(self, delta_ano: Decimal = Decimal("0.03")):
        self.delta_ano = delta_ano

    @property
    def nome(self) -> str:
        pct = (self.delta_ano * 100).quantize(Decimal("0.01"))
        return f"Antecipação +{pct} p.p. ao ano (efeito Selic)"

    def transformar(self, transacoes, config, tabela) -> _Entradas:
        nova_tabela = _copiar_tabela(
            tabela,
            taxa_antecipacao_mensal=tabela.taxa_antecipacao_mensal
            + self.delta_ano / 12,
        )
        return transacoes, config, nova_tabela


class CenarioDevolucoesDobram(Cenario):
    """Devoluções dobram: marca mais vendas como devolvidas até ~2× o valor.

    Heurística determinística e transparente: percorre as vendas não
    devolvidas em ordem de data e vai marcando como devolvidas até o
    valor devolvido alcançar o dobro do observado. Se hoje não há
    nenhuma devolução, usa 3% da receita como base (taxa típica de
    e-commerce usada nos dados sintéticos).
    """

    @property
    def nome(self) -> str:
        return "Devoluções/inadimplência dobram"

    def transformar(self, transacoes, config, tabela) -> _Entradas:
        base = decompor_margem(transacoes, config, tabela)
        valor_atual = base.deducao("devolucoes").valor
        alvo = (
            valor_atual * 2 if valor_atual > 0 else base.receita_bruta * Decimal("0.03")
        )
        novas: list[Transacao] = []
        devolvido = valor_atual
        for t in sorted(transacoes, key=lambda t: (t.data, t.valor_bruto)):
            if not t.devolvida and devolvido < alvo:
                devolvido += t.valor_bruto
                novas.append(replace(t, devolvida=True))
            else:
                novas.append(t)
        return novas, config, tabela


class CenarioMudancaAnexo(Cenario):
    """Reenquadramento em outro anexo do Simples (LC 123/2006, art. 18)."""

    def __init__(self, novo_anexo: str = "III"):
        self.novo_anexo = novo_anexo

    @property
    def nome(self) -> str:
        return f"Mudança para o Anexo {self.novo_anexo} do Simples"

    def transformar(self, transacoes, config, tabela) -> _Entradas:
        if config.regime != "simples":
            raise ValueError("Cenário de anexo só se aplica ao regime Simples.")
        nova_config = ConfigTributaria(
            regime="simples", anexo_simples=self.novo_anexo, rbt12=config.rbt12
        )
        return transacoes, nova_config, tabela


class CenarioMigracaoCanal(Cenario):
    """Parte das vendas de um canal migra para outro (ex.: ML → loja própria).

    Responde a pergunta da simulação da review: "se eu migrar 30% das
    vendas do marketplace para canal próprio, quanto sobe a margem?".
    Determinístico: percorre as vendas do canal de origem em ordem de
    data e troca o canal até atingir a fração pedida do valor bruto. As
    vendas migradas perdem a comissão de marketplace e passam a pagar
    adquirência/antecipação como o canal de destino.
    """

    def __init__(
        self,
        origem: str = "mercado_livre",
        destino: str = "loja_propria",
        fracao: Decimal = Decimal("0.30"),
    ):
        if not Decimal("0") < fracao <= Decimal("1"):
            raise ValueError(f"`fracao` deve estar em (0, 1], recebeu {fracao}.")
        self.origem = origem
        self.destino = destino
        self.fracao = fracao

    @property
    def nome(self) -> str:
        pct = (self.fracao * 100).quantize(Decimal("1"))
        return f"Migração de {pct}% das vendas de {self.origem} para {self.destino}"

    def transformar(self, transacoes, config, tabela) -> _Entradas:
        valor_origem = sum(
            (t.valor_bruto for t in transacoes if t.canal == self.origem),
            Decimal("0"),
        )
        alvo = valor_origem * self.fracao
        migrado = Decimal("0")
        novas: list[Transacao] = []
        for t in sorted(transacoes, key=lambda t: (t.data, t.valor_bruto)):
            if t.canal == self.origem and migrado < alvo:
                migrado += t.valor_bruto
                # no canal próprio não há comissão observada de marketplace
                novas.append(replace(t, canal=self.destino, comissao_cobrada=None))
            else:
                novas.append(t)
        return novas, config, tabela


def _rbt12_proporcional(
    config: ConfigTributaria,
    base: list[Transacao],
    cenario: list[Transacao],
) -> ConfigTributaria:
    """RBT12 do cenário, na mesma proporção em que a receita mudou.

    A alíquota efetiva do Simples sai da receita bruta acumulada dos doze
    meses anteriores (LC 123/2006, art. 18, § 1º e § 1º-A). Um cenário que
    move a receita move essa base junto — e os cenários que a moviam
    devolviam a ``rbt12`` original, congelada.

    O erro tem direção, e é a pior das duas. Aumentar 5% no preço com a
    RBT12 parada mantém a loja na faixa antiga: o tributo do cenário sai
    menor do que seria, e a margem simulada sai maior. A tela responderia
    "aumentar o preço rende X" com X inflado — bem no número que o lojista
    usa para decidir aumentar o preço. Perto de uma virada de faixa o
    engano é grosso: subir da 1ª para a 2ª faixa do Anexo I custa 0,83
    ponto de margem que a simulação simplesmente não mostrava.

    A proporção usa a receita **sem as devoluções**, que é a base que
    ``rbt12_movel`` acumula (art. 3º, § 1º), para o cenário e o real
    medirem a mesma coisa.

    Isto é premissa, não previsão, e a premissa é forte: supõe que os doze
    meses anteriores mudariam na mesma proporção do período simulado. Vale
    quando o cenário é um regime novo que já vinha valendo — um reajuste
    de tabela, um canal que cresceu — e não vale para um pico de um mês
    só. Congelar a RBT12 também é premissa, e é a que erra a favor da
    tela: entre as duas, prefiro a que erra contra.

    Fora do Simples não há o que fazer: no MEI o DAS é fixo e não tem
    faixa (art. 18-A, § 3º, V).
    """
    if config.regime != "simples" or config.rbt12 <= 0:
        return config
    receita_base = sum((t.valor_bruto for t in base if not t.devolvida), Decimal("0"))
    if receita_base <= 0:
        return config
    receita_cenario = sum(
        (t.valor_bruto for t in cenario if not t.devolvida), Decimal("0")
    )
    nova = (config.rbt12 * receita_cenario / receita_base).quantize(Decimal("0.01"))
    return replace(config, rbt12=nova)


class CenarioCrescimentoCanal(Cenario):
    """Vendas de um canal crescem ``fracao`` (ex.: +20% na loja própria).

    A pergunta de crescimento: "se eu vender X% a mais no canal Y,
    quanto sobra?". Determinístico e transparente: replica vendas
    existentes do canal (em ordem de data) até somar a fração pedida do
    valor bruto — o crescimento herda o mix real de produtos, custos e
    prazos do canal, em vez de inventar vendas médias. Premissa, não
    previsão: a demanda extra é hipótese do usuário.

    A **RBT12 acompanha** a receita do cenário, na mesma proporção (ver
    ``_rbt12_proporcional``). Crescer sem mover a base do Simples manteria
    a loja na faixa antiga e devolveria uma margem maior que a real,
    justamente no número que o lojista usa para decidir crescer.
    """

    def __init__(self, canal: str = "loja_propria", fracao: Decimal = Decimal("0.20")):
        if not Decimal("0") < fracao <= Decimal("1"):
            raise ValueError(f"`fracao` deve estar em (0, 1], recebeu {fracao}.")
        self.canal = canal
        self.fracao = fracao

    @property
    def nome(self) -> str:
        pct = (self.fracao * 100).quantize(Decimal("1"))
        return f"Vender {pct}% a mais em {self.canal}"

    def transformar(self, transacoes, config, tabela) -> _Entradas:
        do_canal = sorted(
            (t for t in transacoes if t.canal == self.canal and not t.devolvida),
            key=lambda t: (t.data, t.valor_bruto),
        )
        if not do_canal:
            raise ValueError(f"não há vendas efetivas no canal {self.canal!r}.")
        alvo = sum((t.valor_bruto for t in do_canal), Decimal("0")) * self.fracao
        extras: list[Transacao] = []
        adicionado = Decimal("0")
        for t in do_canal:
            if adicionado >= alvo:
                break
            extras.append(t)
            adicionado += t.valor_bruto
        todas = list(transacoes) + extras
        return todas, _rbt12_proporcional(config, list(transacoes), todas), tabela


class CenarioPreco(Cenario):
    """Todos os preços sobem ``delta`` (0.05 = +5%), com o MESMO volume.

    A alavanca mais direta do lojista: o motor recalcula imposto e
    comissão sobre o preço novo (comissões observadas no extrato são
    percentuais e escalam junto). Premissa explícita e honesta: volume
    constante — estimar quanto de venda se perde com preço maior
    (elasticidade) exige histórico de variação de preço e é roadmap.

    A **RBT12 acompanha** o preço novo, na mesma proporção (ver
    ``_rbt12_proporcional``). Sem isso o cenário mantinha a loja na faixa
    antiga do Simples e devolvia um ganho inflado — o erro caía do lado de
    recomendar o aumento.
    """

    def __init__(self, delta: Decimal = Decimal("0.05")):
        self.delta = delta

    @property
    def nome(self) -> str:
        pct = (self.delta * 100).quantize(Decimal("1"))
        return f"Aumentar os preços em {pct}% (mesmo volume)"

    def transformar(self, transacoes, config, tabela) -> _Entradas:
        fator = Decimal("1") + self.delta
        novas = [
            replace(
                t,
                valor_bruto=(t.valor_bruto * fator).quantize(Decimal("0.01")),
                comissao_cobrada=(
                    (t.comissao_cobrada * fator).quantize(Decimal("0.01"))
                    if t.comissao_cobrada is not None
                    else None
                ),
            )
            for t in transacoes
        ]
        return novas, _rbt12_proporcional(config, list(transacoes), novas), tabela


CENARIOS_PADRAO: tuple[type[Cenario], ...] = (
    CenarioPreco,
    CenarioComissao,
    CenarioAntecipacao,
    CenarioDevolucoesDobram,
    CenarioMudancaAnexo,
    CenarioMigracaoCanal,
)


def rodar_cenarios_padrao(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
) -> list[ResultadoCenario]:
    """Roda a bateria padrão de cenários (a "página de stress" do relatório).

    **Cenário que não roda é omitido da lista, não derruba a bateria.**
    Um cenário é uma pergunta hipotética, e nem toda hipótese cabe nos
    dados: subir o preço de um MEI que já está perto do teto produz um
    ano acima do limite, migrar canal exige que o canal de origem tenha
    venda. Antes, o primeiro cenário impossível levava junto os outros
    cinco — e a aba inteira de simulação sumia por causa de uma pergunta
    que não se aplicava àquela loja.

    A omissão é silenciosa **aqui de propósito**: quem chama sabe quais
    cenários pediu e vê quais voltaram. Não invento um resultado com
    aviso no meio da lista, porque a lista é de números comparáveis entre
    si e um item "não deu" ali dentro só serve para ser somado por
    engano.
    """
    cenarios: list[Cenario] = [
        CenarioPreco(),
        CenarioComissao(),
        CenarioAntecipacao(),
        CenarioDevolucoesDobram(),
    ]
    if config.regime == "simples":
        outro = "III" if config.anexo_simples != "III" else "I"
        cenarios.append(CenarioMudancaAnexo(outro))
    if any(t.canal == "mercado_livre" for t in transacoes):
        cenarios.append(CenarioMigracaoCanal())

    resultados: list[ResultadoCenario] = []
    for cenario in cenarios:
        try:
            resultados.append(cenario.executar(transacoes, config, tabela))
        except (ValueError, TypeError):
            continue
    return resultados


# ---------------------------------------------------------------------------
# Atalhos funcionais mantidos por compatibilidade de API
# ---------------------------------------------------------------------------


def cenario_comissao(
    transacoes, config, tabela=None, delta_pp: Decimal = Decimal("0.02")
) -> ResultadoCenario:
    """Atalho para ``CenarioComissao(delta_pp).executar(...)``."""
    return CenarioComissao(delta_pp).executar(transacoes, config, tabela)


def cenario_antecipacao(
    transacoes, config, tabela=None, delta_ano: Decimal = Decimal("0.03")
) -> ResultadoCenario:
    """Atalho para ``CenarioAntecipacao(delta_ano).executar(...)``."""
    return CenarioAntecipacao(delta_ano).executar(transacoes, config, tabela)


def cenario_devolucoes_dobram(transacoes, config, tabela=None) -> ResultadoCenario:
    """Atalho para ``CenarioDevolucoesDobram().executar(...)``."""
    return CenarioDevolucoesDobram().executar(transacoes, config, tabela)


def cenario_mudanca_anexo(
    transacoes, config, tabela=None, novo_anexo: str = "III"
) -> ResultadoCenario:
    """Atalho para ``CenarioMudancaAnexo(novo_anexo).executar(...)``."""
    return CenarioMudancaAnexo(novo_anexo).executar(transacoes, config, tabela)


def cenario_migracao_canal(
    transacoes,
    config,
    tabela=None,
    origem: str = "mercado_livre",
    destino: str = "loja_propria",
    fracao: Decimal = Decimal("0.30"),
) -> ResultadoCenario:
    """Atalho para ``CenarioMigracaoCanal(...).executar(...)``."""
    return CenarioMigracaoCanal(origem, destino, fracao).executar(
        transacoes, config, tabela
    )
