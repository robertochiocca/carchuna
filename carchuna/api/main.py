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

from fastapi import FastAPI, HTTPException, Query, Request

from carchuna import __version__
from carchuna.analise import AnalisadorMargem
from carchuna.api.limite import (
    LIMITE_CALCULO_POR_JANELA,
    LimiteDeChamadas,
    chave_do_chamador,
)
from carchuna.api.schemas import (
    MAX_PERGUNTA,
    AchadoOut,
    AnaliseRequest,
    BuscaLegalResponse,
    CenarioOut,
    ConferenciasOut,
    CrescimentoResponse,
    DecomposicaoOut,
    DiagnosticoResponse,
    DispositivoOut,
    FontePerdaOut,
    MargemResponse,
    OportunidadeOut,
    PrecoAlvoRequest,
    PrecoAlvoResponse,
    ResultadoOut,
    ResumoExecutivoOut,
)
from carchuna.crescimento import AVISO_CRESCIMENTO, preco_para_margem
from carchuna.diagnostico import ParametrosDiagnostico
from carchuna.margem import conferir_plausibilidade, reconciliar
from carchuna.rag.llm import estado_da_geracao, gerar_resposta, resposta_extrativa
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

_limite = LimiteDeChamadas()
# Os endpoints que calculam têm limite próprio: o custo deles é CPU do
# processo compartilhado, não dinheiro de terceiro, e a conta que define
# o número é outra (ver `limite.py`). Antes só a busca legal tinha
# barreira, e os quatro analíticos aceitavam chamada atrás de chamada no
# teto de lançamentos.
_limite_calculo = LimiteDeChamadas(limite=LIMITE_CALCULO_POR_JANELA)
_retriever = Retriever()  # índice BM25 construído uma vez, na subida


def _cobrar_limite(request: Request, limitador: LimiteDeChamadas, porque: str) -> None:
    """429 com ``Retry-After`` quando o chamador passou da janela.

    A chave é o IP do socket, e o que isso alcança está escrito em
    ``limite.py`` — atrás de proxy ele não distingue chamadores, e o
    estado é por processo. É barreira contra laço acidental e abuso
    simples, não contra abuso distribuído.
    """
    chave = chave_do_chamador(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
    )
    if limitador.permitir(chave):
        return
    espera = limitador.segundos_para_liberar(chave)
    raise HTTPException(
        status_code=429,
        detail=f"Muitas chamadas seguidas. Tente de novo em {espera}s. {porque}",
        headers={"Retry-After": str(espera)},
    )


_PORQUE_CALCULO = (
    "O limite existe porque cada chamada decompõe a sua base inteira, "
    "num processo que atende todo mundo ao mesmo tempo."
)


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
    """Verificação de vida da API, do índice legal e da narrativa opcional.

    `geracao` responde à pergunta que antes não tinha resposta: por que a
    narrativa em linguagem natural não está saindo. Traz o modelo em uso
    e, quando algo falta, o motivo em português — nunca a credencial.
    """
    return {
        "status": "ok",
        "versao": __version__,
        "dispositivos_no_corpus": len(_retriever.dispositivos),
        "geracao": estado_da_geracao(),
    }


@app.post("/api/v1/margem/decompor", response_model=MargemResponse)
def decompor(request: Request, corpo: AnaliseRequest) -> MargemResponse:
    """Decompõe a margem do período, com resumo executivo e conferências.

    As conferências vão no corpo da resposta, e não em código HTTP: uma
    decomposição implausível não é erro de requisição — a conta rodou, o
    número existe, e o que o cliente precisa saber é que não dá para
    confiar nele. Devolver 422 aqui esconderia o número de quem tem todo
    o direito de auditá-lo.
    """
    _cobrar_limite(request, _limite_calculo, _PORQUE_CALCULO)
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
        conferencias=ConferenciasOut(
            plausibilidade=ResultadoOut(
                **asdict(conferir_plausibilidade(analise.decomposicao))
            ),
            reconciliacao=ResultadoOut(
                **asdict(
                    reconciliar(
                        list(analise.transacoes),
                        analise.config,
                        analise.decomposicao,
                        analise.tabela,
                    )
                )
            ),
        ),
    )


