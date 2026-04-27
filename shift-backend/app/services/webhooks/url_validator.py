"""Validacao SSRF de URLs de webhook (Tarefa 1 do hardening 6.2/6.3).

Por que existe
--------------
``HttpUrl`` do Pydantic so verifica forma — nao bloqueia hosts internos.
Sem este modulo, qualquer cliente (ou atacante com permissao MANAGER) pode
cadastrar URL apontando pra:

- ``localhost`` / ``127.0.0.1``      → bate processos da mesma maquina
- 10/8, 172.16/12, 192.168/16        → bate redes privadas do host
- ``169.254.169.254``                → AWS metadata service (vaza creds IAM!)
- ``metadata.google.internal``       → GCP metadata
- IPv6 link-local (``fe80::/10``), IPv6 loopback (``::1``), IPv4-mapped

A funcao publica ``validate_webhook_url`` cobre as 3 camadas:

1. **Hostname literal**: rejeita nomes "internos" conhecidos.
2. **IP literal**: rejeita IPs em todas as faixas perigosas (privado,
   loopback, link-local, multicast, reservado, unspecified, em IPv4 e IPv6).
3. **Resolucao DNS**: chama ``getaddrinfo`` e bloqueia se *qualquer* IP
   resolvido cair nas faixas acima — defesa contra hostname publico que
   resolve pra IP interno (ex: ``evil.com`` → ``10.0.0.5``).

A camada 3 nao protege contra DNS rebinding *no momento do dispatch* —
isso e responsabilidade da Tarefa 2 (re-resolucao + verificacao na hora
do POST). Aqui so impedimos o cadastro inicial.

Mensagens de erro opacas
------------------------
``WebhookUrlError`` SEMPRE traz a mesma mensagem ("URL nao permitida ...")
sem mencionar IP/host especifico. Isso evita ajudar um atacante a mapear
a topologia interna a partir de erros do POST de cadastro.

Os detalhes especificos vao para LOG (com nivel WARNING) em vez do
ValidationError publico — operadores conseguem auditar via logs sem
expor pelo response.

Bypass para testes locais
-------------------------
``WEBHOOK_ALLOW_INSECURE_HOSTS=true`` desliga TODAS as validacoes de
host/IP. Default e ``False``. Em producao deve permanecer false.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from typing import Iterable
from urllib.parse import urlparse

from pydantic import HttpUrl


logger = logging.getLogger(__name__)


# Hostnames "internos" conhecidos. Match e case-insensitive e contra a
# raiz exata (sem subdominios). ``metadata.google.internal`` cobre o
# caso GCP; ``metadata.aws.internal`` o caso AWS (via DNS, alem do IP);
# ``instance-data`` e usado por algumas distros AWS.
_BLOCKED_HOSTNAMES: frozenset[str] = frozenset({
    "localhost",
    "metadata",
    "metadata.google.internal",
    "metadata.aws.internal",
    "instance-data",
})


# IPs literais bloqueados (alem das checagens automaticas via ipaddress).
# 169.254.169.254 e o magico de AWS/GCP/Azure metadata. Ja seria detectado
# por ``is_link_local``, mas listamos explicitamente pra clareza.
_BLOCKED_IP_LITERALS: frozenset[str] = frozenset({
    "169.254.169.254",
    "::1",  # IPv6 loopback — tambem detectado via is_loopback
})


# Mensagem unica e opaca pra error response. Detalhes vao pra log.
_OPAQUE_ERROR = (
    "URL nao permitida: hostname privado, interno ou nao resolvivel."
)


# -----------------------------------------------------------------------
# API publica
# -----------------------------------------------------------------------


class WebhookUrlError(ValueError):
    """Levantado quando a URL falha qualquer checagem SSRF.

    Subclasse de ``ValueError`` para que pydantic/FastAPI converta
    automaticamente em 422. Mensagem propositalmente generica.
    """


def validate_webhook_url(url: str | HttpUrl) -> HttpUrl:
    """Aceita string ou HttpUrl, retorna HttpUrl validada contra SSRF.

    Validacoes (ordem):
      1. Esquema = HTTPS (lanca em ``http://`` etc., a menos que
         ``WEBHOOK_ALLOW_INSECURE_HOSTS`` esteja ligado).
      2. Hostname nao bate ``_BLOCKED_HOSTNAMES``.
      3. Se for IP literal, nao bate ``_BLOCKED_IP_LITERALS`` nem
         ranges privados/reservados.
      4. Se for hostname, ``getaddrinfo`` resolve para IPs publicos;
         qualquer IP em faixa privada/loopback/link-local/etc rejeita.
      5. Porta != 80/443 emite WARN (mas aceita).

    Levanta ``WebhookUrlError`` em qualquer falha. Detalhes ficam em LOG.
    """
    if _is_insecure_mode():
        # Modo dev: aceita qualquer URL HTTP(S). Util pra testes contra
        # ngrok/localhost. Loga que o bypass esta ativo (segurança em
        # camadas — visibilidade pelo menos via log).
        logger.warning(
            "webhook.url.insecure_mode_active",
            extra={"url_host": _safe_host(url)},
        )
        return _coerce_to_http_url(url)

    parsed = urlparse(str(url))

    # 1. Esquema
    if parsed.scheme.lower() != "https":
        logger.warning(
            "webhook.url.rejected.scheme",
            extra={"scheme": parsed.scheme, "host": parsed.hostname},
        )
        raise WebhookUrlError(_OPAQUE_ERROR)

    # Hostname obrigatorio (parse robusto)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        logger.warning("webhook.url.rejected.no_host")
        raise WebhookUrlError(_OPAQUE_ERROR)

    # 2. Hostname literalmente bloqueado
    if host in _BLOCKED_HOSTNAMES:
        logger.warning("webhook.url.rejected.blocked_hostname", extra={"host": host})
        raise WebhookUrlError(_OPAQUE_ERROR)

    # 3+4. IP literal vs hostname publico
    try:
        ip_obj = ipaddress.ip_address(host.strip("[]"))  # ip_address aceita "::1" mas nao "[::1]"
        # Era IP literal — checa direto.
        if str(ip_obj) in _BLOCKED_IP_LITERALS or _ip_is_dangerous(ip_obj):
            logger.warning(
                "webhook.url.rejected.dangerous_ip_literal",
                extra={"ip": str(ip_obj)},
            )
            raise WebhookUrlError(_OPAQUE_ERROR)
    except ValueError:
        # Hostname — resolve via DNS.
        for resolved in _resolve_all(host, parsed.port or 443):
            if _ip_is_dangerous(resolved):
                logger.warning(
                    "webhook.url.rejected.dns_resolves_to_internal",
                    extra={"host": host, "resolved": str(resolved)},
                )
                raise WebhookUrlError(_OPAQUE_ERROR)

    # 5. Porta nao-padrao = warning, nao bloqueio
    if parsed.port is not None and parsed.port not in (80, 443):
        logger.warning(
            "webhook.url.unusual_port",
            extra={"host": host, "port": parsed.port},
        )

    return _coerce_to_http_url(url)


# -----------------------------------------------------------------------
# Helpers internos
# -----------------------------------------------------------------------


def _is_insecure_mode() -> bool:
    """Le ``WEBHOOK_ALLOW_INSECURE_HOSTS`` direto da env — nao depende de
    ``settings`` para que testes possam ``monkeypatch.setenv`` sem
    reinicializar o singleton."""
    raw = (os.getenv("WEBHOOK_ALLOW_INSECURE_HOSTS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _coerce_to_http_url(url: str | HttpUrl) -> HttpUrl:
    """Devolve sempre um ``HttpUrl`` (Pydantic faz parsing/validacao
    sintatica). Nao re-valida SSRF aqui — caller ja chamou."""
    if isinstance(url, HttpUrl):
        return url
    # Pydantic v2: HttpUrl(string) levanta ValueError se invalido.
    return HttpUrl(str(url))  # type: ignore[arg-type]


def _safe_host(url: str | HttpUrl) -> str:
    """Extrai hostname para log sem expor path/credenciais."""
    try:
        return urlparse(str(url)).hostname or "<unknown>"
    except Exception:  # noqa: BLE001
        return "<unparseable>"


def _resolve_all(host: str, port: int) -> Iterable[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve ``host`` para todos os IPs (v4 + v6).

    ``getaddrinfo`` pode levantar ``socket.gaierror`` se DNS nao
    resolver. Tratamos como "rejeita" — host inalcancavel nao deveria
    virar webhook subscription.
    """
    try:
        infos = socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        logger.warning("webhook.url.dns_unresolvable", extra={"host": host})
        raise WebhookUrlError(_OPAQUE_ERROR)

    for family, _socktype, _proto, _canonname, sockaddr in infos:
        # sockaddr varia: (ip, port) IPv4; (ip, port, flow, scope) IPv6.
        ip_str = sockaddr[0]
        try:
            yield ipaddress.ip_address(ip_str)
        except ValueError:  # noqa: PERF203 — defensivo
            continue


def _ip_is_dangerous(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """``True`` se o IP cai em faixa que NAO deve ser destino de webhook.

    Cobre, em IPv4 e IPv6:
    - loopback         (127.0.0.0/8, ::1)
    - private          (RFC1918, fc00::/7)
    - link-local       (169.254.0.0/16, fe80::/10)
    - multicast        (224.0.0.0/4, ff00::/8)
    - reserved         (varios)
    - unspecified      (0.0.0.0, ::)

    IPv4-mapped IPv6 (``::ffff:0:0/96``) e detectado via
    ``ipv4_mapped`` — desempacota o IPv4 e re-aplica as checagens.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _ip_is_dangerous(ip.ipv4_mapped)

    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )
