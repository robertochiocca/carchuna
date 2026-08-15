"""Entre R$ 3,6 mi e R$ 4,8 mi a margem saía para cima, calada.

``aliquota_efetiva_simples`` só recusava acima do teto do Simples
(R$ 4,8 mi). Na faixa abaixo dele e acima do sublimite de ICMS/ISS a
conta rodava normalmente e ``decompor_margem`` publicava a margem sem
uma palavra — mas nessa faixa a empresa recolhe ICMS e/ou ISS **fora do
DAS**, pelas regras do Estado e do Município (LC 123/2006, arts. 19 e
20). A dedução ``tributos`` cobre só o DAS. Faltando um imposto na
dedução, a margem sai **alta**: o mesmo erro direcional que o motor já
se recusa a cometer no MEI acima do teto.

O tratamento espelha o do MEI, e a divisão entre recusar e avisar vem da
lei, não de gosto. Excesso de mais de 20% sobre o sublimite tira o
ICMS/ISS do DAS já no mês seguinte; até 20%, a saída fica para janeiro
do ano seguinte (art. 20, § 1º). Então acima de R$ 4.320.000 o período
calculado provavelmente já é um período em que o número está errado —
recusa. Entre R$ 3,6 mi e R$ 4,32 mi a conta do período corrente ainda
vale — aviso, porque recusar seria negar um número que está certo.

O que não muda: nada abaixo de R$ 3.600.000. Nenhuma alíquota de ICMS
ou ISS é calculada, estimada ou chutada em lugar nenhum — a Carchuna
não sabe, e o que ela faz aqui é não publicar margem que sabe estar
incompleta.
"""

import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna import crescimento, margem
from carchuna.margem import (
    EXCESSO_SUBLIMITE_IMEDIATO,
    SUBLIMITE_ICMS_ISS,
    TETO_SIMPLES,
    ConfigTributaria,
    Transacao,
    decompor_margem,
)


def _config(rbt12):
    return ConfigTributaria(regime="simples", anexo_simples="I", rbt12=Decimal(rbt12))


def _vendas():
    return [
        Transacao(
            data=date(2026, 3, 10),
            canal="fisico",
            valor_bruto=Decimal("10000"),
            custo_produto=Decimal("4000"),
            frete_pago=Decimal("0"),
        )
    ]


# ---------------------------------------------------------------------------
# Abaixo do sublimite: nada muda, nem o número nem o silêncio
# ---------------------------------------------------------------------------


def test_abaixo_do_sublimite_nao_avisa_nada():
    d = decompor_margem(_vendas(), _config("3599999.99"))
    assert d.avisos == ()


def test_a_fronteira_e_inclusiva_estar_no_sublimite_e_estar_dentro():
    """R$ 3.600.000 exatos ainda é "dentro".

    A lei fala em *exceder* o sublimite (art. 20). Quem parou em cima
    dele não excedeu, e um aviso aqui seria a Carchuna inventando uma
    obrigação meio real antes da hora.
    """
    d = decompor_margem(_vendas(), _config(SUBLIMITE_ICMS_ISS))
    assert d.avisos == ()


def test_nenhum_numero_mudou_abaixo_do_sublimite():
    """A conferência não pode ter mexido na conta de quem está dentro.

    Os valores abaixo são a decomposição inteira de uma venda de
    R$ 10.000 com RBT12 de R$ 1 mi no Anexo I — se alguma linha mudar,
    esta mudança extrapolou o que ela deveria fazer.
    """
    d = decompor_margem(_vendas(), _config("1000000"))

    assert d.receita_bruta == Decimal("10000.00")
    assert d.deducao("tributos").valor == Decimal("845.00")  # 8,45% do Anexo I
    assert d.deducao("cmv").valor == Decimal("4000.00")
    assert d.deducao("adquirencia").valor == Decimal("200.00")
    assert d.margem_liquida == Decimal("4955.00")
    assert d.avisos == ()


# ---------------------------------------------------------------------------
# A faixa do aviso: o número continua valendo, e a lacuna é dita
# ---------------------------------------------------------------------------


def test_passou_do_sublimite_avisa_e_nao_recusa():
    """R$ 4 mi: fora do sublimite, dentro dos 20%. A conta sai."""
    d = decompor_margem(_vendas(), _config("4000000"))

    assert d.margem_liquida == Decimal("4845.00")  # a conta saiu de verdade
    assert len(d.avisos) == 1
    assert "3.600.000" in d.avisos[0]
    assert "art. 20, § 1º" in d.avisos[0]


def test_um_centavo_acima_do_sublimite_ja_avisa():
    d = decompor_margem(_vendas(), _config("3600000.01"))
    assert len(d.avisos) == 1


