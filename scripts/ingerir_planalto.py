#!/usr/bin/env python3
"""Extrai artigos de uma lei do Planalto e gera esqueletos para o corpus PME.

O Planalto e o portal de normas da Receita respondem 503/403 a cliente que
não seja navegador — o WAF olha o User-Agent e o handshake TLS, e nenhum
cabeçalho forjado resolve com confiabilidade. Por isso o script aceita as
duas origens, e a segunda é a que sempre funciona:

    # a partir de um arquivo salvo ("Salvar página como…" no navegador)
    python scripts/ingerir_planalto.py \\
        --arquivo lcp123.html \\
        --lei "Lei Complementar nº 123/2006 (Estatuto da ME/EPP — Simples Nacional)" \\
        --prefixo lc123 --tema tributario --artigos 18 18-A > novos.json

    # direto da URL (quando o portal deixar)
    python scripts/ingerir_planalto.py \\
        --url https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm \\
        --lei "Lei Complementar nº 123/2006" --prefixo lc123 --tema tributario

Por padrão a saída vai para stdout, para você conferir antes de gravar.
Com ``--mesclar``, o resultado entra em ``data/corpus_pme.json`` sem tocar
em nenhum dispositivo já marcado ``revisado: true``.

Todo esqueleto sai com ``"revisado": false`` e resumo TODO. A conferência
na fonte oficial continua sendo sua — o script só evita a digitação.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from carchuna.rag.ingestao import (  # noqa: E402
    decodificar_html,
    gerar_esqueletos,
    mesclar_no_corpus,
)

CORPUS = RAIZ / "data" / "corpus_pme.json"

# Navegadores reais passam pelos WAFs; um User-Agent de script, não. Isto
# aumenta a chance de o --url funcionar, mas não é garantia: se vier 403 ou
# 503, salve a página e use --arquivo.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _carregar_html(args: argparse.Namespace) -> str:
    if args.arquivo:
        return decodificar_html(Path(args.arquivo).read_bytes())

    try:
        import httpx
    except ImportError:
        sys.exit(
            "httpx não está instalado. Instale com 'pip install httpx' ou "
            "salve a página no navegador e use --arquivo."
        )

    try:
        resp = httpx.get(
            args.url,
            timeout=60,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        sys.exit(
            f"O portal respondeu HTTP {exc.response.status_code}. É o WAF "
            f"bloqueando cliente que não é navegador — abra a página no "
            f"navegador, salve como HTML e rode de novo com --arquivo."
        )
    except httpx.HTTPError as exc:
        sys.exit(f"Falha de rede: {exc}. Alternativa: salve a página e use --arquivo.")

    return decodificar_html(resp.content, resp.encoding)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    origem = ap.add_mutually_exclusive_group(required=True)
    origem.add_argument("--url", help="URL da lei no Planalto")
    origem.add_argument("--arquivo", help="Arquivo HTML salvo do navegador")
    ap.add_argument("--lei", required=True, help="Nome oficial completo da lei")
    ap.add_argument(
        "--prefixo",
        help="Prefixo dos ids (ex.: lc123 → lc123-18a). Default: slug do nome da lei.",
    )
    ap.add_argument(
        "--tema", default="revisar", help="Tema do corpus (default: revisar)"
    )
    ap.add_argument(
        "--artigos",
        nargs="*",
        default=None,
        help="Números a extrair, incluindo sufixo (ex.: 18 18-A). Default: todos.",
    )
    ap.add_argument(
        "--mesclar",
        action="store_true",
        help="Grava em data/corpus_pme.json preservando os dispositivos revisados.",
    )
    args = ap.parse_args()

    html = _carregar_html(args)
    fonte = args.url or args.lei
    esqueletos = gerar_esqueletos(
        html,
        lei=args.lei,
        fonte=fonte,
        tema=args.tema,
        numeros=args.artigos,
        prefixo=args.prefixo,
    )

    if not esqueletos:
        sys.exit(
            "Nenhum artigo encontrado. Confira os números pedidos — e, se veio "
            "de --url, é possível que o portal tenha devolvido uma página de "
            "bloqueio em vez da lei. Salve no navegador e use --arquivo."
        )

    if not args.mesclar:
        json.dump(esqueletos, sys.stdout, ensure_ascii=False, indent=2)
        print(file=sys.stdout)
        return

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    resultado = mesclar_no_corpus(corpus, esqueletos)

    if resultado.adicionados or resultado.atualizados:
        CORPUS.write_text(
            json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    else:
        # Nada mudou: não reescrever evita um diff de reformatação no git.
        print("Nada a gravar — o corpus não mudou.", file=sys.stderr)

    print(
        f"{len(resultado.adicionados)} adicionado(s), "
        f"{len(resultado.atualizados)} esqueleto(s) intocado(s) atualizado(s), "
        f"{len(resultado.preservados)} preservado(s).",
        file=sys.stderr,
    )
    if resultado.preservados:
        print(
            f"Preservados (já têm conteúdo humano — edite à mão se quiser trocar): "
            f"{', '.join(resultado.preservados)}",
            file=sys.stderr,
        )
    print(
        f"Corpus tem {len(corpus['dispositivos'])} dispositivo(s). "
        f"Os novos entraram com resumo TODO e revisado: false.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
