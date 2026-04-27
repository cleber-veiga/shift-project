"""Sanitizacao de logs para evitar vazamento de credenciais.

O Shift manipula connection_strings, tokens de API e chaves Fernet.
Sem cuidado, qualquer ``logger.info("config %s", config)`` vaza isso.
Este modulo prove dois mecanismos:

1. **structlog processor** (``sanitize_processor``) que roda em cada log
   emitido — varre o ``event_dict`` recursivamente e substitui valores
   por ``<REDACTED>`` quando:
     a) a CHAVE bate uma das ``SECRET_KEY_NAMES`` (case-insensitive,
        substring match — ``LLM_API_KEY`` bate ``api_key``);
     b) o VALOR bate um padrao reconhecidamente sensivel (Bearer token,
        URL com user:password, base64 de Fernet key etc.).

2. ``sanitize_event_dict(d)`` para uso direto fora do pipeline structlog
   (ex: ao serializar um payload de webhook para auditoria).

Limitacoes
----------
- Nao tenta detectar secrets em logs de bibliotecas terceiras que escrevam
  via stdlib ``logging`` SEM passar pelo structlog. Para esses, considere
  configurar ``logging.basicConfig`` com formatador estruturado e enviar
  para o mesmo pipeline (assunto separado).
- Match por nome de chave e o caminho mais barato e cobre 95% dos casos.
  O match por valor existe para pegar o que escapou (ex: alguem joga uma
  ``connection_string`` num campo ``url``). Tem custo — mas roda apenas
  no caminho de log e ainda e ~us por evento.
- Limite de profundidade de recursao (``_MAX_DEPTH``) evita estouro em
  estruturas circulares.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


REDACTED = "<REDACTED>"

# Limite de profundidade: o caminho normal de log raramente passa de 5
# niveis. Acima disso paramos de recursar para nao gastar tempo em
# estruturas cripticas — o conteudo profundo passa intacto, mas isso e
# preferivel a um stack overflow.
_MAX_DEPTH = 6


# ---------------------------------------------------------------------------
# Match por nome de chave
# ---------------------------------------------------------------------------


# Substrings: se o nome da chave (lower) contem qualquer destas, o valor
# e mascarado independente do conteudo. Mantemos como tuple para iteracao
# determinista e ordenada (case-insensitive ja foi aplicado no caller).
SECRET_KEY_NAMES: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "access_token",
    "refresh_token",
    "private_key",
    "client_secret",
    "encryption_key",
    "fernet",
    "credential",
    "credentials",
    "authorization",
    "auth_token",
    "session_id",  # tokens de sessao em geral
    "cookie",
    # Conexoes
    "connection_string",
    "conn_string",
    "dsn",
    "database_url",
    "db_url",
    # LLM/integracoes
    "openai_api_key",
    "anthropic_api_key",
    "google_api_key",
    "resend_api_key",
)


# Chaves explicitamente seguras (whitelist) — usadas em logs comuns,
# nao mascarar mesmo que contenham substring de SECRET_KEY_NAMES.
# Ex: ``token_count`` (tokens de LLM) nao e segredo.
_SAFE_KEY_OVERRIDES: frozenset[str] = frozenset({
    "token_count",
    "tokens_in",
    "tokens_out",
    "total_tokens",
    "tokens_used",
    "is_authorization_required",
    "secret_required",
    "has_credentials",
})


def _key_is_secret(key: str) -> bool:
    """``True`` se o nome de chave parece referir a um valor sensivel."""
    if not isinstance(key, str):
        return False
    low = key.lower()
    if low in _SAFE_KEY_OVERRIDES:
        return False
    return any(needle in low for needle in SECRET_KEY_NAMES)


# ---------------------------------------------------------------------------
# Match por valor — heuristicas para conteudo claramente sensivel
# ---------------------------------------------------------------------------


# 1. Bearer / Basic / Token authorization headers.
_AUTH_HEADER_RE = re.compile(
    r"^\s*(Bearer|Basic|Token)\s+\S+", re.IGNORECASE,
)
# 2. URL com credentials embutidas: ``scheme://user:pass@host/...``.
_URL_CREDS_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9+\-.]*://[^/\s:@]+:[^/\s@]+@",
)
# 3. Fernet key — 44 chars base64-url-safe terminando em ``=``. Falso
#    positivo possivel mas raro em log normal.
_FERNET_RE = re.compile(r"^[A-Za-z0-9_\-]{43}=$")
# 4. OpenAI/Anthropic API keys — prefixos conhecidos.
_KNOWN_API_KEY_RE = re.compile(
    r"\b(sk-[A-Za-z0-9_\-]{20,}|sk-ant-[A-Za-z0-9_\-]{20,}|"
    r"AIza[A-Za-z0-9_\-]{20,}|"  # google
    r"re_[A-Za-z0-9_]{20,})",  # resend
)
# 5. JWT — 3 segmentos base64url separados por ``.``. Heuristica:
#    ``eyJ`` no inicio (header decodado costuma comecar com ``{"alg":...``).
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")


def _value_looks_like_secret(value: str) -> bool:
    if not value or len(value) < 16:
        # Strings curtas dificilmente sao tokens reais; evita falsos positivos
        # em ids curtos (UUIDs com 36 chars passam, JWTs reais sao ~100+).
        return False
    if _AUTH_HEADER_RE.search(value):
        return True
    if _URL_CREDS_RE.search(value):
        return True
    if _FERNET_RE.match(value):
        return True
    if _KNOWN_API_KEY_RE.search(value):
        return True
    if _JWT_RE.search(value):
        return True
    return False


def _redact_value_keep_url(value: str) -> str:
    """Para URLs com creds, preserva a estrutura mas redata user:pass.

    Util para diagnostico — manter o host/banco visivel enquanto esconde a
    senha. ``postgres://shift:abc123@db:5432/shift`` →
    ``postgres://<REDACTED>@db:5432/shift``.
    """
    return _URL_CREDS_RE.sub(
        lambda m: m.group(0).split("://")[0] + "://" + REDACTED + "@",
        value,
    )


# ---------------------------------------------------------------------------
# Recursao
# ---------------------------------------------------------------------------


def _sanitize(obj: Any, depth: int = 0) -> Any:
    if depth >= _MAX_DEPTH:
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_pair(k, v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(item, depth + 1) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize(item, depth + 1) for item in obj)
    if isinstance(obj, str):
        return _sanitize_string(obj)
    return obj


def _sanitize_pair(key: Any, value: Any, depth: int) -> Any:
    if _key_is_secret(key if isinstance(key, str) else str(key)):
        return REDACTED
    return _sanitize(value, depth)


def _sanitize_string(value: str) -> str:
    """Aplica heuristicas de match por valor.

    URLs com creds preservam a estrutura (host/database visiveis); outros
    padroes sao integralmente redatados — manter trecho e arriscar leak.
    """
    if not isinstance(value, str):
        return value
    if _URL_CREDS_RE.search(value):
        return _redact_value_keep_url(value)
    if _value_looks_like_secret(value):
        return REDACTED
    return value


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------


def sanitize_event_dict(event_dict: dict[str, Any]) -> dict[str, Any]:
    """Sanitiza recursivamente um dicionario de evento de log.

    Nao muta o dict de entrada — devolve uma copia limpa. (Isso e mais caro
    mas evita surpresas para o caller que ainda vai usar o original.)
    """
    if not isinstance(event_dict, dict):
        return event_dict
    return {k: _sanitize_pair(k, v, depth=1) for k, v in event_dict.items()}


def sanitize_processor(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor — pluga em ``app.core.logging``.

    Mutates in-place quando seguro (estruturas internas do structlog),
    mas a funcao trata o caso de receber um dict ja imutavel devolvendo
    o sanitizado. structlog encadeia processors — entao retornar o dict
    mutado e o contrato esperado.
    """
    return sanitize_event_dict(event_dict)


def add_secret_keys(extra: Iterable[str]) -> None:
    """Adiciona substrings de chave a serem mascaradas em runtime.

    Usado por testes / extensoes que querem incluir nomes proprios
    (ex: chave customizada de integracao). Nao remove existentes.
    """
    global SECRET_KEY_NAMES  # noqa: PLW0603
    extra_clean = tuple(s.lower() for s in extra if isinstance(s, str) and s)
    SECRET_KEY_NAMES = tuple({*SECRET_KEY_NAMES, *extra_clean})
