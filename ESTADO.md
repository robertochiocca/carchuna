# Estado do loop — atualizado em 2026-08-05

## Ciclos 1–10 — OBJETIVO MÁXIMO atingido em 05/08/2026

| # | Item | Commit |
|---|---|---|
| 1 | Encoding: CSV em latin-1/cp1252 do Excel brasileiro | `9a85990` |
| 2 | Achar o cabeçalho da tabela sob linhas de título; separador `;`/`,`/tab/`\|` | `34e1683` |
| 3 | Datas em formatos mistos (dd/mm/aaaa, ERP, ISO com hora) | `ab135f4` |
| 4 | Relatório de linhas recusadas — nada some em silêncio | `fdecf02` |
| 5 | Mensagem que diz onde achar a coluna que faltou no relatório | `358017c` |
| 6 | Fixtures cruas de Shopee e Mercado Livre, ponta a ponta | `a9206be` |
| 7 | Teste de UI das 7 abas com `AppTest` + dashboard usando o relatório | `1b06be5` |
| 8 | Tabela de status do README alinhada com a realidade | `2932647` |
| 9 | Demo do site conferida contra o motor (tabelas + fórmula no node) | `19a9128` |
| 10 | Caminho do LLM coberto sem chave; piso do CI de 85% para 95% | `7885439` |

- Portões do último ciclo: pytest 173 passando · cobertura 98,33% · ruff ok · black ok
- CI verde em Python 3.10, 3.11 e 3.12 (run 41, commit `86b1ae0`)

### Conferência das 6 condições de pronto
| # | Condição | Estado |
|---|---|---|
| 1 | pytest verde, cobertura ≥ 95% real | 173 testes, 98,33% |
| 2 | ruff e black limpos; CI em 3.10/3.11/3.12 | verde nas três |
| 3 | Export cru de Shopee e ML entra, ou falha com frase de lojista | as duas fixtures, ponta a ponta |
| 4 | `AppTest` nas 7 abas + upload inválido | 10 testes em `tests/test_app.py` |
| 5 | Todo item do README classificado sem meio-termo | 23 linhas conferidas |
| 6 | Zero itens P0/P1 na fila | fila começa em P4 |

## Fila
| P | Item | Estado | Bloqueio |
|---|------|--------|----------|
| P4 | RBT12 móvel mês a mês nas séries | fila | exige 12 meses contínuos no arquivo; hoje a RBT12 é um valor só para o período |
| P4 | Lucro Presumido atrás de flag | bloqueado | cada alíquota de ICMS/ISS depende de estado e município e nenhuma foi validada em fonte oficial |
| P5 | Conector Shopee API | bloqueado por humano | app aprovado na Open Platform + OAuth do lojista |
| P5 | Conector Mercado Livre API | bloqueado por humano | app registrado + OAuth do lojista |
| P5 | Open Finance via agregador (Pluggy/Belvo) | bloqueado por humano | contrato e credenciais do agregador |
| P6 | Persistência/auth | roadmap | só faz sentido com piloto multiusuário |

**Nenhum item P0 ou P1 na fila.**

## Bloqueados por humano (ação do Roberto)
- Registrar o app na Shopee Open Platform e no Mercado Livre e obter as credenciais OAuth.
- Conferir os 21 dispositivos de `data/corpus_pme.json` na fonte oficial e virar `revisado: true`.
- Conseguir 1 lojista piloto e substituir `tests/fixtures/reais/` por um export de verdade,
  anonimizado (a fixture de hoje reproduz a FORMA do relatório, não é arquivo capturado).
- Conferir os valores dos Anexos do Simples no Planalto (a conferência automática de
  19/07/2026 recebeu HTTP 503) antes de qualquer uso real.

## Decisões tomadas (para não redecidir)
- **Data ambígua é brasileira.** `05/01/2026` é 5 de janeiro. O formato americano não entra
  na lista de tentativas: adivinhar entre dd/mm e mm/dd trocaria meses de lugar em silêncio.
- **Dois contratos de importação, de propósito.** `carregar_transacoes` e
  `transacoes_de_mapa` são tudo-ou-nada (quem já dependia disso continua servido);
  `carregar_com_relatorio` e `relatorio_de_mapa` importam o que dá e devolvem as recusadas.
  O dashboard usa os segundos.
- **O nome do cabeçalho é preservado como está na planilha.** A busca por campo é que ignora
  caixa e acento — assim a mensagem de erro e o mapeador mostram o nome que o lojista vê.
- **Palpite de coluna vence por especificidade.** "Custo do envio" é frete (termo longo),
  não CMV (termo "custo"). Sem isso o relatório do Mercado Livre mapeava errado em silêncio.
- **Os nomes de coluna de Shopee/ML são palpites, não fonte.** Estão no código com essa
  ressalva escrita e a frase diz "costuma se chamar"; o caminho garantido é o mapeador.
- **Cobertura mede só `carchuna/`.** O `app.py` é casca e é coberto pelo `AppTest`, não pelo
  percentual — por isso o piso de 95% vale para o pacote.
- **O site é código que afirma alíquota.** Por isso as tabelas e a fórmula do `index.html`
  são conferidas contra `margem.py` a cada CI, inclusive rodando o JavaScript no node.
- Ambiente do container precisa de `pip install cffi` antes de `pdfplumber` — problema de
  ambiente, não do repositório.
