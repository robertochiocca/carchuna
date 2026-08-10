"""Fachada orientada a objetos da Carchuna: ``AnalisadorMargem``.

Um único objeto reúne os quatro motores (margem, métricas, cenários,
diagnóstico) sobre um conjunto de vendas — a "inteligência de margem" do
produto: importa os dados, reconstrói a margem venda a venda, resume
onde o lucro morreu, simula alternativas e só então chama a camada
legal/IA para explicar. **A IA entra depois do cálculo, nunca antes.**

Uso típico::

    analise = AnalisadorMargem.demo(meses=6)          # ou .de_arquivo(...)
    analise.resumo_executivo().frase()
    # "No período de 7 mês(es), R$ 833.092,65 de margem se perderam entre
    #  a margem anunciada (41.90%) e a real (13.36%); 35% dessa perda
    #  veio de Comissões de canal."
    analise.margem_por_venda()[0].margem_liquida      # venda a venda
    analise.cenarios()                                # simulações
    analise.diagnosticar()                            # achados com base legal
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import cached_property

from carchuna.cenarios import Cenario, ResultadoCenario, rodar_cenarios_padrao
from carchuna.dados import carregar_transacoes, transacoes_sinteticas
from carchuna.diagnostico import (
    Achado,
    MotorDiagnostico,
    ParametrosDiagnostico,
)
from carchuna.margem import (
    BASE_VARIAVEL,
    ROTULOS_DEDUCOES,
    ConfigTributaria,
    DecomposicaoMargem,
    TabelaCustos,
    Transacao,
    config_do_subconjunto,
    decompor_margem,
)
from carchuna.metricas import (
    JanelaRBT12,
    instabilidade_margem,
    lucro_acumulado,
    maior_queda_margem,
    margem_mensal,
    rbt12_por_mes,
    serie_margem_pct,
)
from carchuna.metricas import procedencia_rbt12 as _procedencia_rbt12
from carchuna.rag.retrieval import Retriever


def _brl(valor: Decimal) -> str:
    """Formata em moeda brasileira: Decimal('1234.5') → 'R$ 1.234,50'."""
    inteiro, _, centavos = f"{valor:.2f}".partition(".")
    sinal = "-" if inteiro.startswith("-") else ""
    inteiro = inteiro.lstrip("-")
    grupos = []
    while inteiro:
        grupos.append(inteiro[-3:])
        inteiro = inteiro[:-3]
    return f"{sinal}R$ {'.'.join(reversed(grupos))},{centavos}"


@dataclass(frozen=True)
class FontePerda:
    """Uma dedução vista como fonte de perda de margem."""

    nome: str
    rotulo: str
    valor: Decimal
    pct_da_perda: Decimal  # participação na perda total (ex.: 62.0)


@dataclass(frozen=True)
class ResumoExecutivo:
    """A resposta da review em números: quanto se perdeu e de onde veio.

    "Margem anunciada" é a conta ingênua que o lojista faz (receita −
    custo do produto); "margem real" é o que sobra depois de impostos,
    comissões, adquirência, antecipação, frete e devoluções. A diferença
    entre as duas é a **perda de margem**, decomposta por fonte.
    """

    meses: int
    receita_bruta: Decimal
    margem_anunciada: Decimal  # receita − CMV (a conta ingênua)
    margem_anunciada_pct: Decimal
    margem_real: Decimal  # margem líquida calculada
    margem_real_pct: Decimal
    perda_total: Decimal  # anunciada − real
    fontes_perda: tuple[FontePerda, ...]  # ordenadas por valor decrescente

    @property
    def maior_fonte(self) -> FontePerda:
        return self.fontes_perda[0]

    def frase(self) -> str:
        """O diagnóstico em uma frase, no formato pedido pela review."""
        maior = self.maior_fonte
        return (
            f"No período de {self.meses} mês(es), {_brl(self.perda_total)} de "
            f"margem se perderam entre a margem anunciada "
            f"({self.margem_anunciada_pct}%) e a real ({self.margem_real_pct}%); "
            f"{maior.pct_da_perda.quantize(Decimal('1'))}% dessa perda veio de "
            f"{maior.rotulo}."
        )


@dataclass(frozen=True)
class MargemVenda:
    """A margem real de UMA venda — o MVP da review: venda a venda."""

    transacao: Transacao
    decomposicao: DecomposicaoMargem

    @property
    def margem_liquida(self) -> Decimal:
        return self.decomposicao.margem_liquida

    @property
    def margem_pct(self) -> Decimal:
        return self.decomposicao.margem_pct


@dataclass(frozen=True)
class ResumoProduto:
    """A margem real agregada de um produto (ou canal, na falta do nome)."""

    nome: str
    vendas: int
    devolvidas: int
    receita: Decimal
    margem: Decimal
    margem_pct: Decimal


class AnalisadorMargem:
    """Fachada dos motores da Carchuna sobre um conjunto de vendas.

    Guarda transações, configuração tributária e tabela de custos, e
    expõe cada análise como método; resultados caros ficam em cache.
    O objeto é imutável na prática: para outra base de vendas ou outra
    configuração, crie outro analisador.
    """

    def __init__(
        self,
        transacoes: list[Transacao],
        config: ConfigTributaria,
        tabela: TabelaCustos | None = None,
        parametros: ParametrosDiagnostico | None = None,
        retriever: Retriever | None = None,
        rbt12_movel: bool = False,
        confirmar_lacunas: bool = False,
        origem: str | None = None,
    ):
        if not transacoes:
            raise ValueError("`transacoes` não pode ser vazio.")
        self.transacoes = list(transacoes)
        self.config = config
        self.tabela = tabela or TabelaCustos()
        self.parametros = parametros or ParametrosDiagnostico()
        self._retriever = retriever
        # Rastreabilidade: de onde os dados vieram e quando o cálculo rodou.
        self.origem = origem or "origem não informada"
        self.criado_em = datetime.now()
        # Tributar cada mês pela RBT12 dos seus 12 meses anteriores
        # (LC 123/2006, art. 18, § 1º) em vez de repetir a informada.
        # Só afeta a série mensal; o total do período segue a informada,
        # porque a janela de 12 meses do período inteiro não existe.
        self.rbt12_movel = rbt12_movel
        # O lojista confirmou que os meses vazios do MEIO da janela foram
        # faturamento zero, e não dado que faltou. Só ele pode responder
        # isso; enquanto não responde, vale a RBT12 informada.
        self.confirmar_lacunas = confirmar_lacunas

    # -- construtores alternativos ------------------------------------------

    @classmethod
    def de_arquivo(
        cls,
        source,
        config: ConfigTributaria,
        tabela: TabelaCustos | None = None,
        name: str | None = None,
        **kwargs,
    ) -> AnalisadorMargem:
        """Cria o analisador direto de um CSV/JSON/XLSX de vendas."""
        kwargs.setdefault("origem", name or str(source))
        return cls(carregar_transacoes(source, name=name), config, tabela, **kwargs)

    @classmethod
    def demo(
        cls,
        meses: int = 6,
        config: ConfigTributaria | None = None,
        tabela: TabelaCustos | None = None,
        seed: int = 7,
        **kwargs,
    ) -> AnalisadorMargem:
        """Analisador com dados sintéticos reprodutíveis (roda offline)."""
        config = config or ConfigTributaria(
            regime="simples", anexo_simples="I", rbt12=Decimal("4200000")
        )
        kwargs.setdefault("origem", f"dados sintéticos de exemplo (seed {seed})")
        return cls(
            transacoes_sinteticas(meses=meses, seed=seed), config, tabela, **kwargs
        )

    # -- margem --------------------------------------------------------------

    @cached_property
    def decomposicao(self) -> DecomposicaoMargem:
        """Decomposição da margem do período inteiro."""
        return decompor_margem(self.transacoes, self.config, self.tabela)

    @cached_property
    def mensal(self) -> dict[str, DecomposicaoMargem]:
        """Decomposição mês a mês ("AAAA-MM")."""
        return margem_mensal(
            self.transacoes,
            self.config,
            self.tabela,
            usar_rbt12_movel=self.rbt12_movel,
            confirmar_lacunas=self.confirmar_lacunas,
        )

    def composicao_deducao(self, nome: str) -> dict[str, list[tuple[str, Decimal]]]:
        """De onde vem uma dedução: quebra por canal e por mês.

        Alimenta o drill-down do raio-X (clicar numa barra abre a
        composição dela). ``por_canal`` traz só canais com valor > 0,
        do maior para o menor; ``por_mes`` segue a ordem do calendário.

        No MEI, o DAS é fixo mensal e não é rateável por canal (mesma
        convenção de ``margem_por_venda``): a quebra de ``tributos`` por
        canal fica vazia e o valor cheio aparece na quebra por mês.
        """
        # Terceiro caso da regra de `config_do_subconjunto`, e o único que
        # ela NÃO resolve: aqui o DAS sairia publicado como valor em reais
        # de um canal ("tributos da Shopee: R$ 76"), que é afirmar um fato
        # que o dado não tem. A linha é suprimida, não repartida.
        config = self.config
        if config.regime == "mei" and nome == "tributos":
            config = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("0"))
        por_canal_grupos: dict[str, list[Transacao]] = {}
        for t in self.transacoes:
            por_canal_grupos.setdefault(t.canal, []).append(t)
        por_canal = [
            (canal, decompor_margem(grupo, config, self.tabela).deducao(nome).valor)
            for canal, grupo in por_canal_grupos.items()
        ]
        por_canal = sorted([(c, v) for c, v in por_canal if v > 0], key=lambda x: -x[1])
        # Cada canal é decomposto sozinho e arredondado sozinho; o número da
        # tela é arredondado uma vez só, sobre a soma. A diferença é resíduo
        # de arredondamento — no máximo um centavo por canal — e ela precisa
        # sumir: a quebra existe para explicar o número da tela, e uma quebra
        # que soma diferente do que ela explica é pior que quebra nenhuma.
        # O resíduo vai para o maior canal, onde é proporcionalmente menor.
        if por_canal:
            residuo = self.decomposicao.deducao(nome).valor - sum(
                v for _, v in por_canal
            )
            if residuo:
                canal, valor = por_canal[0]
                por_canal[0] = (canal, valor + residuo)
        por_mes = [(mes, d.deducao(nome).valor) for mes, d in self.mensal.items()]
        return {"por_canal": por_canal, "por_mes": por_mes}

    @cached_property
    def rbt12_mensal(self) -> dict[str, Decimal | None]:
        """RBT12 móvel de cada mês; ``None`` onde o arquivo não cobre a janela.

        Serve para a tela dizer de onde veio a alíquota de cada mês em
        vez de o lojista ter que adivinhar. Para saber POR QUE um mês deu
        ``None`` — e quais meses estão vazios no meio da janela —, use
        ``procedencia_rbt12``.
        """
        return rbt12_por_mes(self.transacoes, confirmar_lacunas=self.confirmar_lacunas)

    @cached_property
    def procedencia_rbt12(self) -> dict[str, JanelaRBT12]:
        """De onde saiu a RBT12 de cada mês, com as lacunas nomeadas.

        É o que permite a tela perguntar ao lojista "março/2026 está sem
        lançamentos: foi mês sem faturamento ou o arquivo está
        incompleto?" — e registrar a resposta dele no resultado.
        """
        return _procedencia_rbt12(
            self.transacoes, confirmar_lacunas=self.confirmar_lacunas
        )

    def margem_por_venda(self) -> list[MargemVenda]:
        """A margem real de cada venda, decomposta pelo mesmo motor testado.

        No Simples, os tributos por venda usam a alíquota efetiva. No
        MEI o DAS é fixo mensal e não é rateável por venda — a visão por
        venda considera tributos = 0 e o valor cheio segue na visão
        mensal (``decomposicao``/``mensal``).
        """
        config = config_do_subconjunto(
            self.config, self.transacoes, self.transacoes, base=BASE_VARIAVEL
        )
        return [
            MargemVenda(t, decompor_margem([t], config, self.tabela))
            for t in self.transacoes
        ]

    def margem_por_produto(self) -> list[ResumoProduto]:
        """Margem real agregada por produto — campeões e vilões do catálogo.

        Agrupa a visão venda a venda pelo campo ``produto`` (quando o
        arquivo não traz produto, agrupa por canal). Ordenado da maior
        para a menor margem em reais; produtos com margem negativa são
        os candidatos a reprecificação.
        """
        grupos: dict[str, list[MargemVenda]] = {}
        for venda in self.margem_por_venda():
            chave = venda.transacao.produto or venda.transacao.canal
            grupos.setdefault(chave, []).append(venda)
        resumos = []
        for nome, vendas in grupos.items():
            receita = sum((v.transacao.valor_bruto for v in vendas), Decimal("0"))
            margem = sum((v.margem_liquida for v in vendas), Decimal("0"))
            pct = (
                (margem / receita * 100).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if receita
                else Decimal("0")
            )
            resumos.append(
                ResumoProduto(
                    nome=nome,
                    vendas=len(vendas),
                    devolvidas=sum(1 for v in vendas if v.transacao.devolvida),
                    receita=receita,
                    margem=margem,
                    margem_pct=pct,
                )
            )
        return sorted(resumos, key=lambda r: r.margem, reverse=True)

    def resumo_executivo(self) -> ResumoExecutivo:
        """Quanto de margem se perdeu no período — e de onde veio a perda."""
        d = self.decomposicao
        cmv = d.deducao("cmv").valor
        anunciada = d.receita_bruta - cmv
        perdas = [x for x in d.deducoes if x.nome != "cmv"]
        perda_total = sum((x.valor for x in perdas), Decimal("0"))
        fontes = tuple(
            FontePerda(
                nome=x.nome,
                rotulo=ROTULOS_DEDUCOES.get(x.nome, x.nome),
                valor=x.valor,
                pct_da_perda=(
                    (x.valor / perda_total * 100).quantize(
                        Decimal("0.1"), rounding=ROUND_HALF_UP
                    )
                    if perda_total
                    else Decimal("0")
                ),
            )
            for x in sorted(perdas, key=lambda x: x.valor, reverse=True)
        )
        pct = (
            (anunciada / d.receita_bruta * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if d.receita_bruta
            else Decimal("0")
        )
        meses = len({(t.data.year, t.data.month) for t in self.transacoes})
        return ResumoExecutivo(
            meses=meses,
            receita_bruta=d.receita_bruta,
            margem_anunciada=anunciada,
            margem_anunciada_pct=pct,
            margem_real=d.margem_liquida,
            margem_real_pct=d.margem_pct,
            perda_total=perda_total,
            fontes_perda=fontes,
        )

    # -- métricas ------------------------------------------------------------

    @cached_property
    def serie(self) -> list[tuple[str, Decimal]]:
        return serie_margem_pct(self.mensal)

    def maior_queda(self) -> Decimal:
        return maior_queda_margem(self.serie)

    def instabilidade(self) -> Decimal:
        return instabilidade_margem(self.serie)

    def lucro_acumulado(self) -> list[tuple[str, Decimal]]:
        return lucro_acumulado(self.mensal)

    # -- simulação -----------------------------------------------------------

    def simular(self, cenario: Cenario) -> ResultadoCenario:
        """Executa um cenário avulso (qualquer subclasse de ``Cenario``)."""
        return cenario.executar(self.transacoes, self.config, self.tabela)

    def cenarios(self) -> list[ResultadoCenario]:
        """A bateria padrão de cenários de stress."""
        return rodar_cenarios_padrao(self.transacoes, self.config, self.tabela)

    # -- diagnóstico legal (a IA entra DEPOIS do cálculo) --------------------

    @cached_property
    def retriever(self) -> Retriever:
        return self._retriever or Retriever()

    def diagnosticar(self) -> list[Achado]:
        """Achados das regras de detecção, com base legal citada."""
        motor = MotorDiagnostico(retriever=self.retriever, parametros=self.parametros)
        return motor.diagnosticar(self.transacoes, self.config, self.tabela)

    # -- crescimento: como faturar mais, com prova ---------------------------

    def crescimento(self) -> list:
        """Oportunidades de faturar mais (mix de canais, preço, espaço fiscal)."""
        from carchuna.crescimento import MotorCrescimento

        motor = MotorCrescimento(retriever=self.retriever)
        return motor.sugerir(self.transacoes, self.config, self.tabela)

    # -- radar: o que mudou e quanto custou ----------------------------------

    def radar(self) -> list:
        """Sinais do radar: tendência, margem magra e mês fora do padrão."""
        from carchuna.insights import MotorInsights

        return MotorInsights().radar(self.transacoes, self.config, self.tabela)

    # -- linhagem: como chegamos a cada número -------------------------------

    def linhagem(self, nome: str | None = None):
        """Ficha de rastreabilidade dos números (todas, ou uma por nome).

        Responde "como a Carchuna chegou a este número?": arquivo de
        origem, colunas, transformações, fórmula com os parâmetros do
        caso, premissas, limitações e o momento do cálculo.
        """
        from carchuna.linhagem import montar_linhagem

        fichas = montar_linhagem(
            self.decomposicao,
            self.transacoes,
            self.config,
            self.tabela,
            origem_dados=self.origem,
            calculado_em=self.criado_em,
        )
        return fichas if nome is None else fichas[nome]

    def preco_sugerido(
        self,
        custo_produto,
        frete,
        canal: str,
        margem_alvo: Decimal = Decimal("0.10"),
    ) -> Decimal:
        """Preço que entrega a margem alvo neste canal (motor invertido)."""
        from carchuna.crescimento import preco_para_margem

        return preco_para_margem(
            custo_produto, frete, canal, self.config, self.tabela, margem_alvo
        )

    # -- relatório -----------------------------------------------------------

    def gerar_pdf(self, output, narrativa: str | None = None):
        """Relatório PDF de 3 páginas (requer matplotlib, extra ``viz``)."""
        from carchuna.relatorio import gerar_pdf_relatorio

        return gerar_pdf_relatorio(
            self.decomposicao,
            self.cenarios(),
            self.diagnosticar(),
            output,
            narrativa=narrativa,
        )
