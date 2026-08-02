"""Tests for app.tools — ToolRegistry, ToolContext, ToolResult, built-in tools.

Covers P1-tool-1: validates the tool abstraction (registry, context,
result envelope) and the three built-in tools (search_lore,
get_character, save_chapter). All tests are pure-Python — service
functions are mocked via `unittest.mock.patch.object` so no DB / LLM
is required.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.models.chapter import Chapter
from app.models.character import Character
from app.tools import (
    GetCharacterTool,
    SaveChapterTool,
    SearchLoreTool,
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    make_default_registry,
)
from app.tools import builtins as builtins_module


# ---------------------------------------------------------------------------
# ToolContext
# ---------------------------------------------------------------------------


def test_tool_context_session_required():
    """ToolContext requires a session — calling without one is a TypeError."""
    with pytest.raises(TypeError):
        ToolContext()  # type: ignore[call-arg]


def test_tool_context_defaults_to_none():
    ctx = ToolContext(session="fake-session")  # type: ignore[arg-type]
    assert ctx.session == "fake-session"
    assert ctx.stage_config is None
    assert ctx.novel_id is None


def test_tool_context_is_frozen():
    ctx = ToolContext(session="fake")  # type: ignore[arg-type]
    with pytest.raises(Exception):
        ctx.session = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------


def test_tool_result_success_factory():
    r = ToolResult.success({"a": 1})
    assert r.ok is True
    assert r.data == {"a": 1}
    assert r.error is None


def test_tool_result_failure_factory():
    r = ToolResult.failure("oops")
    assert r.ok is False
    assert r.data == {}
    assert r.error == "oops"


def test_tool_result_direct_construction():
    r = ToolResult(ok=False, data={"partial": "x"}, error="bad")
    assert r.ok is False
    assert r.data == {"partial": "x"}
    assert r.error == "bad"


# ---------------------------------------------------------------------------
# ToolRegistry — registration / lookup
# ---------------------------------------------------------------------------


class _DummyParams(BaseModel):
    pass


class _DummyTool(Tool):
    name = "dummy"
    description = "A dummy tool for testing."
    Params = _DummyParams

    async def execute(self, params, ctx):
        return ToolResult.success({})


class _OtherTool(Tool):
    name = "other"
    description = "Another tool."
    Params = _DummyParams

    async def execute(self, params, ctx):
        return ToolResult.success({})


def test_register_adds_tool_by_name():
    reg = ToolRegistry()
    reg.register(_DummyTool())
    assert reg.has("dummy")
    assert isinstance(reg.get("dummy"), _DummyTool)


def test_register_duplicate_raises():
    reg = ToolRegistry()
    reg.register(_DummyTool())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_DummyTool())


def test_get_unknown_raises_keyerror():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("does-not-exist")


def test_has_returns_false_for_unknown():
    reg = ToolRegistry()
    assert reg.has("anything") is False


def test_list_names_returns_all_registered():
    reg = ToolRegistry()
    reg.register(_DummyTool())
    reg.register(_OtherTool())
    assert sorted(reg.list_names()) == ["dummy", "other"]


# ---------------------------------------------------------------------------
# ToolRegistry — schemas() export
# ---------------------------------------------------------------------------


def test_schemas_export_openai_format():
    """schemas() should produce OpenAI tool-calling format."""
    from pydantic import BaseModel, Field

    class _Params(BaseModel):
        query: str = Field(..., description="Search query")

    class _SearchedTool(Tool):
        name = "searched"
        description = "Search things."
        Params = _Params

        async def execute(self, params, ctx):
            return ToolResult.success({})

    reg = ToolRegistry()
    reg.register(_SearchedTool())
    schemas = reg.schemas()
    assert len(schemas) == 1
    s = schemas[0]
    assert s["type"] == "function"
    fn = s["function"]
    assert fn["name"] == "searched"
    assert fn["description"] == "Search things."
    # JSON Schema should include "query" in properties and required.
    assert "query" in fn["parameters"]["properties"]
    assert "query" in fn["parameters"]["required"]


def test_schemas_include_all_tools():
    reg = ToolRegistry()
    reg.register(_DummyTool())
    reg.register(_OtherTool())
    schemas = reg.schemas()
    names = [s["function"]["name"] for s in schemas]
    assert sorted(names) == ["dummy", "other"]


# ---------------------------------------------------------------------------
# ToolRegistry — invoke() dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_unknown_returns_failure():
    reg = ToolRegistry()
    ctx = ToolContext(session="fake")  # type: ignore[arg-type]
    result = await reg.invoke("nope", {}, ctx)
    assert result.ok is False
    assert "not registered" in (result.error or "")


@pytest.mark.asyncio
async def test_invoke_invalid_params_returns_failure():
    """Pydantic ValidationError becomes ToolResult.failure."""
    from pydantic import BaseModel, Field

    class _Params(BaseModel):
        name: str = Field(..., min_length=1)

    class _NamedTool(Tool):
        name = "named"
        description = "Needs a name."
        Params = _Params

        async def execute(self, params, ctx):
            return ToolResult.success({"echo": params.name})

    reg = ToolRegistry()
    reg.register(_NamedTool())
    ctx = ToolContext(session="fake")  # type: ignore[arg-type]
    # Missing required field "name".
    result = await reg.invoke("named", {}, ctx)
    assert result.ok is False
    assert "Invalid params" in (result.error or "")


@pytest.mark.asyncio
async def test_invoke_catches_handler_exception():
    """If a handler raises, the registry wraps it as a failure result."""
    from pydantic import BaseModel

    class _Params(BaseModel):
        pass

    class _BoomTool(Tool):
        name = "boom"
        description = "Always raises."
        Params = _Params

        async def execute(self, params, ctx):
            raise RuntimeError("kaboom")

    reg = ToolRegistry()
    reg.register(_BoomTool())
    ctx = ToolContext(session="fake")  # type: ignore[arg-type]
    result = await reg.invoke("boom", {}, ctx)
    assert result.ok is False
    assert "RuntimeError" in (result.error or "")
    assert "kaboom" in (result.error or "")


@pytest.mark.asyncio
async def test_invoke_passes_through_tool_result():
    """A handler that returns ToolResult directly is passed through."""
    from pydantic import BaseModel

    class _Params(BaseModel):
        pass

    class _OkTool(Tool):
        name = "ok"
        description = "Returns ok."
        Params = _Params

        async def execute(self, params, ctx):
            return ToolResult.success({"value": 42})

    reg = ToolRegistry()
    reg.register(_OkTool())
    ctx = ToolContext(session="fake")  # type: ignore[arg-type]
    result = await reg.invoke("ok", {}, ctx)
    assert result.ok is True
    assert result.data == {"value": 42}


# ---------------------------------------------------------------------------
# SearchLoreTool — happy path + novel_id defaulting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_lore_returns_hits(mock_session):
    fake_hits = [
        type("H", (), {
            "entity_type": "chapter", "entity_id": 1, "score": 0.9,
            "payload": {"title": "Ch1"},
            "model_dump": lambda self=None: {
                "entity_type": "chapter", "entity_id": 1, "score": 0.9,
                "payload": {"title": "Ch1"},
            },
        })(),
    ]
    with patch.object(
        builtins_module, "retrieve", AsyncMock(return_value=fake_hits)
    ) as mock_retrieve:
        tool = SearchLoreTool()
        ctx = ToolContext(session=mock_session, novel_id=1)
        result = await tool.execute(
            tool.Params(query="detective backstory"), ctx
        )
    assert result.ok is True
    assert result.data["count"] == 1
    assert result.data["hits"][0]["entity_id"] == 1
    # retrieve() was called with the right args.
    mock_retrieve.assert_awaited_once()
    call_args = mock_retrieve.call_args
    assert call_args.args[1] == "detective backstory"
    assert call_args.kwargs["k_per_collection"] == 3


@pytest.mark.asyncio
async def test_search_lore_defaults_novel_id_from_ctx(mock_session):
    """When params.novel_id is None, ctx.novel_id is used."""
    with patch.object(
        builtins_module, "retrieve", AsyncMock(return_value=[])
    ) as mock_retrieve:
        tool = SearchLoreTool()
        ctx = ToolContext(session=mock_session, novel_id=42)
        await tool.execute(tool.Params(query="x"), ctx)
    mock_retrieve.assert_awaited_once()
    assert mock_retrieve.call_args.kwargs["novel_id"] == 42


@pytest.mark.asyncio
async def test_search_lore_params_novel_id_overrides_ctx(mock_session):
    """Explicit params.novel_id wins over ctx.novel_id."""
    with patch.object(
        builtins_module, "retrieve", AsyncMock(return_value=[])
    ) as mock_retrieve:
        tool = SearchLoreTool()
        ctx = ToolContext(session=mock_session, novel_id=42)
        await tool.execute(
            tool.Params(query="x", novel_id=99), ctx
        )
    assert mock_retrieve.call_args.kwargs["novel_id"] == 99


@pytest.mark.asyncio
async def test_search_lore_passes_stage_config(mock_session):
    """stage_config from ctx is forwarded to retrieve() (BYOK embeddings)."""
    from app.schemas.chat import StageConfig

    stage = StageConfig(
        api_base="https://embed.example.com/v1",
        api_key="sk-embed-xxx",
        model="text-embedding-3-small",
    )
    with patch.object(
        builtins_module, "retrieve", AsyncMock(return_value=[])
    ) as mock_retrieve:
        tool = SearchLoreTool()
        ctx = ToolContext(session=mock_session, novel_id=1, stage_config=stage)
        await tool.execute(tool.Params(query="x"), ctx)
    assert mock_retrieve.call_args.kwargs["stage_config"] is stage


def test_search_lore_rejects_empty_query():
    """Empty query fails pydantic validation."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SearchLoreTool.Params(query="")


