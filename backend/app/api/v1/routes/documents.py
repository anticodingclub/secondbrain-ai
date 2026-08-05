"""Document upload and management."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    CurrentUser,
    DocumentRepositoryDep,
    ParsingServiceDep,
    SessionDep,
    SettingsDep,
    UploadServiceDep,
)
from app.core.exceptions import NotFoundError
from app.models.document import Document, DocumentStatus
from app.schemas.document import (
    DocumentFilters,
    DocumentResponse,
    ExtractedTextResponse,
    Page,
    StorageUsageResponse,
    TextBlockResponse,
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
    session: SessionDep,
    upload_service: UploadServiceDep,
    parsing_service: ParsingServiceDep,
    background: BackgroundTasks,
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
    response = UploadResponse(
        document=DocumentResponse.model_validate(result.document),
        was_duplicate=result.was_duplicate,
    )

    # Parsing runs after the response so the client is not left waiting on a
    # 200-page PDF. A duplicate is already parsed; re-running would repeat the
    # work for no change.
    if not result.was_duplicate:
        # This commit is load-bearing, and one of the few places a handler
        # commits deliberately. FastAPI runs background tasks *before* it tears
        # down `yield` dependencies, so `get_session` has not committed yet at
        # this point. Without committing here, the parser opens its own session
        # and finds no such document — every upload would sit at `pending`
        # forever while the log filled with `parse_target_missing`.
        await session.commit()
        background.add_task(
            parsing_service.parse_document, result.document.id, owner_id=current_user.id
        )

    return response


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


@router.get(
    "/{document_id}/text",
    response_model=ExtractedTextResponse,
    summary="The extracted text and its citation anchors",
)
async def get_extracted_text(
    document: OwnedDocument, parsing_service: ParsingServiceDep
) -> ExtractedTextResponse:
    parsed = await parsing_service.load_blocks(document)
    if parsed is None:
        raise NotFoundError(
            "This document has not been parsed yet."
            if document.status in {DocumentStatus.PENDING, DocumentStatus.PARSING}
            else "No extracted text is available for this document."
        )

    return ExtractedTextResponse(
        document_id=document.id,
        page_count=document.page_count,
        word_count=document.word_count or 0,
        warnings=list(parsed.warnings),
        blocks=[
            TextBlockResponse(
                text=block.text,
                page_number=block.page_number,
                section_title=block.section_title,
                heading_level=block.heading_level,
                metadata=block.metadata,
            )
            for block in parsed.blocks
        ],
    )


@router.post(
    "/{document_id}/reparse",
    response_model=DocumentResponse,
    summary="Extract the text again",
)
async def reparse_document(
    document: OwnedDocument,
    current_user: CurrentUser,
    session: SessionDep,
    parsing_service: ParsingServiceDep,
    background: BackgroundTasks,
) -> DocumentResponse:
    """Re-run extraction.

    Worth having for the failure cases that are fixable without re-uploading:
    a scanned PDF after Tesseract is installed, or anything that failed on a
    parser bug since fixed.
    """
    response = DocumentResponse.model_validate(document)
    # Same ordering hazard as upload — see the comment there.
    await session.commit()
    background.add_task(parsing_service.parse_document, document.id, owner_id=current_user.id)
    return response


@router.delete(
    "/{document_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a document"
)
async def delete_document(
    document_id: uuid.UUID, current_user: CurrentUser, upload_service: UploadServiceDep
) -> None:
    await upload_service.delete(document_id, owner_id=current_user.id)
