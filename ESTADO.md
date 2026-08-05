# Estado do loop — atualizado em 2026-08-05

## Ciclo 0 (baseline)
- Item: levantamento do repositório e prova empírica das falhas de ingestão real
- Portões: pytest 101 passando · cobertura 96% · ruff ok · black ok
- Commit: (sem commit — só leitura)

Falhas de ingestão confirmadas rodando `carregar_transacoes` contra arquivos crus:

| Caso | Resultado hoje |
|---|---|
| CSV em latin-1/cp1252 (Excel BR) | `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9` |
| Linhas de título antes do cabeçalho | `linha 2: colunas obrigatórias vazias: [...]` |
| Data `01/05/2026` | `Invalid isoformat string: '01/05/2026'` |
| Uma linha ruim entre linhas boas | aborta o arquivo inteiro |
| Cabeçalho com nomes do relatório real | `colunas obrigatórias vazias: [...]` (não diz onde achar) |

## Fila
| P | Item | Estado | Bloqueio |
|---|------|--------|----------|
| P1 | Encoding: aceitar latin-1/cp1252 além de utf-8/utf-8-sig | a fazer | — |
| P1 | Linhas de cabeçalho extras + detecção de separador robusta | a fazer | — |
| P1 | Datas em formatos mistos (dd/mm/aaaa, dd-mm-aaaa, ISO com hora) | a fazer | — |
| P1 | Linhas parcialmente inválidas: relatório de rejeitadas, sem descarte silencioso | a fazer | — |
| P2 | Coluna faltando → frase de lojista dizendo como ela se chama na Shopee/ML | a fazer | — |
| P1 | Fixtures cruas reais em `tests/fixtures/reais/` (Shopee e Mercado Livre) ponta a ponta | a fazer | — |
| P3 | Teste de UI do `app.py` com `streamlit.testing.v1.AppTest` (7 abas + upload inválido) | a fazer | — |
| P0 | README honesto: contagem de testes e cobertura conferem com o real | a fazer | — |
| P4 | RBT12 móvel mês a mês | fila | — |
| P4 | Lucro Presumido atrás de flag | bloqueado | exige validar ICMS/ISS estadual/municipal em fonte oficial |
| P5 | Conectores Shopee/ML | bloqueado | exige credencial OAuth e aprovação de app |
| P6 | Persistência/auth | roadmap | só com piloto multiusuário |

## Bloqueados por humano (ação do Roberto)
- Registrar app na Shopee Open Platform e no Mercado Livre para obter as credenciais OAuth.
- Revisar juridicamente os 21 dispositivos de `data/corpus_pme.json` (`revisado: false`).
- Conseguir 1 lojista piloto e um export real de vendas.

## Decisões tomadas (para não redecidir)
- Cobertura medida só sobre `carchuna/` (`[tool.coverage.run] source`); `app.py` é casca e será
  coberto por `AppTest`, não pelo mínimo de cobertura.
- Ambiente do container precisa de `pip install cffi` antes de `pdfplumber` — problema de
  ambiente, não do repositório.
