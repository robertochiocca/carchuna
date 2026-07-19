"""Interface ``Conector`` — como dados de venda entram na Carchuna.

Mesmo padrão do ``Retriever``: uma interface estável, motores trocáveis.
Hoje existe um conector real (:class:`ConectorArquivo`, para CSV/JSON/
XLSX exportados de qualquer canal); os conectores de API dos
marketplaces implementarão a MESMA interface, então nada acima desta
camada muda quando eles chegarem.

O que cada conector de API exigirá (roadmap honesto, sem promessa):

- **Shopee** — Shopee Open Platform (open.shopee.com): cadastro de
  desenvolvedor, app aprovado pela Shopee e autorização OAuth do
  lojista; endpoints de pedidos (``order.get_order_list``) e de repasses
  (``payment.get_escrow_detail``, que traz comissão e taxas por pedido —
  exatamente o ``comissao_cobrada`` da Carchuna).
- **Mercado Livre** — developers.mercadolivre.com.br: app registrado e
  OAuth do vendedor; ``/orders/search`` e ``/billing`` para tarifas.
- **Nunca** armazenar senha do lojista: apenas tokens OAuth revogáveis,
  e credenciais bancárias só via agregador homologado (Open Finance).

Enquanto os conectores de API não existem, TODO marketplace já entra na
Carchuna pelo caminho universal: exportar o relatório de vendas do
painel do canal (Shopee: Meus Dados → Exportar; ML: Vendas → Baixar
relatório) e importar o arquivo — ver ``TUTORIAL.md``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from carchuna.dados import carregar_transacoes
from carchuna.margem import Transacao


class Conector(ABC):
    """Fonte de transações de venda, atrás de uma interface estável."""

    @property
    @abstractmethod
    def nome(self) -> str:
        """Nome legível da fonte (ex.: "arquivo CSV", "Shopee API")."""

    @abstractmethod
    def transacoes(
        self,
        inicio: date | None = None,
        fim: date | None = None,
    ) -> list[Transacao]:
        """Transações da fonte, opcionalmente filtradas por período."""


class ConectorArquivo(Conector):
    """Conector v1: arquivos CSV/JSON/XLSX exportados de qualquer canal.

    É o caminho do piloto ("CSV valida a tese antes de qualquer
    conector de API") e continuará existindo depois deles — todo canal
    tem exportação de planilha, nem todo lojista quer conectar OAuth.
    """

    def __init__(self, source, name: str | None = None):
        self._source = source
        self._name = name

    @property
    def nome(self) -> str:
        return f"arquivo ({self._name or self._source})"

    def transacoes(
        self,
        inicio: date | None = None,
        fim: date | None = None,
    ) -> list[Transacao]:
        todas = carregar_transacoes(self._source, name=self._name)
        return [
            t
            for t in todas
            if (inicio is None or t.data >= inicio) and (fim is None or t.data <= fim)
        ]
