"""
Sanitizador anti-prompt-injection para tool results.

Aplicado SEMPRE antes de retornar conteudo ao LLM. Substitui padroes
conhecidos por placeholders, trunca resultados excessivos e encapsula
a saida em delimitadores claros para o LLM distinguir dados de instrucoes.

Regra: agent_audit_log guarda o resultado RAW (humano precisa investigar);
apenas o estado do grafo/LLM recebe o sanitizado. Essa assimetria e
intencional — observabilidade de um lado, defesa do outro.
"""

from __future__ import annotations

import re

_SUSPICIOUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"<\|.*?\|>", re.DOTALL),
        "[bloqueado: tokens especiais]",
    ),
    (
        re.compile(r"\[INST\].*?\[/INST\]", re.DOTALL | re.IGNORECASE),
        "[bloqueado: instrucao llama]",
    ),
    (
        re.compile(r"<system>.*?</system>", re.DOTALL | re.IGNORECASE),
        "[bloqueado: tag system]",
    ),
    (
        re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL | re.IGNORECASE),
        "[bloqueado: tool_call falsa]",
    ),
    (
        re.compile(
            r"###\s*(system|instructions?|override|ignore.*previous)[^\n]*",
            re.IGNORECASE,
        ),
        "[bloqueado: diretiva]",
    ),
    (
        re.compile(
            r"ignore\s+(all\s+)?(prior|previous)\s+instructions?",
            re.IGNORECASE,
        ),
        "[bloqueado: override]",
    ),
    (
        re.compile(
            r"\b(you\s+are\s+now|act\s+as|respond\s+only)\b[^\n]{0,200}",
            re.IGNORECASE,
        ),
        "[bloqueado: reatribuicao de persona]",
    ),
    (
        re.compile(r"\bassistant\b\s*[:]\s*", re.IGNORECASE),
        "[bloqueado: role assistant]",
    ),
]

_MAX_TOOL_RESULT_LENGTH = 20_000


def sanitize_tool_result(raw: str, *, tool_name: str) -> tuple[str, list[str]]:
    """Retorna (sanitizado, avisos).

    - Substitui padroes suspeitos por placeholders.
    - Trunca em _MAX_TOOL_RESULT_LENGTH chars (evita blow-up de contexto).
    - Avisos devem ser anexados ao audit log (observabilidade).
    """
    if not isinstance(raw, str):
        raw = str(raw)
    warnings: list[str] = []
    cleaned = raw

    for pattern, replacement in _SUSPICIOUS_PATTERNS:
        matches = pattern.findall(cleaned)
        if matches:
            warnings.append(
                f"{tool_name}: {len(matches)}x padrao suspeito '{pattern.pattern[:40]}'"
            )
            cleaned = pattern.sub(replacement, cleaned)

    if len(cleaned) > _MAX_TOOL_RESULT_LENGTH:
        warnings.append(
            f"{tool_name}: resultado truncado de {len(cleaned)} para "
            f"{_MAX_TOOL_RESULT_LENGTH} chars"
        )
        cleaned = cleaned[:_MAX_TOOL_RESULT_LENGTH] + "\n\n[TRUNCADO]"

    return cleaned, warnings


def wrap_tool_result(clean_result: str, *, tool_name: str) -> str:
    """Envolve o resultado com delimitadores para o LLM distinguir de instrucoes."""
    return (
        f"<tool_result tool={tool_name}>\n"
        f"{clean_result}\n"
        f"</tool_result>"
    )
