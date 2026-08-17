"""Shared pytest fixtures.

Stubs required env vars BEFORE `app.main` is imported so Settings() doesn't
fail. LLM credentials are NOT stubbed because BYOK mode made them optional
(`default=""`). Provides both a sync `app_client` (for non-streaming tests)
and an async `async_app_client` (for SSE streaming tests).

The `mock_session` fixture is used by novel-memory service tests to avoid
needing a real PostgreSQL + pgvector instance. Tests construct ORM
instances directly and patch the AsyncSession methods that the service
under test actually calls.
"""
from __future__ import annotations

import os

# Must run before any `from app.main import app`. setdefault avoids
# overriding real env vars when the developer wants to test against a real
# backend/DB.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://stub:stub@localhost/stub")
os.environ.setdefault("REDIS_URL", "redis://localhost:16379/0")
os.environ.setdefault("API_KEYS", '["test-key"]')

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def fake_chat_rate_limit_redis(monkeypatch):
    """Keep API tests independent from the external Redis deployment."""
    class FakeRedis:
        def __init__(self) -> None:
            self.counts: dict[str, int] = {}

        async def incr(self, key: str) -> int:
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        async def expire(self, key: str, seconds: int) -> None:
            return None

    fake = FakeRedis()
    monkeypatch.setattr("app.api._deps.get_redis", lambda: fake)
    return fake


@pytest.fixture(scope="session")
def app_client() -> TestClient:
    """Session-scoped TestClient. Imported here (not at module top) so env
    stubs above are guaranteed to be set first.
    """
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture
async def async_app_client() -> AsyncClient:
    """Per-test async client for SSE streaming tests.

    Uses httpx.ASGITransport to talk to the FastAPI app in-process without a
    real network socket. Does NOT trigger the app lifespan (no Redis ping),
    which is fine because chat tests mock `stream_pipeline` and never touch
    Redis. Scope is function (not session) because streaming tests often
    monkeypatch per-test.
    """
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test-key"},
    ) as c:
        yield c


# --- Novel-memory service test fixtures ------------------------------------


class _FakeScalar:
    """Stand-in for `await session.scalar(stmt)` results.

    `session.scalar(...)` returns the first column of the first row.
    Service code uses it for COUNT(*) and for `select(Model).where(...)`
    single-instance fetches. Tests inject the desired return value.
    """

    def __init__(self, value=None):
        self.value = value

    def __await__(self):
        async def _coro():
            return self.value
        return _coro().__await__()


class _FakeResult:
    """Stand-in for `await session.execute(stmt)` results.

    Two usage patterns:
      - service code: `result.scalars().all()` → list of ORM instances
      - retrieval code: `result.all()` → list of (instance, distance) tuples

    Construct with `scalars=[...]` for service tests, `rows=[...]` for
    retrieval tests. `_rows=None` (the default) makes `all()` fall back
    to `_scalars` so the same instance works for both call shapes.
    """

    def __init__(self, scalars=None, rows=None):
        self._scalars = scalars or []
        # `None` means "not set" — distinguishes from "set to empty list".
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        if self._rows is not None:
            return self._rows
        return self._scalars


class MockAsyncSession:
    """Minimal async-session double for service-layer tests.

    Tracks `add()` calls, captures `commit()` invocations, and returns
    configurable results for `scalar()` and `execute()`. Refresh mutates
    nothing — it exists so `await session.refresh(obj)` is a no-op.

    Tests configure behavior by setting `mock_session.scalar_result` and
    `mock_session.execute_result` (or lists thereof for sequential calls).
    """

    def __init__(self):
        self.added: list = []
        self.deleted: list = []
        self.commits: int = 0
        self.refreshes: int = 0
        self.rolled_back: int = 0
        self._scalar_results: list = []
        self._execute_results: list = []
        self._scalar_idx = 0
        self._execute_idx = 0

    def set_scalar_results(self, results: list) -> None:
        self._scalar_results = list(results)
        self._scalar_idx = 0

    def set_execute_results(self, results: list) -> None:
        self._execute_results = list(results)
        self._execute_idx = 0

    async def scalar(self, stmt):
        if self._scalar_idx < len(self._scalar_results):
            r = self._scalar_results[self._scalar_idx]
            self._scalar_idx += 1
            return r
        return None

    async def execute(self, stmt):
        if self._execute_idx < len(self._execute_results):
            r = self._execute_results[self._execute_idx]
            self._execute_idx += 1
            return r
        return _FakeResult()

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        self.refreshes += 1

    async def delete(self, obj):
        self.deleted.append(obj)

    async def rollback(self):
        self.rolled_back += 1

    def add(self, obj):
        self.added.append(obj)


@pytest.fixture
def mock_session() -> MockAsyncSession:
    """A fresh MockAsyncSession for each test."""
    return MockAsyncSession()
