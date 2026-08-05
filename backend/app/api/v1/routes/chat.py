"""Chat with your documents."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import (
    ChatServiceDep,
    ConversationRepositoryDep,
    CurrentUser,
    MessageRepositoryDep,
    SessionDep,
)
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.conversation import ChatMessage, Conversation, MessageRole
from app.services.chat import derive_title
from app.services.llm.base import LLMUnavailableError

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    #: Omit to start a new conversation.
    conversation_id: uuid.UUID | None = None
    #: Restrict retrieval to specific documents — "chat with this file".
    document_ids: list[uuid.UUID] | None = None


class CitationResponse(BaseModel):
    number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    filename: str
    snippet: str
    page_number: int | None
    section_title: str | None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ordinal: int
    role: MessageRole
    content: str
    citations: list[dict[str, Any]]
    model: str | None
    latency_ms: int | None
    created_at: datetime


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse]


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/ask", summary="Ask a question, streamed")
async def ask(
    payload: AskRequest,
    current_user: CurrentUser,
    session: SessionDep,
    chat_service: ChatServiceDep,
    conversations: ConversationRepositoryDep,
    messages: MessageRepositoryDep,
) -> StreamingResponse:
    """Stream an answer as Server-Sent Events.

    Streaming rather than a single response because a grounded answer over
    several documents takes seconds, and a user watching a spinner that long
    assumes the app has hung.

    Events: `token` for each fragment, `citations` once the answer is
    complete, `done` with the persisted ids, `error` if the model fails
    mid-stream.
    """
    conversation = await _resolve_conversation(payload, current_user.id, conversations, session)
    history = await messages.list_for_conversation(conversation.id, owner_id=current_user.id)

    ordinal = await messages.next_ordinal(conversation.id)
    await messages.add(
        ChatMessage(
            conversation_id=conversation.id,
            owner_id=current_user.id,
            ordinal=ordinal,
            role=MessageRole.USER,
            content=payload.question,
        )
    )
    # Committed before streaming starts: the response body is already being
    # written by the time the generator runs, so the request transaction is
    # no longer a safe place to hold anything.
    await session.commit()

    conversation_id = conversation.id
    owner_id = current_user.id
    question = payload.question

    async def event_stream() -> AsyncIterator[str]:
        yield _sse("start", {"conversation_id": str(conversation_id)})

        try:
            final = None
            async for token, state in chat_service.answer(
                question=question,
                owner_id=owner_id,
                conversation=conversation,
                history=history,
                document_ids=payload.document_ids,
            ):
                if token:
                    yield _sse("token", {"text": token})
                final = state

            if final is None:
                return

            yield _sse(
                "citations",
                {"citations": [citation.as_dict() for citation in final.citations]},
            )

            message_id = await _persist_answer(
                chat_service, conversation_id, owner_id, ordinal + 1, final
            )
            yield _sse(
                "done",
                {
                    "message_id": str(message_id),
                    "conversation_id": str(conversation_id),
                    "latency_ms": final.latency_ms,
                },
            )
        except LLMUnavailableError as exc:
            # Surfaced as an event rather than a status code: the response has
            # already begun, so the status line is long gone.
            logger.warning("llm_unavailable", provider=exc.provider, detail=exc.detail)
            yield _sse(
                "error",
                {
                    "message": (
                        f"The {exc.provider} model is unavailable. "
                        "Start it, or configure a different provider in settings."
                    ),
                    "provider": exc.provider,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("chat_stream_failed")
            yield _sse("error", {"message": f"The answer failed midway: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Stops nginx buffering the stream into one delayed blob.
            "X-Accel-Buffering": "no",
        },
    )


async def _resolve_conversation(
    payload: AskRequest,
    owner_id: uuid.UUID,
    conversations: ConversationRepositoryDep,
    session: SessionDep,
) -> Conversation:
    if payload.conversation_id is not None:
        existing = await conversations.get_for_owner(payload.conversation_id, owner_id=owner_id)
        if existing is None:
            raise NotFoundError("Conversation not found.")
        existing.message_count += 2  # the question and its answer
        return existing

    conversation = Conversation(
        owner_id=owner_id,
        title=derive_title(payload.question),
        scope_document_ids=[str(doc) for doc in payload.document_ids or []],
        message_count=2,
    )
    await conversations.add(conversation)
    await session.flush()
    return conversation


async def _persist_answer(
    chat_service: ChatServiceDep,
    conversation_id: uuid.UUID,
    owner_id: uuid.UUID,
    ordinal: int,
    final: Any,
) -> uuid.UUID:
    """Save the assistant turn in its own session.

    The request transaction was committed before streaming began, so this
    needs a fresh one — and it must not fail silently, or the user sees an
    answer that is gone when they reload.
    """
    return await chat_service.persist_answer(
        conversation_id=conversation_id,
        owner_id=owner_id,
        ordinal=ordinal,
        text=final.text,
        citations=[citation.as_dict() for citation in final.citations],
        latency_ms=final.latency_ms,
    )


@router.get("/conversations", summary="List conversations")
async def list_conversations(
    current_user: CurrentUser, conversations: ConversationRepositoryDep
) -> list[ConversationResponse]:
    rows = await conversations.list_for_owner(owner_id=current_user.id)
    return [ConversationResponse.model_validate(row) for row in rows]


async def _owned_conversation(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    conversations: ConversationRepositoryDep,
) -> Conversation:
    conversation = await conversations.get_for_owner(conversation_id, owner_id=current_user.id)
    if conversation is None:
        raise NotFoundError("Conversation not found.")
    return conversation


OwnedConversation = Annotated[Conversation, Depends(_owned_conversation)]


@router.get("/conversations/{conversation_id}", summary="One conversation")
async def get_conversation(
    conversation: OwnedConversation,
    current_user: CurrentUser,
    messages: MessageRepositoryDep,
) -> ConversationDetailResponse:
    rows = await messages.list_for_conversation(conversation.id, owner_id=current_user.id)
    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        message_count=conversation.message_count,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageResponse.model_validate(row) for row in rows],
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation",
)
async def delete_conversation(
    conversation: OwnedConversation, conversations: ConversationRepositoryDep
) -> None:
    await conversations.delete(conversation.id)
