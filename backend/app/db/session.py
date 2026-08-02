"""Async SQLAlchemy engine + session factory + FastAPI dependency.

Important: `expire_on_commit=False` is mandatory for async sessions — otherwise
accessing attributes after commit triggers implicit IO and raises
MissingGreenlet. `pool_pre_ping=True` is mandatory for managed/hosted PG to
survive idle connections being killed server-side.
"""
from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a session, rolls back on exception.

    Service layer is responsible for calling commit() — this dependency does
    NOT auto-commit, so partial failures stay isolated.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