def test_exatamente_vinte_por_cento_de_excesso_ainda_e_aviso():
    """R$ 4.320.000 é o limite do art. 20, § 1º, e ele também é inclusivo.

    "Excesso superior a 20%" antecipa a saída para o mês seguinte. Em
    cima dos 20% o excesso não é superior a eles, e a saída continua
    sendo em janeiro — logo, aviso.
    """
    assert Decimal("4320000") == EXCESSO_SUBLIMITE_IMEDIATO
    d = decompor_margem(_vendas(), _config(EXCESSO_SUBLIMITE_IMEDIATO))
    assert len(d.avisos) == 1


def test_o_aviso_e_uma_tupla_de_mensagens_e_nao_uma_string():
    """``avisos`` é ``tuple[str, ...]``, e uma string também é iterável.

    Uma string devolvida no lugar da tupla passa por qualquer ``for`` sem
    reclamar e publica a mensagem letra a letra. O tipo é a única coisa
    que separa um aviso de 567 avisos de um caractere cada.
    """
    d = decompor_margem(_vendas(), _config("4000000"))
    assert isinstance(d.avisos, tuple)
    assert len(d.avisos) == 1
    assert len(d.avisos[0]) > 1


def test_o_aviso_sai_em_avisos_e_nao_na_fonte_da_deducao():
    """Lugar do aviso é `avisos`. A `fonte` é a base legal do número.

    Enfiar o alerta na `fonte` de `tributos` faria a citação legal da
    linha carregar um texto que não fundamenta o valor dela — e o valor
    ali é o DAS, calculado corretamente pelo art. 18, § 1º-A. O que está
    incompleto é o conjunto, não aquela linha.
    """
    d = decompor_margem(_vendas(), _config("4000000"))
    fonte = d.deducao("tributos").fonte

    assert "sublimite" not in fonte.lower()
    assert "art. 20" not in fonte
    assert "art. 18, § 1º-A" in fonte  # continua sendo a fonte do DAS
    assert "sublimite" in d.avisos[0].lower()


def test_o_das_da_faixa_do_aviso_continua_sendo_o_do_anexo():
    """Avisar não é corrigir por conta própria.

    A tentação seria "compensar" a lacuna inflando a dedução. Isso seria
    inventar alíquota de estado e de município. O DAS publicado é o do
    Anexo I, exato, e a lacuna é dita em português.
    """
    d = decompor_margem(_vendas(), _config("4000000"))
    aliquota = margem.aliquota_efetiva_simples(Decimal("4000000"), "I")
    assert d.deducao("tributos").valor == (Decimal("10000") * aliquota).quantize(
        Decimal("0.01")
    )


# ---------------------------------------------------------------------------
# A faixa da recusa
# ---------------------------------------------------------------------------


def test_excesso_de_mais_de_vinte_por_cento_recusa():
    with pytest.raises(ValueError) as erro:
        decompor_margem(_vendas(), _config("4400000"))

    mensagem = str(erro.value)
    assert "4.400.000" in mensagem
    assert "3.600.000" in mensagem
    assert "art. 20, § 1º" in mensagem


def test_um_centavo_acima_dos_vinte_por_cento_ja_recusa():
    with pytest.raises(ValueError):
        decompor_margem(_vendas(), _config("4320000.01"))


def test_a_recusa_nao_estima_icms_nem_iss():
    """A recusa diz o que não sabe, e não preenche o buraco com chute.

    O único percentual que pode aparecer na mensagem é o dos 20% do
    art. 20, § 1º, que é limiar legal e não alíquota. Qualquer outro
    seria a Carchuna inventando ICMS de estado ou ISS de município — o
    que ela não sabe e nesta mensagem está justamente admitindo.
    """
    with pytest.raises(ValueError) as erro:
        decompor_margem(_vendas(), _config("4400000"))

    mensagem = str(erro.value)
    assert "contador" in mensagem
    assert re.findall(r"\d+(?:[.,]\d+)?\s*%", mensagem) == ["20%"]


# ---------------------------------------------------------------------------
# Acima do teto do Simples quem responde é o teto
# ---------------------------------------------------------------------------


def test_acima_do_teto_a_recusa_continua_sendo_a_do_teto():
    """R$ 4,8 mi para cima não é caso de sublimite: é de estar fora.

    A conferência do sublimite roda antes de `aliquota_efetiva_simples`,
    então sem cuidado ela sequestraria a recusa mais fundamental e diria
    ao lojista que o problema é o ICMS/ISS quando o problema é que ele
    não está mais no Simples.
    """
    with pytest.raises(ValueError) as erro:
        decompor_margem(_vendas(), _config("5000000"))

    mensagem = str(erro.value)
    assert "teto do Simples" in mensagem
    assert "sublimite" not in mensagem


