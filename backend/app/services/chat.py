"""Retrieval-augmented answering.

Retrieves passages, gives them to the model as numbered sources, and streams
back an answer that cites them.

The prompt is the load-bearing part of this file. A model handed documents
will happily blend them with what it already believes, and the result is
fluent, plausible and unattributable — the exact failure a personal search
engine cannot afford, because the user asked precisely because they did not
remember. So the instructions are blunt: answer only from the sources, cite
every claim, and say so when the sources do not contain the answer.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.models.conversation import ChatMessage, Conversation, MessageRole
from app.services.llm.base import LLMProvider, Message, Role
from app.services.retrieval import RetrievalService, SearchHit, SearchQuery

logger = get_logger(__name__)

#: Sources given to the model. Beyond roughly this many, a small local model
#: starts losing the earlier ones in the middle of its context, and recall
#: gets worse rather than better.
MAX_SOURCES = 8

#: Prior turns replayed for follow-up questions. Enough for "and what about
#: the salary?" to resolve, without spending the window on old answers.
MAX_HISTORY_MESSAGES = 6

SYSTEM_PROMPT = """You are SecondBrain, a search assistant answering strictly \
from the user's own documents.

Rules:
1. Answer using ONLY the numbered sources below. Do not use outside knowledge.
2. Cite every factual claim with its source number in square brackets, like [2].
3. If the sources do not contain the answer, say so plainly and state what is \
missing. Do not guess, and do not fill gaps from general knowledge.
4. Quote exact figures, dates and identifiers as they appear. Never round or \
paraphrase a number.
5. Be concise. Two or three sentences unless the question needs more.

