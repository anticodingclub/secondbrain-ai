"""Conversation persistence."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.conversation import ChatMessage, Conversation
from app.repositories.base import SQLAlchemyRepository


class ConversationRepository(SQLAlchemyRepository[Conversation]):
    model = Conversation

    async def get_for_owner(
        self, conversation_id: uuid.UUID, *, owner_id: uuid.UUID
    ) -> Conversation | None:
        return await self.find_one_by(id=conversation_id, owner_id=owner_id)

    async def list_for_owner(
        self, *, owner_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> Sequence[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.owner_id == owner_id)
            # Most recently *used*, not created: a conversation returned to
            # after a week belongs at the top.
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_for_owner(self, owner_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Conversation).where(Conversation.owner_id == owner_id)
        )
        return int(result.scalar_one())


class ChatMessageRepository(SQLAlchemyRepository[ChatMessage]):
    model = ChatMessage

    async def list_for_conversation(
        self, conversation_id: uuid.UUID, *, owner_id: uuid.UUID
    ) -> Sequence[ChatMessage]:
        result = await self.session.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.owner_id == owner_id,
            )
            .order_by(ChatMessage.ordinal)
        )
        return result.scalars().all()

    async def next_ordinal(self, conversation_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.max(ChatMessage.ordinal), -1)).where(
                ChatMessage.conversation_id == conversation_id
            )
        )
        return int(result.scalar_one()) + 1
