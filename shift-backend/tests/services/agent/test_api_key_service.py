"""
Testes unitarios do AgentApiKeyService.

Abordagem: mocks de AsyncSession + authorization_service. Nao requer
banco real. Cobre geracao/validacao de plaintext, Argon2, tools whitelist,
roles, revoked/expired, last_used bookkeeping.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.security import hash_password
from app.services.agent.api_key_service import (
    AgentApiKeyPermissionError,
    AgentApiKeyService,
    AgentApiKeyValidationError,
    _extract_prefix,
    _generate_plaintext_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id=None):
    user = MagicMock()
    user.id = user_id or uuid4()
    return user


def _make_execute_result(scalars: list | None = None, scalar_one=None):
    """Monta objeto compativel com o retorno de AsyncSession.execute()."""
    result = MagicMock()
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=scalars or [])
    result.scalars = MagicMock(return_value=scalars_result)
    if scalar_one is not None:
        result.scalar_one_or_none = MagicMock(return_value=scalar_one)
    return result


@pytest.fixture
def service() -> AgentApiKeyService:
    return AgentApiKeyService()


@pytest.fixture
def db():
    sess = AsyncMock()
    sess.execute = AsyncMock()
    sess.add = MagicMock()
    sess.flush = AsyncMock()
    sess.refresh = AsyncMock()
    sess.delete = AsyncMock()
    return sess


# ---------------------------------------------------------------------------
# Geradores e helpers puros
# ---------------------------------------------------------------------------


def test_generate_plaintext_key_has_correct_prefix_and_entropy():
    key = _generate_plaintext_key()
    assert key.startswith("sk_shift_")
    # sk_shift_ (9) + ~48 chars url-safe (min 40)
    assert len(key) >= 40


def test_extract_prefix_length():
    key = "sk_shift_AbCdEFghIj"
    prefix = _extract_prefix(key)
    assert prefix == "sk_shift_AbCd"
    assert len(prefix) == 13


def test_generated_keys_are_unique():
    keys = {_generate_plaintext_key() for _ in range(50)}
    assert len(keys) == 50


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


async def test_create_returns_plaintext_once(service: AgentApiKeyService, db):
    creator = _make_user()
    workspace_id = uuid4()

    with patch(
        "app.services.agent.api_key_service.authorization_service.has_permission",
        AsyncMock(return_value=True),
    ):
        entity, plaintext = await service.create(
            db,
            creator=creator,
            workspace_id=workspace_id,
            project_id=None,
            name="teste",
            max_workspace_role="CONSULTANT",
            max_project_role=None,
            allowed_tools=["list_workflows"],
            require_human_approval=True,
            expires_at=None,
        )

    assert plaintext.startswith("sk_shift_")
    assert entity.prefix == plaintext[:13]
    # Hash deve verificar contra o plaintext
    from app.core.security import verify_password

    assert verify_password(plaintext, entity.key_hash) is True
    db.add.assert_called_once()


async def test_create_rejects_role_above_creator(service: AgentApiKeyService, db):
    creator = _make_user()

    with patch(
        "app.services.agent.api_key_service.authorization_service.has_permission",
        AsyncMock(return_value=False),
    ):
        with pytest.raises(AgentApiKeyPermissionError):
            await service.create(
                db,
                creator=creator,
                workspace_id=uuid4(),
                project_id=None,
                name="teste",
                max_workspace_role="MANAGER",
                max_project_role=None,
                allowed_tools=["list_workflows"],
                require_human_approval=True,
                expires_at=None,
            )


async def test_create_rejects_unknown_tools(service: AgentApiKeyService, db):
    creator = _make_user()

    with patch(
        "app.services.agent.api_key_service.authorization_service.has_permission",
        AsyncMock(return_value=True),
    ):
        with pytest.raises(AgentApiKeyValidationError):
            await service.create(
                db,
                creator=creator,
                workspace_id=uuid4(),
                project_id=None,
                name="teste",
                max_workspace_role="CONSULTANT",
                max_project_role=None,
                allowed_tools=["tool_inexistente"],
                require_human_approval=True,
                expires_at=None,
            )


async def test_create_accepts_wildcard_tools(service: AgentApiKeyService, db):
    creator = _make_user()

    with patch(
        "app.services.agent.api_key_service.authorization_service.has_permission",
        AsyncMock(return_value=True),
    ):
        entity, _ = await service.create(
            db,
            creator=creator,
            workspace_id=uuid4(),
            project_id=None,
            name="todas",
            max_workspace_role="MANAGER",
            max_project_role=None,
            allowed_tools=["*"],
            require_human_approval=True,
            expires_at=None,
        )
    assert entity.allowed_tools == ["*"]


async def test_create_rejects_invalid_max_workspace_role(
    service: AgentApiKeyService, db
):
    with pytest.raises(AgentApiKeyValidationError):
        await service.create(
            db,
            creator=_make_user(),
            workspace_id=uuid4(),
            project_id=None,
            name="teste",
            max_workspace_role="SUPERADMIN",
            max_project_role=None,
            allowed_tools=["list_workflows"],
            require_human_approval=True,
            expires_at=None,
        )


async def test_create_rejects_project_role_without_project_id(
    service: AgentApiKeyService, db
):
    with patch(
        "app.services.agent.api_key_service.authorization_service.has_permission",
        AsyncMock(return_value=True),
    ):
        with pytest.raises(AgentApiKeyValidationError):
            await service.create(
                db,
                creator=_make_user(),
                workspace_id=uuid4(),
                project_id=None,
                name="teste",
                max_workspace_role="CONSULTANT",
                max_project_role="EDITOR",
                allowed_tools=["list_workflows"],
                require_human_approval=True,
                expires_at=None,
            )


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


def _make_candidate(
    *,
    plaintext: str,
    revoked_at=None,
    expires_at=None,
    usage_count: int = 0,
):
    """Cria um SimpleNamespace que mimica uma instancia de AgentApiKey."""
    return SimpleNamespace(
        id=uuid4(),
        prefix=plaintext[:13],
        key_hash=hash_password(plaintext),
        workspace_id=uuid4(),
        project_id=None,
        revoked_at=revoked_at,
        expires_at=expires_at,
        last_used_at=None,
        usage_count=usage_count,
    )


async def test_validate_rejects_malformed_key(service: AgentApiKeyService, db):
    assert await service.validate(db, plaintext_key="") is None
    assert await service.validate(db, plaintext_key="not-a-key") is None
    assert await service.validate(db, plaintext_key="sk_shift_") is None


async def test_validate_rejects_wrong_key(service: AgentApiKeyService, db):
    real_plaintext = _generate_plaintext_key()
    candidate = _make_candidate(plaintext=real_plaintext)
    db.execute.return_value = _make_execute_result(scalars=[candidate])

    wrong = _generate_plaintext_key()  # mesmo formato, bytes diferentes
    # Mesma estrutura: mesmo prefixo seria necessario; forcamos mesmo prefixo
    # criando um plaintext com o mesmo prefixo mas hash diferente.
    wrong_same_prefix = candidate.prefix + "ZZZZ_diff_suffix_not_matching_hash_AAA"
    result = await service.validate(db, plaintext_key=wrong_same_prefix)
    assert result is None


async def test_validate_succeeds_and_updates_last_used(
    service: AgentApiKeyService, db
):
    plaintext = _generate_plaintext_key()
    candidate = _make_candidate(plaintext=plaintext)
    db.execute.return_value = _make_execute_result(scalars=[candidate])

    result = await service.validate(db, plaintext_key=plaintext)

    assert result is candidate
    assert result.last_used_at is not None
    assert result.usage_count == 1
    db.flush.assert_awaited()


async def test_validate_rejects_revoked(service: AgentApiKeyService, db):
    plaintext = _generate_plaintext_key()
    candidate = _make_candidate(
        plaintext=plaintext,
        revoked_at=datetime.now(timezone.utc),
    )
    db.execute.return_value = _make_execute_result(scalars=[candidate])

    result = await service.validate(db, plaintext_key=plaintext)
    assert result is None


async def test_validate_rejects_expired(service: AgentApiKeyService, db):
    plaintext = _generate_plaintext_key()
    candidate = _make_candidate(
        plaintext=plaintext,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db.execute.return_value = _make_execute_result(scalars=[candidate])

    result = await service.validate(db, plaintext_key=plaintext)
    assert result is None


async def test_validate_returns_none_when_no_candidates(
    service: AgentApiKeyService, db
):
    db.execute.return_value = _make_execute_result(scalars=[])
    plaintext = _generate_plaintext_key()
    result = await service.validate(db, plaintext_key=plaintext)
    assert result is None


async def test_validate_prefix_collision_picks_matching_hash(
    service: AgentApiKeyService, db
):
    """Duas chaves com mesmo prefixo — apenas a de hash correspondente valida."""
    plaintext_a = _generate_plaintext_key()
    # Forca o mesmo prefixo para plaintext_b
    plaintext_b = plaintext_a[:13] + "XYZdifferent_suffix_for_collision_check_here"

    cand_a = _make_candidate(plaintext=plaintext_a)
    cand_b = _make_candidate(plaintext=plaintext_b)
    cand_a.prefix = plaintext_a[:13]
    cand_b.prefix = plaintext_a[:13]

    db.execute.return_value = _make_execute_result(scalars=[cand_b, cand_a])

    result = await service.validate(db, plaintext_key=plaintext_a)
    assert result is cand_a


# ---------------------------------------------------------------------------
# revoke() / delete()
# ---------------------------------------------------------------------------


async def test_revoke_sets_revoked_at(service: AgentApiKeyService, db):
    key = SimpleNamespace(revoked_at=None)
    await service.revoke(db, key=key)
    assert key.revoked_at is not None
    db.flush.assert_awaited()


async def test_revoke_is_idempotent(service: AgentApiKeyService, db):
    original = datetime.now(timezone.utc) - timedelta(hours=1)
    key = SimpleNamespace(revoked_at=original)
    await service.revoke(db, key=key)
    assert key.revoked_at == original


async def test_delete_calls_db_delete(service: AgentApiKeyService, db):
    key = SimpleNamespace()
    await service.delete(db, key=key)
    db.delete.assert_awaited_once_with(key)
    db.flush.assert_awaited()


# ---------------------------------------------------------------------------
# list()
# ---------------------------------------------------------------------------


async def test_list_builds_result(service: AgentApiKeyService, db):
    key_a = SimpleNamespace(id=uuid4())
    key_b = SimpleNamespace(id=uuid4())
    count_result = MagicMock()
    count_result.scalar_one = MagicMock(return_value=2)
    rows_result = _make_execute_result(scalars=[key_a, key_b])
    db.execute.side_effect = [count_result, rows_result]

    rows, total = await service.list(db, workspace_id=uuid4())
    assert rows == [key_a, key_b]
    assert total == 2
