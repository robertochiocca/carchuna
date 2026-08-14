"""Importação de vendas (CSV/Excel/JSON) e dados sintéticos para demo.

Adaptado do padrão de ``data.py`` da Calahonda: valida, limpa e — na
ausência de dados reais — gera um conjunto sintético reprodutível que
permite rodar todo o projeto offline.

Dinheiro entra como ``str`` e vira ``Decimal`` direto (nunca passa por
``float``); no JSON os números são lidos com ``parse_float=str`` pela
mesma razão.

O Excel é a exceção que não dá para fechar: o arquivo já guarda a célula
em ponto flutuante, e o openpyxl a entrega como ``float`` — o erro é
anterior à Carchuna. O que a fronteira faz é não deixá-lo entrar: todo
``float`` de planilha é quantizado a centavos com ``ROUND_HALF_UP`` em
``_celula_de_planilha`` antes de virar texto. Então a garantia é "o motor
nunca calcula em float", e ela não se estende ao que o Excel já
arredondou antes de o arquivo chegar.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import random
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from carchuna.margem import Transacao
from carchuna.tipos import (
    eh_ausente,
    interpretar_devolucao,
    normalizar_valor,
)

COLUNAS_OBRIGATORIAS = (
    "data",
    "canal",
    "valor_bruto",
    "custo_produto",
    "frete_pago",
)
COLUNAS_OPCIONAIS = (
    "devolvida",
    "prazo_recebimento_dias",
    "comissao_cobrada",
    "produto",
)


# "1.234", "12.345.678" — grupos de milhar sem centavos. O primeiro grupo
# não pode começar em zero: "0.500" é meio real, e ninguém escreve
# quinhentos reais assim. Sem essa ressalva a regra do milhar cometeria,
# na direção oposta, o mesmo erro de mil vezes que ela existe para corrigir.
_MILHAR_SEM_CENTAVO = re.compile(r"^[+-]?[1-9]\d{0,2}(\.\d{3})+$")

# "1234.567": quatro dígitos ou mais antes de um ponto com exatamente três
# casas. Pode ser milhar ("1.234.567" mal digitado) ou decimal de três
# casas, e as duas leituras diferem por mil.
_PONTO_AMBIGUO = re.compile(r"^[+-]?\d{4,}\.\d{3}$")


def _para_decimal(texto: str) -> Decimal:
    """'R$ 1.234,56', '1.234' ou '1234.56' → Decimal, sem passar por float.

    A ordem das decisões importa, e cada uma existe por um arquivo real:

    1. os dois separadores presentes e o ponto DEPOIS da vírgula → formato
       americano, e aí a função recusa;
    2. tem vírgula → formato brasileiro, o ponto é milhar;
    3. sem vírgula, mas em grupos de três → o ponto é milhar. É o caso que
       dividia por mil em silêncio: painel que exporta valor redondo manda
       "1.234", e a heurística antiga lia um real e vinte e três;
    4. um ponto só, com uma ou duas casas → decimal, como sempre foi;
    5. um ponto só, com exatamente três casas e quatro dígitos ou mais
       antes → **ambíguo de verdade**, e aí a função recusa.

    O passo 1 fecha o erro de mil pelo lado oposto ao do passo 5. O ramo
    brasileiro apagava os pontos e trocava a vírgula por ponto sem olhar a
    ORDEM dos separadores, então "1,234.56" — Amazon Seller Central e boa
    parte dos ERPs exportam assim — virava ``Decimal("1.23456")``. Mil
    vezes menor, calado, e do mesmo jeito que o passo 5 já impedia na
    outra direção.

    **O que ela não faz: adivinhar locale.** Ninguém converte en-US em
    silêncio aqui. Um arquivo americano pode trazer "1,234" — que é mil
    duzentos e trinta e quatro em en-US e um vírgula duzentos e trinta e
    quatro em pt-BR — e nada no valor diz qual dos dois é. Converter o
    caso decidível e recusar o indecidível deixaria metade do arquivo
    numa leitura e metade na outra, que é pior que recusar as duas.

    Os passos 1 e 5 vão irritar alguém. Irritar é melhor que errar por
    mil: um valor mil vezes menor não estoura nada, entra na soma e sai
    na tela como margem, e ninguém tem como desconfiar olhando o
    resultado.
    """
    limpo = str(texto).strip().replace("R$", "").replace(" ", "")
    if "." in limpo and "," in limpo and limpo.rfind(".") > limpo.rfind(","):
        americano = limpo.replace(",", "")
        como_brasileiro = limpo.replace(".", "").replace(",", ".")
        raise ValueError(
            f"{texto!r} está em formato americano: a vírgula separa o "
            f"milhar e o ponto separa os centavos. Lido assim, o valor é "
            f"{americano}. Lido como brasileiro, que é como a Carchuna lê "
            f"o resto do arquivo, sairia {como_brasileiro} — mil vezes "
            "menor, e sem estourar nada. A Carchuna não adivinha o "
            "formato do arquivo: reexporte a planilha em pt-BR "
            "(1.234,56) ou converta essa coluna antes de subir."
        )
    if "," in limpo:  # formato brasileiro: ponto de milhar, vírgula decimal
        return Decimal(limpo.replace(".", "").replace(",", "."))
    if _MILHAR_SEM_CENTAVO.match(limpo):
        return Decimal(limpo.replace(".", ""))
    if _PONTO_AMBIGUO.match(limpo):
        raise ValueError(
            f"{texto!r} pode ser {limpo.replace('.', '')} (ponto de milhar) ou "
            f"{limpo} (três casas decimais), e a diferença entre as duas "
            "leituras é de mil vezes. A Carchuna não chuta: reexporte a "
            "planilha com os centavos (1.234.567,00) ou confira essa coluna."
        )
    return Decimal(limpo)


def decimal_de_texto(texto: str, campo: str = "valor") -> Decimal:
    """Converte o que a pessoa digitou em ``Decimal``, sem passar por float.

    É o mesmo parser das planilhas, exposto para os formulários: a taxa
    da maquininha digitada como ``2,49`` precisa virar ``Decimal("2.49")``
    e não ``2.49`` em ponto flutuante, porque esse número multiplica cada
    venda da base. ``st.number_input`` devolve ``float`` — por isso o
    dashboard lê percentual como texto e chama esta função.
    """
    try:
        return _para_decimal(texto)
    except InvalidOperation:
        raise ValueError(
            f"`{campo}` = {texto!r} não é um número válido. "
            "Use vírgula ou ponto para os centavos (ex.: 2,49)."
        ) from None
    except ValueError as ambiguo:
        # a recusa do ponto ambíguo já explica o problema; falta só dizer
        # em qual campo ele apareceu
        raise ValueError(f"`{campo}`: {ambiguo}") from None


def _decimal_br(texto: str, campo: str, linha: int) -> Decimal:
    """Como ``decimal_de_texto``, mas com o número da linha na mensagem.

    As recusas do ``_para_decimal`` — formato americano e ponto ambíguo —
    já explicam o problema; o que falta nelas é ONDE ele está. Sem este
    prefixo, a linha vira ``LinhaRejeitada`` com um motivo que não diz
    qual linha nem qual coluna, e quem recebe o relatório não tem por
    onde começar a consertar a planilha.
    """
    try:
        return _para_decimal(texto)
    except InvalidOperation:
        raise ValueError(
            f"linha {linha}: `{campo}` = {texto!r} não é um valor monetário válido."
        ) from None
    except ValueError as recusa:
        raise ValueError(f"linha {linha}: `{campo}`: {recusa}") from None


# Formatos de data tentados, em ordem. `dd/mm` vem antes de qualquer leitura
# `mm/dd` porque o público é brasileiro: 05/01/2026 é 5 de janeiro. O formato
# americano não entra na lista — adivinhar entre os dois em silêncio trocaria
# meses inteiros de lugar sem o lojista perceber.
_FORMATOS_DATA = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%y")


def _data_br(texto: str, linha: int) -> date:
    """Converte a data de qualquer painel em ``date``.

    Aceita ISO (``2026-05-01``, com ou sem hora), o padrão brasileiro
    (``01/05/2026``) e as variantes de ERP com ``-`` ou ``.``. A parte de
    hora é descartada: a Carchuna trabalha por dia.
    """
    bruto = str(texto).strip()
    # descarta a hora: '2026-05-01 14:32', '01/05/2026 14:32', ISO 8601 com T
    dia = bruto.replace("T", " ").split(" ")[0]
    try:
        return date.fromisoformat(dia)
    except ValueError:
        pass
    for formato in _FORMATOS_DATA:
        try:
            return datetime.strptime(dia, formato).date()
        except ValueError:
            continue
    raise ValueError(
        f"linha {linha}: `data` = {texto!r} não é uma data que eu saiba ler. "
        "Use dd/mm/aaaa (ex.: 01/05/2026) ou aaaa-mm-dd (ex.: 2026-05-01). "
        "Se a coluna veio do painel do marketplace com data e hora juntas, "
        "pode deixar — a hora é ignorada."
    )


def _devolvida_de(texto, linha: int, interpretacao: dict[str, bool] | None) -> bool:
    """Converte a coluna de devolução para o booleano do motor.

    Três camadas, nesta ordem (léxicos centralizados em ``tipos.py``):

    1. ausente → ``False`` (sem informação de devolução = venda normal —
       premissa documentada, distinta de valor inválido);
    2. decisão do USUÁRIO (``interpretacao``: valor normalizado → bool),
       que sobrepõe qualquer inferência;
    3. semântica de negócio: booleanos e status conclusivos
       ("Solicitação aprovada" → devolvida; "Solicitação recusada" →
       não). Estado intermediário ("Em análise") ou fora do léxico NUNCA
       vira sim/não em silêncio: o erro explica como decidir.

    Quem chama pelo caminho do relatório (``carregar_com_relatorio``,
    ``relatorio_de_mapa``) recolhe esse erro como ``LinhaRejeitada``: a
    linha ambígua fica de fora e aparece na lista, em vez de derrubar a
    importação inteira.
    """
    if eh_ausente(texto):
        return False
    if interpretacao is not None:
        decidido = interpretacao.get(normalizar_valor(texto))
        if decidido is not None:
            return decidido
    estado = interpretar_devolucao(texto)
    if estado == "devolvida":
        return True
    if estado == "nao_devolvida":
        return False
    if estado == "indefinido":
        motivo = "é um status intermediário (a devolução ainda não se resolveu)"
    elif estado == "cancelada":
        motivo = (
            "diz que algo foi cancelado, mas não diz o quê — e as duas "
            "leituras vão para lados opostos: cancelar a SOLICITAÇÃO DE "
            "DEVOLUÇÃO deixa a venda de pé, cancelar o PEDIDO quer dizer "
            "que ela nunca aconteceu"
        )
    else:
        motivo = "não está no léxico de devolução"
    raise ValueError(
        f"linha {linha}: `devolvida` = {texto!r} {motivo}. A Carchuna não "
        "adivinha: diga como tratar esta categoria — no dashboard, o "
        "mapeador de colunas pergunta; na biblioteca, passe "
        f"`interpretacao_devolvida={{{normalizar_valor(texto)!r}: True/False}}`."
    )


def _campos_normalizados(linha: dict) -> dict:
    """Indexa a linha por nome de coluna normalizado (sem caixa nem acento).

    O cabeçalho chega como o lojista salvou — ``Data``, ``DATA``,
    ``Valor_Bruto`` — e o nome original é preservado para aparecer no
    mapeador e nas mensagens de erro. A busca por campo é que ignora
    caixa e acento.
    """
    return {_normalizar_nome(chave).strip(): valor for chave, valor in linha.items()}


def _linha_para_transacao(
    linha: dict, numero: int, interpretacao_devolvida: dict[str, bool] | None = None
) -> Transacao:
    linha = _campos_normalizados(linha)
    faltando = [c for c in COLUNAS_OBRIGATORIAS if linha.get(c) in (None, "")]
    if faltando:
        colunas = ", ".join(f"`{c}`" for c in faltando)
        plural = "estão vazias" if len(faltando) > 1 else "está vazia"
        raise ValueError(
            f"linha {numero}: {colunas} {plural} nesta linha. "
            "Preencha na planilha ou apague a linha inteira."
        )
    canal = str(linha["canal"]).strip().lower().replace(" ", "_")
    canal = "".join(
        c for c in unicodedata.normalize("NFKD", canal) if not unicodedata.combining(c)
    )
    comissao = linha.get("comissao_cobrada")
    devolucao_bruta = linha.get("devolvida", "")
    return Transacao(
        data=_data_br(linha["data"], numero),
        canal=canal,
        valor_bruto=_decimal_br(linha["valor_bruto"], "valor_bruto", numero),
        custo_produto=_decimal_br(linha["custo_produto"], "custo_produto", numero),
        frete_pago=_decimal_br(linha["frete_pago"], "frete_pago", numero),
        devolvida=_devolvida_de(devolucao_bruta, numero, interpretacao_devolvida),
        prazo_recebimento_dias=int(linha.get("prazo_recebimento_dias") or 0),
        comissao_cobrada=(
            _decimal_br(comissao, "comissao_cobrada", numero)
            if comissao not in (None, "")
            else None
        ),
        produto=(str(linha.get("produto") or "").strip() or None),
        # o valor ORIGINAL do arquivo fica preservado (linhagem/auditoria)
        devolucao_status=(
            None if eh_ausente(devolucao_bruta) else str(devolucao_bruta).strip()
        ),
    )


# Onde o lojista acha cada coluna no relatório que ele já tem.
#
# ATENÇÃO ao ler isto como fato: são PALPITES para ajudar a localizar a
# coluna, colhidos dos nomes que aparecem nos relatórios, e não uma
# transcrição conferida contra documentação oficial da Shopee ou do
# Mercado Livre — os painéis mudam os rótulos sem aviso. Por isso a frase
# diz "costuma se chamar", e o caminho garantido é sempre o mapeador de
# colunas do dashboard, onde o próprio lojista aponta o de-para.
_ONDE_ACHAR: dict[str, str] = {
    "data": (
        "a data da venda. No relatório da Shopee ela costuma se chamar "
        '"Data do pedido"; no do Mercado Livre, "Data da venda". Serve '
        "qualquer uma: dd/mm/aaaa ou aaaa-mm-dd, com ou sem hora."
    ),
    "canal": (
        "onde a venda aconteceu. Relatório de um canal só não traz essa "
        "coluna — e tudo bem: no mapeador do dashboard você fixa o canal "
        "do arquivo inteiro (shopee, mercado_livre, amazon, loja_propria "
        "ou fisico)."
    ),
    "valor_bruto": (
        "quanto o cliente pagou pelo produto, antes de qualquer desconto. "
        'No relatório da Shopee costuma se chamar "Valor total do pedido"; '
        'no do Mercado Livre, "Receita por produtos".'
    ),
    "custo_produto": (
        "quanto o produto custou para você (CMV). O marketplace não conhece "
        "esse número: ele não existe no painel da Shopee nem no do "
        "Mercado Livre. Ele vem do seu controle de estoque, do ERP ou da "
        "nota do fornecedor — sem ele não dá para calcular margem."
    ),
    "frete_pago": (
        "quanto do frete saiu do seu bolso. Na Shopee costuma aparecer "
        'como "Taxa de envio"; no Mercado Livre, "Custo do frete". Se o '
        "frete é sempre do comprador, fixe zero no mapeador."
    ),
}


class ColunasFaltando(ValueError):
    """O arquivo não tem alguma coluna obrigatória — erro do arquivo todo.

    Diferente de célula vazia numa linha (isso é ``LinhaRejeitada``): aqui
    a coluna não existe no cabeçalho, então não há o que importar.
    """


def _conferir_colunas(linhas: list[dict]) -> None:
    """Confere o cabeçalho antes de tentar linha por linha.

    Sem isto, um arquivo sem a coluna de valor produzia o mesmo erro em
    todas as 5.000 linhas, e nenhum deles dizia onde achar a coluna.
    """
    if not linhas:
        return
    presentes = {_normalizar_nome(c).strip() for linha in linhas for c in linha}
    faltando = [c for c in COLUNAS_OBRIGATORIAS if c not in presentes]
    if not faltando:
        return
    originais = list(dict.fromkeys(c for linha in linhas for c in linha if c))
    # Se a informação está no arquivo com outro nome, o palpite do mapeador
    # já sabe qual coluna é — dizer isso poupa o lojista de procurar.
    palpites = sugerir_mapeamento(originais)
    itens = []
    for campo in faltando:
        dica = f"  • `{campo}`: {_ONDE_ACHAR[campo]}"
        candidata = palpites.get(campo)
        if candidata:
            dica += f' No seu arquivo isso parece ser "{candidata}".'
        itens.append(dica)
    quantas = (
        "Faltou 1 coluna que a Carchuna precisa"
        if len(faltando) == 1
        else f"Faltaram {len(faltando)} colunas que a Carchuna precisa"
    )
    raise ColunasFaltando(
        f"{quantas} no seu arquivo:\n" + "\n".join(itens) + "\n\n"
        f"O que o seu arquivo tem: {', '.join(originais)}.\n"
        "Se a informação está aí com outro nome, use o mapeador de colunas "
        "do dashboard para apontar qual coluna é qual — não precisa mexer na "
        "planilha."
    )


@dataclass(frozen=True)
class LinhaRejeitada:
    """Uma linha que não virou venda — com o número e o motivo em PT-BR.

    ``numero`` é o número da linha no arquivo como o lojista o vê na
    planilha (o cabeçalho é a linha 1), para ele conseguir ir lá e olhar.
    """

    numero: int
    motivo: str
    conteudo: dict


@dataclass(frozen=True)
class ResultadoImportacao:
    """O que entrou, o que ficou de fora e por quê.

    Existe para que nenhuma linha suma em silêncio: um arquivo com 5.000
    vendas e 3 linhas estragadas importa as 4.997 e mostra as 3 — em vez
    de recusar o arquivo inteiro (o que era o comportamento antigo) ou,
    pior, descartar as 3 sem avisar.
    """

    transacoes: list[Transacao]
    rejeitadas: list[LinhaRejeitada]

    @property
    def total_lidas(self) -> int:
        """Linhas de dados lidas do arquivo (fora o cabeçalho)."""
        return len(self.transacoes) + len(self.rejeitadas)

    def resumo(self) -> str:
        """Uma frase para o lojista sobre o que aconteceu com o arquivo."""
        if not self.transacoes:
            return (
                f"Nenhuma venda pôde ser lida: as {self.total_lidas} linhas do "
                "arquivo foram recusadas. Veja o motivo de cada uma abaixo e "
                "corrija a planilha — normalmente é a coluna de valor ou a de "
                "data que veio em outro formato."
            )
        if not self.rejeitadas:
            return f"{len(self.transacoes)} vendas importadas, nenhuma linha de fora."
        return (
            f"{len(self.transacoes)} vendas importadas. "
            f"{len(self.rejeitadas)} de {self.total_lidas} linhas ficaram de fora "
            "e não entram em nenhum número deste relatório — a lista abaixo diz "
            "o número da linha na sua planilha e o motivo."
        )


# ---------------------------------------------------------------------------
# Política de leitura por caminho
# ---------------------------------------------------------------------------

# Ler um arquivo por CAMINHO é recurso de uso local, e a ajuda na tela já
# dizia isso desde sempre: "aponte para um arquivo no SEU computador
# (funciona com o app rodando localmente)". No dashboard público o campo
# não serve ao lojista — ele não tem arquivo no servidor — e serve muito
# bem a um visitante que queira ler o disco de lá.
#
# Desligado de fábrica, pelo mesmo motivo que a narrativa por LLM é: quem
# publica o dashboard não deve expor o disco do servidor sem ter pedido,
# do mesmo jeito que quem clona o repositório não deve gastar com API sem
# ter pedido.
#
# O interruptor mora aqui e não nos loaders de propósito.
# `carregar_com_relatorio("/caminho/x.csv")` continua sendo API legítima
# de biblioteca: quem escreve um script Python já tem o disco inteiro na
# mão, e recusar ali seria teatro. O que estava errado era o dashboard
# público oferecer essa API a um visitante anônimo — e é essa fronteira,
# a da aplicação, que esta função guarda.
CHAVE_LEITURA_POR_CAMINHO = "CARCHUNA_LER_CAMINHO"


def leitura_por_caminho_ligada() -> bool:
    """O operador autorizou ler arquivo por caminho nesta instância?"""
    return os.environ.get(CHAVE_LEITURA_POR_CAMINHO, "0") == "1"


def carregar_com_relatorio(
    source,
    name: str | None = None,
    interpretacao_devolvida: dict[str, bool] | None = None,
) -> ResultadoImportacao:
    """Importa o que der e explica o que não deu.

    É o caminho do dashboard: o lojista sobe o arquivo cru e vê o raio-X
    das linhas boas mais um relatório das linhas recusadas. Quem precisa
    de tudo-ou-nada usa ``carregar_transacoes``.

    ``interpretacao_devolvida`` é a decisão do lojista por categoria da
    coluna de devolução (valor normalizado → conta como devolvida?). Sem
    ela, um status ambíguo ("Em análise") não vira sim/não em silêncio:
    a linha entra na lista de recusadas com o motivo.
    """
    linhas = ler_linhas_brutas(source, name=name)
    _conferir_colunas(linhas)
    transacoes: list[Transacao] = []
    rejeitadas: list[LinhaRejeitada] = []
    for numero, linha in enumerate(linhas, 2):
        try:
            transacoes.append(
                _linha_para_transacao(linha, numero, interpretacao_devolvida)
            )
        except (ValueError, TypeError) as erro:
            rejeitadas.append(
                LinhaRejeitada(numero=numero, motivo=str(erro), conteudo=dict(linha))
            )
    return ResultadoImportacao(transacoes=transacoes, rejeitadas=rejeitadas)


def carregar_transacoes(
    source,
    name: str | None = None,
    interpretacao_devolvida: dict[str, bool] | None = None,
) -> list[Transacao]:
    """Importa transações de CSV, JSON ou Excel (.xlsx).

    O arquivo precisa das colunas ``data, canal, valor_bruto,
    custo_produto, frete_pago`` (e opcionalmente ``devolvida,
    prazo_recebimento_dias, comissao_cobrada``). CSV aceita separador
    ``,`` ou ``;`` e vírgula decimal brasileira. A coluna de devolução
    aceita booleano ("Sim"/"Não"/True/1) OU status categórico
    ("Solicitação aprovada"); ver ``tipos.interpretar_devolucao``.

    Parameters
    ----------
    source : str | Path | file-like
        Caminho ou buffer do arquivo (ex.: upload do Streamlit).
    name : str | None
        Nome do arquivo, para detectar a extensão quando ``source`` é um
        buffer. ``None`` usa ``source.name``.
    interpretacao_devolvida : dict[str, bool] | None
        Decisão do usuário por categoria da coluna de devolução (chave
        normalizada → conta como devolvida?). Necessária quando o
        arquivo traz status indefinidos ("Em análise") ou fora do léxico
        — a Carchuna não decide sozinha.
    """
    linhas = ler_linhas_brutas(source, name=name)
    _conferir_colunas(linhas)
    transacoes = [
        _linha_para_transacao(linha, i, interpretacao_devolvida)
        for i, linha in enumerate(linhas, 2)
    ]
    if not transacoes:
        raise ValueError("Arquivo sem nenhuma transação válida.")
    return transacoes


def ler_linhas_brutas(source, name: str | None = None) -> list[dict]:
    """Lê o arquivo como linhas cruas (chaves = cabeçalho em minúsculas).

    É a matéria-prima do mapeador de colunas do dashboard: quando o
    arquivo vem com os nomes do relatório do marketplace, o usuário
    aponta qual coluna é qual e ``transacoes_de_mapa`` faz o resto.
    """
    filename = (name or getattr(source, "name", str(source))).lower()
    extensao = filename.rsplit(".", 1)[-1]
    if extensao in ("csv", "tsv", "json", "xlsx", "pdf"):
        _conferir_assinatura(source, extensao)
    if extensao in ("csv", "tsv"):
        return _ler_csv(source)
    if extensao == "json":
        return _ler_json(source)
    if extensao == "xlsx":
        return _ler_xlsx(source)
    if extensao == "pdf":
        return _ler_pdf(source)
    raise ValueError(
        f"Formato não suportado: .{extensao} (aceitos: csv, tsv, json, xlsx, pdf)."
    )


# Palpites do mapeador: por campo da Carchuna, termos que costumam aparecer
# nos cabeçalhos dos relatórios reais (Shopee, Mercado Livre, Amazon, ERPs).
#
# Termos compostos existem para desempatar coluna que casa com dois campos:
# "Custo do envio" tem "custo" (que puxaria para o CMV) e "envio" (que puxa
# para o frete) — quem ganha é o termo MAIS LONGO que casou, e "custo do
# envio" é mais específico que "custo". Mesma história entre "Receita por
# produtos" (dinheiro) e "Título do anúncio" (produto).
_PALPITES_MAPEAMENTO: dict[str, tuple[str, ...]] = {
    "data": ("data", "date", "dia", "data do pedido", "data da venda"),
    "produto": (
        "produto",
        "item",
        "titulo",
        "sku",
        "anuncio",
        "product",
        "nome do produto",
        "titulo do anuncio",
    ),
    "canal": ("canal", "channel", "marketplace", "origem", "loja"),
    "valor_bruto": (
        "valor_bruto",
        "preco",
        "valor",
        "price",
        "total",
        "bruto",
        "receita",
        "preco acordado",
        "receita por produtos",
        "valor total do pedido",
    ),
    "custo_produto": ("custo", "cost", "cmv", "custo do produto", "custo unitario"),
    "frete_pago": (
        "frete",
        "shipping",
        "envio",
        "custo do envio",
        "custo do frete",
        "taxa de envio",
        "valor do frete",
    ),
    "devolvida": ("devolvid", "devolu", "cancelad", "returned", "estorn"),
    "prazo_recebimento_dias": ("prazo", "recebimento", "repasse"),
    "comissao_cobrada": (
        "comissao",
        "tarifa",
        "commission",
        "fee",
        "tarifa de venda",
    ),
}

# Casar com o nome do campo em cheio vale mais que qualquer termo composto.
_PESO_NOME_EXATO = 1000


def _normalizar_nome(coluna: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(coluna).lower())
    return "".join(c for c in sem_acento if not unicodedata.combining(c))


def _forca_do_palpite(campo: str, coluna_normalizada: str) -> int:
    """O quanto uma coluna do arquivo puxa para um campo da Carchuna.

    Nome do campo em cheio vale ``_PESO_NOME_EXATO``; fora isso, vale o
    comprimento do termo mais longo que casou — quanto mais específico o
    termo, mais forte o palpite.
    """
    if coluna_normalizada == campo:
        return _PESO_NOME_EXATO
    casados = [t for t in _PALPITES_MAPEAMENTO[campo] if t in coluna_normalizada]
    return max((len(t) for t in casados), default=0)


def sugerir_mapeamento(colunas: list[str]) -> dict[str, str | None]:
    """Sugere, por palpite, qual coluna do arquivo é qual campo da Carchuna.

    Todos os pares (campo, coluna) são pontuados e os mais fortes ficam
    com a vaga primeiro, de modo que uma coluna ambígua vá para o campo
    que a reconhece melhor: no relatório do Mercado Livre, "Custo do
    envio (BRL)" fica com o frete (termo "custo do envio") e não com o
    CMV (termo "custo"). Cada coluna é usada uma vez só, e campo sem
    nenhum palpite fica ``None`` — quem decide é o usuário no mapeador.
    """
    normalizadas = {c: _normalizar_nome(c).strip() for c in colunas}
    ordem_dos_campos = list(_PALPITES_MAPEAMENTO)
    candidatos = [
        (forca, -ordem_dos_campos.index(campo), campo, coluna)
        for campo in ordem_dos_campos
        for coluna, norma in normalizadas.items()
        if (forca := _forca_do_palpite(campo, norma)) > 0
    ]
    candidatos.sort(reverse=True)

    mapa: dict[str, str | None] = dict.fromkeys(ordem_dos_campos)
    usadas: set[str] = set()
    for _forca, _ordem, campo, coluna in candidatos:
        if mapa[campo] is None and coluna not in usadas:
            mapa[campo] = coluna
            usadas.add(coluna)
    return mapa


def _aplicar_mapa(linha: dict, mapa: dict[str, str]) -> dict:
    """Traduz uma linha crua para os campos da Carchuna.

    Valor iniciado em ``=`` é constante do arquivo inteiro (ex.:
    ``{"canal": "=shopee"}`` quando o relatório todo veio da Shopee).
    """
    convertida: dict = {}
    for campo, origem in mapa.items():
        if not origem:
            continue
        convertida[campo] = origem[1:] if origem.startswith("=") else linha.get(origem)
    return convertida


def relatorio_de_mapa(
    linhas: list[dict],
    mapa: dict[str, str],
    interpretacao_devolvida: dict[str, bool] | None = None,
) -> ResultadoImportacao:
    """Como ``transacoes_de_mapa``, mas importando o que der.

    É o caminho do mapeador no dashboard: o relatório do marketplace
    quase sempre tem alguma linha estragada (pedido sem data, valor
    escrito por extenso), e recusar o arquivo inteiro por causa dela
    seria o mesmo erro que o importador cometia antes. Um status de
    devolução ambíguo entra aqui pela mesma porta: vira linha recusada
    com o motivo, não exceção que estoura o arquivo.
    """
    transacoes: list[Transacao] = []
    rejeitadas: list[LinhaRejeitada] = []
    for numero, linha in enumerate(linhas, 2):
        try:
            transacoes.append(
                _linha_para_transacao(
                    _aplicar_mapa(linha, mapa), numero, interpretacao_devolvida
                )
            )
        except (ValueError, TypeError) as erro:
            rejeitadas.append(
                LinhaRejeitada(numero=numero, motivo=str(erro), conteudo=dict(linha))
            )
    return ResultadoImportacao(transacoes=transacoes, rejeitadas=rejeitadas)


def transacoes_de_mapa(
    linhas: list[dict],
    mapa: dict[str, str],
    interpretacao_devolvida: dict[str, bool] | None = None,
) -> list[Transacao]:
    """Converte linhas cruas em transações usando o de-para do usuário.

    ``mapa`` liga cada campo da Carchuna a uma coluna do arquivo; valores
    iniciados em ``=`` são constantes para o arquivo inteiro (ex.:
    ``{"canal": "=shopee"}`` quando o relatório todo veio da Shopee, ou
    ``{"frete_pago": "=0"}`` quando o arquivo não traz frete).
    ``interpretacao_devolvida`` é a decisão do usuário por categoria da
    coluna de devolução (chave normalizada → conta como devolvida?) —
    obrigatória quando há status indefinidos ("Em análise").

    Tudo-ou-nada: a primeira linha ruim derruba o lote. Para importar o
    que der e listar as recusadas, use ``relatorio_de_mapa``.
    """
    transacoes = [
        _linha_para_transacao(
            _aplicar_mapa(linha, mapa), numero, interpretacao_devolvida
        )
        for numero, linha in enumerate(linhas, 2)
    ]
    if not transacoes:
        raise ValueError("Arquivo sem nenhuma transação válida.")
    return transacoes


# Ordem de tentativa de decodificação. `utf-8-sig` primeiro (e trata o BOM);
# `cp1252` cobre o Excel em português, que é o que a maioria dos lojistas usa
# para abrir e salvar o relatório do marketplace; `latin-1` fecha a conta
# porque decodifica qualquer byte — assim nenhum arquivo morre com
# `UnicodeDecodeError`, que não é mensagem para lojista.
_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def _decodificar(conteudo: bytes) -> str:
    for encoding in _ENCODINGS:
        try:
            return conteudo.decode(encoding)
        except UnicodeDecodeError:
            continue
    # latin-1 nunca falha; este retorno só existe para o caso de a lista mudar.
    return conteudo.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# Tetos de ingestão
#
# A Carchuna parseia arquivo de origem desconhecida num processo que
# atende todos os visitantes ao mesmo tempo. Sem teto, o custo do ataque
# é um arquivo pequeno e o custo da defesa é o processo inteiro.
#
# Cada número abaixo é folgado sobre o uso real e apertado sobre o abuso.
# O lojista típico deste estudo faz ~1.000 lançamentos/mês.
# ---------------------------------------------------------------------------

# ~40 anos de vendas do lojista típico. Passa disso e não é planilha de
# PME: é despejo, ou uma coluna que virou linha na exportação.
MAX_LINHAS_ARQUIVO = 500_000

# Relatório de marketplace não passa de algumas dezenas de páginas, e
# `extract_tables()` custa caro por página: um PDF pequeno e denso é o
# jeito mais barato de queimar CPU alheia.
MAX_PAGINAS_PDF = 200

# O formato de transações tem profundidade 2 (lista de objetos). Vinte é
# generoso e ainda muito abaixo do limite de recursão do interpretador —
# que é o ponto: `json.load` estoura com `RecursionError`, que não é
# `ValueError` nem `TypeError` e portanto não é contido por nenhum
# `except` deste projeto.
MAX_PROFUNDIDADE_JSON = 20

# Zip bomb: um `.xlsx` é um zip, e o cabeçalho do zip declara o tamanho
# descomprimido de cada parte. Dá para conferir antes de expandir, com a
# stdlib. Planilha real comprime de 10x a 20x; 100x já é assinatura de
# arquivo montado para expandir, não para ser lido.
MAX_RAZAO_COMPRESSAO_XLSX = 100
MAX_BYTES_DESCOMPRIMIDOS_XLSX = 500 * 1024 * 1024


def _conferir_zip_bomb(source) -> None:
    """Recusa o `.xlsx` que expande demais — **antes** de expandir.

    O tamanho descomprimido está no cabeçalho do zip, então esta conta
    não paga o custo que ela evita. Um arquivo de 199 KB que declara 210
    MB é recusado sem que um byte seja descomprimido.
    """
    import zipfile

    posicao = source.tell() if hasattr(source, "tell") else None
    try:
        with zipfile.ZipFile(source) as pacote:
            comprimido = sum(i.compress_size for i in pacote.infolist()) or 1
            descomprimido = sum(i.file_size for i in pacote.infolist())
    except zipfile.BadZipFile:
        raise ValueError(
            "Este arquivo tem extensão .xlsx mas não é uma planilha do "
            "Excel. Confira se ele não foi renomeado, e exporte de novo "
            "pelo painel do canal."
        ) from None
    finally:
        if posicao is not None:
            source.seek(posicao)

    razao = descomprimido / comprimido
    if (
        descomprimido > MAX_BYTES_DESCOMPRIMIDOS_XLSX
        or razao > MAX_RAZAO_COMPRESSAO_XLSX
    ):
        raise ValueError(
            "Esta planilha expande para um tamanho que a Carchuna não "
            "processa. Se ela é uma planilha de vendas de verdade, exporte "
            "de novo pelo painel do canal ou salve como CSV."
        )


def _conferir_profundidade_json(texto: str) -> None:
    """Conta aninhamento no texto, sem construir o objeto.

    `json.load` de um documento muito aninhado levanta `RecursionError`,
    que herda de `RuntimeError` — nenhum dos `except (ValueError,
    TypeError)` do projeto o captura, e a aplicação cai. Contar colchete
    antes de parsear resolve sem pagar o parse.
    """
    profundidade = maxima = 0
    dentro_de_texto = escapado = False
    for caractere in texto:
        if dentro_de_texto:
            if escapado:
                escapado = False
            elif caractere == "\\":
                escapado = True
            elif caractere == '"':
                dentro_de_texto = False
            continue
        if caractere == '"':
            dentro_de_texto = True
        elif caractere in "[{":
            profundidade += 1
            maxima = max(maxima, profundidade)
            if maxima > MAX_PROFUNDIDADE_JSON:
                raise ValueError(
                    "Este JSON tem estrutura aninhada demais para ser uma "
                    f"lista de vendas (o limite é {MAX_PROFUNDIDADE_JSON} "
                    "níveis). A Carchuna espera uma lista de objetos, um "
                    "por venda."
                )
        elif caractere in "]}":
            profundidade -= 1


def _conferir_quantidade_de_linhas(quantas: int) -> None:
    if quantas > MAX_LINHAS_ARQUIVO:
        raise ValueError(
            f"Este arquivo tem {quantas} linhas, e a Carchuna processa até "
            f"{MAX_LINHAS_ARQUIVO} de uma vez. Divida o período em arquivos "
            "menores — por ano, por exemplo."
        )


# Assinaturas de formato. Um arquivo binário se identifica nos primeiros
# bytes, e o nome dele não identifica nada: quem envia escolhe a
# extensão. Sem esta conferência, um `.csv` que é zip chegava no leitor
# de texto e um `.xlsx` que é texto chegava no openpyxl — cada um
# levantando o erro do parser errado, e o de zip antes de qualquer teto.
_ASSINATURAS: dict[str, tuple[bytes, ...]] = {
    "xlsx": (b"PK\x03\x04",),  # todo .xlsx é um zip
    "pdf": (b"%PDF-",),
}

# Formatos de texto não têm assinatura própria, mas têm o contrário:
# nenhum arquivo de texto começa com o cabeçalho de um binário. Um
# `.csv` que abre com `PK` foi renomeado.
_ASSINATURAS_BINARIAS = (b"PK\x03\x04", b"%PDF-", b"\x7fELF", b"\x89PNG")


def _primeiros_bytes(source, quantos: int = 8) -> bytes:
    """Espia o começo do arquivo sem consumir o buffer de quem vem depois."""
    if hasattr(source, "read"):
        posicao = source.tell() if hasattr(source, "tell") else None
        inicio = source.read(quantos)
        if posicao is not None:
            source.seek(posicao)
        return inicio if isinstance(inicio, bytes) else str(inicio).encode()
    with open(source, "rb") as arquivo:
        return arquivo.read(quantos)


def _conferir_assinatura(source, extensao: str) -> None:
    """A extensão promete um formato; os bytes confirmam ou desmentem.

    Recusa nos dois sentidos, e o segundo é o que importa para quem
    ataca: extensão de texto com conteúdo binário manda um zip para o
    leitor de CSV, que é o caminho onde nenhum teto de expansão existe.
    """
    inicio = _primeiros_bytes(source)
    esperadas = _ASSINATURAS.get(extensao)
    if esperadas is not None:
        if not any(inicio.startswith(a) for a in esperadas):
            raise ValueError(
                f"Este arquivo tem extensão .{extensao} mas o conteúdo não é "
                f"de um .{extensao}. Confira se ele não foi renomeado, e "
                "exporte de novo pelo painel do canal."
            )
        return
    if any(inicio.startswith(a) for a in _ASSINATURAS_BINARIAS):
        raise ValueError(
            f"Este arquivo tem extensão .{extensao}, que a Carchuna lê como "
            "texto, mas o conteúdo é de um arquivo binário. Renomear a "
            "extensão não converte o formato — exporte de novo no formato "
            "que você quer usar."
        )


def _abrir_texto(source):
    if hasattr(source, "read"):
        conteudo = source.read()
        if isinstance(conteudo, bytes):
            conteudo = _decodificar(conteudo)
        return io.StringIO(conteudo)
    return io.StringIO(_decodificar(Path(source).read_bytes()))


_SEPARADORES = (";", ",", "\t", "|")

# Quantas linhas do começo do arquivo podem ser título/período antes da tabela.
_MAX_LINHAS_DE_TITULO = 30

# Uma linha só é cabeçalho se reconhecermos pelo menos duas colunas nela.
# Uma só não basta: "lançamento;histórico;valor" de um extrato bancário
# casaria com o palpite "valor" e sequestraria o arquivo inteiro.
_MIN_COLUNAS_RECONHECIDAS = 2


def _colunas_reconhecidas(celulas: list[str]) -> int:
    """Quantas células parecem nome de coluna que a Carchuna sabe usar."""
    total = 0
    for celula in celulas:
        norma = _normalizar_nome(celula).strip()
        if not norma:
            continue
        if norma in COLUNAS_OBRIGATORIAS or norma in COLUNAS_OPCIONAIS:
            total += 1
            continue
        if any(
            termo in norma
            for termos in _PALPITES_MAPEAMENTO.values()
            for termo in termos
        ):
            total += 1
    return total


_SEM_CABECALHO = (
    "Não encontrei o cabeçalho da tabela neste arquivo. A Carchuna "
    "procura uma linha com os nomes das colunas (data, canal, "
    "valor_bruto, custo_produto, frete_pago) ou os nomes do relatório "
    "do marketplace (ex.: 'Data do pedido', 'Preço', 'Tarifa de "
    "venda'). Confira se você exportou o relatório de VENDAS — um "
    "extrato bancário ou um resumo financeiro não tem essas colunas."
)


def _achar_cabecalho(linhas: list[str]) -> tuple[int, str]:
    """Descobre em que linha começa a tabela e qual é o separador.

    Relatório de marketplace quase nunca começa na tabela: vem título,
    período, linha em branco e só então o cabeçalho. E a linha de título
    costuma ter vírgulas, então detectar o separador nela escolhe o
    separador errado. Testamos cada linha contra cada separador e ficamos
    com a combinação que reconhece mais colunas.
    """
    melhor = (0, 0, 0, ",")  # (colunas reconhecidas, nº de células, índice, separador)
    for indice, linha in enumerate(linhas[:_MAX_LINHAS_DE_TITULO]):
        if not linha.strip():
            continue
        for separador in _SEPARADORES:
            celulas = next(csv.reader([linha], delimiter=separador), [])
            if len(celulas) < 2:
                continue
            reconhecidas = _colunas_reconhecidas(celulas)
            # mais colunas reconhecidas vence; empate, mais células; depois,
            # a linha mais acima (por isso o índice entra negativo)
            candidato = (reconhecidas, len(celulas), -indice, separador)
            if candidato[:3] > melhor[:3]:
                melhor = candidato
    if melhor[0] < _MIN_COLUNAS_RECONHECIDAS:
        raise ValueError(_SEM_CABECALHO)
    return -melhor[2], melhor[3]


def _achar_cabecalho_em_celulas(linhas: list[list[str]]) -> int:
    """A mesma busca do CSV, para quem já chega em células.

    A planilha não precisa de separador — o Excel já separou —, mas
    precisa da busca: o relatório que o lojista exporta traz título,
    loja e período antes da tabela, e ele é o MESMO relatório salvo em
    outro formato. Assumir a linha 1 recusava em .xlsx o arquivo que a
    Carchuna aceitava em .csv.
    """
    melhor = (0, 0, 0)  # (colunas reconhecidas, nº de células, -índice)
    for indice, celulas in enumerate(linhas[:_MAX_LINHAS_DE_TITULO]):
        if not any(c.strip() for c in celulas):
            continue
        candidato = (_colunas_reconhecidas(celulas), len(celulas), -indice)
        if candidato > melhor:
            melhor = candidato
    if melhor[0] < _MIN_COLUNAS_RECONHECIDAS:
        raise ValueError(_SEM_CABECALHO)
    return -melhor[2]


def _ler_csv(source) -> list[dict]:
    texto = _abrir_texto(source).read()
    linhas = texto.splitlines()
    _conferir_quantidade_de_linhas(len(linhas))
    inicio, separador = _achar_cabecalho(linhas)
    leitor = csv.DictReader(
        io.StringIO("\n".join(linhas[inicio:])), delimiter=separador
    )
    return [{(k or "").strip(): v for k, v in linha.items()} for linha in leitor]


def _ler_json(source) -> list[dict]:
    texto = _abrir_texto(source).read()
    _conferir_profundidade_json(texto)
    # parse_float=str preserva os números como texto: dinheiro nunca vira float.
    dados = json.loads(texto, parse_float=str, parse_int=str)
    if not isinstance(dados, list):
        raise ValueError("JSON deve ser uma lista de objetos de transação.")
    _conferir_quantidade_de_linhas(len(dados))
    return [{str(k).strip(): v for k, v in item.items()} for item in dados]


_CENTAVO = Decimal("0.01")


def _celula_de_planilha(valor) -> str:
    """Converte uma célula do Excel em texto sem carregar erro de float.

    O openpyxl entrega célula numérica como ``float``, e ``str()`` sozinho
    não desfaz o erro de ponto flutuante: congela ele num texto que passa
    por baixo da guarda que rejeita ``float`` no motor. ``0,1 + 0,2``
    chega como ``"0.30000000000000004"`` e vira ``Decimal`` com o rastro
    junto. A fronteira é o último lugar onde dá para cortar esse rastro,
    então todo ``float`` é quantizado a centavos com ``ROUND_HALF_UP`` — o
    arredondamento da prática comercial.

    O ``str(valor)`` de dentro do ``Decimal`` é proposital: ele devolve o
    número curto que o lojista vê na tela (``1234.565``), não a expansão
    binária que está logo abaixo (``1234.5649999...``). Quantizar a partir
    do que ele vê é o que faz meio centavo subir, como ele espera.

    Inteiro não é dinheiro: prazo de 30 dias não vira ``"30,00"``. Texto e
    data seguem intactos.
    """
    if valor is None:
        return ""
    if isinstance(valor, float):
        if not math.isfinite(valor):
            # `str(nan)` é "nan", e `Decimal("nan")` NÃO estoura: cria um NaN
            # que contamina a soma inteira em silêncio (NaN + 10 = NaN).
            # O marcador não vira Decimal nenhum, então a linha é recusada
            # com nome de coluna e número — e as outras entram normalmente.
            return "#ERRO"
        return str(Decimal(str(valor)).quantize(_CENTAVO, rounding=ROUND_HALF_UP))
    return str(valor)


def _ler_xlsx(source) -> list[dict]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ImportError(
            "Importar .xlsx requer `openpyxl` (pip install openpyxl) — "
            "ou exporte a planilha como CSV."
        ) from None
    _conferir_zip_bomb(source)
    try:
        planilha = load_workbook(source, read_only=True, data_only=True).active
    except OSError:
        # openpyxl levanta OSError para pacote corrompido, e OSError não é
        # ValueError nem TypeError: subiria por fora de todo `except` do
        # projeto e derrubaria a tela em vez de recusar o arquivo.
        raise ValueError(
            "Não consegui abrir esta planilha: o arquivo parece corrompido "
            "ou incompleto. Exporte de novo pelo painel do canal."
        ) from None
    linhas = []
    for linha in planilha.iter_rows(values_only=True):
        linhas.append([_celula_de_planilha(c) for c in linha])
        _conferir_quantidade_de_linhas(len(linhas))
    if not any(any(c.strip() for c in linha) for linha in linhas):
        raise ValueError(
            "Esta planilha não tem nenhuma linha preenchida. A Carchuna lê a "
            "primeira aba do arquivo — confira se as vendas não ficaram em "
            "outra aba, ou exporte de novo."
        )
    inicio = _achar_cabecalho_em_celulas(linhas)
    cabecalho = [c.strip() for c in linhas[inicio]]
    return [
        dict(zip(cabecalho, linha, strict=False))
        for linha in linhas[inicio + 1 :]
        if any(c.strip() for c in linha)
    ]


def _ler_pdf(source) -> list[dict]:
    """Extrai vendas de um PDF que contenha uma TABELA com as colunas do modelo.

    Suporte beta e honesto: PDF não é um formato de dados — cada relatório
    tem um layout. Funciona quando o PDF traz uma tabela (com linhas de
    grade) cujo cabeçalho usa os mesmos nomes de coluna do modelo da
    Carchuna (``data, canal, valor_bruto...``). Para qualquer outro
    layout, exporte como CSV/Excel — todo painel de marketplace oferece.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "Importar .pdf requer `pdfplumber` (pip install pdfplumber) — "
            "ou exporte o relatório como CSV/Excel."
        ) from None
    linhas: list[dict] = []
    cabecalho: list[str] | None = None
    with pdfplumber.open(source) as pdf:
        if len(pdf.pages) > MAX_PAGINAS_PDF:
            raise ValueError(
                f"Este PDF tem {len(pdf.pages)} páginas, e a Carchuna lê até "
                f"{MAX_PAGINAS_PDF}. Extrair tabela de PDF é caro por "
                "página — exporte o relatório como CSV ou Excel, que todo "
                "painel de marketplace oferece."
            )
        for pagina in pdf.pages:
            for tabela in pagina.extract_tables():
                for bruta in tabela:
                    celulas = [str(c or "").strip() for c in bruta]
                    normalizadas = [c.lower() for c in celulas]
                    if "data" in normalizadas and "canal" in normalizadas:
                        cabecalho = normalizadas
                        continue
                    if cabecalho and any(celulas):
                        linhas.append(dict(zip(cabecalho, celulas, strict=False)))
    if cabecalho is None:
        raise ValueError(
            "Não encontrei no PDF uma tabela com as colunas do modelo "
            "(data, canal, valor_bruto...). Exporte o relatório como "
            "CSV/Excel ou use a planilha modelo do tutorial."
        )
    return linhas


