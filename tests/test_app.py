"""Teste de UI do dashboard com `streamlit.testing.v1.AppTest`.

O `app.py` era o único item marcado `pronto` no README sem teste
automatizado. Aqui o app roda de verdade — com dados sintéticos (o
caminho padrão, sem upload) e com upload de arquivo — e o teste confere
que as 7 abas montam sem exceção e que os números que aparecem na tela
são os mesmos que o motor calcula.

Nada aqui depende de `ANTHROPIC_API_KEY`: o app tem que rodar inteiro
sem chave, e é isso que o teste prova.
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pandas")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")
FIXTURES = Path(__file__).parent / "fixtures" / "reais"

# O app monta 7 abas e faz cálculo sobre 6 meses de vendas sintéticas;
# 120s dá folga para a máquina mais lenta do CI sem esconder travamento.
TIMEOUT = 120


# Widgets alcançados pela `key` do app, não pela posição: acrescentar um
# campo na barra lateral não pode quebrar teste nenhum.
IDIOMA = "idioma"
CAMINHO = "caminho_arquivo"


def _rodar() -> AppTest:
    """Roda o app do zero, no caminho padrão (sem upload, dados sintéticos)."""
    return AppTest.from_file(APP, default_timeout=TIMEOUT).run()


def _rodar_com_arquivo(caminho) -> AppTest:
    """Roda o app apontando o campo de caminho para um arquivo de vendas."""
    teste = _rodar()
    teste.text_input(CAMINHO).set_value(str(caminho))
    return teste.run()


@pytest.fixture(scope="module")
def app_demo() -> AppTest:
    """O app no caminho padrão: sem upload, com dados sintéticos."""
    return _rodar()


def test_o_app_sobe_sem_excecao(app_demo):
    """O caminho padrão monta inteiro, sem nenhuma exceção."""
    assert not app_demo.exception


def test_o_app_monta_com_e_sem_ANTHROPIC_API_KEY(monkeypatch):
    """Degradação graciosa de verdade: o teste mexe na variável.

    Antes este teste recebia `monkeypatch` e não usava — o nome prometia
    uma garantia que ninguém estava conferindo.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sem_chave = _rodar()
    assert not sem_chave.exception
    rotulos_sem = [aba.label for aba in sem_chave.tabs]

    # com chave (falsa): o app não pode nem quebrar nem mudar de forma —
    # o cálculo não depende de LLM, então as abas são as mesmas
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-chave-falsa-de-teste")
    com_chave = _rodar()
    assert not com_chave.exception
    assert [aba.label for aba in com_chave.tabs] == rotulos_sem


def test_as_sete_abas_existem_com_os_nomes_do_lojista(app_demo):
    """As 7 abas do README, na ordem, em linguagem de lojista."""
    rotulos = [aba.label for aba in app_demo.tabs]
    assert rotulos == [
        "Resumo",
        "Vendas e Produtos",
        "Histórico",
        "E se…?",
        "Crescer",
        "Diagnóstico Legal",
        "Relatório",
    ]


def test_o_resumo_executivo_aparece_na_primeira_aba(app_demo):
    """A frase do motor ('R$ X de margem se perderam') vai para a tela."""
    frases = [info.value for info in app_demo.info]
    assert any("margem se perderam" in f for f in frases)


def test_os_numeros_da_tela_batem_com_o_motor(app_demo):
    """O que o lojista lê é o que o motor calculou — sem arredondar na UI.

    Recalcula a decomposição com a mesma configuração padrão do app e
    confere que a receita bruta formatada aparece na tela.
    """
    from carchuna.analise import AnalisadorMargem

    analise = AnalisadorMargem.demo(meses=6)
    receita = analise.decomposicao.receita_bruta

    # o app formata em pt-BR: 1.234.567,89
    inteiro = f"{receita:,.0f}".replace(",", ".")
    texto_da_tela = " ".join(
        [m.value for m in app_demo.metric] + [str(m.value) for m in app_demo.markdown]
    )
    assert inteiro in texto_da_tela


