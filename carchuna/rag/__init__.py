"""Motor legal da Carchuna: BM25 + sinônimos do lojista + LLM opcional."""

from carchuna.rag.llm import gerar_resposta, resposta_extrativa
from carchuna.rag.retrieval import AVISO_LEGAL, Dispositivo, Retriever
from carchuna.rag.sinonimos import SINONIMOS_LOJISTA

__all__ = [
    "AVISO_LEGAL",
    "Dispositivo",
    "Retriever",
    "SINONIMOS_LOJISTA",
    "gerar_resposta",
    "resposta_extrativa",
]
