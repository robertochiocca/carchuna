# Auditoria de segurança da Carchuna — Fase 0 (discovery)

**Data:** 11/08/2026 · **Escopo:** repositório na branch `carchuna/rateio-do-das-e-invariante`
(11 commits à frente de `origin/main`) · **Fase:** 0 — somente leitura, nenhum arquivo de
código alterado.

**Baseline registrado antes de qualquer leitura profunda:** `pytest -q` → 558 passed ·
`ruff check .` → All checks passed · `black --check .` → 72 files unchanged.

---

## 1. Sumário executivo

Não afirmo que a Carchuna está segura. Este é o que foi verificado e o que foi achado.

Achei **um defeito que derruba a aplicação com cinco caracteres**, e ele não estava nas
hipóteses de partida: `Decimal("1e999")` num campo de dinheiro passa por toda a validação —
é finito, é `Decimal`, não é `float` — e estoura em `_q()` com `decimal.InvalidOperation`,
que é `ArithmeticError` e **não** é `ValueError`/`TypeError`. Nenhum dos `except` do projeto
o captura. Medido: HTTP **500** na API; no dashboard, traceback na tela. Entra por uma
célula de CSV ou por um JSON de 200 bytes.

O campo "tempo real" lê **caminho arbitrário do servidor**, e a mensagem de erro ecoa
todos os nomes de coluna do arquivo lido. A hipótese H1 (ler `/etc/passwd`) está
**parcialmente refutada**: o despacho por extensão recusa o que não termina em
`.csv/.tsv/.json/.xlsx/.pdf` **antes** de abrir — uma mitigação acidental, não desenhada,
que segura a parte pior. O que sobra ainda é leitura de arquivo do servidor e um oráculo
de existência de caminho.

A varredura de histórico foi feita de verdade — 106 commits, todos os blobs de todos os
refs — e **nenhum segredo real foi commitado**; o único `sk-ant` do histórico é o literal
`"sk-ant-chave-falsa-de-teste"` de `tests/test_app.py`. Isto eu posso afirmar porque varri,
não porque presumi.

Duas hipóteses foram **refutadas** e estão registradas como tal (H8, e H1 em parte).

---

## 2. Arquitetura descoberta

O mapa da §1 do prompt está **correto**. Correções e precisões:

| Item do prompt | Verificado | Correção |
|---|---|---|
| `.streamlit/config.toml` | **existe e é versionado** | o prompt sugeria ausência; ele existe mas tem **só `[theme]`** — nenhuma seção `[server]`, então `maxUploadSize` fica no default de 200 MB |
| Rate limit "chave = `request.client.host`" | confirmado | `carchuna/api/main.py:237` |
| Parsers "despacho por extensão" | confirmado | `carchuna/dados.py:476-477` |
| `unsafe_allow_html` — 1 ocorrência | confirmado | `app.py:80`, bloco `<style>` estático, sem interpolação de dado |
| Núcleo com zero dependências | confirmado | `pyproject.toml`: `dependencies = []` |
| `SECURITY.md`, `.env.example` | **não existem** | a criar na Fase 1 |
| `.gitignore` cobre `secrets.toml` | confirmado desde o 1º commit (`f4d4169`) | **não** cobre `.env*`, `*.pem`, `*.key` |

### Inventário de endpoints

| Endpoint | Método | Auth | Validação | Teto de payload | Rate limit | Custo/chamada | Risco |
|---|---|---|---|---|---|---|---|
| `/api/v1/saude` | GET | não | — | — | não | zero | INFO — expõe versão e estado da geração (sem credencial) |
| `/api/v1/margem/decompor` | POST | não | Pydantic | 200.000 transações | **não** | CPU | **500 com `1e999`** (V1); CPU (V4) |
| `/api/v1/cenarios` | POST | não | Pydantic | 200.000 | **não** | CPU × 6 cenários | **7,7 s medidos** no teto (V4) |
| `/api/v1/diagnostico` | POST | não | Pydantic | 200.000 | **não** | CPU + BM25 | V4 |
| `/api/v1/crescimento` | POST | não | Pydantic | 200.000 | **não** | CPU | V4 |
| `/api/v1/preco-alvo` | POST | não | Pydantic | payload pequeno | **não** | baixo | baixo |
| `/api/v1/legal/buscar` | GET | não | `q` ≤ 500, `top_k` 1–10 | — | **sim** 30/60 s | **pode virar chamada paga** | V8 (chave do limite) |

