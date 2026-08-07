"""Camada de geração com LLM — opcional por desenho (padrão DireitoAberto).

Sem ``ANTHROPIC_API_KEY`` (ou sem o pacote ``anthropic``), tudo continua
funcionando em modo extrativo: os dispositivos recuperados e uma
orientação padrão. O cálculo da margem NUNCA depende de LLM — a única
feature de geração da v1 é a narrativa em linguagem natural (respostas do
diagnóstico e texto do relatório).
"""

from __future__ import annotations

import os

try:
    import anthropic
except ImportError:  # dependência opcional
    anthropic = None

# O modelo é configurável por ambiente; este é o padrão de quem clona o
# repositório e não configura nada. Escolha deliberada de um modelo da
# faixa intermediária: a tarefa aqui é redigir, em português, um texto
# que já vem com os dispositivos legais e os números prontos no contexto
# — não é raciocínio pesado, e o padrão não deve queimar o crédito de
# quem só quer ver o projeto rodando.
MODELO_PADRAO = "claude-sonnet-5"


def modelo_configurado() -> str:
    """Qual modelo a narrativa vai usar (lido do ambiente a cada chamada).

    Lido na hora, e não uma vez na importação, para que trocar
    ``CARCHUNA_MODEL`` valha sem reimportar o módulo — o dashboard e a
    API vivem em processos longos.
    """
    return os.environ.get("CARCHUNA_MODEL") or MODELO_PADRAO


def _credencial_no_ambiente() -> bool:
    """Se há credencial da API exportada no ambiente.

    Vale como diagnóstico, **não** como porteiro: o SDK também aceita
    perfil de credencial gravado em disco, e barrar a chamada por
    ausência das variáveis recusaria quem autenticou por esse caminho.
    Por isso a geração continua sendo tentada; o que esta função alimenta
    é a mensagem de `/api/v1/saude`.
    """
    return bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )


def _ligada() -> bool:
    """Se a Carchuna vai sequer tentar gerar a narrativa.

    Duas condições, e credencial não é uma delas — ver
    ``_credencial_no_ambiente``.
    """
    return anthropic is not None and os.environ.get("CARCHUNA_USAR_LLM", "1") == "1"


def estado_da_geracao() -> dict:
    """O que a Carchuna sabe dizer sobre a narrativa opcional, sem chamá-la.

    Existe porque "a narrativa não apareceu" tinha exatamente uma
    explicação visível — nenhuma. Sem pacote, sem credencial, desligada
    por variável ou com modelo trocado, o efeito na tela era o mesmo
    texto extrativo, e quem estava subindo a Carchuna não tinha como
    saber em qual dos casos estava. O ``motivo`` diz qual é e o que
    fazer a respeito.

    Nunca devolve a credencial nem parte dela — só se existe.
    """
    if anthropic is None:
        motivo = (
            "O pacote `anthropic` não está instalado. A Carchuna funciona "
            "inteira sem ele (modo extrativo, com os dispositivos legais "
            "citados); para ligar a narrativa em linguagem natural, instale "
            "o extra: `pip install -e .[llm]`."
        )
    elif os.environ.get("CARCHUNA_USAR_LLM", "1") != "1":
        motivo = (
            "A narrativa está desligada por `CARCHUNA_USAR_LLM`. Defina "
            "`CARCHUNA_USAR_LLM=1` para ligá-la."
        )
    elif not _credencial_no_ambiente():
        motivo = (
            "Não encontrei credencial da API nas variáveis de ambiente. "
            "Exporte `ANTHROPIC_API_KEY` antes de subir a Carchuna. Se você "
            "autenticou por perfil gravado em disco, ignore este aviso: a "
            "chamada será tentada assim mesmo. De todo modo o diagnóstico "
            "sai igual, em modo extrativo — o cálculo nunca dependeu disto."
        )
    else:
        motivo = None
    return {
        "disponivel": _ligada(),
        "credencial_no_ambiente": _credencial_no_ambiente(),
        "modelo": modelo_configurado(),
        "motivo": motivo,
    }


SYSTEM_PROMPT = """\
Você é o assistente da Carchuna, plataforma de diagnóstico de margem para \
pequenas e médias empresas brasileiras. Sua função é INFORMAR o lojista, \
nunca decidir por ele nem prometer resultados.

Regras:
- Responda em português simples, no vocabulário do lojista, em no máximo \
4 parágrafos curtos.
- Baseie-se EXCLUSIVAMENTE nos dispositivos legais e números fornecidos no \
contexto. Se eles não bastarem para responder, diga isso com clareza.
- Use linguagem cautelosa ("em regra", "há indício", "possivelmente") — \
detalhes do caso concreto podem mudar a resposta.
- Cite os dispositivos pelo nome (ex.: "art. 18 da LC 123/2006") ao usá-los.
- NUNCA afirme "você tem direito a receber R$ X de volta" nem prometa \
recuperação tributária; no máximo, aponte o indício e a base legal.
- Não invente lei, número, alíquota ou prazo que não esteja no contexto.
- Termine SEMPRE orientando: "confirme com seu contador ou advogado antes \
de agir".\
"""


def _montar_contexto(dispositivos) -> str:
    blocos = []
    for disp in dispositivos:
        blocos.append(
            f"[{disp.lei} — {disp.artigo}]\n{disp.texto}\nFonte: {disp.fonte}"
        )
    return "\n\n".join(blocos)


def gerar_resposta(pergunta: str, dispositivos) -> str | None:
    """Gera a resposta com o LLM. Retorna ``None`` se ele estiver indisponível."""
    if not dispositivos or not _ligada():
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=modelo_configurado(),
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Dispositivos legais recuperados para esta dúvida:\n\n"
                        f"{_montar_contexto(dispositivos)}\n\n"
                        f"Dúvida do lojista: {pergunta}"
                    ),
                }
            ],
        )
        if response.stop_reason == "refusal":
            return None
        texto = "".join(b.text for b in response.content if b.type == "text").strip()
        return texto or None
    except Exception:
        # Sem credenciais, sem rede ou erro da API: cai no modo extrativo.
        return None


def resposta_extrativa(pergunta: str, dispositivos) -> str:
    """Fallback sem LLM: apresenta os dispositivos encontrados com orientação."""
    if not dispositivos:
        return (
            "Não encontrei, na base atual da Carchuna, dispositivos legais "
            "diretamente relacionados à sua dúvida. Tente reformular com "
            "palavras como 'taxa da maquininha', 'antecipação', 'anexo do "
            "Simples', 'devolução' ou 'comissão do marketplace' — ou leve a "
            "questão ao seu contador ou advogado."
        )
    linhas = [
        "Encontrei possível relação da sua situação com os seguintes "
        "dispositivos legais:\n"
    ]
    for disp in dispositivos:
        pendente = "" if disp.revisado else " [revisão humana pendente]"
        linhas.append(f"• {disp.lei}, {disp.artigo}{pendente}: {disp.resumo}")
    linhas.append(
        "\nIsto é informação geral, não parecer jurídico nem promessa de "
        "recuperação de valores. Confirme com seu contador ou advogado "
        "antes de agir."
    )
    return "\n".join(linhas)
