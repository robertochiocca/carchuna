"""O que o pipeline permite a um passo comprometido.

Não há aqui ataque de visitante: a superfície é o build. Uma action de
terceiro roda com o token do workflow, e uma dependência com `>=` aberto
resolve sozinha a cada build — sem lockfile, sem aviso e sem ninguém
revisando o que entrou antes de o Streamlit Cloud publicar.

Estes testes leem os arquivos de configuração. É o único jeito de prender
isto sem rodar o GitHub, e a alternativa era não prender.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RAIZ = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((RAIZ / ".github" / "workflows").glob("*.yml"))

# `uses: dono/repo@ref` — o ref é o que interessa.
_USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _acoes_de(caminho: Path) -> list[str]:
    return _USES.findall(caminho.read_text(encoding="utf-8"))


def test_existe_workflow_para_conferir():
    assert WORKFLOWS, "os workflows sumiram — este arquivo ficaria vazio"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_toda_action_esta_pinada_por_sha(workflow):
    """`@v4` é um ponteiro que o dono move quando quiser.

    Quem controla a tag controla o que roda com o token do workflow. O
    SHA é imutável, e o comentário ao lado guarda a legibilidade que a
    tag dava.
    """
    for acao in _acoes_de(workflow):
        _, _, ref = acao.partition("@")
        assert _SHA.match(ref), f"{acao} não está pinada por SHA em {workflow.name}"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_todo_workflow_declara_permissoes(workflow):
    """Sem `permissions:`, vale o default do repositório — que não se lê
    do código, e pode ser de escrita."""
    assert "permissions:" in workflow.read_text(encoding="utf-8")


def test_o_ci_so_le_o_repositorio():
    """O workflow que roda código de terceiro é o que menos pode escrever.

    É nele que uma dependência ou uma action comprometida executaria, e é
    nele que o token precisa não valer nada além de ler.
    """
    ci = (RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "contents: read" in ci
    assert "contents: write" not in ci


def test_o_ci_audita_as_dependencias():
    """Sem isto, uma CVE conhecida entrava calada no próximo deploy."""
    ci = (RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pip-audit" in ci


def test_o_pip_audit_nao_virou_dependencia_do_projeto():
    """O núcleo tem zero dependências por desenho, e segurança não paga
    esse preço: pip-audit é ferramenta de CI e não entra em lugar nenhum
    que o lojista instale."""
    requisitos = (RAIZ / "requirements.txt").read_text(encoding="utf-8")
    projeto = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    assert "pip-audit" not in requisitos
    assert "dependencies = []" in projeto


def test_o_dependabot_cobre_pip_e_as_actions():
    """Pinar por SHA sem Dependabot troca "versão que muda sozinha" por
    "versão que nunca é corrigida", e a segunda é pior."""
    config = (RAIZ / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: pip" in config
    assert "package-ecosystem: github-actions" in config


def test_o_gitignore_cobre_os_arquivos_de_segredo():
    ignorados = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    for padrao in (".streamlit/secrets.toml", ".env", "*.pem", "*.key"):
        assert padrao in ignorados, f"{padrao} não está no .gitignore"


def test_o_env_example_lista_nomes_e_nenhum_valor():
    """O arquivo existe para dizer QUAIS variáveis, nunca o conteúdo."""
    exemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=" in exemplo
    assert "CARCHUNA_LER_CAMINHO=" in exemplo
    for linha in exemplo.splitlines():
        if "=" in linha and not linha.lstrip().startswith("#"):
            _, _, valor = linha.partition("=")
            assert valor.strip() == "", f"{linha!r} traz valor"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
