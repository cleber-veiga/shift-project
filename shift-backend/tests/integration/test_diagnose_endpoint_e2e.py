"""
Teste E2E HTTP do endpoint /api/v1/connections/diagnose contra os 3 cenarios.

Bate na app FastAPI real via httpx, com get_current_user mockado, e valida
o JSON estruturado retornado para cada cenario.

Skip se Docker indisponivel (fixtures fb*_server cuidam).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.dependencies import get_current_user
from app.api.v1.connections import router as connections_router
from app.core.rate_limit import limiter


pytestmark = pytest.mark.firebird


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(connections_router, prefix="/api/v1")

    async def _fake_user() -> Any:
        class _U:
            id = uuid.uuid4()
            email = "test@shift.app"
        return _U()

    app.dependency_overrides[get_current_user] = _fake_user
    return app


@pytest_asyncio.fixture
async def client():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_limiter():
    try:
        limiter.reset()
    except Exception:  # noqa: BLE001
        pass
    yield


# ---------------------------------------------------------------------------
# Cenario A — bundled (sucesso)
# ---------------------------------------------------------------------------


async def test_diagnose_endpoint_scenario_a_success(
    client: AsyncClient, fb30_server, fb30_database
) -> None:
    payload = {
        "type": "firebird",
        "host": fb30_server["host"],
        "port": fb30_server["port"],
        "database": fb30_database["container_path"],
        "username": "SYSDBA",
        "password": "masterkey",
        "extra_params": {"firebird_version": "3+"},
    }
    resp = await client.post("/api/v1/connections/diagnose", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_ok"] is True, body
    assert body["first_failure_stage"] is None
    assert len(body["steps"]) == 4
    assert all(s["ok"] for s in body["steps"])


# ---------------------------------------------------------------------------
# Cenario B — Firebird remoto, path nao existe (path_not_found)
# ---------------------------------------------------------------------------


async def test_diagnose_endpoint_scenario_b_path_not_found(
    client: AsyncClient, fb30_server
) -> None:
    payload = {
        "type": "firebird",
        "host": fb30_server["host"],
        "port": fb30_server["port"],
        "database": "/firebird/data/inexistente_shift_test.fdb",  # path Linux inexistente, dispara I/O error consistente
        "username": "SYSDBA",
        "password": "masterkey",
        "extra_params": {"firebird_version": "3+"},
    }
    resp = await client.post("/api/v1/connections/diagnose", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_ok"] is False
    assert body["first_failure_stage"] == "auth_query"
    auth = body["steps"][3]
    assert auth["error_class"] == "path_not_found", (
        f"esperado path_not_found, veio {auth['error_class']!r}"
    )


# ---------------------------------------------------------------------------
# Cenario C — ODS incompativel (FB 3.0 atachando .fdb ODS 11)
# ---------------------------------------------------------------------------


async def test_diagnose_endpoint_scenario_c_wrong_ods(
    client: AsyncClient, fb30_server, fb25_db_in_fb30_mount
) -> None:
    payload = {
        "type": "firebird",
        "host": fb30_server["host"],
        "port": fb30_server["port"],
        "database": fb25_db_in_fb30_mount["container_path"],
        "username": "SYSDBA",
        "password": "masterkey",
        "extra_params": {"firebird_version": "3+"},
    }
    resp = await client.post("/api/v1/connections/diagnose", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_ok"] is False
    assert body["first_failure_stage"] == "auth_query"
    auth = body["steps"][3]
    assert auth["error_class"] == "wrong_ods", (
        f"esperado wrong_ods, veio {auth['error_class']!r}"
    )