def test_search_lore_k_must_be_in_range():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SearchLoreTool.Params(query="x", k=0)
    with pytest.raises(ValidationError):
        SearchLoreTool.Params(query="x", k=11)


@pytest.mark.asyncio
async def test_search_lore_requires_novel_id(mock_session):
    """Guard: search_lore refuses to run when novel_id is absent from both
    params and ctx (cross-novel retrieval is forbidden)."""
    tool = SearchLoreTool()
    ctx = ToolContext(session=mock_session)
    result = await tool.execute(tool.Params(query="x"), ctx)
    assert result.ok is False
    assert "novel_id is required" in (result.error or "")
    assert "cross-novel" in (result.error or "")


# ---------------------------------------------------------------------------
# GetCharacterTool — params validation
# ---------------------------------------------------------------------------


def test_get_character_requires_id_or_name():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="character_id or name"):
        GetCharacterTool.Params()


@pytest.mark.asyncio
async def test_get_character_name_lookup_requires_novel_id(mock_session):
    """Name-only lookup without novel_id (params or ctx) must be rejected.

    The guard lives in execute() as a runtime ToolResult.failure, not as a
    pydantic ValidationError on Params — novel_id defaults to None.
    """
    tool = GetCharacterTool()
    ctx = ToolContext(session=mock_session)
    result = await tool.execute(
        tool.Params(name="Detective Chen"), ctx
    )
    assert result.ok is False
    assert "novel_id is required" in (result.error or "")


