"""Chat history.

Citations are stored on the message rather than recomputed from the answer
text. Retrieval is not deterministic across model or index changes, so
re-deriving them later would eventually produce citations that point somewhere
the original answer never looked — which is worse than having none.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, JSONType, UUIDType

if TYPE_CHECKING:
    from app.models.user import User


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ConversationScope(StrEnum):
    """What the conversation is allowed to search."""

    ALL = "all"
    DOCUMENTS = "documents"
    COLLECTION = "collection"


class Conversation(Entity):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_owner_updated", "owner_id", "updated_at"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    #: Derived from the first question rather than asked for. Nobody titles a
    #: conversation before having it.
    title: Mapped[str] = mapped_column(String(255), default="New conversation")

    scope: Mapped[ConversationScope] = mapped_column(
        SAEnum(ConversationScope, native_enum=False, length=32),
        default=ConversationScope.ALL,
    )
    #: Document ids when scope is DOCUMENTS. JSON rather than a join table:
    #: it is read whole, written whole, and never queried across.
    scope_document_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("collections.id", ondelete="SET NULL"), default=None
    )

    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    owner: Mapped[User] = relationship()
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChatMessage.ordinal",
    )

    def __repr__(self) -> str:
        return f"<Conversation {self.title!r}>"


class ChatMessage(Entity):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_conversation_ordinal", "conversation_id", "ordinal"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    #: Denormalised so a message can be authorised without loading its parent.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    ordinal: Mapped[int] = mapped_column(Integer)
    role: Mapped[MessageRole] = mapped_column(SAEnum(MessageRole, native_enum=False, length=32))
    content: Mapped[str] = mapped_column(Text)

    #: The sources this answer was grounded in: chunk id, document id, title,
    #: page, section and the quoted snippet. Frozen at answer time.
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)

    #: Which model wrote it, so an answer can always be attributed.
    model: Mapped[str | None] = mapped_column(String(128), default=None)
    #: Milliseconds from request to final token, for the analytics in Phase 8.
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage {self.role} #{self.ordinal}>"