def test_todas_as_abas_renderizam_algum_conteudo(app_demo):
    """Aba vazia é bug: cada uma das 7 tem que ter escrito alguma coisa."""
    for aba in app_demo.tabs:
        conteudo = (
            len(aba.markdown)
            + len(aba.metric)
            + len(aba.dataframe)
            + len(aba.caption)
            + len(aba.button)
        )
        assert conteudo > 0, f"a aba {aba.label!r} não renderizou nada"


def test_a_versao_em_ingles_tambem_monta():
    """Bilíngue de verdade: trocar o idioma não pode quebrar o app."""
    teste = _rodar()
    teste.radio(IDIOMA).set_value("EN")
    teste.run()
    assert not teste.exception
    assert [aba.label for aba in teste.tabs][0] == "Summary"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_upload_invalido_mostra_erro_e_nao_estoura(tmp_path):
    """Arquivo que não é relatório de vendas: erro na tela, sem traceback."""
    extrato = tmp_path / "extrato.csv"
    extrato.write_text(
        "Extrato bancário\nlançamento;histórico;valor\n01/05;PIX;100,00\n",
        encoding="utf-8",
    )
    teste = _rodar_com_arquivo(extrato)
    assert not teste.exception
    erros = " ".join(e.value for e in teste.error)
    assert "cabeçalho" in erros.lower() or "não encontrei" in erros.lower()


def test_upload_de_arquivo_valido_recalcula_o_dashboard(tmp_path):
    """O caminho que importa: sobe planilha, todas as abas se recalculam."""
    vendas = tmp_path / "vendas.csv"
    vendas.write_text(
        "data;canal;produto;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;shopee;Capa;100,00;40,00;10,00\n"
        "02/05/2026;mercado_livre;Fone;200,00;90,00;12,00\n"
        "03/05/2026;shopee;Caixa;300,00;120,00;15,00\n",
        encoding="utf-8",
    )
    teste = _rodar_com_arquivo(vendas)
    assert not teste.exception
    # receita bruta = 100 + 200 + 300 = 600,00, conferido à mão. Procurar só
    # por "600" casaria com "1.600" ou com um pedaço de data: exige o
    # formato do app, com centavos.
    texto = " ".join(
        [m.value for m in teste.metric] + [str(m.value) for m in teste.markdown]
    )
    assert "600,00" in texto
    # e as 3 vendas entraram, nenhuma de fora
    sucessos = " ".join(s.value for s in teste.success)
    assert "3 vendas importadas" in sucessos


def test_arquivo_com_linha_estragada_importa_o_resto_e_avisa(tmp_path):
    """A regra da casa na tela: nada some sem o lojista ficar sabendo."""
    vendas = tmp_path / "vendas.csv"
    vendas.write_text(
        "data;canal;produto;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;shopee;Capa;100,00;40,00;10,00\n"
        "02/05/2026;shopee;Fone;LIXO;90,00;12,00\n"
        "03/05/2026;shopee;Caixa;200,00;90,00;12,00\n",
        encoding="utf-8",
    )
    teste = _rodar_com_arquivo(vendas)
    assert not teste.exception
    avisos = " ".join(w.value for w in teste.warning)
    # a frase inteira, não um dígito solto: "2" casaria com qualquer data
    assert "2 vendas importadas" in avisos
    assert "1 de 3 linhas ficaram de fora" in avisos

    # e o motivo da linha recusada aparece na tabela do expander
    motivos = " ".join(
        str(d.value.to_dict()) for d in teste.dataframe if hasattr(d.value, "to_dict")
    )
    assert "linha 3" in motivos
    assert "valor monetário" in motivos


def test_o_valor_da_venda_recusada_nao_entra_no_total(tmp_path):
    """Invariante de dinheiro: linha recusada não soma em lugar nenhum.

    100,00 + 200,00 = 300,00 — a linha de valor 'LIXO' não pode inflar
    nem esvaziar esse total.
    """
    from carchuna.analise import AnalisadorMargem
    from carchuna.dados import carregar_com_relatorio
    from carchuna.margem import ConfigTributaria

    vendas = tmp_path / "vendas.csv"
    vendas.write_text(
        "data;canal;produto;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;shopee;Capa;100,00;40,00;10,00\n"
        "02/05/2026;shopee;Fone;LIXO;90,00;12,00\n"
        "03/05/2026;shopee;Caixa;200,00;90,00;12,00\n",
        encoding="utf-8",
    )
    resultado = carregar_com_relatorio(vendas)
    analise = AnalisadorMargem(
        resultado.transacoes,
        ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("500000")),
    )
    assert analise.decomposicao.receita_bruta == Decimal("300.00")


