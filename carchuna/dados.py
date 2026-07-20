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
from datetime import date, timedelta
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


def _decimal_br(texto: str, campo: str, linha: int) -> Decimal:
    """Converte '1.234,56' ou '1234.56' em Decimal, sem passar por float."""
    limpo = str(texto).strip().replace("R$", "").replace(" ", "")
    if "," in limpo:  # formato brasileiro: ponto de milhar, vírgula decimal
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except InvalidOperation:
        raise ValueError(
            f"linha {linha}: `{campo}` = {texto!r} não é um valor monetário válido."
        ) from None


def _bool_br(texto: str, linha: int) -> bool:
    normal = str(texto).strip().lower()
    if normal in _VERDADEIRO:
        return True
    if normal in _FALSO:
        return False
    raise ValueError(f"linha {linha}: `devolvida` = {texto!r} não é sim/não.")


def _linha_para_transacao(linha: dict, numero: int) -> Transacao:
    faltando = [c for c in COLUNAS_OBRIGATORIAS if linha.get(c) in (None, "")]
    if faltando:
        raise ValueError(f"linha {numero}: colunas obrigatórias vazias: {faltando}.")
    canal = str(linha["canal"]).strip().lower().replace(" ", "_")
    canal = "".join(
        c for c in unicodedata.normalize("NFKD", canal) if not unicodedata.combining(c)
    )
    comissao = linha.get("comissao_cobrada")
    return Transacao(
        data=date.fromisoformat(str(linha["data"]).strip()[:10]),
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
    if extensao == "csv":
        return _ler_csv(source)
    if extensao == "json":
        return _ler_json(source)
    if extensao == "xlsx":
        return _ler_xlsx(source)
    if extensao == "pdf":
        return _ler_pdf(source)
    raise ValueError(
        f"Formato não suportado: .{extensao} (aceitos: csv, json, xlsx, pdf)."
    )


# Palpites do mapeador: por campo da Carchuna, termos que costumam aparecer
# nos cabeçalhos dos relatórios reais (Shopee, Mercado Livre, Amazon, ERPs).
_PALPITES_MAPEAMENTO: dict[str, tuple[str, ...]] = {
    "data": ("data", "date", "dia"),
    "produto": ("produto", "item", "titulo", "sku", "anuncio", "product"),
    "canal": ("canal", "channel", "marketplace", "origem", "loja"),
    "valor_bruto": ("valor_bruto", "preco", "valor", "price", "total", "bruto"),
    "custo_produto": ("custo", "cost", "cmv"),
    "frete_pago": ("frete", "shipping", "envio"),
    "devolvida": ("devolvid", "devolu", "cancelad", "returned", "estorn"),
    "prazo_recebimento_dias": ("prazo", "recebimento", "repasse"),
    "comissao_cobrada": ("comissao", "tarifa", "commission", "fee"),
}


def _normalizar_nome(coluna: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(coluna).lower())
    return "".join(c for c in sem_acento if not unicodedata.combining(c))


def sugerir_mapeamento(colunas: list[str]) -> dict[str, str | None]:
    """Sugere, por palpite, qual coluna do arquivo é qual campo da Carchuna.

    Match exato primeiro, depois por conter o termo; cada coluna do
    arquivo só é usada uma vez. Campos sem palpite ficam ``None`` — o
    usuário decide no mapeador.
    """
    normalizadas = {c: _normalizar_nome(c) for c in colunas}
    usadas: set[str] = set()
    mapa: dict[str, str | None] = {}
    for campo, termos in _PALPITES_MAPEAMENTO.items():
        escolhida = None
        for coluna, norma in normalizadas.items():
            if coluna not in usadas and norma == campo:
                escolhida = coluna
                break
        if escolhida is None:
            for termo in termos:
                for coluna, norma in normalizadas.items():
                    if coluna not in usadas and termo in norma:
                        escolhida = coluna
                        break
                if escolhida:
                    break
        mapa[campo] = escolhida
        if escolhida:
            usadas.add(escolhida)
    return mapa


def transacoes_de_mapa(linhas: list[dict], mapa: dict[str, str]) -> list[Transacao]:
    """Converte linhas cruas em transações usando o de-para do usuário.

    ``mapa`` liga cada campo da Carchuna a uma coluna do arquivo; valores
    iniciados em ``=`` são constantes para o arquivo inteiro (ex.:
    ``{"canal": "=shopee"}`` quando o relatório todo veio da Shopee, ou
    ``{"frete_pago": "=0"}`` quando o arquivo não traz frete).
    """
    transacoes = []
    for numero, linha in enumerate(linhas, 2):
        convertida: dict = {}
        for campo, origem in mapa.items():
            if not origem:
                continue
            if origem.startswith("="):
                convertida[campo] = origem[1:]
            else:
                convertida[campo] = linha.get(origem)
        transacoes.append(_linha_para_transacao(convertida, numero))
    if not transacoes:
        raise ValueError("Arquivo sem nenhuma transação válida.")
    return transacoes


def _abrir_texto(source):
    if hasattr(source, "read"):
        conteudo = source.read()
        if isinstance(conteudo, bytes):
            conteudo = conteudo.decode("utf-8-sig")
        return io.StringIO(conteudo)
    return io.StringIO(Path(source).read_text(encoding="utf-8-sig"))


def _ler_csv(source) -> list[dict]:
    buffer = _abrir_texto(source)
    amostra = buffer.readline()
    buffer.seek(0)
    separador = ";" if amostra.count(";") > amostra.count(",") else ","
    leitor = csv.DictReader(buffer, delimiter=separador)
    return [
        {(k or "").strip().lower(): v for k, v in linha.items()} for linha in leitor
    ]


def _ler_json(source) -> list[dict]:
    buffer = _abrir_texto(source)
    # parse_float=str preserva os números como texto: dinheiro nunca vira float.
    dados = json.load(buffer, parse_float=str, parse_int=str)
    if not isinstance(dados, list):
        raise ValueError("JSON deve ser uma lista de objetos de transação.")
    return [{str(k).strip().lower(): v for k, v in item.items()} for item in dados]


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
    cabecalho = [str(c or "").strip().lower() for c in next(linhas_iter)]
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
