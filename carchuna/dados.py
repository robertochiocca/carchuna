"""Importação de vendas (CSV/Excel/JSON) e dados sintéticos para demo.

Adaptado do padrão de ``data.py`` da Calahonda: valida, limpa e — na
ausência de dados reais — gera um conjunto sintético reprodutível que
permite rodar todo o projeto offline.

Dinheiro entra como ``str`` e vira ``Decimal`` direto (nunca passa por
``float``); no JSON os números são lidos com ``parse_float=str`` pela
mesma razão. A única exceção é o Excel, em que a célula já chega como
``float`` do openpyxl — a conversão passa por ``str()`` e o caso está
documentado no README.
"""

from __future__ import annotations

import csv
import io
import json
import random
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from carchuna.margem import Transacao

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

_VERDADEIRO = {"1", "true", "sim", "s", "verdadeiro", "yes"}
_FALSO = {"", "0", "false", "nao", "não", "n", "falso", "no"}


def _para_decimal(texto: str) -> Decimal:
    """'R$ 1.234,56' ou '1234.56' → Decimal, sem nunca passar por float."""
    limpo = str(texto).strip().replace("R$", "").replace(" ", "")
    if "," in limpo:  # formato brasileiro: ponto de milhar, vírgula decimal
        limpo = limpo.replace(".", "").replace(",", ".")
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


def _decimal_br(texto: str, campo: str, linha: int) -> Decimal:
    """Como ``decimal_de_texto``, mas com o número da linha na mensagem."""
    try:
        return _para_decimal(texto)
    except InvalidOperation:
        raise ValueError(
            f"linha {linha}: `{campo}` = {texto!r} não é um valor monetário válido."
        ) from None


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


def _bool_br(texto: str, linha: int) -> bool:
    normal = str(texto).strip().lower()
    if normal in _VERDADEIRO:
        return True
    if normal in _FALSO:
        return False
    raise ValueError(f"linha {linha}: `devolvida` = {texto!r} não é sim/não.")


def _campos_normalizados(linha: dict) -> dict:
    """Indexa a linha por nome de coluna normalizado (sem caixa nem acento).

    O cabeçalho chega como o lojista salvou — ``Data``, ``DATA``,
    ``Valor_Bruto`` — e o nome original é preservado para aparecer no
    mapeador e nas mensagens de erro. A busca por campo é que ignora
    caixa e acento.
    """
    return {_normalizar_nome(chave).strip(): valor for chave, valor in linha.items()}