---

## 3. Score de segurança — ANTES

| Categoria | Nota 0–10 | Evidência |
|---|---|---|
| Segurança de upload | **3** | despacho por extensão (`dados.py:476-477`), sem magic bytes; sem teto de tamanho (`.streamlit/config.toml` sem `[server]`); `_ler_pdf` sem teto de páginas (`dados.py:884-893`) |
| Validação de entrada / API | **5** | Pydantic cobre tipo e tamanho de lista/string (`schemas.py:73,78,84-86`), mas `1e999` atravessa tudo e estoura em `margem.py:410` |
| Exaustão de recurso / abuso | **3** | 5 de 7 endpoints sem limite; 200k transações = 7,7 s medidos; upload de 200 MB aceito |
| Gestão de segredos | **8** | histórico varrido e limpo; só `os.environ` em `rag/llm.py`; `estado_da_geracao()` nunca imprime valor. Perde ponto por não haver `.env.example` nem `SECURITY.md` |
| Tratamento de erro / vazamento | **4** | `HTTPException(detail=str(erro))` (`main.py:76,208`); `st.error(f"... {erro}")` (`app.py:1332,1342,1380`); `ColunasFaltando` ecoa o cabeçalho do arquivo |
| Segurança de dependências | **2** | tudo `>=`, sem lockfile (`requirements.txt`), sem pip-audit, sem Dependabot |
| CI/CD e supply chain | **3** | `ci.yml` sem `permissions:`; `pages.yml` com `contents: write` + `--force`; actions por tag, não SHA |
| Logging e observabilidade | **1** | não existe logging estruturado; um 500 só aparece no log do Cloud |
| Autenticação / Autorização | **N/A** | não há usuários na v1 |

---

## 4. Tabela de vulnerabilidades

| Sev | Confiança | Vulnerabilidade | OWASP | Arquivo:linha | Evidência | Impacto | Explorabilidade | Correção proposta |
|---|---|---|---|---|---|---|---|---|
| **HIGH** | CONFIRMADO | `decimal.InvalidOperation` não capturado em nenhum lugar | A04 / API4 | `margem.py:410` (`_q`), `margem.py:158-167` (`_dinheiro`) | HTTP 500 medido; `issubclass(InvalidOperation, (ValueError,TypeError))` = **False** | queda do dashboard e 500 na API | **trivial** — `1e999` numa célula | recusar expoente fora da faixa monetária em `_dinheiro`, com `ValueError` |
| **HIGH** | CONFIRMADO | Leitura de caminho arbitrário + eco do cabeçalho do arquivo | A01 / A05 | `app.py:1317,1337` → `dados.py:693`, mensagem em `_conferir_colunas` | PoC: nomes `cpf_do_cliente, saldo_bancario, senha_hash` ecoados na mensagem | leitura de `.csv/.json/.xlsx/.pdf` do servidor + oráculo de existência | **trivial** — campo de texto público | allowlist de diretório + mensagem que não ecoa nomes de coluna de fora do allowlist |
| **HIGH** | PROVÁVEL | Ingestão sem teto de tamanho / páginas / linhas | A05 | `.streamlit/config.toml` (sem `[server]`), `dados.py:884-893` | `for pagina in pdf.pages: pagina.extract_tables()` sem corte | CPU/memória de um processo compartilhado | alta | `maxUploadSize`, teto de páginas/linhas/profundidade antes do parse |
| **MEDIUM** | CONFIRMADO | 5 de 7 endpoints sem limite, com CPU proporcional | API4 | `main.py:95,136,152,172` | **7,7 s** medidos para 200k transações (corpo de 21,6 MB) | indisponibilidade | média | limite por IP em todos; baixar o teto de 200k |
| **MEDIUM** | CONFIRMADO | Despacho de parser por extensão do nome | A08 / File Upload CS | `dados.py:476-477` | `filename.rsplit(".", 1)[-1]` | `.csv` que é zip chega no parser errado | média | conferir magic bytes antes do despacho |
| **MEDIUM** | CONFIRMADO | Erro interno propagado para tela/resposta | A05 | `main.py:76,208`; `app.py:1332,1342,1380` | `FileNotFoundError: [Errno 2] ... '<path>'` na tela | caminho, errno, classe de exceção | trivial | mensagem para o lojista; detalhe interno só no log |
| **MEDIUM** | CONFIRMADO | Supply chain sem pin nem permissão mínima | A08 | `requirements.txt`; `ci.yml` (sem `permissions:`); `pages.yml:14-15` | tudo `>=`; `contents: write` + `git push --force` | build não reprodutível; workflow com escrita | baixa | lockfile, `permissions: contents: read`, actions por SHA |
| **LOW** | CONFIRMADO | Rate limit por `request.client.host`, estado por processo | API4 | `main.py:237`; `limite.py:44-70` | chave é o IP do socket | atrás de proxy: bloqueio coletivo ou IP ignorável | média | ler `X-Forwarded-For` **só** com lista de proxies confiáveis |
| **INFO** | PRECISA VERIFICAR | Devcontainer desliga XSRF e CORS | A05 | `.devcontainer/devcontainer.json` (`postAttachCommand`) | flags só no comando do Codespaces | nenhum caminho de deploy no repo herda isso | — | confirmar no painel do Streamlit Cloud |

