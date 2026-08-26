"""Tests for scripts/check_migrations.py (L1 迁移自动化).

Covers the acceptance criteria without touching a real database:
- single head -> OK (exit 0) against the real chain
- dual heads  -> FAIL loud (exit 1) against a synthetic two-head chain
- unapplied revisions -> FAIL loud (exit 1, DB revision monkeypatched)
- missing DATABASE_URL / unreadable chain -> config error (exit 2)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.check_migrations import (
    EXIT_CHECK_FAILED,
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    UnknownRevisionError,
    build_script_directory,
    collect_unapplied,
    main,
)


def test_single_head_real_chain_reports_ok(monkeypatch):
    """The committed chain must stay single-head; check exits 0 when the DB
    sits exactly at that head."""
    monkeypatch.setattr(
        "scripts.check_migrations.load_database_url", lambda root: "postgresql+asyncpg://stub"
    )
    script = build_script_directory()
    head = script.get_heads()[0]

    async def fake_fetch(url: str):
        return head

    monkeypatch.setattr(
        "scripts.check_migrations.fetch_current_revision", fake_fetch
    )
    assert main() == EXIT_OK


def test_dual_head_fails_loud(tmp_path, monkeypatch):
    """A synthetic chain with two independent heads must exit non-zero."""
    alembic_dir = tmp_path / "alembic" / "versions"
    alembic_dir.mkdir(parents=True)
    (alembic_dir / "rev_a.py").write_text(
        'revision = "rev_a"\ndown_revision = None\n', encoding="utf-8"
    )
    (alembic_dir / "rev_b.py").write_text(
        'revision = "rev_b"\ndown_revision = None\n', encoding="utf-8"
    )

    monkeypatch.setattr(
        "scripts.check_migrations.load_database_url", lambda root: "postgresql+asyncpg://stub"
    )
    exit_code = main(tmp_path)
    assert exit_code == EXIT_CHECK_FAILED
    # The DB is never reached on a multi-head failure.
    heads = build_script_directory(tmp_path).get_heads()
    assert sorted(heads) == ["rev_a", "rev_b"]


def test_unapplied_revisions_fail_loud(monkeypatch, capsys):
    """DB behind head (here: empty alembic_version) -> exit non-zero with a
    report of every unapplied revision."""
    monkeypatch.setattr(
        "scripts.check_migrations.load_database_url", lambda root: "postgresql+asyncpg://stub"
    )

    async def fake_fetch(url: str):
        return None  # DB behind head (nothing applied)

    monkeypatch.setattr(
        "scripts.check_migrations.fetch_current_revision", fake_fetch
    )
    exit_code = main()
    assert exit_code == EXIT_CHECK_FAILED
    err = capsys.readouterr().err
    assert "unapplied" in err
    assert "c0d1e2f3a4b50" in err  # current known head is listed as unapplied


def test_missing_database_url_is_config_error(monkeypatch):
    monkeypatch.setattr("scripts.check_migrations.load_database_url", lambda root: None)
    assert main() == EXIT_CONFIG_ERROR


def test_unreadable_chain_is_config_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.check_migrations.load_database_url", lambda root: "postgresql+asyncpg://stub"
    )
    # tmp_path/alembic does not exist -> ScriptDirectory raises.
    assert main(tmp_path) == EXIT_CONFIG_ERROR


def test_unknown_db_revision_is_config_error(monkeypatch, capsys):
    """DB stamped with a revision absent from the local chain -> clean exit 2
    with an explanatory message (no uncaught CommandError crash)."""
    monkeypatch.setattr(
        "scripts.check_migrations.load_database_url", lambda root: "postgresql+asyncpg://stub"
    )

    async def fake_fetch(url: str):
        return "deadbeefcafe"  # not in the real chain

    monkeypatch.setattr(
        "scripts.check_migrations.fetch_current_revision", fake_fetch
    )
    exit_code = main()
    assert exit_code == EXIT_CONFIG_ERROR
    err = capsys.readouterr().err
    assert "deadbeefcafe" in err
    assert "not present in the local alembic/versions chain" in err


def test_collect_unapplied_raises_on_unknown_revision():
    script = build_script_directory()
    with pytest.raises(UnknownRevisionError):
        collect_unapplied(script, "deadbeefcafe")


def test_collect_unapplied_walks_merge_chain():
    """From an older single revision, everything after it (across both merge
    points of the real chain) counts as unapplied."""
    script = build_script_directory()
    unapplied = collect_unapplied(script, "d292f6abee87")
    assert "c0d1e2f3a4b50" in unapplied
    assert "d292f6abee87" not in unapplied
    assert len(unapplied) == len(list(script.walk_revisions())) - 1


def test_collect_unapplied_empty_db_lists_everything():
    script = build_script_directory()
    unapplied = collect_unapplied(script, None)
    all_revisions = {rev.revision for rev in script.walk_revisions()}
    assert set(unapplied) == all_revisions
