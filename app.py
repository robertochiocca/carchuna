"""Dashboard da Carchuna — pensado para o lojista, não para o analista.

Oito abas em linguagem simples: Resumo (cachoeira da margem com
drill-down e o Radar do CFO), Vendas e Produtos (campeões e vilões de
margem), Histórico (evolução mês a mês), E se…? (testes de estresse),
Crescer (como faturar mais), Caixa (agenda de recebíveis e fôlego),
Diagnóstico Legal e Relatório. Interface bilíngue (PT/EN); roda 100%
offline com dados sintéticos e aceita upload de CSV/JSON/XLSX.

As narrativas geradas pelos motores (achados, oportunidades, nomes de
cenário) são em português — a língua do público-alvo; a interface é que
alterna. Isso está sinalizado no modo EN.

Uso::

    streamlit run app.py
"""

from __future__ import annotations

import io
from decimal import Decimal

import altair as alt
import pandas as pd
import streamlit as st

from carchuna import (
    AnalisadorMargem,
    CenarioCrescimentoCanal,
    ConfigTributaria,
    Copiloto,
    MotorAnomalias,
    MotorDecisao,
    MotorInsights,
    MotorOtimizacao,
    ParametrosDiagnostico,
    ParametrosOtimizacao,
    Restricoes,
    TabelaCustos,
    agenda_recebimentos,
    analisar_caixa,
    carregar_transacoes,
    comparar_benchmarks,
    projetar_caixa,
    transacoes_sinteticas,
)
from carchuna.crescimento import AVISO_CRESCIMENTO
from carchuna.dados import (
    COLUNAS_OBRIGATORIAS,
    ler_linhas_brutas,
    sugerir_mapeamento,
    transacoes_de_mapa,
)
from carchuna.rag.llm import gerar_resposta, resposta_extrativa
from carchuna.rag.retrieval import AVISO_LEGAL, Retriever

st.set_page_config(page_title="Carchuna", layout="wide")

# Tipografia dos números: serenos, tabulares, em água-clara — e métricas
# como cartões uniformes, para a simetria entre as colunas.
st.markdown(
    """
    <style>
    [data-testid="stMetric"] {
        background: rgba(10, 56, 64, 0.55);
        border: 1px solid #134d57;
        border-radius: 14px;
        padding: 14px 18px;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.6rem;
        font-weight: 600;
        color: #9ff2e9;
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.01em;
    }
    [data-testid="stMetricLabel"] { color: #87a9a8; }
    [data-testid="stMetricDelta"] { font-size: 0.85rem; }
    [data-testid="stTable"], [data-testid="stDataFrame"] {
        font-variant-numeric: tabular-nums;
    }
    h1 { letter-spacing: -0.5px; }
    h2, h3 { letter-spacing: -0.3px; }
    </style>
    """,
    unsafe_allow_html=True,
)

AGUA = "#2ee6d6"
AGUA_TEXTO = "#cfe9e6"
TEAL_CALMO = "#4fb3c1"
_SEM_FUNDO = {"background": "rgba(0,0,0,0)"}