@app.post("/api/v1/cenarios", response_model=list[CenarioOut])
def cenarios(request: Request, corpo: AnaliseRequest) -> list[CenarioOut]:
    """Roda a bateria padrão de simulações sobre as vendas enviadas."""
    _cobrar_limite(request, _limite_calculo, _PORQUE_CALCULO)
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
def diagnostico(request: Request, corpo: AnaliseRequest) -> DiagnosticoResponse:
    """Achados das regras de detecção, com base legal citada do corpus."""
    _cobrar_limite(request, _limite_calculo, _PORQUE_CALCULO)
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


@app.post("/api/v1/crescimento", response_model=CrescimentoResponse)
def crescimento(request: Request, corpo: AnaliseRequest) -> CrescimentoResponse:
    """Como faturar mais: mix de canais, preço e espaço no Simples."""
    _cobrar_limite(request, _limite_calculo, _PORQUE_CALCULO)
    analise = _analisador(corpo)
    return CrescimentoResponse(
        oportunidades=[
            OportunidadeOut(
                **{
                    **asdict(o),
                    "base_legal": [DispositivoOut(**asdict(d)) for d in o.base_legal],
                }
            )
            for o in analise.crescimento()
        ],
        aviso=AVISO_CRESCIMENTO,
    )


@app.post("/api/v1/preco-alvo", response_model=PrecoAlvoResponse)
def preco_alvo(request: Request, corpo: PrecoAlvoRequest) -> PrecoAlvoResponse:
    """Preço de equilíbrio e preço para a margem alvo (motor invertido)."""
    _cobrar_limite(request, _limite_calculo, _PORQUE_CALCULO)
    try:
        config = corpo.config.para_dominio()
        tabela = corpo.tabela.para_dominio() if corpo.tabela else None
        equilibrio = preco_para_margem(
            corpo.custo_produto, corpo.frete, corpo.canal, config, tabela
        )
        alvo = preco_para_margem(
            corpo.custo_produto,
            corpo.frete,
            corpo.canal,
            config,
            tabela,
            corpo.margem_alvo,
        )
    except (ValueError, TypeError) as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    return PrecoAlvoResponse(
        canal=corpo.canal,
        preco_equilibrio=equilibrio,
        preco_alvo=alvo,
        margem_alvo=corpo.margem_alvo,
    )


@app.get("/api/v1/legal/buscar", response_model=BuscaLegalResponse)
def buscar_legal(
    request: Request,
    q: str = Query(
        min_length=3,
        max_length=MAX_PERGUNTA,
        description="Pergunta na língua do lojista",
    ),
    top_k: int = Query(default=4, ge=1, le=10),
) -> BuscaLegalResponse:
    """Busca dispositivos no corpus PME (BM25 + sinônimos do lojista).

    Com credencial da API no ambiente e ``CARCHUNA_USAR_LLM=1``, a
    resposta vem em linguagem natural; fora isso, no modo extrativo —
    sempre citando fonte.

    É o único endpoint com limite por **custo de terceiro**: cada chamada
    pode virar uma chamada paga ao modelo, e um laço de shell esvazia o
    crédito de quem subiu a Carchuna.

    Não é o único com limite. Os cinco endpoints que calculam
    (``/margem/decompor``, ``/cenarios``, ``/diagnostico``,
    ``/crescimento``, ``/preco-alvo``) têm o seu, e por outro motivo: ali
    o recurso escasso é CPU do processo que atende todo mundo. Os dois
    números são diferentes porque as duas contas são diferentes —
    ``LIMITE_POR_JANELA`` e ``LIMITE_CALCULO_POR_JANELA``, com o
    raciocínio de cada um ao lado, em ``carchuna/api/limite.py``.
    """
    _cobrar_limite(
        request,
        _limite,
        "O limite existe porque cada busca pode virar uma chamada paga ao "
        "modelo de linguagem.",
    )
    dispositivos = _retriever.buscar(q, top_k=top_k)
    resposta = gerar_resposta(q, dispositivos) or resposta_extrativa(q, dispositivos)
    return BuscaLegalResponse(
        dispositivos=[DispositivoOut(**asdict(d)) for d in dispositivos],
        resposta=resposta,
        aviso=AVISO_LEGAL,
    )