def _linha_para_transacao(linha: dict, numero: int) -> Transacao:
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
    return Transacao(
        data=_data_br(linha["data"], numero),
        canal=canal,
        valor_bruto=_decimal_br(linha["valor_bruto"], "valor_bruto", numero),
        custo_produto=_decimal_br(linha["custo_produto"], "custo_produto", numero),
        frete_pago=_decimal_br(linha["frete_pago"], "frete_pago", numero),
        devolvida=_bool_br(linha.get("devolvida", ""), numero),
        prazo_recebimento_dias=int(linha.get("prazo_recebimento_dias") or 0),
        comissao_cobrada=(
            _decimal_br(comissao, "comissao_cobrada", numero)
            if comissao not in (None, "")
            else None
        ),
        produto=(str(linha.get("produto") or "").strip() or None),
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


def carregar_com_relatorio(source, name: str | None = None) -> ResultadoImportacao:
    """Importa o que der e explica o que não deu.

    É o caminho do dashboard: o lojista sobe o arquivo cru e vê o raio-X
    das linhas boas mais um relatório das linhas recusadas. Quem precisa
    de tudo-ou-nada usa ``carregar_transacoes``.
    """
    linhas = ler_linhas_brutas(source, name=name)
    _conferir_colunas(linhas)
    transacoes: list[Transacao] = []
    rejeitadas: list[LinhaRejeitada] = []
    for numero, linha in enumerate(linhas, 2):
        try:
            transacoes.append(_linha_para_transacao(linha, numero))
        except (ValueError, TypeError) as erro:
            rejeitadas.append(
                LinhaRejeitada(numero=numero, motivo=str(erro), conteudo=dict(linha))
            )
    return ResultadoImportacao(transacoes=transacoes, rejeitadas=rejeitadas)


def carregar_transacoes(source, name: str | None = None) -> list[Transacao]:
    """Importa transações de CSV, JSON ou Excel (.xlsx).

    O arquivo precisa das colunas ``data, canal, valor_bruto,
    custo_produto, frete_pago`` (e opcionalmente ``devolvida,
    prazo_recebimento_dias, comissao_cobrada``). CSV aceita separador
    ``,`` ou ``;`` e vírgula decimal brasileira.

    Parameters
    ----------
    source : str | Path | file-like
        Caminho ou buffer do arquivo (ex.: upload do Streamlit).
    name : str | None
        Nome do arquivo, para detectar a extensão quando ``source`` é um
        buffer. ``None`` usa ``source.name``.
    """
    linhas = ler_linhas_brutas(source, name=name)
    _conferir_colunas(linhas)
    transacoes = [_linha_para_transacao(linha, i) for i, linha in enumerate(linhas, 2)]
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


def relatorio_de_mapa(linhas: list[dict], mapa: dict[str, str]) -> ResultadoImportacao:
    """Como ``transacoes_de_mapa``, mas importando o que der.

    É o caminho do mapeador no dashboard: o relatório do marketplace
    quase sempre tem alguma linha estragada (pedido sem data, valor
    escrito por extenso), e recusar o arquivo inteiro por causa dela
    seria o mesmo erro que o importador cometia antes.
    """
    transacoes: list[Transacao] = []
    rejeitadas: list[LinhaRejeitada] = []
    for numero, linha in enumerate(linhas, 2):
        try:
            transacoes.append(_linha_para_transacao(_aplicar_mapa(linha, mapa), numero))
        except (ValueError, TypeError) as erro:
            rejeitadas.append(
                LinhaRejeitada(numero=numero, motivo=str(erro), conteudo=dict(linha))
            )
    return ResultadoImportacao(transacoes=transacoes, rejeitadas=rejeitadas)


def transacoes_de_mapa(linhas: list[dict], mapa: dict[str, str]) -> list[Transacao]:
    """Converte linhas cruas em transações usando o de-para do usuário.

    ``mapa`` liga cada campo da Carchuna a uma coluna do arquivo; valores
    iniciados em ``=`` são constantes para o arquivo inteiro (ex.:
    ``{"canal": "=shopee"}`` quando o relatório todo veio da Shopee, ou
    ``{"frete_pago": "=0"}`` quando o arquivo não traz frete).

    Tudo-ou-nada: a primeira linha ruim derruba o lote. Para importar o
    que der e listar as recusadas, use ``relatorio_de_mapa``.
    """
    transacoes = [
        _linha_para_transacao(_aplicar_mapa(linha, mapa), numero)
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
        raise ValueError(
            "Não encontrei o cabeçalho da tabela neste arquivo. A Carchuna "
            "procura uma linha com os nomes das colunas (data, canal, "
            "valor_bruto, custo_produto, frete_pago) ou os nomes do relatório "
            "do marketplace (ex.: 'Data do pedido', 'Preço', 'Tarifa de "
            "venda'). Confira se você exportou o relatório de VENDAS — um "
            "extrato bancário ou um resumo financeiro não tem essas colunas."
        )
    return -melhor[2], melhor[3]


def _ler_csv(source) -> list[dict]:
    texto = _abrir_texto(source).read()
    linhas = texto.splitlines()
    inicio, separador = _achar_cabecalho(linhas)
    leitor = csv.DictReader(
        io.StringIO("\n".join(linhas[inicio:])), delimiter=separador
    )
    return [{(k or "").strip(): v for k, v in linha.items()} for linha in leitor]


def _ler_json(source) -> list[dict]:
    buffer = _abrir_texto(source)
    # parse_float=str preserva os números como texto: dinheiro nunca vira float.
    dados = json.load(buffer, parse_float=str, parse_int=str)
    if not isinstance(dados, list):
        raise ValueError("JSON deve ser uma lista de objetos de transação.")
    return [{str(k).strip(): v for k, v in item.items()} for item in dados]


def _ler_xlsx(source) -> list[dict]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ImportError(
            "Importar .xlsx requer `openpyxl` (pip install openpyxl) — "
            "ou exporte a planilha como CSV."
        ) from None
    planilha = load_workbook(source, read_only=True, data_only=True).active
    linhas_iter = planilha.iter_rows(values_only=True)
    cabecalho = [str(c or "").strip() for c in next(linhas_iter)]
    return [
        # células numéricas do Excel chegam como float; str() antes do Decimal
        dict(zip(cabecalho, ["" if v is None else str(v) for v in linha], strict=False))
        for linha in linhas_iter
        if any(v not in (None, "") for v in linha)
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

    ~R$400 mil/mês distribuídos nos cinco canais, com CMV em torno de
    55–65% do preço, frete, ~3% de devoluções e prazos de recebimento
    realistas. Mesma ``seed`` → mesmas transações, sempre.
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
            # nº de vendas do canal no dia calibrado para ~R$400k/mês no total
            n_vendas = max(0, round(rng.gauss(40 * share / 100, 4)))
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
