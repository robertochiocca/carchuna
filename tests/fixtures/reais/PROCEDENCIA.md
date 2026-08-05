# Procedência destas fixtures — leia antes de confiar nelas

**Estes arquivos NÃO são exports de um lojista real.** São reconstruções da
*forma* dos relatórios, escritas à mão para os testes de ingestão. O que foi
reproduzido é a bagunça estrutural que derruba um importador:

| O que a fixture reproduz | Shopee | Mercado Livre |
|---|---|---|
| Encoding | cp1252 (Excel em português) | UTF-8 com BOM |
| Linhas de título antes do cabeçalho | 4 + linha em branco | 2 + linha em branco |
| Separador | `;` | `,` com decimais entre aspas |
| Decimal | vírgula (`89,90`) | vírgula entre aspas (`"249,90"`) |
| Data | `01/05/2026` | `2026-05-02T14:32:07` |
| Caractere fora do latin-1 | travessão `–` no título | travessão `–` no título |
| Linha estragada | data vazia (pedido 2605050005) | valor `"ver detalhe"` (venda 2000000005) |
| Coluna de custo (CMV) | não existe | não existe |
| Coluna de canal | não existe | não existe |

As duas últimas linhas da tabela não são defeito da fixture: **nenhum
marketplace conhece o custo do produto do lojista**, e um relatório de um canal
só não traz coluna de canal. É por isso que o fluxo do dashboard passa pelo
mapeador de colunas, onde o lojista fixa o canal e aponta de onde vem o custo.

## Os nomes das colunas são palpites, não transcrição oficial

Os cabeçalhos (`Preço acordado`, `Receita por produtos (BRL)`, `Custo do envio
(BRL)`…) foram escritos a partir dos nomes que costumam aparecer nesses
relatórios. **Não foram conferidos contra documentação oficial da Shopee nem do
Mercado Livre**, e os painéis mudam rótulo sem aviso. Eles servem para testar o
importador contra a *forma* do problema, não para afirmar como o relatório de
2026 se chama.

## Ação pendente (só um humano pode fazer)

Substituir os dois arquivos por um export **de verdade**, baixado do painel por
um lojista, com os dados anonimizados. Enquanto isso não acontece, o teste
`tests/test_fixtures_reais.py` prova que o importador aguenta a forma — não que
ele aguenta o arquivo que a Shopee gera hoje.
