"""Built-in tools: search_lore / get_character / save_chapter.

These three tools are the minimum viable set for an agent to ground its
writing in the novel's memory layer:

  - search_lore    — semantic search across all four memory collections
                     (chapters, characters, world_settings, plot_events).
                     Used by drafting agents to retrieve relevant prior
                     context before writing.
  - get_character  — fetch a character profile by ID or by name within
                     a novel. Used by CharacterAgent and consistency
                     checks to inspect a single character in detail.
  - save_chapter   — persist a chapter's content (create or update).
                     Used by PlotterAgent to commit a draft and by
                     EditorAgent to commit a refined version.

Each tool wraps an existing service function with:
  - Pydantic parameter validation
  - ToolResult envelope (no exceptions escape to the agent)
  - ToolContext for runtime resources (session, BYOK stage_config, novel_id)

The handler signatures are uniform: (params, ctx) -> ToolResult. Adding
a new tool is a matter of subclassing Tool and registering it.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.schemas.novel_memory import (
    ChapterCreate,
    ChapterUpdate,
    CharacterRead,
)
from app.services.chapter import (
    create_chapter,
    update_chapter,
    update_chapter_embedding,
)
from app.services.character import (
    CharacterNotFound,
    get_character,
    get_character_by_name,
)
from app.services.retrieval import retrieve
from app.tools.base import Tool, ToolContext, ToolResult


# ---------------------------------------------------------------------------
# search_lore — semantic retrieval across all four collections
# ---------------------------------------------------------------------------


class SearchLoreTool(Tool):
    """Search the novel's memory layer for relevant content.

    Wraps `app.services.retrieval.retrieve` — embeds the query and
    searches chapters / characters / world_settings / plot_events in
    parallel, returning hits ranked by descending similarity.

    Use this BEFORE writing a chapter to ground the draft in established
    lore. The query is the natural-language description of what the
    agent is looking for ("Detective Chen's backstory", "the robbery
    scene in chapter 3").
    """

    name = "search_lore"
    description = (
        "Semantic search over the novel's memory: chapters, characters, "
        "world_settings, and plot_events. Returns ranked hits by similarity "
        "to the query. Use to ground writing in established lore."
    )

    class Params(BaseModel):
        query: str = Field(
            ..., min_length=1, description="Natural-language search query."
        )
        novel_id: int | None = Field(
            default=None, ge=0,
            description="Scope to a specific novel. Defaults to ctx.novel_id.",
        )
        k: int = Field(
            default=3, ge=1, le=10,
            description="Max hits per collection (total ≤ 4×k).",
        )

    async def execute(self, params, ctx: ToolContext) -> ToolResult:
        novel_id = (
            params.novel_id if params.novel_id is not None else ctx.novel_id
        )
        # Novel scope protection: refuse to run a cross-novel search.
        # Without a novel_id, retrieve() would leak characters/worlds from
        # other stories into the results — a hard scope violation.
        if novel_id is None:
            return ToolResult.failure(
                "novel_id is required for search_lore: pass it in params "
                "or set ctx.novel_id (cross-novel retrieval is forbidden)"
            )
        try:
            hits = await retrieve(
                ctx.session,
                params.query,
                novel_id=novel_id,
                k_per_collection=params.k,
                stage_config=ctx.stage_config,
            )
        except ValueError as e:
            return ToolResult.failure(str(e))
        return ToolResult.success(
            data={
                "hits": [h.model_dump() for h in hits],
                "count": len(hits),
                "query": params.query,
            }
        )


# ---------------------------------------------------------------------------
# get_character — fetch a character profile by ID or name
# ---------------------------------------------------------------------------


class GetCharacterTool(Tool):
    """Fetch a character profile by ID or by name within a novel.

    Wraps `app.services.character.get_character` /
    `get_character_by_name`. When `character_id` is provided, the
    lookup is global (every character ID is unique). When `name` is
    provided instead, `novel_id` is required to disambiguate across
    novels (the same name may appear in different stories).
    """

    name = "get_character"
    description = (
        "Fetch a character profile by ID or by name. When using name, "
        "novel_id is required to disambiguate across novels. Returns the "
        "full character record including description, role, and attributes."
    )

    class Params(BaseModel):
        character_id: int | None = Field(
            default=None, ge=1,
            description="Lookup by character ID (global).",
        )
        name: str | None = Field(
            default=None, min_length=1,
            description="Lookup by name within a novel.",
        )
        novel_id: int | None = Field(
            default=None, ge=0,
            description="Required when looking up by name.",
        )

        @model_validator(mode="after")
        def _require_id_or_name(self):
            if self.character_id is None and not self.name:
                raise ValueError(
                    "Either character_id or name must be provided"
                )
            return self

    async def execute(self, params, ctx: ToolContext) -> ToolResult:
        if params.character_id is not None:
            try:
                c = await get_character(ctx.session, params.character_id)
            except CharacterNotFound as e:
                return ToolResult.failure(str(e))
            # Cross-novel guard: verify the character belongs to the expected
            # novel when ctx.novel_id is set. Without this check, any agent
            # could read characters from other novels by guessing IDs.
            if ctx.novel_id is not None and c.novel_id != ctx.novel_id:
                return ToolResult.failure(
                    f"Character {params.character_id} belongs to "
                    f"novel_id={c.novel_id}, not novel_id={ctx.novel_id}"
                )
        else:
            # Validator guarantees name + novel_id are set here.
            # Resolve novel scope: explicit param > ctx.novel_id. Refuse
            # cross-novel name lookups — the same name may exist in multiple
            # stories and an unscoped lookup is a scope violation.
            lookup_novel_id = (
                params.novel_id if params.novel_id is not None else ctx.novel_id
            )
            if lookup_novel_id is None:
                return ToolResult.failure(
                    "novel_id is required when looking up a character by name "
                    "(pass it in params or set ctx.novel_id)"
                )
            c = await get_character_by_name(
                ctx.session, lookup_novel_id, params.name
            )
            if c is None:
                return ToolResult.failure(
                    f"No character named {params.name!r} in novel_id={lookup_novel_id}"
                )
        return ToolResult.success(
            data=CharacterRead.model_validate(c).model_dump()
        )


# ---------------------------------------------------------------------------
# save_chapter — create or update a chapter
# ---------------------------------------------------------------------------


class SaveChapterTool(Tool):
    """Persist a chapter's content (create or update).

    When `chapter_id` is None, creates a new chapter via
    `app.services.chapter.create_chapter`. When `chapter_id` is
    provided, updates the existing chapter via `update_chapter`.

    Word count is auto-computed from `content_text` when omitted
    (handled by the service layer). Embeddings are NOT auto-generated
    by this tool — that's a separate concern owned by the writing
    pipeline (`update_chapter_embedding`). A separate tool can be
    added later if agents need to trigger embedding refresh.

    Returns the saved chapter's id, title, and word_count so the
    agent can reference it in subsequent tool calls.
    """

    name = "save_chapter"
    description = (
        "Persist a chapter (create new or update existing). When chapter_id "
        "is None, creates a new chapter; otherwise updates the existing one. "
        "Returns the saved chapter's id and word_count."
    )

    class Params(BaseModel):
        chapter_id: int | None = Field(
            default=None, ge=1,
            description="If provided, update the existing chapter with this id.",
        )
        novel_id: int | None = Field(
            default=None, ge=0,
            description="Novel scope. Defaults to ctx.novel_id when omitted.",
        )
        chapter_index: int = Field(
            ..., ge=0,
            description="Position of the chapter in the novel (1-based typically).",
        )
        title: str = Field(..., min_length=1, max_length=500)
        content_text: str = Field(default="")
        summary: str = Field(default="")
        status: str = Field(
            default="draft", max_length=32,
            description="Chapter lifecycle state: draft|refined|polished|final.",
        )

    async def execute(self, params, ctx: ToolContext) -> ToolResult:
        # Resolve novel_id: explicit param > ctx.novel_id > error
        novel_id = params.novel_id if params.novel_id is not None else ctx.novel_id
        if novel_id is None:
            return ToolResult.failure(
                "novel_id is required: pass it in params or set ctx.novel_id"
            )
        if params.chapter_id is not None:
            # Cross-novel guard BEFORE the update: fetch first and verify
            # ownership so we never mutate a chapter belonging to another
            # novel. Verifying after the update would already have
            # committed the change — too late.
            from app.services.chapter import get_chapter, ChapterNotFound
            try:
                existing = await get_chapter(ctx.session, params.chapter_id)
            except ChapterNotFound as e:
                return ToolResult.failure(str(e))
            if existing.novel_id != novel_id:
                return ToolResult.failure(
                    f"Chapter {params.chapter_id} belongs to "
                    f"novel_id={existing.novel_id}, not novel_id={novel_id}"
                )
            try:
                ch = await update_chapter(
                    ctx.session,
                    params.chapter_id,
                    ChapterUpdate(
                        chapter_index=params.chapter_index,
                        title=params.title,
                        content_text=params.content_text,
                        summary=params.summary,
                        status=params.status,
                    ),
                )
            except ChapterNotFound as e:
                return ToolResult.failure(str(e))
        else:
            ch = await create_chapter(
                ctx.session,
                ChapterCreate(
                    novel_id=novel_id,
                    chapter_index=params.chapter_index,
                    title=params.title,
                    content_text=params.content_text,
                    summary=params.summary,
                    status=params.status,
                )
            )
        # Best-effort embedding refresh so the chapter is immediately
        # searchable via `search_lore`. Failures are logged but never
        # fail the save — the chapter exists, it just isn't in the
        # vector index until the next explicit refresh.
        #
        # Embeddings use their own dedicated credentials (.env EMBEDDING_*),
        # NOT ctx.stage_config — that is a chat stage pointing at a chat-only
        # endpoint whose model/api_base are invalid for /embeddings (404).
        if ch.content_text and ch.content_text.strip():
            try:
                from app.llm.embedding import embed_text
                embedding = await embed_text(
                    ch.content_text, stage_config=ctx.embedding_stage_config,
                )
                await update_chapter_embedding(ctx.session, ch.id, embedding)
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "save_chapter: embedding generation failed for chapter_id=%s — "
                    "memory/RAG disabled for this row (check EMBEDDING_* in backend/.env)",
                    ch.id,
                    exc_info=True,
                )
        return ToolResult.success(
            data={
                "id": ch.id,
                "novel_id": ch.novel_id,
                "chapter_index": ch.chapter_index,
                "title": ch.title,
                "word_count": ch.word_count,
                "status": ch.status,
            }
        )


# ---------------------------------------------------------------------------
# Factory: default registry with all built-in tools
# ---------------------------------------------------------------------------


def make_default_registry() -> "ToolRegistry":  # noqa: F821 (local import below)
    """Build a ToolRegistry with the three built-in tools registered.

    Returns a fresh registry on each call — caller may register
    additional tools or replace built-ins via direct mutation
    (not encouraged; prefer composing a new registry).
    """
    from app.tools.base import ToolRegistry  # local import to avoid cycle

    reg = ToolRegistry()
    reg.register(SearchLoreTool())
    reg.register(GetCharacterTool())
    reg.register(SaveChapterTool())
    return reg
