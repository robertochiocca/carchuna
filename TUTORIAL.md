# Tutorial da Carchuna — do zero absoluto ao seu raio-X de margem

Este guia é para quem **nunca programou** e quer usar a Carchuna no próprio
computador. Sem pressa: são uns 20 minutos na primeira vez. Se algo der errado,
veja a seção [Problemas comuns](#problemas-comuns) no final.

> A Carchuna roda **no seu computador**: suas vendas não são enviadas para
> nenhum servidor. E lembre — ela informa e calcula, mas **não substitui o seu
> contador**.

---

## Parte 1 — Preparar o computador (só na primeira vez)

### 1. Instalar o Python

O Python é a linguagem em que a Carchuna é feita — instalar é como instalar
qualquer programa.

**Windows**
1. Acesse [python.org/downloads](https://www.python.org/downloads/) e clique no
   botão amarelo **Download Python 3.x**.
2. Abra o arquivo baixado. **IMPORTANTE:** na primeira tela, marque a caixinha
   **"Add Python to PATH"** antes de clicar em *Install Now*. (Se esquecer,
   desinstale e instale de novo — é o erro nº 1 de iniciantes.)

**Mac**
1. Mesmo site, botão **Download Python 3.x**, abra o `.pkg` e siga o instalador.

Para conferir: abra o **Prompt de Comando** (Windows: tecla ⊞, digite `cmd`,
Enter) ou o **Terminal** (Mac: ⌘+espaço, digite `terminal`) e digite:

```
python --version
```

Se aparecer algo como `Python 3.12.x`, deu certo. (No Mac, se não funcionar,
tente `python3 --version` — e use `python3`/`pip3` no resto do guia.)

### 2. Baixar a Carchuna

**Sem instalar nada a mais (mais fácil):**
1. Acesse [github.com/robertochiocca/carchuna](https://github.com/robertochiocca/carchuna).
2. Clique no botão verde **Code** → **Download ZIP**.
3. Descompacte o ZIP em um lugar fácil, por exemplo `C:\carchuna` (Windows) ou
   a pasta Documentos (Mac).

### 3. Instalar as dependências

No Prompt/Terminal, entre na pasta e instale (copie e cole, uma linha por vez):

```
cd C:\carchuna
pip install -r requirements.txt
```

(No Mac: `cd ~/Documents/carchuna` — ajuste para onde você descompactou.)
A instalação demora alguns minutos na primeira vez. Mensagens amarelas são
normais; só as vermelhas indicam problema.

---

## Parte 2 — Abrir o app

Ainda no Prompt/Terminal, dentro da pasta da Carchuna:

```
streamlit run app.py
```

O navegador abre sozinho com o painel (se não abrir, acesse
[http://localhost:8501](http://localhost:8501)). Para **fechar** o app, volte ao
Prompt/Terminal e aperte `Ctrl+C`.

Na primeira vez, o app já vem carregado com **dados de demonstração** (vendas
inventadas, mas realistas) — explore as 7 abas antes de colocar os seus dados:

| Aba | O que mostra |
|---|---|
| **Resumo** | o essencial em uma tela: quanto faturou, quanto sobrou de verdade, para onde foi o dinheiro e as 3 ações mais valiosas |
| **Vendas e Produtos** | campeões de margem ("venda mais destes"), produtos que dão prejuízo ("reprecifique"), tabela por produto e por canal |
| **Histórico** | a evolução mês a mês, com comparação do último mês contra o anterior em uma frase simples |
| **E se…?** | testes de estresse: "e se a comissão subir 2 pontos?", "e se as devoluções dobrarem?" |
| **Crescer** | como faturar mais: o canal onde cada real rende mais, a calculadora de preço certo e quanto cabe crescer no Simples |
| **Diagnóstico Legal** | vazamentos detectados com a lei correspondente citada (e link oficial) |
| **Relatório** | um PDF de 3 páginas para levar ao seu contador |

---

## Parte 3 — Usar as SUAS vendas

### 1. Monte a planilha

A Carchuna lê um arquivo com **uma linha por venda**. Há um modelo pronto em
[`examples/vendas_exemplo.csv`](examples/vendas_exemplo.csv) — abra no Excel,
apague as linhas de exemplo e preencha com as suas vendas.

As colunas (as 5 primeiras são obrigatórias):

| Coluna | O que é | Exemplo |
|---|---|---|
| `data` | dia da venda, formato ano-mês-dia | `2026-05-02` |
| `produto` | nome do produto (opcional, mas habilita o ranking de campeões e vilões de margem) | `Fone bluetooth` |
| `canal` | onde vendeu: `mercado_livre`, `shopee`, `amazon`, `loja_propria` ou `fisico` | `shopee` |
| `valor_bruto` | preço que o cliente pagou | `129,90` |
| `custo_produto` | quanto o produto custou para você | `70,00` |
| `frete_pago` | frete que saiu do seu bolso (0 se nenhum) | `14,00` |
| `devolvida` | a venda foi devolvida? `sim` ou `nao` | `nao` |
| `prazo_recebimento_dias` | em quantos dias o dinheiro cai na conta | `15` |
| `comissao_cobrada` | comissão que o canal cobrou nesta venda (do extrato de repasse); deixe vazio para usar a tabela padrão | `18,19` |

Pode usar vírgula nos valores (`129,90`) — a Carchuna entende o formato
brasileiro. Salve como **CSV** (no Excel: *Salvar como → CSV UTF-8*) ou até
como `.xlsx` mesmo. **PDF** também funciona, desde que o arquivo traga uma
tabela com essas mesmas colunas (é um suporte beta — se não funcionar com o
seu relatório, exporte como CSV/Excel).

**De onde tirar os dados?** Todo marketplace exporta relatório de vendas:
- **Shopee**: Central do Vendedor → Meus Dados → Exportar relatório de pedidos;
- **Mercado Livre**: Vendas → baixar relatório (Excel);
- **Amazon**: Seller Central → Relatórios → Pagamentos/Pedidos.

As colunas vêm com outros nomes — copie para o modelo da Carchuna. (Conexão
automática com as APIs dos canais está no roadmap; hoje o caminho é a
exportação manual, que funciona para qualquer canal.)

### 2. Importe no app

Na barra lateral esquerda, no passo **1 · Suas vendas**, clique em **Browse
files** e escolha o seu arquivo. Pronto — todas as abas passam a usar as suas
vendas.

**Modo tempo real** (app rodando no seu computador): em *Acompanhar um
arquivo em tempo real*, cole o caminho da sua planilha (ex.:
`C:\vendas\maio.xlsx`) e ligue a chave. Toda vez que você salvar o arquivo
no Excel, os números do painel se atualizam sozinhos em poucos segundos.

### 3. Configure a tributação (pergunte ao contador se tiver dúvida)

Também na barra lateral:

- **Regime**: `SIMPLES` (a maioria) ou `MEI`;
- **Anexo do Simples**: revenda de mercadoria é o Anexo I, indústria o II,
  serviços do III ao V — *o seu contador sabe o seu*;
- **RBT12**: quanto sua empresa faturou nos últimos 12 meses — está no
  PGDAS-D/extrato do Simples que o contador emite todo mês;
- **Custos**: a taxa da sua maquininha e da antecipação — estão no contrato ou
  no app da adquirente.

### 4. Leia os resultados do jeito certo

- **Margem "anunciada" vs. margem real** — a anunciada é a conta ingênua
  (receita − custo do produto); a real desconta impostos, comissões,
  maquininha, antecipação, frete e devoluções. A diferença entre as duas é a
  **perda de margem**, e o app diz de onde ela veio.
- Cada número tem uma etiqueta de **confiança**: `calculado` (sai dos seus
  dados e da lei) ou `estimado` (usa uma tabela padrão editável — troque pelos
  números do seu contrato para virar `calculado`).
- O **Diagnóstico Legal aponta indícios, não certezas**: "há indício, com base
  no art. X — leve ao seu contador". Desconfie de quem promete "recuperar
  R$ X de impostos" sem análise: esse mercado é cheio de golpes.

---

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `'python' não é reconhecido...` | Python sem PATH | Reinstale marcando **Add Python to PATH** |
| `'streamlit' não é reconhecido...` | dependências não instaladas | Rode `pip install -r requirements.txt` na pasta certa |
| "colunas obrigatórias vazias" ao importar | faltou coluna ou linha em branco | Confira os nomes das colunas contra a tabela acima |
| "não é um valor monetário válido" | texto no meio dos números (ex.: "R$" com espaço estranho) | Deixe só números: `129,90` |
| `canal 'xyz' inválido` | nome de canal fora da lista | Use exatamente: `mercado_livre`, `shopee`, `amazon`, `loja_propria`, `fisico` |
| App abre em branco | navegador bloqueou | Acesse manualmente http://localhost:8501 |

Ficou preso? Abra uma *issue* no
[GitHub](https://github.com/robertochiocca/carchuna/issues) descrevendo o que
apareceu na tela.

---

> **Aviso**: a Carchuna é um projeto de portfólio e uma ferramenta de
> informação. Nenhum resultado é parecer jurídico ou contábil, nem promessa de
> recuperação de valores. Confirme com seu contador ou advogado antes de agir.