def _base_config(grafico):
    return grafico.configure(**_SEM_FUNDO).configure_view(strokeOpacity=0)


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
        "monitorar": "Atualizar sozinho quando o arquivo mudar",
        "monitorando": "Acompanhando o arquivo — salve a planilha e veja aqui.",
        "importadas": "vendas importadas.",
        "falha_importacao": "Não consegui ler o arquivo:",
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
        "rbt12_ajuda": (
            "Soma de tudo que a empresa faturou nos últimos 12 meses "
            "(o 'RBT12'). Está no extrato do Simples (PGDAS-D) que o "
            "contador emite todo mês. Define a sua alíquota."
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
            "Caixa",
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
            "com o impacto em R$/mês e o que fazer a respeito."
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
        "radar_aviso": (
            "Insights calculados por regras transparentes, sem IA — são "
            "sinais para investigar com seu contador, não veredito."
        ),
        "caixa_caption": (
            "Seu fôlego financeiro: quando o dinheiro das vendas JÁ "
            "FEITAS cai na conta, contra as contas que você paga por mês. "
            "Nada aqui prevê vendas futuras — é agenda, não bola de "
            "cristal."
        ),
        "caixa_inicial": "Dinheiro em caixa hoje (R$)",
        "caixa_saidas": "Quanto sai por mês (R$)",
        "caixa_saidas_ajuda": (
            "Some tudo que sai todo mês: aluguel, salários, fornecedores, "
            "luz — e inclua o DAS do Simples, que é pago à parte do "
            "repasse dos canais."
        ),
        "caixa_recebs": "Vai cair na conta (90 dias)",
        "caixa_saidas_metric": "Vai sair (90 dias)",
        "caixa_folego": "Fôlego",
        "caixa_folego_ok": "90+ dias",
        "caixa_dias": "{dias} dias",
        "caixa_alerta": (
            "Risco de caixa: no ritmo informado, o saldo fica negativo "
            "em {dias} dias ({data}). Antecipar recebíveis, adiar saídas "
            "ou reforçar o caixa evita o aperto — leve esta curva ao seu "
            "contador."
        ),
        "caixa_ok": (
            "Sem sufoco à vista: o saldo não fica negativo nos próximos " "90 dias."
        ),
        "caixa_curva": "Saldo projetado, dia a dia",
        "caixa_etiquetas": (
            "Recebimentos: `calculado` — a agenda das vendas do arquivo, "
            "no prazo de cada uma. Saídas: `estimado` — o valor que você "
            "informou, diluído por dia. A curva enxerga só as vendas já "
            "feitas: sem vendas novas no arquivo, ela desce."
        ),
        "fila_titulo": "Qual problema resolver primeiro",
        "fila_caption": (
            "Achados, sinais do radar e oportunidades, juntos numa fila "
            "única — ordenada por impacto × confiança × esforço × "
            "velocidade × risco × reversibilidade. A conta de cada posição "
            "está aberta no 'por quê'."
        ),
        "fila_acao": "O que fazer:",
        "fila_porque": "Por que esta prioridade?",
        "fila_confianca": "confiança",
        "fila_esforco": "esforço",
        "fila_velocidade": "resultado em",
        "fila_risco": "risco",
        "fila_motivos": "O que sustenta a confiança:",
        "anom_titulo": "Mudanças anormais no último mês",
        "anom_esperado": "Esperado",
        "anom_observado": "Observado",
        "anom_desvio": "Desvio",
        "anom_metodo": "Como foi detectada:",
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
        "otim_titulo": "Qual combinação maximiza o lucro?",
        "otim_caption": (
            "Busca em grade determinística sobre preço × migração de canal, "
            "no mesmo motor testado. Defina suas restrições; todos os "
            "candidatos avaliados ficam visíveis — a explicação é a grade."
        ),
        "otim_elast": "Volume perdido a cada +1% de preço (%) — sua premissa",
        "otim_elast_ajuda": (
            "0 = volume constante (premissa padrão, declarada no resultado). "
            "A planilha de vendas não tem como medir elasticidade — este "
            "número é uma hipótese SUA."
        ),
        "otim_margem_min": "Margem mínima (%)",
        "otim_queda_max": "Queda máxima de volume (%)",
        "otim_teto": "Ticket médio máximo (R$, 0 = sem teto)",
        "otim_melhor": "Melhor combinação viável",
        "otim_ganho": "Ganho vs. hoje",
        "otim_grade": "Ver todos os candidatos avaliados",
        "otim_col": {
            "preco": "preço",
            "migracao": "migração ML→próprio",
            "margem": "margem %",
            "lucro": "lucro/mês",
            "status": "status",
        },
        "cx_janelas": "Janelas de 30, 60 e 90 dias",
        "cx_entra": "entra",
        "cx_sai": "sai",
        "cx_saldo": "saldo",
        "bench_titulo": "Comparações com régua honesta",
        "bench_caption": (
            "Só comparamos com o que tem fonte: tabela pública do canal "
            "(com link), referências documentadas e editáveis, ou um número "
            "que VOCÊ trouxer. Sem fonte confiável, dizemos 'indisponível' — "
            "benchmark inventado não entra."
        ),
        "bench_sua_ref": "Sua referência de margem líquida (%, opcional)",
        "bench_fonte": "Fonte:",
        "cop_dados": "Os números por trás da resposta",
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
        "monitorar": "Refresh automatically when the file changes",
        "monitorando": "Watching the file — save the spreadsheet and see it here.",
        "importadas": "sales imported.",
        "falha_importacao": "Could not read the file:",
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
        "rbt12_ajuda": (
            "Everything the company billed in the last 12 months (the "
            "'RBT12'). Found in the monthly Simples statement (PGDAS-D). "
            "It sets your tax rate."
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
            "Cash",
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
            "R$/month impact and what to do about it."
        ),
        "radar_vazio": (
            "Nothing on the radar — stable margins and no new leak " "between months."
        ),
        "radar_sev": {
            "critico": "CRITICAL",
            "atencao": "WARNING",
            "oportunidade": "OPPORTUNITY",
        },
        "radar_aviso": (
            "Insights computed by transparent rules, no AI — signals to "
            "investigate with your accountant, not verdicts. Narratives "
            "are in Portuguese (the audience's language)."
        ),
        "caixa_caption": (
            "Your cash runway: when the money from sales ALREADY MADE "
            "lands in your account, against what you pay out each month. "
            "Nothing here predicts future sales — it is a schedule, not "
            "a crystal ball."
        ),
        "caixa_inicial": "Cash on hand today (R$)",
        "caixa_saidas": "Monthly outflows (R$)",
        "caixa_saidas_ajuda": (
            "Add up everything that leaves every month: rent, salaries, "
            "suppliers, utilities — and include the Simples DAS, which "
            "is paid separately from channel payouts."
        ),
        "caixa_recebs": "Landing in your account (90 days)",
        "caixa_saidas_metric": "Going out (90 days)",
        "caixa_folego": "Runway",
        "caixa_folego_ok": "90+ days",
        "caixa_dias": "{dias} days",
        "caixa_alerta": (
            "Cash risk: at the stated pace, the balance goes negative in "
            "{dias} days ({data}). Advancing receivables, delaying "
            "outflows or adding cash avoids the squeeze — take this "
            "curve to your accountant."
        ),
        "caixa_ok": (
            "No squeeze in sight: the balance stays positive for the " "next 90 days."
        ),
        "caixa_curva": "Projected balance, day by day",
        "caixa_etiquetas": (
            "Receivables: `calculado` — the schedule of the sales in "
            "your file, each on its payout term. Outflows: `estimado` — "
            "the amount you entered, spread per day. The curve only sees "
            "sales already made: with no new sales in the file, it goes "
            "down."
        ),
        "fila_titulo": "Which problem to solve first",
        "fila_caption": (
            "Findings, radar signals and opportunities in a single queue — "
            "ranked by impact × confidence × effort × speed × risk × "
            "reversibility. The math behind each position is open in the "
            "'why'."
        ),
        "fila_acao": "What to do:",
        "fila_porque": "Why this priority?",
        "fila_confianca": "confidence",
        "fila_esforco": "effort",
        "fila_velocidade": "results in",
        "fila_risco": "risk",
        "fila_motivos": "What supports the confidence:",
        "anom_titulo": "Abnormal changes in the last month",
        "anom_esperado": "Expected",
        "anom_observado": "Observed",
        "anom_desvio": "Deviation",
        "anom_metodo": "How it was detected:",
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
        "otim_titulo": "Which combination maximizes profit?",
        "otim_caption": (
            "Deterministic grid search over price × channel migration, on "
            "the same tested engine. Set your constraints; every candidate "
            "evaluated stays visible — the grid IS the explanation."
        ),
        "otim_elast": "Volume lost per +1% price (%) — your assumption",
        "otim_elast_ajuda": (
            "0 = constant volume (default assumption, declared in the "
            "result). A sales sheet cannot measure elasticity — this "
            "number is YOUR hypothesis."
        ),
        "otim_margem_min": "Minimum margin (%)",
        "otim_queda_max": "Maximum volume drop (%)",
        "otim_teto": "Maximum average ticket (R$, 0 = no cap)",
        "otim_melhor": "Best feasible combination",
        "otim_ganho": "Gain vs. today",
        "otim_grade": "See every candidate evaluated",
        "otim_col": {
            "preco": "price",
            "migracao": "migration ML→own",
            "margem": "margin %",
            "lucro": "profit/mo",
            "status": "status",
        },
        "cx_janelas": "30, 60 and 90-day windows",
        "cx_entra": "in",
        "cx_sai": "out",
        "cx_saldo": "balance",
        "bench_titulo": "Comparisons with an honest yardstick",
        "bench_caption": (
            "We only compare against things with a source: the channel's "
            "public fee table (with link), documented editable references, "
            "or a number YOU bring. Without a reliable source we say "
            "'unavailable' — invented benchmarks don't get in."
        ),
        "bench_sua_ref": "Your net-margin reference (%, optional)",
        "bench_fonte": "Source:",
        "cop_dados": "The numbers behind the answer",
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

with st.sidebar:
    idioma = st.radio("Idioma / Language", ["PT", "EN"], horizontal=True)
lang = "pt" if idioma == "PT" else "en"
t = T[lang]
rotulos = ROTULOS_SIMPLES_PT if lang == "pt" else ROTULOS_EN


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


@st.cache_resource(show_spinner=False)
def _retriever_cacheado() -> Retriever:
    return Retriever()


@st.cache_data(show_spinner=False)
def _resultados_cacheados(
    transacoes: tuple, config, tabela, atividade: str, origem: str
) -> dict:
    """Roda os motores uma vez por (dados, config) — não por clique.

    Com bases reais (dezenas de milhares de vendas), decompor venda a
    venda a cada interação de widget ficaria lento; o cache devolve o
    conjunto pronto enquanto nada mudar.
    """
    analise = AnalisadorMargem(
        list(transacoes),
        config,
        tabela,
        ParametrosDiagnostico(atividade=atividade),
        retriever=_retriever_cacheado(),
        origem=origem,
    )
    achados = analise.diagnosticar()
    radar = MotorInsights().radar(list(transacoes), config, tabela)
    oportunidades = analise.crescimento()
    return {
        "decomposicao": analise.decomposicao,
        "resumo": analise.resumo_executivo(),
        "mensal": analise.mensal,
        "lucro": analise.lucro_acumulado(),
        "por_venda": analise.margem_por_venda(),
        "por_produto": analise.margem_por_produto(),
        "cenarios": analise.cenarios(),
        "anomalias": MotorAnomalias().detectar(list(transacoes), config, tabela),
        "recomendacoes": MotorDecisao().recomendar(
            list(transacoes), achados, radar, oportunidades
        ),
        "linhagem": analise.linhagem(),
        "achados": achados,
        "oportunidades": oportunidades,
        "radar": radar,
    }


@st.cache_data(show_spinner=False)
def _composicao_cacheada(transacoes: tuple, config, tabela, nome: str) -> dict:
    """Drill-down de uma dedução (por canal e por mês), cacheado por clique."""
    return AnalisadorMargem(list(transacoes), config, tabela).composicao_deducao(nome)


def _grafico_cachoeira(decomposicao, rotulos: dict, t: dict):
    """A cachoeira da margem: do faturamento ao que sobrou, degrau a degrau.

    Cada dedução é um degrau descendo do acumulado; a última barra é o
    que sobrou. As barras de custo são clicáveis (seleção nomeada
    ``ponto``): o app abre a composição por canal e por mês da dedução
    clicada. Estilo da casa: sem eixo Y, valor escrito sobre cada barra.
    """
    linhas = []
    acumulado = decomposicao.receita_bruta
    linhas.append(
        {
            "nome": "receita",
            "rotulo": t["wf_receita"],
            "inicio": 0.0,
            "fim": float(acumulado),
            "topo": float(acumulado),
            "texto": _brl_inteiro(acumulado),
            "tipo": "receita",
        }
    )
    for d in decomposicao.deducoes:
        linhas.append(
            {
                "nome": d.nome,
                "rotulo": rotulos.get(d.nome, d.nome),
                "inicio": float(acumulado - d.valor),
                "fim": float(acumulado),
                "topo": float(acumulado),
                "texto": f"− {_brl_inteiro(d.valor)}",
                "tipo": "deducao",
            }
        )
        acumulado -= d.valor
    margem = decomposicao.margem_liquida
    linhas.append(
        {
            "nome": "margem",
            "rotulo": t["sobrou"],
            "inicio": float(min(Decimal("0"), margem)),
            "fim": float(max(Decimal("0"), margem)),
            "topo": float(max(Decimal("0"), margem)),
            "texto": _brl_inteiro(margem),
            "tipo": "margem",
        }
    )
    dados = pd.DataFrame(linhas)
    selecao = alt.selection_point(name="ponto", fields=["nome"], on="click")
    base = alt.Chart(dados).encode(
        x=alt.X(
            "rotulo:N",
            sort=dados["rotulo"].tolist(),
            title=None,
            axis=alt.Axis(
                labelAngle=-22,
                labelFontSize=12,
                labelColor="#d8e7e5",
                labelLimit=0,
                labelOverlap=False,
            ),
        )
    )
    barras = (
        base.mark_bar(cornerRadius=6, size=46)
        .encode(
            y=alt.Y(
                "inicio:Q",
                title=None,
                axis=alt.Axis(labels=False, grid=False, ticks=False, domain=False),
            ),
            y2="fim:Q",
            color=alt.Color(
                "tipo:N",
                scale=alt.Scale(
                    domain=["receita", "deducao", "margem"],
                    range=[TEAL_CALMO, "#cf8a70", "#8fd694"],
                ),
                legend=None,
            ),
            opacity=alt.condition(selecao, alt.value(1.0), alt.value(0.55)),
            tooltip=[
                alt.Tooltip("rotulo:N", title=" "),
                alt.Tooltip("texto:N", title="R$"),
            ],
        )
        .add_params(selecao)
    )
    textos = base.mark_text(
        dy=-10, color=AGUA_TEXTO, fontSize=11.5, font="monospace"
    ).encode(y=alt.Y("topo:Q"), text="texto:N")
    return _base_config((barras + textos).properties(height=320, padding={"top": 16}))


def _grafico_barras_h(linhas: list[dict], cor: str = TEAL_CALMO):
    """Barras horizontais no estilo da casa: rótulo inteiro, valor na ponta."""
    dados = pd.DataFrame(linhas)
    ordem = dados.sort_values("valor", ascending=False)["rotulo"].tolist()
    base = alt.Chart(dados).encode(
        y=alt.Y(
            "rotulo:N",
            sort=ordem,
            title=None,
            axis=alt.Axis(labelLimit=0, labelFontSize=13, labelColor="#d8e7e5"),
        ),
        x=alt.X(
            "valor:Q",
            title=None,
            axis=alt.Axis(labels=False, grid=False, ticks=False, domain=False),
        ),
    )
    barras = base.mark_bar(cornerRadiusEnd=7, height=22, color=cor)
    textos = base.mark_text(
        align="left", dx=8, color=AGUA_TEXTO, fontSize=12.5, font="monospace"
    ).encode(text="texto:N")
    return _base_config(
        (barras + textos).properties(height=len(linhas) * 38, padding={"right": 90})
    )


def _grafico_barras_v(linhas: list[dict], cor: str = TEAL_CALMO):
    """Barras verticais (ex.: meses) com o valor escrito no topo de cada uma."""
    dados = pd.DataFrame(linhas)
    base = alt.Chart(dados).encode(
        x=alt.X(
            "rotulo:N",
            sort=dados["rotulo"].tolist(),
            title=None,
            axis=alt.Axis(labelAngle=0, labelFontSize=12.5, labelColor="#d8e7e5"),
        ),
        y=alt.Y(
            "valor:Q",
            title=None,
            axis=alt.Axis(labels=False, grid=False, ticks=False, domain=False),
        ),
    )
    barras = base.mark_bar(
        cornerRadiusTopLeft=7, cornerRadiusTopRight=7, size=44, color=cor
    )
    textos = base.mark_text(
        dy=-10, color=AGUA_TEXTO, fontSize=12, font="monospace"
    ).encode(text="texto:N")
    return _base_config((barras + textos).properties(height=280, padding={"top": 16}))


def _grafico_serie(linhas: list[dict], modo: str = "linha"):
    """Linha (ou área) mensal com o valor escrito em cada ponto."""
    dados = pd.DataFrame(linhas)
    base = alt.Chart(dados).encode(
        x=alt.X(
            "rotulo:N",
            sort=dados["rotulo"].tolist(),
            title=None,
            axis=alt.Axis(labelAngle=0, labelFontSize=12.5, labelColor="#d8e7e5"),
        ),
        y=alt.Y(
            "valor:Q",
            title=None,
            scale=alt.Scale(zero=(modo == "area")),
            axis=alt.Axis(labels=False, grid=False, ticks=False, domain=False),
        ),
    )
    ponto = alt.OverlayMarkDef(color=AGUA, size=70)
    if modo == "area":
        gradiente = alt.Gradient(
            gradient="linear",
            stops=[
                alt.GradientStop(color="rgba(46,230,214,0.02)", offset=0),
                alt.GradientStop(color="rgba(46,230,214,0.30)", offset=1),
            ],
            x1=1,
            x2=1,
            y1=1,
            y2=0,
        )
        marca = base.mark_area(
            line={"color": AGUA, "strokeWidth": 2.5}, color=gradiente, point=ponto
        )
    else:
        marca = base.mark_line(color=AGUA, strokeWidth=2.5, point=ponto)
    textos = base.mark_text(
        dy=-15, color=AGUA_TEXTO, fontSize=12, font="monospace"
    ).encode(text="texto:N")
    return _base_config((marca + textos).properties(height=280, padding={"top": 18}))


def _grafico_caixa(curva, dia_negativo):
    """Área do saldo projetado, com a linha do zero e o dia do vermelho.

    Diferente dos gráficos mensais, aqui são 90 pontos — escrever o
    valor em cada um viraria ruído; o eixo Y entra discreto no lugar.
    """
    dados = pd.DataFrame([{"dia": dia, "saldo": float(s)} for dia, s in curva])
    base = alt.Chart(dados).encode(
        x=alt.X(
            "dia:T",
            title=None,
            axis=alt.Axis(
                format="%d/%m",
                grid=False,
                labelColor="#d8e7e5",
                labelFontSize=12,
                tickColor="#134d57",
                domainColor="#134d57",
            ),
        ),
        y=alt.Y(
            "saldo:Q",
            title=None,
            axis=alt.Axis(
                grid=False,
                labelColor="#87a9a8",
                labelFontSize=11,
                format="~s",
                ticks=False,
                domain=False,
            ),
        ),
    )
    gradiente = alt.Gradient(
        gradient="linear",
        stops=[
            alt.GradientStop(color="rgba(46,230,214,0.02)", offset=0),
            alt.GradientStop(color="rgba(46,230,214,0.30)", offset=1),
        ],
        x1=1,
        x2=1,
        y1=1,
        y2=0,
    )
    area = base.mark_area(line={"color": AGUA, "strokeWidth": 2.5}, color=gradiente)
    zero = (
        alt.Chart(pd.DataFrame({"y": [0.0]}))
        .mark_rule(color="#cf8a70", strokeDash=[5, 5], strokeWidth=1.5)
        .encode(y="y:Q")
    )
    camadas = area + zero
    if dia_negativo is not None:
        marco = (
            alt.Chart(pd.DataFrame({"dia": [pd.Timestamp(dia_negativo)]}))
            .mark_rule(color="#cf8a70", strokeWidth=1.5)
            .encode(x="dia:T")
        )
        camadas = camadas + marco
    return _base_config(camadas.properties(height=300, padding={"top": 14}))


st.title(t["titulo"])
st.caption(t["subtitulo"])
if t["nota_motor"]:
    st.caption(t["nota_motor"])

# ---------------------------------------------------------------------------
# Barra lateral: 3 passos simples
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header(t["passo1"])
    upload = st.file_uploader(
        t["upload"], type=["csv", "json", "xlsx", "pdf"], help=t["upload_ajuda"]
    )
    caminho_arquivo = ""
    monitorar = False
    with st.expander(t["tempo_real"]):
        caminho_arquivo = st.text_input(
            t["caminho_arquivo"], help=t["tempo_real_ajuda"]
        ).strip()
        monitorar = st.toggle(t["monitorar"], value=bool(caminho_arquivo))
    linhas_brutas = None
    if upload is not None:
        try:
            transacoes = carregar_transacoes(upload, name=upload.name)
            st.success(f"{len(transacoes)} {t['importadas']}")
        except (ValueError, TypeError) as erro:
            upload.seek(0)
            try:
                linhas_brutas = ler_linhas_brutas(upload, name=upload.name)
            except (ValueError, TypeError, ImportError):
                st.error(f"{t['falha_importacao']} {erro}")
                st.stop()
    elif caminho_arquivo:
        try:
            transacoes = carregar_transacoes(caminho_arquivo)
            st.success(f"{len(transacoes)} {t['importadas']}")
            if monitorar:
                st.info(t["monitorando"])
        except (ValueError, TypeError, OSError, ImportError) as erro:
            st.error(f"{t['falha_importacao']} {erro}")
            st.stop()
    else:
        meses_demo = st.slider(t["meses_demo"], 2, 12, 6)
        transacoes = transacoes_sinteticas(meses=meses_demo)

    if linhas_brutas is not None:
        # Mapeador de colunas: o relatório real veio com outros nomes —
        # o usuário aponta o de-para e a análise segue normalmente.
        st.info(t["mapa_sidebar"])
        st.caption(t["mapa_caption"])
        colunas_arquivo = sorted({chave for lin in linhas_brutas for chave in lin})
        palpites = sugerir_mapeamento(colunas_arquivo)
        mapa: dict[str, str] = {}
        for campo, rotulo in t["mapa_campos"].items():
            opcoes = ["", *colunas_arquivo, *_CONSTANTES_MAPA.get(campo, [])]
            palpite = palpites.get(campo) or ""
            mapa[campo] = st.selectbox(
                rotulo,
                opcoes,
                index=opcoes.index(palpite) if palpite in opcoes else 0,
                key=f"mapa_{campo}",
                format_func=lambda opcao: _rotulo_opcao(opcao, t),
            )
        faltando = [
            t["mapa_campos"][campo].rstrip(" •")
            for campo in COLUNAS_OBRIGATORIAS
            if not mapa.get(campo)
        ]
        if faltando:
            st.warning(t["mapa_incompleto"].format(campos=", ".join(faltando)))
            st.stop()
        try:
            transacoes = transacoes_de_mapa(
                linhas_brutas, {c: o for c, o in mapa.items() if o}
            )
            st.success(f"{len(transacoes)} {t['importadas']}")
        except (ValueError, TypeError) as erro:
            st.error(f"{t['falha_importacao']} {erro}")
            st.stop()

    # Um upload transcreve tudo: com dados reais, a RBT12 é sugerida do
    # próprio arquivo (média mensal x 12) — editável e para confirmar
    # com o PGDAS-D; a alíquota do Simples sai dela, pela LC 123.
    rbt12_sugerida = None
    if upload is not None or caminho_arquivo:
        meses_arquivo = len({(tr.data.year, tr.data.month) for tr in transacoes})
        receita_arquivo = sum((tr.valor_bruto for tr in transacoes), Decimal("0"))
        rbt12_sugerida = int(
            min(
                max(receita_arquivo / meses_arquivo * 12, Decimal("1000")),
                Decimal("4800000"),
            )
        )

    st.header(t["passo2"])
    regime = st.selectbox(
        t["regime"],
        ["simples", "mei"],
        format_func=str.upper,
        help=t["regime_ajuda"],
    )
    if regime == "simples":
        anexo = st.selectbox(
            t["anexo"], ["I", "II", "III", "IV", "V"], help=t["anexo_ajuda"]
        )
        rbt12 = st.number_input(
            t["rbt12"],
            min_value=1_000,
            max_value=4_800_000,
            value=rbt12_sugerida or 4_200_000,
            step=10_000,
            help=t["rbt12_ajuda"],
        )
        if rbt12_sugerida:
            st.caption(t["rbt12_sugerida"])
        config = ConfigTributaria(
            regime="simples", anexo_simples=anexo, rbt12=Decimal(int(rbt12))
        )
    else:
        das = st.number_input(t["das"], 1, 500, 76, help=t["das_ajuda"])
        config = ConfigTributaria(regime="mei", das_mei_mensal=Decimal(int(das)))

    st.header(t["passo3"])
    taxa_adq = st.number_input(
        t["taxa_adq"], 0.0, 10.0, 2.0, 0.1, help=t["taxa_adq_ajuda"]
    )
    taxa_ant = st.number_input(
        t["taxa_ant"], 0.0, 10.0, 1.99, 0.01, help=t["taxa_ant_ajuda"]
    )
    tabela = TabelaCustos(
        taxa_adquirencia=Decimal(str(taxa_adq)) / 100,
        taxa_antecipacao_mensal=Decimal(str(taxa_ant)) / 100,
    )
    atividade = st.selectbox(
        t["atividade"],
        ["comercio", "industria", "servicos"],
        format_func=lambda a: ATIVIDADES[lang][a],
    )

if upload is None and not caminho_arquivo:
    st.warning(t["aviso_demo"])

if monitorar and caminho_arquivo:
    # Vigia o arquivo apontado: quando o mtime muda (a pessoa salvou a
    # planilha), dispara um rerun completo — os números se atualizam
    # sozinhos. Roda como fragment para custar quase nada entre reruns.
    @st.fragment(run_every="3s")
    def _vigiar_arquivo():
        from pathlib import Path

        try:
            mtime = Path(caminho_arquivo).stat().st_mtime
        except OSError:
            return
        if st.session_state.get("_mtime_arquivo") != mtime:
            st.session_state["_mtime_arquivo"] = mtime
            st.rerun(scope="app")

    _vigiar_arquivo()

# Rastreabilidade: o nome do arquivo real alimenta a linhagem de dados.
if upload is not None:
    origem_dados = upload.name
elif caminho_arquivo:
    origem_dados = caminho_arquivo
else:
    origem_dados = (
        "dados sintéticos de exemplo" if lang == "pt" else "synthetic sample data"
    )

# Motores rodam uma vez por (dados, config) via cache; a fachada fica
# disponível para as ações sob demanda (simular, preço, PDF, copiloto).
res = _resultados_cacheados(tuple(transacoes), config, tabela, atividade, origem_dados)
analise = AnalisadorMargem(
    transacoes,
    config,
    tabela,
    ParametrosDiagnostico(atividade=atividade),
    retriever=_retriever_cacheado(),
    origem=origem_dados,
)
decomposicao = res["decomposicao"]
resumo = res["resumo"]

(
    aba_resumo,
    aba_vendas,
    aba_historico,
    aba_ese,
    aba_crescer,
    aba_caixa,
    aba_diagnostico,
    aba_relatorio,
) = st.tabs(t["abas"])

# ---------------------------------------------------------------------------
with aba_resumo:
    if lang == "pt":
        st.info(resumo.frase())
    else:
        maior = resumo.maior_fonte
        st.info(
            f"Over {resumo.meses} month(s), {_brl(resumo.perda_total)} of "
            f"margin was lost between the head-math margin "
            f"({resumo.margem_anunciada_pct}%) and the real one "
            f"({resumo.margem_real_pct}%); "
            f"{maior.pct_da_perda.quantize(Decimal('1'))}% of that came "
            f"from {ROTULOS_EN.get(maior.nome, maior.rotulo)}."
        )
    col1, col2, col3 = st.columns(3)
    col1.metric(t["faturou"], _brl(resumo.receita_bruta))
    col2.metric(t["sobrou"], _brl(resumo.margem_real), f"{resumo.margem_real_pct}%")
    col3.metric(
        t["foi_embora"],
        _brl(resumo.perda_total + decomposicao.deducao("cmv").valor),
    )

    st.subheader(t["para_onde"])
    evento = st.altair_chart(
        _grafico_cachoeira(decomposicao, rotulos, t),
        use_container_width=True,
        on_select="rerun",
        key="cachoeira",
    )
    clicados = [
        p.get("nome")
        for p in (evento.selection.get("ponto") or [])
        if p.get("nome") not in (None, "receita", "margem")
    ]
    if clicados:
        nome_drill = clicados[0]
        comp = _composicao_cacheada(tuple(transacoes), config, tabela, nome_drill)
        rotulo_drill = rotulos.get(nome_drill, nome_drill)
        st.markdown(f"##### {t['drill_titulo'].format(rotulo=rotulo_drill)}")
        col_canal, col_mes = st.columns(2)
        with col_canal:
            st.caption(t["drill_por_canal"])
            if comp["por_canal"]:
                st.altair_chart(
                    _grafico_barras_h(
                        [
                            {
                                "rotulo": canal,
                                "valor": float(v),
                                "texto": _brl_inteiro(v),
                            }
                            for canal, v in comp["por_canal"]
                        ]
                    ),
                    use_container_width=True,
                )
            else:
                st.info(t["drill_sem_canal"])
        with col_mes:
            st.caption(t["drill_por_mes"])
            st.altair_chart(
                _grafico_barras_v(
                    [
                        {"rotulo": mes, "valor": float(v), "texto": _brl_inteiro(v)}
                        for mes, v in comp["por_mes"]
                    ]
                ),
                use_container_width=True,
            )
    else:
        st.caption(t["cachoeira_dica"])

    st.subheader(t["radar_titulo"])
    st.caption(t["radar_caption"])
    radar = res["radar"]
    if not radar:
        st.success(t["radar_vazio"])
    estilo_sev = {
        "critico": st.error,
        "atencao": st.warning,
        "oportunidade": st.success,
    }
    for sinal in radar:
        estilo_sev[sinal.severidade](
            f"**{t['radar_sev'][sinal.severidade]} · {sinal.titulo}** — "
            f"~{_brl(sinal.impacto_mensal)}/{t['por_mes']} "
            f"[{sinal.confianca}]\n\n{sinal.explicacao}"
        )
        st.caption(sinal.caminho_pratico)
    anomalias = res["anomalias"]
    if anomalias:
        st.markdown(f"**{t['anom_titulo']}**")
        for anomalia in anomalias:
            estilo_sev[anomalia.severidade](
                f"**{t['radar_sev'][anomalia.severidade]} · {anomalia.titulo}** "
                f"— ~{_brl(anomalia.impacto_mensal)}/{t['por_mes']}\n\n"
                f"{anomalia.o_que_aconteceu}\n\n"
                f"{t['anom_esperado']}: {anomalia.esperado} · "
                f"{t['anom_observado']}: {anomalia.observado} · "
                f"{t['anom_desvio']}: {anomalia.desvio_pct:+}% · "
                f"{t['fila_confianca']}: {anomalia.confianca.pct}%"
            )
            st.caption(f"{t['anom_metodo']} {anomalia.metodo}")
    st.caption(t["radar_aviso"])

    st.subheader(t["fila_titulo"])
    st.caption(t["fila_caption"])
    recomendacoes = res["recomendacoes"]
    if not recomendacoes:
        st.success(t["sem_acoes"])
    for rec in recomendacoes[:5]:
        with st.container(border=True):
            st.markdown(
                f"**{rec.prioridade}. {rec.problema}** — "
                f"~{_brl(rec.impacto_mensal)}/{t['por_mes']}"
            )
            st.markdown(f"{t['fila_acao']} {rec.acao}")
            st.caption(
                f"{t['fila_confianca']} {rec.confianca.pct}% "
                f"({rec.confianca.nivel}) · {t['fila_esforco']} {rec.esforco} · "
                f"{t['fila_velocidade']} {rec.velocidade} · "
                f"{t['fila_risco']} {rec.risco} · {rec.reversibilidade}"
            )
            with st.expander(t["fila_porque"]):
                st.markdown(rec.justificativa)
                st.markdown(f"_{rec.confianca.frase}_")
                st.markdown(f"**{t['fila_motivos']}**")
                for motivo in rec.confianca.motivos:
                    st.markdown(f"- {motivo}")

    with st.expander(t["lin_titulo"]):
        st.caption(t["lin_caption"])
        fichas = res["linhagem"]
        nome_ficha = st.selectbox(
            t["lin_numero"],
            list(fichas),
            format_func=lambda n: (
                f"{rotulos.get(n, fichas[n].rotulo)} — {_brl(fichas[n].valor)}"
            ),
            key="linhagem_numero",
        )
        ficha = fichas[nome_ficha]
        st.markdown(f"**{t['lin_origem']}:** `{ficha.origem_dados}`")
        st.markdown(f"**{t['lin_colunas']}:** `{'`, `'.join(ficha.colunas)}`")
        st.markdown(f"**{t['lin_formula']}:** {ficha.formula}")
        st.markdown(f"**{t['lin_transf']}:**")
        for transf in ficha.transformacoes:
            st.markdown(f"- {transf}")
        if ficha.premissas:
            st.markdown(f"**{t['lin_premissas']}:**")
            for premissa in ficha.premissas:
                st.markdown(f"- {premissa}")
        if ficha.limitacoes:
            st.markdown(f"**{t['lin_limitacoes']}:**")
            for limitacao in ficha.limitacoes:
                st.markdown(f"- {limitacao}")
        st.caption(
            f"{t['lin_fonte']} {ficha.fonte} · [{ficha.confianca_dados}] · "
            f"{t['lin_quando']} "
            f"{ficha.calculado_em.strftime('%d/%m/%Y %H:%M')}"
        )

    with st.expander(t["como_ler"]):
        st.markdown(t["como_ler_texto"])

# ---------------------------------------------------------------------------
with aba_vendas:
    frame = pd.DataFrame(
        [
            {
                "data": tr.data,
                "produto": tr.produto or "—",
                "canal": tr.canal,
                "valor_bruto": float(tr.valor_bruto),
                "custo_produto": float(tr.custo_produto),
                "frete_pago": float(tr.frete_pago),
                "devolvida": tr.devolvida,
            }
            for tr in transacoes
        ]
    )
    m = t["vendas_metricas"]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(m[0], len(frame))
    col2.metric(m[1], _brl(decomposicao.receita_bruta))
    col3.metric(m[2], frame["canal"].nunique())
    col4.metric(m[3], int(frame["devolvida"].sum()))

    produtos = res["por_produto"]
    campeoes = [p for p in produtos if p.margem > 0][:3]
    viloes = [p for p in produtos if p.margem < 0]

    st.subheader(t["campeoes"])
    st.caption(t["campeoes_caption"])
    colunas = st.columns(max(len(campeoes), 1))
    for coluna, produto in zip(colunas, campeoes, strict=False):
        with coluna, st.container(border=True):
            st.markdown(f"**{produto.nome}**")
            st.metric(
                t["col_margem_pct"],
                f"{produto.margem_pct}%",
                _brl(produto.margem),
            )
            st.caption(f"R$ {produto.margem_pct:.0f} {t['cada_100']}")

    st.subheader(t["viloes"])
    if not viloes:
        st.success(t["sem_viloes"])
    else:
        st.caption(t["viloes_caption"])
        for produto in viloes:
            st.error(
                f"**{produto.nome}** — {produto.vendas}x · "
                f"{_brl(produto.margem)} {t['prejuizo_por_venda']} "
                f"({produto.margem_pct}%)"
            )

    st.subheader(t["tabela_produtos"])
    st.dataframe(
        pd.DataFrame(
            [
                {
                    t["col_produto"]: p.nome,
                    t["col_vendas"]: p.vendas,
                    t["col_devolvidas"]: p.devolvidas,
                    t["col_receita"]: _brl(p.receita),
                    t["col_margem"]: _brl(p.margem),
                    t["col_margem_pct"]: f"{p.margem_pct}%",
                }
                for p in produtos
            ]
        ),
        use_container_width=True,
    )

    st.subheader(t["receita_por_canal"])
    por_canal = frame.groupby("canal")["valor_bruto"].sum()
    st.altair_chart(
        _grafico_barras_h(
            [
                {
                    "rotulo": canal,
                    "valor": float(valor),
                    "texto": _brl_inteiro(Decimal(str(round(valor)))),
                }
                for canal, valor in por_canal.items()
            ]
        ),
        use_container_width=True,
    )

    with st.expander(t["todas_vendas"]):
        if st.toggle(t["margem_por_venda"], value=len(frame) <= 500):
            por_venda = res["por_venda"]
            frame["margem"] = [float(v.margem_liquida) for v in por_venda]
            frame["margem_%"] = [float(v.margem_pct) for v in por_venda]
        st.dataframe(frame, use_container_width=True, height=320)

# ---------------------------------------------------------------------------
with aba_historico:
    st.caption(t["hist_caption"])
    mensal = res["mensal"]
    if len(mensal) < 2:
        st.info(t["hist_um_mes"])
    else:
        meses_lst = list(mensal.items())
        (mes_a, dec_a), (mes_b, dec_b) = meses_lst[-2], meses_lst[-1]
        delta_pp = dec_b.margem_pct - dec_a.margem_pct
        difs = {
            d.nome: (
                dec_b.deducao(d.nome).pct_receita - dec_a.deducao(d.nome).pct_receita
            )
            for d in dec_b.deducoes
        }
        causa = max(difs, key=lambda n: abs(difs[n]))
        modelo = t["hist_frase_melhora"] if delta_pp >= 0 else t["hist_frase_piora"]
        st.info(
            modelo.format(
                m1=mes_a,
                m2=mes_b,
                a=dec_a.margem_pct,
                b=dec_b.margem_pct,
                d=abs(delta_pp),
                causa=rotulos.get(causa, causa),
                ca=dec_a.deducao(causa).pct_receita,
                cb=dec_b.deducao(causa).pct_receita,
            )
        )
        st.subheader(t["hist_comparacao"])
        c1, c2, c3 = st.columns(3)
        c1.metric(
            t["delta_receita"],
            _brl(dec_b.receita_bruta),
            _brl(dec_b.receita_bruta - dec_a.receita_bruta),
        )
        c2.metric(
            t["delta_margem"],
            _brl(dec_b.margem_liquida),
            _brl(dec_b.margem_liquida - dec_a.margem_liquida),
        )
        c3.metric(t["delta_pp"], f"{dec_b.margem_pct}%", f"{delta_pp:+.2f}")

        dec = (lambda v: v.replace(".", ",")) if lang == "pt" else (lambda v: v)
        st.subheader(t["hist_receita"])
        st.altair_chart(
            _grafico_barras_v(
                [
                    {
                        "rotulo": mes,
                        "valor": float(d.receita_bruta),
                        "texto": _brl_inteiro(d.receita_bruta),
                    }
                    for mes, d in mensal.items()
                ]
            ),
            use_container_width=True,
        )
        st.subheader(t["hist_margem"])
        st.altair_chart(
            _grafico_serie(
                [
                    {
                        "rotulo": mes,
                        "valor": float(d.margem_pct),
                        "texto": dec(f"{d.margem_pct}%"),
                    }
                    for mes, d in mensal.items()
                ],
                modo="linha",
            ),
            use_container_width=True,
        )
        st.subheader(t["hist_lucro"])
        st.altair_chart(
            _grafico_serie(
                [
                    {"rotulo": mes, "valor": float(v), "texto": _brl_inteiro(v)}
                    for mes, v in res["lucro"]
                ],
                modo="area",
            ),
            use_container_width=True,
        )

        st.subheader(t["hist_tabela"])
        historico = pd.DataFrame(
            [
                {
                    t["col_mes"]: mes,
                    t["col_receita"]: float(d.receita_bruta),
                    t["col_margem"]: float(d.margem_liquida),
                    t["col_margem_pct"]: float(d.margem_pct),
                    t["col_maior_custo"]: rotulos.get(
                        max(d.deducoes, key=lambda x: x.valor).nome, ""
                    ),
                }
                for mes, d in mensal.items()
            ]
        )
        st.dataframe(historico, use_container_width=True)
        st.download_button(
            t["baixar_hist"],
            data=historico.to_csv(index=False).encode("utf-8"),
            file_name="historico_carchuna.csv",
            mime="text/csv",
        )

# ---------------------------------------------------------------------------
with aba_ese:
    st.caption(t["ese_caption"])
    for resultado in res["cenarios"]:
        with st.container(border=True):
            st.markdown(f"**{resultado.nome}**")
            c1, c2, c3 = st.columns(3)
            c1.metric(t["margem_cenario"], _brl(resultado.cenario.margem_liquida))
            c2.metric(t["impacto_reais"], _brl(resultado.impacto_reais))
            c3.metric(t["impacto_pp"], f"{resultado.impacto_pp:+.2f}")

    st.subheader(t["otim_titulo"])
    st.caption(t["otim_caption"])
    col_o1, col_o2 = st.columns(2)
    elast = col_o1.number_input(
        t["otim_elast"], 0.0, 10.0, 0.0, 0.5, help=t["otim_elast_ajuda"]
    )
    margem_min = col_o2.number_input(t["otim_margem_min"], 0.0, 90.0, 0.0, 1.0)
    col_o3, col_o4 = st.columns(2)
    queda_max = col_o3.number_input(t["otim_queda_max"], 0.0, 100.0, 15.0, 5.0)
    teto_ticket = col_o4.number_input(t["otim_teto"], 0.0, value=0.0, step=10.0)
    otimizador = MotorOtimizacao(
        ParametrosOtimizacao(elasticidade=Decimal(str(elast)) if elast > 0 else None)
    )
    resultado_otim = otimizador.otimizar(
        transacoes,
        config,
        tabela,
        restricoes=Restricoes(
            margem_minima_pct=(Decimal(str(margem_min)) if margem_min > 0 else None),
            queda_maxima_volume=Decimal(str(queda_max)) / 100,
            preco_medio_maximo=(Decimal(str(teto_ticket)) if teto_ticket > 0 else None),
        ),
    )
    if resultado_otim.melhor is not None:
        melhor = resultado_otim.melhor
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric(
            t["otim_melhor"],
            f"{(melhor.delta_preco * 100).quantize(Decimal('1')):+}% · "
            f"{(melhor.fracao_migracao * 100).quantize(Decimal('1'))}%",
        )
        col_m2.metric(t["margem_cenario"], f"{melhor.margem_pct}%")
        col_m3.metric(t["otim_ganho"], _brl(resultado_otim.ganho_mensal))
    st.info(resultado_otim.explicacao)
    for premissa in resultado_otim.premissas:
        st.caption(f"— {premissa}")
    with st.expander(t["otim_grade"]):
        cols = t["otim_col"]
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        cols["preco"]: f"{(c.delta_preco * 100):+.0f}%",
                        cols["migracao"]: f"{(c.fracao_migracao * 100):.0f}%",
                        cols["margem"]: float(c.margem_pct),
                        cols["lucro"]: float(c.lucro_mensal),
                        cols["status"]: ("ok" if c.viavel else "; ".join(c.violacoes)),
                    }
                    for c in resultado_otim.candidatos
                ]
            ),
            use_container_width=True,
            height=300,
        )