def test_get_character_id_lookup_does_not_require_novel_id():
    """Lookup by ID is global — novel_id is optional."""
    p = GetCharacterTool.Params(character_id=7)
    assert p.character_id == 7
    assert p.novel_id is None


def test_get_character_can_take_both_id_and_name():
    """If both are provided, validation passes (handler prefers ID)."""
    p = GetCharacterTool.Params(character_id=7, name="X", novel_id=1)
    assert p.character_id == 7
    assert p.name == "X"


# ---------------------------------------------------------------------------
# GetCharacterTool — handler dispatch
# ---------------------------------------------------------------------------


def _fake_character(**overrides) -> Character:
    """Build a Character ORM instance with sensible defaults."""
    now = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
    defaults = dict(
        id=1, novel_id=0, name="Detective Chen", role="主角",
        description="A veteran detective.", attributes={"age": 45},
        arc_summary="Solved the locked-room mystery.",
        embedding=None, created_at=now, updated_at=now,
    )
    defaults.update(overrides)
    return Character(**defaults)


@pytest.mark.asyncio
async def test_get_character_by_id_happy_path(mock_session):
    char = _fake_character(id=42, name="Aria")
    with patch.object(
        builtins_module, "get_character", AsyncMock(return_value=char)
    ) as mock_get:
        tool = GetCharacterTool()
        ctx = ToolContext(session=mock_session)
        result = await tool.execute(
            tool.Params(character_id=42), ctx
        )
    assert result.ok is True
    assert result.data["id"] == 42
    assert result.data["name"] == "Aria"
    mock_get.assert_awaited_once_with(mock_session, 42)


