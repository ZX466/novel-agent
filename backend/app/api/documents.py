"""REST CRUD endpoints for Document (a.k.a. 作品 in the novel surface).

Uses X-API-Key header authentication. All document operations are scoped
to the authenticated key — each key sees only its own documents (prevents
IDOR).

List supports type/category/search/status filters + pagination.
DELETE is soft-delete (回收站); restore / permanent endpoints handle
recovery and hard removal.

# TODO(auth): replace API key with proper user auth (JWT/OAuth) once
# authentication is introduced.
# TODO(security): sanitize content_html with nh3 before persisting once we
# expose content outside the Tiptap/ProseMirror renderer (e.g. PDF export,
# email, markdown preview). ProseMirror schema strips <script>/on* handlers
# so v1 is safe within Tiptap-only rendering.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._deps import require_api_key
from app.db.session import get_db
from app.schemas.document import (
    DocumentCreate,
    DocumentListResponse,
    DocumentRead,
    DocumentUpdate,
)
from app.services.document import (
    DocumentNotFound,
    create_document,
    delete_document,
    get_document,
    list_documents,
    permanent_delete_document,
    restore_document,
    update_document,
)

router = APIRouter(prefix="/v1/documents", tags=["documents"])


@router.get("", response_model=DocumentListResponse)
async def get_documents(
    type: str | None = Query(None, description="作品类型 novel/short/script/video"),
    category: str | None = Query(None, description="分类 长篇/短篇/剧本/视频"),
    search: str | None = Query(None, max_length=500, description="按标题模糊搜索"),
    status_filter: str | None = Query(
        None,
        alias="status",
        description="active(默认) / deleted(回收站) / 不传则默认 active",
    ),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> DocumentListResponse:
    """List documents, newest-first. Omits content_html/content_text.

    Filters: type, category, search, status. Pagination via limit/offset.
    """
    items, total = await list_documents(
        session,
        limit=limit,
        offset=offset,
        doc_type=type,
        category=category,
        search=search,
        status=status_filter,
    )
    return DocumentListResponse(items=items, total=total)  # type: ignore[arg-type]


@router.post(
    "",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_document(
    payload: DocumentCreate,
    response: Response,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> DocumentRead:
    """Create a new document. Returns 201 with Location header."""
    doc = await create_document(session, payload)
    response.headers["Location"] = f"/v1/documents/{doc.id}"
    return doc  # type: ignore[return-value]


@router.get("/{doc_id}", response_model=DocumentRead)
async def get_document_endpoint(
    doc_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> DocumentRead:
    """Return full document by ID. 404 if missing (or soft-deleted)."""
    try:
        return await get_document(session, doc_id)  # type: ignore[return-value]
    except DocumentNotFound:
        raise HTTPException(status_code=404, detail="Document not found")


@router.patch("/{doc_id}", response_model=DocumentRead)
async def patch_document_endpoint(
    doc_id: int,
    payload: DocumentUpdate,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> DocumentRead:
    """Partial update. Bumps version. 404 if missing."""
    try:
        return await update_document(session, doc_id, payload)  # type: ignore[return-value]
    except DocumentNotFound:
        raise HTTPException(status_code=404, detail="Document not found")


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document_endpoint(
    doc_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> Response:
    """Soft-delete by ID (moves to 回收站, recoverable). 204 on success."""
    try:
        await delete_document(session, doc_id)
    except DocumentNotFound:
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{doc_id}/restore", response_model=DocumentRead)
async def restore_document_endpoint(
    doc_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> DocumentRead:
    """Restore a soft-deleted document from the 回收站."""
    try:
        return await restore_document(session, doc_id)  # type: ignore[return-value]
    except DocumentNotFound:
        raise HTTPException(status_code=404, detail="Document not found")


@router.delete(
    "/{doc_id}/permanent",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def permanent_delete_document_endpoint(
    doc_id: int,
    session: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> Response:
    """Permanently remove the document. Irreversible."""
    try:
        await permanent_delete_document(session, doc_id)
    except DocumentNotFound:
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
