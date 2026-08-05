"""Upload through to a searchable vector.

Marked `slow`: these run a real embedding model against a real Qdrant, which
is the only way to prove the two stores actually agree. Everything cheaper
would assert that a mock was called.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.slow]

PREFIX = "/api/v1"

NOTES = b"""# Engineering Notes

## Authentication

We chose OAuth 2.0 with PKCE for the mobile client, rejecting implicit flow.

## Deployment

The Dockerfile builds on python:3.11-slim and installs tesseract for OCR.
"""


async def sign_up(client: AsyncClient, email: str = "ada@example.com") -> str:
    response = await client.post(
        f"{PREFIX}/auth/register",
        json={"email": email, "password": "correct-horse-battery", "display_name": "Ada"},
    )
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def upload(
    client: AsyncClient, token: str, *, filename: str = "notes.md", content: bytes = NOTES
):
    return await client.post(
        f"{PREFIX}/documents/upload",
        headers=bearer(token),
        files={"file": (filename, content, "text/markdown")},
    )


async def test_upload_becomes_indexed(client: AsyncClient) -> None:
    token = await sign_up(client)
    document_id = (await upload(client, token)).json()["document"]["id"]

    document = (await client.get(f"{PREFIX}/documents/{document_id}", headers=bearer(token))).json()

    assert document["status"] == "indexed"
    assert document["chunk_count"] > 0


async def test_chunks_are_written_to_both_stores(client: AsyncClient, app) -> None:
    """Postgres holds the text and anchors, Qdrant the vectors, joined by id.
    If the two disagree, search returns hits that cannot be rendered."""
    from app.repositories.chunk import ChunkRepository

    token = await sign_up(client)
    body = (await upload(client, token)).json()
    document_id = uuid.UUID(body["document"]["id"])
    owner_id = uuid.UUID(body["document"]["id"])  # replaced below

    container = app.state.container
    async with container.session_factory() as session:
        chunks = await ChunkRepository(session).list_for_document(
            document_id, owner_id=(await _owner_of(session, document_id))
        )
    owner_id = chunks[0].owner_id

    assert chunks, "no chunk rows were written"
    assert all(chunk.embedding_model for chunk in chunks), "vectors not recorded"

    vector_count = await container.vector_store.count(owner_id=owner_id)
    assert vector_count == len(chunks)


async def _owner_of(session, document_id: uuid.UUID) -> uuid.UUID:
    from sqlalchemy import select

    from app.models.document import Document

    result = await session.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one().owner_id


async def test_indexed_content_is_semantically_retrievable(client: AsyncClient, app) -> None:
    """The payoff for all of Phases 3 to 5: a natural-language question finds
    the right passage in a file the user uploaded."""
    from app.services.vectorstore import SearchFilter

    token = await sign_up(client)
    body = (await upload(client, token)).json()

    container = app.state.container
    async with container.session_factory() as session:
        owner_id = await _owner_of(session, uuid.UUID(body["document"]["id"]))

    query_vector = await container.embedding_provider.embed_query(
        "How do we build the container image?"
    )
    hits = await container.vector_store.search(
        query_vector, filters=SearchFilter(owner_id=owner_id), limit=1
    )

    assert hits
    assert "Dockerfile" in hits[0].payload["text"]


async def test_reindexing_does_not_duplicate_vectors(client: AsyncClient, app) -> None:
    token = await sign_up(client)
    body = (await upload(client, token)).json()
    document_id = body["document"]["id"]

    container = app.state.container
    async with container.session_factory() as session:
        owner_id = await _owner_of(session, uuid.UUID(document_id))

    before = await container.vector_store.count(owner_id=owner_id)

    await client.post(f"{PREFIX}/documents/{document_id}/reparse", headers=bearer(token))

    assert await container.vector_store.count(owner_id=owner_id) == before


async def test_deleting_a_document_removes_its_vectors(client: AsyncClient, app) -> None:
    """Qdrant has no foreign key to Postgres, so nothing else would ever clean
    these up — they would remain searchable after the document was gone."""
    token = await sign_up(client)
    body = (await upload(client, token)).json()
    document_id = body["document"]["id"]

    container = app.state.container
    async with container.session_factory() as session:
        owner_id = await _owner_of(session, uuid.UUID(document_id))

    assert await container.vector_store.count(owner_id=owner_id) > 0

    await client.delete(f"{PREFIX}/documents/{document_id}", headers=bearer(token))

    assert await container.vector_store.count(owner_id=owner_id) == 0


async def test_one_users_vectors_are_invisible_to_another(client: AsyncClient, app) -> None:
    from app.services.vectorstore import SearchFilter

    ada = await sign_up(client, "ada@example.com")
    grace = await sign_up(client, "grace@example.com")
    body = (await upload(client, ada)).json()

    container = app.state.container
    async with container.session_factory() as session:
        ada_id = await _owner_of(session, uuid.UUID(body["document"]["id"]))

    grace_id = uuid.UUID(
        (await client.get(f"{PREFIX}/auth/me", headers=bearer(grace))).json()["id"]
    )
    assert ada_id != grace_id

    query_vector = await container.embedding_provider.embed_query("OAuth PKCE")
    assert (
        await container.vector_store.search(
            query_vector, filters=SearchFilter(owner_id=grace_id), limit=10
        )
        == []
    )


async def test_an_image_without_ocr_is_indexed_as_empty_not_failed(
    client: AsyncClient,
) -> None:
    """A photo with no readable text is a legitimate document, not an error."""
    pytest.importorskip("PIL")
    import io

    from PIL import Image

    token = await sign_up(client)
    buffer = io.BytesIO()
    Image.new("RGB", (48, 24), color="white").save(buffer, format="PNG")

    document_id = (
        await client.post(
            f"{PREFIX}/documents/upload",
            headers=bearer(token),
            files={"file": ("photo.png", buffer.getvalue(), "image/png")},
        )
    ).json()["document"]["id"]

    document = (await client.get(f"{PREFIX}/documents/{document_id}", headers=bearer(token))).json()

    assert document["status"] == "indexed"
    assert document["chunk_count"] == 0
    assert document["error_message"] is None