# ---------------------------------------------------------------------------
with aba_crescer:
    st.caption(t["crescimento_caption"])
    for oportunidade in res["oportunidades"]:
        with st.container(border=True):
            ganho = _brl(oportunidade.ganho_estimado_mensal)
            st.markdown(
                f"**{oportunidade.titulo}** — ~{ganho}/{t['por_mes']} "
                f"[{oportunidade.confianca}]"
            )
            st.write(oportunidade.explicacao)
            for disp in oportunidade.base_legal:
                st.markdown(
                    f"- **{disp.lei}, {disp.artigo}** — {disp.resumo} "
                    f"[[{t['fonte_oficial']}]({disp.fonte})]"
                )
            st.markdown(f"**{t['caminho']}** {oportunidade.caminho_pratico}")

    st.subheader(t["simular_canal"])
    col_c1, col_c2 = st.columns(2)
    canal_cresc = col_c1.selectbox(
        t["canal"], sorted({tr.canal for tr in transacoes}), key="canal_cresc"
    )
    pct_cresc = col_c2.slider(t["crescimento_vendas"], 5, 100, 20, 5)
    try:
        simulacao = analise.simular(
            CenarioCrescimentoCanal(canal_cresc, Decimal(pct_cresc) / 100)
        )
        c1, c2, c3 = st.columns(3)
        c1.metric(t["margem_hoje"], _brl(simulacao.base.margem_liquida))
        c2.metric(t["margem_cenario"], _brl(simulacao.cenario.margem_liquida))
        c3.metric(t["ganho"], _brl(simulacao.impacto_reais))
    except ValueError as erro:
        st.warning(str(erro))

    st.subheader(t["calculadora"])
    st.caption(t["calculadora_caption"])
    col_p1, col_p2, col_p3, col_p4 = st.columns(4)
    calc_custo = col_p1.number_input(t["custo_produto"], 0.01, 100000.0, 40.0)
    calc_frete = col_p2.number_input(t["frete"], 0.0, 10000.0, 10.0)
    calc_canal = col_p3.selectbox(
        t["canal_venda"],
        ["mercado_livre", "shopee", "amazon", "loja_propria", "fisico"],
        key="calc_canal",
    )
    calc_margem = col_p4.number_input(t["margem_alvo"], 0.0, 60.0, 10.0, 1.0)
    try:
        equilibrio = analise.preco_sugerido(
            Decimal(str(calc_custo)),
            Decimal(str(calc_frete)),
            calc_canal,
            Decimal("0"),
        )
        alvo = analise.preco_sugerido(
            Decimal(str(calc_custo)),
            Decimal(str(calc_frete)),
            calc_canal,
            Decimal(str(calc_margem)) / 100,
        )
        col_r1, col_r2 = st.columns(2)
        col_r1.metric(t["preco_equilibrio"], _brl(equilibrio))
        col_r2.metric(t["preco_para"].format(pct=f"{calc_margem:.0f}"), _brl(alvo))
    except ValueError as erro:
        st.error(str(erro))
    st.subheader(t["bench_titulo"])
    st.caption(t["bench_caption"])
    ref_margem = st.number_input(t["bench_sua_ref"], 0.0, 90.0, 0.0, 0.5)
    comparacoes = comparar_benchmarks(
        transacoes,
        config,
        tabela,
        referencias_usuario=(
            {"margem_liquida_pct": Decimal(str(ref_margem))} if ref_margem > 0 else None
        ),
    )
    for bench in comparacoes:
        with st.container(border=True):
            if bench.referencia is None:
                st.markdown(f"**{bench.rotulo}** — {bench.valor_usuario}")
            else:
                st.markdown(
                    f"**{bench.rotulo}** — {bench.valor_usuario} · "
                    f"{bench.referencia} · {bench.diferenca}"
                )
            st.write(bench.leitura)
            st.caption(f"[{bench.tipo_fonte}] {t['bench_fonte']} {bench.fonte}")

    st.caption(AVISO_CRESCIMENTO)

