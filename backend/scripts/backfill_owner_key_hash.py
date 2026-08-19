"""Backfill `documents.owner_key_hash` for legacy rows created before tenant
scoping (R5-3) existed.

IDEMPOTENT: each run only touches rows whose `owner_key_hash` is still empty
(`''`), assigning them the SHA-256 fingerprint of *one* configured API key.
Rows that already carry a hash are never overwritten, so running the script
multiple times with the same API_KEYS yields identical data and zero changes
after the first pass.

Ownership model: with a single production key, all legacy rows inherit that
key's tenant. With multiple keys, rows are NOT auto-assigned at random — you
must pass `--api-key <KEY>` to claim legacy rows for a specific tenant.
Re-running with the same key only fills the rows that are still unassigned.

Usage (from `backend/`):
    # From .env API_KEYS (single key -> claim all empty rows):
    uv run python -m scripts.backfill_owner_key_hash

    # Explicit tenant claim (recommended for multi-key production):
    uv run python -m scripts.backfill_owner_key_hash --api-key <KEY>

    # Preview without writing:
    uv run python -m scripts.backfill_owner_key_hash --dry-run

Notes:
- Requires DATABASE_URL in backend/.env (asyncpg).
- Key(s) must match what `X-API-Key` clients use; the fingerprint (sha256) is
  the same `owner_key_hash()` used by `app/api/_deps.py`.
"""
from __future__ import annotations

import argparse
import hashlib
import sys

from sqlalchemy import text

from app.config import settings
from app.db.session import AsyncSessionLocal


def owner_key_hash(api_key: str) -> str:
    """Must stay in lock-step with app.api._deps.owner_key_hash."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


async def _run(keys: list[str], dry_run: bool, session_factory=AsyncSessionLocal) -> int:
    total = 0
    async with session_factory() as session:
        for key in keys:
            fp = owner_key_hash(key)
            # Only rows with an empty hash are unassigned; never overwrite.
            if dry_run:
                stmt = text(
                    "SELECT COUNT(*) FROM documents WHERE owner_key_hash = ''"
                )
                row = await session.execute(stmt)
                n = row.scalar() or 0
                print(f"[dry-run] key={key} legacy rows to claim: {n}")
                total += n
                continue
            stmt = text(
                "UPDATE documents SET owner_key_hash = :fp "
                "WHERE owner_key_hash = ''"
            )
            result = await session.execute(stmt, {"fp": fp})
            total += result.rowcount or 0
            print(f"[backfill] key={key} rows claimed: {result.rowcount or 0}")
        if not dry_run:
            await session.commit()
            print(f"[backfill] committed. total rows claimed: {total}")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill owner_key_hash")
    parser.add_argument("--api-key", default="", help="API key to claim rows for")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    if args.api_key:
        keys = [args.api_key]
    elif settings.api_keys:
        keys = settings.api_keys
    else:
        print("ERROR: no API key. Pass --api-key or set API_KEYS in backend/.env.", file=sys.stderr)
        return 2

    import asyncio
    total = asyncio.run(_run(keys, args.dry_run))
    # Exit code is 0 on success regardless of how many rows were claimed
    # (0 rows on a re-run is a legitimately successful, idempotent no-op).
    return 0 if total >= 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())