"""Ingesting uploaded files.

The hard part is not writing bytes to disk; it is making sure that a failure
anywhere in the sequence does not leave the database and the object store
disagreeing about what exists.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.core.logging import get_logger
from app.models.document import Document, DocumentStatus, SourceType
from app.repositories.document import DocumentRepository
from app.services.storage.base import ObjectStorage
from app.services.uploads.file_types import (
    SIGNATURE_PROBE_BYTES,
    FileType,
    detect,
    signature_matches,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class UploadResult:
    document: Document
    #: True when an identical file was already owned by this user, in which
    #: case `document` is the existing row and nothing new was stored.
    was_duplicate: bool


class UploadService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        documents: DocumentRepository,
        storage: ObjectStorage,
        settings: Settings,
    ) -> None:
        self._session = session
        self._documents = documents
        self._storage = storage
        self._settings = settings

    async def upload(
        self,
        *,
        owner_id: uuid.UUID,
        filename: str,
        stream: AsyncIterator[bytes],
        declared_content_type: str | None = None,
        collection_id: uuid.UUID | None = None,
    ) -> UploadResult:
        file_type = detect(filename)
        if file_type is None:
            raise UnsupportedMediaTypeError(
                f"{filename!r} is not a file type SecondBrain can index."
            )

        # The browser's Content-Type is a hint, not evidence — the extension
        # and the leading bytes decide.
        del declared_content_type

        stored = await self._storage.put(
            owner_id=owner_id,
            filename=filename,
            stream=self._guarded(stream, file_type=file_type, filename=filename),
        )

        if stored.size_bytes == 0:
            await self._storage.delete(stored.key)
            raise UnsupportedMediaTypeError("The file is empty.")

        # Dedupe *after* storing, because the hash is only known once the bytes
        # have been read, and reading them twice to check first would double
        # the cost of every upload to save work on the rare duplicate.
        existing = await self._documents.find_by_content_hash(
            stored.content_hash, owner_id=owner_id
        )
        if existing is not None:
            await self._storage.delete(stored.key)
            logger.info(
                "upload_deduplicated",
                document_id=str(existing.id),
                content_hash=stored.content_hash[:12],
            )
            return UploadResult(document=existing, was_duplicate=True)

        document = Document(
            owner_id=owner_id,
            collection_id=collection_id,
            title=_title_from(filename),
            original_filename=filename[:512],
            mime_type=file_type.mime_type,
            extension=file_type.extension.lstrip("."),
            size_bytes=stored.size_bytes,
            content_hash=stored.content_hash,
            source_type=SourceType.UPLOAD,
            storage_key=stored.key,
            status=DocumentStatus.PENDING,
        )

        try:
            await self._documents.add(document)
        except BaseException:
            # The row failed to persist, so nothing will ever reference these
            # bytes. Leaving them would be a slow storage leak that no query
            # can find.
            await self._storage.delete(stored.key)
            raise

        logger.info(
            "upload_accepted",
            document_id=str(document.id),
            extension=document.extension,
            size_bytes=document.size_bytes,
        )
        return UploadResult(document=document, was_duplicate=False)

    async def delete(self, document_id: uuid.UUID, *, owner_id: uuid.UUID) -> None:
        """Remove a document and its bytes.

        The row goes first. If storage deletion then fails we are left with an
        orphaned object — wasted space, but harmless and reclaimable by a
        sweep. The reverse order would leave a row pointing at nothing, which
        surfaces to the user as a document that opens to an error.
        """
        document = await self._documents.get_for_owner(document_id, owner_id=owner_id)
        if document is None:
            raise NotFoundError("Document not found.")

        storage_key = document.storage_key
        await self._documents.delete(document.id)
        await self._session.flush()

        if not await self._storage.delete(storage_key):
            logger.warning("storage_object_orphaned", document_id=str(document_id), key=storage_key)

    async def open_content(self, document: Document) -> AsyncIterator[bytes]:
        return await self._storage.open(document.storage_key)

    # ── Internals ────────────────────────────────────────────────────────

    async def _guarded(
        self, stream: AsyncIterator[bytes], *, file_type: FileType, filename: str
    ) -> AsyncIterator[bytes]:
        """Enforce the size cap and signature check mid-stream.

        Both checks happen while forwarding rather than afterwards: the whole
        point of a size limit is to stop reading, and a limit applied after the
        bytes are already on disk protects nothing.
        """
        limit = self._settings.max_upload_bytes
        total = 0
        head = b""
        checked = False

        async for chunk in stream:
            total += len(chunk)
            if total > limit:
                raise PayloadTooLargeError(
                    f"{filename!r} exceeds the {limit // (1024 * 1024)} MB upload limit."
                )

            if not checked:
                head += chunk[: SIGNATURE_PROBE_BYTES - len(head)]
                if len(head) >= SIGNATURE_PROBE_BYTES or not file_type.signatures:
                    if not signature_matches(file_type, head):
                        raise UnsupportedMediaTypeError(
                            f"{filename!r} does not contain valid "
                            f"{file_type.extension.lstrip('.')} data."
                        )
                    checked = True

            yield chunk

        # A file shorter than the probe window still has to be verified.
        if not checked and not signature_matches(file_type, head):
            raise UnsupportedMediaTypeError(
                f"{filename!r} does not contain valid {file_type.extension.lstrip('.')} data."
            )


def _title_from(filename: str) -> str:
    """A human-facing title: the stem, with separators relaxed into spaces."""
    stem = Path(filename).stem.strip() or filename
    return stem.replace("_", " ").replace("-", " ").strip()[:512] or filename[:512]
