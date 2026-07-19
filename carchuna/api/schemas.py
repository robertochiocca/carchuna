"""Esquemas Pydantic da API v1 — a fronteira de validação da Carchuna.

Dinheiro trafega como ``Decimal`` e é serializado como **string** no
JSON (nunca float), preservando centavo a centavo a mesma garantia do
motor. A conversão para as dataclasses do núcleo é explícita: a API é
uma casca fina; quem calcula é o motor testado.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

from carchuna.margem import ConfigTributaria, TabelaCustos, Transacao

# Decimal serializado como string no JSON: "5.65", nunca 5.65 (float).
Dinheiro = Annotated[Decimal, PlainSerializer(str, return_type=str, when_used="json")]

Canal = Literal["mercado_livre", "shopee", "amazon", "loja_propria", "fisico"]


class TransacaoIn(BaseModel):
    data: date
    canal: Canal
    valor_bruto: Dinheiro
    custo_produto: Dinheiro
    frete_pago: Dinheiro
    devolvida: bool = False
    prazo_recebimento_dias: int = Field(default=0, ge=0)
    comissao_cobrada: Dinheiro | None = None

    def para_dominio(self) -> Transacao:
        return Transacao(**self.model_dump())


class ConfigTributariaIn(BaseModel):
    regime: Literal["simples", "mei"]
    anexo_simples: Literal["I", "II", "III", "IV", "V"] | None = None
    rbt12: Dinheiro = Decimal("0")
    das_mei_mensal: Dinheiro | None = None

    def para_dominio(self) -> ConfigTributaria:
        return ConfigTributaria(**self.model_dump())


class TabelaCustosIn(BaseModel):
    comissao_canal: dict[Canal, Dinheiro] | None = None
    taxa_adquirencia: Dinheiro | None = None
    taxa_antecipacao_mensal: Dinheiro | None = None

    def para_dominio(self) -> TabelaCustos:
        campos = {k: v for k, v in self.model_dump().items() if v is not None}
        return TabelaCustos(**campos)


class AnaliseRequest(BaseModel):
    """Corpo comum: vendas + configuração tributária + custos opcionais."""

    transacoes: list[TransacaoIn] = Field(min_length=1)
    config: ConfigTributariaIn
    tabela: TabelaCustosIn | None = None
    atividade: Literal["comercio", "industria", "servicos"] = "comercio"


class DeducaoOut(BaseModel):
    nome: str
    valor: Dinheiro
    pct_receita: Dinheiro
    fonte: str
    confianca: str


class DecomposicaoOut(BaseModel):
    receita_bruta: Dinheiro
    deducoes: list[DeducaoOut]
    margem_liquida: Dinheiro
    margem_pct: Dinheiro
    aliquota_efetiva: Dinheiro | None


class FontePerdaOut(BaseModel):
    nome: str
    rotulo: str
    valor: Dinheiro
    pct_da_perda: Dinheiro


class ResumoExecutivoOut(BaseModel):
    meses: int
    receita_bruta: Dinheiro
    margem_anunciada: Dinheiro
    margem_anunciada_pct: Dinheiro
    margem_real: Dinheiro
    margem_real_pct: Dinheiro
    perda_total: Dinheiro
    fontes_perda: list[FontePerdaOut]
    frase: str


class MargemResponse(BaseModel):
    decomposicao: DecomposicaoOut
    resumo: ResumoExecutivoOut


class DispositivoOut(BaseModel):
    id: str
    lei: str
    artigo: str
    tema: str
    resumo: str
    fonte: str
    revisado: bool
    score: float


class AchadoOut(BaseModel):
    tipo: str
    titulo: str
    impacto_mensal: Dinheiro
    explicacao: str
    base_legal: list[DispositivoOut]
    caminho_pratico: str
    confianca: str
    aviso: str


class DiagnosticoResponse(BaseModel):
    achados: list[AchadoOut]
    aviso_corpus: str


class CenarioOut(BaseModel):
    nome: str
    margem_base: Dinheiro
    margem_cenario: Dinheiro
    impacto_reais: Dinheiro
    impacto_pp: Dinheiro


class BuscaLegalResponse(BaseModel):
    dispositivos: list[DispositivoOut]
    resposta: str
    aviso: str
