"""Document upload and management."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    CurrentUser,
    DocumentRepositoryDep,
    SettingsDep,
    UploadServiceDep,
)
from app.core.exceptions import NotFoundError
from app.models.document import Document
from app.schemas.document import (
    DocumentFilters,
    DocumentResponse,
    Page,
    StorageUsageResponse,
    UploadResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])

#: Matches the storage layer's read size; keeps one buffer size in play.
STREAM_CHUNK_SIZE = 1024 * 1024


async def _stream_upload(upload: UploadFile) -> AsyncIterator[bytes]:
    """Adapt Starlette's UploadFile to a plain byte iterator.

    Starlette already spills large uploads to a temporary file, so this reads
    from disk rather than memory for anything sizeable.
    """
    while chunk := await upload.read(STREAM_CHUNK_SIZE):
        yield chunk


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document",
)
async def upload_document(
    current_user: CurrentUser,
    upload_service: UploadServiceDep,
    file: Annotated[UploadFile, File(description="The file to index.")],
    collection_id: Annotated[uuid.UUID | None, Form()] = None,
) -> UploadResponse:
    result = await upload_service.upload(
        owner_id=current_user.id,
        filename=file.filename or "untitled",
        stream=_stream_upload(file),
        declared_content_type=file.content_type,
        collection_id=collection_id,
    )
    return UploadResponse(
        document=DocumentResponse.model_validate(result.document),
        was_duplicate=result.was_duplicate,
    )


@router.get("", response_model=Page[DocumentResponse], summary="List documents")
async def list_documents(
    current_user: CurrentUser,
    documents: DocumentRepositoryDep,
    filters: Annotated[DocumentFilters, Query()],
) -> Page[DocumentResponse]:
    criteria: dict[str, object] = {
        "status": filters.status,
        "extensions": filters.extension,
        "collection_id": filters.collection_id,
        "search": filters.search,
        "created_after": filters.created_after,
        "created_before": filters.created_before,
    }

    rows = await documents.list_for_owner(
        owner_id=current_user.id,
        limit=filters.limit,
        offset=filters.offset,
        **criteria,
    )
    total = await documents.count_for_owner(owner_id=current_user.id, **criteria)

    return Page[DocumentResponse](
        items=[DocumentResponse.model_validate(row) for row in rows],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


@router.get("/usage", response_model=StorageUsageResponse, summary="Storage usage")
async def storage_usage(
    current_user: CurrentUser,
    documents: DocumentRepositoryDep,
    settings: SettingsDep,
) -> StorageUsageResponse:
    return StorageUsageResponse(
        document_count=await documents.count_for_owner(owner_id=current_user.id),
        total_bytes=await documents.total_bytes_for_owner(current_user.id),
        max_upload_bytes=settings.max_upload_bytes,
    )


async def _owned_document(
    document_id: uuid.UUID, current_user: CurrentUser, documents: DocumentRepositoryDep
) -> Document:
    """Load a document or 404.

    Returns the same 404 whether the document is missing or belongs to someone
    else, so the endpoint cannot be used to probe for valid ids.
    """
    document = await documents.get_for_owner(document_id, owner_id=current_user.id)
    if document is None:
        raise NotFoundError("Document not found.")
    return document


OwnedDocument = Annotated[Document, Depends(_owned_document)]


@router.get("/{document_id}", response_model=DocumentResponse, summary="One document")
async def get_document(document: OwnedDocument) -> DocumentResponse:
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/content", summary="Download the original file")
async def download_document(
    document: OwnedDocument, upload_service: UploadServiceDep
) -> StreamingResponse:
    stream = await upload_service.open_content(document)

    return StreamingResponse(
        stream,
        media_type=document.mime_type,
        headers={
            # `filename*` carries the UTF-8 form for non-ASCII names; the plain
            # `filename` is the ASCII fallback older clients understand.
            "Content-Disposition": (
                f"inline; filename*=UTF-8''{quote(document.original_filename)}"
            ),
            "Content-Length": str(document.size_bytes),
        },
    )


@router.delete(
    "/{document_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a document"
)
async def delete_document(
    document_id: uuid.UUID, current_user: CurrentUser, upload_service: UploadServiceDep
) -> None:
    await upload_service.delete(document_id, owner_id=current_user.id)
