"""Status de devolução em português, dentro do export cru da Shopee.

Este arquivo existe no encontro de duas metades que nasceram separadas:

- a ingestão aprendeu a ler o relatório como o lojista baixa do canal
  (cp1252, linhas de título antes do cabeçalho, `;`, vírgula decimal) e a
  recusar linha por linha, com motivo, em vez de derrubar o arquivo;
- a coluna de devolução do marketplace aprendeu que ela é um STATUS
  ("Solicitação aprovada", "Em análise"), não um booleano — e que estado
  intermediário não vira sim/não em silêncio.

Separadas, cada metade passa nos seus testes. Juntas é que aparece a
pergunta que interessa: o que acontece quando o arquivo cru traz status
ambíguo? A resposta que este arquivo fixa é *linha recusada com motivo*,
nunca exceção que estoura a importação inteira.

O arquivo de teste é derivado do export cru de verdade
(`fixtures/reais/shopee_pedidos_cru.csv`): só a coluna `Devolução` é
trocada, e todo o resto da bagunça — encoding, títulos, separador,
decimal, a linha de data vazia — vem do arquivo original. Leia o
`PROCEDENCIA.md` daquela pasta antes de tomar a fixture por export real.
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.dados import ler_linhas_brutas, relatorio_de_mapa, sugerir_mapeamento

SHOPEE = Path(__file__).parent / "fixtures" / "reais" / "shopee_pedidos_cru.csv"

# O que cada pedido do relatório passa a trazer na coluna `Devolução`.
# Cobre as quatro situações que o lojista encontra no painel: conclusiva
# nos dois sentidos, célula vazia, booleano antigo e estado intermediário.
_STATUS_POR_PEDIDO = {
    "2605010001": "Solicitação recusada",  # conclusivo: NÃO é devolução
    "2605020002": "Não",  # booleano antigo, tem que seguir funcionando
    "2605030003": "Solicitação aprovada",  # conclusivo: É devolução
    "2605040004": "",  # ausente ≠ inválido: venda normal
    "2605050005": "Solicitação aprovada",  # esta linha já cai pela data vazia
    "2605060006": "Em análise",  # intermediário: ninguém decide por ele
}


@pytest.fixture
def shopee_com_status(tmp_path) -> Path:
    """O export cru de verdade, com a coluna de devolução em status."""
    original = SHOPEE.read_bytes().decode("cp1252")
    saida = []
    for linha in original.split("\n"):
        pedido = linha.split(";")[0]
        if pedido in _STATUS_POR_PEDIDO:
            campos = linha.split(";")
            campos[-1] = _STATUS_POR_PEDIDO[pedido]
            linha = ";".join(campos)
        saida.append(linha)
    destino = tmp_path / "shopee_pedidos_cru.csv"
    # cp1252 de novo: o arquivo derivado tem que ser tão cru quanto o original
    destino.write_bytes("\n".join(saida).encode("cp1252"))
    return destino


def _importar(caminho: Path, interpretacao=None):
    """Sobe o arquivo pelo caminho do dashboard: mapeador + relatório."""
    linhas = ler_linhas_brutas(caminho)
    mapa = sugerir_mapeamento(sorted({c for lin in linhas for c in lin}))
    # o relatório do marketplace não traz nem canal nem CMV: o lojista fixa
    mapa["canal"] = "=shopee"
    mapa["custo_produto"] = "=40.00"
    return relatorio_de_mapa(
        linhas,
        {campo: origem for campo, origem in mapa.items() if origem},
        interpretacao_devolvida=interpretacao,
    )


def test_status_conclusivo_vira_devolucao_e_ambiguo_vira_linha_recusada(
    shopee_com_status,
):
    """A metade de cada árvore, funcionando na mesma importação.

    Quatro vendas entram (89,90 + 129,90 + 249,90 + 349,00 = 818,70) e
    duas ficam de fora, cada uma pelo seu motivo: a de data vazia, que já
    era recusada antes, e a de status intermediário, que é o caso novo.
    """
    resultado = _importar(shopee_com_status)

    assert len(resultado.transacoes) == 4
    assert sum(t.valor_bruto for t in resultado.transacoes) == Decimal("818.70")

    # "Solicitação recusada" e a célula vazia NÃO são devolução;
    # "Solicitação aprovada" é; "Não" continua valendo como antes.
    assert [t.devolvida for t in resultado.transacoes] == [False, False, True, False]

    por_numero = {r.numero: r for r in resultado.rejeitadas}
    assert sorted(por_numero) == [6, 7]
    assert "`data`" in por_numero[6].motivo
    assert "Em análise" in por_numero[7].motivo
    assert "status intermediário" in por_numero[7].motivo
    assert "não" in por_numero[7].motivo and "adivinha" in por_numero[7].motivo
    # a mensagem ensina o caminho, em vez de só reclamar
    assert "mapeador" in por_numero[7].motivo


def test_a_importacao_nao_estoura_por_causa_do_status_ambiguo(shopee_com_status):
    """O ponto de fusão: semântica de status DENTRO do relatório de recusadas.

    Antes deste encontro havia duas saídas possíveis, as duas ruins: ou a
    linha ambígua virava `False` em silêncio (e a devolução sumia da
    conta), ou a exceção derrubava o arquivo inteiro por causa de uma
    linha. Aqui ela vira uma linha listada, e as outras quatro entram.
    """
    resultado = _importar(shopee_com_status)

    assert resultado.total_lidas == 6
    assert len(resultado.rejeitadas) == 2
    resumo = resultado.resumo()
    assert "4 vendas importadas" in resumo
    assert "2 de 6 linhas ficaram de fora" in resumo


def test_o_lojista_decide_e_a_linha_ambigua_entra(shopee_com_status):
    """Quem decide o que é "Em análise" é o lojista, não a Carchuna."""
    resultado = _importar(shopee_com_status, interpretacao={"em analise": True})

    assert len(resultado.transacoes) == 5
    assert sum(t.valor_bruto for t in resultado.transacoes) == Decimal("908.60")
    # só a de data vazia continua de fora
    (rejeitada,) = resultado.rejeitadas
    assert rejeitada.numero == 6

    devolvidas = [t for t in resultado.transacoes if t.devolvida]
    assert sorted(t.valor_bruto for t in devolvidas) == [
        Decimal("89.90"),
        Decimal("249.90"),
    ]


def test_o_texto_original_do_status_fica_guardado(shopee_com_status):
    """`devolucao_status` é linhagem: o que o arquivo dizia, como dizia."""
    resultado = _importar(shopee_com_status)

    status = [t.devolucao_status for t in resultado.transacoes]
    assert status == ["Solicitação recusada", "Não", "Solicitação aprovada", None]
    # célula vazia é dado FALTANDO, não o texto vazio
    assert resultado.transacoes[3].devolucao_status is None


def test_o_status_atravessa_ate_a_deducao_de_devolucoes_do_motor(shopee_com_status):
    """Ponta a ponta: "Solicitação aprovada" vira R$ 249,90 de devolução.

    Este é o número que fecha o merge. O texto em português saiu do
    relatório cru da Shopee, passou pelo léxico de devolução, virou o
    booleano do motor e reapareceu como uma linha de dedução no raio-X —
    com a invariante contábil da casa fechando centavo a centavo.
    """
    from carchuna.analise import AnalisadorMargem
    from carchuna.margem import ConfigTributaria

    resultado = _importar(shopee_com_status)
    analise = AnalisadorMargem(
        resultado.transacoes,
        ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("4200000")),
    )
    decomposicao = analise.decomposicao

    assert decomposicao.receita_bruta == Decimal("818.70")
    devolucoes = next(d for d in decomposicao.deducoes if d.nome == "devolucoes").valor
    assert devolucoes == Decimal("249.90")

    deducoes = sum(d.valor for d in decomposicao.deducoes)
    assert deducoes + decomposicao.margem_liquida == decomposicao.receita_bruta


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
