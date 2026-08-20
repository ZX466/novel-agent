"""Tests for update_document metadata_json merge semantics (R7-2 P0 fix).

update_document now treats metadata_json as a PATCH: incoming keys are merged
into the service's current value instead of replacing it wholesale. This keeps
concurrent writers (an in-flight editor save racing a Creative Kit outline
apply) from clobbering keys like `outline` they didn't touch.
"""
from __future__ import annotations

import pytest

from app.models.document import Document
from app.schemas.document import DocumentUpdate
from app.services.document import update_document


def _doc(metadata=None) -> Document:
    return Document(
        id=1,
        title="T",
        content_text="",
        word_count=0,
        metadata_json=metadata or {},
        version=0,
    )


@pytest.mark.asyncio
async def test_metadata_json_merges_preserving_unrelated_keys(mock_session) -> None:
    doc = _doc({"outline": "v1", "genre": "x"})
    mock_session.set_scalar_results([doc])
    await update_document(mock_session, 1, DocumentUpdate(metadata_json={"theme": "y"}))
    assert doc.metadata_json == {"outline": "v1", "genre": "x", "theme": "y"}


@pytest.mark.asyncio
async def test_metadata_json_payload_key_wins_on_conflict(mock_session) -> None:
    doc = _doc({"outline": "old", "genre": "x"})
    mock_session.set_scalar_results([doc])
    await update_document(mock_session, 1, DocumentUpdate(metadata_json={"outline": "new"}))
    assert doc.metadata_json == {"outline": "new", "genre": "x"}


@pytest.mark.asyncio
async def test_metadata_json_absent_patch_does_not_touch_it(mock_session) -> None:
    doc = _doc({"outline": "keep"})
    mock_session.set_scalar_results([doc])
    await update_document(mock_session, 1, DocumentUpdate(title="仅改标题"))
    assert doc.metadata_json == {"outline": "keep"}