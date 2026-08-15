"""Ingestão semiautomatizada de leis do Planalto para o corpus PME.

Portado do DireitoAberto e adaptado ao esquema de ``data/corpus_pme.json``.

As páginas do Planalto são HTML antigo e irregular, então a ingestão é
**semiautomatizada por desenho**: o parser extrai os artigos e gera
esqueletos com ``"revisado": false`` e resumo marcado como TODO; um humano
confere na fonte oficial, escreve o resumo no vocabulário do lojista e
decide o que entra. Essa é a camada de revisão do projeto, não uma etapa
que se possa automatizar — o `Retriever` propaga o campo ``revisado`` justo
para que o app avise enquanto a conferência não aconteceu.

Duas diferenças em relação ao irmão, ambas motivadas pela LC 123:

- o regex de artigo aceita sufixo de letra (``Art. 18-A``), que o Simples
  usa à exaustão e que o parser original descartava;
- a decodificação tenta UTF-8 antes de cair para windows-1252, porque
  página salva pelo navegador vem em UTF-8 e página baixada crua, não.

Uso via CLI: ``python scripts/ingerir_planalto.py --help``.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser
from typing import NamedTuple

# Os temas em uso no corpus. "revisar" é a caixa de entrada: esqueleto que
# ainda não recebeu classificação humana.
TEMAS_VALIDOS = frozenset(
    {
        "tributario",
        "financeiro",
        "operacional",
        "consumidor",
        "contratual",
        "revisar",
    }
)

_TODO_RESUMO = "TODO: escrever resumo no vocabulário do lojista (revisão humana)"


class _ExtratorTexto(HTMLParser):
    """Converte o HTML do Planalto em texto corrido, ignorando scripts/estilos."""

    _IGNORAR = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._partes: list[str] = []
        self._ignorando = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._IGNORAR:
            self._ignorando += 1
        elif tag in ("p", "br", "div", "tr"):
            self._partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self._IGNORAR and self._ignorando:
            self._ignorando -= 1

    def handle_data(self, data):
        if not self._ignorando:
            self._partes.append(data)

    def texto(self) -> str:
        bruto = "".join(self._partes)
        linhas = [" ".join(linha.split()) for linha in bruto.splitlines()]
        return "\n".join(linha for linha in linhas if linha)


# "Art. 1º", "Art. 2 o" (o Planalto marca o ordinal com <sup>o</sup>),
# "Art. 10.", "Art. 1.694." e "Art. 18-A." — este último é o que a LC 123
# usa para quase tudo que foi acrescentado depois de 2006.
_RE_ARTIGO = re.compile(
    r"(?m)^\s*Art\.?\s*(\d+(?:\.\d+)*(?:-[A-Z])?)\s*[ºo°.]?",
    re.IGNORECASE,
)


def decodificar_html(bruto: bytes, encoding_declarado: str | None = None) -> str:
    """Decodifica HTML do Planalto tolerando as três origens possíveis.

    Página salva pelo navegador sai em UTF-8; página baixada crua costuma
    vir em windows-1252 mal declarado. Tentar UTF-8 estrito primeiro e só
    então cair para o legado evita transformar acento em mojibake sem
    ninguém perceber.
    """
    if encoding_declarado:
        try:
            return bruto.decode(encoding_declarado)
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return bruto.decode("utf-8")
    except UnicodeDecodeError:
        return bruto.decode("windows-1252", errors="replace")


def extrair_texto_html(html: str) -> str:
    parser = _ExtratorTexto()
    parser.feed(html)
    return parser.texto()


def extrair_artigos(html: str) -> list[dict]:
    """Divide o texto da lei em artigos: ``[{'numero': '18-A', 'texto': ...}]``."""
    texto = extrair_texto_html(html)
    encontrados = list(_RE_ARTIGO.finditer(texto))
    artigos = []
    for i, m in enumerate(encontrados):
        fim = encontrados[i + 1].start() if i + 1 < len(encontrados) else len(texto)
        corpo = " ".join(texto[m.start() : fim].split())
        artigos.append({"numero": m.group(1).upper(), "texto": corpo})
    return artigos


def _slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", sem_acento).strip("-")


def _id_artigo(prefixo: str, numero: str) -> str:
    return f"{prefixo}-{numero.replace('.', '').replace('-', '').lower()}"


def gerar_esqueletos(
    html: str,
    lei: str,
    fonte: str,
    tema: str = "revisar",
    numeros: list[str] | None = None,
    prefixo: str | None = None,
) -> list[dict]:
    """Gera entradas no formato do corpus PME, prontas para revisão humana.

    ``prefixo`` define o começo do ``id`` (ex.: ``lc123`` produz
    ``lc123-18a``), mantendo a convenção curta dos dispositivos já no
    corpus. Sem ele, o slug do nome oficial da lei vira um id ilegível.
    """
    if tema not in TEMAS_VALIDOS:
        validos = ", ".join(sorted(TEMAS_VALIDOS))
        raise ValueError(f"Tema '{tema}' fora do corpus. Válidos: {validos}.")
    prefixo = prefixo or _slug(lei)
    alvos = {n.upper() for n in numeros} if numeros else None

    esqueletos = []
    for art in extrair_artigos(html):
        if alvos and art["numero"] not in alvos:
            continue
        esqueletos.append(
            {
                "id": _id_artigo(prefixo, art["numero"]),
                "lei": lei,
                "artigo": f"Art. {art['numero']}",
                "tema": tema,
                "texto": art["texto"],
                "resumo": _TODO_RESUMO,
                "palavras_chave": [],
                "fonte": fonte,
                "revisado": False,
                # O esqueleto nasce não conferido, e os três campos dizem
                # isso juntos. `revisado: false` com data preenchida seria
                # contradição; a regra de integridade do corpus recusa.
                "conferido_em": None,
                "conferido_por": None,
            }
        )
    return esqueletos


class ResultadoMesclagem(NamedTuple):
    """O que a mesclagem fez com cada id — para o script relatar sem inventar."""

    adicionados: list[str]
    atualizados: list[str]
    preservados: list[str]


def _e_esqueleto_intocado(disp: dict) -> bool:
    """Só é descartável o esqueleto em que ninguém encostou.

    ``revisado: false`` **não** significa descartável: no corpus de hoje
    todo dispositivo tem resumo escrito à mão e segue não revisado, porque
    o que falta é a conferência na fonte oficial, não o trabalho. Apagar
    esses resumos numa reingestão seria destruir horas de escrita.

    ``conferido_em`` entra na conta pela mesma razão, e é a guarda mais
    barata que existe: dispositivo com data de conferência jamais é
    esqueleto, qualquer que seja o resto. Sem esta linha, um resumo
    reescrito para começar com "TODO" depois de conferido derrubaria a
    conferência numa reingestão.
    """
    resumo = disp.get("resumo", "")
    return (
        not disp.get("revisado")
        and not disp.get("conferido_em")
        and resumo.startswith("TODO")
        and not disp.get("palavras_chave")
    )


def mesclar_no_corpus(corpus: dict, novos: list[dict]) -> ResultadoMesclagem:
    """Insere esqueletos no corpus **sem jamais sobrescrever trabalho humano**.

    Id já existente só é substituído quando o que está lá é esqueleto
    intocado (resumo TODO e sem palavras-chave). Qualquer outra coisa —
    revisada ou apenas escrita à mão — é preservada, e o script relata o
    id para você decidir na mão.

    Modifica ``corpus`` no lugar e devolve o que aconteceu.
    """
    indice = {d["id"]: i for i, d in enumerate(corpus["dispositivos"])}
    adicionados: list[str] = []
    atualizados: list[str] = []
    preservados: list[str] = []

    for novo in novos:
        pos = indice.get(novo["id"])
        if pos is None:
            indice[novo["id"]] = len(corpus["dispositivos"])
            corpus["dispositivos"].append(novo)
            adicionados.append(novo["id"])
        elif _e_esqueleto_intocado(corpus["dispositivos"][pos]):
            corpus["dispositivos"][pos] = novo
            atualizados.append(novo["id"])
        else:
            preservados.append(novo["id"])

    return ResultadoMesclagem(adicionados, atualizados, preservados)
