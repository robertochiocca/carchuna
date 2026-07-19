"""Exemplo completo da Carchuna, 100% offline com dados sintéticos.

Uso::

    python examples/exemplo_diagnostico.py
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carchuna import (
    ConfigTributaria,
    ParametrosDiagnostico,
    TabelaCustos,
    decompor_margem,
    diagnosticar,
    instabilidade_margem,
    maior_queda_margem,
    margem_mensal,
    rodar_cenarios_padrao,
    serie_margem_pct,
    transacoes_sinteticas,
)

# Lojista típico do público-alvo: fatura ~R$400k/mês no Anexo I, mas foi
# configurado (de propósito, para o exemplo) com antecipação cara.
transacoes = transacoes_sinteticas(meses=6)
config = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("4200000"))
tabela = TabelaCustos(taxa_antecipacao_mensal=Decimal("0.029"))

d = decompor_margem(transacoes, config, tabela)
print("=== Raio-X da margem (6 meses sintéticos) ===")
print(f"Receita bruta   : R$ {d.receita_bruta:>14,.2f}")
for deducao in d.deducoes:
    print(
        f"(-) {deducao.nome:<16}: R$ {deducao.valor:>14,.2f}"
        f"  ({deducao.pct_receita:>6}%)  [{deducao.confianca}]"
    )
print(f"(=) margem líquida: R$ {d.margem_liquida:>14,.2f}  ({d.margem_pct}%)")
print(f"Alíquota efetiva do Simples: {(d.aliquota_efetiva * 100):.4f}%")

serie = serie_margem_pct(margem_mensal(transacoes, config, tabela))
print(f"\nMaior queda de margem : {maior_queda_margem(serie)} p.p.")
print(f"Instabilidade         : {instabilidade_margem(serie)} p.p.")

print("\n=== Cenários de stress ===")
for cenario in rodar_cenarios_padrao(transacoes, config, tabela):
    print(
        f"- {cenario.nome}: impacto R$ {cenario.impacto_reais:,.2f} "
        f"({cenario.impacto_pp:+.2f} p.p.)"
    )

print("\n=== Diagnóstico legal ===")
achados = diagnosticar(
    transacoes, config, tabela, ParametrosDiagnostico(atividade="comercio")
)
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
