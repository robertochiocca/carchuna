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

MODEL = os.environ.get("CARCHUNA_MODEL", "claude-opus-4-8")

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
    if anthropic is None or not dispositivos:
        return None
    if os.environ.get("CARCHUNA_USAR_LLM", "1") != "1":
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
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
