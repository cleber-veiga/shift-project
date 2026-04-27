"""Testes do validador SSRF de URLs de webhook (Tarefa 1, hardening 6.2/6.3).

Cobertura:
- 12 casos de URL bloqueada (literais, RFC1918, metadata, link-local, IPv6, etc).
- DNS resolution bloqueia hostname publico que resolve pra IP interno.
- HTTPS externo legitimo passa.
- Flag ``WEBHOOK_ALLOW_INSECURE_HOSTS`` libera tudo em dev.
- Mensagens de erro sao opacas (nao vazam IP/hostname interno).
- Schema do webhook usa o validador (rejeita os mesmos casos via FastAPI).
"""

from __future__ import annotations

import socket
from unittest.mock import patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.webhook_subscription import (
    WebhookSubscriptionCreate,
    WebhookSubscriptionUpdate,
)
from app.services.webhooks.url_validator import (
    WebhookUrlError,
    validate_webhook_url,
)


# Helper minimo: schema valido exceto pela URL.
def _schema_kwargs(url: str) -> dict:
    return {
        "workspace_id": UUID("00000000-0000-0000-0000-000000000001"),
        "url": url,
        "events": ["execution.completed"],
    }


# -----------------------------------------------------------------------
# Casos bloqueados
# -----------------------------------------------------------------------


# Lista parametrica do spec — TODAS devem cair em ValidationError.
_BLOCKED_URLS = [
    "http://localhost/hook",                 # http (esquema)
    "https://localhost/hook",                # localhost por nome
    "https://127.0.0.1/hook",                # loopback IPv4
    "https://[::1]/hook",                    # loopback IPv6
    "https://10.0.0.5/hook",                 # RFC1918
    "https://172.20.1.1/hook",               # RFC1918
    "https://192.168.1.1/hook",              # RFC1918
    "https://169.254.169.254/m",             # AWS metadata
    "https://metadata.google.internal/",     # GCP metadata
    "https://[fe80::1]/hook",                # link-local IPv6
    "ftp://example.com/hook",                # esquema errado
    "http://example.com/hook",               # http (nao https)
]


@pytest.mark.parametrize("url", _BLOCKED_URLS)
def test_url_blocked_by_validator(url):
    """Funcao pura levanta ``WebhookUrlError`` — caller nao convertido ainda."""
    with pytest.raises(WebhookUrlError):
        validate_webhook_url(url)


@pytest.mark.parametrize("url", _BLOCKED_URLS)
def test_url_blocked_by_schema(url):
    """Schema converte ``WebhookUrlError`` em ``ValidationError`` (pydantic)."""
    with pytest.raises(ValidationError):
        WebhookSubscriptionCreate(**_schema_kwargs(url))


@pytest.mark.parametrize("url", _BLOCKED_URLS)
def test_update_schema_blocks_same_urls(url):
    """``WebhookSubscriptionUpdate`` aplica a mesma validacao quando ``url`` e enviada."""
    with pytest.raises(ValidationError):
        WebhookSubscriptionUpdate(url=url)


# -----------------------------------------------------------------------
# DNS rebind no momento do CREATE — hostname publico que resolve pra IP interno
# -----------------------------------------------------------------------


def test_dns_resolution_blocked(monkeypatch):
    """Hostname ``evil.example`` resolve pra 10.0.0.5 → bloqueia.

    Atacante poderia controlar DNS dele e responder IP interno.
    O cadastro precisa pegar isso ja na hora do CREATE.
    """
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if "evil" in host:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]
        # Para HTTPS legitimo, deixa o socket real (mas nao deveria ser chamado).
        return socket.getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(WebhookUrlError):
        validate_webhook_url("https://evil.example/hook")


