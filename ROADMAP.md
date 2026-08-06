# Roadmap

O que ainda não está pronto, por que não está, e o que precisa acontecer para destravar.

A regra da casa vale aqui também: item que depende de número que eu não conferi em fonte
oficial não sai do papel. Prefiro a fila curta e honesta a uma lista de intenções.

## Fila

| P | Item | Estado | Bloqueio |
|---|------|--------|----------|
| P4 | Lucro Presumido atrás de flag | bloqueado | cada alíquota de ICMS/ISS depende do estado e do município, e não conferi nenhuma em fonte oficial |
| P5 | Conector Shopee API | bloqueado por humano | app aprovado na Open Platform + OAuth do lojista |
| P5 | Conector Mercado Livre API | bloqueado por humano | app registrado + OAuth do lojista |
| P5 | Open Finance via agregador (Pluggy/Belvo) | bloqueado por humano | contrato e credenciais do agregador |
| P6 | Persistência e autenticação da API | roadmap | só faz sentido quando houver piloto multiusuário |

Não há nada em P0 nem em P1. O que sobrou na fila está todo travado em alguma coisa que não
se resolve escrevendo código — e, enquanto nenhum desses bloqueios cair, mexer aqui seria
reescrever o que já funciona.

## O que destrava cada coisa, na ordem de quem chega primeiro

1. **Export real de um lojista.** Substitui `tests/fixtures/reais/` por dados de verdade. É o
   item que provavelmente revela ingestão que ainda não aguenta — as fixtures de hoje
   reproduzem a forma do relatório, não um arquivo capturado.
2. **Credencial OAuth de Shopee ou de Mercado Livre.** Tira os dois conectores do bloqueio. A
   interface `Conector` e o `ConectorArquivo` já existem e são testados; falta só a
   implementação concreta de cada canal.
3. **Revisão jurídica do corpus.** Os 21 dispositivos de `data/corpus_pme.json` saem de
   `revisado: false`.
4. **Alíquotas de ICMS/ISS conferidas em fonte oficial.** Destrava o Lucro Presumido.

## Bloqueados por humano — o que depende de mim

- Registrar o app na Shopee Open Platform e no Mercado Livre e obter as credenciais OAuth.
- Conferir os 21 dispositivos de `data/corpus_pme.json` na fonte oficial e virar
  `revisado: true`. **Ainda não conferi nenhum**, e por isso o corpus segue marcado como não
  revisado no próprio arquivo.
- Conseguir 1 lojista piloto e trocar `tests/fixtures/reais/` por um export de verdade,
  anonimizado. O `PROCEDENCIA.md` ao lado das fixtures declara que elas não são exports reais
  e que os nomes das colunas são palpites meus.
- Conferir os valores dos Anexos do Simples no Planalto antes de qualquer uso real. Tentei
  buscar o texto fora do navegador e recebi HTTP 503 nas duas vezes; num navegador comum a
  página abre normalmente:
  <https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm>
- Conferir na fonte oficial a leitura do art. 18, § 1º que usei na RBT12 móvel — a de que o
  período de apuração é tributado pela receita dos doze meses anteriores a ele. Tentei por
  duas rotas e as duas estão fechadas fora do navegador: o Planalto devolveu HTTP 503 e o
  portal de normas da Receita (Resolução CGSN 140/2018) devolveu HTTP 403, com e sem
  cabeçalhos de navegador. As duas abrem normalmente no navegador:
  <https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm> (art. 18, § 1º) e
  <https://normasinternet2.receita.fazenda.gov.br/#/consulta/externa/92278> (RCGSN 140/2018).
