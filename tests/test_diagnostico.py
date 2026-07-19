"""Testes das 4 regras de detecção do diagnóstico (heurísticas transparentes)."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.diagnostico import ParametrosDiagnostico, diagnosticar
from carchuna.margem import ConfigTributaria, TabelaCustos, Transacao
from carchuna.rag.retrieval import Retriever

RETRIEVER = Retriever()  # índice construído uma vez para a suíte toda

CONFIG_OK = ConfigTributaria(
    regime="simples", anexo_simples="I", rbt12=Decimal("360000")
)


def _venda(valor="1000", canal="mercado_livre", **kwargs):
    padrao = dict(
        data=date(2026, 5, 15),
        canal=canal,
        valor_bruto=Decimal(valor),
        custo_produto=Decimal("0"),
        frete_pago=Decimal("0"),
    )
    padrao.update(kwargs)
    return Transacao(**padrao)


def _diagnosticar(vendas, config=CONFIG_OK, tabela=None, parametros=None):
    return diagnosticar(vendas, config, tabela, parametros, RETRIEVER)


def test_dados_saudaveis_nao_geram_achados():
    achados = _diagnosticar([_venda()])
    assert achados == []


def test_regra_anexo_errado_com_impacto_calculado_a_mao():
    """Comércio no Anexo III: efetiva 8,60% vs 5,65% → 29,50 a maior em 1000."""
    config = ConfigTributaria(
        regime="simples", anexo_simples="III", rbt12=Decimal("360000")
    )
    (achado,) = _diagnosticar([_venda("1000")], config)
    assert achado.tipo == "tributario"
    assert achado.confianca == "calculado"
    # (0,086 − 0,0565) × 1000 = 29,50 em um único mês
    assert achado.impacto_mensal == Decimal("29.50")
    assert achado.base_legal, "todo achado cita base legal recuperada do corpus"
    ids = {d.id for d in achado.base_legal}
    assert "ctn-165" in ids or "lc123-atividades-anexos" in ids
    assert "contador" in achado.caminho_pratico
    assert "não" in achado.aviso.lower() or "Confirme" in achado.aviso


def test_regra_anexo_de_aliquota_menor_vira_alerta_de_risco():
    """Serviços recolhendo no Anexo I (mais barato): risco, não economia."""
    config = ConfigTributaria(
        regime="simples", anexo_simples="I", rbt12=Decimal("360000")
    )
    parametros = ParametrosDiagnostico(atividade="servicos")
    achados = _diagnosticar([_venda("1000")], config, parametros=parametros)
    assert any("autuação" in a.explicacao for a in achados)


def test_regra_antecipacao_acima_da_mediana():
    """Taxa 3% vs mediana 1,6%: excesso = 30 × (0,014/0,03) = 14,00/mês."""
    venda = _venda("1000", canal="loja_propria", prazo_recebimento_dias=30)
    tabela = TabelaCustos(taxa_antecipacao_mensal=Decimal("0.03"))
    achados = _diagnosticar([venda], tabela=tabela)
    (achado,) = [a for a in achados if a.tipo == "financeiro"]
    assert achado.impacto_mensal == Decimal("14.00")
    assert achado.confianca == "estimado"  # mediana é régua editável
    assert any(d.id == "cmn-4734" for d in achado.base_legal)


def test_regra_antecipacao_nao_dispara_sem_volume_antecipado():
    tabela = TabelaCustos(taxa_antecipacao_mensal=Decimal("0.03"))
    achados = _diagnosticar([_venda("1000")], tabela=tabela)  # ML, sem antecipação
    assert all(a.tipo != "financeiro" for a in achados)


def test_regra_devolucoes_acima_do_limiar():
    """1500 de receita, 500 devolvidos (33%) > 3%: excesso = 500 − 45 = 455."""
    vendas = [_venda("1000"), _venda("500", devolvida=True)]
    achados = _diagnosticar(vendas)
    (achado,) = [a for a in achados if a.tipo == "operacional"]
    assert achado.impacto_mensal == Decimal("455.00")
    assert any(d.id == "cdc-49" for d in achado.base_legal)


def test_regra_comissao_divergente_do_extrato():
    """ML: cobrado 200 vs tabela 12% de 1000 = 120 → divergência 80/mês."""
    vendas = [_venda("1000", comissao_cobrada=Decimal("200"))]
    achados = _diagnosticar(vendas)
    (achado,) = [a for a in achados if a.tipo == "contratual"]
    assert achado.impacto_mensal == Decimal("80.00")
    assert "mercado_livre" in achado.titulo


def test_regra_comissao_respeita_tolerancia():
    """Divergência de 10 < tolerância de 50 → sem ruído."""
    vendas = [_venda("1000", comissao_cobrada=Decimal("130"))]
    achados = _diagnosticar(vendas)
    assert all(a.tipo != "contratual" for a in achados)


def test_achados_ordenados_por_impacto():
    vendas = [
        _venda("1000", comissao_cobrada=Decimal("200")),
        _venda("500", devolvida=True),
    ]
    achados = _diagnosticar(vendas)
    impactos = [a.impacto_mensal for a in achados]
    assert impactos == sorted(impactos, reverse=True)


def test_parametros_validam_atividade():
    with pytest.raises(ValueError, match="atividade"):
        ParametrosDiagnostico(atividade="mineracao")
    with pytest.raises(ValueError, match="transacoes"):
        diagnosticar([], CONFIG_OK, retriever=RETRIEVER)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