### Hipóteses refutadas (registradas para não voltarem)

- **H1 (parcial) — REFUTADA na parte pior.** `/etc/passwd`, `/proc/self/environ` e
  `.streamlit/secrets.toml` são **recusados antes de o arquivo ser aberto**, porque
  `dados.py:477` exige extensão conhecida. Saída medida:
  `ValueError: Formato não suportado: ./etc/passwd`. A leitura arbitrária existe, mas só
  para as cinco extensões — e isso muda a severidade de CRITICAL para HIGH.
- **H8 — REFUTADA.** Existe **um** export CSV (`app.py:1955`, `historico.to_csv`) e nenhuma
  das suas colunas carrega string do arquivo do lojista: mês é `f"{ano:04d}-{mes:02d}"`,
  os três valores são numéricos e `col_maior_custo` vem do dicionário interno `rotulos`.
  Não há injeção de fórmula no que a Carchuna exporta hoje.
- **H11 — VERIFICADA E LIMPA.** 106 commits, varredura de `sk-ant` em **todos os blobs de
  todos os refs**: 11 ocorrências, todas o literal `"sk-ant-chave-falsa-de-teste"` de
  `tests/test_app.py`. Padrões AWS/GitHub/Google/Slack/PEM: zero. `secrets.toml`, `.env`,
  `*.pem`, `*.key` nunca foram adicionados em commit nenhum.
- **H6 (parcial) — REFUTADA.** Existe teto: `MAX_TRANSACOES_POR_CHAMADA = 200_000` e
  `MAX_PERGUNTA = 500` (`schemas.py:73,78`). O achado que sobra é o **tamanho** do teto.

---

## 5. Caminhos de ataque (os três mais graves)

**A1 — Queda por número monetário absurdo**
`Visitante anônimo → CSV com a célula 1e999 (ou POST /margem/decompor com
"valor_bruto":"1e999") → _dinheiro() aceita (é Decimal, é finito, não é float) →
_q().quantize() levanta decimal.InvalidOperation → nenhum except do projeto captura
(é ArithmeticError) → API responde 500; dashboard mostra traceback`
Medido nas duas pontas. Custo do ataque: um arquivo de duas linhas.