The user cannot see the sources. Refer to documents by name, not by number, \
in your prose — the bracketed numbers are for linking only."""


@dataclass(frozen=True, slots=True)
class Citation:
    number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    filename: str
    snippet: str
    page_number: int | None = None
    section_title: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "document_title": self.document_title,
            "filename": self.filename,
            "snippet": self.snippet,
            "page_number": self.page_number,
            "section_title": self.section_title,
        }


@dataclass(slots=True)
class AnswerStream:
    """A streaming answer, plus what it was grounded in."""

    citations: list[Citation] = field(default_factory=list)
    text: str = ""
    latency_ms: int = 0


class ChatService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        session_factory: async_sessionmaker[AsyncSession],
        retrieval: RetrievalService,
        llm: LLMProvider,
    ) -> None:
        self._session = session
        self._session_factory = session_factory
        self._retrieval = retrieval
        self._llm = llm

    async def persist_answer(
        self,
        *,
        conversation_id: uuid.UUID,
        owner_id: uuid.UUID,
        ordinal: int,
        text: str,
        citations: list[dict[str, object]],
        latency_ms: int,
    ) -> uuid.UUID:
        """Save a completed answer in its own transaction.

        The request transaction is committed before streaming begins, so by
        the time an answer is complete there is none left to write into.
        """
        async with self._session_factory() as session:
            message = ChatMessage(
                conversation_id=conversation_id,
                owner_id=owner_id,
                ordinal=ordinal,
                role=MessageRole.ASSISTANT,
                content=text,
                citations=citations,
                model=self._llm.model,
                latency_ms=latency_ms,
            )
            session.add(message)
            await session.flush()
            message_id = message.id

            # Bumping the parent keeps "most recently used" ordering honest in
            # the conversation list.
            conversation = await session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.updated_at = datetime.now(UTC)

            await session.commit()
            return message_id

    async def answer(
        self,
        *,
        question: str,
        owner_id: uuid.UUID,
        conversation: Conversation,
        history: Sequence[ChatMessage] = (),
        document_ids: Sequence[uuid.UUID] | None = None,
        top_k: int = MAX_SOURCES,
    ) -> AsyncIterator[tuple[str, AnswerStream]]:
        """Yield answer text as it arrives, with the accumulating state.

        The final yield carries the complete text, the citations actually
        referenced, and the latency — everything the caller needs to persist
        the turn.
        """
        started = time.perf_counter()
        state = AnswerStream()

        hits = await self._retrieval.search(
            SearchQuery(
                text=question,
                limit=top_k,
                document_ids=list(document_ids) if document_ids else None,
            ),
            owner_id=owner_id,
        )

        if not hits:
            # Answered without calling the model at all. There is nothing to
            # ground an answer in, and asking anyway invites exactly the
            # confident invention the prompt exists to prevent.
            state.text = (
                "I could not find anything in your documents about that. "
                "Try rephrasing, or upload the document you have in mind."
            )
            state.latency_ms = int((time.perf_counter() - started) * 1000)
            yield state.text, state
            return

        sources = [_citation_for(index, hit) for index, hit in enumerate(hits, start=1)]
        messages = _build_messages(question, hits, history)

        parts: list[str] = []
        async for chunk in self._llm.stream(messages):
            if chunk.text:
                parts.append(chunk.text)
                state.text = "".join(parts)
                yield chunk.text, state

        # Only the sources the answer actually cited are kept. Listing all
        # eight when the model used two turns citations into decoration and
        # trains the user to ignore them.
        referenced = _referenced_numbers(state.text)
        state.citations = [source for source in sources if source.number in referenced] or (
            sources[:3]
        )
        state.latency_ms = int((time.perf_counter() - started) * 1000)

        logger.info(
            "answer_generated",
            conversation_id=str(conversation.id),
            sources=len(sources),
            cited=len(state.citations),
            latency_ms=state.latency_ms,
        )
        yield "", state


def _citation_for(number: int, hit: SearchHit) -> Citation:
    return Citation(
        number=number,
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        document_title=hit.document_title,
        filename=hit.filename,
        snippet=hit.snippet,
        page_number=hit.page_number,
        section_title=hit.section_title,
    )


def _build_messages(
    question: str, hits: Sequence[SearchHit], history: Sequence[ChatMessage]
) -> list[Message]:
    messages = [Message(role=Role.SYSTEM, content=SYSTEM_PROMPT)]

    # Prior turns come before the sources so the freshest, most relevant
    # material sits closest to the question — models weight the end of their
    # context most heavily.
    for past in list(history)[-MAX_HISTORY_MESSAGES:]:
        messages.append(
            Message(
                role=Role.USER if past.role is MessageRole.USER else Role.ASSISTANT,
                content=past.content,
            )
        )

    messages.append(Message(role=Role.USER, content=_format_sources(hits, question)))
    return messages


def _format_sources(hits: Sequence[SearchHit], question: str) -> str:
    blocks: list[str] = []
    for number, hit in enumerate(hits, start=1):
        location = " · ".join(
            part
            for part in (
                hit.document_title or hit.filename,
                f"page {hit.page_number}" if hit.page_number else None,
                hit.section_title,
            )
            if part
        )
        blocks.append(f"[{number}] {location}\n{hit.text.strip()}")

    # Joined outside the f-string: a backslash inside an f-string expression
    # is a syntax error on Python 3.11, which this project supports.
    body = "\n\n".join(blocks)
    return f"Sources:\n\n{body}\n\nQuestion: {question}"


_CITATION_PATTERN = re.compile(r"\[(\d{1,2})(?:\s*,\s*(\d{1,2}))*\]")


def _referenced_numbers(text: str) -> set[int]:
    """Every source number the answer cites, including `[1, 3]` forms."""
    numbers: set[int] = set()
    for match in re.finditer(r"\[([\d\s,]+)\]", text):
        for token in match.group(1).split(","):
            token = token.strip()
            if token.isdigit():
                numbers.add(int(token))
    return numbers


def derive_title(question: str, *, limit: int = 60) -> str:
    """A conversation title from its first question.

    Nobody titles a conversation before having it, so it is taken from the
    question and trimmed at a word boundary.
    """
    cleaned = " ".join(question.split())
    if len(cleaned) <= limit:
        return cleaned or "New conversation"
    return cleaned[:limit].rsplit(" ", 1)[0] + "…"
