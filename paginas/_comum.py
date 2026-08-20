"""Textos, rótulos e formatadores da interface — sem estado e sem tela.

Extraído do `app.py` sem alteração de comportamento: as funções e os
dicionários abaixo são os mesmos, movidos para que as sete páginas os
importem em vez de dependerem de um arquivo de 2.178 linhas.

Nada aqui desenha widget nem lê `session_state`. É a camada que as
páginas podem chamar sem ordem imposta.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from carchuna.dados import decimal_de_texto
from carchuna.metricas import procedencia_rbt12

ROTULOS_EN = {
    "tributos": "Taxes (Simples/MEI)",
    "comissoes_canal": "Marketplace commissions",
    "adquirencia": "Card machine fees",
    "antecipacao": "Early-payment cost",
    "frete": "Shipping",
    "devolucoes": "Returns",
    "cmv": "Product cost",
}

ROTULOS_SIMPLES_PT = {
    "tributos": "Impostos",
    "comissoes_canal": "Comissões dos marketplaces",
    "adquirencia": "Taxa da maquininha",
    "antecipacao": "Custo de antecipar",
    "frete": "Frete",
    "devolucoes": "Devoluções",
    "cmv": "Custo dos produtos",
}

ATIVIDADES = {
    "pt": {
        "comercio": "Comércio (revenda de produtos)",
        "industria": "Indústria (fabricação própria)",
        "servicos": "Serviços",
    },
    "en": {
        "comercio": "Commerce (product resale)",
        "industria": "Industry (own manufacturing)",
        "servicos": "Services",
    },
}


# ---------------------------------------------------------------------------
# Textos da interface (PT/EN). Saídas dos motores permanecem em PT.
# ---------------------------------------------------------------------------

T = {
    "pt": {
        "titulo": "Carchuna — o raio-X da margem",
        "subtitulo": (
            "Descubra quanto sobra DE VERDADE de cada venda — e o que fazer "
            "para sobrar mais. Projeto de portfólio; não é aconselhamento "
            "jurídico/contábil."
        ),
        "nota_motor": "",
        "passo1": "1 · Suas vendas",
        "upload": "Planilha de vendas (CSV, Excel, JSON ou PDF)",
        "upload_ajuda": (
            "Uma linha por venda. Colunas: data, canal, valor_bruto, "
            "custo_produto, frete_pago (opcionais: produto, devolvida, "
            "prazo_recebimento_dias, comissao_cobrada). Há um modelo "
            "pronto no tutorial do projeto. PDF: funciona quando o "
            "arquivo traz uma tabela com essas mesmas colunas. "
            "Privacidade: no app rodando no seu computador, o arquivo "
            "não sai dele; na versão hospedada (carchuna.streamlit.app), "
            "ele é processado no servidor do Streamlit durante a sessão "
            "e não é armazenado pela Carchuna."
        ),
        "mapa_sidebar": (
            "Seu arquivo veio com nomes de coluna diferentes do modelo — "
            "sem problema: aponte abaixo qual coluna é qual."
        ),
        "mapa_caption": (
            "A Carchuna já chutou o que reconheceu; confira e complete "
            "os campos com • (obrigatórios)."
        ),
        "mapa_incompleto": "Falta apontar: {campos}.",
        "opcao_nenhuma": "— (não tem no arquivo)",
        "opcao_zero": "(usar zero para todas)",
        "opcao_nao": "(nenhuma foi devolvida)",
        "opcao_fixo": "(tudo veio de:",
        "mapa_campos": {
            "data": "Data da venda •",
            "canal": "Canal de venda •",
            "valor_bruto": "Preço pago pelo cliente •",
            "custo_produto": "Custo do produto •",
            "frete_pago": "Frete pago por você •",
            "produto": "Nome do produto",
            "devolvida": "Foi devolvida?",
            "prazo_recebimento_dias": "Prazo de recebimento (dias)",
            "comissao_cobrada": "Comissão cobrada pelo canal",
        },
        "tempo_real": "Acompanhar um arquivo em tempo real",
        "tempo_real_ajuda": (
            "Aponte para um arquivo no SEU computador (funciona com o app "
            "rodando localmente). Toda vez que você salvar a planilha, os "
            "números daqui se atualizam sozinhos em alguns segundos."
        ),
        "caminho_arquivo": "Caminho do arquivo (ex.: C:\\vendas\\maio.xlsx)",
        "falha_arquivo": (
            "Não consegui abrir esse arquivo. Confira o caminho, se o "
            "arquivo existe e se você tem permissão para lê-lo."
        ),
        "caminho_desligado": (
            "Este recurso lê um arquivo do disco da máquina onde a Carchuna "
            "está rodando, então ele vem desligado e só faz sentido no seu "
            "computador. Para ligar, rode a Carchuna localmente com "
            "`CARCHUNA_LER_CAMINHO=1`. Nesta instância, use o campo de "
            "upload acima."
        ),
        "monitorar": "Atualizar sozinho quando o arquivo mudar",
        "monitorando": "Acompanhando o arquivo — salve a planilha e veja aqui.",
        "importadas": "vendas importadas.",
        "falha_importacao": "Não consegui ler o arquivo:",
        "percentual_invalido": (
            "Não entendi o valor de '{campo}': {valor}. Digite só o "
            "número, com vírgula nos centavos (ex.: 2,49)."
        ),
        "linhas_de_fora": (
            "{ok} vendas importadas. {fora} de {total} linhas ficaram de fora "
            "e não entram em nenhum número desta tela — veja quais abaixo."
        ),
        "ver_de_fora": "Ver as linhas que ficaram de fora",
        "col_linha": "Linha na sua planilha",
        "col_motivo": "Por que ficou de fora",
        "meses_demo": "Meses de dados de exemplo",
        "aviso_demo": (
            "Você está vendo DADOS DE EXEMPLO. Envie sua planilha na barra "
            "lateral para ver os seus números."
        ),
        "passo2": "2 · Seus impostos",
        "regime": "Regime tributário",
        "regime_ajuda": (
            "A maioria das lojas está no Simples Nacional. Se você é "
            "microempreendedor individual, escolha MEI. Na dúvida, "
            "pergunte ao seu contador."
        ),
        "anexo": "Anexo do Simples",
        "anexo_ajuda": (
            "Revenda de produtos = Anexo I. Fabricação própria = Anexo II. "
            "Serviços = III a V. Seu contador sabe o seu."
        ),
        "rbt12": "Faturamento dos últimos 12 meses (R$)",
        "rbt12_movel": "Calcular a alíquota mês a mês (RBT12 móvel)",
        "rbt12_movel_ajuda": (
            "No Simples a alíquota de cada mês sai do faturamento dos 12 "
            "meses ANTERIORES a ele (LC 123/2006, art. 18, § 1º) — quem "
            "cresceu paga mais no fim do ano. Só é possível nos meses em "
            "que o seu arquivo cobre esses 12 meses inteiros; nos outros "
            "vale o valor que você informou acima."
        ),
        "rbt12_movel_aplicada": (
            "Alíquota calculada do próprio arquivo em {n} de {total} meses; "
            "nos demais vale o faturamento que você informou."
        ),
        "rbt12_movel_sem_janela": (
            "O seu arquivo ainda não cobre 12 meses anteriores a nenhum mês, "
            "então a alíquota de todos eles vem do valor informado acima. "
            "Com 13 meses de histórico este cálculo liga sozinho."
        ),
        "rbt12_lacuna": (
            "{meses} sem lançamentos. Foi mês sem faturamento ou o arquivo "
            "está incompleto?"
        ),
        "rbt12_lacuna_confirmar": "Foram meses sem faturamento (venda zero)",
        "rbt12_lacuna_ajuda": (
            "Enquanto você não confirma, a Carchuna não usa a RBT12 do seu "
            "arquivo nos meses afetados: um mês vazio pode ser venda zero ou "
            "dado que não veio na exportação, e as duas leituras dão "
            "alíquotas diferentes. Sem confirmação vale o faturamento que "
            "você informou acima, que é o lado seguro — RBT12 menor do que a "
            "real geraria alíquota menor e imposto a menos."
        ),
        "rbt12_lacuna_confirmada": (
            "Meses vazios confirmados como venda zero: a alíquota deles "
            "passa a sair do próprio arquivo."
        ),
        "meses_do_ano": (
            "Janeiro",
            "Fevereiro",
            "Março",
            "Abril",
            "Maio",
            "Junho",
            "Julho",
            "Agosto",
            "Setembro",
            "Outubro",
            "Novembro",
            "Dezembro",
        ),
        "narrativa_indisponivel": "Narrativa indisponível: {motivo}",
        "rbt12_ajuda": (
            "Soma de tudo que a empresa faturou nos últimos 12 meses "
            "(o 'RBT12'). Está no extrato do Simples (PGDAS-D) que o "
            "contador emite todo mês. Define a sua alíquota.\n\n"
            "**Até R$ 3.600.000:** tudo no DAS, e a conta desta tela é o "
            "imposto todo.\n\n"
            "**De R$ 3.600.000 a R$ 4.320.000:** a conta sai, com aviso — "
            "a partir de janeiro do ano que vem você recolhe ICMS e/ou "
            "ISS por fora do DAS, pelas regras do seu Estado e do seu "
            "Município (LC 123/2006, art. 20, § 1º), e esse valor não "
            "está em nenhum número daqui.\n\n"
            "**Acima de R$ 4.320.000:** a Carchuna não calcula. O "
            "ICMS/ISS saem do DAS já no mês seguinte e a margem sairia "
            "para cima; estimar exigiria inventar alíquota de estado e "
            "de município."
        ),
        "das": "Valor mensal do boleto do MEI (R$)",
        "das_ajuda": "O DAS fixo que você paga todo mês.",
        "rbt12_sugerida": (
            "Sugerido a partir do seu arquivo (média mensal × 12). "
            "Confirme com o valor exato do extrato do Simples (PGDAS-D)."
        ),
        "passo3": "3 · Suas taxas",
        "taxa_adq": "Taxa da maquininha (%)",
        "taxa_adq_ajuda": (
            "Quanto a maquininha desconta de cada venda na loja própria ou "
            "física. Está no contrato ou no app da adquirente."
        ),
        "taxa_ant": "Taxa para receber antes (% ao mês)",
        "taxa_ant_ajuda": (
            "O juro que você paga quando antecipa o dinheiro das vendas a "
            "prazo em vez de esperar."
        ),
        "atividade": "Sua atividade",
        "abas": [
            "Resumo",
            "Vendas e Produtos",
            "Histórico",
            "E se…?",
            "Crescer",
            "Diagnóstico Legal",
            "Relatório",
        ],
        "faturou": "Você faturou",
        "sobrou": "Sobrou de verdade",
        "foi_embora": "Foi embora em custos e taxas",
        "para_onde": "Para onde foi o dinheiro",
        "acoes_titulo": "As ações mais valiosas agora",
        "acoes_caption": (
            "Calculadas dos seus números. Detalhes nas abas Diagnóstico "
            "Legal e Crescer."
        ),
        "por_mes": "mês",
        "como_ler": "Como ler estes números?",
        "como_ler_texto": (
            "**Margem 'de cabeça'** é a conta que todo lojista faz: preço "
            "menos custo do produto. **Margem real** desconta também "
            "impostos, comissões, maquininha, antecipação, frete e "
            "devoluções — é o que sobra de verdade. Cada número tem uma "
            "etiqueta: `calculado` sai dos seus dados e da lei; `estimado` "
            "usa uma taxa padrão editável na barra lateral — troque pela "
            "sua taxa real para ficar exato."
        ),
        "sem_acoes": "Nada urgente detectado — seus números parecem saudáveis.",
        "implausivel_titulo": "Estes números não fecham com a realidade.",
        "reconciliacao_titulo": "Os dois caminhos de cálculo não bateram.",
        "aviso_titulo": "A conta está feita, mas leia isto antes de usá-la.",
        "motor_falhou": "Esta parte não pôde ser calculada.",
        "motor_falhou_base": (
            "A decomposição da margem não rodou, e sem ela não há nada "
            "para as abas mostrarem."
        ),
        "wf_receita": "Faturamento",
        "cachoeira_dica": (
            "Toque numa barra de custo para abrir de onde ela vem — por "
            "canal e por mês. Duplo clique desfaz a seleção."
        ),
        "drill_titulo": "De onde vem: {rotulo}",
        "drill_por_canal": "Por canal",
        "drill_por_mes": "Por mês",
        "drill_sem_canal": (
            "O DAS do MEI é fixo por mês — dividi-lo por canal seria "
            "inventar número. A quebra por mês ao lado é a real."
        ),
        "radar_titulo": "Radar do CFO",
        "radar_caption": (
            "Sinais achados automaticamente nos seus números — cada um "
            "com o impacto em R$/mês, o método que o detectou e o que "
            "fazer a respeito."
        ),
        "radar_vazio": (
            "Nenhum sinal no radar — margens estáveis e sem vazamento "
            "novo entre os meses."
        ),
        "radar_sev": {
            "critico": "CRÍTICO",
            "atencao": "ATENÇÃO",
            "oportunidade": "OPORTUNIDADE",
        },
        "radar_esperado": "esperado",
        "radar_observado": "observado",
        "radar_metodo": "Como foi detectado:",
        "radar_aviso": (
            "Sinais calculados por regras transparentes, sem IA — são "
            "pistas para investigar com seu contador, não veredito."
        ),
        "lin_titulo": "De onde vem cada número?",
        "lin_caption": (
            "Escolha um número e veja o arquivo de origem, as colunas, a "
            "fórmula com os parâmetros do seu caso, as premissas e as "
            "limitações — rastreabilidade completa."
        ),
        "lin_numero": "Número",
        "lin_origem": "Fonte dos dados",
        "lin_colunas": "Colunas usadas",
        "lin_formula": "Cálculo",
        "lin_transf": "Transformações na importação",
        "lin_premissas": "Premissas",
        "lin_limitacoes": "Limitações",
        "lin_fonte": "Base legal / tabela",
        "lin_quando": "Calculado em",
        "conf_titulo": "Quanto dá para confiar nestes números?",
        "conf_nota": "Confiança da base: {pct}% ({nivel})",
        "conf_caption": (
            "A nota mede a sua BASE, não o cálculo: o cálculo é o mesmo "
            "sempre. Ela soma quatro componentes de rubrica fixa — "
            "evidência, histórico, amostra e campos preenchidos — e cada "
            "um diz o porquê da sua parcela."
        ),
        "vendas_metricas": ["Vendas", "Faturamento", "Canais", "Devoluções"],
        "campeoes": "Campeões de margem — venda mais destes",
        "campeoes_caption": (
            "Os produtos que mais deixam dinheiro no seu bolso, já " "descontando tudo."
        ),
        "cada_100": "de cada R$ 100 vendidos viram lucro",
        "viloes": "Atenção: estes dão prejuízo a cada venda",
        "viloes_caption": (
            "Depois de impostos, comissões e custos, estes produtos saem "
            "no vermelho. Suba o preço (calculadora na aba Crescer) ou "
            "tire do catálogo."
        ),
        "prejuizo_por_venda": "de prejuízo acumulado",
        "sem_viloes": "Nenhum produto dando prejuízo. Bom sinal.",
        "tabela_produtos": "Todos os produtos",
        "col_produto": "produto",
        "col_vendas": "vendas",
        "col_devolvidas": "devolvidas",
        "col_receita": "faturamento",
        "col_margem": "margem (R$)",
        "col_margem_pct": "margem %",
        "receita_por_canal": "Faturamento por canal",
        "todas_vendas": "Ver todas as vendas, uma a uma",
        "margem_por_venda": "Incluir a margem real de cada venda",
        "hist_caption": (
            "A evolução do seu negócio, mês a mês — calculada pelo mesmo "
            "motor das outras abas."
        ),
        "hist_um_mes": (
            "Sua planilha tem um mês só. Envie mais meses para ver a "
            "evolução e a comparação."
        ),
        "hist_receita": "Faturamento por mês",
        "hist_margem": "Margem % por mês",
        "hist_lucro": "Lucro acumulado",
        "hist_comparacao": "Último mês vs. anterior",
        "hist_frase_melhora": (
            "De {m1} para {m2}, sua margem foi de {a}% para {b}% "
            "(subiu {d} p.p.). O que mais mudou: {causa}, que foi de "
            "{ca}% para {cb}% do faturamento."
        ),
        "hist_frase_piora": (
            "De {m1} para {m2}, sua margem foi de {a}% para {b}% "
            "(caiu {d} p.p.). O que mais pesou: {causa}, que foi de "
            "{ca}% para {cb}% do faturamento."
        ),
        "hist_tabela": "Tabela mensal",
        "col_mes": "mês",
        "col_maior_custo": "maior custo",
        "baixar_hist": "Baixar histórico (CSV)",
        "delta_receita": "Faturamento",
        "delta_margem": "Margem (R$)",
        "delta_pp": "Margem (p.p.)",
        "ese_caption": (
            "Testes de estresse: o que acontece com o seu lucro se algo "
            "mudar amanhã? Cada caixa mostra a margem recalculada do zero "
            "pelo mesmo motor."
        ),
        "margem_cenario": "Margem no cenário",
        "impacto_reais": "Diferença (R$)",
        "impacto_pp": "Diferença (p.p.)",
        "crescimento_caption": (
            "Como faturar mais — com os seus números, não com promessa: "
            "onde cada real vendido rende mais, o preço certo e quanto "
            "cabe crescer dentro do Simples."
        ),
        "caminho": "O que fazer:",
        "simular_canal": "E se eu vendesse mais em um canal?",
        "canal": "Canal",
        "crescimento_vendas": "Vender a mais (%)",
        "margem_hoje": "Sua margem hoje",
        "ganho": "Você ganharia (R$)",
        "calculadora": "Descubra o preço certo",
        "calculadora_caption": (
            "Diga quanto o produto custa e quanto quer ganhar; a Carchuna "
            "diz por quanto vender — já contando imposto, comissão e taxas."
        ),
        "custo_produto": "Quanto o produto te custa (R$)",
        "frete": "Frete que você paga (R$)",
        "canal_venda": "Onde vai vender",
        "margem_alvo": "Quanto quer ganhar (%)",
        "preco_equilibrio": "Abaixo deste preço você PERDE dinheiro",
        "preco_para": "Venda por este preço para ganhar {pct}%",
        "diag_caption": (
            "Vazamentos detectados nos seus números, com a lei que "
            "sustenta cada um — para levar ao seu contador."
        ),
        "vazamentos": "O que encontramos",
        "sem_achados": "Nenhum vazamento detectado. Bom sinal.",
        "base_legal": "A lei que sustenta isto:",
        "pendente": " · _revisão humana pendente_",
        "conferido_em": " · _conferido em {data}_",
        "fonte_oficial": "fonte oficial",
        "pergunte": "Pergunte com suas palavras",
        "pergunta_exemplo": (
            "Ex.: 'a taxa da maquininha tá alta demais, posso trocar?'"
        ),
        "modo_extrativo": (
            "Resposta no modo básico (sem chave de IA) — sempre citando a "
            "lei e a fonte."
        ),
        "relatorio_caption": (
            "Um PDF de 3 páginas com o raio-X, os cenários e os achados — "
            "pronto para levar ao contador."
        ),
        "gerar_pdf": "Gerar relatório PDF",
        "baixar_pdf": "Baixar o relatório",
    },
    "en": {
        "titulo": "Carchuna — the margin X-ray",
        "subtitulo": (
            "Find out how much of each sale you REALLY keep — and what to "
            "do to keep more. Portfolio project; not legal or accounting "
            "advice."
        ),
        "nota_motor": (
            "Engine narratives (findings, opportunities, scenario names) "
            "are in Portuguese — the audience's language; the interface "
            "is bilingual."
        ),
        "passo1": "1 · Your sales",
        "upload": "Sales spreadsheet (CSV, Excel, JSON or PDF)",
        "upload_ajuda": (
            "One row per sale. Columns: data, canal, valor_bruto, "
            "custo_produto, frete_pago (optional: produto, devolvida, "
            "prazo_recebimento_dias, comissao_cobrada). PDF works when "
            "the file contains a table with these same columns. "
            "Privacy: running on your computer, the file never leaves "
            "it; on the hosted version (carchuna.streamlit.app) it is "
            "processed on Streamlit's server during the session and is "
            "not stored by Carchuna."
        ),
        "mapa_sidebar": (
            "Your file has different column names than the template — "
            "no problem: point out which column is which below."
        ),
        "mapa_caption": (
            "Carchuna guessed what it recognized; review and complete "
            "the fields marked • (required)."
        ),
        "mapa_incompleto": "Still missing: {campos}.",
        "opcao_nenhuma": "— (not in the file)",
        "opcao_zero": "(use zero for all)",
        "opcao_nao": "(none was returned)",
        "opcao_fixo": "(everything came from:",
        "mapa_campos": {
            "data": "Sale date •",
            "canal": "Sales channel •",
            "valor_bruto": "Price paid by the customer •",
            "custo_produto": "Product cost •",
            "frete_pago": "Shipping you paid •",
            "produto": "Product name",
            "devolvida": "Was it returned?",
            "prazo_recebimento_dias": "Days until payout",
            "comissao_cobrada": "Commission charged by the channel",
        },
        "tempo_real": "Watch a file in real time",
        "tempo_real_ajuda": (
            "Point to a file on YOUR computer (works with the app running "
            "locally). Every time you save the spreadsheet, the numbers "
            "here refresh by themselves within seconds."
        ),
        "caminho_arquivo": "File path (e.g.: C:\\sales\\may.xlsx)",
        "falha_arquivo": (
            "I could not open that file. Check the path, whether the file "
            "exists, and whether you have permission to read it."
        ),
        "caminho_desligado": (
            "This feature reads a file from the disk of the machine running "
            "Carchuna, so it ships disabled and only makes sense on your own "
            "computer. To enable it, run Carchuna locally with "
            "`CARCHUNA_LER_CAMINHO=1`. On this instance, use the upload "
            "field above."
        ),
        "monitorar": "Refresh automatically when the file changes",
        "monitorando": "Watching the file — save the spreadsheet and see it here.",
        "importadas": "sales imported.",
        "falha_importacao": "Could not read the file:",
        "percentual_invalido": (
            "I could not read '{campo}': {valor}. Type just the number, "
            "using a comma or dot for decimals (e.g. 2.49)."
        ),
        "linhas_de_fora": (
            "{ok} sales imported. {fora} of {total} rows were left out "
            "and are in none of the numbers on this screen — see which below."
        ),
        "ver_de_fora": "See the rows that were left out",
        "col_linha": "Row in your spreadsheet",
        "col_motivo": "Why it was left out",
        "meses_demo": "Months of sample data",
        "aviso_demo": (
            "You are looking at SAMPLE DATA. Upload your spreadsheet in "
            "the sidebar to see your own numbers."
        ),
        "passo2": "2 · Your taxes",
        "regime": "Tax regime",
        "regime_ajuda": (
            "Most Brazilian small businesses use Simples Nacional. "
            "Individual micro-entrepreneurs use MEI. Ask your accountant."
        ),
        "anexo": "Simples annex",
        "anexo_ajuda": (
            "Product resale = Annex I. Own manufacturing = Annex II. "
            "Services = III to V. Your accountant knows yours."
        ),
        "rbt12": "Revenue over the last 12 months (R$)",
        "rbt12_movel": "Compute the tax rate month by month (rolling RBT12)",
        "rbt12_movel_ajuda": (
            "Under Simples, each month's rate comes from the revenue of the "
            "12 months BEFORE it (LC 123/2006, art. 18, § 1). Only possible "
            "for months where your file covers those 12 months in full; for "
            "the others the value you entered above applies."
        ),
        "rbt12_movel_aplicada": (
            "Rate computed from your own file for {n} of {total} months; "
            "the rest use the revenue you entered."
        ),
        "rbt12_movel_sem_janela": (
            "Your file does not yet cover 12 months before any month, so "
            "every month uses the value entered above. With 13 months of "
            "history this turns on by itself."
        ),
        "rbt12_lacuna": (
            "{meses} with no entries. Were these months without revenue, or "
            "is the file incomplete?"
        ),
        "rbt12_lacuna_confirmar": "These were months with no revenue (zero sales)",
        "rbt12_lacuna_ajuda": (
            "Until you confirm, Carchuna will not use your file's RBT12 for "
            "the affected months: an empty month may be zero sales or data "
            "that did not make it into the export, and the two readings "
            "yield different tax rates. Without confirmation the revenue you "
            "entered above applies — the safe side, since an RBT12 lower "
            "than the real one would understate the rate and the tax."
        ),
        "rbt12_lacuna_confirmada": (
            "Empty months confirmed as zero sales: their tax rate now comes "
            "from your own file."
        ),
        "meses_do_ano": (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        "narrativa_indisponivel": "Narrative unavailable: {motivo}",
        "rbt12_ajuda": (
            "Everything the company billed in the last 12 months (the "
            "'RBT12'). Found in the monthly Simples statement (PGDAS-D). "
            "It sets your tax rate.\n\n"
            "**Up to R$ 3,600,000:** all inside the DAS, and the figures "
            "on this screen are the whole tax bill.\n\n"
            "**R$ 3,600,000 to R$ 4,320,000:** the numbers are computed, "
            "with a warning — from January onwards you pay state ICMS "
            "and/or municipal ISS outside the DAS (LC 123/2006, art. 20, "
            "§ 1º), and none of it shows up here.\n\n"
            "**Above R$ 4,320,000:** Carchuna does not compute. ICMS/ISS "
            "leave the DAS the following month and the margin would come "
            "out overstated; estimating would mean inventing state and "
            "municipal rates."
        ),
        "das": "Monthly MEI flat payment (R$)",
        "das_ajuda": "The fixed DAS you pay every month.",
        "rbt12_sugerida": (
            "Suggested from your file (monthly average × 12). Confirm "
            "with the exact figure from your Simples statement (PGDAS-D)."
        ),
        "passo3": "3 · Your fees",
        "taxa_adq": "Card machine fee (%)",
        "taxa_adq_ajuda": (
            "What the card machine takes from each sale in your own or "
            "physical store. It's in your contract or acquirer app."
        ),
        "taxa_ant": "Early-payment fee (%/month)",
        "taxa_ant_ajuda": (
            "The interest you pay to receive installment money early "
            "instead of waiting."
        ),
        "atividade": "Your activity",
        "abas": [
            "Summary",
            "Sales & Products",
            "History",
            "What if…?",
            "Grow",
            "Legal Diagnosis",
            "Report",
        ],
        "faturou": "You billed",
        "sobrou": "You really kept",
        "foi_embora": "Went to costs and fees",
        "para_onde": "Where the money went",
        "acoes_titulo": "The most valuable actions right now",
        "acoes_caption": (
            "Computed from your numbers. Details in the Legal Diagnosis "
            "and Grow tabs."
        ),
        "por_mes": "mo",
        "como_ler": "How to read these numbers?",
        "como_ler_texto": (
            "**'Head math' margin** is what every seller computes: price "
            "minus product cost. **Real margin** also subtracts taxes, "
            "commissions, card fees, early-payment costs, shipping and "
            "returns — what you actually keep. Every number has a label: "
            "`calculado` comes from your data and the law; `estimado` "
            "uses an editable default rate — replace it with your real "
            "one in the sidebar."
        ),
        "sem_acoes": "Nothing urgent detected — your numbers look healthy.",
        "implausivel_titulo": "These numbers don't add up.",
        "reconciliacao_titulo": "The two calculation paths disagree.",
        "aviso_titulo": "The math is done, but read this before using it.",
        "motor_falhou": "This section could not be computed.",
        "motor_falhou_base": (
            "The margin breakdown did not run, and without it there is "
            "nothing for the tabs to show."
        ),
        "wf_receita": "Revenue",
        "cachoeira_dica": (
            "Click a cost bar to see where it comes from — by channel "
            "and by month. Double-click to clear."
        ),
        "drill_titulo": "Where it comes from: {rotulo}",
        "drill_por_canal": "By channel",
        "drill_por_mes": "By month",
        "drill_sem_canal": (
            "The MEI's DAS is a fixed monthly fee — splitting it by "
            "channel would be making numbers up. The monthly breakdown "
            "beside is the real one."
        ),
        "radar_titulo": "CFO radar",
        "radar_caption": (
            "Signals found automatically in your numbers — each with its "
            "R$/month impact, the method that caught it and what to do "
            "about it."
        ),
        "radar_vazio": (
            "Nothing on the radar — stable margins and no new leak between months."
        ),
        "radar_sev": {
            "critico": "CRITICAL",
            "atencao": "WARNING",
            "oportunidade": "OPPORTUNITY",
        },
        "radar_esperado": "expected",
        "radar_observado": "observed",
        "radar_metodo": "How it was detected:",
        "radar_aviso": (
            "Signals computed by transparent rules, no AI — leads to "
            "investigate with your accountant, not verdicts. Narratives "
            "are in Portuguese (the audience's language)."
        ),
        "lin_titulo": "Where does each number come from?",
        "lin_caption": (
            "Pick a number and see the source file, the columns, the "
            "formula with your case's parameters, the assumptions and the "
            "limitations — full traceability."
        ),
        "lin_numero": "Number",
        "lin_origem": "Data source",
        "lin_colunas": "Columns used",
        "lin_formula": "Calculation",
        "lin_transf": "Import transformations",
        "lin_premissas": "Assumptions",
        "lin_limitacoes": "Limitations",
        "lin_fonte": "Legal basis / table",
        "lin_quando": "Computed at",
        "conf_titulo": "How much can you trust these numbers?",
        "conf_nota": "Confidence in the data: {pct}% ({nivel})",
        "conf_caption": (
            "The score rates your DATA, not the maths: the maths is always "
            "the same. It adds up four fixed-rubric components — evidence, "
            "history, sample size and filled-in fields — and each one "
            "states why it scored what it scored."
        ),
        "vendas_metricas": ["Sales", "Revenue", "Channels", "Returns"],
        "campeoes": "Margin champions — sell more of these",
        "campeoes_caption": (
            "The products that leave the most money in your pocket after "
            "everything is discounted."
        ),
        "cada_100": "of every R$ 100 sold becomes profit",
        "viloes": "Warning: these lose money on every sale",
        "viloes_caption": (
            "After taxes, commissions and costs, these products are in "
            "the red. Raise the price (calculator in the Grow tab) or "
            "drop them."
        ),
        "prejuizo_por_venda": "accumulated loss",
        "sem_viloes": "No product losing money. Good sign.",
        "tabela_produtos": "All products",
        "col_produto": "product",
        "col_vendas": "sales",
        "col_devolvidas": "returned",
        "col_receita": "revenue",
        "col_margem": "margin (R$)",
        "col_margem_pct": "margin %",
        "receita_por_canal": "Revenue by channel",
        "todas_vendas": "See every sale, one by one",
        "margem_por_venda": "Include the real margin of each sale",
        "hist_caption": (
            "Your business over time, month by month — computed by the "
            "same engine as every other tab."
        ),
        "hist_um_mes": (
            "Your spreadsheet has a single month. Upload more months to "
            "see the evolution and the comparison."
        ),
        "hist_receita": "Revenue by month",
        "hist_margem": "Margin % by month",
        "hist_lucro": "Cumulative profit",
        "hist_comparacao": "Last month vs. previous",
        "hist_frase_melhora": (
            "From {m1} to {m2}, your margin went from {a}% to {b}% "
            "(up {d} p.p.). Biggest change: {causa}, from {ca}% to {cb}% "
            "of revenue."
        ),
        "hist_frase_piora": (
            "From {m1} to {m2}, your margin went from {a}% to {b}% "
            "(down {d} p.p.). Biggest weight: {causa}, from {ca}% to "
            "{cb}% of revenue."
        ),
        "hist_tabela": "Monthly table",
        "col_mes": "month",
        "col_maior_custo": "largest cost",
        "baixar_hist": "Download history (CSV)",
        "delta_receita": "Revenue",
        "delta_margem": "Margin (R$)",
        "delta_pp": "Margin (p.p.)",
        "ese_caption": (
            "Stress tests: what happens to your profit if something "
            "changes tomorrow? Each box shows the margin recomputed from "
            "scratch by the same engine."
        ),
        "margem_cenario": "Margin in scenario",
        "impacto_reais": "Difference (R$)",
        "impacto_pp": "Difference (p.p.)",
        "crescimento_caption": (
            "How to bill more — with your numbers, not promises: where "
            "each real earns the most, the right price and how much room "
            "you have inside Simples."
        ),
        "caminho": "What to do:",
        "simular_canal": "What if I sold more in one channel?",
        "canal": "Channel",
        "crescimento_vendas": "Sell more (%)",
        "margem_hoje": "Your margin today",
        "ganho": "You would gain (R$)",
        "calculadora": "Find the right price",
        "calculadora_caption": (
            "Tell it what the product costs and how much you want to "
            "earn; Carchuna returns the selling price — taxes, commission "
            "and fees included."
        ),
        "custo_produto": "What the product costs you (R$)",
        "frete": "Shipping you pay (R$)",
        "canal_venda": "Where you will sell",
        "margem_alvo": "How much you want to earn (%)",
        "preco_equilibrio": "Below this price you LOSE money",
        "preco_para": "Sell at this price to earn {pct}%",
        "diag_caption": (
            "Leaks detected in your numbers, with the law behind each one "
            "— ready to take to your accountant."
        ),
        "vazamentos": "What we found",
        "sem_achados": "No leaks detected. Good sign.",
        "base_legal": "The law behind this:",
        "pendente": " · _human review pending_",
        "conferido_em": " · _checked on {data}_",
        "fonte_oficial": "official source",
        "pergunte": "Ask in your own words",
        "pergunta_exemplo": (
            "E.g.: 'my card machine fee looks too high, can I switch?'"
        ),
        "modo_extrativo": (
            "Basic-mode answer (no AI key) — always citing the law and " "the source."
        ),
        "relatorio_caption": (
            "A 3-page PDF with the X-ray, scenarios and findings — ready "
            "to take to your accountant."
        ),
        "gerar_pdf": "Generate PDF report",
        "baixar_pdf": "Download the report",
    },
}


def _brl(v: Decimal) -> str:
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _brl_inteiro(v: Decimal) -> str:
    return f"R$ {v:,.0f}".replace(",", ".")


_CONSTANTES_MAPA = {
    "canal": ["=mercado_livre", "=shopee", "=amazon", "=loja_propria", "=fisico"],
    "custo_produto": ["=0"],
    "frete_pago": ["=0"],
    "prazo_recebimento_dias": ["=0"],
    "devolvida": ["=nao"],
}


def _rotulo_opcao(opcao: str, textos: dict) -> str:
    if opcao == "":
        return textos["opcao_nenhuma"]
    if opcao == "=0":
        return textos["opcao_zero"]
    if opcao == "=nao":
        return textos["opcao_nao"]
    if opcao.startswith("="):
        return f"{textos['opcao_fixo']} {opcao[1:]})"
    return opcao


def _percentual(rotulo: str, padrao: str, ajuda: str, textos: dict, chave: str):
    """Lê um percentual da barra lateral como texto e devolve ``Decimal``.

    O `st.number_input` devolveria `float` — e float em número que
    multiplica dinheiro é justamente o que a regra da casa proíbe.

    Não pode ser cacheada: desenha um widget, e widget dentro de função
    com cache é erro do Streamlit.
    """
    bruto = st.text_input(rotulo, value=padrao, help=ajuda, key=chave)
    try:
        return decimal_de_texto(bruto, rotulo)
    except ValueError:
        st.error(textos["percentual_invalido"].format(campo=rotulo, valor=bruto))
        st.stop()


def _transacoes_do_resultado(resultado, textos: dict) -> list:
    """Mostra o que entrou, o que ficou de fora e devolve as vendas boas.

    A regra da casa é que nenhuma linha suma em silêncio: quando o
    arquivo tem linha estragada, o lojista vê quantas ficaram de fora, o
    número de cada uma na planilha dele e o motivo — e os totais da tela
    são só das linhas que entraram.
    """
    if not resultado.transacoes:
        st.error(f"{textos['falha_importacao']} {resultado.resumo()}")
        st.stop()
    if not resultado.rejeitadas:
        st.success(f"{len(resultado.transacoes)} {textos['importadas']}")
        return resultado.transacoes
    st.warning(
        textos["linhas_de_fora"].format(
            ok=len(resultado.transacoes),
            fora=len(resultado.rejeitadas),
            total=resultado.total_lidas,
        )
    )
    with st.expander(textos["ver_de_fora"]):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        textos["col_linha"]: r.numero,
                        textos["col_motivo"]: r.motivo,
                    }
                    for r in resultado.rejeitadas
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    return resultado.transacoes


def _lacunas_do_arquivo(transacoes) -> list[str]:
    """Todos os meses vazios no meio de alguma janela de 12 meses.

    Reúne as lacunas de todos os meses do arquivo numa lista só: para o
    lojista a pergunta é sobre o mês ("março teve faturamento?"), não
    sobre em quantas janelas ele entra.
    """
    return sorted(
        {
            mes
            for janela in procedencia_rbt12(list(transacoes)).values()
            for mes in janela.lacunas
        }
    )


def _lista_de_meses(meses: list[str], t: dict) -> str:
    """['2026-03', '2026-09'] → 'Março/2026 e Setembro/2026'."""
    nomes = [f"{t['meses_do_ano'][int(mes[5:7]) - 1]}/{mes[:4]}" for mes in meses]
    if len(nomes) == 1:
        return nomes[0]
    return f"{', '.join(nomes[:-1])} e {nomes[-1]}"
