"""Moving a stored document through extraction.

Owns the status lifecycle, the temp-file dance the parsing libraries require,
and the rule that a document which fails to parse is still a document the user
owns — it is marked failed with a reason, never deleted.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import DocumentParseError, NotFoundError
from app.core.logging import get_logger
from app.models.document import Document, DocumentStatus
from app.repositories.document import DocumentRepository
from app.services.parsing import ParseContext, ParsedDocument, ParserRegistry
from app.services.storage.base import ObjectStorage

logger = get_logger(__name__)

#: Suffix for the extracted-blocks artifact stored beside the original.
BLOCKS_SUFFIX = ".blocks.json"


class ParsingService:
    """Extracts text from an uploaded document.

    Takes a session *factory* rather than a session because it runs after the
    HTTP response has been sent, by which point the request's transaction is
    long closed. Each document gets its own short transaction, so one failure
    cannot roll back another document's progress.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage: ObjectStorage,
        registry: ParserRegistry,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._registry = registry

    async def parse_document(self, document_id: uuid.UUID, *, owner_id: uuid.UUID) -> None:
        """Parse one document, recording the outcome either way.

        Never raises for an unreadable file: it is invoked as a background
        task, where an exception would vanish into the void and leave the
        document stuck at `parsing` forever with nothing to explain it.
        """
        async with self._session_factory() as session:
            documents = DocumentRepository(session)
            document = await documents.get_for_owner(document_id, owner_id=owner_id)
            if document is None:
                logger.warning("parse_target_missing", document_id=str(document_id))
                return

            document.status = DocumentStatus.PARSING
            document.error_message = None
            await session.commit()

            storage_key = document.storage_key
            filename = document.original_filename
            mime_type = document.mime_type
            extension = document.extension

        try:
            parsed = await self._extract(
                storage_key=storage_key,
                filename=filename,
                mime_type=mime_type,
                extension=extension,
            )
        except DocumentParseError as exc:
            await self._record_failure(document_id, owner_id, str(exc))
            return
        except Exception as exc:
            logger.exception("parse_unexpected_failure", document_id=str(document_id))
            await self._record_failure(
                document_id, owner_id, f"An unexpected error occurred: {exc}"
            )
            return

        await self._record_success(document_id, owner_id, storage_key, parsed)

    async def _extract(
        self, *, storage_key: str, filename: str, mime_type: str, extension: str
    ) -> ParsedDocument:
        """Stream the object to a temp file and parse it off the event loop."""
        suffix = Path(filename).suffix or f".{extension}"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            temp_path = Path(handle.name)
            try:
                async for chunk in await self._storage.open(storage_key):
                    handle.write(chunk)
            except BaseException:
                handle.close()
                temp_path.unlink(missing_ok=True)
                raise

        try:
            context = ParseContext(
                path=temp_path,
                filename=filename,
                mime_type=mime_type,
                extension=extension,
            )
            # Every parsing library is blocking and CPU-bound. Running one
            # inline would stall every other request on this worker for the
            # duration of a 200-page PDF.
            return await asyncio.to_thread(self._registry.parse, context)
        finally:
            temp_path.unlink(missing_ok=True)

    async def _record_success(
        self,
        document_id: uuid.UUID,
        owner_id: uuid.UUID,
        storage_key: str,
        parsed: ParsedDocument,
    ) -> None:
        # Blocks are persisted to object storage rather than Postgres: the
        # full text of 100k documents is bulk that no query filters on, and
        # Phase 5 reads it exactly once per document to chunk it.
        payload = json.dumps(
            {
                "blocks": [asdict(block) for block in parsed.blocks],
                "metadata": parsed.metadata,
                "warnings": list(parsed.warnings),
            },
            ensure_ascii=False,
        ).encode("utf-8")

        blocks_key = await self._storage.put_derived(
            source_key=storage_key, suffix=BLOCKS_SUFFIX, data=payload
        )

        async with self._session_factory() as session:
            documents = DocumentRepository(session)
            document = await documents.get_for_owner(document_id, owner_id=owner_id)
            if document is None:
                # Deleted while we were parsing; drop the artifact we just made.
                await self._storage.delete(blocks_key)
                return

            document.status = DocumentStatus.PARSED
            document.page_count = parsed.page_count
            document.word_count = parsed.word_count
            document.error_message = None
            document.doc_metadata = {
                **document.doc_metadata,
                **parsed.metadata,
                "blocks_key": blocks_key,
                "block_count": len(parsed.blocks),
                "warnings": list(parsed.warnings),
            }
            await session.commit()

        logger.info(
            "document_parsed",
            document_id=str(document_id),
            blocks=len(parsed.blocks),
            words=parsed.word_count,
            pages=parsed.page_count,
            warnings=len(parsed.warnings),
        )

    async def _record_failure(
        self, document_id: uuid.UUID, owner_id: uuid.UUID, message: str
    ) -> None:
        async with self._session_factory() as session:
            documents = DocumentRepository(session)
            document = await documents.get_for_owner(document_id, owner_id=owner_id)
            if document is None:
                return

            document.status = DocumentStatus.FAILED
            # Truncated because some libraries put an entire stack trace in the
            # message, and this is rendered to the user.
            document.error_message = message[:1000]
            await session.commit()

        logger.warning("document_parse_failed", document_id=str(document_id), reason=message)

    async def load_blocks(self, document: Document) -> ParsedDocument | None:
        """Read back what a previous parse produced. Used by Phase 5."""
        blocks_key = document.doc_metadata.get("blocks_key")
        if not isinstance(blocks_key, str):
            return None

        try:
            raw = b"".join([chunk async for chunk in await self._storage.open(blocks_key)])
        except NotFoundError:
            return None

        from app.services.parsing.base import TextBlock

        payload = json.loads(raw)
        return ParsedDocument(
            blocks=[TextBlock(**block) for block in payload["blocks"]],
            page_count=document.page_count,
            metadata=payload.get("metadata", {}),
            warnings=tuple(payload.get("warnings", [])),
        )