# ---------------------------------------------------------------------------
with aba_caixa:
    st.caption(t["caixa_caption"])
    col_cx1, col_cx2 = st.columns(2)
    caixa_inicial = col_cx1.number_input(
        t["caixa_inicial"], min_value=0.0, value=0.0, step=500.0, format="%.2f"
    )
    saidas_mensais = col_cx2.number_input(
        t["caixa_saidas"],
        min_value=0.0,
        value=0.0,
        step=500.0,
        format="%.2f",
        help=t["caixa_saidas_ajuda"],
    )
    projecao = projetar_caixa(
        transacoes,
        tabela,
        caixa_inicial=Decimal(str(caixa_inicial)),
        saidas_mensais=Decimal(str(saidas_mensais)),
    )
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric(t["caixa_recebs"], _brl(projecao.recebimentos_no_horizonte))
    col_m2.metric(t["caixa_saidas_metric"], _brl(projecao.saidas_no_horizonte))
    col_m3.metric(
        t["caixa_folego"],
        (
            t["caixa_folego_ok"]
            if projecao.dias_de_folego is None
            else t["caixa_dias"].format(dias=projecao.dias_de_folego)
        ),
    )
    if projecao.dia_negativo is not None:
        st.error(
            t["caixa_alerta"].format(
                dias=projecao.dias_de_folego,
                data=projecao.dia_negativo.strftime("%d/%m/%Y"),
            )
        )
    else:
        st.success(t["caixa_ok"])

    st.subheader(t["caixa_curva"])
    st.altair_chart(
        _grafico_caixa(projecao.curva, projecao.dia_negativo),
        use_container_width=True,
    )
    st.caption(t["caixa_etiquetas"])

    intel = analisar_caixa(
        projecao, agenda_recebimentos(transacoes, tabela, a_partir_de=projecao.hoje)
    )
    st.subheader(t["cx_janelas"])
    colunas_janela = st.columns(max(len(intel.janelas), 1))
    for coluna, janela in zip(colunas_janela, intel.janelas, strict=False):
        coluna.metric(
            f"{janela.dias}d",
            _brl(janela.saldo_final),
            (
                f"+{_brl(janela.entradas)} {t['cx_entra']} · "
                f"−{_brl(janela.saidas)} {t['cx_sai']}"
            ),
            delta_color="off",
        )
    for alerta in intel.alertas:
        st.warning(alerta)

