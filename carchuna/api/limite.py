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

import os
import threading
import time
from collections import deque

# Sessão de uso real: o lojista pergunta, lê a resposta com a citação da
# lei, pensa, pergunta de novo. Trinta por minuto é folgado para isso e
# curto para um laço.
LIMITE_POR_JANELA = 30
JANELA_SEGUNDOS = 60

# Limite dos endpoints que calculam. O custo aqui é CPU e não dinheiro de
# terceiro, então a conta é outra: uma chamada no teto de lançamentos
# leva cerca de 8 segundos de um processo que atende todos os
# visitantes. A 30/minuto, um único IP pediria quatro minutos de CPU por
# minuto de relógio. Doze é uma a cada cinco segundos — folgado para
# pessoa e para integração honesta, apertado para quem quer ocupar a
# máquina.
LIMITE_CALCULO_POR_JANELA = 12

# De quantas em quantas chamadas o dicionário de marcas é varrido atrás
# de chave ociosa. Ver `LimiteDeChamadas._varrer` para o porquê de ser
# varredura periódica e não remoção por chamada.
#
# 256 é o meio-termo entre as duas coisas que a escolha equilibra: varrer
# demais custa O(chaves) toda hora, varrer de menos deixa o dicionário
# crescer entre as varreduras. Com um IP novo por chamada — o pior caso
# — o dicionário chega a 256 entradas antes de encolher, o que é
# desprezível em memória; com tráfego normal, a varredura roda a cada
# poucos minutos e não encontra quase nada.
CHAMADAS_ENTRE_VARREDURAS = 256


# Cabeçalho que um proxy reverso usa para dizer quem é o chamador real.
# Ele é **texto que o cliente manda**: sem um proxy confiável na frente,
# qualquer um escreve o que quiser ali e ganha uma janela nova por
# requisição. Por isso ler o cabeçalho é opt-in do operador, que é quem
# sabe se existe proxy e quantos.
CHAVE_PROXIES_CONFIAVEIS = "CARCHUNA_PROXIES_CONFIAVEIS"


def chave_do_chamador(ip_do_socket: str | None, encaminhado: str | None) -> str:
    """Quem contar como "o mesmo chamador" para efeito de limite.

    Sem proxy declarado, vale o IP do socket e o cabeçalho é ignorado —
    confiar nele por padrão é entregar o limite a quem ele deveria
    limitar, porque `X-Forwarded-For: <aleatório>` reinicia a contagem.

    Com ``CARCHUNA_PROXIES_CONFIAVEIS=n``, os ``n`` saltos da direita
    são os proxies da própria infraestrutura, e o cliente real é o que
    está logo à esquerda deles. Contar da direita para a esquerda é o que
    importa: a parte esquerda da lista é escrita pelo cliente e não vale
    nada.

    **O que isto continua não resolvendo.** Atrás de um CDN sem a
    variável configurada, todos os visitantes compartilham um IP e o
    limite vira bloqueio coletivo. E o estado é por processo: dois
    workers são dois limites. Ver o topo deste módulo.
    """
    quantos = os.environ.get(CHAVE_PROXIES_CONFIAVEIS, "0")
    confiaveis = int(quantos) if quantos.isdigit() else 0
    if confiaveis and encaminhado:
        saltos = [parte.strip() for parte in encaminhado.split(",") if parte.strip()]
        # O salto imediatamente à esquerda dos nossos proxies.
        indice = len(saltos) - confiaveis - 1
        if 0 <= indice < len(saltos):
            return saltos[indice]
    return ip_do_socket or "desconhecido"


class LimiteDeChamadas:
    """Janela deslizante por chave, protegida por lock.

    Deslizante, e não fixa por minuto, porque a janela fixa deixa passar
    o dobro do limite na virada — 30 chamadas no fim de um minuto e 30 no
    começo do seguinte são 60 em dois segundos.
    """

    def __init__(
        self,
        limite: int = LIMITE_POR_JANELA,
        janela: int = JANELA_SEGUNDOS,
        chamadas_entre_varreduras: int = CHAMADAS_ENTRE_VARREDURAS,
    ):
        self.limite = limite
        self.janela = janela
        self.chamadas_entre_varreduras = chamadas_entre_varreduras
        self._marcas: dict[str, deque[float]] = {}
        self._desde_a_varredura = 0
        self._lock = threading.Lock()

    def _varrer(self, corte: float) -> None:
        """Remove as chaves que não têm mais marca dentro da janela.

        **Por que varredura periódica e não remoção por chamada.** O
        código antigo tentava a segunda e não fazia nada: apagava a chave
        e a recriava na linha seguinte, com um comentário prometendo que
        chave ociosa não ocuparia memória para sempre. O dicionário nunca
        encolhia.

        E a promessa não se cumpre nem escrevendo aquele trecho direito,
        porque a chave que `permitir` está tratando **nunca** é a que
        precisa sair: no caminho de sucesso ela acabou de receber uma
        marca, e no caminho negado o deque está cheio. Quem envelhece é o
        IP que parou de chamar, e ele só é alcançado por alguém que
        percorra o dicionário.

        Chamado com o lock tomado.

        **O custo, declarado:** a varredura é O(chaves) e roda a cada
        ``chamadas_entre_varreduras`` chamadas, então o custo amortizado
        por chamada é O(chaves ÷ N). Não é de graça, e é por isso que não
        roda em toda chamada.

        **O que continua não resolvendo:** entre duas varreduras o
        dicionário cresce, e o estado segue por processo — dois workers,
        dois dicionários. Ver o topo deste módulo.
        """
        ociosas = [
            chave
            for chave, marcas in self._marcas.items()
            if not marcas or marcas[-1] <= corte
        ]
        for chave in ociosas:
            del self._marcas[chave]

    def permitir(self, chave: str, agora: float | None = None) -> bool:
        """Registra a chamada e diz se ela cabe na janela.

        ``agora`` é injetável para o teste não precisar dormir de verdade.
        """
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            corte = agora - self.janela
            self._desde_a_varredura += 1
            if self._desde_a_varredura >= self.chamadas_entre_varreduras:
                self._varrer(corte)
                self._desde_a_varredura = 0
            marcas = self._marcas.setdefault(chave, deque())
            while marcas and marcas[0] <= corte:
                marcas.popleft()
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