def test_em_cima_do_teto_do_simples_ainda_e_recusa_de_sublimite():
    """A fronteira do teto também é inclusiva, e R$ 4,8 mi está dentro dele.

    Quem está exatamente no teto continua no Simples — e continua muito
    acima dos 20% do sublimite. A recusa existe, e é a do sublimite.
    """
    with pytest.raises(ValueError) as erro:
        decompor_margem(_vendas(), _config(TETO_SIMPLES))
    assert "sublimite" in str(erro.value)


# ---------------------------------------------------------------------------
# Um sublimite só no projeto inteiro
# ---------------------------------------------------------------------------


def test_margem_e_crescimento_usam_a_mesma_constante():
    """O valor muda por portaria todo ano; duas cópias divergem numa delas.

    `crescimento.py` declarava o próprio R$ 3.600.000. Duas verdades para
    o mesmo número é uma que vai ficar desatualizada em silêncio na
    virada do ano — e a que sobrevive seria justamente a da tela de
    marcos, que fala do futuro.
    """
    assert crescimento.SUBLIMITE_ICMS_ISS is margem.SUBLIMITE_ICMS_ISS


def test_o_mei_nao_recebe_conferencia_de_sublimite():
    """O sublimite é do Simples. O MEI tem o teto do art. 18-A, e só."""
    mei = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76.00"))
    d = decompor_margem(_vendas(), mei)
    assert all("sublimite" not in a.lower() for a in d.avisos)


# ---------------------------------------------------------------------------
# `hipotetico`: a recusa protege o estado real, não a pergunta
# ---------------------------------------------------------------------------


def test_hipotetico_troca_a_recusa_por_carimbo():
    """Num cenário, atravessar o sublimite é o achado — não motivo de sumir.

    Recusar existe para impedir que o lojista leia como SUA uma margem
    incompleta. Numa simulação ninguém está naquele estado, e a
    travessia é a informação mais valiosa que a simulação tem: "subir 5%
    te leva para uma faixa em que você recolhe ICMS/ISS por fora".
    """
    d = decompor_margem(_vendas(), _config("4400000"), hipotetico=True)

    (carimbo,) = d.avisos
    assert "4.400.000" in carimbo
    assert "não considera" in carimbo
    assert "art. 20, § 1º" in carimbo


def test_hipotetico_nao_muda_nada_abaixo_da_fronteira():
    """A bandeira só age onde havia recusa. No resto, é inerte."""
    for rbt12 in ("1000000", "3600000", "4000000"):
        normal = decompor_margem(_vendas(), _config(rbt12))
        hipo = decompor_margem(_vendas(), _config(rbt12), hipotetico=True)
        assert normal == hipo, f"hipotetico mudou o resultado em {rbt12}"


def test_hipotetico_nao_abre_a_porta_acima_do_teto_do_simples():
    """Fora do Simples, nem cenário existe: não é imposto incompleto.

    Acima de R$ 4,8 mi a empresa está fora do regime. Um cenário
    calculado com as tabelas do Simples ali não seria incompleto, seria
    sem sentido — e `hipotetico` não pode virar chave-mestra para isso.
    """
    with pytest.raises(ValueError, match="teto do Simples"):
        decompor_margem(_vendas(), _config("5000000"), hipotetico=True)


def test_hipotetico_nao_alcanca_o_teto_do_mei():
    """O MEI acima do corte dos 20% continua recusado, com ou sem cenário.

    Mesma razão do teto do Simples: passando de R$ 97.200 o
    desenquadramento retroage ao início do ano, o DAS fixo é o
    instrumento errado, e simular com ele não produz um número
    incompleto — produz um número que não quer dizer nada.

    A fixture subiu de R$ 84.000 para R$ 102.000 quando a recusa do MEI
    passou a começar em R$ 97.200: R$ 84.000 hoje é faixa de aviso, e
    calcular ali é o comportamento certo.
    """
    mei = ConfigTributaria(regime="mei", das_mei_mensal=Decimal("76.00"))
    vendas = [
        Transacao(
            data=date(2026, m, 15),
            canal="loja_propria",
            valor_bruto=Decimal("8500"),
            custo_produto=Decimal("0"),
            frete_pago=Decimal("0"),
        )
        for m in range(1, 13)
    ]  # R$ 102.000 no ano
    with pytest.raises(ValueError, match="art. 18-A"):
        decompor_margem(vendas, mei, hipotetico=True)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
