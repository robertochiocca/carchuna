# Auditoria de segurança da Carchuna

**Data:** 11/08/2026 · **Escopo:** repositório na branch `carchuna/rateio-do-das-e-invariante`
(11 commits à frente de `origin/main`) · **Fases 0 e 1** concluídas — discovery e correções.

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

# Fase 1 — correções

Um commit por vulnerabilidade, na ordem aprovada. **Gate de saída aplicado em cada
um**: `pytest -q` verde · cobertura ≥ 95% · `ruff check .` · `black --check .` ·
`python examples/exemplo_diagnostico.py` roda.

Cada correção foi verificada por mutação: reverter o código faz cair um teste com
nome. Onde a mutação **não** derrubou nada, o teste foi corrigido antes do commit —
aconteceu três vezes, e está registrado abaixo.

## 8. Correções implementadas

### V1 — `decimal.InvalidOperation` atravessava toda a defesa · `f24392a`

| | |
|---|---|
| **Vulnerabilidade** | `Decimal("1e999")` num campo de dinheiro derruba a aplicação |
| **Causa raiz** | `_dinheiro` recusa `bool`, `float` e não-finito; `1e999` não é nenhum dos três. O estouro vem em `_q().quantize()`, com uma exceção que herda de `ArithmeticError` — e todo `except` do projeto captura `(ValueError, TypeError)` |
| **Correção** | `MAX_DINHEIRO = 1e9` e `MAX_PRAZO_RECEBIMENTO_DIAS = 365`, recusados na fronteira com `ValueError` |
| **Arquivos** | `carchuna/margem.py`, `carchuna/api/schemas.py` |
| **Razão** | O limite sai da aritmética, não de opinião: o contexto `Decimal` tem 28 dígitos e `quantize` a centavos estoura a partir de `1e26`; o pior caso do motor é `valor × taxa × dias/30` somado sobre a lista, então o teto de um campo é a raiz disso. No teto de tudo, com o teto de 200.000 lançamentos da API, o pior caso dá **2,4e24** — cabe com folga de 40×. E R$ 1 bilhão numa linha é três ordens de grandeza acima do teto do Simples |
| **Testes** | `test_seguranca_upload.py` (14), `test_seguranca_api.py` (10) |
| **Resultado** | verde · API: **500 → 422**; CSV: a linha ruim é rejeitada com motivo e as boas entram |

**Eram cinco portas, não uma.** Os campos de dinheiro da transação, as três taxas da
tabela de custos, e o `prazo_recebimento_dias` — que é `int` puro e não passava por
`_dinheiro` nenhum, mas multiplica o valor no custo de antecipação.

**O limite não podia ser de plausibilidade.** Uma comissão de 900% da receita continua
passando aqui de propósito: quem a carimba é `conferir_plausibilidade`. Confundir as
duas apagaria `test_comissao_de_900_por_cento_e_implausivel_e_a_identidade_nao_percebe`,
que é o teste que prova que a identidade estrutural não vê absurdo nenhum. Aqui recusa-se
o que **não é número calculável**; lá carimba-se o que **é número e não cabe na
realidade**.

### V2 — o dashboard público lia arquivo do disco do servidor · `17f5c83`

| | |
|---|---|
| **Vulnerabilidade** | Campo de texto público → `Path(source).read_bytes()` no container |
| **Causa raiz** | Recurso de uso local exposto na instância pública |
| **Correção** | O campo depende de `CARCHUNA_LER_CAMINHO=1`, desligado de fábrica, e **some** quando desligado |
| **Arquivos** | `carchuna/dados.py` (`leitura_por_caminho_ligada`), `app.py` |
| **Razão** | Mesmo padrão do `CARCHUNA_USAR_LLM`: quem publica o dashboard não deve expor o disco do servidor sem ter pedido. E some em vez de aparecer e recusar — caixa que só devolve erro convida a tentar, e cada tentativa responde alguma coisa |
| **Testes** | `test_seguranca_caminho.py` (14) |
| **Resultado** | verde |

**A fronteira é a aplicação, não a biblioteca, e isso é escolha.**
`carregar_com_relatorio("/x.csv")` continua funcionando: quem escreve um script Python
já tem o disco inteiro na mão, recusar ali seria teatro, e quebraria os onze arquivos de
teste que carregam fixture por caminho.