@pytest.mark.asyncio
async def test_get_character_by_id_not_found(mock_session):
    from app.services.character import CharacterNotFound

    with patch.object(
        builtins_module, "get_character",
        AsyncMock(side_effect=CharacterNotFound(999)),
    ):
        tool = GetCharacterTool()
        ctx = ToolContext(session=mock_session)
        result = await tool.execute(
            tool.Params(character_id=999), ctx
        )
    assert result.ok is False
    assert "999" in (result.error or "")


@pytest.mark.asyncio
async def test_get_character_by_name_happy_path(mock_session):
    char = _fake_character(id=7, name="Aria", novel_id=5)
    with patch.object(
        builtins_module, "get_character_by_name",
        AsyncMock(return_value=char),
    ) as mock_by_name:
        tool = GetCharacterTool()
        ctx = ToolContext(session=mock_session)
        result = await tool.execute(
            tool.Params(name="Aria", novel_id=5), ctx
        )
    assert result.ok is True
    assert result.data["id"] == 7
    assert result.data["name"] == "Aria"
    mock_by_name.assert_awaited_once_with(mock_session, 5, "Aria")


@pytest.mark.asyncio
async def test_get_character_by_name_not_found(mock_session):
    with patch.object(
        builtins_module, "get_character_by_name",
        AsyncMock(return_value=None),
    ):
        tool = GetCharacterTool()
        ctx = ToolContext(session=mock_session)
        result = await tool.execute(
            tool.Params(name="Ghost", novel_id=1), ctx
        )
    assert result.ok is False
    assert "Ghost" in (result.error or "")
    assert "novel_id=1" in (result.error or "")


# ---------------------------------------------------------------------------
# SaveChapterTool — params validation
# ---------------------------------------------------------------------------


def test_save_chapter_requires_chapter_index():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SaveChapterTool.Params(title="x")  # missing chapter_index


def test_save_chapter_requires_title():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SaveChapterTool.Params(chapter_index=1)  # missing title


def test_save_chapter_defaults():
    p = SaveChapterTool.Params(chapter_index=1, title="Chapter 1")
    assert p.chapter_id is None
    assert p.novel_id is None
    assert p.content_text == ""
    assert p.summary == ""
    assert p.status == "draft"


@pytest.mark.asyncio
async def test_save_chapter_requires_novel_id(mock_session):
    """Guard: save_chapter refuses to run when novel_id is absent from both
    params and ctx."""
    tool = SaveChapterTool()
    ctx = ToolContext(session=mock_session)
    result = await tool.execute(
        tool.Params(chapter_index=1, title="Ch1"), ctx
    )
    assert result.ok is False
    assert "novel_id is required" in (result.error or "")


