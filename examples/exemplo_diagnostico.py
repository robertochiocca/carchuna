"""Exemplo completo da Carchuna, 100% offline com dados sintéticos.

Mostra o fluxo do produto na ordem da review: importar → reconstruir a
margem (inclusive venda a venda) → resumo executivo → simulação →
explicação legal. Tudo via fachada :class:`AnalisadorMargem`.

Uso::

    python examples/exemplo_diagnostico.py
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carchuna import AnalisadorMargem, ConfigTributaria, TabelaCustos

# Lojista típico do público-alvo: fatura ~R$60k/mês no Anexo I, mas foi
# configurado (de propósito, para o exemplo) com antecipação cara.
analise = AnalisadorMargem.demo(
    meses=6,
    config=ConfigTributaria(
        regime="simples", anexo_simples="I", rbt12=Decimal("750000")
    ),
    tabela=TabelaCustos(taxa_antecipacao_mensal=Decimal("0.029")),
)

d = analise.decomposicao
print("=== Raio-X da margem (6 meses sintéticos) ===")
print(f"Receita bruta   : R$ {d.receita_bruta:>14,.2f}")
for deducao in d.deducoes:
    print(
        f"(-) {deducao.nome:<16}: R$ {deducao.valor:>14,.2f}"
        f"  ({deducao.pct_receita:>6}%)  [{deducao.confianca}]"
    )
print(f"(=) margem líquida: R$ {d.margem_liquida:>14,.2f}  ({d.margem_pct}%)")
print(f"Alíquota efetiva do Simples: {(d.aliquota_efetiva * 100):.4f}%")

print("\n=== Resumo executivo ===")
resumo = analise.resumo_executivo()
print(resumo.frase())
for fonte in resumo.fontes_perda:
    print(f"  {fonte.rotulo:<24} R$ {fonte.valor:>12,.2f}  ({fonte.pct_da_perda}%)")

print("\n=== Margem venda a venda (3 primeiras) ===")
for venda in analise.margem_por_venda()[:3]:
    t = venda.transacao
    print(
        f"  {t.data} {t.canal:<14} bruto R$ {t.valor_bruto:>7,.2f} → "
        f"margem R$ {venda.margem_liquida:>7,.2f} ({venda.margem_pct}%)"
    )

print(f"\nMaior queda de margem : {analise.maior_queda()} p.p.")
print(f"Instabilidade         : {analise.instabilidade()} p.p.")

print("\n=== Cenários de stress e simulações ===")
for cenario in analise.cenarios():
    print(
        f"- {cenario.nome}: impacto R$ {cenario.impacto_reais:,.2f} "
        f"({cenario.impacto_pp:+.2f} p.p.)"
    )

print("\n=== Crescimento: como faturar mais, com prova ===")
for oportunidade in analise.crescimento():
    print(f"\n[{oportunidade.tipo} · {oportunidade.confianca}] {oportunidade.titulo}")
    print(f"  ganho estimado ~R$ {oportunidade.ganho_estimado_mensal:,.2f}/mês")
    print(f"  {oportunidade.explicacao}")
    print(f"  caminho: {oportunidade.caminho_pratico}")
preco = analise.preco_sugerido(Decimal("40"), Decimal("10"), "mercado_livre")
print(
    f"\nCalculadora de preço: custo 40 + frete 10 no ML → R$ {preco} p/ 10% de margem"
)

print("\n=== Diagnóstico legal (a IA entra depois do cálculo) ===")
achados = analise.diagnosticar()
if not achados:
    print("Nenhum vazamento detectado pelas regras da v1.")
for achado in achados:
    print(f"\n[{achado.tipo} · {achado.confianca}] {achado.titulo}")
    print(f"  impacto ~R$ {achado.impacto_mensal:,.2f}/mês")
    print(f"  {achado.explicacao}")
    for disp in achado.base_legal[:2]:
        print(f"  base legal: {disp.lei}, {disp.artigo} — {disp.fonte}")
    print(f"  caminho: {achado.caminho_pratico}")
    print(f"  aviso: {achado.aviso}")
