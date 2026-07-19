<div align="center">

# 🏖️ Carchuna

**O raio-X da margem para o PME brasileiro. Você fatura 400; a Carchuna mostra, com prova, por que sobra 8 — e o que a lei permite recuperar.**

*(Como a praia de Carchuna, na costa de Granada: águas transparentes onde se vê o fundo.)*

[![CI](https://github.com/robertochiocca/carchuna/actions/workflows/ci.yml/badge.svg)](https://github.com/robertochiocca/carchuna/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Testes](https://img.shields.io/badge/testes-65%2F65-brightgreen.svg)](tests/)
[![Cobertura](https://img.shields.io/badge/cobertura-95%25-brightgreen.svg)](.github/workflows/ci.yml)
[![Código: black](https://img.shields.io/badge/c%C3%B3digo-black-000000.svg)](https://github.com/psf/black)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green.svg)](LICENSE)

🇧🇷 [Português](#-o-problema) · 🇺🇸 [English](#-english-version)

</div>

> ℹ️ **Conceito / projeto de portfólio — não é uma empresa nem aconselhamento jurídico/contábil.** Este repositório estuda como uma plataforma de diagnóstico de margem para PMEs brasileiras *poderia* funcionar. O que está implementado tem teste e CI; o que não está é roadmap explicitamente sinalizado.

---

## 🎯 O problema

O CNPJ brasileiro típico deste estudo fatura **~R$ 400 mil/mês e lucra ~2% disso**. Vende em marketplaces (Mercado Livre, Shopee, Amazon), usa maquininha, antecipa recebíveis, está no Simples Nacional — e **não sabe exatamente onde a margem morre**. Não pode pagar CFO (R$ 15–30 mil/mês) nem tributarista por hora.

A **Carchuna** é a terceira plataforma de uma trilogia andaluza de projetos de portfólio:

| Projeto | Público | Motor |
|---|---|---|
| ⚡ [Calahonda](https://github.com/robertochiocca/calahonda) | gestoras/investidores | quant (VaR, stress, otimização) |
| ⚖️ [DireitoAberto](https://github.com/robertochiocca/direitoaberto) | cidadão comum | legal (RAG com fonte citada) |
| 🏖️ **Carchuna** | **PME que fatura muito e lucra pouco** | **os dois, casados** |

## 🧬 DNA da trilogia (inegociável)

1. **Nenhuma afirmação sem lastro** — toda saída ou é calculada por código testado, ou é citada de fonte oficial com link. A IA nunca inventa.
2. **Degradação graciosa** — funciona de ponta a ponta **sem chave de API**: cálculo local + modo extrativo.
3. **PT-BR do lojista** — "maquininha" → adquirência, "antecipar" → antecipação de recebíveis, "ML" → Mercado Livre.
4. **Honestidade técnica** — a tabela de status abaixo separa o implementado do roadmap; dispositivos legais entram com `"revisado": false` até revisão humana.
5. **Camadas trocáveis** — motores atrás de interfaces estáveis (padrão `Retriever` do DireitoAberto).
6. **Dinheiro é `Decimal`** — `float` em campo monetário é rejeitado com `TypeError`, sem exceção.

## 📊 Status honesto (o que existe vs. roadmap)

| Módulo | Status |
|---|---|
| `margem.py` — decomposição da margem com alíquota efetiva do Simples (fórmula do art. 18, § 1º-A, LC 123/2006; Anexos I–V) | ✅ implementado e testado |
| `dados.py` — importação CSV/JSON/XLSX (vírgula decimal BR) + dados sintéticos reprodutíveis | ✅ implementado e testado |
| `metricas.py` — margem mês a mês, maior queda, instabilidade, lucro acumulado | ✅ implementado e testado |
| `cenarios.py` — comissão +2 p.p., Selic +3 p.p., devoluções dobram, mudança de anexo | ✅ implementado e testado |
| `rag/` — BM25 + sinônimos do lojista + LLM opcional com fallback extrativo | ✅ implementado e testado |
| `data/corpus_pme.json` — 21 dispositivos (LC 123, CDC, CTN, Bacen, LGPD…) | ✅ ingerido · ⚠️ **revisão humana pendente** (`revisado: false`) |
| `diagnostico.py` — 4 regras transparentes gerando achados com base legal | ✅ implementado e testado |
| `relatorio.py` — PDF de 3 páginas (raio-X, cenários, achados) | ✅ implementado e testado |
| `app.py` — dashboard Streamlit com 5 abas | ✅ implementado (sem teste automatizado de UI) |
| Regime **Lucro Presumido** | ⬜ roadmap (depende de ICMS/ISS estaduais/municipais) |
| RBT12 móvel mês a mês nas séries | ⬜ roadmap |
| API FastAPI pública (`/api/v1`) | ⬜ roadmap |
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
pip install pytest && pytest          # 65 testes

# Dashboard completo
pip install -r requirements.txt
streamlit run app.py
```

Saída real do exemplo (6 meses sintéticos, Anexo I, RBT12 R$ 4,2 mi):

```
=== Raio-X da margem (6 meses sintéticos) ===
Receita bruta   : R$   2,918,696.00
(-) tributos        : R$     282,526.10  (  9.68%)  [calculado]
(-) comissoes_canal : R$     291,714.61  (  9.99%)  [estimado]
(-) adquirencia     : R$      11,744.76  (  0.40%)  [estimado]
(-) antecipacao     : R$       9,980.18  (  0.34%)  [estimado]
(-) frete           : R$     143,692.00  (  4.92%)  [calculado]
(-) devolucoes      : R$      93,435.00  (  3.20%)  [calculado]
(-) cmv             : R$   1,695,709.91  ( 58.10%)  [calculado]
(=) margem líquida: R$     389,893.44  (13.36%)
Alíquota efetiva do Simples: 10.0000%
```

Com `ANTHROPIC_API_KEY` configurada, as respostas do diagnóstico ganham narrativa em linguagem natural (API da Anthropic); **sem chave, tudo funciona em modo extrativo** — o cálculo nunca depende de LLM.

## 🔍 Como cada número ganha lastro

- **Tributos**: fórmula oficial da alíquota efetiva (LC 123/2006, art. 18, § 1º-A) com os Anexos I–V na redação da LC 155/2016, validada por testes calculados à mão — inclusive o degrau da 6ª faixa, em que o ICMS/ISS saem da guia pelo sublimite (arts. 19 e 20). A conferência automática no Planalto foi tentada em 19/07/2026 (portal retornou HTTP 503 a robôs); a data e a ressalva estão documentadas em `carchuna/margem.py`.
- **Comissões/adquirência/antecipação**: tabelas **editáveis pelo usuário**, com defaults documentados com fonte e marcados `estimado` — o seu contrato prevalece.
- **Invariante contábil testado**: soma das deduções + margem líquida == receita bruta, centavo a centavo.
- **Base legal dos achados**: apenas o que o `Retriever` recuperou do corpus versionado — com link oficial e status de revisão em cada citação.
- **Excel**: células numéricas chegam como `float` do openpyxl; a conversão passa por `str()` e esta é a única exceção documentada à regra do `Decimal` — prefira CSV.

## 🚫 O que a Carchuna **não** é (anti-escopo)

Não é ERP (não emite nota, não controla estoque); **não dá parecer jurídico nem promete recuperação tributária** ("você tem direito a R$ X de volta" — nunca; esse mercado é infestado de golpes de "teses"); não é a Calahonda (sem VaR/carteira); não importa o corpus B2C do DireitoAberto; sem ML preditivo, score de crédito ou decisão financeira automatizada na v1; sem armazenar credenciais bancárias; sem scraping de portais que bloqueiam robôs.

## 🧪 Qualidade

`pytest` (65 testes, cobertura 95%, mínimo 85% no CI) · `ruff` · `black` · GitHub Actions em Python 3.10, 3.11 e 3.12. Padrão de teste: casos validados contra cálculo manual (o "VaR ≈ 1.645σ" daqui é a alíquota do Simples conferida à mão).

**Stack:** Python 3.10+ (núcleo sem dependências) · Streamlit · matplotlib · pytest

---

## 🇺🇸 English version

**Carchuna** — a verifiable margin X-ray for Brazilian SMBs: it decomposes where profit dies (taxes, marketplace fees, card acquiring, receivables prepayment, freight, returns, COGS) with tested code, and points to legal remedies with cited official sources. Fintech + legaltech for high-revenue, low-margin sellers; third project of an Andalusian trilogy ([Calahonda](https://github.com/robertochiocca/calahonda) → quant, [DireitoAberto](https://github.com/robertochiocca/direitoaberto) → legal RAG).

Core principles: every output is either computed by tested code or cited from an official source with a link; graceful degradation (fully functional without any API key); money is `Decimal`, never `float`; legal corpus entries ship with `"revisado": false` until human review; honest README separating implemented (✅ tests + CI) from roadmap (⬜).

```bash
python examples/exemplo_diagnostico.py   # zero dependencies, fully offline
pytest                                    # 65 tests, 95% coverage
streamlit run app.py                      # full dashboard (pip install -r requirements.txt)
```

> ℹ️ Concept / portfolio project — not a company, not legal or accounting advice.

## 📄 Licença

[MIT](LICENSE) — © 2026 Roberto Chiocca