# ---------------------------------------------------------------------------
# SaveChapterTool — create path
# ---------------------------------------------------------------------------


def _fake_chapter(**overrides) -> Chapter:
    now = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
    defaults = dict(
        id=10, novel_id=0, chapter_index=1, title="Chapter 1",
        content_text="Once upon a time...", summary="Opening scene.",
        word_count=21, status="draft", metadata_json={},
        embedding=None, created_at=now, updated_at=now,
    )
    defaults.update(overrides)
    return Chapter(**defaults)


@pytest.mark.asyncio
async def test_save_chapter_create_path(mock_session):
    """chapter_id=None → calls create_chapter with ChapterCreate."""
    new_ch = _fake_chapter(id=10, title="The Beginning")
    with (
        patch.object(
            builtins_module, "create_chapter",
            AsyncMock(return_value=new_ch),
        ) as mock_create,
        patch("app.llm.embedding.embed_text", AsyncMock(return_value=[0.0])),
    ):
        tool = SaveChapterTool()
        ctx = ToolContext(session=mock_session, novel_id=5)
        result = await tool.execute(
            tool.Params(
                chapter_index=1, title="The Beginning",
                content_text="Once upon a time...",
            ),
            ctx,
        )
    assert result.ok is True
    assert result.data["id"] == 10
    assert result.data["title"] == "The Beginning"
    assert result.data["word_count"] == 21
    mock_create.assert_awaited_once()
    # First positional arg should be the session.
    assert mock_create.call_args.args[0] is mock_session
    # Second arg is a ChapterCreate — verify the title was propagated.
    payload = mock_create.call_args.args[1]
    assert payload.title == "The Beginning"
    assert payload.chapter_index == 1


@pytest.mark.asyncio
async def test_save_chapter_update_path(mock_session):
    """chapter_id=10 → calls update_chapter with ChapterUpdate."""
    existing_ch = _fake_chapter(id=10, novel_id=5)
    updated = _fake_chapter(
        id=10, novel_id=5, title="Revised Title", word_count=10, status="refined",
    )
    with (
        patch.object(
            builtins_module, "update_chapter",
            AsyncMock(return_value=updated),
        ) as mock_update,
        patch("app.services.chapter.get_chapter", AsyncMock(return_value=existing_ch)),
        patch("app.llm.embedding.embed_text", AsyncMock(return_value=[0.0])),
    ):
        tool = SaveChapterTool()
        ctx = ToolContext(session=mock_session, novel_id=5)
        result = await tool.execute(
            tool.Params(
                chapter_id=10, chapter_index=1, title="Revised Title",
                content_text="short text", status="refined",
            ),
            ctx,
        )
    assert result.ok is True
    assert result.data["id"] == 10
    assert result.data["status"] == "refined"
    mock_update.assert_awaited_once_with(
        mock_session, 10, mock_update.call_args.args[2],
    )
    # The ChapterUpdate should carry the new title + status.
    payload = mock_update.call_args.args[2]
    assert payload.title == "Revised Title"
    assert payload.status == "refined"


@pytest.mark.asyncio
async def test_save_chapter_update_path_not_found(mock_session):
    """get_chapter raising ChapterNotFound → ToolResult.failure.

    The cross-novel guard in save_chapter calls get_chapter() before
    update_chapter().  When the chapter doesn't exist, the error comes
    from that first lookup.
    """
    from app.services.chapter import ChapterNotFound

    with (
        patch(
            "app.services.chapter.get_chapter",
            AsyncMock(side_effect=ChapterNotFound(99)),
        ),
        patch("app.llm.embedding.embed_text", AsyncMock(return_value=[0.0])),
    ):
        tool = SaveChapterTool()
        ctx = ToolContext(session=mock_session, novel_id=5)
        result = await tool.execute(
            tool.Params(
                chapter_id=99, chapter_index=1, title="x",
            ),
            ctx,
        )
    assert result.ok is False
    assert "99" in (result.error or "")


