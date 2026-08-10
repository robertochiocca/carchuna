"""Tipos semânticos da ingestão: físico ≠ estatístico ≠ negócio.

O bug que motivou este módulo: o arquivo real de marketplace traz a
coluna de devolução como STATUS ("Solicitação aprovada", "Em análise"),
e a ingestão presumia representação booleana ("Sim"/"Não") — quebrando
com dado válido. A correção separa três camadas que estavam misturadas:

1. **Tipo físico** — o que a célula é (texto, número, data, vazio);
2. **Tipo estatístico** — o que a COLUNA é (:func:`inferir_tipo_coluna`):
   ``booleano`` só quando TODOS os valores não vazios são interpretáveis
   como booleano; senão ``numerico``/``data``/``categorico``/``texto``;
3. **Significado de negócio** — o que o valor QUER DIZER para o campo
   (:func:`interpretar_devolucao`): "Solicitação aprovada" É uma
   devolução; "Solicitação recusada" NÃO é; "Em análise" é um estado
   ``indefinido`` que o sistema preserva — nunca vira True/False em
   silêncio: a decisão é do usuário, no mapeador.

Regras inegociáveis:

- valor AUSENTE (célula vazia, None, NaN) não é valor INVÁLIDO;
- o valor original é preservado (``Transacao.devolucao_status``);
- léxicos centralizados aqui — nada de ifs espalhados pelo projeto.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

TIPOS_COLUNA = ("booleano", "numerico", "data", "categorico", "texto")

# Colunas com até este nº de valores distintos são categóricas; acima,
# texto livre (limiar clássico e editável por parâmetro).
MAX_CATEGORIAS = 12

# -- camada 1/2: físico e estatístico ---------------------------------------

_AUSENTES = {"", "nan", "none", "null", "na", "n/a", "-", "--"}

_BOOL_VERDADEIRO = {"1", "true", "sim", "s", "verdadeiro", "yes", "y"}
_BOOL_FALSO = {"0", "false", "nao", "n", "falso", "no"}


def normalizar_valor(valor) -> str:
    """minúsculas + espaços aparados + acentos removidos ('  SIM ' → 'sim')."""
    texto = str(valor).strip().lower()
    sem_acento = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sem_acento if not unicodedata.combining(c))


def eh_ausente(valor) -> bool:
    """Célula vazia/None/NaN é dado FALTANDO — nunca dado inválido."""
    return valor is None or normalizar_valor(valor) in _AUSENTES


def como_booleano(valor) -> bool | None:
    """True/False quando o valor é confiavelmente booleano; senão None.

    'Solicitação aprovada' devolve None — é categoria, não booleano.
    """
    normal = normalizar_valor(valor)
    if normal in _BOOL_VERDADEIRO:
        return True
    if normal in _BOOL_FALSO:
        return False
    return None


def _eh_numerico(valor) -> bool:
    limpo = normalizar_valor(valor).replace("r$", "").replace(" ", "").replace("%", "")
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        Decimal(limpo)
        return True
    except InvalidOperation:
        return False


def _eh_data(valor) -> bool:
    texto = str(valor).strip()[:10]
    try:
        date.fromisoformat(texto)
        return True
    except ValueError:
        pass
    partes = texto.split("/")
    if len(partes) == 3:
        try:
            dia, mes, ano = (int(p) for p in partes)
            date(ano if ano > 99 else 2000 + ano, mes, dia)
            return True
        except ValueError:
            return False
    return False


@dataclass(frozen=True)
class TipoColuna:
    """O que a coluna é, com os valores distintos para o usuário conferir."""

    tipo: str  # um de TIPOS_COLUNA
    valores_distintos: tuple[str, ...]  # originais (sem normalizar), na ordem
    ausentes: int  # células vazias/None/NaN (contadas, nunca invalidadas)


def inferir_tipo_coluna(valores, max_categorias: int = MAX_CATEGORIAS) -> TipoColuna:
    """Classifica a coluna pelos valores NÃO vazios.

    ``booleano`` exige que TODOS sejam interpretáveis como booleano;
    depois ``numerico`` e ``data`` pelo mesmo critério; senão
    ``categorico`` (até ``max_categorias`` distintos) ou ``texto``.
    Coluna toda vazia é ``texto`` com tudo em ``ausentes``.
    """
    presentes: list[str] = []
    distintos: list[str] = []
    vistos: set[str] = set()
    ausentes = 0
    for valor in valores:
        if eh_ausente(valor):
            ausentes += 1
            continue
        original = str(valor).strip()
        presentes.append(original)
        normal = normalizar_valor(original)
        if normal not in vistos:
            vistos.add(normal)
            distintos.append(original)
    if not presentes:
        return TipoColuna("texto", (), ausentes)
    if all(como_booleano(v) is not None for v in presentes):
        tipo = "booleano"
    elif all(_eh_numerico(v) for v in presentes):
        tipo = "numerico"
    elif all(_eh_data(v) for v in presentes):
        tipo = "data"
    elif len(distintos) <= max_categorias:
        tipo = "categorico"
    else:
        tipo = "texto"
    return TipoColuna(tipo, tuple(distintos), ausentes)


# -- camada 3: significado de negócio da devolução ---------------------------

ESTADOS_DEVOLUCAO = (
    "devolvida",
    "nao_devolvida",
    "cancelada",
    "indefinido",
    "desconhecido",
)

# "Cancelado" sozinho não diz o que foi cancelado, e as duas leituras vão
# para lados opostos: "solicitação de devolução cancelada" quer dizer que
# a venda ficou de pé; "pedido cancelado" quer dizer que ela nunca
# aconteceu. Estava na lista dos negativos, então todo cancelamento virava
# venda normal — inclusive o pedido cancelado, que entrava na receita com
# CMV e comissão de uma venda que não existiu.
#
# Quando o texto DIZ o que foi cancelado, a leitura sai daí: os dois
# léxicos abaixo resolvem esses casos, e cada um vai para o seu lado.
# Quando não diz, o valor cai em `cancelada` — estado próprio, que pede a
# decisão do usuário em vez de escolher por ele.
_TERMOS_DEVOLUCAO_CANCELADA = (
    "devolucao cancelada",
    "solicitacao cancelada",
    "solicitacao de devolucao cancelada",
    "reembolso cancelado",
    "estorno cancelado",
    "return canceled",
    "return cancelled",
)
_TERMOS_VENDA_CANCELADA = (
    "pedido cancelad",
    "venda cancelada",
    "compra cancelada",
    "order canceled",
    "order cancelled",
    "cancelado pelo comprador",
    "cancelado pelo vendedor",
)

# Léxico central (termos normalizados, casados por substring). A ORDEM
# importa: negativos primeiro, porque "não devolvida" contém "devolvid"
# e "reembolso recusado" contém "reembols".
_TERMOS_NAO_DEVOLVIDA = (
    "recusad",
    "rejeitad",
    "negad",
    "nao se aplica",
    "nao devolvid",
    "sem devolucao",
    "improcedente",
)
_TERMOS_DEVOLVIDA = (
    "aprovad",
    "devolvid",
    "estornad",
    "reembolsad",
    "reembolso realizado",
    "reembolso concluido",
    "refund",
    "returned",
)
_TERMOS_INDEFINIDO = (
    "analise",
    "aguardando",
    "pendente",
    "andamento",
    "disputa",
    "processamento",
    "aberto",
)


def interpretar_devolucao(valor) -> str:
    """O significado de negócio do valor para o campo "Foi devolvida?".

    - booleano confiável → ``devolvida``/``nao_devolvida``;
    - status conclusivo do léxico ("Solicitação aprovada" → devolução
      aconteceu; "Solicitação recusada" → não) → idem;
    - cancelamento que DIZ o que foi cancelado ("Pedido cancelado" → a
      venda não aconteceu; "Solicitação de devolução cancelada" → a
      venda ficou de pé) → resolvido pelo próprio texto;
    - cancelamento que não diz ("Cancelado") → ``cancelada``, estado
      próprio: as duas leituras vão para lados opostos e nenhuma delas é
      dedutível do dado;
    - estado intermediário ("Em análise") → ``indefinido`` — preservado,
      NUNCA reduzido a sim/não automaticamente;
    - fora do léxico → ``desconhecido`` (decisão do usuário).
    """
    booleano = como_booleano(valor)
    if booleano is True:
        return "devolvida"
    if booleano is False:
        return "nao_devolvida"
    normal = normalizar_valor(valor)
    # Antes dos léxicos gerais: "devolução cancelada" contém "cancelad" e
    # também "devolucao", e casaria com o lado errado em qualquer ordem
    # que não seja esta.
    if any(termo in normal for termo in _TERMOS_DEVOLUCAO_CANCELADA):
        return "nao_devolvida"
    if any(termo in normal for termo in _TERMOS_VENDA_CANCELADA):
        return "devolvida"
    if "cancelad" in normal or "cancel" in normal:
        return "cancelada"
    if any(termo in normal for termo in _TERMOS_NAO_DEVOLVIDA):
        return "nao_devolvida"
    if any(termo in normal for termo in _TERMOS_DEVOLVIDA):
        return "devolvida"
    if any(termo in normal for termo in _TERMOS_INDEFINIDO):
        return "indefinido"
    return "desconhecido"


def resumo_devolucao(valores) -> dict[str, list[str]]:
    """Agrupa os valores distintos da coluna por estado interpretado.

    Alimenta o mapeador do dashboard: o usuário VÊ como cada categoria
    foi entendida e pode sobrescrever qualquer uma.
    """
    grupos: dict[str, list[str]] = {estado: [] for estado in ESTADOS_DEVOLUCAO}
    vistos: set[str] = set()
    for valor in valores:
        if eh_ausente(valor):
            continue
        normal = normalizar_valor(valor)
        if normal in vistos:
            continue
        vistos.add(normal)
        grupos[interpretar_devolucao(valor)].append(str(valor).strip())
    return grupos
