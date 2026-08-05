"""O site (`index.html`) não pode divergir do motor.

A demo do site recalcula a decomposição no navegador, e para isso repete
as tabelas do Simples em JavaScript. Duas cópias da mesma tabela é um
convite a mentir: alguém corrige `margem.py` e o site continua mostrando
a alíquota velha para quem chegou pelo GitHub Pages.

Este teste lê os números de dentro do `index.html` e compara com
`carchuna.margem`, faixa a faixa. Se as duas divergirem, é falha — a
regra da casa é que nenhuma afirmação circula sem lastro, e o site
afirma alíquota.
"""

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from carchuna.margem import ANEXOS_SIMPLES, TETO_SIMPLES

SITE = Path(__file__).resolve().parents[1] / "index.html"


def _anexos_do_site() -> dict[str, list[list[int]]]:
    """Extrai o literal `const ANEXOS = {...}` do JavaScript da página."""
    html = SITE.read_text(encoding="utf-8")
    bloco = re.search(r"const ANEXOS = (\{.*?\});", html, re.DOTALL)
    assert bloco, "não achei `const ANEXOS` no index.html"
    # o literal JS vira JSON depois de aspar as chaves I/II/III e tirar a
    # vírgula final, que o JavaScript aceita e o JSON não
    texto = re.sub(r"(\b[IV]+):", r'"\1":', bloco.group(1))
    texto = re.sub(r",(\s*[}\]])", r"\1", texto)
    return json.loads(texto)


def test_o_site_traz_as_mesmas_faixas_do_motor():
    """Cada faixa do site bate com a do `margem.py`, centavo a centavo.

    No site tudo é inteiro para fugir do float do JavaScript: limite e
    parcela a deduzir em CENTAVOS, alíquota nominal em pontos-base
    (400 = 4,00%). A conversão é feita aqui e comparada em `Decimal`.
    """
    do_site = _anexos_do_site()
    for anexo, faixas_site in do_site.items():
        faixas_motor = ANEXOS_SIMPLES[anexo]
        assert len(faixas_site) == len(faixas_motor), (
            f"Anexo {anexo}: o site tem {len(faixas_site)} faixas e o motor "
            f"tem {len(faixas_motor)}"
        )
        for i, ((limite, pb, pd), (m_limite, m_aliq, m_pd)) in enumerate(
            zip(faixas_site, faixas_motor, strict=True)
        ):
            assert (
                Decimal(limite) / 100 == m_limite
            ), f"Anexo {anexo}, faixa {i}: limite"
            assert Decimal(pb) / 10000 == m_aliq, f"Anexo {anexo}, faixa {i}: alíquota"
            assert Decimal(pd) / 100 == m_pd, f"Anexo {anexo}, faixa {i}: dedução"


def test_o_teto_do_simples_citado_no_site_e_o_do_motor():
    """R$ 4,8 milhões aparece no texto da página e vem da LC 123, art. 3º."""
    html = SITE.read_text(encoding="utf-8")
    assert Decimal("4800000") == TETO_SIMPLES
    assert "4,8 milhões" in html
    assert "art. 3º, II" in html


def test_a_demo_do_site_cita_a_fonte_legal_da_formula():
    """Nenhuma alíquota sem lastro — inclusive na página de marketing."""
    html = SITE.read_text(encoding="utf-8")
    assert "art. 18, § 1º-A" in html
    assert "LC 123/2006" in html


def test_a_decomposicao_de_exemplo_do_site_bate_com_o_motor():
    """A venda de R$ 100 impressa na home é conferida pelo motor.

    Conta à mão, Anexo I com RBT12 de R$ 360.000 (2ª faixa: alíquota
    nominal 7,3%, parcela a deduzir R$ 5.940):

        efetiva = (360.000 × 0,073 − 5.940) / 360.000
                = (26.280 − 5.940) / 360.000 = 0,0565 → 5,65%

    e daí a venda de R$ 100: 100,00 − 5,65 (tributos) − 12,00 (comissão)
    − 10,00 (frete) − 40,00 (CMV) = 32,35 de margem líquida, 32,35%.
    """
    from datetime import date

    from carchuna.margem import (
        ConfigTributaria,
        TabelaCustos,
        Transacao,
        decompor_margem,
    )

    html = SITE.read_text(encoding="utf-8")
    config = ConfigTributaria(
        regime="simples", anexo_simples="I", rbt12=Decimal("360000")
    )
    tabela = TabelaCustos(
        comissao_canal={"shopee": Decimal("0.12")},
        taxa_adquirencia=Decimal("0"),
        taxa_antecipacao_mensal=Decimal("0"),
    )
    decomposicao = decompor_margem(
        [
            Transacao(
                data=date(2026, 5, 1),
                canal="shopee",
                valor_bruto=Decimal("100.00"),
                custo_produto=Decimal("40.00"),
                frete_pago=Decimal("10.00"),
            )
        ],
        config,
        tabela,
    )
    assert decomposicao.deducao("tributos").valor == Decimal("5.65")
    assert decomposicao.deducao("comissoes_canal").valor == Decimal("12.00")
    assert decomposicao.margem_liquida == Decimal("32.35")

    # e é isso que está escrito na página
    assert "R$ 5,65" in html
    assert "R$ 32,35" in html
    assert "32,35%" in html


def _node_disponivel() -> bool:
    import shutil

    return shutil.which("node") is not None


@pytest.mark.skipif(not _node_disponivel(), reason="precisa do node para rodar o JS")
@pytest.mark.parametrize(
    "rbt12,anexo",
    [
        (Decimal("180000"), "I"),  # topo da 1ª faixa
        (Decimal("360000"), "I"),  # topo da 2ª — a do exemplo da home
        (Decimal("500000"), "I"),  # meio da 3ª
        (Decimal("4200000"), "I"),  # 6ª faixa, onde a dedução é enorme
        (Decimal("900000"), "II"),
        (Decimal("2000000"), "III"),
    ],
)
def test_a_formula_do_site_devolve_a_mesma_aliquota_do_motor(rbt12, anexo):
    """Não basta a tabela bater: a CONTA do navegador tem que bater também.

    O JS calcula em pontos-base com inteiros e o Python em `Decimal`;
    as duas implementações da fórmula do art. 18, § 1º-A precisam dar o
    mesmo número, senão o visitante do site vê uma alíquota que o motor
    não assina.
    """
    import json
    import subprocess

    from carchuna.margem import aliquota_efetiva_simples

    html = SITE.read_text(encoding="utf-8")
    anexos = re.search(r"(const ANEXOS = \{.*?\};)", html, re.DOTALL).group(1)
    funcao = re.search(r"(function aliquotaEfetiva\(.*?\n\})", html, re.DOTALL).group(1)
    script = (
        f"{anexos}\n{funcao}\n"
        f"console.log(JSON.stringify(aliquotaEfetiva({int(rbt12) * 100}, "
        f'"{anexo}")));'
    )
    saida = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    do_site = Decimal(str(json.loads(saida.stdout))) / 10000

    do_motor = aliquota_efetiva_simples(rbt12, anexo)
    # o JS trabalha em pontos-base inteiros; comparar na 6ª casa da fração
    assert do_site.quantize(Decimal("0.000001")) == do_motor.quantize(
        Decimal("0.000001")
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