**A2 — Leitura de arquivo do servidor pelo campo "tempo real"**
`Visitante anônimo → digita /caminho/qualquer.csv no st.text_input →
carregar_com_relatorio() → Path(source).read_bytes() → cabeçalho não bate →
ColunasFaltando ecoa "O que o seu arquivo tem: <todas as colunas do arquivo>" na tela`
PoC executado: um CSV fora do projeto teve `cpf_do_cliente, saldo_bancario, senha_hash`
impressos. Caminho inexistente devolve `FileNotFoundError` com o path — três respostas
distinguíveis formam um oráculo de existência.

**A3 — Exaustão do processo compartilhado**
`Visitante anônimo → PDF pequeno e denso, ou 200k transações via API →
pdf.pages × extract_tables() sem teto, ou 6 cenários sobre 200k lançamentos →
7,7 s de CPU por requisição num processo que atende todos os visitantes`
Medido: 20k → 0,78 s; 200k → 7,7 s. Poucas requisições paralelas bastam.

---

## 6. Modelo de ameaças

### 7a. v1 — o que está no ar hoje

| Ameaça | Prob. | Impacto | Risco | Mitigação | Teste que prova |
|---|---|---|---|---|---|
| Derrubar o app com número absurdo | alta | alto | **alto** | recusar expoente fora da faixa monetária | `test_seguranca_upload.py` — CSV com `1e999` recusa a linha e o app segue |
| Ler arquivo do servidor pelo campo de caminho | alta | médio | **alto** | allowlist de diretório; mensagem sem eco | `test_seguranca_upload.py` — caminho fora do allowlist recusado sem revelar existência |
| Exaurir CPU com PDF/planilha densos | alta | médio | **alto** | teto de páginas/linhas/tamanho | `test_seguranca_upload.py` — PDF acima do teto recusa |
| Exaurir CPU pela API | média | médio | médio | limite em todos os endpoints | `test_seguranca_api.py` — 429 com `Retry-After` |
| Vazar detalhe interno por mensagem de erro | alta | baixo | médio | mensagem para o lojista, detalhe no log | `test_seguranca_erros.py` — resposta sem path/stack/módulo |
| Comprometer o corpus legal por dependência | baixa | alto | médio | lockfile + pip-audit | CI falha com CVE conhecida |
| Escrita indevida via workflow de Pages | baixa | alto | médio | `permissions` mínimo, actions por SHA | revisão do workflow |
| Vazar `ANTHROPIC_API_KEY` por log/erro | baixa | alto | médio | nunca imprimir valor (já é o caso, `rag/llm.py`) | `test_geracao_config.py` (existente) |

**Ativo que a arquitetura atual não protege:** a disponibilidade. É um processo único no
Community Cloud atendendo todos os visitantes; qualquer correção reduz o custo do ataque,
nenhuma elimina a classe.

### 7b. Roadmap — requisitos prévios ao merge de auth + persistência

Nada aqui é achado atual. São condições de aceite para quando `PBKDF2 + Bearer` e
SQLAlchemy entrarem (README já os prevê):

- **Ownership check server-side em toda leitura e escrita.** Sem isso, IDOR/BOLA nasce no
  primeiro endpoint que receber um `id`.
- **Isolamento por lojista** no nível da consulta, não do filtro de aplicação.
- **Retenção declarada** para dado financeiro de terceiro, com prazo e apagamento.
- **Criptografia em repouso** e segredo de assinatura fora do repositório.
- **Teste de autorização por endpoint** — um por rota, não um genérico.

---

## 7. Achados HIGH em detalhe

### V1 — `decimal.InvalidOperation` atravessa toda a defesa (CONFIRMADO)

`_dinheiro` (`margem.py:146-168`) recusa `bool`, `float` e não-finito. `Decimal("1e999")`
não é nenhum dos três: é `Decimal`, é finito, e passa. O estouro acontece adiante, em
`_q()` (`margem.py:410`), quando `.quantize(Decimal("0.01"))` não cabe na precisão do
contexto.