# ---------------------------------------------------------------------------
# RBT12 móvel na tela
# ---------------------------------------------------------------------------


def _csv_de_meses(caminho: Path, meses: int, valor: str, ano=2025, mes=1) -> Path:
    """Uma venda por mês, a partir de (ano, mes)."""
    linhas = ["data;canal;produto;valor_bruto;custo_produto;frete_pago"]
    for i in range(meses):
        a, m = ano + (mes - 1 + i) // 12, (mes - 1 + i) % 12 + 1
        linhas.append(f"15/{m:02d}/{a};shopee;Capa;{valor};40,00;10,00")
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def test_o_toggle_da_rbt12_movel_diz_quantos_meses_usou_o_arquivo(tmp_path):
    """15 meses de histórico: 3 deles têm a janela de 12 meses fechada.

    Conferido à mão: com dados de 2025-01 a 2026-03, os meses que têm
    doze meses ANTERIORES dentro do arquivo são 2026-01, 2026-02 e
    2026-03 — os outros 12 caem na RBT12 informada.
    """
    vendas = _csv_de_meses(tmp_path / "vendas.csv", 15, "30000,00")
    teste = _rodar()
    teste.text_input(CAMINHO).set_value(str(vendas))
    teste.run()
    # o toggle existe e começa desligado
    movel = teste.toggle("rbt12_movel")
    assert movel.value is False

    movel.set_value(True)
    teste.run()
    assert not teste.exception
    legendas = " ".join(c.value for c in teste.caption)
    assert "3 de 15 meses" in legendas


def test_arquivo_curto_avisa_que_a_aliquota_veio_do_valor_informado(tmp_path):
    """6 meses: nenhuma janela fecha, e a tela diz isso em vez de fingir."""
    vendas = _csv_de_meses(tmp_path / "vendas.csv", 6, "30000,00")
    teste = _rodar()
    teste.text_input(CAMINHO).set_value(str(vendas))
    teste.run()
    teste.toggle("rbt12_movel").set_value(True)
    teste.run()
    assert not teste.exception
    avisos = " ".join(i.value for i in teste.info)
    assert "não cobre 12 meses" in avisos


def test_nenhuma_funcao_que_desenha_widget_esta_cacheada():
    """Guarda estrutural — este erro passou por aqui e ninguém viu.

    Ao inserir uma função nova logo acima de outra, o decorador
    `@st.cache_resource` da de baixo ficou grudado na de cima: uma função
    que desenha widgets virou cacheada, e o `Retriever` (que lê e indexa
    o corpus) perdeu o cache e passou a ser reconstruído a cada rerun.
    O Streamlit só reclama disso como aviso, então o teste de tela não
    derrubou nada. Este lê a árvore sintática do `app.py` e não depende
    de nenhum aviso.
    """
    import ast

    DESENHAM = {
        "text_input",
        "number_input",
        "selectbox",
        "slider",
        "toggle",
        "radio",
        "checkbox",
        "button",
        "file_uploader",
        "expander",
        "error",
        "warning",
        "success",
        "info",
        "metric",
        "dataframe",
        "stop",
        "tabs",
        "download_button",
        "caption",
        "markdown",
    }
    arvore = ast.parse(Path(APP).read_text(encoding="utf-8"))
    problemas = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.FunctionDef):
            continue
        cacheada = any("cache" in ast.unparse(d) for d in no.decorator_list)
        if not cacheada:
            continue
        for interno in ast.walk(no):
            if (
                isinstance(interno, ast.Call)
                and isinstance(interno.func, ast.Attribute)
                and isinstance(interno.func.value, ast.Name)
                and interno.func.value.id == "st"
                and interno.func.attr in DESENHAM
            ):
                problemas.append(
                    f"{no.name}() é cacheada e chama st.{interno.func.attr}"
                )
    assert not problemas, "; ".join(problemas)


