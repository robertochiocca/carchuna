# Política de segurança

## O que a Carchuna é, para efeito de segurança

Projeto de portfólio, sem empresa por trás e sem SLA. O dashboard em
`carchuna.streamlit.app` é público e **não tem login**; a API `/api/v1` é
stateless e **não tem autenticação**. Nada é armazenado: nem conta, nem sessão,
nem o arquivo que você sobe — a análise acontece na requisição e some com ela.

Isso define o que faz sentido reportar. Não há dados de outro usuário para
vazar, nem privilégio para escalar, nem dinheiro para desviar. O que existe é a
disponibilidade do app público, a integridade dos números calculados, a
integridade do corpus legal, e uma credencial de API opcional no ambiente de
deploy.

**Não use a Carchuna como sistema de registro contábil.** Ela não substitui o
seu contador nem o PGDAS-D, e o próprio README diz onde cada número foi
conferido e onde não foi.

## Escopo

**Está no escopo:**

- Ingestão de arquivo hostil (CSV, JSON, XLSX, PDF) — parser, tetos, expansão.
- A fronteira da API: corpo malformado, payload grande, limite de chamadas.
- Vazamento de informação por mensagem de erro.
- O pipeline: workflows, permissões, dependências.
- Qualquer caminho que leve a credencial a aparecer em log, tela ou resposta.

**Está fora do escopo:**

- Ausência de autenticação, autorização, MFA ou controle de sessão — não há
  usuários na v1, e isso é desenho declarado, não descuido. Quando auth e
  persistência entrarem, os requisitos prévios já estão escritos em
  `docs/auditoria-seguranca.md`, seção 7b.
- Achados de banco de dados, ORM, SQL, JWT, cookies próprios ou CORS: nada
  disso existe no código.
- Relatório de scanner sem prova de exploração no código deste repositório.
- Falta de rate limit por IP contra abuso **distribuído**: a barreira existente
  é por processo e por IP, e o que ela não alcança está escrito em
  `carchuna/api/limite.py`.

## Como reportar

Abra uma **issue privada de segurança** pelo GitHub Security Advisories do
repositório (`Security` → `Report a vulnerability`). Se não conseguir, abra uma
issue pública **sem detalhe de exploração** pedindo um canal.

Inclua, se possível: o caminho de ataque, o arquivo e a linha, e o menor
exemplo que reproduz. Um arquivo de duas linhas vale mais que um parágrafo.

**Não** inclua dados reais de nenhum lojista. Se o seu caso precisa de um
arquivo de vendas, anonimize antes — e mande o formato, não o conteúdo.

## O que você pode esperar

Resposta em até 7 dias. Não há programa de recompensa; não há dinheiro
envolvido neste projeto em nenhuma direção.

Se o relato proceder, a correção vem com teste que reproduz o ataque, e o
`docs/auditoria-seguranca.md` é atualizado com o achado, a correção e o que
**continua** em risco. Este projeto publica o que não conseguiu resolver junto
com o que resolveu.

## Divulgação

Prefiro divulgação coordenada: corrijo, publico a correção, e o relato vira
público depois. Como não há usuário instalado e o deploy é contínuo a cada
push na `main`, a janela entre corrigir e publicar é curta por construção.

Se você já publicou antes de me avisar, tudo bem — me mande o link e eu trato
como qualquer outro relato.

## O que já foi auditado

`docs/auditoria-seguranca.md` traz a auditoria da v1: o que foi verificado, o
que foi achado, o que foi corrigido, **o que não pôde ser verificado** e o que
continua em risco. Ela não diz que a Carchuna está segura, e este arquivo
também não.