**Custou 14 testes de UI, e eu só vi pela mutação.** Eles usavam o campo como ferramenta
para pôr arquivo na tela. Ligar o interruptor neles é o certo — o que afirmam é sobre as
abas e os números. Registro o erro de processo: rodei o gate completo depois de V1 e não
repeti antes de seguir para o passo seguinte.

### V3 — a ingestão não tinha teto nenhum · `511a40a`

| | |
|---|---|
| **Correção** | Profundidade de JSON, razão de compressão de XLSX, linhas por arquivo, páginas de PDF, `maxUploadSize` |
| **Arquivos** | `carchuna/dados.py`, `.streamlit/config.toml` |
| **Testes** | `test_seguranca_upload.py` (+11) |
| **Resultado** | verde |

**Duas exceções novas da família do V1, achadas medindo:**

- `RecursionError` — JSON aninhado. **200 KB de colchete** derrubavam a aplicação. Não é
  `ValueError` nem `TypeError`.
- `OSError` — pacote `.xlsx` corrompido, levantado pelo openpyxl. Idem.

**Zip bomb recusado sem expandir:** o tamanho descomprimido está no cabeçalho do zip.
Medido: 199 KB no disco declarando **210 MB** — razão de **1028×**. Recusado sem um byte
descomprimido. Planilha real comprime de 10× a 20×.

Tetos: 500.000 linhas (~40 anos do lojista típico), 200 páginas de PDF, `maxUploadSize`
de 20 MB. **Nenhuma dependência nova** — `zipfile` e `json` são stdlib, e o
`maxUploadSize` é conferido com leitura de linha porque `tomllib` só existe a partir
do 3.11 e a matriz do CI começa no 3.10.

*Um teste meu não tinha dente:* chamava a guarda de profundidade na mão em vez de passar
pelo leitor. Corrigido antes do commit.

### V4 — só a busca legal tinha barreira · `ffa6a24`

| | |
|---|---|
| **Correção** | `LIMITE_CALCULO_POR_JANELA = 12` num limitador separado, nos cinco endpoints que calculam |
| **Arquivos** | `carchuna/api/limite.py`, `carchuna/api/main.py` |
| **Testes** | `test_seguranca_api.py` (+8) |
| **Resultado** | verde |

O custo aqui é CPU, não dinheiro de terceiro, então a conta é outra: a 30/minuto um
único IP pediria **quatro minutos de CPU por minuto de relógio**. Os dois contadores não
se misturam de propósito, e `/saude` fica de fora — é o que um monitor chama.

### V5 — a extensão prometia o formato e ninguém conferia · `0d15b42`

| | |
|---|---|
| **Correção** | Assinatura (magic bytes) confere a extensão nos dois sentidos |
| **Arquivos** | `carchuna/dados.py` |
| **Testes** | `test_seguranca_upload.py` (+7) |
| **Resultado** | verde |

A direção que importa é a segunda: extensão de texto com conteúdo binário mandava um zip
para o leitor de CSV — o caminho onde o teto de expansão não existe, porque ele mora no
leitor de planilha. A espiada devolve o buffer para trás; há teste para isso, porque um
`read` sem `seek` entregaria ao parser um arquivo já mordido.

### V6 — o erro do sistema operacional ia cru para a tela · `2c23ae5`

| | |
|---|---|
| **Correção** | `OSError` dá sempre a mesma mensagem; `ValueError` do motor continua inteira |
| **Arquivos** | `app.py` |
| **Testes** | `test_seguranca_erros.py` (13) |
| **Resultado** | verde |

**É uma distinção, não uma poda.** As mensagens do motor dizem qual coluna faltou, em que
linha e o que fazer — são funcionalidade central, e um erro que só diz "erro" empurra o
lojista para o suporte sem proteger ninguém. O que não sai é o que não foi escrito para
ninguém ler. Mensagem igual para causas diferentes é o que fecha o oráculo, e o arquivo
de teste guarda **as duas direções**: uma mutação que poda demais também derruba a suíte.

### V7 — o que o pipeline permitia · `257dca6`

| | |
|---|---|
| **Correção** | Actions por SHA, `permissions: contents: read` no CI, `pip-audit`, Dependabot, `.env.example`, `.gitignore` |
| **Testes** | `test_seguranca_supply_chain.py` (11) |
| **Resultado** | verde |

