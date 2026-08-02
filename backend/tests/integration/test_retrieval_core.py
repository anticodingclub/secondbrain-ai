"""End-to-end test of the retrieval core: embed -> upsert -> search.

This is the only test that runs a real embedding model against a real Qdrant.
Everything else can pass while retrieval is silently broken — a dimension
mismatch, a missing query instruction prefix, or a filter that does not
actually filter would all slip through unit tests.

Marked ``slow`` because the first run downloads ~130 MB of model weights:

    pytest -m slow                 # just this
    pytest -m "not slow"           # everything else
"""

from __future__ import annotations

import uuid

import pytest

from app.core.config import Settings
from app.services.embeddings import build_embedding_provider
from app.services.vectorstore import SearchFilter, VectorRecord, build_vector_store

pytestmark = [pytest.mark.integration, pytest.mark.slow]

CORPUS = [
    "The internship offer letter from Acme Corp confirms a start date of June 3rd.",
    "Our backend exposes POST /api/v1/documents/upload for multipart file uploads.",
    "Meeting notes: we decided to use OAuth 2.0 with PKCE for the mobile client.",
    "The Dockerfile builds on python:3.11-slim and installs tesseract for OCR.",
    "Recipe: whisk three eggs with butter over low heat until softly scrambled.",
]

#: The queries from the product brief, mapped to the chunk that should win.
QUERIES = [
    ("Where is my internship offer letter?", 0),
    ("What was the API endpoint in my backend project?", 1),
    ("Show notes where I discussed OAuth.", 2),
    ("Find every mention of Docker.", 3),
]


@pytest.fixture
async def indexed_corpus(settings: Settings):
    """Embed the corpus into a throwaway collection owned by one user."""
    embedder = build_embedding_provider(settings)
    store = build_vector_store(settings)
    await store.ensure_collection(dimensions=embedder.dimensions)

    owner = uuid.uuid4()
    chunk_ids = [uuid.uuid4() for _ in CORPUS]
    vectors = await embedder.embed_documents(CORPUS)

    await store.upsert(
        [
            VectorRecord(
                id=chunk_id,
                vector=vector,
                payload={
                    "owner_id": str(owner),
                    "document_id": str(uuid.uuid4()),
                    "extension": "md",
                    "text": text,
                },
            )
            for chunk_id, vector, text in zip(chunk_ids, vectors, CORPUS, strict=True)
        ]
    )

    yield embedder, store, owner, chunk_ids

    await embedder.aclose()
    await store.aclose()


async def test_embeddings_match_the_configured_dimensions(settings: Settings) -> None:
    embedder = build_embedding_provider(settings)
    vectors = await embedder.embed_documents(CORPUS[:2])

    assert len(vectors) == 2
    assert all(len(v) == embedder.dimensions for v in vectors)
    await embedder.aclose()


@pytest.mark.parametrize(("question", "expected_index"), QUERIES)
async def test_natural_language_query_retrieves_the_right_chunk(
    indexed_corpus, question: str, expected_index: int
) -> None:
    embedder, store, owner, chunk_ids = indexed_corpus

    query_vector = await embedder.embed_query(question)
    hits = await store.search(query_vector, filters=SearchFilter(owner_id=owner), limit=1)

    assert hits, f"no results for {question!r}"
    assert hits[0].id == chunk_ids[expected_index], (
        f"{question!r} retrieved {hits[0].payload['text']!r}"
    )
    assert hits[0].payload["text"] == CORPUS[expected_index]


async def test_search_is_scoped_to_the_owner(indexed_corpus) -> None:
    """The tenant boundary. A different owner must see nothing at all."""
    embedder, store, _owner, _chunk_ids = indexed_corpus

    query_vector = await embedder.embed_query(QUERIES[0][0])
    hits = await store.search(query_vector, filters=SearchFilter(owner_id=uuid.uuid4()), limit=10)

    assert hits == []


async def test_metadata_filters_narrow_the_result_set(indexed_corpus) -> None:
    embedder, store, owner, _chunk_ids = indexed_corpus

    query_vector = await embedder.embed_query("Docker")

    assert await store.search(
        query_vector, filters=SearchFilter(owner_id=owner, extensions=["md"]), limit=10
    )
    assert (
        await store.search(
            query_vector, filters=SearchFilter(owner_id=owner, extensions=["pdf"]), limit=10
        )
        == []
    )


async def test_upsert_replaces_a_chunk_in_place(indexed_corpus) -> None:
    """Re-indexing a changed document must not duplicate its vectors."""
    embedder, store, owner, chunk_ids = indexed_corpus
    before = await store.count(owner_id=owner)

    replacement = "The offer letter was superseded; the new start date is July 15th."
    [vector] = await embedder.embed_documents([replacement])
    await store.upsert(
        [
            VectorRecord(
                id=chunk_ids[0],
                vector=vector,
                payload={
                    "owner_id": str(owner),
                    "document_id": str(uuid.uuid4()),
                    "extension": "md",
                    "text": replacement,
                },
            )
        ]
    )

    assert await store.count(owner_id=owner) == before

    query_vector = await embedder.embed_query("When does my internship start?")
    hits = await store.search(query_vector, filters=SearchFilter(owner_id=owner), limit=1)
    assert hits[0].payload["text"] == replacement
