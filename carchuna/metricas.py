"""Métricas da margem ao longo do tempo.

Tradução das métricas de risco da Calahonda para o mundo do lojista:

- curva de patrimônio → **curva de lucro acumulado**;
- drawdown → **maior queda de margem** (em pontos percentuais desde o
  melhor mês);
- volatilidade → **instabilidade da margem** (desvio-padrão da margem
  mensal).

Tudo em ``Decimal`` e Python puro; a decomposição de cada mês é feita
pelo próprio ``decompor_margem``, então cada número da série herda as
fontes das deduções.

**RBT12 móvel** (``margem_mensal(..., usar_rbt12_movel=True)``): o Simples não
tem uma alíquota do ano, tem uma por mês de apuração, calculada sobre a
receita bruta acumulada nos doze meses anteriores (LC 123/2006, art. 18,
§ 1º). Quem cresceu no ano paga em dezembro uma alíquota maior que a de
janeiro, e é exatamente essa variação que a série existe para mostrar.

Nota de conferência (padrão de honestidade da casa): a leitura do art.
18, § 1º usada aqui não foi conferida automaticamente na fonte oficial —
a tentativa em 05/08/2026 recebeu HTTP 503 do planalto.gov.br para
acesso automatizado, o mesmo que já havia acontecido com os Anexos em
19/07/2026. Confira na fonte antes de qualquer uso real.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal

from carchuna.margem import (
    ROTULOS_DEDUCOES,
    ConfigTributaria,
    DecomposicaoMargem,
    TabelaCustos,
    Transacao,
    decompor_margem,
)
from carchuna.validade import Resultado, limiar_divergencia_pp, variacao_percentual


def _mes_de(data) -> str:
    return f"{data.year:04d}-{data.month:02d}"


def _mes_anterior(mes: str, quantos: int = 1) -> str:
    """Devolve o mês ``quantos`` meses antes de ``mes`` ("AAAA-MM")."""
    ano, m = int(mes[:4]), int(mes[5:7])
    total = ano * 12 + (m - 1) - quantos
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


@dataclass(frozen=True)
class JanelaRBT12:
    """De onde saiu a RBT12 de um mês — e o que o lojista decidiu a respeito.

    A recusa de calcular a RBT12 do arquivo é conservadora de propósito
    (ver ``rbt12_movel``), mas conservadora e silenciosa é uma combinação
    ruim: o lojista via a alíquota informada valer em meses que ele acha
    que o arquivo cobria, sem nada explicando a diferença. Este registro é
    o que permite dizer, mês a mês, qual caminho a conta tomou.
    """

    mes: str
    valor: Decimal | None
    origem: str  # "arquivo" ou "informada"
    lacunas: tuple[str, ...] = ()
    confirmada: bool = False

    @property
    def tem_lacuna(self) -> bool:
        return bool(self.lacunas)


def lacunas_na_janela(transacoes: list[Transacao], mes: str) -> tuple[str, ...]:
    """Meses da janela sem nenhum lançamento **entre** dois que têm.

    A distinção é o ponto. Um arquivo que começa tarde não tem lacuna:
    ele simplesmente não alcança o começo da janela, e ninguém pode
    confirmar como "venda zero" um período que o arquivo nunca cobriu. Já
    o buraco no meio é uma pergunta respondível — o lojista sabe se
    faturou naquele mês —, e é a única coisa que ele pode confirmar.
    """
    janela = [_mes_anterior(mes, n) for n in range(12, 0, -1)]  # em ordem
    presentes = {_mes_de(t.data) for t in transacoes}
    dentro = [m for m in janela if m in presentes]
    if len(dentro) < 2:
        return ()
    primeiro, ultimo = dentro[0], dentro[-1]
    return tuple(m for m in janela if primeiro < m < ultimo and m not in presentes)


def rbt12_movel(
    transacoes: list[Transacao], mes: str, confirmar_lacunas: bool = False
) -> Decimal | None:
    """Receita bruta acumulada nos 12 meses ANTERIORES a ``mes`` ("AAAA-MM").

    É a RBT12 do art. 18, § 1º, da LC 123/2006: o mês de apuração não
    entra na própria janela, e vendas devolvidas/canceladas ficam de fora
    da receita bruta (art. 3º, § 1º) — a mesma base que
    ``decompor_margem`` usa para o tributo do mês.

    Devolve ``None`` quando o arquivo **não tem linha em cada um dos 12
    meses** da janela. Essa recusa é o ponto: mês ausente valeria zero, e
    zero puxa a alíquota para baixo sem que ninguém perceba. A Carchuna
    não sabe distinguir "não vendeu" de "o dado não veio" — então não
    chuta, e quem chama usa a RBT12 que o lojista informou.

    Não basta o arquivo COMEÇAR antes da janela: exportar "os últimos 3
    meses" e juntar com um arquivo velho produz um arquivo que começa
    cedo e tem dez meses faltando no meio. Por isso a conferência é mês a
    mês, e não pela primeira data.

    ``confirmar_lacunas=True`` é o lojista respondendo à pergunta que a
    Carchuna não sabe responder: os meses vazios do MEIO da janela são
    faturamento zero, e não dado que faltou. Só isso ele pode confirmar —
    um arquivo que começa depois do início da janela continua devolvendo
    ``None`` mesmo com a confirmação, porque ali não há nada para
    confirmar (ver ``lacunas_na_janela``).
    """
    if not transacoes:
        return None
    janela = {_mes_anterior(mes, n) for n in range(1, 13)}
    meses_do_arquivo = {_mes_de(t.data) for t in transacoes}
    faltando = janela - meses_do_arquivo
    if faltando and not (
        confirmar_lacunas and faltando <= set(lacunas_na_janela(transacoes, mes))
    ):
        return None
    return sum(
        (
            t.valor_bruto
            for t in transacoes
            if _mes_de(t.data) in janela and not t.devolvida
        ),
        Decimal("0"),
    )


def procedencia_rbt12(
    transacoes: list[Transacao], confirmar_lacunas: bool = False
) -> dict[str, JanelaRBT12]:
    """A RBT12 de cada mês do arquivo, com a procedência ao lado do número.

    É esta função que a tela usa para avisar o lojista: ela sabe quais
    meses estão vazios no meio da janela, e portanto qual pergunta fazer
    ("foi mês sem faturamento ou o arquivo está incompleto?").
    """
    resultado: dict[str, JanelaRBT12] = {}
    for mes in sorted({_mes_de(t.data) for t in transacoes}):
        valor = rbt12_movel(transacoes, mes, confirmar_lacunas=confirmar_lacunas)
        lacunas = lacunas_na_janela(transacoes, mes)
        # RBT12 zerada não serve para a fórmula, que divide por ela — nesse
        # caso a conta usa a informada, e a procedência tem de dizer isso.
        do_arquivo = valor is not None and valor > 0
        resultado[mes] = JanelaRBT12(
            mes=mes,
            valor=valor,
            origem="arquivo" if do_arquivo else "informada",
            lacunas=lacunas,
            confirmada=bool(lacunas) and confirmar_lacunas and do_arquivo,
        )
    return resultado


def rbt12_por_mes(
    transacoes: list[Transacao], confirmar_lacunas: bool = False
) -> dict[str, Decimal | None]:
    """RBT12 móvel de cada mês do arquivo, em ordem cronológica.

    ``None`` no mês significa "não dá para calcular do arquivo" — quem
    mostra isso na tela deve dizer que ali vale a RBT12 informada. Para
    saber POR QUE deu ``None``, use ``procedencia_rbt12``.
    """
    return {
        mes: janela.valor
        for mes, janela in procedencia_rbt12(
            transacoes, confirmar_lacunas=confirmar_lacunas
        ).items()
    }


def margem_mensal(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
    usar_rbt12_movel: bool = False,
    confirmar_lacunas: bool = False,
) -> dict[str, DecomposicaoMargem]:
    """Decomposição completa da margem para cada mês ("AAAA-MM"), em ordem.

    Com ``usar_rbt12_movel=True`` cada mês do Simples é tributado pela RBT12
    dos seus doze meses anteriores (art. 18, § 1º), em vez de repetir a
    RBT12 informada em todos eles. Nos meses em que o arquivo não cobre a
    janela inteira vale a RBT12 informada — ver ``rbt12_movel()``.

    O padrão é ``False``: quem já usava a função continua recebendo
    exatamente a mesma série.
    """
    if not transacoes:
        raise ValueError("`transacoes` não pode ser vazio.")
    por_mes: dict[str, list[Transacao]] = {}
    for t in transacoes:
        por_mes.setdefault(_mes_de(t.data), []).append(t)

    if not (usar_rbt12_movel and config.regime == "simples"):
        return {
            mes: decompor_margem(grupo, config, tabela)
            for mes, grupo in sorted(por_mes.items())
        }

    janelas = rbt12_por_mes(transacoes, confirmar_lacunas=confirmar_lacunas)
    series = {}
    for mes, grupo in sorted(por_mes.items()):
        janela = janelas.get(mes)
        # RBT12 zerada na janela (12 meses sem venda nenhuma) não serve para
        # a fórmula, que divide por ela: nesse caso vale a informada.
        config_do_mes = (
            replace(config, rbt12=janela) if janela and janela > 0 else config
        )
        series[mes] = decompor_margem(grupo, config_do_mes, tabela)
    return series


def serie_margem_pct(
    decomposicoes: dict[str, DecomposicaoMargem],
) -> list[tuple[str, Decimal]]:
    """Série (mês, margem %) a partir de ``margem_mensal``."""
    return [(mes, d.margem_pct) for mes, d in decomposicoes.items()]


def maior_queda_margem(serie: list[tuple[str, Decimal]]) -> Decimal:
    """Maior queda da margem, em pontos percentuais, desde o melhor mês anterior.

    Análogo do máximo drawdown da Calahonda: percorre a série guardando o
    pico e mede a maior distância pico → vale. Devolve um valor >= 0
    (``Decimal("4.20")`` = a margem já caiu 4,2 p.p. do topo).
    """
    if not serie:
        raise ValueError("`serie` não pode ser vazia.")
    pico = serie[0][1]
    maior_queda = Decimal("0")
    for _, margem in serie:
        pico = max(pico, margem)
        maior_queda = max(maior_queda, pico - margem)
    return maior_queda


def instabilidade_margem(serie: list[tuple[str, Decimal]]) -> Decimal:
    """Desvio-padrão (amostral) da margem mensal, em pontos percentuais.

    Margem estável ≈ 0; margem que oscila muito entre meses = número
    alto. É a "volatilidade" da Calahonda no vocabulário do lojista.
    """
    if len(serie) < 2:
        raise ValueError("`serie` precisa de pelo menos 2 meses.")
    valores = [margem for _, margem in serie]
    n = Decimal(len(valores))
    media = sum(valores) / n
    variancia = sum((v - media) ** 2 for v in valores) / (n - 1)
    return variancia.sqrt().quantize(Decimal("0.01"))


def lucro_acumulado(
    decomposicoes: dict[str, DecomposicaoMargem],
) -> list[tuple[str, Decimal]]:
    """Curva de lucro acumulado: soma corrente da margem líquida mensal."""
    if not decomposicoes:
        raise ValueError("`decomposicoes` não pode ser vazio.")
    acumulado = Decimal("0")
    curva = []
    for mes, d in decomposicoes.items():
        acumulado += d.margem_liquida
        curva.append((mes, acumulado))
    return curva


# ---------------------------------------------------------------------------
# Por que o lucro mudou de um mês para o outro
# ---------------------------------------------------------------------------


_CENTESIMO = Decimal("0.01")


def _q1(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct_exato(valor: Decimal, receita: Decimal) -> Decimal:
    """``valor`` como % da receita, sem arredondar — espelha ``_pct``.

    A conta em precisão cheia é o que torna a repartição do resíduo
    honesta: sem ela eu só teria os percentuais já arredondados, e
    distribuir centésimos entre números arredondados é chute com aparência
    de método.
    """
    if receita == 0:
        return Decimal("0")
    return valor / receita * 100


def _repartir_residuo_pp(
    exatos: list[Decimal],
    ajustaveis: list[bool],
    total: Decimal,
) -> list[Decimal]:
    """Arredonda ao centésimo de ponto somando **exatamente** ``total``.

    O problema: ``margem% = 100 − Σ pct_receita`` é exato em precisão
    cheia, mas cada linha é publicada arredondada. Somar o que está na
    tela dava até meio centésimo de erro por linha, e o lojista que
    conferia a cachoeira na mão encontrava uma diferença que não existe
    em lugar nenhum da conta.

    A saída é maior-resto: cada linha vai para o centésimo mais próximo, e
    os poucos centésimos que faltam para fechar o total vão para as linhas
    que mais perderam no arredondamento — as de maior resto, na direção
    em que falta. Cada linha publicada fica no máximo um centésimo do seu
    valor exato, e a soma fecha na unha.

    **O que esta função se recusa a fazer.** Se o que falta passar de um
    centésimo por linha ajustável, ela devolve os valores arredondados sem
    tocar em nada. Um resíduo desse tamanho não é arredondamento: é driver
    faltando ou fórmula errada, e maquiar a soma esconderia exatamente o
    defeito que a aditividade existe para pegar. Quem reporta é
    ``conferir_aditividade_pp``.

    ``ajustaveis`` marca quem pode receber centésimo. Fica de fora quem
    não foi arredondado: a receita, que entra em p.p. como zero
    estrutural, e qualquer linha que não se mexeu entre os dois períodos.
    Dar resíduo a elas seria publicar movimento onde não houve nenhum.
    """
    arredondados = [_q2(e) for e in exatos]
    falta = total - sum(arredondados, Decimal("0"))
    residuo = int((falta / _CENTESIMO).to_integral_value(rounding=ROUND_HALF_UP))
    if residuo == 0:
        return arredondados
    pool = [i for i, pode in enumerate(ajustaveis) if pode]
    if not pool or abs(residuo) > len(pool):
        return arredondados
    sentido = 1 if residuo > 0 else -1
    ordem = sorted(pool, key=lambda i: (-sentido * (exatos[i] - arredondados[i]), i))
    for i in ordem[: abs(residuo)]:
        arredondados[i] += sentido * _CENTESIMO
    return arredondados


@dataclass(frozen=True)
class Contribuicao:
    """Quanto um fator empurrou o lucro entre dois meses."""

    nome: str
    rotulo: str
    delta_reais: Decimal  # sinal do efeito no LUCRO (negativo = pressionou)
    delta_pp: Decimal  # o mesmo efeito em pontos de margem — sempre definido
    pct_da_pressao: Decimal  # fatia entre os fatores que empurraram no
    # sentido da variação (0 quando empurrou contra)


@dataclass(frozen=True)
class ExplicacaoVariacao:
    """Por que o lucro mudou entre dois meses, em três moedas.

    A moeda principal são **pontos de margem** (p.p.), e a escolha tem
    motivo. Margem é lucro sobre receita, e receita é estritamente
    positiva, então a diferença entre duas margens está sempre definida —
    inclusive quando o lucro atravessa o zero, que é justamente onde o
    percentual de lucro passa a mentir. Além disso ela é aditiva: a soma
    dos ``delta_pp`` das contribuições reproduz o ``delta_margem_pp``
    exatamente, porque ``margem% = 100 − Σ (dedução como % da receita)``.
    E é a linguagem que o lojista já usa: "caí três pontos de margem".

    ``delta_lucro`` em reais também está sempre definido.

    A soma dos ``delta_pp`` publicados fecha com ``delta_margem_pp`` na
    unha, e não por sorte: o resíduo de arredondamento é repartido por
    maior-resto em ``_repartir_residuo_pp``. Quando o resíduo é grande
    demais para ser arredondamento, a repartição se recusa a acontecer e
    ``conferir_aditividade_pp`` reporta a divergência.

    ``var_lucro_pct`` e ``var_receita_pct`` são ``Resultado``: viram
    ``indefinido`` quando a base do mês anterior não é estritamente
    positiva, em vez de devolver um percentual com o sinal trocado.
    """

    mes_a: str
    mes_b: str
    var_receita_pct: Resultado
    var_lucro_pct: Resultado
    delta_lucro: Decimal  # R$ — sempre definido
    delta_margem_pp: Decimal  # pontos de margem — sempre definido
    contribuicoes: tuple[Contribuicao, ...]  # ordenadas pelo efeito
    margem_base_pct: Decimal  # margem do mês A — calibra o limiar de divergência

    def frase(self) -> str:
        """O resumo no formato do CFO: causa principal e secundária."""
        direcao = "caiu" if self.delta_lucro < 0 else "subiu"
        if self.var_lucro_pct.ok:
            quanto = f"{abs(self.var_lucro_pct.valor)}%"
        else:
            # base não positiva: o percentual mentiria, então some da frase
            quanto = f"{abs(self.delta_margem_pp)} ponto(s) de margem"
        frase = (
            f"De {self.mes_a} para {self.mes_b}, o lucro {direcao} {quanto} "
            f"(R$ {abs(self.delta_lucro)})."
        )
        pressoes = [c for c in self.contribuicoes if c.pct_da_pressao > 0]
        if pressoes:
            principal = pressoes[0]
            frase += (
                f" Principal causa: {principal.rotulo}, respondendo por "
                f"{principal.pct_da_pressao}% da pressão."
            )
        if len(pressoes) > 1:
            segunda = pressoes[1]
            frase += f" Causa secundária: {segunda.rotulo} ({segunda.pct_da_pressao}%)."
        return frase


def explicar_variacao(
    mensal: dict[str, DecomposicaoMargem],
    mes_b: str | None = None,
) -> ExplicacaoVariacao:
    """Decompõe a variação do lucro de ``mes_b`` contra o mês anterior.

    Duas decomposições, ambas exatas:

    - **em reais**, pela identidade contábil ``Δlucro = Δreceita −
      Σ Δdeduções``: a soma dos ``delta_reais`` fecha com ``delta_lucro``;
    - **em pontos de margem**, por ``margem% = 100 − Σ pct_receita``: a
      soma dos ``delta_pp`` fecha com ``delta_margem_pp``. A receita não
      aparece aqui, e não é omissão — margem é razão, então crescer
      faturando o mesmo por real não move a margem. O que move são as
      fatias.

    Os p.p. são calculados em precisão cheia a partir dos valores em
    reais e só depois arredondados, com o resíduo repartido por
    maior-resto. Antes eles saíam da subtração de dois percentuais já
    arredondados, e a soma da cachoeira ficava alguns centésimos longe da
    manchete — diferença pequena, mas que aparecia para quem conferisse na
    mão e não tinha resposta nenhuma na conta.

    A "pressão" é a fatia de cada fator ENTRE os que empurraram o lucro no
    sentido observado; quem empurrou contra aparece com o delta e pressão 0.
    """
    meses = list(mensal.items())
    if len(meses) < 2:
        raise ValueError("preciso de pelo menos 2 meses para comparar.")
    nomes = [m for m, _ in meses]
    if mes_b is None:
        idx = len(meses) - 1
    else:
        if mes_b not in nomes:
            raise ValueError(f"mês {mes_b!r} não está na base ({nomes}).")
        idx = nomes.index(mes_b)
        if idx == 0:
            raise ValueError(f"{mes_b} é o primeiro mês da base — sem anterior.")
    (mes_a, dec_a), (mes_b, dec_b) = meses[idx - 1], meses[idx]

    delta_lucro = dec_b.margem_liquida - dec_a.margem_liquida
    r_a, r_b = dec_a.receita_bruta, dec_b.receita_bruta
    # A receita move o lucro em reais, mas não move a margem por si só:
    # entra com delta_pp zero de propósito, e o comentário existe para
    # ninguém "consertar" isso depois achando que faltou um termo. Sendo
    # zero estrutural, e não zero arredondado, ela também não recebe
    # resíduo — daí o `False` na terceira posição.
    contribs = [("receita", "Receita", r_b - r_a, Decimal("0"), False)]
    for d in dec_b.deducoes:
        anterior = dec_a.deducao(d.nome)
        delta_pp = _pct_exato(anterior.valor, r_a) - _pct_exato(d.valor, r_b)
        contribs.append(
            (
                d.nome,
                ROTULOS_DEDUCOES.get(d.nome, d.nome),
                -(d.valor - anterior.valor),
                delta_pp,
                delta_pp != 0,
            )
        )

    delta_margem_pp = dec_b.margem_pct - dec_a.margem_pct
    publicados = _repartir_residuo_pp(
        [pp for _, _, _, pp, _ in contribs],
        [pode for *_, pode in contribs],
        delta_margem_pp,
    )

    sentido = -1 if delta_lucro < 0 else 1
    pressao_total = sum(
        (abs(delta) for _, _, delta, _, _ in contribs if delta * sentido > 0),
        Decimal("0"),
    )
    contribuicoes = tuple(
        sorted(
            (
                Contribuicao(
                    nome=nome,
                    rotulo=rotulo,
                    delta_reais=_q2(delta),
                    delta_pp=pp,
                    pct_da_pressao=(
                        _q1(abs(delta) / pressao_total * 100)
                        if pressao_total > 0 and delta * sentido > 0
                        else Decimal("0")
                    ),
                )
                for (nome, rotulo, delta, _, _), pp in zip(
                    contribs, publicados, strict=True
                )
            ),
            key=lambda c: (-c.pct_da_pressao, -abs(c.delta_reais)),
        )
    )
    return ExplicacaoVariacao(
        mes_a=mes_a,
        mes_b=mes_b,
        var_receita_pct=variacao_percentual(r_a, r_b, "faturamento"),
        var_lucro_pct=variacao_percentual(
            dec_a.margem_liquida, dec_b.margem_liquida, "lucro"
        ),
        delta_lucro=_q2(delta_lucro),
        delta_margem_pp=delta_margem_pp,
        contribuicoes=contribuicoes,
        margem_base_pct=dec_a.margem_pct,
    )


def conferir_aditividade_pp(explicacao: ExplicacaoVariacao) -> Resultado:
    """A cachoeira publicada soma o que a manchete diz?

    A manchete é ``delta_margem_pp``, e a cachoeira é a lista de
    ``contribuicoes``. Elas têm de dar o mesmo número, porque
    ``margem% = 100 − Σ pct_receita`` e a soma dos deltas das fatias é o
    delta da margem. Com o resíduo repartido a igualdade sai exata; se
    sobrar divergência, ela não é arredondamento.

    O limiar não é fixo: vem de ``limiar_divergencia_pp`` e encolhe junto
    com a margem da loja, porque meio ponto que é ruído para quem fecha em
    30% é um sexto do resultado de quem fecha em 3%.

    Devolve a divergência em pontos, carimbada. Não conserta a cachoeira e
    não esconde a linha: quem lê precisa saber que a decomposição daquele
    mês não fecha, e isso é diferente de não ter decomposição.
    """
    soma = sum((c.delta_pp for c in explicacao.contribuicoes), Decimal("0"))
    divergencia = abs(soma - explicacao.delta_margem_pp)
    limiar = limiar_divergencia_pp(explicacao.margem_base_pct)
    if divergencia <= limiar:
        return Resultado.de_valor(divergencia)
    return Resultado.implausivel(
        divergencia,
        f"A decomposição de {explicacao.mes_a} para {explicacao.mes_b} não "
        f"fecha: as linhas somam {soma} ponto(s) de margem e a variação do "
        f"período é de {explicacao.delta_margem_pp}, uma diferença de "
        f"{divergencia} — acima do limiar de {limiar} p.p. para uma margem "
        f"base de {explicacao.margem_base_pct}%. Falta um fator na conta; "
        "não use a cachoeira deste mês para decidir onde mexer.",
    )
