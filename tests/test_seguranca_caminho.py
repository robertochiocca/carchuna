"""O dashboard público lia arquivo do disco do servidor.

O campo "acompanhar um arquivo em tempo real" aceita um caminho e o
loader faz ``Path(source).read_bytes()``. No app publicado, quem digita
ali é um visitante anônimo e o disco é o do container do Streamlit
Cloud.

**O que a mitigação acidental já segurava, e por que ela não conta.** O
despacho de parser recusa extensão desconhecida antes de abrir o
arquivo, então ``/etc/passwd`` e ``.streamlit/secrets.toml`` nunca foram
lidos. Isso é efeito colateral de `ler_linhas_brutas`, não defesa: quem
acrescentar um formato amanhã abre a porta sem perceber que havia uma.

**O que sobrava, e foi medido.** Qualquer ``.csv``/``.tsv``/``.json``
do servidor era aberto, e a mensagem de `ColunasFaltando` termina com
"O que o seu arquivo tem: <todas as colunas>". Um CSV com cabeçalho
``cpf_do_cliente;saldo_bancario;senha_hash`` tinha os três nomes
impressos na tela. Somando: leitura de conteúdo, mais um oráculo de
existência de caminho (três respostas distinguíveis).

A correção não mexe nos loaders. `carregar_com_relatorio("/x.csv")`
continua sendo API legítima de biblioteca — quem escreve um script
Python já tem o disco na mão. O que estava errado era a **aplicação
pública** oferecer essa API a um anônimo, e a própria ajuda do campo já
dizia que ele é de uso local.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pandas")

import streamlit as st
from streamlit.testing.v1 import AppTest

from carchuna.dados import (
    CHAVE_LEITURA_POR_CAMINHO,
    carregar_com_relatorio,
    leitura_por_caminho_ligada,
)

APP = str(Path(__file__).resolve().parents[1] / "app.py")
TIMEOUT = 120


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    """Sem herdar o interruptor de quem rodou o teste antes."""
    monkeypatch.delenv(CHAVE_LEITURA_POR_CAMINHO, raising=False)
    st.cache_data.clear()
    yield
    st.cache_data.clear()


# ---------------------------------------------------------------------------
# A política
# ---------------------------------------------------------------------------


def test_a_leitura_por_caminho_vem_desligada_de_fabrica():
    """Mesmo padrão da narrativa por LLM, pela mesma razão.

    Quem publica o dashboard não deve expor o disco do servidor sem ter
    pedido, do mesmo jeito que quem clona o repositório não deve gastar
    com API sem ter pedido.
    """
    assert leitura_por_caminho_ligada() is False


def test_o_operador_liga_explicitamente(monkeypatch):
    monkeypatch.setenv(CHAVE_LEITURA_POR_CAMINHO, "1")
    assert leitura_por_caminho_ligada() is True


@pytest.mark.parametrize("valor", ["0", "", "true", "sim", "yes", "2"])
def test_so_o_valor_1_liga(monkeypatch, valor):
    """Interruptor que aceita qualquer coisa liga por acidente."""
    monkeypatch.setenv(CHAVE_LEITURA_POR_CAMINHO, valor)
    assert leitura_por_caminho_ligada() is False


# ---------------------------------------------------------------------------
# A tela
# ---------------------------------------------------------------------------


def test_sem_o_interruptor_o_campo_de_caminho_nao_existe():
    """Não aparece e recusa: não aparece.

    Um campo que só devolve erro é pior que campo nenhum — a caixa de
    texto sozinha já convida a tentar um caminho do servidor, e cada
    tentativa vira uma mensagem de erro que responde alguma coisa.
    """
    teste = AppTest.from_file(APP, default_timeout=TIMEOUT).run()

    assert not teste.exception
    assert not [c for c in teste.text_input if c.key == "caminho_arquivo"]


def test_a_tela_explica_por_que_o_campo_sumiu_e_como_ligar():
    """Recurso que some sem explicação vira suporte, não segurança."""
    teste = AppTest.from_file(APP, default_timeout=TIMEOUT).run()

    avisos = " ".join(str(i.value) for i in teste.info)
    assert "CARCHUNA_LER_CAMINHO=1" in avisos
    assert "disco da máquina" in avisos
    assert "upload" in avisos  # aponta o caminho que continua servindo


def test_com_o_interruptor_o_campo_volta(monkeypatch):
    """Ligar não é remover funcionalidade — é devolver a quem pediu."""
    monkeypatch.setenv(CHAVE_LEITURA_POR_CAMINHO, "1")
    teste = AppTest.from_file(APP, default_timeout=TIMEOUT).run()

    assert not teste.exception
    assert [c for c in teste.text_input if c.key == "caminho_arquivo"]


def test_o_upload_continua_funcionando_com_o_campo_desligado(tmp_path):
    """O caminho que o lojista de verdade usa não pode ter sido afetado."""
    arquivo = tmp_path / "vendas.csv"
    arquivo.write_text(
        "data;canal;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;shopee;100,00;40,00;10,00\n"
        "02/05/2026;shopee;200,00;90,00;12,00\n",
        encoding="utf-8",
    )
    resultado = carregar_com_relatorio(str(arquivo))
    assert len(resultado.transacoes) == 2


# ---------------------------------------------------------------------------
# O que a correção NÃO promete
# ---------------------------------------------------------------------------


def test_a_biblioteca_continua_lendo_caminho_de_proposito(tmp_path):
    """A fronteira é a aplicação, não a biblioteca — e isso é escolha.

    Quem chama `carregar_com_relatorio` de um script já tem o disco
    inteiro na mão; recusar ali seria teatro, e quebraria os onze
    arquivos de teste que carregam fixture por caminho.
    """
    arquivo = tmp_path / "qualquer.csv"
    arquivo.write_text(
        "data;canal;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;shopee;100,00;40,00;10,00\n",
        encoding="utf-8",
    )
    assert leitura_por_caminho_ligada() is False
    assert len(carregar_com_relatorio(str(arquivo)).transacoes) == 1


def test_a_recusa_por_extensao_e_efeito_colateral_e_nao_defesa():
    """Documenta a mitigação acidental para ninguém confiar nela.

    Hoje `/etc/passwd` é recusado porque não termina em extensão
    conhecida — não porque alguém decidiu protegê-lo. Quem acrescentar
    um formato amanhã abre a porta sem ver que havia uma; o interruptor
    é que é a defesa.
    """
    with pytest.raises(ValueError, match="Formato não suportado"):
        carregar_com_relatorio("/etc/passwd")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