# ---------------------------------------------------------------------------
# make_default_registry()
# ---------------------------------------------------------------------------


def test_make_default_registry_has_three_tools():
    reg = make_default_registry()
    assert sorted(reg.list_names()) == [
        "get_character", "save_chapter", "search_lore",
    ]


def test_make_default_registry_schemas_exportable():
    """All three tools must export valid JSON Schemas."""
    reg = make_default_registry()
    schemas = reg.schemas()
    assert len(schemas) == 3
    for s in schemas:
        assert s["type"] == "function"
        assert "name" in s["function"]
        assert "description" in s["function"]
        assert "parameters" in s["function"]
        # Each schema must be a non-empty JSON Schema object.
        params = s["function"]["parameters"]
        assert isinstance(params, dict)
        assert "properties" in params
        assert isinstance(params["properties"], dict)


def test_make_default_registry_returns_fresh_instance():
    """Each call returns a new registry — registration state does not leak."""
    reg1 = make_default_registry()
    reg2 = make_default_registry()
    assert reg1 is not reg2
    # Registering an extra tool on reg1 does not affect reg2.
    reg1.register(_DummyTool())
    assert reg1.has("dummy")
    assert not reg2.has("dummy")


# ---------------------------------------------------------------------------
# End-to-end via registry.invoke (uses mock_session fixture)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_invoke_search_lore_end_to_end(mock_session):
    """invoke() validates params, calls handler, returns ToolResult."""
    fake_hits = []
    with patch.object(
        builtins_module, "retrieve", AsyncMock(return_value=fake_hits)
    ):
        reg = make_default_registry()
        ctx = ToolContext(session=mock_session, novel_id=1)
        result = await reg.invoke(
            "search_lore",
            {"query": "detective", "k": 2},
            ctx,
        )
    assert result.ok is True
    assert result.data["count"] == 0
    assert result.data["query"] == "detective"


@pytest.mark.asyncio
async def test_registry_invoke_get_character_by_id_e2e(mock_session):
    char = _fake_character(id=5, name="Aria")
    with patch.object(
        builtins_module, "get_character", AsyncMock(return_value=char)
    ):
        reg = make_default_registry()
        ctx = ToolContext(session=mock_session)
        result = await reg.invoke(
            "get_character",
            {"character_id": 5},
            ctx,
        )
    assert result.ok is True
    assert result.data["name"] == "Aria"


@pytest.mark.asyncio
async def test_registry_invoke_save_chapter_create_e2e(mock_session):
    new_ch = _fake_chapter(id=1, title="Ch1")
    with (
        patch.object(
            builtins_module, "create_chapter", AsyncMock(return_value=new_ch)
        ),
        patch("app.llm.embedding.embed_text", AsyncMock(return_value=[0.0])),
    ):
        reg = make_default_registry()
        ctx = ToolContext(session=mock_session, novel_id=1)
        result = await reg.invoke(
            "save_chapter",
            {"chapter_index": 1, "title": "Ch1", "content_text": "x"},
            ctx,
        )
    assert result.ok is True
    assert result.data["id"] == 1
    assert result.data["title"] == "Ch1"


@pytest.mark.asyncio
async def test_registry_invoke_invalid_params_e2e(mock_session):
    """Registry-level invoke catches pydantic validation failures."""
    reg = make_default_registry()
    ctx = ToolContext(session=mock_session)
    # search_lore requires non-empty query.
    result = await reg.invoke("search_lore", {"query": ""}, ctx)
    assert result.ok is False
    assert "Invalid params" in (result.error or "")


@pytest.mark.asyncio
async def test_registry_invoke_unknown_tool_e2e(mock_session):
    reg = make_default_registry()
    ctx = ToolContext(session=mock_session)
    result = await reg.invoke("nonexistent_tool", {}, ctx)
    assert result.ok is False
    assert "not registered" in (result.error or "")