O que torna isto grave não é o estouro, é a **classe da exceção**. Todo o projeto contém
erro de dado com `except (ValueError, TypeError)` — em `carregar_com_relatorio`
(`dados.py:419`), em `app.py:1330`, no `_analisador` da API (`main.py:75`) e no
`_resultados_cacheados` que acabei de blindar. `decimal.InvalidOperation` herda de
`ArithmeticError`, não de nenhuma das duas. Verificado:
`issubclass(decimal.InvalidOperation, (ValueError, TypeError))` → **False**.

Medições:
- API: `POST /api/v1/margem/decompor` com `"valor_bruto":"1e999"` → **HTTP 500**.
- Dashboard: `carregar_com_relatorio()` **importa a linha sem rejeitar** e o estouro só
  acontece no `decompor_margem` — fora do `try` que existe para isso.

A correção pertence a `_dinheiro`, e não a um `except` novo: a faixa de um valor monetário
é conhecida, e um número fora dela é dado ruim, que este projeto já sabe recusar com nome
de coluna e número de linha.

### V2 — Leitura de caminho arbitrário com eco do cabeçalho (CONFIRMADO)

Cadeia: `app.py:1317` (`st.text_input("caminho_arquivo")`) → `app.py:1337`
(`carregar_com_relatorio(caminho_arquivo)`) → `dados.py:693`
(`io.StringIO(_decodificar(Path(source).read_bytes()))`).

**O que a mitigação acidental já segura.** `dados.py:477` extrai a extensão e recusa o que
não conhece **antes** de qualquer leitura. Por isso `/etc/passwd` e
`.streamlit/secrets.toml` não são lidos. Isto não foi desenhado como defesa — é efeito
colateral do despacho — e por isso não deve ser tratado como uma.

**O que sobra, provado.** Qualquer `.csv/.tsv/.json/.xlsx/.pdf` do servidor é aberto, e
`_conferir_colunas` termina a mensagem com
`f"O que o seu arquivo tem: {', '.join(originais)}."`. PoC: um CSV fora do projeto com
cabeçalho `data;canal;cpf_do_cliente;saldo_bancario;senha_hash` teve os cinco nomes
impressos na mensagem de erro que vai para `st.error`.

Três respostas distinguíveis fazem o oráculo: `FileNotFoundError` (não existe),
`ValueError: Formato não suportado` (existe, extensão recusada), erro de cabeçalho
(existe e foi lido).

### V3 — Ingestão sem teto (PROVÁVEL — falta executar o PoC)

`.streamlit/config.toml` tem só `[theme]`; sem `[server] maxUploadSize`, o default de
200 MB vale. `_ler_pdf` (`dados.py:884-893`) faz `for pagina in pdf.pages:` e
`pagina.extract_tables()` por página, sem teto de páginas nem de tempo. `_ler_xlsx` usa
`read_only=True`, o que reduz memória mas não impede zip bomb nem planilha de 1M de linhas.

Marcado **PROVÁVEL** e não CONFIRMADO porque não construí o zip bomb nem o PDF denso nesta
fase — o gate da Fase 0 é leitura, e o PoC pertence aos testes da Fase 1.

---

## O que NÃO pôde ser verificado

- **Configuração do Streamlit Community Cloud** (secrets, `maxUploadSize` efetivo,
  visibilidade do app) — fora do repositório.
- **Configuração do GitHub** (Secret Scanning, Push Protection, Dependabot, CodeQL, branch
  protection, default de `permissions:` do repositório) — fora do repositório. O
  `ci.yml` **não declara** `permissions:`, então o que vale é esse default, que não consigo
  ler daqui.
- **Se o `ANTHROPIC_API_KEY` está de fato configurado no Cloud** e há quanto tempo — a
  decisão de rotação depende disso.
- **Zip bomb e PDF denso** — não construídos nesta fase, por causa do gate de leitura.

---

## Fim da Fase 0

Nenhum arquivo de código foi alterado. `pytest`, `ruff` e `black` seguem no baseline
registrado no topo.

**A Fase 1 precisa da sua aprovação.** A ordem que proponho, por severidade e por custo de
ataque: V1 (cinco caracteres derrubam o app) → V2 (leitura de arquivo do servidor) →
V3 (tetos de ingestão) → V4/V5/V6 → V7/V8.
