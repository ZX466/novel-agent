"""Migration health check (L1 迁移自动化).

One-shot pre-flight verification for the alembic migration chain:

1. The chain has EXACTLY ONE head. Multiple heads mean a branch merge
   happened without a merge revision -> `alembic upgrade head` would be
   ambiguous and fail mid-deploy.
2. Every revision in the chain is applied to the database (the DB sits at
   head). Reports any unapplied revisions instead of failing silently later.

Fail loud: any problem exits non-zero so deploy pipelines stop before
serving traffic.

Exit codes:
    0  ok (single head, nothing unapplied)
    1  check failed (zero/multiple heads, or unapplied revisions)
    2  configuration error (DATABASE_URL missing, unreadable chain,
       database unreachable, or the DB records a revision that is not
       in the local chain)

Usage:
    cd backend && uv run python scripts/check_migrations.py
    docker compose exec backend python scripts/check_migrations.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

BACKEND_ROOT = Path(__file__).resolve().parent.parent

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_CONFIG_ERROR = 2


class UnknownRevisionError(Exception):
    """The DB records a revision missing from the local migration chain."""


def load_database_url(root: Path = BACKEND_ROOT) -> str | None:
    """Resolve DATABASE_URL from process env, falling back to <root>/.env.

    Process env wins over .env (same rule as alembic/env.py) so prod/CI
    overrides still work.
    """
    load_dotenv(root / ".env", override=False)
    return os.environ.get("DATABASE_URL")


def build_script_directory(root: Path = BACKEND_ROOT) -> ScriptDirectory:
    cfg = Config()
    cfg.set_main_option("script_location", str(root / "alembic"))
    return ScriptDirectory.from_config(cfg)


async def fetch_current_revision(
    database_url: str,
) -> str | tuple[str, ...] | None:
    """Read the revision(s) recorded in the DB's alembic_version table."""
    connectable = async_engine_from_config(
        {"sqlalchemy.url": database_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as conn:

            def _current(sync_conn):  # pragma: no cover - trivial adapter
                return MigrationContext.configure(sync_conn).get_current_revision()

            return await conn.run_sync(_current)
    finally:
        await connectable.dispose()


def _collect_ancestry(script: ScriptDirectory, revision_id: str) -> set[str]:
    """All revisions reachable from `revision_id` via down_revision links.

    Raises UnknownRevisionError when `revision_id` (i.e. a revision recorded
    in the DB's alembic_version) does not exist in the local chain — that is
    a deployment/configuration mismatch, not a failed health check.
    """
    ancestry: set[str] = set()
    stack = [revision_id]
    while stack:
        rev_id = stack.pop()
        try:
            rev = script.get_revision(rev_id)
        except CommandError as exc:
            raise UnknownRevisionError(
                f"revision {rev_id!r} is recorded in the database but not "
                "present in the local alembic/versions chain — the DB was "
                "migrated by different code. Align the deployed code with "
                "the database (or restore the missing migration file) "
                "before running migrations."
            ) from exc
        if rev is None or rev.revision in ancestry:
            continue
        ancestry.add(rev.revision)
        down = rev.down_revision
        if isinstance(down, str):
            stack.append(down)
        elif isinstance(down, (tuple, list)):
            stack.extend(item for item in down if item)
    return ancestry


def collect_unapplied(
    script: ScriptDirectory, current: str | tuple[str, ...] | None
) -> list[str]:
    """Revisions present in the chain but not reachable from `current`.

    Raises UnknownRevisionError for a DB revision missing from the local
    chain (configuration error -> exit code 2).
    """
    targets = [current] if isinstance(current, str) else list(current or [])
    applied: set[str] = set()
    for target in targets:
        applied |= _collect_ancestry(script, target)
    all_revisions = {rev.revision for rev in script.walk_revisions()}
    return sorted(all_revisions - applied)


def main(root: Path = BACKEND_ROOT) -> int:
    database_url = load_database_url(root)
    if not database_url:
        print(
            "[check-migrations] ERROR: DATABASE_URL is not set "
            "(export it or create backend/.env).",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    try:
        script = build_script_directory(root)
        heads = list(script.get_heads())
    except Exception as exc:
        print(
            f"[check-migrations] ERROR: cannot read alembic chain: {exc}",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    if len(heads) != 1:
        found = ", ".join(heads) if heads else "(none)"
        print(
            f"[check-migrations] FAIL: expected exactly 1 head, found "
            f"{len(heads)}: {found}. Merge the branches into one revision.",
            file=sys.stderr,
        )
        return EXIT_CHECK_FAILED
    head = heads[0]
    print(f"[check-migrations] single head OK: {head}")

    try:
        current = asyncio.run(fetch_current_revision(database_url))
    except Exception as exc:
        print(
            f"[check-migrations] ERROR: cannot reach database: {exc}",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    try:
        unapplied = collect_unapplied(script, current)
    except UnknownRevisionError as exc:
        print(f"[check-migrations] ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    if unapplied:
        current_desc = ", ".join(targets) if (targets := _as_tuple(current)) else "(empty)"
        print(
            f"[check-migrations] FAIL: database at [{current_desc}], "
            f"head is {head}.",
            file=sys.stderr,
        )
        print(
            f"[check-migrations] FAIL: {len(unapplied)} unapplied "
            f"revision(s): {', '.join(unapplied)}",
            file=sys.stderr,
        )
        print(
            "[check-migrations] Run `alembic upgrade head`, then re-run "
            "this check.",
            file=sys.stderr,
        )
        return EXIT_CHECK_FAILED

    print("[check-migrations] OK: single head, all revisions applied.")
    return EXIT_OK


def _as_tuple(current: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if current is None:
        return ()
    if isinstance(current, str):
        return (current,)
    return tuple(current)


if __name__ == "__main__":
    raise SystemExit(main())
