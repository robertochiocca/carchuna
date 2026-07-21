"""Detecção de anomalias: "o que mudou de forma anormal este mês?".

Métodos estatísticos robustos e interpretáveis — nada de caixa preta:

- **z-score** do último mês contra a média e o desvio-padrão do
  histórico (≥ 3 meses anteriores);
- **cerca de IQR** (quartis ± 1,5×IQR) quando há ≥ 5 meses — robusta a
  meses atípicos no próprio histórico;
- **variação contra a média móvel** dos 3 meses anteriores, para a
  economia unitária (frete por pedido);
- **regra de divergência**: receita subiu e o lucro caiu — o par que
  mais denuncia custo comendo o crescimento.

Cada anomalia explica o que aconteceu, o valor esperado, o observado, o
desvio, o impacto financeiro estimado, a severidade, o MÉTODO que a
detectou e a confiança (rubrica do ``confianca.py``).

Divisão de trabalho com o radar (``insights.py``), sem duplicação: o
radar cuida da TENDÊNCIA entre primeiro e último mês e da margem % fora
do padrão; este módulo vigia cada dedução, a economia unitária e a
divergência receita×lucro no último mês. Decomposição STL fica para
quando houver ≥ 24 meses (dois ciclos sazonais) — documentado, não
prometido.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from carchuna.confianca import NotaConfianca, avaliar_confianca
from carchuna.margem import (
    ROTULOS_DEDUCOES,
    ConfigTributaria,
    TabelaCustos,
    Transacao,
)
from carchuna.metricas import margem_mensal

AVISO_ANOMALIAS = (
    "Anomalia é desvio estatístico, não veredito: confirme a causa nos "
    "extratos antes de agir. Métodos e limiares estão documentados."
)


@dataclass(frozen=True)
class Anomalia:
    """Uma mudança anormal detectada, com esperado × observado e método."""

    metrica: str
    titulo: str
    o_que_aconteceu: str
    esperado: str  # com unidade (ex.: "12.00% da receita", "R$ 18,40/pedido")
    observado: str
    desvio_pct: Decimal  # (observado − esperado) / esperado × 100
    impacto_mensal: Decimal  # R$/mês estimado
    severidade: str  # "critico" | "atencao" | "oportunidade"
    metodo: str  # como foi detectada (z-score, IQR, média móvel…)
    confianca: NotaConfianca
    caminho_pratico: str
    aviso: str = AVISO_ANOMALIAS


@dataclass
class ParametrosAnomalias:
    """Limiares documentados e editáveis."""

    z_atencao: Decimal = Decimal("2")
    z_critico: Decimal = Decimal("3")
    # com histórico constante (σ = 0), qualquer desvio acima disto (em
    # p.p. da receita) é fora do padrão
    limiar_pp_historico_constante: Decimal = Decimal("0.5")
    # variação da economia unitária contra a média móvel de 3 meses
    limiar_var_unitaria: Decimal = Decimal("0.25")  # 25%
    # divergência: receita sobe ≥ +5% e lucro cai ≥ −5%
    limiar_divergencia: Decimal = Decimal("0.05")


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q1(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


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

    return _q(Decimal("0.25")), Decimal(_q(Decimal("0.75")))


def _desvio_pct(esperado: Decimal, observado: Decimal) -> Decimal:
    if esperado == 0:
        return Decimal("0")
    return _q1((observado - esperado) / abs(esperado) * 100)


class MotorAnomalias:
    """Vigia o último mês contra o histórico, métrica a métrica."""

    def __init__(self, parametros: ParametrosAnomalias | None = None):
        self.parametros = parametros or ParametrosAnomalias()

    # -- deduções como % da receita ------------------------------------------

    def _deducoes_fora_do_padrao(
        self, mensal, transacoes: list[Transacao]
    ) -> list[Anomalia]:
        meses = list(mensal.items())
        if len(meses) < 4:  # 3 de histórico + o mês vigiado
            return []
        historico, (mes_atual, dec_atual) = meses[:-1], meses[-1]
        anomalias = []
        for deducao in dec_atual.deducoes:
            serie = [d.deducao(deducao.nome).pct_receita for _, d in historico]
            media, desvio = _media_desvio(serie)
            observado = deducao.pct_receita
            delta = observado - media

            metodo = ""
            severidade = None
            if desvio > 0:
                z = abs(delta) / desvio
                if z >= self.parametros.z_critico:
                    severidade = "critico"
                elif z >= self.parametros.z_atencao:
                    severidade = "atencao"
                metodo = (
                    f"z-score {_q1(z)}σ contra {len(serie)} meses de histórico "
                    f"(média {_q2(media)}%, desvio {_q2(desvio)} p.p.)"
                )
                if len(serie) >= 4:
                    q1, q3 = _quartis(serie)
                    iqr = q3 - q1
                    fora_iqr = observado > q3 + iqr * Decimal(
                        "1.5"
                    ) or observado < q1 - iqr * Decimal("1.5")
                    if fora_iqr:
                        metodo += "; cerca de IQR (quartis ± 1,5×IQR) ultrapassada"
                    elif severidade == "atencao":
                        # sinal fraco que o método robusto não confirma: descarta
                        severidade = None
            elif abs(delta) > self.parametros.limiar_pp_historico_constante:
                severidade = "critico"
                metodo = (
                    f"histórico constante em {_q2(media)}% por {len(serie)} meses; "
                    f"desvio de {_q2(abs(delta))} p.p. é fora do padrão"
                )
            if severidade is None:
                continue
            if delta < 0:
                severidade = "oportunidade"  # custo CAIU fora do padrão
            impacto = _q2(abs(delta) / 100 * dec_atual.receita_bruta)
            rotulo = ROTULOS_DEDUCOES.get(deducao.nome, deducao.nome)
            direcao = "subiu" if delta > 0 else "caiu"
            anomalias.append(
                Anomalia(
                    metrica=f"{deducao.nome}_pct",
                    titulo=f"{rotulo}: {direcao} fora do padrão em {mes_atual}",
                    o_que_aconteceu=(
                        f"{rotulo} consumia em média {_q2(media)}% da receita "
                        f"e em {mes_atual} consumiu {observado}%."
                    ),
                    esperado=f"{_q2(media)}% da receita",
                    observado=f"{observado}% da receita",
                    desvio_pct=_desvio_pct(media, observado),
                    impacto_mensal=impacto,
                    severidade=severidade,
                    metodo=metodo,
                    confianca=avaliar_confianca(transacoes, base="calculado"),
                    caminho_pratico=(
                        "Abra o drill-down desta dedução (clique na barra do "
                        "raio-X) e compare os extratos do mês com os anteriores."
                    ),
                )
            )
        return anomalias

    # -- economia unitária: frete por pedido ---------------------------------

    def _frete_por_pedido(self, transacoes: list[Transacao]) -> list[Anomalia]:
        por_mes: dict[str, list[Transacao]] = {}
        for t in sorted(transacoes, key=lambda t: t.data):
            if t.devolvida:
                continue
            por_mes.setdefault(f"{t.data.year}-{t.data.month:02d}", []).append(t)
        if len(por_mes) < 4:
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
        if abs(variacao) < self.parametros.limiar_var_unitaria:
            return []
        pedidos = len(por_mes[mes_atual])
        impacto = _q2((observado - esperado) * pedidos)
        severidade = "atencao" if variacao > 0 else "oportunidade"
        return [
            Anomalia(
                metrica="frete_por_pedido",
                titulo=(
                    f"Frete por pedido anormalmente "
                    f"{'alto' if variacao > 0 else 'baixo'} em {mes_atual}"
                ),
                o_que_aconteceu=(
                    f"O frete médio por pedido foi R$ {_q2(observado)} em "
                    f"{mes_atual}, contra R$ {_q2(esperado)} na média dos 3 "
                    f"meses anteriores ({pedidos} pedidos no mês)."
                ),
                esperado=f"R$ {_q2(esperado)}/pedido",
                observado=f"R$ {_q2(observado)}/pedido",
                desvio_pct=_desvio_pct(esperado, observado),
                impacto_mensal=abs(impacto),
                severidade=severidade,
                metodo=(
                    f"variação de {_q1(variacao * 100)}% contra a média móvel "
                    f"de 3 meses (limiar: "
                    f"{_q1(self.parametros.limiar_var_unitaria * 100)}%)"
                ),
                confianca=avaliar_confianca(transacoes, base="calculado"),
                caminho_pratico=(
                    "Confira tabela de frete, mix de regiões e peso dos "
                    "pedidos do mês; renegocie a faixa com a transportadora."
                ),
            )
        ]

    # -- divergência: receita sobe, lucro cai --------------------------------

    def _receita_sobe_lucro_cai(
        self, mensal, transacoes: list[Transacao]
    ) -> list[Anomalia]:
        meses = list(mensal.items())
        if len(meses) < 2:
            return []
        (mes_a, dec_a), (mes_b, dec_b) = meses[-2], meses[-1]
        if dec_a.receita_bruta == 0 or dec_a.margem_liquida <= 0:
            return []
        var_receita = (dec_b.receita_bruta - dec_a.receita_bruta) / dec_a.receita_bruta
        var_lucro = (dec_b.margem_liquida - dec_a.margem_liquida) / dec_a.margem_liquida
        limiar = self.parametros.limiar_divergencia
        if var_receita < limiar or var_lucro > -limiar:
            return []
        # lucro esperado se a margem tivesse acompanhado a receita
        esperado = _q2(dec_a.margem_liquida * (1 + var_receita))
        impacto = _q2(esperado - dec_b.margem_liquida)
        # a dedução que mais subiu como % da receita é a principal suspeita
        difs = {
            d.nome: d.pct_receita - dec_a.deducao(d.nome).pct_receita
            for d in dec_b.deducoes
        }
        causa = max(difs, key=lambda n: difs[n])
        rotulo_causa = ROTULOS_DEDUCOES.get(causa, causa)
        return [
            Anomalia(
                metrica="receita_x_lucro",
                titulo=f"Receita subiu e o lucro caiu em {mes_b}",
                o_que_aconteceu=(
                    f"De {mes_a} para {mes_b} a receita variou "
                    f"{_q1(var_receita * 100)}% e o lucro variou "
                    f"{_q1(var_lucro * 100)}%. Principal suspeita: "
                    f"{rotulo_causa}, que subiu {_q2(difs[causa])} p.p. como "
                    "fatia da receita."
                ),
                esperado=(
                    f"R$ {esperado} de lucro (se a margem tivesse "
                    "acompanhado a receita)"
                ),
                observado=f"R$ {dec_b.margem_liquida} de lucro",
                desvio_pct=_desvio_pct(esperado, dec_b.margem_liquida),
                impacto_mensal=impacto,
                severidade="critico",
                metodo=(
                    f"regra de divergência: receita +{_q1(var_receita * 100)}% "
                    f"e lucro {_q1(var_lucro * 100)}% no mesmo mês (limiar "
                    f"±{_q1(limiar * 100)}%); causa apontada pela maior alta "
                    "entre as deduções"
                ),
                confianca=avaliar_confianca(transacoes, base="calculado"),
                caminho_pratico=(
                    f"Abra o drill-down de {rotulo_causa} e a comparação da "
                    "aba Histórico: crescer pagando mais caro por venda é o "
                    "vazamento mais silencioso."
                ),
            )
        ]

    def detectar(
        self,
        transacoes: list[Transacao],
        config: ConfigTributaria,
        tabela: TabelaCustos | None = None,
    ) -> list[Anomalia]:
        """Anomalias do último mês, por severidade e impacto decrescentes."""
        if not transacoes:
            raise ValueError("`transacoes` não pode ser vazio.")
        tabela = tabela or TabelaCustos()
        mensal = margem_mensal(transacoes, config, tabela)
        anomalias = (
            self._deducoes_fora_do_padrao(mensal, transacoes)
            + self._frete_por_pedido(transacoes)
            + self._receita_sobe_lucro_cai(mensal, transacoes)
        )
        ordem = {"critico": 0, "atencao": 1, "oportunidade": 2}
        return sorted(anomalias, key=lambda a: (ordem[a.severidade], -a.impacto_mensal))