def test_o_retriever_continua_cacheado():
    """O corpus é lido e indexado uma vez, não a cada clique de widget."""
    import ast

    arvore = ast.parse(Path(APP).read_text(encoding="utf-8"))
    cacheadas = {
        no.name
        for no in ast.walk(arvore)
        if isinstance(no, ast.FunctionDef)
        and any("cache" in ast.unparse(d) for d in no.decorator_list)
    }
    assert "_retriever_cacheado" in cacheadas
    assert "_resultados_cacheados" in cacheadas


def test_o_app_nao_usa_parametro_do_streamlit_com_remocao_marcada():
    """`use_container_width` tinha remoção anunciada para 31/12/2025.

    A data já passou. Enquanto o parâmetro só emite aviso o app roda,
    mas no dia em que o Streamlit Cloud atualizar para uma versão que o
    removeu, o dashboard publicado quebra inteiro — e o lojista não tem
    como saber o que aconteceu. `width='stretch'` é o substituto.
    """
    fonte = Path(APP).read_text(encoding="utf-8")
    assert "use_container_width" not in fonte


def test_nenhum_aviso_de_depreciacao_escapa_para_a_tela(app_demo):
    """`AppTest.exception` também recolhe aviso (`is_warning=True`).

    Deixar aviso passar é o que fez o erro de cache sobreviver nove
    commits: o Streamlit reclamava e ninguém estava ouvindo.
    """
    assert not app_demo.exception


def test_a_taxa_digitada_chega_inteira_ao_motor(tmp_path):
    """A fronteira do widget não pode reintroduzir float no cálculo.

    `TabelaCustos` rejeita `float` com `TypeError` — então se o campo
    voltasse a ser `st.number_input`, o app quebraria e `exception` não
    estaria vazio. Além disso o valor digitado tem que chegar inteiro:
    numa venda de R$ 1.000,00 em canal com adquirência própria, mudar a
    taxa de 2,00% para 2,49% muda a dedução em exatamente R$ 4,90
    (1000 × 0,0049), e é isso que a tela precisa refletir.
    """
    vendas = tmp_path / "vendas.csv"
    vendas.write_text(
        "data;canal;produto;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;loja_propria;Capa;1000,00;400,00;0,00\n",
        encoding="utf-8",
    )

    def _foi_embora(taxa: str) -> Decimal:
        teste = _rodar()
        teste.text_input(CAMINHO).set_value(str(vendas))
        teste.text_input("taxa_adq").set_value(taxa)
        teste.run()
        assert not teste.exception, f"o app quebrou com a taxa {taxa}"
        # selecionar pelo RÓTULO, não pela posição: a ordem das métricas
        # é layout, e layout muda
        (foi_embora,) = [
            m.value for m in teste.metric if m.label == "Foi embora em custos e taxas"
        ]
        return Decimal(
            foi_embora.removeprefix("R$ ").replace(".", "").replace(",", ".")
        )

    assert _foi_embora("2,49") - _foi_embora("2,00") == Decimal("4.90")


def _dados_do_grafico(elemento) -> dict:
    """Os números que o gráfico realmente mandou para a tela."""
    import io

    import pyarrow as pa

    fluxo = io.BytesIO(elemento.proto.datasets[0].data.data)
    return pa.ipc.open_stream(fluxo).read_all().to_pydict()


def _cachoeira(teste):
    """A cachoeira do Resumo, achada pela seleção que só ela tem."""
    graficos = [
        el
        for el in teste.main
        if el.type == "vega_lite_chart" and "ponto" in list(el.proto.selection_mode)
    ]
    assert len(graficos) == 1, "a cachoeira clicável tem que existir, uma só"
    return graficos[0]