`pip-audit` é ferramenta de CI e **não** entrou no `requirements.txt`: o núcleo continua
com zero dependências, que é propriedade do desenho e não se perde numa correção de
segurança. A entrada `github-actions` no Dependabot não é enfeite — pinar por SHA sem ela
troca "versão que muda sozinha" por "versão que nunca é corrigida".

### V8 — a chave do limite era o IP do socket · `516508a`

| | |
|---|---|
| **Correção** | `chave_do_chamador()` lê `X-Forwarded-For` **só** com `CARCHUNA_PROXIES_CONFIAVEIS=n` |
| **Testes** | `test_seguranca_api.py` (+6) |
| **Resultado** | verde |

Confiar no cabeçalho por padrão entrega o limite a quem ele deveria limitar: um
`X-Forwarded-For` aleatório por requisição reinicia a contagem. A contagem é da **direita
para a esquerda**, porque a parte esquerda da lista é escrita pelo cliente. Valor
inválido cai no socket, nunca no cabeçalho.

*Um teste meu não separava as duas leituras* (um salto só no cabeçalho). Corrigido antes
do commit.

## 9. Testes de segurança adicionados

| Arquivo | Testes | Cobre |
|---|---|---|
| `tests/test_seguranca_upload.py` | 35 | V1 (dinheiro, prazo, taxas), V3 (JSON, zip bomb, linhas, PDF, upload), V5 (assinatura) |
| `tests/test_seguranca_api.py` | 39 | V1 na porta HTTP, tetos de payload, corpo malformado, V4 (limites), V8 (chave) |
| `tests/test_seguranca_erros.py` | 13 | V6 nas duas direções — vazamento e poda excessiva |
| `tests/test_seguranca_caminho.py` | 14 | V2 (política, tela, o que a correção não promete) |
| `tests/test_seguranca_supply_chain.py` | 11 | V7 (SHA, permissões, auditoria, segredos) |
| **Total** | **112** | |

**Regressão:** as fixtures reais (`mercado_livre_vendas_cru.csv`, `shopee_pedidos_cru.csv`)
continuam importando, conferido em `test_as_fixtures_reais_continuam_importando_igual` e
`test_os_arquivos_de_verdade_continuam_passando`.

Suíte total: **558 → 670 testes**, cobertura **99%** (piso do CI: 95%).

## 10. Score de segurança — DEPOIS

Mesma metodologia da seção 3.

| Categoria | Antes | Depois | O que mudou |
|---|---|---|---|
| Segurança de upload | 3 | **8** | assinatura, zip bomb, tetos de linha/página/tamanho. Não é 10: não há sandbox de parsing, e `pdfplumber` roda no mesmo processo |
| Validação de entrada / API | 5 | **8** | faixa aritmética fechada nas cinco portas. Não é 10: `TypeError` genérico ainda vira `detail=str(erro)` |
| Exaustão de recurso / abuso | 3 | **6** | limite nos cinco endpoints que calculam + tetos de ingestão. Continua um processo por instância, e o limite é por processo |
| Gestão de segredos | 8 | **9** | `.env.example`, `.gitignore` completo, `SECURITY.md`. Não é 10: a rotação depende de informação fora do repositório |
| Tratamento de erro / vazamento | 4 | **8** | `OSError` contido, oráculo fechado, teste varrendo respostas |
| Segurança de dependências | 2 | **5** | `pip-audit` no CI + Dependabot. **Continua sem lockfile** |
| CI/CD e supply chain | 3 | **7** | SHA + `contents: read`. `pages.yml` ainda precisa de `contents: write` para o desenho de deploy atual |
| Logging e observabilidade | 1 | **1** | **não mexi** — fora do escopo desta fase, e continua sendo o ponto mais fraco |
| Autenticação / Autorização | N/A | N/A | não há usuários na v1 |

## 11. Segredos que exigem rotação

| Nome | Local | Status | Ação |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | secrets do Streamlit Community Cloud | **não vazado** — histórico varrido em todos os blobs de todos os refs | rotação **não é urgente**. Rotacione se a chave for anterior à primeira publicação do app ou se tiver sido usada fora deste projeto |
| `ANTHROPIC_AUTH_TOKEN` | idem, alternativa à anterior | idem | idem |

Nenhum valor de segredo aparece neste relatório, em teste, em log ou em mensagem de
commit. O único literal parecido no repositório é `"sk-ant-chave-falsa-de-teste"` em
`tests/test_app.py`, que é placeholder e está aqui nomeado como tal.

## 12. Configuração necessária no Streamlit Community Cloud

