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

**RBT12 móvel** (``margem_mensal(..., rbt12_movel=True)``): o Simples não
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


def _mes_de(data) -> str:
    return f"{data.year:04d}-{data.month:02d}"


def _mes_anterior(mes: str, quantos: int = 1) -> str:
    """Devolve o mês ``quantos`` meses antes de ``mes`` ("AAAA-MM")."""
    ano, m = int(mes[:4]), int(mes[5:7])
    total = ano * 12 + (m - 1) - quantos
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def rbt12_movel(transacoes: list[Transacao], mes: str) -> Decimal | None:
    """Receita bruta acumulada nos 12 meses ANTERIORES a ``mes`` ("AAAA-MM").

    É a RBT12 do art. 18, § 1º, da LC 123/2006: o mês de apuração não
    entra na própria janela, e vendas devolvidas/canceladas ficam de fora
    da receita bruta (art. 3º, § 1º) — a mesma base que
    ``decompor_margem`` usa para o tributo do mês.

    Devolve ``None`` quando o arquivo **não cobre os 12 meses inteiros**
    da janela. Essa recusa é o ponto: um arquivo que começa no meio faria
    os meses ausentes valerem zero, e zero puxaria a alíquota para baixo
    sem que ninguém percebesse. A Carchuna não sabe distinguir "não
    vendeu" de "o dado não veio" — então não chuta, e quem chama usa a
    RBT12 que o lojista informou.
    """
    if not transacoes:
        return None
    inicio = _mes_anterior(mes, 12)
    fim = _mes_anterior(mes, 1)
    primeiro_do_arquivo = min(_mes_de(t.data) for t in transacoes)
    if primeiro_do_arquivo > inicio:
        return None
    return sum(
        (
            t.valor_bruto
            for t in transacoes
            if inicio <= _mes_de(t.data) <= fim and not t.devolvida
        ),
        Decimal("0"),
    )


def rbt12_por_mes(transacoes: list[Transacao]) -> dict[str, Decimal | None]:
    """RBT12 móvel de cada mês do arquivo, em ordem cronológica.

    ``None`` no mês significa "não dá para calcular do arquivo" — quem
    mostra isso na tela deve dizer que ali vale a RBT12 informada.
    """
    meses = sorted({_mes_de(t.data) for t in transacoes})
    return {mes: rbt12_movel(transacoes, mes) for mes in meses}


def margem_mensal(
    transacoes: list[Transacao],
    config: ConfigTributaria,
    tabela: TabelaCustos | None = None,
    rbt12_movel: bool = False,
) -> dict[str, DecomposicaoMargem]:
    """Decomposição completa da margem para cada mês ("AAAA-MM"), em ordem.

    Com ``rbt12_movel=True`` cada mês do Simples é tributado pela RBT12
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

    if not (rbt12_movel and config.regime == "simples"):
        return {
            mes: decompor_margem(grupo, config, tabela)
            for mes, grupo in sorted(por_mes.items())
        }

    janelas = rbt12_por_mes(transacoes)
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


def _q1(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Contribuicao:
    """Quanto um fator empurrou o lucro entre dois meses."""

    nome: str
    rotulo: str
    delta_reais: Decimal  # sinal do efeito no LUCRO (negativo = pressionou)
    pct_da_pressao: Decimal  # fatia entre os fatores que empurraram no
    # sentido da variação (0 quando empurrou contra)


@dataclass(frozen=True)
class ExplicacaoVariacao:
    """Δlucro entre dois meses decomposto pela identidade contábil."""

    mes_a: str
    mes_b: str
    var_receita_pct: Decimal
    var_lucro_pct: Decimal
    delta_lucro: Decimal
    contribuicoes: tuple[Contribuicao, ...]  # ordenadas pelo efeito

    def frase(self) -> str:
        """O resumo no formato do CFO: causa principal e secundária."""
        direcao = "caiu" if self.delta_lucro < 0 else "subiu"
        pressoes = [c for c in self.contribuicoes if c.pct_da_pressao > 0]
        frase = (
            f"De {self.mes_a} para {self.mes_b}, a receita variou "
            f"{self.var_receita_pct:+}% e o lucro {direcao} "
            f"{abs(self.var_lucro_pct)}% (R$ {abs(self.delta_lucro)})."
        )
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

    Identidade contábil: Δlucro = Δreceita − Σ Δdeduções — a soma das
    contribuições fecha exatamente com a variação do lucro. A "pressão"
    é a fatia de cada fator ENTRE os que empurraram o lucro no sentido
    observado (queda ou alta); fatores que empurraram contra aparecem
    com o delta em reais e pressão 0.
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
    contribs = [("receita", "Receita", dec_b.receita_bruta - dec_a.receita_bruta)]
    contribs += [
        (
            d.nome,
            ROTULOS_DEDUCOES.get(d.nome, d.nome),
            -(d.valor - dec_a.deducao(d.nome).valor),
        )
        for d in dec_b.deducoes
    ]
    sentido = -1 if delta_lucro < 0 else 1
    pressao_total = sum(
        (abs(delta) for _, _, delta in contribs if delta * sentido > 0),
        Decimal("0"),
    )
    contribuicoes = tuple(
        sorted(
            (
                Contribuicao(
                    nome=nome,
                    rotulo=rotulo,
                    delta_reais=_q2(delta),
                    pct_da_pressao=(
                        _q1(abs(delta) / pressao_total * 100)
                        if pressao_total > 0 and delta * sentido > 0
                        else Decimal("0")
                    ),
                )
                for nome, rotulo, delta in contribs
            ),
            key=lambda c: (-c.pct_da_pressao, -abs(c.delta_reais)),
        )
    )
    var_receita = (
        _q1((dec_b.receita_bruta - dec_a.receita_bruta) / dec_a.receita_bruta * 100)
        if dec_a.receita_bruta
        else Decimal("0")
    )
    var_lucro = (
        _q1(delta_lucro / abs(dec_a.margem_liquida) * 100)
        if dec_a.margem_liquida
        else Decimal("0")
    )
    return ExplicacaoVariacao(
        mes_a=mes_a,
        mes_b=mes_b,
        var_receita_pct=var_receita,
        var_lucro_pct=var_lucro,
        delta_lucro=_q2(delta_lucro),
        contribuicoes=contribuicoes,
    )