def test_a_cachoeira_da_margem_bate_degrau_a_degrau_com_o_motor(app_demo):
    """Cada degrau da cachoeira é uma dedução do motor, na ordem do motor.

    Não basta o gráfico aparecer: o primeiro degrau tem que sair do
    faturamento, cada dedução tem que descer exatamente o seu valor, e o
    último degrau tem que pousar na margem líquida. Se a UI e o motor
    discordarem em um centavo, o desenho está contando outra história.
    """
    from carchuna.analise import AnalisadorMargem

    decomposicao = AnalisadorMargem.demo(meses=6).decomposicao
    dados = _dados_do_grafico(_cachoeira(app_demo))

    esperado = ["receita"] + [d.nome for d in decomposicao.deducoes] + ["margem"]
    assert dados["nome"] == esperado

    # a barra do faturamento vai de zero ao total do motor
    assert Decimal(str(dados["fim"][0])) == decomposicao.receita_bruta

    # cada degrau desce exatamente o valor da sua dedução, partindo de onde
    # o degrau anterior parou
    acumulado = decomposicao.receita_bruta
    for passo, deducao in enumerate(decomposicao.deducoes, start=1):
        assert Decimal(str(dados["fim"][passo])) == acumulado
        acumulado -= deducao.valor
        assert Decimal(str(dados["inicio"][passo])) == acumulado

    # e o que sobra depois do último degrau é a margem líquida
    assert acumulado == decomposicao.margem_liquida
    assert Decimal(str(dados["fim"][-1])) == decomposicao.margem_liquida


def test_a_cachoeira_so_deixa_clicar_no_que_tem_composicao(app_demo):
    """Faturamento e margem não são deduções: não abrem drill-down.

    O clique nelas é ignorado no app; aqui a garantia é que elas estão
    marcadas com um `tipo` diferente, que é o que a tela usa para
    distinguir — e que a dica de uso aparece enquanto nada foi clicado.
    """
    dados = _dados_do_grafico(_cachoeira(app_demo))
    tipos = dict(zip(dados["nome"], dados["tipo"], strict=True))
    assert tipos["receita"] == "receita"
    assert tipos["margem"] == "margem"
    assert {tipos[n] for n in dados["nome"] if n not in ("receita", "margem")} == {
        "deducao"
    }

    legendas = " ".join(c.value for c in app_demo.caption)
    assert "para abrir de onde ela vem" in legendas


def _csv_com_salto_de_comissao(caminho: Path) -> Path:
    """Comissão em 12% da receita por 3 meses e 20% no quarto.

    O salto é medido contra a própria série do arquivo, então o impacto
    de 8 p.p. sobre R$ 1.000 = R$ 80,00/mês não depende do regime nem da
    RBT12 escolhidos na barra lateral — o que deixa o teste conferir o
    número exato sem replicar a configuração da tela.
    """
    linhas = [
        "data;canal;produto;valor_bruto;custo_produto;frete_pago;comissao_cobrada"
    ]
    for mes in (1, 2, 3):
        linhas.append(f"15/{mes:02d}/2026;shopee;Capa;1000,00;0,00;0,00;120,00")
    linhas.append("15/04/2026;shopee;Capa;1000,00;0,00;0,00;200,00")
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def test_o_radar_mostra_os_mesmos_sinais_que_o_motor(tmp_path):
    """Todo sinal do motor chega à tela, com impacto, método e caminho.

    Mesmo espírito do teste da cachoeira: não basta a seção existir. Cada
    sinal que o motor produz tem que aparecer com o seu título e o seu
    impacto, e nenhum pode chegar sem dizer como foi detectado — que é a
    diferença entre um radar e um palpite com cara de alerta.
    """
    from carchuna.analise import AnalisadorMargem
    from carchuna.dados import carregar_com_relatorio
    from carchuna.margem import ConfigTributaria

    arquivo = _csv_com_salto_de_comissao(tmp_path / "vendas.csv")
    teste = _rodar_com_arquivo(arquivo)
    assert not teste.exception

    resultado = carregar_com_relatorio(arquivo)
    radar = AnalisadorMargem(
        resultado.transacoes,
        ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("4200000")),
    ).radar()
    assert radar, "o arquivo foi montado para acender o radar"

    tela = " ".join(
        [e.value for e in teste.error]
        + [w.value for w in teste.warning]
        + [s.value for s in teste.success]
        + [str(c.value) for c in teste.caption]
    )
    for sinal in radar:
        assert sinal.titulo in tela
        assert sinal.metodo in tela
        assert sinal.caminho_pratico in tela

    # o salto de comissão: 8 p.p. sobre R$ 1.000 no mês = R$ 80,00/mês
    salto = [s for s in radar if s.categoria == "comissoes_canal_pct"]
    assert [s.impacto_mensal for s in salto] == [Decimal("80.00")]
    assert "R$ 80,00" in tela


