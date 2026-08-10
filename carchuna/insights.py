"""Radar de margem: o que mudou, quanto custou e como foi detectado.

Duas camadas, num módulo só:

**Detecção** (estatística, sem caixa preta) — z-score do mês contra o
histórico, cerca de IQR (quartis ± 1,5×IQR), média móvel de 3 meses para
a economia unitária, e a regra de divergência "receita subiu e o lucro
caiu". Cada método carrega o próprio limiar e o próprio mínimo de meses.

**Narrativa e severidade** — o que aconteceu, o esperado, o observado, o
desvio, o impacto em R$/mês calculado pelo motor de margem, e a nota de
confiança da rubrica de ``confianca.py``. Nenhum sinal chega ao lojista
sem essas seis coisas.

Por que a cerca de IQR e não 2σ
-------------------------------
A pergunta "este mês está fora do padrão?" tinha duas respostas neste
projeto: um corte em 2σ sobre a margem do mês, e um z-score com cerca de
IQR sobre cada dedução. Sobrou a segunda, por dois motivos.

O primeiro é estatístico: média e desvio-padrão são calculados com os
mesmos meses que se quer julgar, então um único mês atípico no histórico
infla σ e passa a esconder o mês seguinte. Os quartis não se movem com um
ponto extremo — e o histórico de um lojista real é curto e sujo, que é
exatamente o caso em que 2σ falha. Aqui a cerca de IQR tem poder de veto:
com 4+ meses de histórico, um sinal de 2σ que a cerca não confirma é
descartado. Acima de 3σ o sinal passa de qualquer forma.

O segundo é de produto: "a margem de maio fugiu do padrão" e "o CMV de
maio fugiu do padrão" são o mesmo acontecimento contado duas vezes, e a
segunda frase é a útil — ela nomeia a causa em vez do sintoma. Por isso a
detecção olha cada dedução, e o mês inteiro aparece pela dedução que se
mexeu. Dois sinais para um evento seria dívida no dia em que nascesse.

Decomposição STL fica para quando houver 24+ meses (dois ciclos
sazonais). Está documentado, não prometido.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from functools import cached_property

from carchuna.confianca import NotaConfianca, avaliar_confianca
from carchuna.margem import (
    BASE_RATEADA,
    ROTULOS_DEDUCOES,
    ConfigTributaria,
    TabelaCustos,
    Transacao,
    config_do_subconjunto,
    decompor_margem,
)
from carchuna.metricas import margem_mensal
from carchuna.validade import conferir_receita, variacao_percentual

AVISO_INSIGHTS = (
    "Sinais calculados dos seus números por regras transparentes, com o "
    "método de cada um declarado — são pistas para investigar, não "
    "veredito. Confirme a causa nos extratos antes de agir."
)

SEVERIDADES = ("critico", "atencao", "oportunidade")

# Mínimo de meses ANTERIORES para julgar o mês vigiado. Abaixo disso não
# existe "padrão" para fugir de: três pontos é o piso para uma média e um
# desvio dizerem alguma coisa.
MIN_MESES_HISTORICO = 3

# A partir daqui a cerca de IQR entra como método robusto (e ganha poder
# de veto sobre o z-score fraco). Com menos pontos os quartis são frágeis
# demais para arbitrar.
MIN_MESES_IQR = 4


@dataclass(frozen=True)
class Insight:
    """Um sinal do radar: o que houve, quanto custa, e como se sabe.

    ``base_evidencia`` é a natureza da evidência ("calculado" quando sai
    dos dados e da lei/tabela, "estimado" quando depende de premissa) e
    alimenta a rubrica; ``confianca`` é a nota que sai dela.

    A regra para escolher entre as duas: se algum número do sinal só
    existe porque se assumiu uma coisa que os dados não dizem — volume
    constante depois de um reajuste, o mês seguinte parecido com a média
    dos três anteriores — então é ``estimado``, e a nota cai 15 pontos.
    Um sinal que erra essa classificação para cima é pior que um sinal
    sem nota: ele empresta autoridade de dado a um palpite.
    """

    categoria: str
    severidade: str  # "critico" | "atencao" | "oportunidade"
    titulo: str
    explicacao: str
    impacto_mensal: Decimal  # R$/mês
    caminho_pratico: str
    base_evidencia: str  # "calculado" | "estimado"
    confianca: NotaConfianca
    # Esperado × observado com unidade, e como a diferença foi detectada.
    # Vazios nas análises que não comparam um mês contra um histórico.
    esperado: str = ""
    observado: str = ""
    desvio_pct: Decimal = Decimal("0")
    metodo: str = ""
    aviso: str = AVISO_INSIGHTS


@dataclass
class ParametrosInsights:
    """Limiar de cada método, editável e documentado."""

    # -- tendência entre o primeiro e o último mês (em p.p. da receita)
    tendencia_atencao_pp: Decimal = Decimal("1.5")
    tendencia_critico_pp: Decimal = Decimal("3")
    # -- margem de produto abaixo disto (e >= 0) é "magra"
    margem_magra_pct: Decimal = Decimal("8")
    reajuste_simulado: Decimal = Decimal("0.05")
    # -- mês fora do padrão (z-score, com a cerca de IQR arbitrando)
    z_atencao: Decimal = Decimal("2")
    z_critico: Decimal = Decimal("3")
    # com histórico constante (σ = 0) não há z; qualquer desvio acima
    # disto (em p.p. da receita) é fora do padrão
    limiar_pp_historico_constante: Decimal = Decimal("0.5")
    # -- economia unitária contra a média móvel de 3 meses
    limiar_var_unitaria: Decimal = Decimal("0.25")  # 25%
    # -- divergência: faturamento sobe e MARGEM cai, no mesmo mês.
    # O crescimento segue em % (receita é sempre positiva, então o
    # percentual não mente aqui). A queda vai em pontos de margem: 1 p.p.
    # num mês é o menor movimento que sobrevive ao ruído de mix de
    # produtos e ainda aparece no extrato do lojista.
    limiar_crescimento_receita_pct: Decimal = Decimal("5")
    limiar_queda_margem_pp: Decimal = Decimal("1")


def _q2(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q1(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Camada de detecção
# ---------------------------------------------------------------------------


def _media_desvio(valores: list[Decimal]) -> tuple[Decimal, Decimal]:
    n = Decimal(len(valores))
    media = sum(valores) / n
    if n < 2:
        return media, Decimal("0")
    variancia = sum((v - media) ** 2 for v in valores) / (n - 1)
    return media, variancia.sqrt()


def _quartis(valores: list[Decimal]) -> tuple[Decimal, Decimal]:
    """Q1 e Q3 por interpolação linear (método clássico dos quartis)."""
    ordenados = sorted(valores)
    n = len(ordenados)

    def _q(p: Decimal) -> Decimal:
        pos = (Decimal(n) - 1) * p
        i = int(pos)
        frac = pos - i
        if i + 1 < n:
            return ordenados[i] + (ordenados[i + 1] - ordenados[i]) * frac
        return ordenados[i]

    return _q(Decimal("0.25")), _q(Decimal("0.75"))


def _desvio_pct(esperado: Decimal, observado: Decimal) -> Decimal:
    if esperado == 0:
        return Decimal("0")
    return _q1((observado - esperado) / abs(esperado) * 100)


@dataclass(frozen=True)
class ForaDoPadrao:
    """O veredito da detecção: a referência, o tamanho do desvio e o método."""

    media: Decimal
    delta: Decimal  # observado − média (sinal preservado)
    forte: bool  # ≥ 3σ, ou histórico constante rompido
    metodo: str


def detectar_fora_do_padrao(
    historico: list[Decimal],
    observado: Decimal,
    parametros: ParametrosInsights,
) -> ForaDoPadrao | None:
    """O mês observado foge do padrão do histórico? (``None`` = não foge.)

    Único ponto do projeto que responde essa pergunta — de propósito. A
    ordem é: histórico constante → regra de p.p.; histórico com variação
    → z-score, arbitrado pela cerca de IQR quando há pontos suficientes
    (ver o docstring do módulo para o porquê da cerca).
    """
    if len(historico) < MIN_MESES_HISTORICO:
        return None
    media, desvio = _media_desvio(historico)
    delta = observado - media

    if desvio == 0:
        if abs(delta) <= parametros.limiar_pp_historico_constante:
            return None
        return ForaDoPadrao(
            media=media,
            delta=delta,
            forte=True,
            metodo=(
                f"histórico constante em {_q2(media)}% por {len(historico)} "
                f"meses; desvio de {_q2(abs(delta))} p.p. é fora do padrão"
            ),
        )

    z = abs(delta) / desvio
    if z < parametros.z_atencao:
        return None
    metodo = (
        f"z-score {_q1(z)}σ contra {len(historico)} meses de histórico "
        f"(média {_q2(media)}%, desvio {_q2(desvio)} p.p.)"
    )
    forte = z >= parametros.z_critico

    if len(historico) >= MIN_MESES_IQR:
        q1, q3 = _quartis(historico)
        iqr = q3 - q1
        cerca = iqr * Decimal("1.5")
        if observado > q3 + cerca or observado < q1 - cerca:
            metodo += "; cerca de IQR (quartis ± 1,5×IQR) ultrapassada"
        elif not forte:
            # sinal fraco que o método robusto não confirma: descarta
            return None
    return ForaDoPadrao(media=media, delta=delta, forte=forte, metodo=metodo)


# ---------------------------------------------------------------------------
# Camada de narrativa
# ---------------------------------------------------------------------------


@dataclass
class ContextoInsights:
    transacoes: list[Transacao]
    config: ConfigTributaria
    tabela: TabelaCustos
    parametros: ParametrosInsights

    @cached_property
    def mensal(self):
        """A série mensal, decomposta uma vez por radar.

        Três análises leem isto. Como ``@property`` simples, cada leitura
        redecompunha a base inteira — o mesmo trabalho, três vezes, num
        objeto que vive uma chamada só. ``AnalisadorMargem`` já usava
        ``cached_property`` para a mesma série.
        """
        return margem_mensal(self.transacoes, self.config, self.tabela)

    @cached_property
    def _notas(self) -> dict[str, NotaConfianca]:
        return {}

    def nota(self, base: str = "calculado") -> NotaConfianca:
        """Nota da base, memoizada por natureza de evidência.

        A rubrica só depende das transações e de ``base``, e ambas são
        fixas durante um radar — recalcular por sinal seria varrer a base
        inteira uma vez para cada linha da tela.
        """
        if base not in self._notas:
            self._notas[base] = avaliar_confianca(self.transacoes, base=base)
        return self._notas[base]


class AnaliseInsight(ABC):
    @abstractmethod
    def avaliar(self, ctx: ContextoInsights) -> list[Insight]:
        """Lista de insights (vazia quando não há sinal)."""


class TendenciaCustos(AnaliseInsight):
    """Deduções que cresceram como fatia da receita entre os meses.

    Não é detecção de anomalia: compara o primeiro mês com o último e
    mede a inclinação, que é a pergunta "isto está piorando devagar?".
    Um custo que sobe 1 p.p. por mês durante um ano nunca é anômalo em
    mês nenhum, e é o vazamento mais caro que existe.
    """

    def avaliar(self, ctx: ContextoInsights) -> list[Insight]:
        mensal = list(ctx.mensal.items())
        if len(mensal) < 2:
            return []
        (mes_a, dec_a), (mes_b, dec_b) = mensal[0], mensal[-1]
        insights = []
        for deducao in dec_b.deducoes:
            antes = dec_a.deducao(deducao.nome).pct_receita
            delta = deducao.pct_receita - antes
            if delta < ctx.parametros.tendencia_atencao_pp:
                continue
            severidade = (
                "critico" if delta >= ctx.parametros.tendencia_critico_pp else "atencao"
            )
            impacto = _q2(delta / 100 * dec_b.receita_bruta)
            rotulo = ROTULOS_DEDUCOES.get(deducao.nome, deducao.nome)
            insights.append(
                Insight(
                    categoria="tendencia_custos",
                    severidade=severidade,
                    titulo=f"{rotulo} subiu {delta} p.p. entre {mes_a} e {mes_b}",
                    explicacao=(
                        f"{rotulo} consumia {antes}% da receita em {mes_a} e "
                        f"passou a consumir {deducao.pct_receita}% em {mes_b}. "
                        f"No faturamento do último mês, essa alta equivale a "
                        f"R$ {impacto}/mês de lucro a menos."
                    ),
                    impacto_mensal=impacto,
                    caminho_pratico=(
                        "Abra o detalhamento desta dedução por canal e por mês "
                        "(clique na barra do raio-X) para localizar a origem da "
                        "alta antes de renegociar ou reprecificar."
                    ),
                    base_evidencia="calculado",
                    confianca=ctx.nota("calculado"),
                    esperado=f"{antes}% da receita (como em {mes_a})",
                    observado=f"{deducao.pct_receita}% da receita",
                    desvio_pct=_desvio_pct(antes, deducao.pct_receita),
                    metodo=(
                        f"comparação do primeiro com o último mês; alta de "
                        f"{delta} p.p. (limiares: "
                        f"{ctx.parametros.tendencia_atencao_pp} p.p. atenção, "
                        f"{ctx.parametros.tendencia_critico_pp} p.p. crítico)"
                    ),
                )
            )
        return insights


class ProdutosMargemMagra(AnaliseInsight):
    """Produtos com margem positiva porém magra, e o ganho de um reajuste."""

    def avaliar(self, ctx: ContextoInsights) -> list[Insight]:
        por_produto: dict[str, list[Transacao]] = {}
        for t in ctx.transacoes:
            por_produto.setdefault(t.produto or t.canal, []).append(t)
        magros: list[str] = []
        for nome, grupo in por_produto.items():
            # Margem por produto é lida contra o título da tela: rateada.
            d = decompor_margem(
                grupo,
                config_do_subconjunto(
                    ctx.config, grupo, ctx.transacoes, base=BASE_RATEADA
                ),
                ctx.tabela,
            )
            if Decimal("0") <= d.margem_pct < ctx.parametros.margem_magra_pct:
                magros.append(nome)
        if not magros:
            return []

        reajuste = ctx.parametros.reajuste_simulado
        alvo = set(magros)
        ajustadas = [
            (
                replace(
                    t,
                    valor_bruto=_q2(t.valor_bruto * (1 + reajuste)),
                    comissao_cobrada=(
                        _q2(t.comissao_cobrada * (1 + reajuste))
                        if t.comissao_cobrada is not None
                        else None
                    ),
                )
                if (t.produto or t.canal) in alvo
                else t
            )
            for t in ctx.transacoes
        ]
        base = decompor_margem(ctx.transacoes, ctx.config, ctx.tabela)
        novo = decompor_margem(ajustadas, ctx.config, ctx.tabela)
        meses = len({(t.data.year, t.data.month) for t in ctx.transacoes}) or 1
        ganho = _q2((novo.margem_liquida - base.margem_liquida) / meses)
        pct = (reajuste * 100).quantize(Decimal("1"))
        limiar = ctx.parametros.margem_magra_pct
        return [
            Insight(
                categoria="margem_magra",
                severidade="oportunidade",
                titulo=f"{len(magros)} produto(s) com margem abaixo de {limiar}%",
                explicacao=(
                    f"Estes produtos vendem sem prejuízo, mas deixam pouco: "
                    f"{', '.join(sorted(magros)[:5])}"
                    f"{'…' if len(magros) > 5 else ''}. Um reajuste de {pct}% "
                    f"nos preços deles — mantido o mesmo volume (premissa) — "
                    f"adicionaria cerca de R$ {ganho}/mês de lucro, recalculado "
                    "pelo motor com imposto e comissão sobre o preço novo."
                ),
                impacto_mensal=ganho,
                caminho_pratico=(
                    "Use a calculadora de preço (aba Crescer) para achar o "
                    "preço-alvo de cada um; teste o reajuste nos campeões de "
                    "venda primeiro."
                ),
                # o ganho depende da premissa de volume constante: pela
                # rubrica isso é evidência ESTIMADA, não calculada
                base_evidencia="estimado",
                confianca=ctx.nota("estimado"),
                esperado=f"margem de {limiar}% ou mais",
                observado=f"{len(magros)} produto(s) abaixo do limiar",
                metodo=(
                    f"margem por produto pelo motor; reajuste de {pct}% "
                    "simulado com o mesmo volume (premissa explícita)"
                ),
            )
        ]


class DeducaoForaDoPadrao(AnaliseInsight):
    """Cada dedução do último mês contra o próprio histórico.

    É aqui que mora a resposta a "este mês fugiu do padrão?" — nomeando
    a dedução que se mexeu, em vez de só dizer que a margem mudou.
    """

    def avaliar(self, ctx: ContextoInsights) -> list[Insight]:
        meses = list(ctx.mensal.items())
        if len(meses) < MIN_MESES_HISTORICO + 1:
            return []
        historico, (mes_atual, dec_atual) = meses[:-1], meses[-1]
        insights = []
        for deducao in dec_atual.deducoes:
            serie = [d.deducao(deducao.nome).pct_receita for _, d in historico]
            observado = deducao.pct_receita
            fora = detectar_fora_do_padrao(serie, observado, ctx.parametros)
            if fora is None:
                continue
            # dedução que CAI fora do padrão é boa notícia
            if fora.delta < 0:
                severidade = "oportunidade"
            else:
                severidade = "critico" if fora.forte else "atencao"
            impacto = _q2(abs(fora.delta) / 100 * dec_atual.receita_bruta)
            rotulo = ROTULOS_DEDUCOES.get(deducao.nome, deducao.nome)
            direcao = "subiu" if fora.delta > 0 else "caiu"
            insights.append(
                Insight(
                    categoria=f"{deducao.nome}_pct",
                    severidade=severidade,
                    titulo=f"{rotulo}: {direcao} fora do padrão em {mes_atual}",
                    explicacao=(
                        f"{rotulo} consumia em média {_q2(fora.media)}% da "
                        f"receita e em {mes_atual} consumiu {observado}%."
                    ),
                    impacto_mensal=impacto,
                    caminho_pratico=(
                        "Abra o drill-down desta dedução (clique na barra do "
                        "raio-X) e compare os extratos do mês com os anteriores."
                    ),
                    base_evidencia="calculado",
                    confianca=ctx.nota("calculado"),
                    esperado=f"{_q2(fora.media)}% da receita",
                    observado=f"{observado}% da receita",
                    desvio_pct=_desvio_pct(fora.media, observado),
                    metodo=fora.metodo,
                )
            )
        return insights


class FretePorPedido(AnaliseInsight):
    """Economia unitária: frete médio por pedido contra a média móvel."""

    def avaliar(self, ctx: ContextoInsights) -> list[Insight]:
        por_mes: dict[str, list[Transacao]] = {}
        for t in sorted(ctx.transacoes, key=lambda t: t.data):
            if t.devolvida:
                continue
            por_mes.setdefault(f"{t.data.year}-{t.data.month:02d}", []).append(t)
        if len(por_mes) < MIN_MESES_HISTORICO + 1:
            return []
        serie = [
            (mes, sum((t.frete_pago for t in grupo), Decimal("0")) / len(grupo))
            for mes, grupo in por_mes.items()
        ]
        historico = [v for _, v in serie[-4:-1]]  # média móvel de 3 meses
        mes_atual, observado = serie[-1]
        esperado = sum(historico) / Decimal(len(historico))
        if esperado == 0:
            return []
        variacao = (observado - esperado) / esperado
        if abs(variacao) < ctx.parametros.limiar_var_unitaria:
            return []
        pedidos = len(por_mes[mes_atual])
        impacto = abs(_q2((observado - esperado) * pedidos))
        return [
            Insight(
                categoria="frete_por_pedido",
                severidade="atencao" if variacao > 0 else "oportunidade",
                titulo=(
                    f"Frete por pedido anormalmente "
                    f"{'alto' if variacao > 0 else 'baixo'} em {mes_atual}"
                ),
                explicacao=(
                    f"O frete médio por pedido foi R$ {_q2(observado)} em "
                    f"{mes_atual}, contra R$ {_q2(esperado)} na média dos 3 "
                    f"meses anteriores ({pedidos} pedidos no mês)."
                ),
                impacto_mensal=impacto,
                caminho_pratico=(
                    "Confira tabela de frete, mix de regiões e peso dos "
                    "pedidos do mês; renegocie a faixa com a transportadora."
                ),
                # o "esperado" é a média móvel de 3 meses — uma projeção,
                # não um valor que os dados afirmem: evidência ESTIMADA
                base_evidencia="estimado",
                confianca=ctx.nota("estimado"),
                esperado=f"R$ {_q2(esperado)}/pedido",
                observado=f"R$ {_q2(observado)}/pedido",
                desvio_pct=_desvio_pct(esperado, observado),
                metodo=(
                    f"variação de {_q1(variacao * 100)}% contra a média móvel "
                    f"de 3 meses (limiar: "
                    f"{_q1(ctx.parametros.limiar_var_unitaria * 100)}%)"
                ),
            )
        ]


class ReceitaSobeLucroCai(AnaliseInsight):
    """A divergência que mais denuncia custo comendo o crescimento.

    A regra opera em **pontos de margem**, não em percentual de lucro. A
    versão antiga dividia pela margem do mês anterior e por isso precisava
    de um guard ``margem_liquida <= 0`` que a deixava cega exatamente onde
    ela mais serve: a loja que já estava no vermelho e cresce afundando
    mais. Com base negativa o percentual ainda inverte o sinal — melhorar
    de −100 para −50 vira "−50%", que se lê como piora.

    Margem é razão sobre receita, e receita é estritamente positiva; a
    diferença entre duas margens está sempre definida, atravessa o zero
    sem trocar de sinal e é a linguagem que o lojista já usa.
    """

    def avaliar(self, ctx: ContextoInsights) -> list[Insight]:
        meses = list(ctx.mensal.items())
        if len(meses) < 2:
            return []
        (mes_a, dec_a), (mes_b, dec_b) = meses[-2], meses[-1]
        # receita precisa ser positiva nos dois meses — é o denominador da
        # margem, e sem ela não existe ponto de margem para comparar
        for mes, dec in ((mes_a, dec_a), (mes_b, dec_b)):
            if not conferir_receita(dec.receita_bruta, mes).ok:
                return []

        var_receita = variacao_percentual(
            dec_a.receita_bruta, dec_b.receita_bruta, "faturamento"
        )
        queda_pp = dec_b.margem_pct - dec_a.margem_pct
        if var_receita.valor < ctx.parametros.limiar_crescimento_receita_pct:
            return []
        if queda_pp > -ctx.parametros.limiar_queda_margem_pp:
            return []

        # lucro que o mês teria se a MARGEM do mês anterior tivesse se
        # mantido sobre o faturamento novo — sem dividir por lucro nenhum
        esperado = _q2(dec_b.receita_bruta * dec_a.margem_pct / 100)
        impacto = _q2(esperado - dec_b.margem_liquida)
        # a dedução que mais subiu como % da receita é a principal suspeita
        difs = {
            d.nome: d.pct_receita - dec_a.deducao(d.nome).pct_receita
            for d in dec_b.deducoes
        }
        causa = max(difs, key=lambda n: difs[n])
        rotulo_causa = ROTULOS_DEDUCOES.get(causa, causa)
        return [
            Insight(
                categoria="receita_x_lucro",
                severidade="critico",
                titulo=f"Receita subiu e a margem caiu em {mes_b}",
                explicacao=(
                    f"De {mes_a} para {mes_b} o faturamento subiu "
                    f"{var_receita.valor}% e a margem caiu {abs(queda_pp)} "
                    f"ponto(s), de {dec_a.margem_pct}% para {dec_b.margem_pct}%. "
                    f"Principal suspeita: {rotulo_causa}, que subiu "
                    f"{_q2(difs[causa])} p.p. como fatia da receita."
                ),
                impacto_mensal=impacto,
                caminho_pratico=(
                    f"Abra o drill-down de {rotulo_causa} e a comparação da "
                    "aba Histórico: crescer pagando mais caro por venda é o "
                    "vazamento mais silencioso."
                ),
                base_evidencia="calculado",
                confianca=ctx.nota("calculado"),
                esperado=(
                    f"R$ {esperado} de lucro (se a margem de {mes_a} tivesse "
                    "se mantido sobre o faturamento novo)"
                ),
                observado=f"R$ {dec_b.margem_liquida} de lucro",
                desvio_pct=_desvio_pct(esperado, dec_b.margem_liquida),
                metodo=(
                    f"regra de divergência em pontos de margem: faturamento "
                    f"+{var_receita.valor}% e margem {queda_pp} p.p. no mesmo "
                    f"mês (limiares: "
                    f"+{ctx.parametros.limiar_crescimento_receita_pct}% de "
                    f"receita e −{ctx.parametros.limiar_queda_margem_pp} p.p. "
                    "de margem); causa apontada pela maior alta entre as "
                    "deduções"
                ),
            )
        ]


ANALISES_PADRAO: tuple[type[AnaliseInsight], ...] = (
    TendenciaCustos,
    ProdutosMargemMagra,
    DeducaoForaDoPadrao,
    FretePorPedido,
    ReceitaSobeLucroCai,
)


class MotorInsights:
    """Orquestra as análises do radar (mesmo padrão do diagnóstico)."""

    def __init__(
        self,
        parametros: ParametrosInsights | None = None,
        analises: tuple[AnaliseInsight, ...] | None = None,
    ):
        self.parametros = parametros or ParametrosInsights()
        self.analises = (
            analises
            if analises is not None
            else tuple(classe() for classe in ANALISES_PADRAO)
        )

    def radar(
        self,
        transacoes: list[Transacao],
        config: ConfigTributaria,
        tabela: TabelaCustos | None = None,
    ) -> list[Insight]:
        """Insights ordenados por severidade e impacto."""
        if not transacoes:
            raise ValueError("`transacoes` não pode ser vazio.")
        ctx = ContextoInsights(
            transacoes=transacoes,
            config=config,
            tabela=tabela or TabelaCustos(),
            parametros=self.parametros,
        )
        insights: list[Insight] = []
        for analise in self.analises:
            insights.extend(analise.avaliar(ctx))
        ordem = {s: i for i, s in enumerate(SEVERIDADES)}
        return sorted(
            insights,
            key=lambda i: (ordem[i.severidade], -i.impacto_mensal),
        )
