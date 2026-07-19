"""API pública da Carchuna — FastAPI, versionada em ``/api/v1``.

Casca fina e **stateless** sobre o ``AnalisadorMargem``: valida com
Pydantic, delega ao motor testado e devolve JSON com dinheiro em string
(nunca float). OpenAPI interativa em ``/docs``.

Roadmap explícito (ver README): autenticação (PBKDF2 + Bearer, padrão
DireitoAberto) e persistência (SQLAlchemy; SQLite → PostgreSQL via env)
entram quando houver um piloto real multiusuário — a v1 não armazena
nada de quem chama.

Uso::

    uvicorn carchuna.api.main:app --reload
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query

from carchuna import __version__
from carchuna.analise import AnalisadorMargem
from carchuna.api.schemas import (
    AchadoOut,
    AnaliseRequest,
    BuscaLegalResponse,
    CenarioOut,
    DecomposicaoOut,
    DiagnosticoResponse,
    DispositivoOut,
    FontePerdaOut,
    MargemResponse,
    ResumoExecutivoOut,
)
from carchuna.diagnostico import ParametrosDiagnostico
from carchuna.rag.llm import gerar_resposta, resposta_extrativa
from carchuna.rag.retrieval import AVISO_LEGAL, Retriever

app = FastAPI(
    title="Carchuna API",
    version=__version__,
    description=(
        "Raio-X verificável da margem para PMEs brasileiras. Todo número é "
        "calculado por código testado; toda base legal é citada com fonte "
        "oficial. Projeto de portfólio — não é aconselhamento "
        "jurídico/contábil."
    ),
)

_retriever = Retriever()  # índice BM25 construído uma vez, na subida


def _analisador(corpo: AnaliseRequest) -> AnalisadorMargem:
    try:
        return AnalisadorMargem(
            transacoes=[t.para_dominio() for t in corpo.transacoes],
            config=corpo.config.para_dominio(),
            tabela=corpo.tabela.para_dominio() if corpo.tabela else None,
            parametros=ParametrosDiagnostico(atividade=corpo.atividade),
            retriever=_retriever,
        )
    except (ValueError, TypeError) as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro


@app.get("/api/v1/saude")
def saude() -> dict:
    """Verificação de vida da API (e do índice legal)."""
    return {
        "status": "ok",
        "versao": __version__,
        "dispositivos_no_corpus": len(_retriever.dispositivos),
    }


@app.post("/api/v1/margem/decompor", response_model=MargemResponse)
def decompor(corpo: AnaliseRequest) -> MargemResponse:
    """Decompõe a margem do período e devolve o resumo executivo."""
    analise = _analisador(corpo)
    resumo = analise.resumo_executivo()
    return MargemResponse(
        decomposicao=DecomposicaoOut(**asdict(analise.decomposicao)),
        resumo=ResumoExecutivoOut(
            **{
                **asdict(resumo),
                "fontes_perda": [
                    FontePerdaOut(**asdict(f)) for f in resumo.fontes_perda
                ],
                "frase": resumo.frase(),
            }
        ),
    )


@app.post("/api/v1/cenarios", response_model=list[CenarioOut])
def cenarios(corpo: AnaliseRequest) -> list[CenarioOut]:
    """Roda a bateria padrão de simulações sobre as vendas enviadas."""
    analise = _analisador(corpo)
    return [
        CenarioOut(
            nome=r.nome,
            margem_base=r.base.margem_liquida,
            margem_cenario=r.cenario.margem_liquida,
            impacto_reais=r.impacto_reais,
            impacto_pp=r.impacto_pp,
        )
        for r in analise.cenarios()
    ]


@app.post("/api/v1/diagnostico", response_model=DiagnosticoResponse)
def diagnostico(corpo: AnaliseRequest) -> DiagnosticoResponse:
    """Achados das regras de detecção, com base legal citada do corpus."""
    analise = _analisador(corpo)
    return DiagnosticoResponse(
        achados=[
            AchadoOut(
                **{
                    **asdict(achado),
                    "base_legal": [
                        DispositivoOut(**asdict(d)) for d in achado.base_legal
                    ],
                }
            )
            for achado in analise.diagnosticar()
        ],
        aviso_corpus=_retriever.aviso_corpus,
    )


@app.get("/api/v1/legal/buscar", response_model=BuscaLegalResponse)
def buscar_legal(
    q: str = Query(min_length=3, description="Pergunta na língua do lojista"),
    top_k: int = Query(default=4, ge=1, le=10),
) -> BuscaLegalResponse:
    """Busca dispositivos no corpus PME (BM25 + sinônimos do lojista).

    Com ``ANTHROPIC_API_KEY`` no ambiente, a resposta vem em linguagem
    natural; sem chave, no modo extrativo — sempre citando fonte.
    """
    dispositivos = _retriever.buscar(q, top_k=top_k)
    resposta = gerar_resposta(q, dispositivos) or resposta_extrativa(q, dispositivos)
    return BuscaLegalResponse(
        dispositivos=[DispositivoOut(**asdict(d)) for d in dispositivos],
        resposta=resposta,
        aviso=AVISO_LEGAL,
    )
