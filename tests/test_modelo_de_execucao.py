"""O guarda base só segura porque o Streamlit executa nesta ordem.

A extração do `app.py` em páginas apoia-se em três fatos do
`st.navigation`, e nenhum deles é escolha nossa — são comportamento do
framework:

1. o script de ENTRADA roda uma vez por rerun, **antes** da página;
2. `st.stop()` no script de entrada segura a página inteira, qualquer
   que seja ela;
3. o que a entrada desenha na barra lateral sobrevive à troca de página.

O guarda base do dashboard depende dos três. Ele existe para uma coisa
só: quando a decomposição da margem não roda, nenhuma aba pode desenhar
número, porque não há número. Hoje isso é garantido por ficar acima das
abas; depois da extração, por ficar acima do `pg.run()`.

**Por que isto virou teste.** Esses três fatos foram verificados uma vez,
à mão, na versão de Streamlit que estava instalada — e o
`requirements.txt` declara `>=1.37`, sem teto. Um upgrade que mude a
semântica em silêncio quebraria o guarda sem quebrar nenhum outro teste:
a tela voltaria a desenhar sobre dado que não existe, e o sintoma
apareceria como número errado na frente do lojista, não como erro.

Guarda que para de segurar é o pior tipo de regressão — silenciosa, e em
cima do dado de quem confia nela.

A fixture ao lado (`fixtures/navegacao/`) é o esqueleto do modelo, não
uma cópia do `app.py`: o que se afirma aqui é o comportamento do
Streamlit, e uma fixture mínima o isola melhor que o app inteiro.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

ENTRADA = str(Path(__file__).parent / "fixtures" / "navegacao" / "entrada.py")
TIMEOUT = 60


def _rodar() -> AppTest:
    return AppTest.from_file(ENTRADA, default_timeout=TIMEOUT).run()


# ---------------------------------------------------------------------------
# 1. A ordem de execução
# ---------------------------------------------------------------------------


def test_a_entrada_roda_antes_da_pagina():
    """Se a página rodasse primeiro, o guarda chegaria tarde demais."""
    teste = _rodar()

    assert not teste.exception
    assert teste.session_state["log"] == ["entrada", "pagina_um"]


def test_a_entrada_roda_uma_vez_por_rerun():
    """Uma vez, não zero e não duas.

    Zero significaria que o guarda deixou de ser avaliado em algum
    rerun. Duas significaria que tudo que ele faz — inclusive as funções
    cacheadas que ele chama — acontece em dobro, e o custo apareceria
    primeiro no endpoint de cálculo, não aqui.
    """
    teste = _rodar()
    teste.session_state["log"] = []

    teste.run()
    teste.run()
    teste.run()

    log = teste.session_state["log"]
    assert log.count("entrada") == 3
    # e sempre em par com a página, na ordem certa
    assert log == ["entrada", "pagina_um"] * 3


def test_a_ordem_se_mantem_depois_de_trocar_de_pagina():
    teste = _rodar()
    teste.switch_page("pagina_dois.py")
    teste.run()
    teste.session_state["log"] = []

    teste.run()

    assert teste.session_state["log"] == ["entrada", "pagina_dois"]


# ---------------------------------------------------------------------------
# 2. O guarda segura
# ---------------------------------------------------------------------------


def test_o_stop_da_entrada_impede_a_pagina_de_rodar():
    """O fato de que a extração depende.

    Sem isto, o guarda base viraria decoração: ele mostraria o erro e a
    página desenharia os gráficos logo abaixo, sobre um resultado que
    não existe.
    """
    teste = _rodar()
    teste.session_state["parar"] = True
    teste.session_state["log"] = []

    teste.run()

    assert teste.session_state["log"] == ["entrada", "guarda-parou"]
    assert [e.value for e in teste.error] == ["motor caiu"]
    assert not teste.exception  # `st.stop()` não é exceção vazando


def test_o_guarda_segura_qualquer_pagina_sem_codigo_na_pagina():
    """Uma linha na entrada protege as sete telas.

    É o que separa este desenho da alternativa de chamar o guarda no topo
    de cada página: lá, esquecer uma página é um defeito silencioso; aqui
    não há o que esquecer.
    """
    teste = _rodar()
    teste.switch_page("pagina_dois.py")
    teste.run()

    teste.session_state["parar"] = True
    teste.session_state["log"] = []
    teste.run()

    assert "pagina_dois" not in teste.session_state["log"]
    assert teste.session_state["log"] == ["entrada", "guarda-parou"]


# ---------------------------------------------------------------------------
# 3. A barra lateral é global
# ---------------------------------------------------------------------------


def test_o_widget_da_entrada_sobrevive_a_troca_de_pagina():
    """A barra lateral do dashboard é uma só, em todas as telas.

    Se ela morresse na troca, cada página precisaria redesenhá-la — e
    duas cópias do mesmo widget com a mesma `key` é erro de Streamlit,
    não escolha de arquitetura.
    """
    teste = _rodar()
    assert teste.text_input("taxa_adq").label == "Taxa"

    teste.switch_page("pagina_dois.py")
    teste.run()

    assert teste.text_input("taxa_adq").label == "Taxa"


# ---------------------------------------------------------------------------
# 4. O que o AppTest alcança — e o que não alcança
# ---------------------------------------------------------------------------


def test_o_conteudo_da_pagina_e_legivel_pelo_apptest():
    """A base da reescrita dos testes de aba.

    Os testes de hoje leem o rótulo do widget de abas. Com navegação,
    esse widget não é introspectável — o que sobra legível é o que a
    página desenha no corpo. Por isso o rótulo de cada página passa a ser
    renderizado por ela.
    """
    teste = _rodar()
    assert [h.value for h in teste.header] == ["Um"]

    teste.switch_page("pagina_dois.py")
    teste.run()
    assert [h.value for h in teste.header] == ["Dois"]


def test_a_navegacao_nao_e_legivel_pelo_apptest():
    """A perda desta migração, fixada em teste para não ser esquecida.

    `AppTest` não expõe os rótulos do menu de navegação: `.tabs` fica
    vazio, não há `.pages`, e a árvore de elementos traz só o que foi
    desenhado. Os quatro testes que hoje afirmam "as sete abas existem,
    com estes nomes, nesta ordem" não têm reescrita equivalente.

    Este teste existe para que a limitação seja um fato conferido, e não
    uma frase num documento: no dia em que o Streamlit expuser a
    navegação, ele quebra — e aí a verificação perdida pode voltar.
    """
    teste = _rodar()

    assert list(teste.tabs) == []
    assert not hasattr(teste, "pages")
    assert not hasattr(teste, "navigation")


def test_pagina_inexistente_levanta_em_vez_de_passar_batido():
    """O dente do teste de alcançabilidade.

    É o que faz `switch_page` servir de guarda contra renomear ou mover
    arquivo de página: some o arquivo, quebra o teste.
    """
    teste = _rodar()
    with pytest.raises(ValueError):
        teste.switch_page("pagina_que_nao_existe.py")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
