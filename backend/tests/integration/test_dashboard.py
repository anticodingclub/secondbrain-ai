"""Dashboard statistics."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.slow]

PREFIX = "/api/v1"

NOTES = b"""# Notes

## Deployment

The Dockerfile builds on python:3.11-slim.
"""


async def sign_up(client: AsyncClient, email: str = "ada@example.com") -> str:
    response = await client.post(
        f"{PREFIX}/auth/register",
        json={"email": email, "password": "correct-horse-battery", "display_name": "Ada"},
    )
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def upload(client: AsyncClient, token: str, name: str, body: bytes = NOTES) -> None:
    await client.post(
        f"{PREFIX}/documents/upload",
        headers=bearer(token),
        files={"file": (name, body, "text/markdown")},
    )


async def stats(client: AsyncClient, token: str) -> dict:
    response = await client.get(f"{PREFIX}/dashboard", headers=bearer(token))
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_empty_library_reports_zeroes_not_an_error(client: AsyncClient) -> None:
    token = await sign_up(client)

    body = await stats(client, token)

    assert body["document_count"] == 0
    assert body["chunk_count"] == 0
    assert body["vector_count"] == 0
    # A library with nothing in it is fully indexed, not 0% indexed.
    assert body["indexing_progress"] == 1.0


async def test_counts_reflect_uploaded_documents(client: AsyncClient) -> None:
    token = await sign_up(client)
    await upload(client, token, "notes.md")
    await upload(client, token, "other.md", b"# Other\n\nA different document entirely.\n")

    body = await stats(client, token)

    assert body["document_count"] == 2
    assert body["indexed_count"] == 2
    assert body["chunk_count"] > 0
    assert body["total_bytes"] > 0
    assert body["indexing_progress"] == 1.0


async def test_vector_count_comes_from_the_vector_store(client: AsyncClient) -> None:
    """Counted from Qdrant, not inferred from chunk rows — the two drifting
    apart is exactly the failure this number exists to surface."""
    token = await sign_up(client)
    await upload(client, token, "notes.md")

    body = await stats(client, token)

    assert body["vector_count"] == body["chunk_count"]


async def test_a_failed_document_is_counted_as_failed(client: AsyncClient) -> None:
    token = await sign_up(client)
    await client.post(
        f"{PREFIX}/documents/upload",
        headers=bearer(token),
        files={"file": ("broken.pdf", b"%PDF-1.7\nnot a pdf", "application/pdf")},
    )

    body = await stats(client, token)

    assert body["failed_count"] == 1
    assert body["indexed_count"] == 0
    assert body["indexing_progress"] == 0.0


async def test_documents_are_grouped_by_type(client: AsyncClient) -> None:
    token = await sign_up(client)
    await upload(client, token, "a.md")
    await upload(client, token, "b.txt", b"Plain text content here.\n")

    body = await stats(client, token)

    by_extension = {row["label"]: row["count"] for row in body["by_extension"]}
    assert by_extension == {"md": 1, "txt": 1}


# ── Search analytics ─────────────────────────────────────────────────────────


async def test_searches_are_recorded(client: AsyncClient) -> None:
    token = await sign_up(client)
    await upload(client, token, "notes.md")

    await client.post(f"{PREFIX}/search", headers=bearer(token), json={"query": "Docker"})

    body = await stats(client, token)

    assert body["search_count"] == 1
    assert body["searches_last_7_days"] == 1
    assert body["recent_searches"][0]["query"] == "Docker"
    assert body["recent_searches"][0]["hit_count"] > 0


async def test_repeated_queries_aggregate_regardless_of_case_or_spacing(
    client: AsyncClient,
) -> None:
    token = await sign_up(client)
    await upload(client, token, "notes.md")

    for query in ("Docker", "docker", "  DOCKER  "):
        await client.post(f"{PREFIX}/search", headers=bearer(token), json={"query": query})

    body = await stats(client, token)

    top = {row["label"]: row["count"] for row in body["top_queries"]}
    assert top == {"docker": 3}


async def test_a_search_that_finds_nothing_is_still_recorded(
    client: AsyncClient,
) -> None:
    """Queries returning nothing are the most useful signal there is — they
    say what the library is missing."""
    token = await sign_up(client)
    await upload(client, token, "notes.md")

    await client.post(
        f"{PREFIX}/search",
        headers=bearer(token),
        json={"query": "zzzz nonexistent", "mode": "keyword"},
    )

    body = await stats(client, token)

    assert body["search_count"] == 1
    assert body["recent_searches"][0]["hit_count"] == 0


async def test_recent_documents_are_newest_first(client: AsyncClient) -> None:
    token = await sign_up(client)
    for name in ("first.md", "second.md", "third.md"):
        await upload(client, token, name, f"# {name}\n\nContent of {name} here.\n".encode())

    body = await stats(client, token)

    assert [row["title"] for row in body["recent_documents"]][:3] == [
        "third",
        "second",
        "first",
    ]


# ── Isolation ────────────────────────────────────────────────────────────────


async def test_statistics_never_include_another_users_data(
    client: AsyncClient,
) -> None:
    ada = await sign_up(client, "ada@example.com")
    grace = await sign_up(client, "grace@example.com")

    await upload(client, ada, "notes.md")
    await client.post(f"{PREFIX}/search", headers=bearer(ada), json={"query": "Docker"})

    body = await stats(client, grace)

    assert body["document_count"] == 0
    assert body["chunk_count"] == 0
    assert body["vector_count"] == 0
    assert body["search_count"] == 0
    assert body["recent_documents"] == []


async def test_dashboard_requires_authentication(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/dashboard")
    assert response.status_code == 401