# ---------------------------------------------------------------------------
# Dados sintéticos (demo/testes offline)
# ---------------------------------------------------------------------------

# Nomes de produto derivados da faixa de preço, SEM sorteios extras: a
# sequência aleatória (e portanto todos os números do demo) fica idêntica
# à das versões anteriores.
_PRODUTOS_POR_FAIXA = (
    (Decimal("200"), "Capa de celular"),
    (Decimal("280"), "Carregador turbo"),
    (Decimal("360"), "Fone bluetooth"),
    (Decimal("440"), "Caixa de som"),
    (Decimal("551"), "Smartwatch"),
)


def _produto_por_faixa(valor: Decimal) -> str:
    for limite, nome in _PRODUTOS_POR_FAIXA:
        if valor < limite:
            return nome
    return _PRODUTOS_POR_FAIXA[-1][1]


# Perfil do lojista-alvo: fatura ~R$400 mil/mês, margem apertada.
_PERFIL_CANAIS = (
    ("mercado_livre", 45, 30),  # (canal, % das vendas, prazo típico em dias)
    ("shopee", 25, 15),
    ("amazon", 10, 14),
    ("loja_propria", 12, 30),
    ("fisico", 8, 0),
)


def transacoes_sinteticas(
    meses: int = 6,
    fim: date | None = None,
    seed: int = 7,
) -> list[Transacao]:
    """Gera vendas sintéticas reprodutíveis de um lojista típico.

    ~R$60 mil/mês distribuídos nos cinco canais, com CMV em torno de
    55–65% do preço, frete, ~3% de devoluções e prazos de recebimento
    realistas. Mesma ``seed`` → mesmas transações, sempre.

    **A escala é a do público-alvo, e isso é decisão de produto.** Antes
    a demo faturava ~R$400 mil/mês — R$ 4,8 milhões ao ano, topo do EPP e
    acima do sublimite de ICMS/ISS. Quem abria o dashboard público via a
    margem de uma empresa que não é a dele, com um aviso de que a conta
    estava incompleta. A Carchuna é para MEI e ME de marketplace; a demo
    passou a mostrar uma.
    """
    if meses < 1:
        raise ValueError(f"`meses` deve ser >= 1, recebeu {meses}.")
    rng = random.Random(seed)
    fim = fim or date(2026, 6, 30)
    transacoes: list[Transacao] = []
    inicio = (fim.replace(day=1) - timedelta(days=meses * 31 - 15)).replace(day=1)

    dia = inicio
    while dia <= fim:
        for canal, share, prazo in _PERFIL_CANAIS:
            # nº de vendas do canal no dia calibrado para ~R$60k/mês no total
            n_vendas = max(0, round(rng.gauss(4.5 * share / 100, 1)))
            for _ in range(n_vendas):
                valor = Decimal(rng.randint(120, 550))
                custo = (valor * Decimal(rng.randint(55, 65)) / 100).quantize(
                    Decimal("0.01")
                )
                transacoes.append(
                    Transacao(
                        data=dia,
                        canal=canal,
                        valor_bruto=valor,
                        custo_produto=custo,
                        frete_pago=Decimal(rng.randint(8, 25)),
                        devolvida=rng.random() < 0.03,
                        prazo_recebimento_dias=prazo,
                        produto=_produto_por_faixa(valor),
                    )
                )
        dia += timedelta(days=1)
    return transacoes
