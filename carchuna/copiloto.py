"""Copiloto da Carchuna: pergunte com suas palavras, o motor calcula.

Divisão de trabalho inegociável (DNA do projeto):

- o **copiloto interpreta** a pergunta (regras transparentes de intenção,
  sem IA) e monta a resposta com números que vêm DOS MOTORES testados;
- o **LLM, quando existe**, apenas relê a resposta pronta em linguagem
  mais natural — ele nunca calcula nem inventa número (o texto
  determinístico é sempre devolvido junto);
- perguntas jurídicas continuam com o RAG legal existente (o roteador
  devolve ``None`` e o chamador cai no fluxo do Retriever).

O carro-chefe é :func:`explicar_variacao`: a variação do lucro entre
dois meses decomposta pela identidade contábil — Δlucro = Δreceita −
Σ Δdeduções, que fecha centavo a centavo — com a contribuição de cada
fator na queda (ou na alta), no formato "comissão explica 72% da queda".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from carchuna.margem import ROTULOS_DEDUCOES, DecomposicaoMargem

AVISO_COPILOTO = (
    "Números calculados pelos motores testados da Carchuna; o texto é "
    "montagem determinística (o LLM, quando ligado, só melhora a leitura). "
    "Não é aconselhamento contábil."
)

MESES_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


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


@dataclass(frozen=True)
class RespostaCopiloto:
    """Resposta do copiloto: texto determinístico + números usados."""

    intencao: str
    texto: str
    dados: dict[str, str]  # os números que sustentam o texto
    aviso: str = AVISO_COPILOTO


def _q1(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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


def _normalizar(texto: str) -> str:
    sem_acentos = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in sem_acentos if not unicodedata.combining(c))


def _mes_na_pergunta(pergunta: str, meses_disponiveis: list[str]) -> str | None:
    """Acha "junho" ou "2026-06" na pergunta e mapeia para um mês da base."""
    aaaa_mm = re.search(r"\b(\d{4})-(\d{2})\b", pergunta)
    if aaaa_mm and aaaa_mm.group(0) in meses_disponiveis:
        return aaaa_mm.group(0)
    normalizada = _normalizar(pergunta)
    for nome, numero in MESES_PT.items():
        if nome in normalizada:
            candidatos = [m for m in meses_disponiveis if m.endswith(f"-{numero:02d}")]
            if candidatos:
                return candidatos[-1]  # o mais recente daquele mês
    return None


class Copiloto:
    """Roteia a pergunta para o motor certo e monta a resposta com prova."""

    def __init__(self, analise):
        self.analise = analise  # AnalisadorMargem (duck-typed)

    def responder(self, pergunta: str) -> RespostaCopiloto | None:
        """Resposta determinística, ou ``None`` (pergunta é para o RAG legal)."""
        p = _normalizar(pergunta)

        if re.search(r"\b(por que|porque|pq|o que aconteceu)\b", p) and re.search(
            r"\b(lucro|margem|sobrou)\b", p
        ):
            return self._variacao(pergunta)
        if re.search(r"\b(quanto sobrou|quanto lucrei|qual .{0,10}lucro)\b", p):
            return self._resumo()
        if re.search(r"\b(campe|vil|melhor produto|pior produto)", p):
            return self._produtos()
        if re.search(r"\b(receber|caixa|folego|recebiveis)\b", p):
            return self._caixa()
        if re.search(r"\bimposto|tributo|das\b", p):
            return self._impostos()
        return None  # jurídico/aberto: segue para o RAG legal existente

    # -- intenções ------------------------------------------------------------

    def _variacao(self, pergunta: str) -> RespostaCopiloto:
        mensal = self.analise.mensal
        meses = list(mensal)
        if len(meses) < 2:
            return RespostaCopiloto(
                intencao="variacao_lucro",
                texto=(
                    "Sua base tem um mês só — para explicar uma queda ou alta "
                    "preciso de pelo menos dois meses de vendas."
                ),
                dados={"meses_na_base": str(len(meses))},
            )
        mes = _mes_na_pergunta(pergunta, meses)
        exp = explicar_variacao(mensal, mes)
        dados = {
            "variacao_receita": f"{exp.var_receita_pct:+}%",
            "variacao_lucro": f"{exp.var_lucro_pct:+}%",
            "delta_lucro": f"R$ {exp.delta_lucro}",
        }
        for c in exp.contribuicoes:
            if c.pct_da_pressao > 0:
                dados[f"pressao_{c.nome}"] = (
                    f"R$ {c.delta_reais} ({c.pct_da_pressao}% da pressão)"
                )
        return RespostaCopiloto(
            intencao="variacao_lucro", texto=exp.frase(), dados=dados
        )

    def _resumo(self) -> RespostaCopiloto:
        resumo = self.analise.resumo_executivo()
        return RespostaCopiloto(
            intencao="resumo",
            texto=resumo.frase(),
            dados={
                "receita": f"R$ {resumo.receita_bruta}",
                "margem_real": f"R$ {resumo.margem_real}",
                "margem_real_pct": f"{resumo.margem_real_pct}%",
            },
        )

    def _produtos(self) -> RespostaCopiloto:
        produtos = self.analise.margem_por_produto()
        melhor, pior = produtos[0], produtos[-1]
        texto = (
            f"Campeão de margem: {melhor.nome} (R$ {melhor.margem}, "
            f"{melhor.margem_pct}% em {melhor.vendas} venda(s))."
        )
        if pior.margem < 0:
            texto += (
                f" Atenção com {pior.nome}: R$ {pior.margem} acumulados "
                f"({pior.margem_pct}%) — cada venda sai no prejuízo."
            )
        else:
            texto += f" A menor margem é de {pior.nome} ({pior.margem_pct}%)."
        return RespostaCopiloto(
            intencao="produtos",
            texto=texto,
            dados={
                "campeao": f"{melhor.nome}: R$ {melhor.margem}",
                "lanterna": f"{pior.nome}: R$ {pior.margem}",
            },
        )

    def _caixa(self) -> RespostaCopiloto:
        from carchuna.caixa import agenda_recebimentos

        agenda = agenda_recebimentos(self.analise.transacoes, self.analise.tabela)
        total = sum((v for _, v in agenda), Decimal("0"))
        if not agenda:
            texto = (
                "Não há repasses futuros na agenda — as vendas do arquivo já "
                "caíram na conta. A aba Caixa projeta o fôlego com as saídas."
            )
        else:
            primeiro_dia, primeiro_valor = agenda[0]
            texto = (
                f"Há R$ {_q2(total)} a receber das vendas já feitas, em "
                f"{len(agenda)} dia(s) de repasse; o próximo é "
                f"{primeiro_dia.strftime('%d/%m')} (R$ {primeiro_valor}). Para "
                "o fôlego contra as suas saídas, use a aba Caixa."
            )
        return RespostaCopiloto(
            intencao="caixa",
            texto=texto,
            dados={"total_a_receber": f"R$ {_q2(total)}"},
        )

    def _impostos(self) -> RespostaCopiloto:
        ficha = self.analise.linhagem("tributos")
        return RespostaCopiloto(
            intencao="impostos",
            texto=(
                f"Impostos no período: R$ {ficha.valor}. Como chegamos lá: "
                f"{ficha.formula}."
            ),
            dados={"tributos": f"R$ {ficha.valor}", "fonte": ficha.fonte},
        )