def test_dns_with_ipv6_mapped_to_v4_blocked(monkeypatch):
    """IPv6-mapped IPv4 (``::ffff:10.0.0.5``) tambem rejeita."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "",
             ("::ffff:10.0.0.5", port, 0, 0)),
        ]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(WebhookUrlError):
        validate_webhook_url("https://example.com/hook")


def test_dns_unresolvable_blocked(monkeypatch):
    """Hostname que nao resolve e tratado como bloqueado (host inalcancavel)."""
    def fake_getaddrinfo(*args, **kwargs):
        raise socket.gaierror("nodename nor servname provided")
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(WebhookUrlError):
        validate_webhook_url("https://unresolvable.example/hook")


# -----------------------------------------------------------------------
# Casos legitimos passam
# -----------------------------------------------------------------------


def test_https_external_passes(monkeypatch):
    """Hostname publico que resolve pra IP publico → permitido.

    8.8.8.8 (Google DNS) e nitidamente publico — passa todas as flags
    ``is_*`` do ipaddress. Nao usar 203.0.113.x: e TEST-NET-3 e cai em
    ``is_reserved`` por design.
    """
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    result = validate_webhook_url("https://hooks.slack.com/services/T/B/X")
    assert str(result).startswith("https://hooks.slack.com/")


def test_ipv6_public_passes(monkeypatch):
    """IPv6 publico (2001:db8::/32 NAO conta — e doc range, mas reservado;
    use 2606:4700::/32 que e da Cloudflare publica)."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "",
             ("2606:4700::1111", port, 0, 0)),
        ]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    result = validate_webhook_url("https://example.com/hook")
    assert str(result) == "https://example.com/hook"


# -----------------------------------------------------------------------
# Flag de bypass para dev local
# -----------------------------------------------------------------------


def test_allow_insecure_hosts_flag_bypasses_all(monkeypatch):
    """``WEBHOOK_ALLOW_INSECURE_HOSTS=true`` deixa qualquer URL passar."""
    monkeypatch.setenv("WEBHOOK_ALLOW_INSECURE_HOSTS", "true")
    # Nao chama getaddrinfo, nao importa.
    result = validate_webhook_url("http://localhost:3000/hook")
    assert "localhost" in str(result)


def test_allow_insecure_hosts_flag_off_by_default(monkeypatch):
    """Sem env var, ``http://localhost`` continua bloqueado."""
    monkeypatch.delenv("WEBHOOK_ALLOW_INSECURE_HOSTS", raising=False)
    with pytest.raises(WebhookUrlError):
        validate_webhook_url("http://localhost/hook")


@pytest.mark.parametrize("flag_value", ["false", "0", "no", "off", ""])
def test_allow_insecure_hosts_falsy_values_keep_validation(monkeypatch, flag_value):
    """Valores ``"false"``, ``"0"``, ``""``, etc nao acionam o bypass."""
    monkeypatch.setenv("WEBHOOK_ALLOW_INSECURE_HOSTS", flag_value)
    with pytest.raises(WebhookUrlError):
        validate_webhook_url("https://127.0.0.1/hook")


# -----------------------------------------------------------------------
# Mensagens de erro opacas — nao vazam IP/hostname
# -----------------------------------------------------------------------


def test_error_message_does_not_leak_internal_ip():
    """Erro pro atacante NAO contem o IP interno literal."""
    with pytest.raises(WebhookUrlError) as exc_info:
        validate_webhook_url("https://10.0.0.5/hook")
    msg = str(exc_info.value)
    assert "10.0.0.5" not in msg
    assert "10.0" not in msg
    # E mantem mensagem padrao opaca.
    assert "URL nao permitida" in msg


def test_error_message_does_not_leak_metadata_host():
    """Mensagem nao expoe que tentaram metadata."""
    with pytest.raises(WebhookUrlError) as exc_info:
        validate_webhook_url("https://metadata.google.internal/")
    msg = str(exc_info.value)
    assert "metadata" not in msg.lower()
    assert "URL nao permitida" in msg


def test_schema_error_message_does_not_leak_resolved_ip(monkeypatch):
    """Quando hostname publico resolve pra IP interno, a mensagem NAO
    revela o IP resolvido. Pydantic ECHOES o input do usuario na
    ``input_value`` do ValidationError — isso e o input proprio dele,
    nao um leak de internals; o que importa e nao expor o resultado da
    resolucao DNS (que ele nao sabe)."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.42.42.42", port))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    try:
        WebhookSubscriptionCreate(**_schema_kwargs("https://looks-public.example/hook"))
    except ValidationError as exc:
        flat = str(exc)
        # IP resolvido nao pode aparecer em lugar nenhum.
        assert "10.42.42.42" not in flat
        assert "10.42" not in flat
        # Mensagem opaca padrao deve estar la.
        assert "URL nao permitida" in flat
    else:
        pytest.fail("ValidationError esperado mas nao levantado")