def test_nenhum_sinal_do_radar_chega_sem_metodo_e_sem_nota_de_confianca(tmp_path):
    """A regra da casa, cobrada na fronteira da tela."""
    from carchuna.analise import AnalisadorMargem
    from carchuna.dados import carregar_com_relatorio
    from carchuna.margem import ConfigTributaria

    arquivo = _csv_com_salto_de_comissao(tmp_path / "vendas.csv")
    radar = AnalisadorMargem(
        carregar_com_relatorio(arquivo).transacoes,
        ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("4200000")),
    ).radar()
    for sinal in radar:
        assert sinal.metodo
        assert sinal.confianca.pct > 0
        assert sinal.aviso


def test_sem_sinal_o_radar_diz_que_esta_limpo(app_demo):
    """Seção vazia é pior que seção ausente: o radar fala quando cala."""
    from carchuna.analise import AnalisadorMargem

    assert AnalisadorMargem.demo(meses=6).radar() == []
    sucessos = " ".join(s.value for s in app_demo.success)
    assert "Nenhum sinal no radar" in sucessos


def test_a_ficha_de_linhagem_aponta_o_arquivo_que_o_lojista_subiu(tmp_path):
    """Rastreabilidade só vale se apontar a origem de verdade.

    A ficha nasceu para responder "de onde veio este número?". Se ela
    mostrasse um rótulo genérico enquanto o cálculo saiu do arquivo do
    lojista, seria decoração — e decoração que afirma procedência é pior
    que nenhuma.
    """
    arquivo = _csv_com_salto_de_comissao(tmp_path / "vendas.csv")
    teste = _rodar_com_arquivo(arquivo)
    assert not teste.exception

    tela = " ".join(str(m.value) for m in teste.markdown)
    assert str(arquivo) in tela
    assert "Fonte dos dados" in tela
    assert "Colunas usadas" in tela
    assert "Cálculo" in tela


def test_a_ficha_de_linhagem_traz_o_valor_e_a_formula_do_motor(app_demo):
    """O número da ficha é o do motor, e a fórmula cita os parâmetros do caso."""
    from carchuna.analise import AnalisadorMargem

    analise = AnalisadorMargem.demo(meses=6)
    fichas = analise.linhagem()
    receita = fichas["receita_bruta"]
    assert receita.valor == analise.decomposicao.receita_bruta

    tributos = fichas["tributos"]
    assert tributos.valor == analise.decomposicao.deducao("tributos").valor
    # a fórmula é a do caso, com os parâmetros dentro — não um texto fixo
    assert "Anexo" in tributos.formula or "DAS" in tributos.formula
    assert tributos.fonte
    assert tributos.colunas

    # dado de exemplo se declara como exemplo na própria ficha
    tela = " ".join(str(m.value) for m in app_demo.markdown)
    assert "dados sintéticos de exemplo" in tela


def test_a_nota_de_confianca_na_tela_e_a_soma_dos_seus_componentes(app_demo):
    """A nota exibida tem que reconstruir: pct == soma dos componentes.

    E cada componente aparece com o motivo. Nota sem motivo na tela é
    número mágico, que é o que a rubrica existe para não ser.
    """
    from carchuna.analise import AnalisadorMargem
    from carchuna.confianca import avaliar_confianca

    nota = avaliar_confianca(AnalisadorMargem.demo(meses=6).transacoes, "calculado")
    assert nota.pct == sum(c.pontos for c in nota.componentes)

    rotulos = [e.label for e in app_demo.expander]
    assert any(f"{nota.pct}% ({nota.nivel.upper()})" in r for r in rotulos)

    tela = " ".join(str(m.value) for m in app_demo.markdown)
    assert nota.frase in tela
    for componente in nota.componentes:
        assert f"{componente.pontos}/{componente.maximo}" in tela
        assert componente.motivo in tela


