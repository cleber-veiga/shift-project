"""Testes do sanitizador de logs (Prompt 6.2).

Garantem que segredos nao escapam para JSON estruturado mesmo quando o
caller esquece — porque o processor roda em todo log do structlog.
"""

from __future__ import annotations

import pytest

from app.core.observability.log_sanitizer import (
    REDACTED,
    sanitize_event_dict,
    sanitize_processor,
    add_secret_keys,
    SECRET_KEY_NAMES,
)


class TestKeyMatching:
    def test_redacts_password_field(self):
        out = sanitize_event_dict({"event": "x", "password": "hunter2"})
        assert out["password"] == REDACTED
        assert out["event"] == "x"

    def test_redacts_case_insensitive(self):
        out = sanitize_event_dict({"PASSWORD": "x", "ApiKey": "y", "TOKEN": "z"})
        assert out["PASSWORD"] == REDACTED
        assert out["ApiKey"] == REDACTED
        assert out["TOKEN"] == REDACTED

    def test_redacts_substring_match(self):
        out = sanitize_event_dict({
            "openai_api_key": "sk-xxx",
            "user_password_hash": "abc",
            "client_secret": "shh",
        })
        assert out["openai_api_key"] == REDACTED
        assert out["user_password_hash"] == REDACTED
        assert out["client_secret"] == REDACTED

    def test_safe_overrides_not_redacted(self):
        # ``token_count`` contem "token" mas e seguro.
        out = sanitize_event_dict({"token_count": 42, "tokens_used": 1024})
        assert out["token_count"] == 42
        assert out["tokens_used"] == 1024

    def test_recurses_into_nested_dicts(self):
        out = sanitize_event_dict({
            "config": {"password": "abc", "host": "db.example.com"},
        })
        assert out["config"]["password"] == REDACTED
        assert out["config"]["host"] == "db.example.com"

    def test_recurses_into_lists(self):
        out = sanitize_event_dict({
            "creds": [{"password": "a"}, {"password": "b"}],
        })
        # ``creds`` em si nao bate; entra no list e cada dict tem password.
        assert out["creds"][0]["password"] == REDACTED
        assert out["creds"][1]["password"] == REDACTED


class TestValueMatching:
    def test_redacts_url_with_credentials(self):
        out = sanitize_event_dict({
            "url": "postgres://shift:hunter2@db.example.com:5432/shift",
        })
        assert "hunter2" not in out["url"]
        assert "db.example.com" in out["url"]  # host preservado
        assert REDACTED in out["url"]

    def test_redacts_bearer_token(self):
        out = sanitize_event_dict({
            "header": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
        })
        assert out["header"] == REDACTED

    def test_redacts_anthropic_key(self):
        out = sanitize_event_dict({
            "msg": "starting with key sk-ant-api03-XXXXXXXXXXXXXXXXXXXX",
        })
        assert out["msg"] == REDACTED

    def test_redacts_openai_key(self):
        out = sanitize_event_dict({
            "msg": "key sk-proj-abcdefghijklmnopqrstuvwx",
        })
        assert out["msg"] == REDACTED

    def test_redacts_jwt(self):
        out = sanitize_event_dict({
            "msg": "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        })
        assert out["msg"] == REDACTED

    def test_short_strings_pass_through(self):
        # Strings curtas dificilmente sao tokens reais; evita falsos positivos.
        out = sanitize_event_dict({"msg": "ok"})
        assert out["msg"] == "ok"

    def test_uuid_not_redacted(self):
        # UUID v4 tem 36 chars — nao bate nenhum padrao.
        out = sanitize_event_dict({
            "execution_id": "550e8400-e29b-41d4-a716-446655440000",
        })
        assert out["execution_id"] == "550e8400-e29b-41d4-a716-446655440000"


class TestProcessor:
    def test_processor_signature(self):
        # structlog chama com (logger, method_name, event_dict).
        result = sanitize_processor(None, "info", {"password": "x", "msg": "y"})
        assert result["password"] == REDACTED
        assert result["msg"] == "y"

    def test_does_not_mutate_input(self):
        original = {"password": "hunter2", "user": "alice"}
        snapshot = dict(original)
        sanitize_event_dict(original)
        assert original == snapshot  # input intacto


class TestExtensibility:
    def test_add_secret_keys_extends_match(self):
        custom = "shift_internal_token"
        try:
            assert custom not in SECRET_KEY_NAMES
            add_secret_keys([custom])
            out = sanitize_event_dict({"shift_internal_token": "abc"})
            assert out["shift_internal_token"] == REDACTED
        finally:
            # Limpa para nao vazar entre testes.
            from app.core.observability import log_sanitizer as _ls
            _ls.SECRET_KEY_NAMES = tuple(
                k for k in _ls.SECRET_KEY_NAMES if k != custom
            )


class TestDepthGuard:
    def test_does_not_recurse_forever(self):
        # Estrutura profunda nao deve estourar.
        deep: dict = {"k": {}}
        cur = deep["k"]
        for _ in range(20):
            cur["n"] = {}
            cur = cur["n"]
        cur["password"] = "leaked"
        # Apenas verifica que nao explode — em depth > 6, nao redata,
        # mas tambem nao quebra.
        sanitize_event_dict(deep)


@pytest.mark.parametrize(
    "key",
    ["DATABASE_URL", "fernet_key", "ENCRYPTION_KEY", "Authorization"],
)
def test_known_keys_always_redacted(key):
    out = sanitize_event_dict({key: "any-non-trivial-value"})
    assert out[key] == REDACTED
