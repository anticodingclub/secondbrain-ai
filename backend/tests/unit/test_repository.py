from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import Document, DocumentStatus, User
from app.repositories.base import SQLAlchemyRepository


class UserRepository(SQLAlchemyRepository[User]):
    model = User


class DocumentRepository(SQLAlchemyRepository[Document]):
    model = Document


def make_user(email: str = "ada@example.com") -> User:
    return User(email=email, display_name="Ada", hashed_password="not-a-real-hash")


def make_document(
    owner: User, *, title: str = "Offer Letter", content_hash: str = "a" * 64
) -> Document:
    return Document(
        owner_id=owner.id,
        title=title,
        original_filename=f"{title}.pdf",
        mime_type="application/pdf",
        extension="pdf",
        size_bytes=1024,
        content_hash=content_hash,
        storage_key=f"documents/{uuid.uuid4()}.pdf",
    )


async def test_add_assigns_a_uuid_and_timestamps(session: AsyncSession) -> None:
    repo = UserRepository(session)
    user = await repo.add(make_user())

    assert isinstance(user.id, uuid.UUID)
    assert user.created_at is not None
    assert user.is_active is True


async def test_get_returns_none_for_a_missing_id(session: AsyncSession) -> None:
    repo = UserRepository(session)
    assert await repo.get(uuid.uuid4()) is None


async def test_get_or_raise_reports_the_resource_in_details(session: AsyncSession) -> None:
    repo = UserRepository(session)
    missing = uuid.uuid4()

    with pytest.raises(NotFoundError) as excinfo:
        await repo.get_or_raise(missing)

    assert excinfo.value.details == {"resource": "User", "id": str(missing)}
    assert excinfo.value.status_code == 404


async def test_find_one_by_matches_on_arbitrary_columns(session: AsyncSession) -> None:
    repo = UserRepository(session)
    await repo.add(make_user("grace@example.com"))

    found = await repo.find_one_by(email="grace@example.com")
    assert found is not None
    assert found.display_name == "Ada"
    assert await repo.find_one_by(email="nobody@example.com") is None


async def test_list_paginates(session: AsyncSession) -> None:
    repo = UserRepository(session)
    for i in range(5):
        await repo.add(make_user(f"user{i}@example.com"))

    assert len(await repo.list(limit=2)) == 2
    assert len(await repo.list(limit=10, offset=3)) == 2
    assert await repo.count() == 5


async def test_delete_reports_whether_a_row_was_removed(session: AsyncSession) -> None:
    repo = UserRepository(session)
    user = await repo.add(make_user())

    assert await repo.delete(user.id) is True
    assert await repo.delete(uuid.uuid4()) is False


async def test_document_defaults_to_pending_and_zero_chunks(session: AsyncSession) -> None:
    user = await UserRepository(session).add(make_user())
    document = await DocumentRepository(session).add(make_document(user))

    assert document.status is DocumentStatus.PENDING
    assert document.chunk_count == 0
    assert document.doc_metadata == {}


async def test_deleting_a_user_cascades_to_their_documents(session: AsyncSession) -> None:
    users = UserRepository(session)
    documents = DocumentRepository(session)

    user = await users.add(make_user())
    await documents.add(make_document(user))
    assert await documents.count() == 1

    await session.delete(user)
    await session.flush()

    assert await documents.count() == 0
