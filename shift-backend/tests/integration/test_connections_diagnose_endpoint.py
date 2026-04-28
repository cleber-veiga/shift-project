"""
Testes de integracao do endpoint stateless POST /connections/diagnose.

Cobre:
  - sucesso com Firebird 3.0 real (skip se Docker indisponivel)
  - senha errada -> 200 com first_failure_stage='auth_query'
  - sem auth -> 401
  - rate limit -> 429 na 11a chamada em 1 min
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from app.api.dependencies import get_current_user
from app.api.v1.connections import router as connections_router
from app.core.rate_limit import limiter


def _build_app(authed: bool) -> FastAPI:
    """Monta um FastAPI minimo com o router de connections + slowapi.

    Quando authed=False, NAO sobrescreve get_current_user -> dependencia
    real falha com 401 (que e o que queremos verificar no teste de auth).
    """
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(connections_router, prefix="/api/v1")

    if authed:
        async def _fake_user() -> Any:
            class _U:
                id = uuid.uuid4()
                email = "test@shift.app"
            return _U()
        app.dependency_overrides[get_current_user] = _fake_user

    return app


@pytest_asyncio.fixture
async def authed_client():
    app = _build_app(authed=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def anon_client():
    app = _build_app(authed=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Reset do limiter entre testes — slowapi mantem estado em memoria
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_limiter():
    try:
        limiter.reset()
    except Exception:  # noqa: BLE001
        pass
    yield
    try:
        limiter.reset()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Casos com servidor Firebird real
# ---------------------------------------------------------------------------


@pytest.mark.firebird
async def test_diagnose_payload_firebird_success(
    authed_client: AsyncClient,
    fb30_server,
    fb30_database,
) -> None:
    payload = {
        "type": "firebird",
        "host": fb30_server["host"],
        "port": fb30_server["port"],
        "database": fb30_database["container_path"],
        "username": "SYSDBA",
        "password": "masterkey",
        "extra_params": {"firebird_version": "3+", "charset": "WIN1252"},
    }
    resp = await authed_client.post("/api/v1/connections/diagnose", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_ok"] is True, body
    assert body["first_failure_stage"] is None
    assert len(body["steps"]) == 4
    assert all(s["ok"] for s in body["steps"])


@pytest.mark.firebird
async def test_diagnose_payload_wrong_password(
    authed_client: AsyncClient,
    fb30_server,
    fb30_database,
) -> None:
    payload = {
        "type": "firebird",
        "host": fb30_server["host"],
        "port": fb30_server["port"],
        "database": fb30_database["container_path"],
        "username": "SYSDBA",
        "password": "errada-com-certeza",
        "extra_params": {"firebird_version": "3+"},
    }
    resp = await authed_client.post("/api/v1/connections/diagnose", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_ok"] is False
    assert body["first_failure_stage"] == "auth_query"
    auth_step = body["steps"][3]
    assert auth_step["error_class"] == "auth_failed"
    assert auth_step["hint"] == "Usuario ou senha invalidos."


# ---------------------------------------------------------------------------
# Casos sem Docker — auth + rate limit
# ---------------------------------------------------------------------------


async def test_diagnose_payload_unauthenticated_returns_401(
    anon_client: AsyncClient,
) -> None:
    payload = {
        "type": "firebird",
        "host": "qualquer",
        "port": 3050,
        "database": "x.fdb",
        "username": "u",
        "password": "p",
    }
    resp = await anon_client.post("/api/v1/connections/diagnose", json=payload)
    assert resp.status_code == 401, resp.text


async def test_diagnose_payload_rate_limit(authed_client: AsyncClient) -> None:
    """11 chamadas em 1 min -> a 11a deve retornar 429.

    Usa um payload com host/porta inexistentes — DNS falha rapido, nao
    depende de Docker e nao spawna threads longas.
    """
    payload = {
        "type": "firebird",
        "host": "host-nao-existe-shift-test.invalid",
        "port": 3050,
        "database": "x.fdb",
        "username": "u",
        "password": "p",
    }

    statuses: list[int] = []
    for _ in range(11):
        resp = await authed_client.post("/api/v1/connections/diagnose", json=payload)
        statuses.append(resp.status_code)

    # As 10 primeiras dentro do limite — devem ter status != 429.
    assert statuses[:10].count(429) == 0, f"limite ativou cedo demais: {statuses}"
    # A 11a (ou alguma das ultimas) deve ser 429.
    assert 429 in statuses, f"limite de 10/min nao acionou: {statuses}"


async def test_diagnose_payload_rate_limit_isolated_per_user(
    authed_client: AsyncClient,
) -> None:
    """Limite e por usuario (via JWT sub no key_func), nao por IP.

    Exaure o limite com o token A; em seguida o token B deve continuar
    aceito (mesma fonte / IP / ASGI client). Sem JWT, o key_func cai em
    fallback de IP — entao precisamos enviar tokens distintos.
    """
    import jwt as pyjwt

    def token_for(sub: str) -> str:
        return pyjwt.encode({"sub": sub}, "k", algorithm="HS256")

    headers_a = {"Authorization": f"Bearer {token_for('user-A')}"}
    headers_b = {"Authorization": f"Bearer {token_for('user-B')}"}
    payload = {
        "type": "firebird",
        "host": "host-nao-existe-shift-test.invalid",
        "port": 3050,
        "database": "x.fdb",
        "username": "u",
        "password": "p",
    }

    # Esgota o limite de user-A.
    last_a = 0
    for _ in range(11):
        resp = await authed_client.post(
            "/api/v1/connections/diagnose", json=payload, headers=headers_a,
        )
        last_a = resp.status_code
    assert last_a == 429, f"user-A deveria ter batido 429, ficou em {last_a}"

    # user-B no mesmo IP/cliente NAO deve ter sido afetado.
    resp_b = await authed_client.post(
        "/api/v1/connections/diagnose", json=payload, headers=headers_b,
    )
    assert resp_b.status_code != 429, (
        f"user-B foi limitado pelo balde do user-A — key_func nao isolou "
        f"por usuario (status {resp_b.status_code})"
    )
