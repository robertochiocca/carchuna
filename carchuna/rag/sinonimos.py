"""Dicionário de sinônimos do lojista → vocabulário da lei e do mercado.

Mesmo papel do dicionário do cidadão no DireitoAberto, trocado para o
PT-BR de quem vende: "maquininha" vira "adquirência", "ML" vira
"Mercado Livre", "antecipar" vira "antecipação de recebíveis". Aplicado
apenas na consulta (expansão de query), nunca no corpus.
"""

from __future__ import annotations

SINONIMOS_LOJISTA: dict[str, list[str]] = {
    # pagamentos / adquirência
    "maquininha": ["adquirência", "credenciadora", "cartão", "tarifa", "pagamento"],
    "maquineta": ["adquirência", "credenciadora", "cartão", "tarifa"],
    "pos": ["adquirência", "cartão", "maquininha"],
    "adquirente": ["adquirência", "credenciadora", "instituição", "pagamento"],
    "antecipar": ["antecipação", "recebíveis", "agenda", "taxa"],
    "antecipação": ["recebíveis", "agenda", "registro", "taxa"],
    "recebiveis": ["antecipação", "agenda", "registro", "cartão"],
    "trava": ["recebíveis", "agenda", "registro", "garantia"],
    "split": ["repasse", "arranjo", "pagamento", "marketplace"],
    "repasse": ["split", "marketplace", "comissão", "retenção"],
    "chargeback": ["fraude", "estorno", "cartão", "cobrança", "indevida"],
    "estorno": ["restituição", "devolução", "cobrança", "indevida"],
    "pix": ["banco", "fraude", "transferência", "pagamento"],
    "golpe": ["fraude", "banco", "responsabilidade"],
    "clonaram": ["fraude", "cartão", "banco", "responsabilidade"],
    # marketplaces
    "ml": ["mercado", "livre", "marketplace", "comissão"],
    "mercadolivre": ["mercado", "livre", "marketplace", "comissão"],
    "shopee": ["marketplace", "comissão", "tarifa"],
    "amazon": ["marketplace", "comissão", "tarifa"],
    "magalu": ["marketplace", "comissão", "tarifa"],
    "plataforma": ["marketplace", "contrato", "adesão"],
    "comissão": ["tarifa", "marketplace", "retenção", "repasse"],
    "tarifa": ["comissão", "taxa", "cobrança"],
    "retiveram": ["retenção", "repasse", "cláusula", "contrato"],
    "retenção": ["repasse", "cláusula", "contrato", "abusiva"],
    "glosa": ["cobrança", "indevida", "retenção", "restituição"],
    "glosada": ["cobrança", "indevida", "retenção", "restituição", "nota"],
    # tributário / Simples
    "das": ["simples", "nacional", "guia", "recolhimento", "boleto"],
    "guia": ["das", "simples", "recolhimento"],
    "imposto": ["tributo", "alíquota", "simples", "recolhimento"],
    "simples": ["nacional", "anexo", "alíquota", "lc", "123"],
    "mei": ["microempreendedor", "individual", "limite", "das", "fixo"],
    "anexo": ["enquadramento", "atividade", "alíquota", "faixa", "simples"],
    "cnae": ["atividade", "enquadramento", "anexo"],
    "aliquota": ["efetiva", "nominal", "faixa", "fórmula", "rbt12"],
    "faturamento": ["receita", "bruta", "rbt12", "limite"],
    "teto": ["limite", "receita", "exclusão", "sublimite"],
    "estourar": ["exclusão", "limite", "teto", "desenquadramento"],
    "desenquadrar": ["exclusão", "desenquadramento", "limite", "simples"],
    "sair": ["exclusão", "desenquadramento", "simples"],
    "restituir": ["restituição", "recuperar", "indébito", "repetição"],
    "recuperar": ["restituição", "indébito", "pago", "maior", "prazo"],
    "errado": ["erro", "alíquota", "anexo", "restituição", "indevido"],
    "contador": ["restituição", "enquadramento", "anexo", "apuração"],
    # consumidor / devoluções
    "devolução": ["arrependimento", "restituição", "devolvida", "cancelada"],
    "devolveu": ["arrependimento", "devolução", "restituição"],
    "arrependeu": ["arrependimento", "sete", "dias", "devolução"],
    "cancelou": ["cancelada", "devolução", "reembolso", "arrependimento"],
    "reembolso": ["restituição", "devolução", "arrependimento"],
    "cliente": ["consumidor", "arrependimento", "devolução"],
    "frete": ["arrependimento", "devolução", "reembolso"],
    # dados / operação
    "dados": ["lgpd", "pessoais", "tratamento", "consentimento"],
    "vazamento": ["lgpd", "dados", "segurança", "responsabilidade"],
    "cadastro": ["dados", "pessoais", "lgpd", "cliente"],
    "site": ["e-commerce", "loja", "virtual", "eletrônico", "cnpj"],
    "loja": ["e-commerce", "virtual", "fornecedor", "comércio"],
    # contratos
    "contrato": ["cláusula", "adesão", "abusiva", "equilíbrio"],
    "abusiva": ["cláusula", "nula", "prática", "vantagem"],
    "casada": ["venda", "condicionar", "prática", "abusiva"],
    "obrigaram": ["condicionar", "venda", "casada", "abusiva"],
    "banco": ["instituição", "financeira", "fraude", "tarifa"],
}
