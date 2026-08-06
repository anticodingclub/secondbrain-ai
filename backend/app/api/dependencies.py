"""FastAPI dependency providers.

These are thin adapters from the container to the request scope. Route handlers
annotate the interface they need; they never construct it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.container import Container
from app.core.exceptions import AuthenticationError
from app.core.logging import user_id_var
from app.models.user import User
from app.repositories.chunk import ChunkRepository
from app.repositories.conversation import ChatMessageRepository, ConversationRepository
from app.repositories.document import DocumentRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.services.analytics import AnalyticsService
from app.services.auth import AuthService
from app.services.chat import ChatService
from app.services.embeddings import EmbeddingProvider
from app.services.indexing import IndexingService
from app.services.parsing.pipeline import ParsingService
from app.services.repositories import RepositoryImportService
from app.services.retrieval import RetrievalService
from app.services.storage import ObjectStorage
from app.services.uploads import UploadService
from app.services.vectorstore import VectorStore


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def get_settings_dep(container: Annotated[Container, Depends(get_container)]) -> Settings:
    return container.settings


def get_vector_store(container: Annotated[Container, Depends(get_container)]) -> VectorStore:
    return container.vector_store


def get_embedding_provider(
    container: Annotated[Container, Depends(get_container)],
) -> EmbeddingProvider:
    return container.embedding_provider


async def get_session(
    container: Annotated[Container, Depends(get_container)],
) -> AsyncIterator[AsyncSession]:
    """One transaction per request: commit on success, roll back on any error.

    Handlers therefore never call ``commit()``. A handler that raises after a
    partial write leaves nothing behind.
    """
    session = container.session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


ContainerDep = Annotated[Container, Depends(get_container)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
VectorStoreDep = Annotated[VectorStore, Depends(get_vector_store)]
EmbeddingProviderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]


# ── Authentication ───────────────────────────────────────────────────────────

#: auto_error=False so a missing header produces our own error envelope rather
#: than Starlette's bare {"detail": ...}.
_bearer_scheme = HTTPBearer(auto_error=False, description="Access token")


def get_auth_service(session: SessionDep, settings: SettingsDep) -> AuthService:
    return AuthService(
        session=session,
        users=UserRepository(session),
        refresh_tokens=RefreshTokenRepository(session),
        settings=settings,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    auth_service: AuthServiceDep,
) -> User:
    """Resolve the caller from the Bearer access token.

    This is the tenant boundary for the entire application. Every route that
    touches user data depends on it, and every query downstream filters by the
    id it returns — never by an id taken from the request body, which the
    caller controls.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Not authenticated.")

    user = await auth_service.resolve_access_token(credentials.credentials)
    user_id_var.set(str(user.id))  # every subsequent log line carries the user
    return user


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    auth_service: AuthServiceDep,
) -> User | None:
    """Like `get_current_user` but tolerates anonymity, for routes that adapt."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        user = await auth_service.resolve_access_token(credentials.credentials)
    except AuthenticationError:
        return None
    user_id_var.set(str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


# ── Documents ────────────────────────────────────────────────────────────────


def get_object_storage(container: ContainerDep) -> ObjectStorage:
    return container.object_storage


def get_document_repository(session: SessionDep) -> DocumentRepository:
    return DocumentRepository(session)


DocumentRepositoryDep = Annotated[DocumentRepository, Depends(get_document_repository)]
ObjectStorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]


def get_upload_service(
    session: SessionDep,
    documents: DocumentRepositoryDep,
    storage: ObjectStorageDep,
    settings: SettingsDep,
) -> UploadService:
    return UploadService(session=session, documents=documents, storage=storage, settings=settings)


UploadServiceDep = Annotated[UploadService, Depends(get_upload_service)]


def get_parsing_service(container: ContainerDep) -> ParsingService:
    """Built from the container's session *factory*, not the request session.

    Parsing runs after the response is sent, by which point the request's
    transaction is closed. It must open its own.
    """
    return ParsingService(
        session_factory=container.session_factory,
        storage=container.object_storage,
        registry=container.parser_registry,
    )


ParsingServiceDep = Annotated[ParsingService, Depends(get_parsing_service)]


def get_indexing_service(container: ContainerDep) -> IndexingService:
    return IndexingService(
        session_factory=container.session_factory,
        parsing=get_parsing_service(container),
        chunker=container.chunker,
        embedder=container.embedding_provider,
        vector_store=container.vector_store,
        settings=container.settings,
    )


IndexingServiceDep = Annotated[IndexingService, Depends(get_indexing_service)]


def get_chunk_repository(session: SessionDep) -> ChunkRepository:
    return ChunkRepository(session)


ChunkRepositoryDep = Annotated[ChunkRepository, Depends(get_chunk_repository)]


def get_retrieval_service(
    session: SessionDep,
    embedder: EmbeddingProviderDep,
    vector_store: VectorStoreDep,
) -> RetrievalService:
    return RetrievalService(session=session, embedder=embedder, vector_store=vector_store)


RetrievalServiceDep = Annotated[RetrievalService, Depends(get_retrieval_service)]


# ── Chat ─────────────────────────────────────────────────────────────────────


def get_conversation_repository(session: SessionDep) -> ConversationRepository:
    return ConversationRepository(session)


def get_message_repository(session: SessionDep) -> ChatMessageRepository:
    return ChatMessageRepository(session)


ConversationRepositoryDep = Annotated[ConversationRepository, Depends(get_conversation_repository)]
MessageRepositoryDep = Annotated[ChatMessageRepository, Depends(get_message_repository)]


def get_chat_service(
    session: SessionDep, container: ContainerDep, retrieval: RetrievalServiceDep
) -> ChatService:
    return ChatService(
        session=session,
        session_factory=container.session_factory,
        retrieval=retrieval,
        llm=container.llm_provider,
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


# ── Analytics ────────────────────────────────────────────────────────────────


def get_analytics_service(session: SessionDep) -> AnalyticsService:
    return AnalyticsService(session=session)


AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]


# ── Repositories ─────────────────────────────────────────────────────────────


def get_repository_import_service(container: ContainerDep) -> RepositoryImportService:
    return RepositoryImportService(
        session_factory=container.session_factory,
        storage=container.object_storage,
        parsing=get_parsing_service(container),
        indexing=get_indexing_service(container),
    )


RepositoryImportServiceDep = Annotated[
    RepositoryImportService, Depends(get_repository_import_service)
]
