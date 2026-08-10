"""Limite de chamadas por janela, em memória e sem dependência nova.

Existe por causa de um endpoint só: ``/api/v1/legal/buscar`` é o único
que pode gastar dinheiro de terceiro por requisição — cada chamada pode
virar uma chamada ao LLM. Sem limite, um laço de shell esvazia o crédito
da conta de quem subiu a Carchuna, e a busca no corpus BM25 roda por
cima disso.

**O que este limite é.** Uma barreira contra abuso acidental e contra o
laço distraído: alguém testando a API, um script sem `sleep`, um cliente
com retry mal configurado.

**O que ele NÃO é.** Defesa contra abuso deliberado e distribuído. A
janela vive na memória do processo: sobe com mais de um worker e cada um
tem a sua contagem; reinicie o processo e a contagem zera; um atacante
com muitos IPs passa por ela. Fazer melhor exige estado compartilhado
(Redis) e identidade do chamador (autenticação), que estão os dois no
roadmap e nenhum deles na v1 — e uma barreira honesta com o alcance
escrito vale mais que nenhuma barreira, desde que ninguém a confunda com
o que ela não faz.
"""

from __future__ import annotations

import threading
import time
from collections import deque

# Sessão de uso real: o lojista pergunta, lê a resposta com a citação da
# lei, pensa, pergunta de novo. Trinta por minuto é folgado para isso e
# curto para um laço.
LIMITE_POR_JANELA = 30
JANELA_SEGUNDOS = 60


class LimiteDeChamadas:
    """Janela deslizante por chave, protegida por lock.

    Deslizante, e não fixa por minuto, porque a janela fixa deixa passar
    o dobro do limite na virada — 30 chamadas no fim de um minuto e 30 no
    começo do seguinte são 60 em dois segundos.
    """

    def __init__(self, limite: int = LIMITE_POR_JANELA, janela: int = JANELA_SEGUNDOS):
        self.limite = limite
        self.janela = janela
        self._marcas: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def permitir(self, chave: str, agora: float | None = None) -> bool:
        """Registra a chamada e diz se ela cabe na janela.

        ``agora`` é injetável para o teste não precisar dormir de verdade.
        """
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            marcas = self._marcas.setdefault(chave, deque())
            corte = agora - self.janela
            while marcas and marcas[0] <= corte:
                marcas.popleft()
            if not marcas:
                # chave ociosa não fica ocupando memória para sempre
                del self._marcas[chave]
                marcas = self._marcas.setdefault(chave, deque())
            if len(marcas) >= self.limite:
                return False
            marcas.append(agora)
            return True

    def segundos_para_liberar(self, chave: str, agora: float | None = None) -> int:
        """Quanto falta para a chamada mais antiga sair da janela."""
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            marcas = self._marcas.get(chave)
            if not marcas:
                return 0
            return max(1, int(marcas[0] + self.janela - agora) + 1)