def test_cada_sinal_do_radar_chega_com_a_propria_nota_de_confianca(tmp_path):
    """Conclusão na tela sem etiqueta de confiança é conclusão sem contexto."""
    from carchuna.analise import AnalisadorMargem
    from carchuna.dados import carregar_com_relatorio
    from carchuna.margem import ConfigTributaria

    arquivo = _csv_com_salto_de_comissao(tmp_path / "vendas.csv")
    teste = _rodar_com_arquivo(arquivo)
    radar = AnalisadorMargem(
        carregar_com_relatorio(arquivo).transacoes,
        ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal("4200000")),
    ).radar()

    tela = " ".join(
        [e.value for e in teste.error]
        + [w.value for w in teste.warning]
        + [s.value for s in teste.success]
    )
    for sinal in radar:
        assert f"{sinal.confianca.pct}% ({sinal.confianca.nivel})" in tela
        assert sinal.confianca.frase in tela


def test_o_cenario_de_preco_aparece_no_e_se_com_o_numero_do_motor(app_demo):
    """ "E se eu subisse os preços 5%?" na tela, com a premissa junto.

    O impacto tem que ser o do motor — que recalcula imposto e comissão
    sobre o preço novo — e não 5% do faturamento. E a premissa do volume
    constante aparece no próprio nome do cenário: sem ela o número vira
    promessa, porque ninguém sabe quanta venda se perde ao subir preço.
    """
    from carchuna.analise import AnalisadorMargem

    cenarios = AnalisadorMargem.demo(meses=6).cenarios()
    preco = [c for c in cenarios if "preços" in c.nome]
    assert len(preco) == 1, "o cenário de preço entra uma vez na bateria"
    (preco,) = preco
    assert "mesmo volume" in preco.nome

    aba_ese = app_demo.tabs[3]
    assert aba_ese.label.strip().startswith("E se")
    nomes = [str(m.value) for m in aba_ese.markdown]
    assert any(preco.nome in n for n in nomes)

    # o app formata em pt-BR: R$ 1.234.567,89
    formatado = "R$ " + (
        f"{preco.impacto_reais:,.2f}".replace(",", "@")
        .replace(".", ",")
        .replace("@", ".")
    )
    valores = [m.value for m in aba_ese.metric]
    assert formatado in valores

    # o ganho não é 5% do faturamento: imposto e comissão comem parte
    receita = AnalisadorMargem.demo(meses=6).decomposicao.receita_bruta
    assert preco.impacto_reais < receita * Decimal("0.05")


def test_numero_implausivel_aparece_com_motivo_no_topo_do_resumo(tmp_path):
    """CMV acima do faturamento: a tela diz por que, antes dos números.

    A regra é a do módulo: mostrar o motivo, e **não** esconder, limitar
    nem zerar o valor. Um número absurdo com teto continua absurdo e passa
    a ser também invisível.
    """
    vendas = tmp_path / "vendas.csv"
    vendas.write_text(
        "data;canal;produto;valor_bruto;custo_produto;frete_pago\n"
        "01/05/2026;shopee;Capa;100,00;5000,00;10,00\n"
        "02/05/2026;shopee;Fone;200,00;9000,00;12,00\n",
        encoding="utf-8",
    )
    teste = _rodar_com_arquivo(vendas)
    assert not teste.exception

    erros = " ".join(e.value for e in teste.error)
    assert "não fecham com a realidade" in erros
    assert "mais que todo o faturamento" in erros
    # o número segue na tela: 300,00 de receita continua sendo mostrado
    tela = " ".join(
        [m.value for m in teste.metric] + [str(m.value) for m in teste.markdown]
    )
    assert "300,00" in tela


def test_base_saudavel_nao_mostra_aviso_de_implausibilidade(app_demo):
    """O aviso só aparece quando há o que avisar — senão vira ruído."""
    erros = " ".join(e.value for e in app_demo.error)
    assert "não fecham com a realidade" not in erros


def test_taxa_digitada_errada_avisa_em_vez_de_estourar():
    """'dois e meio' vira frase de lojista, não ValueError na tela."""
    teste = _rodar()
    teste.text_input("taxa_adq").set_value("dois e meio")
    teste.run()
    assert not teste.exception
    erros = " ".join(e.value for e in teste.error)
    assert "dois e meio" in erros


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