# ---------------------------------------------------------------------------
with aba_diagnostico:
    st.caption(t["diag_caption"])
    retriever = analise.retriever
    st.warning(retriever.aviso_corpus)

    st.subheader(t["vazamentos"])
    achados = res["achados"]
    if not achados:
        st.success(t["sem_achados"])
    for achado in achados:
        with st.expander(
            f"{achado.titulo} — ~{_brl(achado.impacto_mensal)}"
            f"/{t['por_mes']} [{achado.confianca}]"
        ):
            st.write(achado.explicacao)
            st.markdown(f"**{t['base_legal']}**")
            for disp in achado.base_legal:
                pendente = "" if disp.revisado else t["pendente"]
                st.markdown(
                    f"- **{disp.lei}, {disp.artigo}**{pendente} — {disp.resumo} "
                    f"[[{t['fonte_oficial']}]({disp.fonte})]"
                )
            st.markdown(f"**{t['caminho']}** {achado.caminho_pratico}")
            st.caption(achado.aviso)

    st.subheader(t["pergunte"])
    pergunta = st.text_input(t["pergunta_exemplo"])
    if pergunta:
        # O copiloto tenta primeiro: perguntas numéricas ("por que meu
        # lucro caiu em junho?") são respondidas pelos motores testados,
        # com os números expostos; o que não é numérico segue para o RAG
        # legal de sempre. O LLM nunca calcula — só o motor.
        resposta_copiloto = Copiloto(analise).responder(pergunta)
        if resposta_copiloto is not None:
            st.info(resposta_copiloto.texto)
            with st.expander(t["cop_dados"]):
                for chave, valor in resposta_copiloto.dados.items():
                    st.markdown(f"- `{chave}`: {valor}")
            st.caption(resposta_copiloto.aviso)
        else:
            dispositivos = retriever.buscar(pergunta)
            resposta = gerar_resposta(pergunta, dispositivos)
            if resposta is None:
                resposta = resposta_extrativa(pergunta, dispositivos)
                st.caption(t["modo_extrativo"])
            st.write(resposta)

# ---------------------------------------------------------------------------
with aba_relatorio:
    st.caption(t["relatorio_caption"])
    if st.button(t["gerar_pdf"]):
        buffer = io.BytesIO()
        analise.gerar_pdf(buffer)
        st.download_button(
            t["baixar_pdf"],
            data=buffer.getvalue(),
            file_name="relatorio_carchuna.pdf",
            mime="application/pdf",
        )
    st.caption(AVISO_LEGAL)
