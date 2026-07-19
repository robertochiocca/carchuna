<div align="center">

# 🏖️ Carchuna

**Inteligência de margem para o PME brasileiro. Você fatura 400; a Carchuna mostra, com prova, por que sobra 8.**

*(Como a praia de Carchuna, na costa de Granada: águas transparentes onde se vê o fundo.)*

[![CI](https://github.com/robertochiocca/carchuna/actions/workflows/ci.yml/badge.svg)](https://github.com/robertochiocca/carchuna/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Testes](https://img.shields.io/badge/testes-78%2F78-brightgreen.svg)](tests/)
[![Cobertura](https://img.shields.io/badge/cobertura-96%25-brightgreen.svg)](.github/workflows/ci.yml)
[![Código: black](https://img.shields.io/badge/c%C3%B3digo-black-000000.svg)](https://github.com/psf/black)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green.svg)](LICENSE)

🇧🇷 [Português](#-o-problema) · 🇺🇸 [English](#-english-version)

</div>

> ℹ️ **Conceito / projeto de portfólio — não é uma empresa nem aconselhamento jurídico/contábil.** Este repositório estuda como uma plataforma de inteligência de margem para PMEs brasileiras *poderia* funcionar. O que está implementado tem teste e CI; o que não está é roadmap explicitamente sinalizado.

---

## 🎯 O problema

O lojista faz a conta ingênua — **receita − custo do produto = "lucro"** — mas o lucro morre no caminho: impostos, comissão de marketplace, taxa da maquininha, antecipação de recebíveis, frete, devoluções. O CNPJ típico deste estudo fatura **~R$ 400 mil/mês e lucra ~2%**, vende no Mercado Livre/Shopee/Amazon, está no Simples Nacional e **não sabe exatamente onde a margem morre**. Não pode pagar CFO (R$ 15–30 mil/mês) nem tributarista por hora.

A palavra-chave do produto é **verificável**: nenhum número sai de um chatbot — todo número sai de um motor determinístico testado, e **a IA entra depois do cálculo, nunca antes**.

## 🔄 O fluxo do produto

```
1. Importação      CSV / JSON / XLSX de vendas (conectores de API no roadmap)
        ↓
2. Reconstrução    receita → impostos → marketplace → adquirência →
   da margem       antecipação → frete → devoluções → CMV → margem real
                   (do período, mês a mês e VENDA A VENDA)
        ↓
3. Diagnóstico     "No período de 7 mês(es), R$ 833.092,65 de margem se
                    perderam entre a margem anunciada (41,90%) e a real
                    (13,36%); 35% dessa perda veio de Comissões de canal."
        ↓
4. Simulação       "Migração de 30% das vendas de mercado_livre para
                    loja_propria: impacto R$ +26.313,31 (+0,90 p.p.)"
        ↓
5. Explicação      base legal citada com fonte oficial (LC 123, CTN, CDC,
   legal/IA        Bacen…) — depois do cálculo, com aviso em toda resposta
```

A venda de R$ 100 decomposta pelo motor (caso conferido à mão nos testes):

```
Receita bruta:                 R$ 100,00
(-) Tributos (Simples, 5,65%): R$   5,65   ← LC 123/2006, art. 18, § 1º-A
(-) Comissão marketplace:      R$  12,00   ← tabela pública do canal (editável)
(-) Frete:                     R$  10,00
(-) Custo do produto (CMV):    R$  40,00
------------------------------------------
Margem líquida real:           R$  32,35   (32,35% — não os 60% "anunciados")
```

## 🧬 DNA da trilogia (inegociável)

Terceira plataforma de uma trilogia andaluza: ⚡ [Calahonda](https://github.com/robertochiocca/calahonda) (quant para gestoras) · ⚖️ [DireitoAberto](https://github.com/robertochiocca/direitoaberto) (legal RAG para o cidadão) · 🏖️ **Carchuna** (os dois motores, casados, para o PME).

1. **Nenhuma afirmação sem lastro** — toda saída ou é calculada por código testado, ou é citada de fonte oficial com link. A IA nunca inventa.
2. **Degradação graciosa** — funciona de ponta a ponta **sem chave de API**: cálculo local + modo extrativo.
3. **PT-BR do lojista** — "maquininha" → adquirência, "antecipar" → antecipação de recebíveis, "ML" → Mercado Livre.
4. **Honestidade técnica** — a tabela de status separa o implementado do roadmap; dispositivos legais entram com `"revisado": false` até revisão humana.
5. **Camadas trocáveis** — motores atrás de interfaces estáveis (padrão `Retriever` do DireitoAberto).
6. **Dinheiro é `Decimal`** — `float` em campo monetário é rejeitado com `TypeError`; na API, dinheiro trafega como *string* no JSON.

## 🏛️ Arquitetura (orientada a objetos, camadas trocáveis)

```
AnalisadorMargem (fachada)          ← analise.py: um objeto, os quatro motores
├── motor de margem                 ← margem.py: decompor_margem + Decimal
│     └── margem_por_venda()        ← a mesma decomposição, venda a venda
├── métricas                        ← metricas.py: queda, instabilidade, lucro
├── Cenario (ABC)                   ← cenarios.py: cada cenário é uma classe
│     ├── CenarioComissao           │  que só sabe TRANSFORMAR as entradas;
│     ├── CenarioAntecipacao        │  a base reexecuta o motor testado e
│     ├── CenarioDevolucoesDobram   │  compara antes/depois
│     ├── CenarioMudancaAnexo       │
│     └── CenarioMigracaoCanal      ← "e se 30% do ML virasse canal próprio?"
├── MotorDiagnostico                ← diagnostico.py: orquestra as regras
│     └── RegraDeteccao (ABC)       ← 4 heurísticas transparentes; estender =
│                                      herdar e registrar (aberto/fechado)
├── Retriever (BM25 + sinônimos)    ← rag/: base legal citada, LLM opcional
└── API FastAPI + Pydantic          ← api/: casca fina e stateless em /api/v1
```

O núcleo é **Python puro, zero dependências** — Streamlit, matplotlib e FastAPI são cascas opcionais em volta do mesmo motor. A parte determinística é 100% testável sem LLM; a parte generativa nunca calcula.

## 📊 Status honesto (o que existe vs. roadmap)

| Módulo | Status |
|---|---|
| `margem.py` — decomposição com alíquota efetiva do Simples (LC 123/2006, art. 18, § 1º-A; Anexos I–V) | ✅ implementado e testado |
| `analise.py` — fachada `AnalisadorMargem`, resumo executivo ("quanto se perdeu e de onde veio") e **margem venda a venda** | ✅ implementado e testado |
| `dados.py` — importação CSV/JSON/XLSX (vírgula decimal BR) + dados sintéticos reprodutíveis | ✅ implementado e testado |
| `metricas.py` — margem mês a mês, maior queda, instabilidade, lucro acumulado | ✅ implementado e testado |
| `cenarios.py` — comissão +2 p.p., Selic +3 p.p., devoluções dobram, mudança de anexo, **migração de canal** | ✅ implementado e testado |
| `rag/` — BM25 + sinônimos do lojista + LLM opcional com fallback extrativo | ✅ implementado e testado |
| `data/corpus_pme.json` — 21 dispositivos (LC 123, CDC, CTN, Bacen, LGPD…) | ✅ ingerido · ⚠️ **revisão humana pendente** (`revisado: false`) |
| `diagnostico.py` — `MotorDiagnostico` com 4 regras plugáveis gerando achados com base legal | ✅ implementado e testado |
| `api/` — FastAPI + Pydantic, stateless, `/api/v1` com OpenAPI em `/docs` | ✅ implementado e testado |
| `relatorio.py` — PDF de 3 páginas (raio-X, cenários, achados) | ✅ implementado e testado |
| `app.py` — dashboard Streamlit com 5 abas | ✅ implementado (sem teste automatizado de UI) |
| Autenticação da API (PBKDF2 + Bearer) e persistência (SQLAlchemy; SQLite → PostgreSQL via env) | ⬜ roadmap — quando houver piloto multiusuário |
| Regime **Lucro Presumido** | ⬜ roadmap (depende de ICMS/ISS estaduais/municipais) |
| RBT12 móvel mês a mês nas séries | ⬜ roadmap |
| Conectores Mercado Livre / Shopee (APIs oficiais) | ⬜ roadmap |
| Open Finance via agregador (Pluggy/Belvo) | ⬜ roadmap |
| MCP server (consultar a Carchuna por assistentes de IA) | ⬜ roadmap |
| Busca semântica (embeddings/ChromaDB, opt-in) | ⬜ roadmap |
| ML preditivo (previsão de vendas) | ⬜ roadmap — heurísticas transparentes primeiro |

**Meta antes de qualquer conector:** 1 lojista piloto usando com CSV real.

## 🚀 Como rodar

```bash
git clone https://github.com/robertochiocca/carchuna.git
cd carchuna

# O núcleo é Python puro (zero dependências): exemplo e testes rodam offline
python examples/exemplo_diagnostico.py
pip install pytest && pytest          # 78 testes

# Dashboard e API
pip install -r requirements.txt
streamlit run app.py                            # dashboard (5 abas)
uvicorn carchuna.api.main:app --reload          # API — OpenAPI em /docs
```

Em três linhas de Python:

```python
from carchuna import AnalisadorMargem

analise = AnalisadorMargem.demo(meses=6)   # ou .de_arquivo("vendas.csv", config)
print(analise.resumo_executivo().frase())
# No período de 7 mês(es), R$ 833.092,65 de margem se perderam entre a margem
# anunciada (41.90%) e a real (13.36%); 35% dessa perda veio de Comissões de canal.
```

Com `ANTHROPIC_API_KEY` configurada, as respostas do diagnóstico ganham narrativa em linguagem natural (API da Anthropic); **sem chave, tudo funciona em modo extrativo** — o cálculo nunca depende de LLM.

## 🔍 Como cada número ganha lastro

- **Tributos**: fórmula oficial da alíquota efetiva (LC 123/2006, art. 18, § 1º-A) com os Anexos I–V na redação da LC 155/2016, validada por testes calculados à mão — inclusive o degrau da 6ª faixa, em que o ICMS/ISS saem da guia pelo sublimite (arts. 19 e 20). A conferência automática no Planalto foi tentada em 19/07/2026 (portal retornou HTTP 503 a robôs); a data e a ressalva estão documentadas em `carchuna/margem.py`.
- **Comissões/adquirência/antecipação**: tabelas **editáveis pelo usuário**, com defaults documentados com fonte e marcados `estimado` — o seu contrato prevalece.
- **Invariante contábil testado**: soma das deduções + margem líquida == receita bruta, centavo a centavo.
- **Base legal dos achados**: apenas o que o `Retriever` recuperou do corpus versionado — com link oficial e status de revisão em cada citação. Fluxo: pergunta → busca no corpus → recuperação dos trechos → LLM interpreta (opcional) → cita fonte → aviso.
- **Excel**: células numéricas chegam como `float` do openpyxl; a conversão passa por `str()` e esta é a única exceção documentada à regra do `Decimal` — prefira CSV.

## 🚫 O que a Carchuna **não** é (anti-escopo)

Não é ERP (não emite nota, não controla estoque); **não dá parecer jurídico nem promete recuperação tributária** ("você tem direito a R$ X de volta" — nunca; esse mercado é infestado de golpes de "teses"); não é a Calahonda (sem VaR/carteira); não importa o corpus B2C do DireitoAberto; sem ML preditivo, score de crédito ou decisão financeira automatizada na v1; sem armazenar credenciais bancárias; sem scraping de portais que bloqueiam robôs.

## 🧪 Qualidade

`pytest` (78 testes, cobertura 96%, mínimo 85% no CI) · `ruff` · `black` · GitHub Actions em Python 3.10, 3.11 e 3.12. Padrão de teste: casos validados contra cálculo manual (o "VaR ≈ 1.645σ" daqui é a alíquota do Simples conferida à mão), invariantes contábeis e a API respondida com os mesmos centavos do motor.

**Stack:** Python 3.10+ (núcleo sem dependências) · FastAPI · Pydantic · Streamlit · matplotlib · pytest

---

## 🇺🇸 English version

**Carchuna** — verifiable margin intelligence for Brazilian SMBs. It rebuilds a seller's real margin deterministically (taxes, marketplace fees, card acquiring, receivables prepayment, freight, returns, COGS) — for the period, per month and **per sale** — quantifies where profit died ("R$ 833k of margin lost; 35% came from marketplace fees"), simulates alternatives (channel migration, fee shocks, tax bracket changes) and only then uses RAG over official legal sources to explain, with citations. **AI comes after the math, never before.** Third project of an Andalusian trilogy ([Calahonda](https://github.com/robertochiocca/calahonda) → quant, [DireitoAberto](https://github.com/robertochiocca/direitoaberto) → legal RAG).

Core principles: every output is either computed by tested code or cited from an official source with a link; graceful degradation (fully functional without any API key); money is `Decimal`, never `float` (serialized as strings over the API); legal corpus entries ship with `"revisado": false` until human review; object-oriented engines behind stable interfaces (`AnalisadorMargem` facade, `Cenario`/`RegraDeteccao` class hierarchies); honest README separating implemented (✅ tests + CI) from roadmap (⬜).

```bash
python examples/exemplo_diagnostico.py       # zero dependencies, fully offline
pytest                                        # 78 tests, 96% coverage
streamlit run app.py                          # dashboard
uvicorn carchuna.api.main:app --reload        # FastAPI + Pydantic, /docs
```

> ℹ️ Concept / portfolio project — not a company, not legal or accounting advice.

## 📄 Licença

[MIT](LICENSE) — © 2026 Roberto Chiocca
