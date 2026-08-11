"""Um motor que estoura levava junto os outros catorze.

O dashboard rodava todos os motores numa expressão só — um `dict` com
quinze chaves, cada valor uma chamada. Basta uma delas levantar
`ValueError` para o `dict` inteiro não existir: o lojista via um
traceback no lugar do dashboard por causa de um cenário que não cabia
nos dados dele, com o resumo, o histórico e o diagnóstico prontos e
inalcançáveis.

A bateria de cenários tinha o mesmo formato de defeito num nível abaixo.
Cenário é pergunta hipotética, e nem toda hipótese cabe: migrar canal
exige que o canal de origem tenha venda. O primeiro cenário impossível
apagava os outros cinco.

Agora cada motor é contido no próprio erro, e o motivo vai para a tela
da aba que ficou sem número. **Contido não é escondido**: lista vazia de
motor que estourou não pode herdar a mensagem de sucesso de quem rodou e
não achou nada.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pandas")

import streamlit as st
from streamlit.testing.v1 import AppTest

from carchuna.analise import AnalisadorMargem
from carchuna.cenarios import (
    CenarioAntecipacao,
    CenarioPreco,
    rodar_cenarios_padrao,
)
from carchuna.margem import ConfigTributaria, Transacao

APP = str(Path(__file__).resolve().parents[1] / "app.py")
TIMEOUT = 120

CONFIG = ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("360000"))


def _vendas(n=6):
    return [
        Transacao(
            data=date(2026, m, 10),
            canal="shopee",
            valor_bruto=Decimal("1000"),
            custo_produto=Decimal("400"),
            frete_pago=Decimal("15"),
        )
        for m in range(1, n + 1)
    ]


def _estoura(*_args, **_kwargs):
    raise ValueError("este motor não roda com estes dados.")


@pytest.fixture(autouse=True)
def _cache_limpo():
    """O cache do Streamlit é global e atravessaria os testes.

    Sem isto, o resultado bom de um teste anterior voltaria para o teste
    que precisa ver a falha, e a conferência passaria sem ter olhado
    nada.
    """
    st.cache_data.clear()
    yield
    st.cache_data.clear()


# ---------------------------------------------------------------------------
# A bateria de cenários
# ---------------------------------------------------------------------------


def test_cenario_que_estoura_e_omitido_e_os_outros_ficam(monkeypatch):
    """Cinco perguntas continuam respondidas quando a sexta não cabe."""
    inteira = rodar_cenarios_padrao(_vendas(), CONFIG)
    assert len(inteira) >= 4

    monkeypatch.setattr(CenarioAntecipacao, "transformar", _estoura)
    restante = rodar_cenarios_padrao(_vendas(), CONFIG)

    assert len(restante) == len(inteira) - 1
    assert all("ntecipa" not in r.nome for r in restante)
    assert [r.nome for r in restante] == [
        r.nome for r in inteira if "ntecipa" not in r.nome
    ]


def test_o_primeiro_cenario_a_estourar_nao_apaga_os_de_baixo(monkeypatch):
    """`CenarioPreco` é o primeiro da fila — era ele quem levava a lista."""
    monkeypatch.setattr(CenarioPreco, "transformar", _estoura)
    restante = rodar_cenarios_padrao(_vendas(), CONFIG)

    assert restante, "a bateria inteira sumiu por causa do primeiro item"
    assert all("preço" not in r.nome.lower() for r in restante)


def test_a_bateria_inteira_impossivel_devolve_lista_vazia(monkeypatch):
    """Vazio é resposta; exceção no meio da lista, não.

    Quem chama recebe uma lista de números comparáveis entre si. Um item
    "não deu" ali dentro só serviria para ser somado por engano.
    """
    for classe in (CenarioPreco, CenarioAntecipacao):
        monkeypatch.setattr(classe, "transformar", _estoura)
    from carchuna import cenarios as mod

    for nome in ("CenarioComissao", "CenarioDevolucoesDobram", "CenarioMudancaAnexo"):
        monkeypatch.setattr(getattr(mod, nome), "transformar", _estoura)

    assert rodar_cenarios_padrao(_vendas(), CONFIG) == []


def test_erro_que_ninguem_previu_continua_subindo(monkeypatch):
    """A contenção é de `ValueError`/`TypeError`, não de tudo.

    Engolir `Exception` transformaria defeito de código em bloco vazio
    com mensagem gentil — que é o modo mais caro de descobrir um bug.
    """

    def _erro_de_programacao(*_a, **_k):
        raise AttributeError("isto é defeito meu, não dado ruim.")

    monkeypatch.setattr(CenarioPreco, "transformar", _erro_de_programacao)
    with pytest.raises(AttributeError):
        rodar_cenarios_padrao(_vendas(), CONFIG)


# ---------------------------------------------------------------------------
# A bandeja do dashboard
# ---------------------------------------------------------------------------


def test_um_motor_caido_nao_derruba_o_dashboard(monkeypatch):
    """Cenários fora do ar, e as outras seis abas continuam de pé."""
    monkeypatch.setattr(AnalisadorMargem, "cenarios", _estoura)
    teste = AppTest.from_file(APP, default_timeout=TIMEOUT).run()

    assert not teste.exception
    # o resumo continua inteiro: os números do motor que rodou estão lá
    assert [m.value for m in teste.metric]


def test_o_motivo_do_motor_caido_aparece_na_tela(monkeypatch):
    """Sumir em silêncio seria trocar um traceback por um buraco."""
    monkeypatch.setattr(AnalisadorMargem, "cenarios", _estoura)
    teste = AppTest.from_file(APP, default_timeout=TIMEOUT).run()

    erros = " ".join(e.value for e in teste.error)
    assert "não pôde ser calculada" in erros
    assert "este motor não roda com estes dados" in erros


def test_a_base_saudavel_nao_mostra_aviso_de_motor_caido():
    """Aviso que aparece sempre deixa de ser aviso."""
    teste = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    erros = " ".join(e.value for e in teste.error)
    assert "não pôde ser calculada" not in erros


def test_motor_caido_nao_vira_mensagem_de_tudo_certo(monkeypatch):
    """A distinção que o `_falhou` existe para manter.

    Sem ela, o diagnóstico que estourou devolveria lista vazia e a tela
    diria "nenhum vazamento encontrado" — trocando um erro por um elogio.
    """
    monkeypatch.setattr(AnalisadorMargem, "diagnosticar", _estoura)
    teste = AppTest.from_file(APP, default_timeout=TIMEOUT).run()

    assert not teste.exception
    tudo = " ".join([s.value for s in teste.success] + [i.value for i in teste.info])
    assert "vazamento" not in tudo.lower()
    assert "nada urgente" not in tudo.lower()


def test_sem_decomposicao_a_tela_diz_por_que_em_vez_de_desenhar_vazio(monkeypatch):
    """A decomposição é a base, não um motor entre outros.

    Parar aqui não é o defeito que esta correção ataca: é a resposta
    honesta quando não há número nenhum para as abas mostrarem. O que não
    pode é o lojista ficar com sete abas vazias e nenhuma explicação.
    """
    monkeypatch.setattr(AnalisadorMargem, "decomposicao", property(_estoura))
    teste = AppTest.from_file(APP, default_timeout=TIMEOUT).run()

    assert not teste.exception
    erros = " ".join(e.value for e in teste.error)
    assert "não há nada" in erros
    assert "este motor não roda com estes dados" in erros


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