Fora do repositório — precisa ser feito no painel:

1. **`CARCHUNA_LER_CAMINHO` NÃO deve ser definida** (ou deve ser `0`). Definir como `1`
   reabre a V2 inteira.
2. **`ANTHROPIC_API_KEY`** só nos secrets do app, nunca no repositório.
3. **`maxUploadSize`** já vem do `.streamlit/config.toml` versionado (20 MB) — confirme
   que o Cloud está lendo o arquivo.
4. **Visibilidade:** o app é público por desenho. Se algum dia receber base real de
   lojista, isso muda o modelo de ameaças inteiro.
5. **`CARCHUNA_PROXIES_CONFIAVEIS`:** deixe vazia até saber quantos proxies o Cloud põe
   na frente. Um número errado é pior que nenhum.

## 13. Configuração necessária no GitHub

Fora do repositório:

1. **Secret Scanning + Push Protection** — ligar. É a única barreira que impede um
   segredo de entrar no histórico; a varredura desta auditoria é de hoje, não do futuro.
2. **CodeQL / Code Scanning** — ligar em `Security` → `Code scanning`. Não adicionei o
   workflow porque habilitar depende do painel, e um arquivo sem a permissão ligada é
   ruído verde.
3. **Branch protection na `main`** — exigir CI verde. Hoje o `pages.yml` publica a cada
   push na `main` sem esperar o CI.
4. **Default de `permissions:` do repositório** — pôr em *read-only*. O `ci.yml` já
   declara o mínimo, mas o default vale para qualquer workflow futuro.
5. **Dependabot** — o arquivo está no repositório; conferir que está ativo em `Security`.

## 14. Riscos remanescentes

**O que a arquitetura atual não permite resolver:**

- **Disponibilidade.** É um processo por instância atendendo todos os visitantes. Cada
  correção sobe o custo do ataque; nenhuma elimina a classe. Só muda com fila, worker
  isolado ou limite de infraestrutura.
- **Limite por processo.** `LimiteDeChamadas` guarda estado em memória. Dois workers são
  dois limites, e um restart zera a contagem. Resolver exige estado compartilhado, que é
  a persistência que a v1 não tem por desenho.

**O que não foi feito, e por quê:**

- **Sem lockfile.** Gerar um do meu ambiente seria pior que não ter: a matriz do CI é
  3.10, 3.11 e 3.12, e um lock só não vale para as três — daria sensação de
  reprodutibilidade sem a coisa. Precisa de `pip-compile` por versão.
- **Logging e observabilidade continuam em 1.** Um 500 aparece no log do Cloud e nada
  mais. Sem isso, um ataque em curso é invisível até alguém reclamar.
- **`pages.yml` mantém `contents: write` e `--force`.** É o mínimo para o desenho de
  deploy atual (push direto na `gh-pages`). Trocar por `actions/deploy-pages` é mudança
  de arquitetura de deploy, fora do escopo desta fase.
- **Parsing sem sandbox.** `pdfplumber` e `openpyxl` rodam no processo do app. Os tetos
  reduzem a superfície; uma vulnerabilidade de memória nas bibliotecas continua com o
  processo inteiro na mão.

**O que não pôde ser verificado** (a seção acima, na Fase 0, continua valendo): a
configuração do Streamlit Cloud e a do GitHub são externas ao repositório.

## 15. Próximos passos

**P0 — nada.** As duas HIGH e a terceira estão corrigidas e com teste.

**P1 — depende de você, não de código:**
1. Confirmar que `CARCHUNA_LER_CAMINHO` **não** está definida no Cloud.
2. Ligar Secret Scanning + Push Protection.
3. Branch protection na `main` exigindo CI verde.

**P2 — código, quando houver tempo:**
4. Lockfile por versão da matriz.
5. Logging estruturado do que é recusado na fronteira — hoje um ataque não deixa rastro.
6. `TypeError` genérico na API deixar de virar `detail=str(erro)`.

**P3 — quando o roadmap pedir:**
7. Estado compartilhado do limite, junto com a persistência.
8. `actions/deploy-pages` no lugar do force push.
9. Os requisitos da seção 7b, **antes** de auth e persistência entrarem — não depois.

---

*Esta auditoria não conclui que a Carchuna está segura. Ela registra o que foi
verificado, o que foi achado, o que foi corrigido, o que não pôde ser verificado e o que
continua em risco.*
