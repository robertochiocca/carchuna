"""Busca lexical (BM25) sobre o corpus PME.

Portado do DireitoAberto: implementação em Python puro, sem dependências
externas, para que tudo funcione em qualquer ambiente (degradação
graciosa). A interface pública (``Retriever.buscar``) é estável — a
migração para busca semântica (embeddings/ChromaDB, opt-in por variável
de ambiente) está no roadmap e trocará o motor sem alterar a API.

Diferenças em relação ao irmão: corpus ``data/corpus_pme.json``, campo
``revisado`` propagado em cada resultado (dispositivos entram como
``revisado: false`` até revisão humana — o chamador decide como avisar) e
dicionário de sinônimos do lojista.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from carchuna.rag.sinonimos import SINONIMOS_LOJISTA

DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "corpus_pme.json"

AVISO_LEGAL = (
    "Isto é informação geral com base na legislação citada, não parecer "
    "jurídico nem promessa de recuperação de valores. Confirme com seu "
    "contador ou advogado antes de agir."
)

STOPWORDS = {
    "a",
    "o",
    "e",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "um",
    "uma",
    "uns",
    "umas",
    "para",
    "pra",
    "por",
    "com",
    "sem",
    "que",
    "se",
    "ao",
    "aos",
    "as",
    "os",
    "me",
    "meu",
    "minha",
    "meus",
    "minhas",
    "seu",
    "sua",
    "seus",
    "suas",
    "ele",
    "ela",
    "eles",
    "elas",
    "eu",
    "nós",
    "foi",
    "ser",
    "é",
    "são",
    "está",
    "estão",
    "ter",
    "tem",
    "têm",
    "não",
    "sim",
    "mais",
    "menos",
    "muito",
    "já",
    "quando",
    "como",
    "qual",
    "quais",
    "onde",
    "quem",
    "isso",
    "isto",
    "essa",
    "esse",
    "ou",
    "mas",
    "também",
    "até",
    "após",
    "sobre",
    "entre",
    "pelo",
    "pela",
    "quer",
    "quero",
    "posso",
    "pode",
    "podem",
    "devo",
    "deve",
}


def normalizar(texto: str) -> list[str]:
    """Minúsculas, sem acentos, sem stopwords e com plural simples reduzido."""
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    tokens = re.findall(r"[a-z0-9]+", sem_acento)
    resultado = []
    for tok in tokens:
        if tok in _STOPWORDS_NORM or len(tok) <= 1:
            continue
        if len(tok) > 3 and tok.endswith("s"):
            tok = tok[:-1]
        resultado.append(tok)
    return resultado


_STOPWORDS_NORM = {
    "".join(c for c in unicodedata.normalize("NFKD", w) if not unicodedata.combining(c))
    for w in STOPWORDS
}

_SINONIMOS_NORM = {
    normalizar(chave)[0]: [t for alvo in alvos for t in normalizar(alvo)]
    for chave, alvos in SINONIMOS_LOJISTA.items()
    if normalizar(chave)
}


@dataclass
class Dispositivo:
    """Um dispositivo legal recuperado do corpus, com score e status de revisão."""

    id: str
    lei: str
    artigo: str
    tema: str
    texto: str
    resumo: str
    fonte: str
    revisado: bool
    score: float
    # Quem conferiu e quando. `revisado: true` sozinho não afirma nada —
    # não diz se a conferência foi ontem ou há três anos, nem quem a
    # assinou. O que se confere é o RESUMO (que é interpretação, não
    # transcrição) e a VIGÊNCIA na data; as duas coisas envelhecem, e sem
    # data não há como saber se envelheceram.
    conferido_em: str | None = None
    conferido_por: str | None = None


def conferir_integridade_do_corpus(dispositivos: list[dict]) -> None:
    """``revisado: true`` sem data e assinatura não afirma nada — recusa.

    **Por que isto é regra e não convenção.** O diferencial que o README
    vende é "nenhuma afirmação sem lastro", e no corpus o lastro é a
    conferência humana. Um ``revisado: true`` solto não diz quem
    conferiu nem quando: não dá para saber se o resumo foi lido por um
    advogado no mês passado ou marcado em lote por alguém apressado três
    anos atrás. Sem os dois campos, o ``true`` é decoração — e decoração
    que a tela publica como selo de qualidade.

    A regra vale nos dois sentidos, e o segundo importa tanto quanto:
    ``revisado: false`` com data preenchida é contradição, e passaria
    despercebida num arquivo de 21 itens editado à mão.

    **O que ela NÃO confere:** se a conferência aconteceu de verdade,
    se a data é honesta, ou se o resumo está certo. Isso nenhum código
    verifica — é assinatura humana, e vale o que a pessoa que assinou
    vale. O que esta função impede é o estado incoerente.

    Levanta ``ValueError`` com o id do dispositivo. Roda na construção do
    ``Retriever``: corpus incoerente não chega à tela.
    """
    for disp in dispositivos:
        identificador = disp.get("id", "<sem id>")
        revisado = bool(disp.get("revisado", False))
        em = disp.get("conferido_em")
        por = disp.get("conferido_por")
        if revisado and not (em and por):
            raise ValueError(
                f"dispositivo {identificador!r} está `revisado: true` sem "
                "`conferido_em` e `conferido_por` preenchidos. Marcar como "
                "conferido sem dizer quem conferiu e quando não afirma nada: "
                "a tela publicaria um selo que ninguém assinou."
            )
        if not revisado and (em or por):
            raise ValueError(
                f"dispositivo {identificador!r} tem `conferido_em` ou "
                "`conferido_por` preenchido mas está `revisado: false`. Os "
                "três campos descrevem um estado só e não podem discordar."
            )


class Retriever:
    """Índice BM25 sobre os dispositivos legais do corpus PME."""

    K1 = 1.5
    B = 0.75
    # Palavras-chave descrevem o caso concreto melhor que o texto legal,
    # então entram no índice com peso maior (padrão DireitoAberto).
    PESO_PALAVRAS_CHAVE = 3

    def __init__(self, data_path: Path = DATA_PATH):
        raw = json.loads(Path(data_path).read_text(encoding="utf-8"))
        self.aviso_corpus: str = raw.get("aviso", "")
        self.dispositivos = raw["dispositivos"]
        conferir_integridade_do_corpus(self.dispositivos)
        self._docs_tokens: list[list[str]] = []
        for disp in self.dispositivos:
            tokens = normalizar(
                f"{disp['lei']} {disp['artigo']} {disp['texto']} {disp['resumo']}"
            )
            tokens += self.PESO_PALAVRAS_CHAVE * [
                t for p in disp.get("palavras_chave", []) for t in normalizar(p)
            ]
            self._docs_tokens.append(tokens)

        self._doc_freqs = [Counter(toks) for toks in self._docs_tokens]
        self._doc_lens = [len(toks) for toks in self._docs_tokens]
        self._avgdl = sum(self._doc_lens) / max(len(self._doc_lens), 1)
        self._idf: dict[str, float] = {}
        n = len(self._docs_tokens)
        df: Counter = Counter()
        for freqs in self._doc_freqs:
            df.update(freqs.keys())
        for termo, freq in df.items():
            self._idf[termo] = math.log(1 + (n - freq + 0.5) / (freq + 0.5))

    def _expandir_consulta(self, pergunta: str) -> list[str]:
        tokens = normalizar(pergunta)
        expandidos = list(tokens)
        for tok in tokens:
            expandidos.extend(_SINONIMOS_NORM.get(tok, []))
        return expandidos

    def temas(self) -> list[str]:
        return sorted({disp["tema"] for disp in self.dispositivos})

    def buscar(
        self,
        pergunta: str,
        top_k: int = 4,
        score_minimo: float = 1.0,
        tema: str | None = None,
    ) -> list[Dispositivo]:
        """Dispositivos mais relevantes para a pergunta do lojista.

        A consulta é expandida pelo dicionário de sinônimos do lojista
        ("maquininha" também busca "adquirência"). Cada resultado carrega
        ``revisado``: exiba o aviso de revisão pendente quando ``False``.
        """
        consulta = self._expandir_consulta(pergunta)
        resultados = []
        for i, disp in enumerate(self.dispositivos):
            if tema and disp["tema"] != tema:
                continue
            freqs = self._doc_freqs[i]
            dl = self._doc_lens[i]
            score = 0.0
            for termo in consulta:
                if termo not in freqs:
                    continue
                tf = freqs[termo]
                idf = self._idf.get(termo, 0.0)
                score += (
                    idf
                    * (tf * (self.K1 + 1))
                    / (tf + self.K1 * (1 - self.B + self.B * dl / self._avgdl))
                )
            if score >= score_minimo:
                resultados.append(
                    Dispositivo(
                        id=disp["id"],
                        lei=disp["lei"],
                        artigo=disp["artigo"],
                        tema=disp["tema"],
                        texto=disp["texto"],
                        resumo=disp["resumo"],
                        fonte=disp["fonte"],
                        revisado=bool(disp.get("revisado", False)),
                        score=round(score, 3),
                        conferido_em=disp.get("conferido_em"),
                        conferido_por=disp.get("conferido_por"),
                    )
                )
        resultados.sort(key=lambda r: r.score, reverse=True)
        return resultados[:top_k]
