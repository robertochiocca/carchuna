"""Quando o motor não tem resposta, ele diz isso — em vez de devolver número.

O defeito que motivou este módulo: o motor de margem nunca se recusava a
responder. Variação percentual de lucro com base negativa saía com o sinal
invertido (melhorar de −100 para −50 era reportado como *queda* de 50%), e
uma margem de −1854% atravessava a decomposição inteira sem um ruído.

Três estados, e nenhum deles é exceção:

``ok``
    O número é confiável e pode ir para a tela como está.

``indefinido``
    A operação não tem resultado matemático válido — denominador zero,
    denominador negativo, base ausente. Não existe número para mostrar, e
    inventar um seria pior que não mostrar nada.

``implausivel``
    A conta fechou, mas a entrada ou a saída está fora de qualquer faixa
    contábil razoável. O número existe; confiar nele é que não dá.

Status diferente de ``ok`` **não levanta exceção**: o cálculo segue e o
resultado viaja carimbado, como já acontece com o diagnóstico legal quando
não há chave de LLM. Quem desenha a tela mostra o ``motivo`` no lugar do
número — nunca um traço mudo, nunca um zero que se confunde com "não
perdeu nada".

Nada aqui usa ``None`` ou ``NaN`` como sinalizador: os dois se parecem
demais com valor legítimo e somem dentro de uma soma sem avisar.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

STATUS_VALIDOS = ("ok", "indefinido", "implausivel")

# ---------------------------------------------------------------------------
# Faixa de plausibilidade contábil
#
# Os dois limiares abaixo são o único lugar do projeto que decide o que é
# "absurdo". Não replicar literal nenhum destes fora daqui.
# ---------------------------------------------------------------------------

# Margem líquida do período, em % da receita.
#
# Teto: a margem é `receita − Σ deduções` e nenhuma dedução é negativa, então
# margem acima de 100% da receita não é um resultado ruim — é impossível, e
# denuncia dedução com sinal trocado.
#
# Piso: −100% significa que os custos do período passaram do DOBRO da
# receita. Prejuízo de verdade acontece e fica bem acima disso; abaixo é
# erro de dado antes de ser prejuízo (a comissão de 900% que motivou este
# módulo produzia −1854%).
MARGEM_MAXIMA_PLAUSIVEL = Decimal("100")
MARGEM_MINIMA_PLAUSIVEL = Decimal("-100")

# Uma única dedução maior que a receita bruta do período. Nenhuma taxa de
# marketplace, imposto ou frete se aproxima disso; CMV acima da receita
# significa vender abaixo do custo em TODAS as vendas do período. É o
# indício mais direto de coluna trocada no mapeamento ou de unidade errada
# (centavos lidos como reais).
FATOR_DEDUCAO_SOBRE_RECEITA = Decimal("1")

# ---------------------------------------------------------------------------
# Tolerâncias de arredondamento
#
# Nenhuma delas absorve erro de fórmula: erro de fórmula produz divergência
# de reais e de pontos inteiros, não de centavos. Elas existem porque o
# motor arredonda cada linha para o centavo, e caminhos diferentes acumulam
# arredondamentos diferentes.
# ---------------------------------------------------------------------------

# Reconciliação: `decompor_margem` arredonda cada uma das 7 deduções uma
# vez; a reconferência lançamento a lançamento soma exato e arredonda só no
# fim. Meio centavo por linha arredondada dá menos de quatro centavos.
TOLERANCIA_RECONCILIACAO = Decimal("0.07")

# Aditividade em pontos de margem: `margem% = 100 − Σ pct_receita` vale
# exatamente em precisão cheia, mas cada pct é publicado arredondado ao
# centésimo de ponto. São 7 deduções mais a própria margem, meio centésimo
# cada uma.
TOLERANCIA_ADITIVIDADE_PP = Decimal("0.05")

# Precisão em que os pontos de margem são publicados. Nenhum limiar pode
# exigir do número uma exatidão menor que a casa que a tela mostra.
PRECISAO_PP = Decimal("0.01")

# Teto do limiar de divergência: um ponto de margem inteiro.
LIMIAR_DIVERGENCIA_MAXIMO_PP = Decimal("1.0")

# Fração da margem do período base abaixo da qual a divergência é ruído.
FRACAO_DA_MARGEM_BASE = Decimal("0.10")


@dataclass(frozen=True)
class Resultado:
    """Um número do motor com o seu estado de validade.

    ``valor`` é ``None`` quando ``status == "indefinido"`` — ali não existe
    número. Em ``implausivel`` o valor existe e vai junto, para quem quiser
    auditar de onde veio o absurdo.
    """

    valor: Decimal | None
    status: str
    motivo: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUS_VALIDOS:
            raise ValueError(
                f"status {self.status!r} inválido; use um de {STATUS_VALIDOS}."
            )
        if self.status == "ok":
            if self.valor is None:
                raise ValueError("resultado `ok` precisa de valor.")
        elif not self.motivo.strip():
            raise ValueError(
                f"resultado {self.status!r} precisa de motivo em texto — é ele "
                "que aparece na tela no lugar do número."
            )
        if self.status == "indefinido" and self.valor is not None:
            raise ValueError(
                "resultado `indefinido` não carrega valor: se existe número, "
                "o status é `ok` ou `implausivel`."
            )

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def texto(self, formato: str = "{}") -> str:
        """O que a tela mostra: o número formatado, ou o motivo por extenso."""
        return format(self.valor, "") if self.ok else self.motivo

    @classmethod
    def de_valor(cls, valor: Decimal) -> Resultado:
        return cls(valor=valor, status="ok")

    @classmethod
    def indefinido(cls, motivo: str) -> Resultado:
        return cls(valor=None, status="indefinido", motivo=motivo)

    @classmethod
    def implausivel(cls, valor: Decimal, motivo: str) -> Resultado:
        return cls(valor=valor, status="implausivel", motivo=motivo)


def variacao_percentual(anterior: Decimal, atual: Decimal, grandeza: str) -> Resultado:
    """Variação percentual, **só** quando a base é estritamente positiva.

    Com base negativa o percentual mente na travessia do zero: melhorar de
    −100 para −50 dá −50%, que se lê como piora. Com base zero não existe
    divisão. Nos dois casos o resultado é ``indefinido``, e a variação em
    reais (sempre definida) é quem responde no lugar.

    Não há fórmula alternativa aqui de propósito: razão absoluta, logaritmo
    e sinal ajustado continuam mentindo em algum ponto da travessia.
    """
    if anterior == 0:
        return Resultado.indefinido(
            f"Não dá para calcular variação percentual de {grandeza}: o mês "
            "anterior fechou em zero, e não existe divisão por zero. Olhe a "
            "variação em reais."
        )
    if anterior < 0:
        return Resultado.indefinido(
            f"Não dá para calcular variação percentual de {grandeza}: o mês "
            "anterior fechou negativo, e percentual sobre base negativa "
            "inverte o sinal — uma melhora apareceria como piora. Olhe a "
            "variação em reais e em pontos de margem."
        )
    return Resultado.de_valor(
        ((atual - anterior) / anterior * 100).quantize(Decimal("0.1"))
    )


def limiar_divergencia_pp(margem_base: Decimal) -> Decimal:
    """Quanta divergência em pontos de margem ainda é ruído **nesta** loja.

    Limiar fixo trata como iguais duas lojas que não são. Meio ponto de
    margem é ruído para quem fecha o mês em 30% e é um sexto do resultado
    de quem fecha em 3% — e no varejo brasileiro a segunda é a comum. Por
    isso o limiar é ``min(1,0 p.p.; 10% da margem do período base)``: o
    teto impede que a loja gorda aceite qualquer coisa em nome da própria
    folga, e a fração faz o limiar encolher junto com a margem de quem tem
    pouco a perder.

    A margem base entra em módulo: num mês de prejuízo o que importa é a
    ordem de grandeza do resultado, não o lado do zero em que ele caiu.

    O piso é ``PRECISAO_PP``, a casa em que os pontos são publicados —
    exigir menos que o centésimo seria cobrar do número uma exatidão que a
    tela não mostra. Margem base zero cai nesse piso, e ali é ele quem
    manda: 10% de nada não é limiar nenhum.
    """
    return max(
        PRECISAO_PP,
        min(LIMIAR_DIVERGENCIA_MAXIMO_PP, abs(margem_base) * FRACAO_DA_MARGEM_BASE),
    )


def conferir_receita(receita: Decimal, mes: str) -> Resultado:
    """Receita do período: precisa ser estritamente positiva para dividir."""
    if receita > 0:
        return Resultado.de_valor(receita)
    if receita == 0:
        return Resultado.indefinido(
            f"O mês {mes} não tem receita: sem faturamento não há margem para "
            "comparar. Confira se o arquivo cobre esse mês."
        )
    return Resultado.indefinido(
        f"O mês {mes} fechou com receita negativa (R$ {receita}), o que não "
        "é faturamento — confira se devoluções entraram com sinal trocado."
    )
