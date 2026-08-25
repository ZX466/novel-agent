"""Tests for scripts/backfill_owner_key_hash.py (R7-3 回填幂等性).

The backfill UPDATE carries `WHERE owner_key_hash = ''` — it can never touch
rows that already have a hash, so re-running is a no-op after the first pass.
These tests assert that contract via a fake async session, plus verify the
script's sha256 fingerprint matches the runtime _deps implementation.
"""
from __future__ import annotations

import asyncio
import pytest

from scripts import backfill_owner_key_hash as bf
from app.api import _deps


class _Stmt:
    def __init__(self, text: str):
        self.text = text


class _Row:
    def __init__(self, n: int):
        self.n = n

    def scalar(self):
        return self.n


class _Result:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _FakeSession:
    """Captures executed statements and returns canned results."""

    def __init__(self, exec_results=None, scalar_rows=None):
        self.captured: list[str] = []
        self.committed = 0
        self._exec_results = list(exec_results or [])
        self._scalar_rows = list(scalar_rows or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def execute(self, stmt, params=None):
        self.captured.append(stmt.text if isinstance(stmt, _Stmt) else str(stmt))
        if "SELECT" in (stmt.text if isinstance(stmt, _Stmt) else str(stmt)):
            if self._scalar_rows:
                n = self._scalar_rows.pop(0)
                return _Row(n)
            return _Row(0)
        if self._exec_results:
            return self._exec_results.pop(0)
        return _Result(1)

    async def commit(self):
        self.committed += 1


class _FakeFactory:
    """Mimics `AsyncSessionLocal()` returning a session that itself supports
    `async with ... as session` (as a real AsyncSession does)."""

    def __init__(self, session):
        self._s = session

    def __call__(self):
        return self._s


def test_owner_key_hash_matches_deps_impl():
    """Script's fingerprint must stay identical to the API dependency."""
    key = "test-key-abc"
    assert bf.owner_key_hash(key) == _deps.owner_key_hash(key)


@pytest.mark.asyncio
async def test_update_statement_only_targets_empty_hash_rows():
    """The backfill UPDATE must gate on owner_key_hash = '' to stay idempotent."""
    session = _FakeSession()
    factory = _FakeFactory(session)
    total = await bf._run(["key-a"], dry_run=False, session_factory=factory)

    # It should execute one UPDATE restricted to unassigned rows.
    updates = [s for s in session.captured if "UPDATE" in s]
    assert len(updates) == 1
    assert "owner_key_hash = ''" in updates[0]
    assert session.committed == 1
    assert total == 1


@pytest.mark.asyncio
async def test_second_run_claims_nothing():
    """After first pass, an empty-hash UPDATE rows count is 0 -> idempotent.

    Simulates a second invocation by returning rowcount 0 (no remaining empty
    rows). The script must not invent rows to claim.
    """
    session = _FakeSession(exec_results=[_Result(0)])
    factory = _FakeFactory(session)
    total = await bf._run(["key-a"], dry_run=False, session_factory=factory)
    assert total == 0
    assert session.committed == 1
    # Update still targets only empty rows (never overwrite assigned ones).
    assert "owner_key_hash = ''" in session.captured[0]


@pytest.mark.asyncio
async def test_dry_run_does_not_write():
    """--dry-run must only SELECT the pending count, never update or commit."""
    session = _FakeSession(scalar_rows=[3])
    factory = _FakeFactory(session)
    total = await bf._run(["key-a"], dry_run=True, session_factory=factory)
    assert session.committed == 0
    assert all("UPDATE" not in s for s in session.captured)
    assert total == 3
def test_main_exit_code_semantics(monkeypatch):
    """main() exit code contract: 0 = success (rows claimed or none pending),
    2 = missing API key config. arg parsing must not leak pytest's argv."""
    import sys
    import app.config as cfg

    # Path A: no API key configured -> exit code 2 (config error).
    old_keys = cfg.settings.api_keys
    old_argv = sys.argv
    try:
        cfg.settings.api_keys = []
        sys.argv = ["backfill_owner_key_hash", "--dry-run"]
        # main() returns the exit code directly (SystemExit is raised by the
        # `if __name__ == "__main__"` wrapper).
        assert bf.main() == 2
    finally:
        cfg.settings.api_keys = old_keys
        sys.argv = old_argv

    # Path B: key configured, dry-run reports pending rows -> success exit 0.
    old_keys = cfg.settings.api_keys
    try:
        cfg.settings.api_keys = ["k"]
        sys.argv = ["backfill_owner_key_hash", "--dry-run"]
        # Patch the underlying _run to avoid touching DB.
        async def _fake_run(keys, dry_run, session_factory=object()):
            return 0
        monkeypatch.setattr(bf, "_run", _fake_run)
        assert bf.main() == 0
    finally:
        cfg.settings.api_keys = old_keys
        sys.argv = old_argv