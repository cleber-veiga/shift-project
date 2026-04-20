"""Testes do job de expiracao de aprovacoes pendentes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.agent.safety.expiration_job import expire_pending_approvals


def _mock_factory(select_rows: list[tuple], update_rowcounts: list[int]):
    """Monta um async_session_factory simulado.

    select_rows = linhas retornadas pelo SELECT inicial;
    update_rowcounts = rowcounts para cada UPDATE subsequente (na ordem).
    """
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    select_result = MagicMock()
    select_result.all = MagicMock(return_value=select_rows)

    update_results: list[MagicMock] = []
    for rc in update_rowcounts:
        mock_result = MagicMock()
        mock_result.rowcount = rc
        update_results.append(mock_result)

    call_outputs = [select_result, *update_results]
    session.execute = AsyncMock(side_effect=call_outputs)

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=cm)
    return factory, session


@pytest.mark.asyncio
async def test_expire_no_pending_is_noop():
    factory, session = _mock_factory(select_rows=[], update_rowcounts=[])
    counters = await expire_pending_approvals(factory)
    assert counters == {"approvals_expired": 0, "threads_expired": 0}
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_expire_updates_approvals_and_threads():
    approval_a = uuid4()
    approval_b = uuid4()
    thread_1 = uuid4()
    select_rows = [(approval_a, thread_1), (approval_b, thread_1)]
    factory, session = _mock_factory(
        select_rows=select_rows,
        update_rowcounts=[2, 1],
    )
    counters = await expire_pending_approvals(factory)
    assert counters == {"approvals_expired": 2, "threads_expired": 1}
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_expire_is_idempotent_when_already_updated():
    approval_a = uuid4()
    thread_1 = uuid4()
    # Na segunda corrida, outro worker ja atualizou: rowcount=0 nos UPDATEs.
    factory, session = _mock_factory(
        select_rows=[(approval_a, thread_1)],
        update_rowcounts=[0, 0],
    )
    counters = await expire_pending_approvals(factory)
    assert counters == {"approvals_expired": 0, "threads_expired": 0}
    # Commit ainda e chamado (transacao foi aberta); rodar N vezes nao
    # produz efeito duplo, pois as linhas ja nao estao 'pending'.
    session.commit.assert_awaited_once()
