"""Cloning a repository and importing its files as documents.

Every imported file becomes an ordinary `Document`, so search, chat, citations
and deletion all work on repository code without knowing it came from one. The
alternative — a parallel "code" pipeline — would have meant duplicating
chunking, embedding and retrieval for no gain.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.models.collection import Collection, CollectionKind
from app.models.document import Document, SourceType
from app.models.repository import Repository, RepositoryStatus
from app.repositories.document import DocumentRepository
from app.services.indexing import IndexingService
from app.services.parsing.pipeline import ParsingService
from app.services.repositories.git import RepositoryError, RepositoryRef, clone
from app.services.repositories.walker import walk_repository
from app.services.storage.base import ObjectStorage

logger = get_logger(__name__)


class RepositoryImportService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage: ObjectStorage,
        parsing: ParsingService,
        indexing: IndexingService,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._parsing = parsing
        self._indexing = indexing

    async def import_repository(
        self, repository_id: uuid.UUID, *, owner_id: uuid.UUID, ref: RepositoryRef
    ) -> None:
        """Clone, import and index. Records failure rather than raising.

        Runs as a background task, so an exception would vanish and leave the
        repository stuck at `cloning` with nothing to explain it.
        """
        # A temporary directory, not permanent storage: the checkout is a
        # means to read files once. Keeping it would double disk use for a
        # copy nothing ever reads again.
        checkout = Path(tempfile.mkdtemp(prefix="secondbrain-repo-"))

        try:
            await self._set_status(repository_id, owner_id, RepositoryStatus.CLONING)
            commit_sha = await clone(ref, checkout)

            await self._set_status(repository_id, owner_id, RepositoryStatus.IMPORTING)
            walk = walk_repository(checkout)

            logger.info(
                "repository_walked",
                repository=ref.full_name,
                files=len(walk.files),
                skipped=walk.skipped,
            )

            collection_id = await self._ensure_collection(repository_id, owner_id, ref)
            document_ids = await self._import_files(
                checkout, walk.files, owner_id=owner_id, collection_id=collection_id
            )

            await self._finalise(
                repository_id,
                owner_id,
                commit_sha=commit_sha,
                file_count=len(document_ids),
                skipped=walk.skipped,
                metadata={
                    "skip_reasons": walk.reasons,
                    "truncated": walk.truncated,
                },
            )

            # Indexed one at a time rather than concurrently: the embedding
            # model is a single in-process runtime, so parallel calls contend
            # for it instead of going faster.
            for document_id in document_ids:
                await self._parsing.parse_document(document_id, owner_id=owner_id)
                await self._indexing.index_document(document_id, owner_id=owner_id)

            logger.info(
                "repository_imported",
                repository=ref.full_name,
                documents=len(document_ids),
            )
        except RepositoryError as exc:
            await self._record_failure(repository_id, owner_id, str(exc))
        except Exception as exc:
            logger.exception("repository_import_failed", repository=ref.full_name)
            await self._record_failure(
                repository_id, owner_id, f"An unexpected error occurred: {exc}"
            )
        finally:
            shutil.rmtree(checkout, ignore_errors=True)

    # ── Internals ────────────────────────────────────────────────────────

    async def _ensure_collection(
        self, repository_id: uuid.UUID, owner_id: uuid.UUID, ref: RepositoryRef
    ) -> uuid.UUID:
        """Give the repository a collection, so its files can be filtered and
        chatted with as a unit."""
        async with self._session_factory() as session:
            repository = await session.get(Repository, repository_id)
            if repository is not None and repository.collection_id is not None:
                return repository.collection_id

            collection = Collection(
                owner_id=owner_id,
                name=ref.full_name,
                kind=CollectionKind.GITHUB_REPO,
                description=f"Imported from {ref.clone_url}",
            )
            session.add(collection)
            await session.flush()

            if repository is not None:
                repository.collection_id = collection.id

            collection_id = collection.id
            await session.commit()
            return collection_id

    async def _import_files(
        self,
        checkout: Path,
        files: list[Path],
        *,
        owner_id: uuid.UUID,
        collection_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        document_ids: list[uuid.UUID] = []

        async with self._session_factory() as session:
            documents = DocumentRepository(session)

            for path in files:
                relative = path.relative_to(checkout)
                stored = await self._storage.put(
                    owner_id=owner_id,
                    filename=path.name,
                    stream=_read_in_chunks(path),
                )

                # Content-hash dedupe still applies: a LICENSE identical to one
                # already owned is not stored twice. The existing document is
                # reused, which is right — it is the same bytes.
                existing = await documents.find_by_content_hash(
                    stored.content_hash, owner_id=owner_id
                )
                if existing is not None:
                    await self._storage.delete(stored.key)
                    continue

                from app.services.uploads.file_types import detect

                file_type = detect(path.name)
                document = Document(
                    owner_id=owner_id,
                    collection_id=collection_id,
                    # The path, not the bare filename: forty files called
                    # `index.ts` are indistinguishable otherwise, and the path
                    # is what a developer actually recognises.
                    title=str(relative).replace("\\", "/"),
                    original_filename=str(relative).replace("\\", "/")[:512],
                    mime_type=file_type.mime_type if file_type else "text/plain",
                    extension=(file_type.extension.lstrip(".") if file_type else "txt"),
                    size_bytes=stored.size_bytes,
                    content_hash=stored.content_hash,
                    source_type=SourceType.GITHUB,
                    storage_key=stored.key,
                    doc_metadata={"repository_path": str(relative).replace("\\", "/")},
                )
                await documents.add(document)
                document_ids.append(document.id)

            await session.commit()

        return document_ids

    async def _set_status(
        self, repository_id: uuid.UUID, owner_id: uuid.UUID, status: RepositoryStatus
    ) -> None:
        async with self._session_factory() as session:
            repository = await session.get(Repository, repository_id)
            if repository is None or repository.owner_id != owner_id:
                return
            repository.status = status
            repository.error_message = None
            await session.commit()

    async def _finalise(
        self,
        repository_id: uuid.UUID,
        owner_id: uuid.UUID,
        *,
        commit_sha: str,
        file_count: int,
        skipped: int,
        metadata: dict[str, object],
    ) -> None:
        async with self._session_factory() as session:
            repository = await session.get(Repository, repository_id)
            if repository is None or repository.owner_id != owner_id:
                return
            repository.status = RepositoryStatus.READY
            repository.commit_sha = commit_sha or None
            repository.file_count = file_count
            repository.skipped_count = skipped
            repository.last_synced_at = datetime.now(UTC)
            repository.repo_metadata = {**repository.repo_metadata, **metadata}
            repository.error_message = None
            await session.commit()

    async def _record_failure(
        self, repository_id: uuid.UUID, owner_id: uuid.UUID, message: str
    ) -> None:
        async with self._session_factory() as session:
            repository = await session.get(Repository, repository_id)
            if repository is None or repository.owner_id != owner_id:
                return
            repository.status = RepositoryStatus.FAILED
            repository.error_message = message[:1000]
            await session.commit()

        logger.warning("repository_import_error", repository_id=str(repository_id), reason=message)


async def _read_in_chunks(path: Path, size: int = 256 * 1024) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(size):
            yield chunk
